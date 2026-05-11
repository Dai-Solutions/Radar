"""
Credit Scoring Algorithm
3-factor scoring: History + Future + Request
"""

from dataclasses import dataclass, field
from typing import Optional, List
import math
import random
from aging_analyzer import AgingAnalysis, AgingRecord, AgingAnalyzer
from translations import translations

class ScenarioResult:
    def __init__(self, name, description, impact, score):
        self.name = name
        self.description = description
        self.impact = impact
        self.score = score

@dataclass
class CreditRequestInput:
    """Inputs for credit scoring request"""
    request_amount: float
    currency: str = 'TL'
    period: str = '2024-01'
    note: str = ""

@dataclass
class CreditScoreResult:
    """Credit scoring final result"""
    account_code: str
    account_name: str
    historical_score: float
    future_score: float
    request_score: float
    debt_score: float
    final_score: float
    credit_note: str
    avg_delay_days: float
    avg_debt: float
    future_6_months_total: float
    request_amount: float
    recommended_limit: float
    recommendation_message: str
    assessment: str = ""
    assessment_i18n: dict = field(default_factory=dict)
    decision_summary_i18n: dict = field(default_factory=dict)
    scenarios: List = field(default_factory=list)
    momentum_score: float = 0
    trend_direction: str = 'stable'
    max_capacity: float = 0
    decision_summary: str = ""
    z_score: float = 0
    z_score_note: str = ""
    profitability_impact: float = 0
    vade_days: int = 0
    vade_message: str = ""
    inflation_capped: bool = False
    dscr_score: float = 0
    volatility: float = 0
    piotroski_score: int = 0
    piotroski_grade: str = ""
    icr_score: float = 0.0
    aging_concentration: float = 0.0
    # KKB entegrasyon alanları
    kkb_veto: Optional[str] = None     # hard veto nedeni (None = veto yok)
    kkb_score: Optional[int] = None    # KKB/GKD skoru (1-1900)
    kkb_grade: Optional[str] = None    # KKB notu (A/B/C/D)
    kkb_enriched: bool = False         # KKB verisiyle ağırlıklandırma yapıldı mı
    # Open Banking
    ob_enriched: bool = False          # OB verisiyle zenginleştirme yapıldı mı
    # ML Overlay
    ml_pd: float = -1.0               # ML PD tahmini (-1 = model mevcut değil)
    ml_adjusted: bool = False          # IFRS 9 PD ML ile harmanlandi mı
    # IFRS 9 / Basel III
    ifrs9_stage: int = 0               # 1, 2, 3
    ifrs9_pd: float = 0.0              # Temerrüt olasılığı (0-1)
    ifrs9_lgd: float = 0.0             # Temerrüt kayıp oranı (0-1)
    ifrs9_ead: float = 0.0             # Temerrüt anı maruz kalım (TL)
    ifrs9_ecl: float = 0.0             # Beklenen kredi zararı (TL)
    ifrs9_rwa: float = 0.0             # Risk ağırlıklı varlık — Basel III (TL)
    ifrs9_capital_req: float = 0.0     # Pillar 1 sermaye gereksinimi (TL)
    ifrs9_stage_reason: str = ""       # Aşama gerekçesi

