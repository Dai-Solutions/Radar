"""
Credit Scoring Algorithm
3-factor scoring: History + Future + Request
"""

from dataclasses import dataclass, field
from typing import Optional, List
import math
from aging_analyzer import AgingAnalysis, AgingRecord, AgingAnalyzer

class ScenarioResult:
    def __init__(self, name, description, impact, score):
        self.name = name
        self.description = description
        self.impact = impact
        self.score = score

from translations import translations

@dataclass
class CreditRequestInput:
    """Credit request technical details"""
    account_code: str
    request_amount: float
    request_date: str  # Format: "2024-01-01"

@dataclass
class CreditScoreResult:
    """Credit scoring final result"""
    account_code: str
    account_name: str
    
    # Score components
    historical_score: float
    future_score: float
    request_score: float
    debt_score: float
    
    # Final
    final_score: float
    credit_note: str  # A, B, C
    
    # Details
    avg_delay_days: float
    avg_debt: float
    future_6_months_total: float
    request_amount: float
    
    # Limit recommendation
    recommended_limit: float
    recommendation_message: str
    
    # Qualitative assessment and scenarios
    assessment: str = ""
    scenarios: List = field(default_factory=list)
    
    # Trend and additional data
    momentum_score: float = 0
    trend_direction: str = 'stable'
    max_capacity: float = 0
    decision_summary: str = ""
    
    # Z-Score Data
    
    # Profitability Impact


