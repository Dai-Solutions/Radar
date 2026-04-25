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

class CreditScorer:
    """Credit scoring engine"""
    
    def __init__(self, customer_id=None, db_session=None, aging_analyzer=None, customer_data=None, aging_records=None):
        self.customer_id = customer_id
        self.session = db_session
        self.aging_analyzer = aging_analyzer or AgingAnalyzer()
        
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

    def calculate(self, settings, request_input, skip_scenarios=False, lang='tr'):
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

        # 5. Sonuçlar
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
        )

        result.decision_summary = self._create_decision_summary(result, lang)

        if not skip_scenarios:
            result.assessment = self._create_assessment(result, liquidity, net_profit, z_score, inflation_rate, lang)
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
        
        if not notes:
            notes.append(t['reliable_profile'])
            
        return " ".join(notes)

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

        return scenarios

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