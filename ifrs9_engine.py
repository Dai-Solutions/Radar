"""
IFRS 9 / Basel III Risk Motoru

IFRS 9 — Beklenen Kredi Zararı (ECL):
  Aşama 1 (iyi performans)  : 12 aylık ECL  = PD_12m × LGD × EAD
  Aşama 2 (artan risk)      : Ömür boyu ECL = PD_lt  × LGD × EAD
  Aşama 3 (değer düşüklüğü) : Ömür boyu ECL = LGD × EAD  (PD ≈ 1)

Basel III IRB Foundation — Sermaye Gerekliliği:
  K   = LGD × Φ[(1-R)^-0.5 × Φ^-1(PD) + (R/(1-R))^0.5 × Φ^-1(0.999)] × maturity_adj − PD × LGD
  RWA = 12.5 × K × EAD
  CR  = 8% × RWA  (Pillar 1 minimum)

Referanslar:
  - Basel III: BIS CRE31 (Corporate IRB)
  - IFRS 9: IASB ED/2013/3
  - BDDK: Kredi Risk Yönetimi Yönetmeliği
"""

import math
import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────
# İstatistik yardımcıları (scipy bağımlılığı olmadan)
# ──────────────────────────────────────────────────────────────

def _norm_cdf(x: float) -> float:
    """Standart normal CDF — math.erfc tabanlı, hassasiyet 1e-7."""
    return 0.5 * math.erfc(-x / math.sqrt(2))


