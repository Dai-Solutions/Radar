"""
Aging Analyzer - 12-Month Aging Report Analysis
Performs analysis for Past 6 months + Future 6 months
"""

from dataclasses import dataclass
from typing import List, Dict, Optional
import math
from datetime import datetime, date
import calendar

@dataclass
class AgingRecord:
    """Aging record for a single period"""
    period: str  # Format: "2024-01"
    overdue: float = 0
    days_1_30: float = 0
    days_31_60: float = 0
    days_61_90: float = 0
    days_90_plus: float = 0
    total_debt: float = 0
    # Type: 'past' or 'future'
    type: str = 'past'

@dataclass
class AgingAnalysis:
    """12-month aging analysis result"""
    account_code: str
    account_name: str
    
    # Historical 6-month totals
    historical_total_debt: float = 0
    historical_overdue: float = 0
    historical_days_1_30: float = 0
    historical_days_31_60: float = 0
    historical_days_61_90: float = 0
    historical_days_90_plus: float = 0
    
    # Future 6-month totals
    future_total_debt: float = 0
    future_overdue: float = 0
    future_days_1_30: float = 0
    future_days_31_60: float = 0
    future_days_61_90: float = 0
    future_days_90_plus: float = 0
    
    # Calculated values
    avg_delay_days: float = 0
    avg_debt: float = 0
    
    # Scores
    historical_score: float = 0
    future_score: float = 0
    
    # Trend/Momentum data
    momentum_score: float = 0 # between -1 and +1
    trend_direction: str = 'stable' # improving, declining, stable
    delay_volatility: float = 0 # Standard deviation of delay days
    
    @property
    def total_debt(self) -> float:
        return self.historical_total_debt + self.future_total_debt
    
    @property
    def total_delay_amount(self) -> float:
        """Total overdue amount (overdue + 1-30 + 31-60 + 61-90 + 90+)"""
        return (self.historical_overdue + self.historical_days_1_30 + 
                self.historical_days_31_60 + self.historical_days_61_90 + self.historical_days_90_plus)


