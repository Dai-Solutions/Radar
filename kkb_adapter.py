"""
KKB (Kredi Kayıt Bürosu) adapter — mock / manual / live mod desteği.

Çalışma modları (.env KKB_MODE değişkeni):
  mock   → tests/fixtures/kkb_mock.json'dan okur, API çağrısı yok (varsayılan)
  manual → elle girilen veriyi KKBReport olarak kaydeder; adapter sorgu yapmaz
  live   → gerçek KKB SOAP API (üye banka sertifikası gerekir)

Gerekli .env değişkenleri (sadece live modda):
  KKB_ENDPOINT    https://ws.kkb.com.tr/KRSService
  KKB_MEMBER_CODE Banka KKB üye kodu
  KKB_CERT        /path/to/client.crt
  KKB_KEY         /path/to/client.key
  KKB_CACHE_DAYS  Rapor önbellek süresi, gün (varsayılan: 30)
"""

import os
import json
import logging
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

_KKB_MODE = os.getenv('KKB_MODE', 'mock')
_KKB_CACHE_DAYS = int(os.getenv('KKB_CACHE_DAYS', '30'))


class KKBVetoError(Exception):
    """Hard veto — karşılıksız çek veya aktif icra tespit edildi."""


class KKBAdapter:

    def __init__(self, config: Optional[dict] = None):
        cfg = config or {}
        self.mode = cfg.get('KKB_MODE', _KKB_MODE)
        self.endpoint = cfg.get('KKB_ENDPOINT', os.getenv('KKB_ENDPOINT', ''))
        self.member_code = cfg.get('KKB_MEMBER_CODE', os.getenv('KKB_MEMBER_CODE', ''))
        cert = cfg.get('KKB_CERT', os.getenv('KKB_CERT', ''))
        key = cfg.get('KKB_KEY', os.getenv('KKB_KEY', ''))
        self.cert = (cert, key) if cert and key else None
        self.cache_days = int(cfg.get('KKB_CACHE_DAYS', _KKB_CACHE_DAYS))

    # ------------------------------------------------------------------
    # Ana sorgu metodu
    # ------------------------------------------------------------------

    def get_corporate_risk(self, tax_no: str, customer_id: int, tenant_id: int, session):
        """
        Vergi numarası için KKB kurumsal risk raporu döner.
        Cache geçerliyse (expires_at > now) API çağrısı yapılmaz.
        Manual modda yalnızca mevcut kayıt döner, yoksa None.
        """
        from database import KKBReport

        cached = (
            session.query(KKBReport)
            .filter(KKBReport.tax_no == tax_no, KKBReport.expires_at > datetime.utcnow())
            .order_by(KKBReport.fetched_at.desc())
            .first()
        )
        if cached:
            logger.debug('KKB cache hit: %s', tax_no)
            return cached

        if self.mode == 'manual':
            return None

        data = self._fetch_live(tax_no) if self.mode == 'live' else self._fetch_mock(tax_no)

        report = self._build_report(tax_no, data, customer_id, tenant_id)
        session.add(report)
        session.commit()
        logger.info('KKB rapor kaydedildi: %s (kaynak: %s)', tax_no, self.mode)
        return report

    # ------------------------------------------------------------------
    # Manuel veri girişi (banka PDF raporundan elle aktarım)
    # ------------------------------------------------------------------

    def save_manual(
        self,
        tax_no: str,
        data: dict,
        customer_id: int,
        tenant_id: int,
        consent_given: bool,
        session,
    ):
        """
        Kullanıcının formdan girdiği KKB verilerini kaydeder.
        Mevcut geçerli kayıt varsa önce expire edilir.
        """
        from database import KKBReport

        session.query(KKBReport).filter(
            KKBReport.tax_no == tax_no,
            KKBReport.expires_at > datetime.utcnow(),
        ).update({'expires_at': datetime.utcnow()})

        report = self._build_report(tax_no, data, customer_id, tenant_id, source='manual')
        report.consent_given = consent_given
        report.consent_timestamp = datetime.utcnow() if consent_given else None
        session.add(report)
        session.commit()
        logger.info('KKB manuel kayıt oluşturuldu: %s', tax_no)
        return report

    # ------------------------------------------------------------------
    # Hard veto kontrolü — CreditScorer'dan önce çağrılır
    # ------------------------------------------------------------------

    @staticmethod
    def check_veto(report) -> Optional[str]:
        """
        Pozitif hard veto alanı varsa neden döner, yoksa None.
        CreditScorer bu değeri kontrol ederek skoru hesaplamadan ret üretir.
        """
        if report is None:
            return None
        if report.has_bounced_check:
            return 'kkb_bounced_check'
        if report.active_enforcement:
            return 'kkb_active_enforcement'
        if report.npl_flag:
            return 'kkb_npl'
        return None

    # ------------------------------------------------------------------
    # Skor ağırlıklandırma yardımcısı
    # ------------------------------------------------------------------

    @staticmethod
    def enrich_scores(historical_score: float, debt_score: float, report) -> tuple[float, float]:
        """
        Mevcut historical ve debt skorlarını KKB verisiyle ağırlıklı olarak günceller.

        KKB ağırlığı %30 — iç veri hâlâ baskın; raporun kalitesi ve tamlığına
        göre ileride dinamik hale getirilebilir.

        Döner: (yeni_historical, yeni_debt)
        """
        if report is None:
            return historical_score, debt_score

        KKB_WEIGHT = 0.30

        # Gecikme cezası: 90+ gün → tam ceza, altı oranlı
        delay_penalty = min((report.max_days_past_due or 0) / 90.0, 1.0)
        kkb_historical = 100.0 - delay_penalty * 100.0
        new_historical = historical_score * (1 - KKB_WEIGHT) + kkb_historical * KKB_WEIGHT

        # Borç skoru: KKB toplam maruz kalım → iç likit tabloya oran
        new_debt = debt_score
        if report.total_bank_exposure and report.total_bank_exposure > 0:
            # Eğer KKB borcu iç likit tablodan %50 fazlaysa ceza uygula
            # (customer.equity normalizasyonu CreditScorer'da yapılır)
            exposure_factor = min(report.npl_amount / max(report.total_bank_exposure, 1), 1.0)
            new_debt = debt_score * (1 - KKB_WEIGHT) + (100.0 - exposure_factor * 100.0) * KKB_WEIGHT

        return round(new_historical, 2), round(new_debt, 2)

    # ------------------------------------------------------------------
    # İç metodlar
    # ------------------------------------------------------------------

    def _fetch_live(self, tax_no: str) -> dict:
        try:
            import requests
            import xmltodict
        except ImportError:
            raise RuntimeError('requests ve xmltodict gereklidir: pip install requests xmltodict')

        if not self.endpoint or not self.cert:
            raise ValueError('KKB_ENDPOINT ve KKB_CERT/KKB_KEY .env dosyasında tanımlı olmalı')

        envelope = self._build_krs_envelope(tax_no)
        resp = requests.post(
            self.endpoint,
            data=envelope.encode('utf-8'),
            cert=self.cert,
            headers={
                'Content-Type': 'text/xml; charset=utf-8',
                'SOAPAction': '"KRSKurumsal"',
            },
            timeout=10,
        )
        resp.raise_for_status()
        parsed = xmltodict.parse(resp.text)
        return self._extract_krs_fields(parsed)

    def _fetch_mock(self, tax_no: str) -> dict:
        fixture_path = os.path.join(
            os.path.dirname(__file__), 'tests', 'fixtures', 'kkb_mock.json'
        )
        if os.path.exists(fixture_path):
            with open(fixture_path, encoding='utf-8') as f:
                fixtures = json.load(f)
            if tax_no in fixtures:
                logger.debug('KKB mock fixture bulundu: %s', tax_no)
                return fixtures[tax_no]

        # Fixture'da yok → temiz profil
        return {
            'total_bank_exposure': 500_000.0,
            'npl_amount': 0.0,
            'npl_flag': False,
            'max_days_past_due': 0,
            'num_late_payments': 0,
            'has_bounced_check': False,
            'active_enforcement': False,
            'kkb_score': 1400,
            'kkb_grade': 'A',
        }

    def _build_report(self, tax_no: str, data: dict, customer_id: int, tenant_id: int, source: str = None):
        from database import KKBReport

        now = datetime.utcnow()
        return KKBReport(
            tax_no=tax_no,
            customer_id=customer_id,
            tenant_id=tenant_id,
            total_bank_exposure=data.get('total_bank_exposure'),
            npl_amount=data.get('npl_amount', 0.0),
            npl_flag=data.get('npl_flag', False),
            max_days_past_due=data.get('max_days_past_due', 0),
            num_late_payments=data.get('num_late_payments', 0),
            has_bounced_check=data.get('has_bounced_check', False),
            active_enforcement=data.get('active_enforcement', False),
            kkb_score=data.get('kkb_score'),
            kkb_grade=data.get('kkb_grade'),
            fetched_at=now,
            expires_at=now + timedelta(days=self.cache_days),
            raw_response=json.dumps(data, ensure_ascii=False),
            source=source or self.mode,
        )

    def _build_krs_envelope(self, tax_no: str) -> str:
        return (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/"'
            '                  xmlns:krs="http://kkb.com.tr/krs">'
            '  <soapenv:Header/>'
            '  <soapenv:Body>'
            '    <krs:KurumRiskSorgu>'
            f'      <krs:UyeKodu>{self.member_code}</krs:UyeKodu>'
            f'      <krs:VergiNo>{tax_no}</krs:VergiNo>'
            '      <krs:SorguTipi>FULL</krs:SorguTipi>'
            '    </krs:KurumRiskSorgu>'
            '  </soapenv:Body>'
            '</soapenv:Envelope>'
        )

    def _extract_krs_fields(self, parsed: dict) -> dict:
        # KKB gerçek SOAP şeması banka ortaklığı sonrası doğrulanacak.
        # Alan isimleri KKB entegrasyon kılavuzuna göre güncellenecek.
        try:
            body = parsed['Envelope']['Body']['KurumRiskSorguResponse']
            return {
                'total_bank_exposure': float(body.get('ToplamKredi', 0)),
                'npl_amount': float(body.get('TakiptekiAlacak', 0)),
                'npl_flag': body.get('TakipDurumu', 'H') == 'E',
                'max_days_past_due': int(body.get('EnUzunGecikme', 0)),
                'num_late_payments': int(body.get('GecikmeAdedi', 0)),
                'has_bounced_check': body.get('KarsilliksizCek', 'H') == 'E',
                'active_enforcement': body.get('AktifIcra', 'H') == 'E',
                'kkb_score': int(body['KKBSkor']) if body.get('KKBSkor') else None,
                'kkb_grade': body.get('KKBNot'),
            }
        except (KeyError, TypeError, ValueError) as exc:
            logger.error('KKB yanıt parse hatası: %s', exc)
            raise ValueError(f'KKB yanıt formatı beklenenden farklı: {exc}') from exc