def _norm_ppf(p: float) -> float:
    """
    Standart normal PPF (ters CDF) — Peter Acklam rasyonel yaklaşımı.
    p ∈ (0.001, 0.999) için maksimum hata < 1.15e-9.
    """
    p = max(1e-10, min(1 - 1e-10, p))

    # Katsayılar
    a = (-3.969683028665376e+01,  2.209460984245205e+02,
         -2.759285104469687e+02,  1.383577518672690e+02,
         -3.066479806614716e+01,  2.506628277459239e+00)
    b = (-5.447609879822406e+01,  1.615858368580409e+02,
         -1.556989798598866e+02,  6.680131188771972e+01,
         -1.328068155288572e+01)
    c = (-7.784894002430293e-03, -3.223964580411365e-01,
         -2.400758277161838e+00, -2.549732539343734e+00,
          4.374664141464968e+00,  2.938163982698783e+00)
    d = ( 7.784695709041462e-03,  3.224671290700398e-01,
          2.445134137142996e+00,  3.754408661907416e+00)

    p_lo, p_hi = 0.02425, 1 - 0.02425

    if p < p_lo:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) \
               / ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    elif p <= p_hi:
        q = p - 0.5
        r = q * q
        return (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*q \
               / (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1)
    else:
        q = math.sqrt(-2 * math.log(1 - p))
        return -(((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) \
                / ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)


# ──────────────────────────────────────────────────────────────
# PD eşleme tablosu (skor → temerrüt olasılığı)
# ──────────────────────────────────────────────────────────────

# (alt_skor, pd) çiftleri — arasındaki değerler log-lineer interpolasyonla hesaplanır.
# Kaynak: S&P kurumsal temerrüt istatistikleri + Türkiye kredi döngüsüne göre kalibre.
_PD_TABLE = [
    (100, 0.003),   # 0.30%  — prime / AAA
    (90,  0.006),   # 0.60%  — AA
    (80,  0.012),   # 1.20%  — A
    (70,  0.025),   # 2.50%  — BBB
    (60,  0.050),   # 5.00%  — BB
    (50,  0.090),   # 9.00%  — B+
    (40,  0.150),   # 15.0%  — B
    (30,  0.220),   # 22.0%  — B-/CCC
    (0,   0.300),   # 30.0%  — default bölgesi
]


def _pd_from_score(score: float) -> float:
    """Kredi skoru (0-100) → 1 yıllık PD (0-1)."""
    score = max(0.0, min(100.0, score))
    for i in range(len(_PD_TABLE) - 1):
        s_hi, pd_hi = _PD_TABLE[i]
        s_lo, pd_lo = _PD_TABLE[i + 1]
        if s_lo <= score <= s_hi:
            if s_hi == s_lo:
                return pd_hi
            # Log-lineer interpolasyon
            t = (score - s_lo) / (s_hi - s_lo)
            return math.exp(math.log(pd_lo) + t * (math.log(pd_hi) - math.log(pd_lo)))
    return 0.300


# ──────────────────────────────────────────────────────────────
# Sonuç veri sınıfı
# ──────────────────────────────────────────────────────────────

@dataclass
class IFRS9Result:
    stage: int             # 1, 2 veya 3
    pd: float              # 12 aylık temerrüt olasılığı
    lgd: float             # Temerrüt kayıp oranı (0-1)
    ead: float             # Temerrüt anındaki maruz kalım (TL)
    ecl_12m: float         # 12 aylık ECL (TL)
    ecl_lifetime: float    # Ömür boyu ECL (TL)
    ecl: float             # Efektif ECL — aşamaya göre (TL)
    rwa: float             # Risk ağırlıklı varlık — Basel III (TL)
    capital_req: float     # Pillar 1 sermaye gerekliliği = %8 × RWA (TL)
    stage_reason: str      # Aşama sınıflandırma gerekçesi


# ──────────────────────────────────────────────────────────────
# Ana motor
# ──────────────────────────────────────────────────────────────

class IFRS9Engine:
    """
    IFRS 9 ECL + Basel III IRB sermaye gerekliliği motoru.

    Kullanım:
        engine = IFRS9Engine()
        result = engine.calculate(
            final_score=72.5,
            avg_debt=850_000,
            request_amount=200_000,
            total_assets=3_000_000,
            total_liabilities=1_800_000,
            equity=700_000,
            kkb_report=kkb_report,    # opsiyonel
            veto_reason=None,          # 'kkb_bounced_check' vb.
        )
    """

    # Basel III Pillar 1 oranları
    PILLAR1_RATIO = 0.08          # %8 minimum
    PILLAR1_WITH_BUFFER = 0.105   # %10.5 (sermaye koruma tamponu dahil)
    MATURITY_YEARS = 2.5          # Kurumsal varsayılan vade (Basel III par. 318)

    def calculate(
        self,
        final_score: float,
        avg_debt: float,
        request_amount: float,
        total_assets: float = 0.0,
        total_liabilities: float = 0.0,
        equity: float = 0.0,
        kkb_report=None,
        veto_reason: Optional[str] = None,
    ) -> IFRS9Result:

        pd = _pd_from_score(final_score)
        lgd = self._lgd(total_assets, total_liabilities, equity)
        ead = self._ead(avg_debt, request_amount)

        stage, reason = self._stage(
            final_score, pd, kkb_report, veto_reason
        )

        ecl_12m = self._ecl_12m(pd, lgd, ead)
        ecl_lt = self._ecl_lifetime(pd, lgd, ead, stage)
        ecl = ecl_lt if stage >= 2 else ecl_12m

        rwa, capital = self._basel3_capital(pd, lgd, ead)

        return IFRS9Result(
            stage=stage,
            pd=round(pd, 6),
            lgd=round(lgd, 4),
            ead=round(ead, 2),
            ecl_12m=round(ecl_12m, 2),
            ecl_lifetime=round(ecl_lt, 2),
            ecl=round(ecl, 2),
            rwa=round(rwa, 2),
            capital_req=round(capital, 2),
            stage_reason=reason,
        )

    # ── IFRS 9 Aşama Sınıflandırması ──────────────────────────

    def _stage(self, score: float, pd: float, kkb_report, veto: Optional[str]) -> tuple[int, str]:
        """IFRS 9 Aşama 1/2/3 belirleme — en kötü sinyal kazanır."""

        # Aşama 3: Değer düşüklüğüne uğramış
        if veto:
            return 3, f'KKB hard veto: {veto}'
        if kkb_report:
            if getattr(kkb_report, 'npl_flag', False):
                return 3, 'KKB NPL kaydı mevcut'
            if getattr(kkb_report, 'max_days_past_due', 0) > 90:
                return 3, f'KKB DPD {kkb_report.max_days_past_due} gün (> 90)'
        if score < 40:
            return 3, f'Skor {score:.1f} < 40 (yüksek temerrüt bölgesi)'

        # Aşama 2: Önemli kredi riski artışı (SICR)
        sicr_signals = []
        if 40 <= score < 60:
            sicr_signals.append(f'skor {score:.1f} ∈ [40, 60)')
        if kkb_report:
            dpd = getattr(kkb_report, 'max_days_past_due', 0) or 0
            if 30 < dpd <= 90:
                sicr_signals.append(f'KKB DPD {dpd} gün ∈ (30, 90]')
            late = getattr(kkb_report, 'num_late_payments', 0) or 0
            if late >= 3:
                sicr_signals.append(f'KKB {late} gecikme / 12 ay')
        if pd >= 0.10:
            sicr_signals.append(f'PD {pd*100:.1f}% ≥ %10')
        if sicr_signals:
            return 2, '; '.join(sicr_signals)

        return 1, 'İyi performans — SICR yok'

    # ── LGD hesabı ─────────────────────────────────────────────

    def _lgd(self, total_assets: float, total_liabilities: float, equity: float) -> float:
        """
        Özkaynak oranına göre LGD tahmini.
        Kurumsal teminatsız standart aralık: %35–%65 (Basel III par. 468).
        """
        if total_assets <= 0:
            return 0.45  # Basel III standart kurumsal LGD

        equity_ratio = equity / total_assets
        if equity_ratio >= 0.40:
            return 0.35   # Güçlü bilanço — düşük kayıp
        if equity_ratio >= 0.25:
            return 0.42
        if equity_ratio >= 0.10:
            return 0.50
        if equity_ratio > 0:
            return 0.58   # İnce özkaynak tamponu
        return 0.65       # Teknik iflasa yakın

    # ── EAD hesabı ─────────────────────────────────────────────

    def _ead(self, avg_debt: float, request_amount: float) -> float:
        """
        Temerrüt anındaki maruz kalım.
        Mevcut bakiye + talep tutarının %75'i (CCF, Basel III par. 83).
        """
        outstanding = max(avg_debt, 0.0)
        undrawn = max(request_amount - outstanding, 0.0)
        ccf = 0.75  # Çekilen tutar dönüşüm faktörü
        return outstanding + undrawn * ccf

    # ── ECL hesapları ──────────────────────────────────────────

    def _ecl_12m(self, pd: float, lgd: float, ead: float) -> float:
        """12 aylık ECL — Aşama 1."""
        df = 1 / (1 + 0.12)  # %12 iskonto oranı (TCMB politika faiz yaklaşımı)
        return pd * lgd * ead * df

    def _ecl_lifetime(self, pd: float, lgd: float, ead: float, stage: int) -> float:
        """
        Ömür boyu ECL.
        Aşama 2: kümülatif temerrüt olasılığı, 5 yıl.
        Aşama 3: LGD × EAD (PD = 1).
        """
        if stage == 3:
            return lgd * ead

        # 5 yıllık ömür boyu PD — marjinal PD toplamı (yıllık sabit varsayım)
        discount_rate = 0.12
        lt_ecl = 0.0
        survival = 1.0
        for t in range(1, 6):
            marginal_pd = survival * pd
            df = 1 / (1 + discount_rate) ** t
            lt_ecl += marginal_pd * lgd * ead * df
            survival *= (1 - pd)
        return lt_ecl

    # ── Basel III IRB Foundation RWA ───────────────────────────

    def _basel3_capital(self, pd: float, lgd: float, ead: float) -> tuple[float, float]:
        """
        Basel III IRB Foundation kurumsal sermaye gereksinimi.
        BIS CRE31.15 formülü.

        Döner: (RWA, capital_requirement)
        """
        pd = max(pd, 0.0003)   # Basel III minimum PD = 0.03%
        pd = min(pd, 0.9999)
        M = self.MATURITY_YEARS

        # Korelasyon faktörü R
        exp_50pd = math.exp(-50 * pd)
        exp_50   = math.exp(-50)
        base_r   = (1 - exp_50pd) / (1 - exp_50)
        R = 0.12 * base_r + 0.24 * (1 - base_r)

        # Vade düzeltme faktörü b
        ln_pd = math.log(pd)
        b = (0.11852 - 0.05478 * ln_pd) ** 2

        # Sermaye çarpanı K
        g_pd    = _norm_ppf(pd)
        g_999   = _norm_ppf(0.999)
        sqrt_r  = math.sqrt(R / (1 - R))
        sqrt_1r = 1 / math.sqrt(1 - R)

        n_arg = sqrt_1r * g_pd + sqrt_r * g_999
        maturity_adj = (1 + (M - 2.5) * b) / (1 - 1.5 * b)

        K = (lgd * _norm_cdf(n_arg) - pd * lgd) * maturity_adj
        K = max(0.0, K)

        rwa = 12.5 * K * ead
        capital = self.PILLAR1_RATIO * rwa
        return rwa, capital
