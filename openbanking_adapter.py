"""
Open Banking Adapter — BKM / Berlin Group NextGenPSD2 uyumlu

Çalışma modları (.env OB_MODE değişkeni):
  mock    → sentetik işlem verileri, API çağrısı yok (varsayılan)
  sandbox → Berlin Group referans sandbox (https://sandbox.openbankingplatform.com)
  live    → gerçek banka OAuth 2.0 API (OB_BASE_URL + OB_CLIENT_ID/SECRET gerekir)

Desteklenen endpointler:
  GET /accounts            → IBAN listesi
  GET /accounts/{id}/balances    → anlık bakiye
  GET /accounts/{id}/transactions → işlem geçmişi (son 12 ay)

Zenginleştirme (CreditScorer entegrasyonu):
  - avg_monthly_balance → future_score iyileştirmesi
  - cashflow_regularity → historical_score iyileştirmesi
  - overdraft_count     → ceza
"""

import os
import json
import math
import logging
import random
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

_OB_MODE = os.getenv('OB_MODE', 'mock')
_OB_CACHE_DAYS = int(os.getenv('OB_CACHE_DAYS', '7'))   # 7 gün TTL
_OB_BLEND_WEIGHT = 0.25   # Open Banking katkısı skor zenginleştirmesinde


class OpenBankingAdapter:
    """
    Open Banking hesap ve cashflow verisi sağlayıcısı.

    Mock modda müşteri IBAN'ına göre deterministik sentetik veri üretir,
    böylece test ortamında tutarlı sonuçlar elde edilir.
    """

    def __init__(self, config: Optional[dict] = None):
        cfg = config or {}
        self.mode = cfg.get('OB_MODE', _OB_MODE)
        self.base_url = cfg.get('OB_BASE_URL', os.getenv('OB_BASE_URL', ''))
        self.client_id = cfg.get('OB_CLIENT_ID', os.getenv('OB_CLIENT_ID', ''))
        self.client_secret = cfg.get('OB_CLIENT_SECRET', os.getenv('OB_CLIENT_SECRET', ''))
        self.cache_days = int(cfg.get('OB_CACHE_DAYS', _OB_CACHE_DAYS))
        self._access_token: Optional[str] = None

    # ──────────────────────────────────────────────────────────────
    # Ana sorgu metodu
    # ──────────────────────────────────────────────────────────────

    def get_account_summary(self, iban: str, customer_id: int, tenant_id: int,
                            session, consent_given: bool = True):
        """
        IBAN için Open Banking özeti döner. Cache geçerliyse API atlanır.
        Returns: OpenBankingRecord nesnesi
        """
        from database import OpenBankingRecord

        cached = (
            session.query(OpenBankingRecord)
            .filter(
                OpenBankingRecord.iban == iban,
                OpenBankingRecord.expires_at > datetime.utcnow(),
            )
            .order_by(OpenBankingRecord.fetched_at.desc())
            .first()
        )
        if cached:
            logger.debug('Open Banking cache hit: %s', iban)
            return cached

        data = self._fetch(iban)
        record = self._build_record(iban, data, customer_id, tenant_id, consent_given)
        session.add(record)
        session.commit()
        logger.info('Open Banking kaydedildi: %s (kaynak: %s)', iban, self.mode)
        return record

    # ──────────────────────────────────────────────────────────────
    # Skor zenginleştirme — CreditScorer çağırır
    # ──────────────────────────────────────────────────────────────

    @staticmethod
    def enrich_scores(historical_score: float, future_score: float,
                      record) -> tuple[float, float]:
        """
        Open Banking cashflow verisiyle historical + future skorlarını zenginleştirir.

        Katkı ağırlığı: %25 (KKB'den daha az — OB verisi ikincil kaynak)

        Döner: (yeni_historical, yeni_future)
        """
        if record is None:
            return historical_score, future_score

        w = _OB_BLEND_WEIGHT

        # Historical: cashflow düzenliliği (0-1) × 100 puan
        ob_historical = record.cashflow_regularity * 100.0
        # Overdraft cezası: her gün -1 puan, max -30
        overdraft_penalty = min(record.overdraft_count or 0, 30)
        ob_historical = max(0, ob_historical - overdraft_penalty)
        new_historical = round(historical_score * (1 - w) + ob_historical * w, 2)

        # Future: ortalama bakiye → talep edilen krediye oran
        # avg_monthly_balance > 0 ise likidite sinyali olarak %25 katkı
        if record.avg_monthly_balance and record.avg_monthly_balance > 0:
            # 500k TL+ bakiye → tam 100 puan; daha az orantılı
            ob_future = min(100.0, (record.avg_monthly_balance / 500_000.0) * 100.0)
        else:
            ob_future = 50.0  # nötr
        new_future = round(future_score * (1 - w) + ob_future * w, 2)

        return new_historical, new_future

    # ──────────────────────────────────────────────────────────────
    # Fetch metodları
    # ──────────────────────────────────────────────────────────────

    def _fetch(self, iban: str) -> dict:
        if self.mode == 'live':
            return self._fetch_live(iban)
        if self.mode == 'sandbox':
            return self._fetch_sandbox(iban)
        return self._fetch_mock(iban)

    def _fetch_mock(self, iban: str) -> dict:
        """IBAN'ın hash'inden deterministik sentetik veri üretir."""
        seed = sum(ord(c) for c in iban)
        rng = random.Random(seed)

        avg_balance = rng.uniform(50_000, 2_000_000)
        inflow = avg_balance * rng.uniform(0.08, 0.20)
        outflow = inflow * rng.uniform(0.85, 1.05)
        overdraft = rng.randint(0, 5)
        regularity = round(1.0 - rng.uniform(0, 0.3), 3)

        return {
            'avg_monthly_balance': round(avg_balance, 2),
            'avg_monthly_inflow': round(inflow, 2),
            'avg_monthly_outflow': round(outflow, 2),
            'overdraft_count': overdraft,
            'cashflow_regularity': regularity,
            'bank_count': rng.randint(1, 3),
        }

    def _fetch_sandbox(self, iban: str) -> dict:
        """Berlin Group referans sandbox — hesap listesi + işlemler."""
        try:
            import requests
        except ImportError:
            raise RuntimeError('requests kurulu değil: pip install requests')

        token = self._get_token_sandbox()
        headers = {'Authorization': f'Bearer {token}', 'X-Request-ID': iban}
        base = self.base_url or 'https://sandbox.openbankingplatform.com/v1'

        try:
            accounts_resp = requests.get(f'{base}/accounts', headers=headers, timeout=10)
            accounts_resp.raise_for_status()
            accounts = accounts_resp.json().get('accounts', [])

            target = next((a for a in accounts if a.get('iban') == iban), accounts[0] if accounts else None)
            if not target:
                return self._fetch_mock(iban)

            acc_id = target['resourceId']
            txn_resp = requests.get(
                f'{base}/accounts/{acc_id}/transactions',
                headers=headers,
                params={'dateFrom': (datetime.utcnow() - timedelta(days=365)).strftime('%Y-%m-%d')},
                timeout=10,
            )
            txn_resp.raise_for_status()
            return self._parse_transactions(txn_resp.json())
        except Exception as e:
            logger.warning('Sandbox sorgu hatası, mock fallback: %s', e)
            return self._fetch_mock(iban)

    def _fetch_live(self, iban: str) -> dict:
        """Gerçek banka API — OAuth 2.0 client credentials akışı."""
        if not self.base_url or not self.client_id:
            raise ValueError('OB_BASE_URL, OB_CLIENT_ID ve OB_CLIENT_SECRET .env dosyasında tanımlı olmalı')
        try:
            import requests
        except ImportError:
            raise RuntimeError('requests kurulu değil')

        token = self._get_token_live()
        headers = {
            'Authorization': f'Bearer {token}',
            'X-Request-ID': iban,
            'PSU-IP-Address': '127.0.0.1',
        }
        accounts_resp = requests.get(f'{self.base_url}/accounts', headers=headers, timeout=15)
        accounts_resp.raise_for_status()
        accounts = accounts_resp.json().get('accounts', [])

        target = next((a for a in accounts if a.get('iban') == iban), None)
        if not target:
            raise ValueError(f'IBAN bulunamadı: {iban}')

        acc_id = target['resourceId']
        txn_resp = requests.get(
            f'{self.base_url}/accounts/{acc_id}/transactions',
            headers=headers,
            params={'dateFrom': (datetime.utcnow() - timedelta(days=365)).strftime('%Y-%m-%d')},
            timeout=15,
        )
        txn_resp.raise_for_status()
        return self._parse_transactions(txn_resp.json())

    # ──────────────────────────────────────────────────────────────
    # Berlin Group NextGenPSD2 yanıt parser
    # ──────────────────────────────────────────────────────────────

    def _parse_transactions(self, txn_data: dict) -> dict:
        """Berlin Group /transactions yanıtından özet metrikleri çıkarır."""
        transactions = (
            txn_data.get('transactions', {}).get('booked', []) +
            txn_data.get('transactions', {}).get('pending', [])
        )
        if not transactions:
            return self._fetch_mock('fallback')

        monthly: dict[str, dict] = {}
        for t in transactions:
            amount = float(t.get('transactionAmount', {}).get('amount', 0))
            date_str = t.get('bookingDate', t.get('valueDate', ''))[:7]  # YYYY-MM
            if date_str not in monthly:
                monthly[date_str] = {'inflow': 0.0, 'outflow': 0.0, 'min_balance': math.inf}

            if amount > 0:
                monthly[date_str]['inflow'] += amount
            else:
                monthly[date_str]['outflow'] += abs(amount)

            balance = float(t.get('balanceAfterTransaction', {}).get('balanceAmount', {}).get('amount', 0) or 0)
            if balance < monthly[date_str]['min_balance']:
                monthly[date_str]['min_balance'] = balance

        if not monthly:
            return self._fetch_mock('fallback')

        months = list(monthly.values())
        avg_inflow = sum(m['inflow'] for m in months) / len(months)
        avg_outflow = sum(m['outflow'] for m in months) / len(months)
        overdraft_count = sum(1 for m in months if m['min_balance'] != math.inf and m['min_balance'] < 0)

        # Cashflow düzenliliği: inflow standart sapması / ort. inflow
        inflows = [m['inflow'] for m in months]
        avg_i = sum(inflows) / len(inflows)
        std_i = math.sqrt(sum((x - avg_i) ** 2 for x in inflows) / len(inflows)) if len(inflows) > 1 else 0
        cv = std_i / avg_i if avg_i > 0 else 1.0
        regularity = round(max(0.0, 1.0 - min(cv, 1.0)), 3)

        avg_balance = avg_inflow - avg_outflow

        return {
            'avg_monthly_balance': round(max(0.0, avg_balance), 2),
            'avg_monthly_inflow': round(avg_inflow, 2),
            'avg_monthly_outflow': round(avg_outflow, 2),
            'overdraft_count': overdraft_count,
            'cashflow_regularity': regularity,
            'bank_count': 1,
        }

    # ──────────────────────────────────────────────────────────────
    # OAuth yardımcıları
    # ──────────────────────────────────────────────────────────────

    def _get_token_sandbox(self) -> str:
        return 'sandbox-demo-token'

    def _get_token_live(self) -> str:
        if self._access_token:
            return self._access_token
        import requests
        resp = requests.post(
            f'{self.base_url}/oauth/token',
            data={
                'grant_type': 'client_credentials',
                'client_id': self.client_id,
                'client_secret': self.client_secret,
                'scope': 'accounts transactions',
            },
            timeout=10,
        )
        resp.raise_for_status()
        self._access_token = resp.json()['access_token']
        return self._access_token

    # ──────────────────────────────────────────────────────────────
    # DB yardımcısı
    # ──────────────────────────────────────────────────────────────

    def _build_record(self, iban: str, data: dict, customer_id: int,
                      tenant_id: int, consent_given: bool):
        from database import OpenBankingRecord
        now = datetime.utcnow()
        return OpenBankingRecord(
            iban=iban,
            customer_id=customer_id,
            tenant_id=tenant_id,
            avg_monthly_balance=data.get('avg_monthly_balance', 0.0),
            avg_monthly_inflow=data.get('avg_monthly_inflow', 0.0),
            avg_monthly_outflow=data.get('avg_monthly_outflow', 0.0),
            overdraft_count=data.get('overdraft_count', 0),
            cashflow_regularity=data.get('cashflow_regularity', 1.0),
            bank_count=data.get('bank_count', 1),
            consent_given=consent_given,
            consent_timestamp=now if consent_given else None,
            fetched_at=now,
            expires_at=now + timedelta(days=self.cache_days),
            raw_response=json.dumps(data, ensure_ascii=False),
            source=self.mode,
        )