class AgingAnalyzer:
    """Class that analyzes aging data"""
    
    # Average delay days by range
    AVERAGE_DAYS = {
        'overdue': 0,      # Overdue = 0 days (already due)
        'days_1_30': 15,    # 1-30 days = average 15 days
        'days_31_60': 45,   # 31-60 days = average 45 days
        'days_61_90': 75,   # 61-90 days = average 75 days
        'days_90_plus': 100 # 90+ days = average 100 days
    }
    
    DECAY_K_HISTORY = 0.04  # Speed of score reduction as delay days increase
    DECAY_K_FUTURE = 0.5   # Speed of score reduction as future debt ratio increases
    
    def analyze(self, aging_records: List[AgingRecord], 
                account_code: str, account_name: str, **kwargs) -> AgingAnalysis:
        """
        Analyzes aging records
        Splits into Past 6 months and Future 6 months
        """
        analysis = AgingAnalysis(
            account_code=account_code,
            account_name=account_name
        )
        
        # Split past and future
        past_records = [r for r in aging_records if r.type == 'past']
        future_records = [r for r in aging_records if r.type == 'future']
        
        # Historical 6-month totals
        for record in past_records:
            analysis.historical_overdue += record.overdue
            analysis.historical_days_1_30 += record.days_1_30
            analysis.historical_days_31_60 += record.days_31_60
            analysis.historical_days_61_90 += record.days_61_90
            analysis.historical_days_90_plus += record.days_90_plus
        
        analysis.historical_total_debt = (
            analysis.historical_overdue + analysis.historical_days_1_30 + 
            analysis.historical_days_31_60 + analysis.historical_days_61_90 + 
            analysis.historical_days_90_plus
        )
        
        # Future 6-month totals
        for record in future_records:
            analysis.future_overdue += record.overdue
            analysis.future_days_1_30 += record.days_1_30
            analysis.future_days_31_60 += record.days_31_60
            analysis.future_days_61_90 += record.days_61_90
            analysis.future_days_90_plus += record.days_90_plus
        
        analysis.future_total_debt = (
            analysis.future_overdue + analysis.future_days_1_30 + 
            analysis.future_days_31_60 + analysis.future_days_61_90 + 
            analysis.future_days_90_plus
        )
        
        # Calculate average delay days and volatility
        analysis.avg_delay_days, analysis.delay_volatility = self._calculate_delay_metrics(past_records)
        
        # Market interest rate
        interest_rate = kwargs.get('interest_rate', 45.0)
        
        # Calculate average debt (past 6 months)
        if len(past_records) > 0:
            analysis.avg_debt = analysis.historical_total_debt / len(past_records)
        else:
            analysis.avg_debt = 0
        
        # Calculate scores (Continuous & Macro-Sensitive)
        analysis.historical_score = self._calculate_historical_score(
            analysis.avg_delay_days, 
            interest_rate=interest_rate
        )
        
        # Calculate future score
        analysis.future_score = self._calculate_future_score(
            analysis.future_total_debt, 
            analysis.avg_debt,
            interest_rate=interest_rate
        )
        
        # Trend / Momentum Analysis
        analysis.momentum_score, analysis.trend_direction = self._analyze_momentum(past_records)
        
        return analysis
        
    def _calculate_delay_metrics(self, past_records: List[AgingRecord]) -> tuple[float, float]:
        """
        Calculates average delay days and volatility (standard deviation)
        """
        if not past_records:
            return 0.0, 0.0
            
        individual_delays = []
        total_delay_amount = 0
        total_weighted_days = 0
        
        for record in past_records:
            record_amount = (record.overdue + record.days_1_30 + record.days_31_60 + 
                             record.days_61_90 + record.days_90_plus)
            
            if record_amount > 0:
                weighted_days = (
                    record.overdue * self.AVERAGE_DAYS['overdue'] +
                    record.days_1_30 * self.AVERAGE_DAYS['days_1_30'] +
                    record.days_31_60 * self.AVERAGE_DAYS['days_31_60'] +
                    record.days_61_90 * self.AVERAGE_DAYS['days_61_90'] +
                    record.days_90_plus * self.AVERAGE_DAYS['days_90_plus']
                )
                avg_days = weighted_days / record_amount
                individual_delays.append(avg_days)
                
                total_delay_amount += record_amount
                total_weighted_days += weighted_days
        
        if not individual_delays:
            return 0.0, 0.0
            
        avg_overall = total_weighted_days / total_delay_amount if total_delay_amount > 0 else 0
        
        # Calculate Standard Deviation (Volatility)
        if len(individual_delays) > 1:
            variance = sum((x - avg_overall) ** 2 for x in individual_delays) / len(individual_delays)
            std_dev = math.sqrt(variance)
        else:
            std_dev = 0.0
            
        return avg_overall, std_dev
    
    def _calculate_historical_score(self, avg_delay_days: float, interest_rate: float = 45.0) -> float:
        """
        Calculate historical score with Exponential Decay
        S = 100 * exp(-k * days)
        If interest rate is above 35%, k coefficient increases (Harsher penalty)
        """
        if avg_delay_days <= 0:
            return 100.0
            
        k = self.DECAY_K_HISTORY
        if interest_rate > 35.0:
            k = k * 1.2  # Delay is more risky in high interest environments
        
        score = 100.0 * math.exp(-k * avg_delay_days)
        return round(float(score), 1)
    
    def _calculate_future_score(self, future_total_debt: float, avg_debt: float, 
                             base_volume: float = 0, interest_rate: float = 45.0) -> float:
        """
        Calculate score based on the ratio of total future 6-month debt to historical average
        If ratio is > 1.0, score decreases exponentially.
        """
        reference_volume = max(avg_debt, base_volume)
        
        if reference_volume <= 0:
            return 50.0 if future_total_debt > 0 else 100.0
            
        ratio = future_total_debt / reference_volume
        
        if ratio <= 1.0:
            return 100.0
            
        score = 100.0 * math.exp(-self.DECAY_K_FUTURE * (ratio - 1.0))
        return round(float(score), 1)
    
    def _analyze_momentum(self, past_records: list[AgingRecord]) -> tuple[float, str]:
        """
        Compare last 3 months with previous 3 months to calculate trend.
        """
        if len(past_records) < 2:
            return 0.0, 'stable'
            
        sorted_records = sorted(past_records, key=lambda x: x.period, reverse=True)
        
        recent_3 = sorted_records[:3]
        older_recs = sorted_records[3:6]
        
        if not older_recs:
            return 0.0, 'stable'
            
        def calculate_avg_risk(records):
            if not records: return 0
            return sum(float(r.overdue or 0) + float(r.days_1_30 or 0) * 0.5 for r in records) / len(records)
            
        avg_recent = calculate_avg_risk(recent_3)
        avg_older = calculate_avg_risk(older_recs)
        
        if avg_older > 0:
            change_ratio = (avg_recent - avg_older) / avg_older
        else:
            change_ratio = 1.0 if avg_recent > 100 else 0.0
            
        if avg_recent > avg_older + 100: 
            momentum = -min(1.0, max(0.1, abs(change_ratio) / 2.0))
            return momentum, 'declining'
        elif avg_recent < avg_older - 100:
            momentum = min(1.0, max(0.1, abs(change_ratio) / 2.0))
            return momentum, 'improving'
        else:
            return 0.0, 'stable'

    def get_as_dict(self, analysis: AgingAnalysis) -> dict:
        """Returns analysis result as dict"""
        return {
            'account_code': analysis.account_code,
            'account_name': analysis.account_name,
            'historical_total_debt': analysis.historical_total_debt,
            'future_total_debt': analysis.future_total_debt,
            'total_debt': analysis.total_debt,
            'avg_delay_days': round(analysis.avg_delay_days, 1),
            'avg_debt': round(analysis.avg_debt, 2),
            'historical_score': analysis.historical_score,
            'future_score': analysis.future_score,
            'delay_details': {
                'overdue': analysis.historical_overdue,
                'days_1_30': analysis.historical_days_1_30,
                'days_31_60': analysis.historical_days_31_60,
                'days_61_90': analysis.historical_days_61_90,
                'days_90_plus': analysis.historical_days_90_plus
            }
        }