class CreditScorer:
    """Credit scoring engine"""
    
    def __init__(self, aging_analyzer: Optional[AgingAnalyzer] = None):
        self.aging_analyzer = aging_analyzer or AgingAnalyzer()
    
    # Weights
    WEIGHT_HISTORY = 0.45
    WEIGHT_FUTURE = 0.30
    WEIGHT_REQUEST = 0.25
    
    DECAY_K_REQUEST = 0.3  # Speed of score reduction as request ratio increases
    
    # Note ranges
    NOTE_RANGES = {
        'A': (80, 100),
        'B': (60, 79.9),
        'C': (0, 59.9)
    }
    
    # Debt score table
    DEBT_SCORE_TABLE = {
        (0, 25000): 100,
        (25001, 75000): 75,
        (75001, 150000): 50,
        (150001, 999999999): 25
    }
    
    # Request score table (request / avg_debt ratio)
    REQUEST_SCORE_TABLE = {
        (0, 1): 100,        # Safe
        (1.01, 2): 90,      # Moderate
        (2.01, 3): 75,      # Normal
        (3.01, 5): 50,      # Warning
        (5.01, 10): 30,     # Risky
        (10.01, 999999): 10 # Very risky
    }
    
    # Note messages (will be translated via app logic usually, but keep as internal defaults)
    NOTE_MESSAGES = {
        'A': "Excellent! Credit suitable for the full requested amount.",
        'B': "Risky (Yellow Alert). Credit suitable for 50% of the requested amount.",
        'C': "Very Risky (Red Alert). Credit absolutely not recommended."
    }
    
    # Altman Z-Score Interpretation
    Z_SAFE_ZONE = 2.9
    Z_GREY_ZONE = 1.23

    def calculate(self, aging_analysis: AgingAnalysis, request_input: CreditRequestInput, 
                 base_volume: float = 0, interest_rate: float = 45.0, skip_scenarios: bool = False,
                 equity: float = 0, liquidity: float = 1.0, net_profit: float = 0,
                 sector_risk: float = 1.0, 
                 total_assets: float = 0, total_liabilities: float = 0, 
                 retained_earnings: float = 0, ebit: float = 0, sales: float = 0,
        """
        Calculate credit score (with Veto, Macro Stress & Altman Z-Score)
        """
        # 0. Altman Z-Score Analysis (Z' for Private Firms)
        
        if total_assets > 0:
            A = (working_capital or 0) / total_assets
            B = (retained_earnings or 0) / total_assets
            C = (ebit or 0) / total_assets
            D = (equity or 0) / (total_liabilities or 1)
            E = (sales or 0) / total_assets
            
            if lang == 'tr':
            else:

        # 0.1 Macro Context Calculations
        interest_rate = float(interest_rate)
        # Real Debt erosion factor
        real_debt_value = max(aging_analysis.avg_debt, base_volume) * (1.0 - erosion_factor)
        
        # Determine suggested term (Vade Stratejisi)
        

        # 1. Component scores
        historical_score = aging_analysis.historical_score
        future_score = self.aging_analyzer._calculate_future_score(
            aging_analysis.future_total_debt, aging_analysis.avg_debt, base_volume, interest_rate=interest_rate
        )
        debt_score = self._calculate_debt_score(max(aging_analysis.avg_debt, base_volume))
        request_score = self._calculate_request_score(request_input.request_amount, max(aging_analysis.avg_debt, base_volume))
        
        # 2. Raw score & Veto
        if aging_analysis.avg_debt == 0:
            raw_score = (future_score * 0.7) + (request_score * 0.3)
            veto_factor = 1.0
        else:
            raw_score = (historical_score * self.WEIGHT_HISTORY + future_score * self.WEIGHT_FUTURE + request_score * self.WEIGHT_REQUEST)
            veto_factor = 0.5 if historical_score < 40 else (0.8 if historical_score < 60 else 1.0)
        
        # 3. Macro Multiplier
        
        # 4. Momentum Impact
        trend_impact = (aging_analysis.momentum_score * 15) if aging_analysis.trend_direction == 'declining' else (aging_analysis.momentum_score * 5 if aging_analysis.trend_direction == 'improving' else 0)
        final_score += trend_impact
        
        # 5. Profitability Impact
        profit_impact = -10 if net_profit < 0 else (10 if (net_profit / max(1, aging_analysis.total_debt)) > 0.15 else (5 if (net_profit / max(1, aging_analysis.total_debt)) > 0.05 else 0))
        final_score += profit_impact
        
        # 6. Z-Score Impact
        final_score += z_impact

        final_score = max(0, min(100, final_score))
        credit_note = self._calculate_note(final_score)
        
        # 7. Recommendation & Capacity
        rec_limit, rec_msg = self._calculate_limit_recommendation(final_score, credit_note, request_input.request_amount, lang)
        max_cap = self._calculate_max_capacity(equity, liquidity, aging_analysis.avg_debt, credit_note, interest_rate, sector_risk)
        
        result_obj = CreditScoreResult(
            account_code=aging_analysis.account_code,
            account_name=aging_analysis.account_name,
            historical_score=historical_score, future_score=future_score,
            request_score=request_score, debt_score=debt_score,
            final_score=final_score, credit_note=credit_note,
            avg_delay_days=aging_analysis.avg_delay_days, avg_debt=aging_analysis.avg_debt,
            future_6_months_total=aging_analysis.future_total_debt, request_amount=request_input.request_amount,
            recommended_limit=rec_limit, recommendation_message=rec_msg,
            max_capacity=max_cap, momentum_score=aging_analysis.momentum_score,
        )

        result_obj.decision_summary = self._create_decision_summary(result_obj, lang)

        if not skip_scenarios:
            result_obj.scenarios = self._probability_analysis(aging_analysis, request_input, base_volume, interest_rate, equity, liquidity, sector_risk, lang)
        
        return result_obj

    def _create_decision_summary(self, res: CreditScoreResult, lang='tr') -> str:
        """Rule-based Decision Logic using Template Library"""
        t = translations[lang]['decision_details']
        
        # Priority 1: Critical Failures
        if res.historical_score < 40 or res.final_score < 40:
            return t['rejected_low_perf']
            
        # Priority 2: Full Approval (A Note + High Liquidity)
        if res.credit_note == 'A':
            return t['approved_full']
            
        # Priority 3: Partial Approval (B Note or Capacity Warning)
        if res.credit_note == 'B':
            percent = 50 if res.historical_score < 60 else 75
            return t['approved_partial'].replace('%{percent}', str(percent))
            
        # Priority 4: Default Rejection
        return t['rejected_risk_limits']

    def _calculate_max_capacity(self, equity, liquidity, avg_debt, note, interest_rate, sector_risk=1.0) -> float:
        """Capacity calculation logic"""
        balance_based_limit = (float(equity or 0) * 0.5 * float(liquidity or 1.0))
        volume_based_limit = float(avg_debt or 0) * 2.0
        
        base_capacity = max(balance_based_limit, volume_based_limit)
        
        note_multipliers = {'A': 1.5, 'B': 1.0, 'C': 0.0}
        sc_mult = note_multipliers.get(note, 0.0)
        
        

        """Advanced Rule-Based Expert Assessment System"""
        t = translations[lang]['expert_assessments']
        notes = []
        
        # 1. Payment History & Discipline
        if res.historical_score < 60:
            impact_val = (60 - res.historical_score) / 2.0
            notes.append(t['weak_discipline'].format(delay=res.avg_delay_days, impact=impact_val))
            
        # 2. Request & Capacity Analysis
        if res.request_score < 60:
            notes.append(t['high_request'])
        if res.request_amount > res.max_capacity and res.max_capacity > 0:
            notes.append(t['capacity_exceeded'].format(request=res.request_amount, max=res.max_capacity))
        elif res.future_score < 50:
            notes.append(t['debt_strain'].format(ratio=(res.future_6_months_total/res.avg_debt)*10 if res.avg_debt else 0))
            
        # 3. Macroeconomic Analysis (The Analysis Depth requested by the user)
            
        # 4. Solvency & Liquidity (Intelligence Layer)
        if liquidity < 1.0:
            notes.append(t['liquidity_low'].format(ratio=liquidity))
        if net_profit > 0 and (net_profit / max(1, res.avg_debt)) < 0.05:
            notes.append(t['profit_low'])
            notes.append(t['zscore_danger'])
        if res.trend_direction == 'declining':
            notes.append(t['momentum_negative'])
            
        return " ".join(notes)

    def _probability_analysis(self, aging_analysis, request_input, base_volume, current_rate, equity=0, liquidity=1.0, sector_risk=1.0, lang='tr') -> list:
        """Simulates scores under different market scenarios"""
        scenarios = []
        
        # Scenario 1: Interest Rate Drops
        optimistic_rate = max(current_rate - 15, 10)
        s_optimistic = self.calculate(aging_analysis, request_input, base_volume, optimistic_rate, 
                                     skip_scenarios=True, equity=equity, liquidity=liquidity, sector_risk=sector_risk, lang=lang)
        
        current_score = self.calculate(aging_analysis, request_input, base_volume, current_rate, 
                                      skip_scenarios=True, equity=equity, liquidity=liquidity, sector_risk=sector_risk, lang=lang).final_score
                                      
        if lang == 'tr':
            scenarios.append({
                "title": "Piyasa İyimserliği",
                "detail": f"Faiz oranları %{optimistic_rate} seviyesine düşerse",
                "impact": round(s_optimistic.final_score - current_score, 1),
                "score": s_optimistic.final_score
            })
        else:
            scenarios.append({
                "title": "Market Optimism",
                "detail": f"If interest rates drop to {optimistic_rate}%",
                "impact": round(s_optimistic.final_score - current_score, 1),
                "score": s_optimistic.final_score
            })
        
        # Scenario 2: Discipline / Acceleration Improvement
        if aging_analysis.avg_delay_days > 0:
            import copy
            better_aging = copy.deepcopy(aging_analysis)
            # Acceleration: Reduce delay days by 50%
            better_aging.avg_delay_days = aging_analysis.avg_delay_days * 0.5
            better_aging.historical_score = min(100, aging_analysis.historical_score + 15)
            
            s_accel = self.calculate(better_aging, request_input, base_volume, current_rate, 
                                   skip_scenarios=True, equity=equity, liquidity=liquidity, sector_risk=sector_risk, lang=lang)
            
            if lang == 'tr':
                scenarios.append({
                    "title": "Hızlı Tahsilat İvmesi",
                    "detail": "Ortalama tahsilat hızı %50 artarsa",
                    "impact": round(s_accel.final_score - current_score, 1),
                    "score": s_accel.final_score
                })
            else:
                scenarios.append({
                    "title": "Payment Acceleration",
                    "detail": "If average collection speed increases by 50%",
                    "impact": round(s_accel.final_score - current_score, 1),
                    "score": s_accel.final_score
                })
            
        return scenarios
    
    def _calculate_debt_score(self, avg_debt: float) -> float:
        """Debt score based on average debt"""
        for (min_debt, max_debt), score in self.DEBT_SCORE_TABLE.items():
            if min_debt <= avg_debt <= max_debt:
                return float(score)
        return 25
    
    def _calculate_request_score(self, request_amount: float, reference_volume: float) -> float:
        """Request score based on ratio to reference volume"""
        if reference_volume <= 0:
            return 20.0
        
        ratio = request_amount / reference_volume
        
        if ratio <= 1.0:
            return 100.0
            
        score = 100.0 * math.exp(-self.DECAY_K_REQUEST * (ratio - 1.0))
        return round(float(score), 1)
    
    def _calculate_note(self, final_score: float) -> str:
        """Determines note based on final score"""
        for note, (min_score, max_score) in self.NOTE_RANGES.items():
            if min_score <= final_score <= max_score:
                return note
        return 'C'
    
    def _calculate_limit_recommendation(self, final_score: float, note: str, request_amount: float, lang='tr') -> tuple:
        """Limit recommendation based on note and requested amount"""
        if note == 'A':
            msg = "Mükemmel! Talep edilen tutarın tamamı için kredi uygundur." if lang == 'tr' else "Excellent! Credit suitable for the full requested amount."
            return request_amount, msg
        elif note == 'B':
            recommendation = request_amount * 0.50
            if lang == 'tr':
                 return recommendation, "Risk düzeyi orta (Sarı Alarm). %50 limit önerilir. Önerilen limit: " + f"{recommendation:,.0f} TL"
            return recommendation, "Moderate Risk (Yellow Alert). 50% limit recommended. Recommended limit: " + f"{recommendation:,.0f} TL"
        else:
            msg = "Çok Riskli (Kırmızı Alarm). Kredi kesinlikle önerilmez." if lang == 'tr' else "Very Risky (Red Alert). Credit absolutely not recommended."
            return 0, msg
    
    def get_report(self, result: CreditScoreResult) -> str:
        """Generates detailed report (Text based internal version)"""
        report = f"""
╔══════════════════════════════════════════════════════╗
║           CREDIT SCORING REPORT                      ║
╠══════════════════════════════════════════════════════╣
Account Code  : {result.account_code}
Account Name  : {result.account_name}
Requested Amt : {result.request_amount:,.2f} TL

─────────────────────────────────────────────
SCORE COMPONENTS
─────────────────────────────────────────────
Historical Score : {result.historical_score} / 100
Future Score     : {result.future_score} / 100
Request Score    : {result.request_score} / 100

─────────────────────────────────────────────
SONUÇ / RESULT
─────────────────────────────────────────────
FINAL SCORE   : {result.final_score:.1f} / 100
CREDIT NOTE   : {result.credit_note}

RECOMMENDED LIMIT : {result.recommended_limit:,.2f} TL
{result.recommendation_message}
╚══════════════════════════════════════════════════════╝
"""
        return report
