"""
Multi-Currency Support
Phase 8: Internationalization
"""

from datetime import datetime, timedelta
import requests
from functools import lru_cache

SUPPORTED_CURRENCIES = {
    'TL': {'name': 'Turkish Lira', 'symbol': '₺', 'code': 'TRY'},
    'USD': {'name': 'US Dollar', 'symbol': '$', 'code': 'USD'},
    'EUR': {'name': 'Euro', 'symbol': '€', 'code': 'EUR'},
    'GBP': {'name': 'British Pound', 'symbol': '£', 'code': 'GBP'},
}

class CurrencyConverter:
    """Handle currency conversions and rates"""
    
    # Simple in-memory cache
    _rate_cache = {}
    _cache_expiry = None
    CACHE_DURATION = timedelta(hours=1)
    
    @classmethod
    def _get_exchange_rates(cls):
        """Fetch exchange rates from public API"""
        try:
            # Using exchangerate-api.com free tier
            response = requests.get(
                'https://api.exchangerate-api.com/v4/latest/TRY',
                timeout=5
            )
            if response.status_code == 200:
                return response.json().get('rates', {})
        except Exception as e:
            print(f'Exchange rate fetch error: {str(e)}')
        
        # Fallback rates (last known)
        return {
            'TRY': 1.0,
            'USD': 0.033,  # 1 TL ≈ 0.033 USD (approximate)
            'EUR': 0.031,  # 1 TL ≈ 0.031 EUR (approximate)
            'GBP': 0.027,  # 1 TL ≈ 0.027 GBP (approximate)
        }
    
    @classmethod
    def get_rates(cls, base_currency='TRY', force_refresh=False):
        """Get current exchange rates"""
        now = datetime.utcnow()
        
        # Check cache validity
        if not force_refresh and cls._cache_expiry and now < cls._cache_expiry and cls._rate_cache:
            return cls._rate_cache
        
        # Fetch new rates
        if base_currency == 'TRY':
            cls._rate_cache = cls._get_exchange_rates()
        else:
            # Normalize to TRY base, then convert
            rates_try = cls._get_exchange_rates()
            rate_from_try = rates_try.get(base_currency, 1.0)
            
            cls._rate_cache = {
                curr: (rate / rate_from_try) if rate_from_try > 0 else 1.0
                for curr, rate in rates_try.items()
            }
        
        cls._cache_expiry = now + cls.CACHE_DURATION
        return cls._rate_cache
    
    @classmethod
    def convert(cls, amount, from_currency, to_currency):
        """Convert amount from one currency to another"""
        if from_currency == to_currency:
            return amount
        
        rates = cls.get_rates(from_currency)
        
        if to_currency not in rates:
            raise ValueError(f'Unsupported currency: {to_currency}')
        
        return amount * rates[to_currency]
    
    @classmethod
    def format_currency(cls, amount, currency):
        """Format amount as currency string"""
        currency_info = SUPPORTED_CURRENCIES.get(currency.upper())
        if not currency_info:
            return f"{amount:,.2f} {currency}"
        
        symbol = currency_info['symbol']
        return f"{symbol}{amount:,.2f}"


# Multi-currency configuration per tenant
class TenantCurrencyConfig:
    """Tenant-specific currency settings"""
    
    def __init__(self, tenant_id, base_currency='TL', supported_currencies=None):
        self.tenant_id = tenant_id
        self.base_currency = base_currency
        self.supported_currencies = supported_currencies or list(SUPPORTED_CURRENCIES.keys())
        self.exchange_rate_provider = 'exchangerate-api'
        self.rounding_precision = 2
    
    def to_dict(self):
        return {
            'tenant_id': self.tenant_id,
            'base_currency': self.base_currency,
            'supported_currencies': self.supported_currencies,
            'exchange_rate_provider': self.exchange_rate_provider,
            'rounding_precision': self.rounding_precision
        }


# Currency-aware operations
def convert_credit_limit(limit_amount, from_currency, to_currency):
    """Convert credit limit between currencies"""
    return CurrencyConverter.convert(limit_amount, from_currency, to_currency)


def calculate_interest_in_currency(principal, annual_rate, days, currency):
    """Calculate interest in specific currency"""
    interest = principal * (annual_rate / 100) * (days / 365)
    return interest


def format_financial_metric(value, currency):
    """Format financial metric for display"""
    return CurrencyConverter.format_currency(value, currency)


# Currency exchange history tracking
class ExchangeRateHistory:
    """Track exchange rate changes for audit/reporting"""
    
    def __init__(self):
        self.history = []
    
    def record_rate(self, from_currency, to_currency, rate, timestamp=None):
        """Record a rate conversion for history"""
        if not timestamp:
            timestamp = datetime.utcnow()
        
        self.history.append({
            'from': from_currency,
            'to': to_currency,
            'rate': rate,
            'timestamp': timestamp
        })
    
    def get_average_rate(self, from_currency, to_currency, days=30):
        """Get average rate over period"""
        cutoff = datetime.utcnow() - timedelta(days=days)
        
        relevant = [
            h for h in self.history
            if h['from'] == from_currency and h['to'] == to_currency
            and h['timestamp'] >= cutoff
        ]
        
        if not relevant:
            return None
        
        avg_rate = sum(h['rate'] for h in relevant) / len(relevant)
        return avg_rate