class CreditScorer:
    """Credit scoring engine"""
    
    def __init__(self, customer_id=None, db_session=None, aging_analyzer=None, customer_data=None, aging_records=None, kkb_report=None, ob_record=None):
        self.customer_id = customer_id
        self.session = db_session
        self.aging_analyzer = aging_analyzer or AgingAnalyzer()
        self.kkb_report = kkb_report
        self.ob_record = ob_record
        
        # Load data: priority to passed objects, then DB
        if customer_data:
            self.customer = customer_data
        elif self.session and self.customer_id:
            from database import Customer
            self.customer = self.session.query(Customer).filter(Customer.id == customer_id).first()
        else:
            self.customer = None

        if aging_records is not None:
            self.aging_records = aging_records
        elif self.session and self.customer_id:
            from database import AgingRecord as AgingRecordDB
            self.aging_records = self.session.query(AgingRecordDB).filter(AgingRecordDB.customer_id == customer_id).all()
        else:
            self.aging_records = []
    
    # Weights
    WEIGHT_HISTORY = 0.45
    WEIGHT_FUTURE = 0.30
    WEIGHT_REQUEST = 0.25
    DECAY_K_REQUEST = 0.3
    
    NOTE_RANGES = {'A': (80, 100), 'B': (60, 79.9), 'C': (0, 59.9)}
    DEBT_SCORE_TABLE = { (0, 25000): 100, (25001, 75000): 75, (75001, 150000): 50, (150001, 999999999): 25 }
    REQUEST_SCORE_TABLE = { (0, 1): 100, (1.01, 2): 90, (2.01, 3): 75, (3.01, 5): 50, (5.01, 10): 30, (10.01, 999999): 10 }
    
    Z_SAFE_ZONE = 2.9
    Z_GREY_ZONE = 1.23
    
    # Altman Z-Score katsayıları sektöre göre (A=çalışma_sermayesi, B=birikmiş_kar,
    # C=EBIT, D=özkaynak/borç, E=satışlar — hepsi toplam varlıklara bölünür)
    SECTOR_Z_CONSTANTS = {
        'manufacturing':  (0.717, 0.847, 3.107, 0.420, 0.998),  # Altman 1968 orijinal
        'retail':         (6.56,  3.26,  6.72,  1.05,  0.999),  # Altman 1995 private firm
        'service':        (1.2,   1.4,   3.3,   0.6,   0.999),  # EM modeli — hizmet ağırlıklı
        'construction':   (0.9,   1.1,   2.8,   0.5,   0.8  ),  # İnşaat — düşük varlık devri
        'general':        (1.2,   1.4,   3.3,   0.6,   1.0  ),  # Genel / bilinmeyen
    }

    VALID_SECTORS = list(SECTOR_Z_CONSTANTS.keys())

    def _safe_get(self, obj, attr, default=0):
        if obj is None: return default
        if isinstance(obj, dict): return obj.get(attr, default)
        return getattr(obj, attr, default)

    def calculate(self, settings, request_input, skip_scenarios=False, lang='tr', kkb_report=None):
        # KKB: çağrı-seviyesi rapor parametre-üzerinden gelirse __init__ raporu override eder
        active_kkb = kkb_report if kkb_report is not None else self.kkb_report

        # ── KKB Hard Veto ────────────────────────────────────────────────────
        # Karşılıksız çek, aktif icra veya NPL tespitinde skor hesaplanmadan
        # erken çıkış yapılır. Rapor ve tüm dil metinleri yine de üretilir.
        from kkb_adapter import KKBAdapter
        veto_reason = KKBAdapter.check_veto(active_kkb)
        if veto_reason:
            return self._veto_result(veto_reason, request_input, active_kkb, lang)

        # Settings Inputs
        inflation_rate = float(self._safe_get(settings, 'inflation_rate', 55.0))
        interest_rate = float(self._safe_get(settings, 'interest_rate', 45.0))
        sector_risk = float(self._safe_get(settings, 'sector_risk', 1.0))
        
        # Altman Z-Score and Financial inputs (From Customer)
        total_assets = float(getattr(self.customer, 'total_assets', 0) or 0)
        total_liabilities = float(getattr(self.customer, 'total_liabilities', 0) or 0)
        retained_earnings = float(getattr(self.customer, 'retained_earnings', 0) or 0)
        ebit = float(getattr(self.customer, 'ebit', 0) or 0)
        sales = float(getattr(self.customer, 'sales', 0) or 0)
        working_capital = float(getattr(self.customer, 'working_capital', 0) or 0)
        
        equity = float(getattr(self.customer, 'equity', 0) or 0)
        net_profit = float(getattr(self.customer, 'annual_net_profit', 0) or 0)
        liquidity = float(getattr(self.customer, 'liquidity_ratio', 1.0) or 1.0)
        
        # 0. Z-Score — sektör customer.sector'dan gelir, eski sector_risk proxy'si kaldırıldı
        z_score = 0.0
        z_score_note = "N/A"
        customer_sector = str(getattr(self.customer, 'sector', 'general') or 'general').lower()
        sector_key = customer_sector if customer_sector in self.VALID_SECTORS else 'general'
        weights = self.SECTOR_Z_CONSTANTS[sector_key]
        
        if total_assets > 0:
            A = (working_capital or 0) / total_assets
            B = (retained_earnings or 0) / total_assets
            C = (ebit or 0) / total_assets
            D = equity / (total_liabilities or 1)
            E = (sales or 0) / total_assets
            
            z_score = (weights[0] * A) + (weights[1] * B) + (weights[2] * C) + (weights[3] * D) + (weights[4] * E)
            
            if lang == 'tr':
                if z_score > self.Z_SAFE_ZONE: z_score_note = "Güvenli"
                elif z_score > self.Z_GREY_ZONE: z_score_note = "Gri"
                else: z_score_note = "Riskli"
        
        # 0.5 DSCR Calculation
        interest_expenses = float(getattr(self.customer, 'interest_expenses', 0) or 0)
        principal_payments = float(getattr(self.customer, 'principal_payments', 0) or 0)
        dscr = (ebit) / (interest_expenses + principal_payments + 0.1) if (interest_expenses + principal_payments) > 0 else 2.0
        dscr = max(0, min(2.0, dscr)) # Cap at 2.0 for scoring

        # 1. Aging Analysis
        analysis = self.aging_analyzer.analyze(self.aging_records, self.customer.account_code, self.customer.account_name, interest_rate=interest_rate)
        
        # 2. Scores
        request_amount = float(self._safe_get(request_input, 'request_amount', 0))
        avg_debt = float(self._safe_get(analysis, 'avg_debt', 0))
        base_volume = avg_debt
        
        historical_score = self._safe_get(analysis, 'historical_score')

        # Apply Volatility Penalty
        volatility = self._safe_get(analysis, 'delay_volatility', 0)
        if volatility > 15: # High volatility (> 15 days)
            vol_penalty = min(20, (volatility - 15) * 1.5)
            historical_score = max(0, historical_score - vol_penalty)

        future_score = self.aging_analyzer._calculate_future_score(self._safe_get(analysis, 'future_total_debt'), avg_debt, base_volume, interest_rate=interest_rate)
        debt_score = self._calculate_debt_score(avg_debt)
        request_score = self._calculate_request_score(request_amount, max(1, avg_debt))

        # ── KKB Ağırlıklandırma ──────────────────────────────────────────────
        kkb_enriched = False
        if active_kkb is not None:
            historical_score, debt_score = KKBAdapter.enrich_scores(
                historical_score, debt_score, active_kkb
            )
            kkb_enriched = True

        # ── Open Banking Zenginleştirme ──────────────────────────────────────
        ob_enriched = False
        if self.ob_record is not None:
            from openbanking_adapter import OpenBankingAdapter
            historical_score, future_score = OpenBankingAdapter.enrich_scores(
                historical_score, future_score, self.ob_record
            )
            ob_enriched = True
        
        # 3. Final Calculation
        if avg_debt == 0:
            raw_score = (future_score * 0.7) + (request_score * 0.3)
            veto_factor = 1.0
        else:
            raw_score = (historical_score * self.WEIGHT_HISTORY + future_score * self.WEIGHT_FUTURE + request_score * self.WEIGHT_REQUEST)
            veto_factor = 0.5 if historical_score < 40 else (0.8 if historical_score < 60 else 1.0)
            
        macro_multiplier = max(0.4, min(1.0, (1.0 - (interest_rate * 0.005)) / float(sector_risk)))
        final_score = raw_score * macro_multiplier * veto_factor
        
        # DSCR and Profit Impact
        dscr_impact = (dscr - 1.0) * 15 # +15 if dscr=2, -15 if dscr=0
        final_score += dscr_impact
        
        momentum = self._safe_get(analysis, 'momentum_score')
        trend_impact = (momentum * 15) if self._safe_get(analysis, 'trend_direction') == 'declining' else (momentum * 5 if self._safe_get(analysis, 'trend_direction') == 'improving' else 0)
        final_score += trend_impact
        
        profit_impact = -10 if net_profit < 0 else (10 if (net_profit / max(1, self._safe_get(analysis, 'total_debt'))) > 0.15 else 0)
        final_score += profit_impact
        
        final_score = max(0, min(100, final_score))
        note = self._calculate_note(final_score)
        
        # 4. Ek Analizler

        # 4a. Interest Coverage Ratio (ICR) — sadece faiz yükü, DSCR'dan bağımsız
        icr = (ebit / interest_expenses) if interest_expenses > 0 else 0.0
        icr = round(max(0.0, icr), 2)

        # 4b. Piotroski F-Score (0-9)
        piotroski, pio_grade = self._calculate_piotroski(
            net_profit, total_assets, total_liabilities, equity,
            ebit, sales, current_assets=float(getattr(self.customer, 'current_assets', 0) or 0),
            short_term_liabilities=float(getattr(self.customer, 'short_term_liabilities', 0) or 0)
        )

        # 4c. Aging Concentration Index (90+ gün yüzdesi)
        hist = analysis.historical_total_debt if hasattr(analysis, 'historical_total_debt') else 0
        aging_conc = 0.0
        if hist > 0:
            bad_debt = (analysis.historical_days_90_plus if hasattr(analysis, 'historical_days_90_plus') else 0)
            aging_conc = round((bad_debt / hist) * 100, 1)

        # Piotroski final_score'a küçük katkı: her puan ~0.5, yani max ±4.5 etki
        pio_impact = (piotroski - 4.5) * 0.5  # 0 = -2.25, 9 = +2.25
        final_score = max(0, min(100, final_score + pio_impact))

        # 5. IFRS 9 / Basel III
        from ifrs9_engine import IFRS9Engine
        ifrs9 = IFRS9Engine().calculate(
            final_score=final_score,
            avg_debt=avg_debt,
            request_amount=request_amount,
            total_assets=total_assets,
            total_liabilities=total_liabilities,
            equity=equity,
            kkb_report=active_kkb,
            veto_reason=veto_reason,
        )

        # 5b. ML Overlay — kural tabanlı PD'ye ML tahminini harmanlıyor
        import ml_overlay
        ml_features = {
            'final_score': final_score,
            'historical_score': historical_score,
            'future_score': future_score,
            'z_score': z_score,
            'dscr_score': dscr,
            'volatility': volatility,
            'piotroski_score': piotroski,
            'icr_score': icr,
            'aging_concentration': aging_conc,
            'avg_delay_days': float(self._safe_get(analysis, 'avg_delay_days', 0)),
        }
        ml_raw_pd = ml_overlay.predict_pd(ml_features)
        blended_pd, ml_adjusted = ml_overlay.blend_pd(ifrs9.pd, ml_features)
        if ml_adjusted:
            ifrs9.pd = blended_pd

        # 6. Sonuçlar
        rec_limit, rec_msg = self._calculate_limit_recommendation(final_score, note, request_amount, lang)
        max_cap = self._calculate_max_capacity(equity, liquidity, avg_debt, note, interest_rate, sector_risk)
        vade_days, vade_key, inf_capped = self._calculate_vade_recommendation(
            final_score, momentum, (request_amount / max(1, avg_debt)), inflation_rate, volatility=volatility)
        vade_msg = translations[lang]['decision_details'].get(f'vade_{vade_key}', "Peşin sevkiyat")

        result = CreditScoreResult(
            account_code=self._safe_get(analysis, 'account_code'),
            account_name=self._safe_get(analysis, 'account_name'),
            historical_score=historical_score, future_score=future_score,
            request_score=request_score, debt_score=debt_score,
            final_score=final_score, credit_note=note,
            avg_delay_days=self._safe_get(analysis, 'avg_delay_days'), avg_debt=avg_debt,
            future_6_months_total=self._safe_get(analysis, 'future_total_debt'), request_amount=request_amount,
            recommended_limit=rec_limit, recommendation_message=rec_msg,
            max_capacity=max_cap, momentum_score=momentum,
            trend_direction=self._safe_get(analysis, 'trend_direction'), profitability_impact=profit_impact,
            z_score=round(z_score, 2), z_score_note=z_score_note,
            vade_days=vade_days, vade_message=vade_msg, inflation_capped=inf_capped,
            dscr_score=round(dscr, 2), volatility=round(volatility, 1),
            piotroski_score=piotroski, piotroski_grade=pio_grade,
            icr_score=icr, aging_concentration=aging_conc,
            kkb_enriched=kkb_enriched,
            kkb_score=getattr(active_kkb, 'kkb_score', None),
            kkb_grade=getattr(active_kkb, 'kkb_grade', None),
            ob_enriched=ob_enriched,
            ml_pd=ml_raw_pd,
            ml_adjusted=ml_adjusted,
            ifrs9_stage=ifrs9.stage,
            ifrs9_pd=ifrs9.pd,
            ifrs9_lgd=ifrs9.lgd,
            ifrs9_ead=ifrs9.ead,
            ifrs9_ecl=ifrs9.ecl,
            ifrs9_rwa=ifrs9.rwa,
            ifrs9_capital_req=ifrs9.capital_req,
            ifrs9_stage_reason=ifrs9.stage_reason,
        )

        # i18n: Yorum metinlerini 4 dilde üret. Rapor sonradan farklı dilde
        # açıldığında dondurulmuş TR metni değil, aktif dilin metni gösterilir.
        all_langs = ('tr', 'en', 'es', 'de')
        result.decision_summary_i18n = {
            L: self._create_decision_summary(result, L) for L in all_langs
        }
        result.decision_summary = result.decision_summary_i18n[lang]

        if not skip_scenarios:
            result.assessment_i18n = {
                L: self._create_assessment(result, liquidity, net_profit, z_score, inflation_rate, L)
                for L in all_langs
            }
            result.assessment = result.assessment_i18n[lang]
            result.scenarios = self._probability_analysis(settings, request_input, lang)

        return result

    def _calculate_vade_recommendation(self, score, momentum, request_ratio, inflation, volatility=0):
        if score >= 90: days, key = 90, "90"
        elif score >= 75: days, key = 60, "60"
        elif score >= 60: days, key = 30, "30"
        else: return 0, "peşin", False
        
        # Volatility penalty on Vade
        if volatility > 20: # Over 20 days of inconsistency
            days = max(0, days - 30)
            key = str(days) if days > 0 else "peşin"
            if days == 0: return 0, "peşin", False

        inf_capped = False
        if inflation > 50 and days > 60: days, key, inf_capped = 60, "60", True
        return days, key, inf_capped

    def _create_decision_summary(self, res, lang):
        t = translations[lang]['decision_details']
        if res.final_score < 50: return t['rejected_risk_limits']
        if res.credit_note == 'A': return t['approved_full']
        return t['approved_partial'].replace('%{percent}', '50')

    def _calculate_max_capacity(self, equity, liquidity, avg_debt, note, interest_rate, sector_risk):
        base = max(equity * 0.5 * liquidity, avg_debt * 2.0)
        mult = {'A': 1.5, 'B': 1.0, 'C': 0.0}.get(note, 0)
        macro = max(0.4, (1.0 - (interest_rate * 0.005)) / float(sector_risk))
        return round(base * mult * macro, 0)

    def _create_assessment(self, res, liquidity, net_profit, z_score, inflation, lang):
        t = translations[lang]['expert_assessments']
        notes = []

        # 1. Macro & Discipline
        if res.historical_score < 60:
            notes.append(t['weak_discipline'].format(delay=res.avg_delay_days, impact=5))

        # 2. Risk Indicators (New Math)
        volatility = getattr(res, 'volatility', 0)
        if volatility > 20:
            notes.append(translations[lang]['stability_alarm'].format(volatility=volatility))

        dscr = getattr(res, 'dscr_score', 1.5)
        if dscr < 1.0:
            notes.append(t['debt_strain'].format(ratio=dscr * 100))
        elif dscr < 1.3:
            notes.append(t['profit_low']) # Reusing profit low as a proxy for debt coverage strain

        # 3. Solvency (Z-Score)
        if z_score < 1.81:
            notes.append(t['zscore_danger'])

        # 4. Request Ratio
        if res.request_score < 40:
            notes.append(t['high_request'])

        # 5. Inflation & Macro
        notes.append(t['inflation_warning'].format(inf=inflation))

        # --- 6. Yeni kategoriler: trend, sektör benchmark, mevsim, konsantrasyon, talep patlaması ---
        for note_fn in (self._note_trend, self._note_sector_benchmark,
                         self._note_seasonality, self._note_concentration,
                         self._note_request_spike):
            try:
                msg = note_fn(res, t, lang)
                if msg:
                    notes.append(msg)
            except Exception:
                # Yorum üretiminde sessiz başarısızlık — ana skor etkilenmesin
                pass

        if not notes:
            notes.append(t['reliable_profile'])

        return " ".join(notes)

    # ── Yorum üreticileri ──────────────────────────────────────────────────
    # Her biri ya str döner ya None. None = veri yetersiz, yorum çıkmaz.

    def _note_trend(self, res, t, lang):
        """Son 3 dönem ile öncekilerin gecikme eğilimi karşılaştırması."""
        past = [r for r in (self.aging_records or []) if getattr(r, 'type', 'past') == 'past']
        if len(past) < 4:
            return None
        past_sorted = sorted(past, key=lambda r: r.period)
        recent = past_sorted[-3:]
        prior = past_sorted[:-3]
        def avg_overdue(rs):
            tot = sum((r.days_31_60 + r.days_61_90 + r.days_90_plus) for r in rs)
            return tot / len(rs) if rs else 0
        recent_avg = avg_overdue(recent)
        prior_avg = avg_overdue(prior)
        if prior_avg <= 0:
            return None
        delta_pct = (recent_avg - prior_avg) / prior_avg * 100
        if abs(delta_pct) < 15:
            return None  # değişim önemsiz
        key = 'trend_worsening' if delta_pct > 0 else 'trend_improving'
        return t.get(key, '').format(pct=abs(delta_pct))

    def _note_sector_benchmark(self, res, t, lang):
        """Aynı sektördeki diğer müşterilerin son skor medyanına karşı pozisyon."""
        if not (self.session and self.customer and getattr(self.customer, 'sector', None)):
            return None
        from database import Customer, CreditScore
        peer_scores = (self.session.query(CreditScore.final_score)
                       .join(Customer, CreditScore.customer_id == Customer.id)
                       .filter(Customer.sector == self.customer.sector,
                               Customer.id != self.customer.id,
                               CreditScore.final_score.isnot(None))
                       .all())
        peer_vals = sorted(s[0] for s in peer_scores if s[0] is not None)
        if len(peer_vals) < 3:
            return None
        median = peer_vals[len(peer_vals) // 2]
        delta = res.final_score - median
        if abs(delta) < 5:
            return None
        key = 'sector_above' if delta > 0 else 'sector_below'
        return t.get(key, '').format(delta=abs(delta), sector=self.customer.sector, n=len(peer_vals))

    def _note_seasonality(self, res, t, lang):
        """Yaşlandırma kayıtlarını çeyreklere ayır, en kötü çeyreği işaretle."""
        past = [r for r in (self.aging_records or []) if getattr(r, 'type', 'past') == 'past']
        if len(past) < 6:
            return None
        quarter_overdue = {1: [], 2: [], 3: [], 4: []}
        for r in past:
            try:
                month = int(r.period.split('-')[1])
            except (ValueError, IndexError, AttributeError):
                continue
            q = (month - 1) // 3 + 1
            quarter_overdue[q].append(r.days_61_90 + r.days_90_plus)
        avgs = {q: (sum(v) / len(v)) for q, v in quarter_overdue.items() if v}
        if len(avgs) < 3:
            return None
        worst_q = max(avgs, key=avgs.get)
        worst_val = avgs[worst_q]
        overall_avg = sum(avgs.values()) / len(avgs)
        if overall_avg <= 0 or worst_val < overall_avg * 1.5:
            return None
        return t.get('seasonality', '').format(quarter=worst_q, ratio=(worst_val / overall_avg))

    def _note_concentration(self, res, t, lang):
        """Bu müşterinin tenant portföyündeki avg_debt payı."""
        if not (self.session and self.customer):
            return None
        from database import Customer, CreditScore
        from sqlalchemy import func as sa_func
        portfolio = (self.session.query(sa_func.sum(CreditScore.avg_debt))
                     .join(Customer, CreditScore.customer_id == Customer.id)
                     .filter(Customer.tenant_id == getattr(self.customer, 'tenant_id', None),
                             CreditScore.avg_debt.isnot(None))
                     .scalar() or 0)
        if portfolio <= 0 or not res.avg_debt:
            return None
        share = (res.avg_debt / portfolio) * 100
        if share < 25:
            return None
        return t.get('concentration', '').format(pct=share)

    def _note_request_spike(self, res, t, lang):
        """Bu talebin müşterinin geçmiş ortalamasına oranı."""
        if not (self.session and self.customer_id):
            return None
        from database import CreditRequest
        prev = (self.session.query(CreditRequest.request_amount)
                .filter(CreditRequest.customer_id == self.customer_id,
                        CreditRequest.request_amount.isnot(None))
                .all())
        prev_amounts = [a[0] for a in prev if a[0]]
        # Şu anki dahil olabilir; en az 2 geçmiş gerekiyor
        if len(prev_amounts) < 3:
            return None
        prior = prev_amounts[:-1]  # son hariç (mevcut talep)
        prior_avg = sum(prior) / len(prior)
        if prior_avg <= 0:
            return None
        ratio = res.request_amount / prior_avg
        if ratio < 1.5:
            return None
        return t.get('request_spike', '').format(ratio=ratio, prior_avg=prior_avg)

    def _probability_analysis(self, settings, request_input, lang):
        scenarios = []
        import copy

        # Monte Carlo Simulation
        # iter sayısı settings'ten okunur (varsayılan 500). Reproducibility için
        # customer_id'ye seed atılır — aynı müşteri için her seferinde aynı dağılım.
        iterations = int(self._safe_get(settings, 'monte_carlo_iterations', 500) or 500)
        iterations = max(50, min(5000, iterations))  # güvenli aralık
        rng = random.Random(self.customer_id if self.customer_id is not None else 0)
        scores = []

        base_interest = float(self._safe_get(settings, 'interest_rate', 45.0))
        base_request = float(self._safe_get(request_input, 'request_amount', 0))

        for _ in range(iterations):
            # Faiz: [0.9, 1.2] aralığı kasıtlı asimetrik — faiz artışı düşüşten daha olası (upside risk).
            # Talep ±%20 simetrik.
            sim_settings = copy.copy(settings)
            sim_settings['interest_rate'] = base_interest * rng.uniform(0.9, 1.2)

            sim_request = copy.copy(request_input)
            sim_request.request_amount = base_request * rng.uniform(0.8, 1.2)

            # Run calculation (skipping nested scenarios to avoid recursion)
            res = self.calculate(sim_settings, sim_request, skip_scenarios=True, lang=lang)
            scores.append(res.final_score)
            
        scores.sort()
        median = scores[int(iterations * 0.5)]

        # P90 — İyimser senaryo
        opt_score = scores[int(iterations * 0.9) - 1]
        scenarios.append(ScenarioResult(
            translations[lang]['scenarios']['optimistic_name'],
            translations[lang]['scenarios']['optimistic_desc'],
            round(opt_score - median, 1),
            round(opt_score, 1)
        ))

        # P50 — Baz senaryo (medyan)
        scenarios.append(ScenarioResult(
            translations[lang]['scenarios'].get('base_name', 'Baz Senaryo'),
            translations[lang]['scenarios'].get('base_desc', 'Mevcut koşulların devam ettiği orta durum.'),
            0.0,
            round(median, 1)
        ))

        # P10 — Kötümser / Stres testi
        crit_score = scores[int(iterations * 0.1) - 1]
        scenarios.append(ScenarioResult(
            translations[lang]['scenarios']['critical_name'],
            translations[lang]['scenarios']['critical_desc'],
            round(crit_score - median, 1),
            round(crit_score, 1)
        ))

        # ── İsimli stres testleri (deterministik, single-shot) ──
        # Her biri belirli bir piyasa şokunu modeller; MC dağılımından bağımsız.
        named = translations[lang]['named_stress']

        def _one_shot(mut):
            sim_settings = copy.copy(settings)
            sim_request = copy.copy(request_input)
            mut(sim_settings, sim_request)
            r = self.calculate(sim_settings, sim_request, skip_scenarios=True, lang=lang)
            return round(r.final_score, 1)

        # Faiz şoku: +10 puan
        try:
            s = _one_shot(lambda st, rq: st.__setitem__('interest_rate', base_interest + 10.0))
            scenarios.append(ScenarioResult(named['rate_shock_name'], named['rate_shock_desc'],
                                            round(s - median, 1), s))
        except Exception:
            pass

        # Sektör çöküşü: sector_risk_factor × 1.5 (geçici override on customer)
        try:
            orig_srf = getattr(self.customer, 'sector_risk_factor', 1.0) if self.customer else 1.0
            def _sector_mut(st, rq):
                if self.customer:
                    self.customer.sector_risk_factor = orig_srf * 1.5
            s = _one_shot(_sector_mut)
            if self.customer:
                self.customer.sector_risk_factor = orig_srf
            scenarios.append(ScenarioResult(named['sector_collapse_name'], named['sector_collapse_desc'],
                                            round(s - median, 1), s))
        except Exception:
            if self.customer:
                self.customer.sector_risk_factor = orig_srf
            pass

        # Likidite donması: liquidity_ratio × 0.7 (geçici override)
        try:
            orig_lq = getattr(self.customer, 'liquidity_ratio', 1.0) if self.customer else 1.0
            def _liq_mut(st, rq):
                if self.customer:
                    self.customer.liquidity_ratio = max(0.1, orig_lq * 0.7)
            s = _one_shot(_liq_mut)
            if self.customer:
                self.customer.liquidity_ratio = orig_lq
            scenarios.append(ScenarioResult(named['liquidity_freeze_name'], named['liquidity_freeze_desc'],
                                            round(s - median, 1), s))
        except Exception:
            if self.customer:
                self.customer.liquidity_ratio = orig_lq
            pass

        return scenarios

    def _veto_result(self, veto_reason: str, request_input, kkb_report, lang: str) -> 'CreditScoreResult':
        """
        KKB hard veto durumunda sıfır skorlu sonuç üretir.
        Skor hesaplaması yapılmaz; ret kararı ve veto nedeni raporlanır.
        """
        veto_labels = {
            'kkb_bounced_check':     {'tr': 'Karşılıksız çek kaydı tespit edildi.',
                                      'en': 'Bounced cheque record detected.',
                                      'es': 'Cheque sin fondos detectado.',
                                      'de': 'Ungedeckter Scheck festgestellt.'},
            'kkb_active_enforcement': {'tr': 'Aktif icra takibi mevcut.',
                                       'en': 'Active enforcement proceeding on file.',
                                       'es': 'Proceso de ejecución activo.',
                                       'de': 'Aktives Vollstreckungsverfahren vorhanden.'},
            'kkb_npl':               {'tr': 'Takipteki alacak (NPL) kaydı mevcut.',
                                      'en': 'Non-performing loan record on file.',
                                      'es': 'Registro de préstamo moroso.',
                                      'de': 'Notleidender Kredit vermerkt.'},
        }
        label = veto_labels.get(veto_reason, {}).get(lang, veto_reason)
        request_amount = float(self._safe_get(request_input, 'request_amount', 0))
        name = getattr(self.customer, 'account_name', '') if self.customer else ''
        code = getattr(self.customer, 'account_code', '') if self.customer else ''

        from ifrs9_engine import IFRS9Engine
        veto_ifrs9 = IFRS9Engine().calculate(
            final_score=0.0,
            avg_debt=0.0,
            request_amount=request_amount,
            kkb_report=kkb_report,
            veto_reason=veto_reason,
        )

        result = CreditScoreResult(
            account_code=code,
            account_name=name,
            historical_score=0.0,
            future_score=0.0,
            request_score=0.0,
            debt_score=0.0,
            final_score=0.0,
            credit_note='C',
            avg_delay_days=0.0,
            avg_debt=0.0,
            future_6_months_total=0.0,
            request_amount=request_amount,
            recommended_limit=0.0,
            recommendation_message=label,
            kkb_veto=veto_reason,
            kkb_score=getattr(kkb_report, 'kkb_score', None),
            kkb_grade=getattr(kkb_report, 'kkb_grade', None),
            kkb_enriched=False,
            ifrs9_stage=veto_ifrs9.stage,
            ifrs9_pd=veto_ifrs9.pd,
            ifrs9_lgd=veto_ifrs9.lgd,
            ifrs9_ead=veto_ifrs9.ead,
            ifrs9_ecl=veto_ifrs9.ecl,
            ifrs9_rwa=veto_ifrs9.rwa,
            ifrs9_capital_req=veto_ifrs9.capital_req,
            ifrs9_stage_reason=veto_ifrs9.stage_reason,
        )
        all_langs = ('tr', 'en', 'es', 'de')
        result.decision_summary_i18n = {
            L: veto_labels.get(veto_reason, {}).get(L, label) for L in all_langs
        }
        result.decision_summary = label
        result.assessment_i18n = result.decision_summary_i18n.copy()
        result.assessment = label
        return result

    def _calculate_debt_score(self, avg_debt):
        for (mi, ma), sc in self.DEBT_SCORE_TABLE.items():
            if mi <= avg_debt <= ma: return float(sc)
        return 25.0

    def _calculate_request_score(self, amount, ref):
        ratio = amount / max(1, ref)
        if ratio <= 1.0: return 100.0
        return round(100.0 * math.exp(-0.3 * (ratio - 1.0)), 1)

    def _calculate_note(self, score):
        for n, (mi, ma) in self.NOTE_RANGES.items():
            if mi <= score <= ma: return n
        return 'C'

    def _calculate_piotroski(self, net_profit, total_assets, total_liabilities, equity,
                              ebit, sales, current_assets=0, short_term_liabilities=0):
        """
        Piotroski F-Score: 9 binary kriter, 0-9 puan.
        Karlılık (F1-F4) + Kaldıraç/Likidite (F5-F7) + Verimlilik (F8-F9).
        Not: tek dönem verisi olduğundan geçmiş yıl kıyaslaması yapılamaz;
        o kriterler varlık bazlı eşik değerlerle yaklaştırılır.
        """
        score = 0

        # --- Karlılık Grubu (F1-F4) ---
        # F1: Pozitif net kar
        if net_profit > 0:
            score += 1
        # F2: Pozitif ROA (net_kar / toplam_varlık)
        roa = (net_profit / total_assets) if total_assets > 0 else 0
        if roa > 0:
            score += 1
        # F3: Pozitif işletme nakit akışı — EBIT proxy olarak kullanılır
        if ebit > 0:
            score += 1
        # F4: Nakit akışı / net kar > 1 (kaliteli kazanç) — EBIT/net_kar eşiği
        if net_profit > 0 and total_assets > 0 and (ebit / total_assets) > roa:
            score += 1

        # --- Kaldıraç / Likidite Grubu (F5-F7) ---
        # F5: Borç oranı düşük — toplam_borç / toplam_varlık < 0.6
        debt_ratio = (total_liabilities / total_assets) if total_assets > 0 else 1.0
        if debt_ratio < 0.6:
            score += 1
        # F6: Current ratio > 1.2
        cr = (current_assets / short_term_liabilities) if short_term_liabilities > 0 else 2.0
        if cr > 1.2:
            score += 1
        # F7: Özkaynak pozitif ve borç / özkaynak < 2
        if equity > 0 and (total_liabilities / equity) < 2.0:
            score += 1

        # --- Verimlilik Grubu (F8-F9) ---
        # F8: Varlık devir hızı > 0.5 (satışlar / toplam_varlık)
        asset_turnover = (sales / total_assets) if total_assets > 0 else 0
        if asset_turnover > 0.5:
            score += 1
        # F9: Brüt marj proxy — EBIT / satışlar > 0.05
        if sales > 0 and (ebit / sales) > 0.05:
            score += 1

        if score >= 7:
            grade = "Güçlü"
        elif score >= 4:
            grade = "Orta"
        else:
            grade = "Zayıf"

        return score, grade

    def _calculate_limit_recommendation(self, score, note, amount, lang):
        if note == 'A': return amount, "Tam Onay"
        if note == 'B': return amount * 0.5, "Kısmi Onay (%50)"
        return 0, "Reddedildi"