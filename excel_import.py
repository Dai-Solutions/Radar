"""
Excel Import - Aging Report Excel Import
Reads aging data from Excel files and imports it into the system
"""

import pandas as pd
from typing import List, Dict, Optional, Tuple
from datetime import datetime
from aging_analyzer import AgingRecord
import os

class ExcelImporter:
    """Class that imports aging data from Excel files"""
    
    # Expected column names (for flexible matching)
    COLUMN_MAPPING = {
        'account_code': ['account_code', 'account code', 'code', 'customer_code', 'cari_kod', 'carikod'],
        'account_name': ['account_name', 'account name', 'name', 'customer_name', 'cari_ad', 'cariad'],
        'overdue': ['overdue', 'vadesi_gecmis', 'vadesi_geçmiş', 'vadesi geçmiş'],
        'days_1_30': ['days_1_30', '1-30 days', '1-30 gun', '1-30 gün', 'gun_1_30'],
        'days_31_60': ['days_31_60', '31-60 days', '31-60 gun', '31-60 gün', 'gun_31_60'],
        'days_61_90': ['days_61_90', '61-90 days', '61-90 gun', '61-90 gün', 'gun_61_90'],
        'days_90_plus': ['days_90_plus', '90 plus', '90+ days', '90 ustu', 'gun_90_uslu'],
        
        # Balance Sheet Columns
        'equity': ['equity', 'oz_kaynak', 'ozkaynak', 'oz sermaye', 'öz kaynak', 'özkaynak'],
        'current_assets': ['current_assets', 'donen_varliklar', 'donen_varlıklar', 'donen varlıklar', 'dönen varlıklar'],
        'short_term_liabilities': ['short_term_liabilities', 'kisa_vadeli_borclar', 'kısa_vadeli_borçlar', 'st_liabilities'],
        'net_profit': ['net_profit', 'annual_profit', 'net_kar', 'yillik_kar', 'profit', 'yıllık net kar'],
        'sector_risk': ['sector_risk', 'sektor_risk', 'sektor_katsayisi', 'risk_katsayisi', 'sektör risk'],
        'tax_no': ['tax_no', 'vergi_no', 'vkn', 'vergi no', 'vergi numarası']
    }
    
    def __init__(self):
        self.last_error = None
    
    def excel_to_aging_records(self, file_path: str, sheet: str = None) -> Tuple[List[AgingRecord], Dict[str, str]]:
        """
        Read Excel file and convert to AgingRecord list
        Format: | Account Code | Account Name | Overdue | 1-30 Days | ... |
        Returns: (aging_records_list, customer_info_dict)
        """
        try:
            # Read Excel file
            if file_path.endswith('.csv'):
                df = pd.read_csv(file_path)
            else:
                if sheet:
                    df = pd.read_excel(file_path, sheet_name=sheet)
                else:
                    df = pd.read_excel(file_path, sheet_name=0)
            
            # Normalize column names
            df = self._normalize_column_names(df)
            
            # Check required columns
            required_columns = ['account_code', 'account_name']
            for col in required_columns:
                if col not in df.columns:
                    self.last_error = f"Required column not found: {col}"
                    return None, {}
            
            aging_records = []
            customer_info = {}
            
            # Convert each row to AgingRecord
            for idx, row in df.iterrows():
                account_code = str(row.get('account_code', '')).strip()
                account_name = str(row.get('account_name', '')).strip()
                
                if not account_code:
                    continue
                
                overdue = self._get_column_value(row, 'overdue', 0)
                days_1_30 = self._get_column_value(row, 'days_1_30', 0)
                days_31_60 = self._get_column_value(row, 'days_31_60', 0)
                days_61_90 = self._get_column_value(row, 'days_61_90', 0)
                days_90_plus = self._get_column_value(row, 'days_90_plus', 0)
                
                total_debt = overdue + days_1_30 + days_31_60 + days_61_90 + days_90_plus
                
                period = row.get('period', row.get('donem', 'past'))
                
                record = AgingRecord(
                    period=str(period),
                    overdue=overdue,
                    days_1_30=days_1_30,
                    days_31_60=days_31_60,
                    days_61_90=days_61_90,
                    days_90_plus=days_90_plus,
                    total_debt=total_debt,
                    type='past' # Default
                )
                
                aging_records.append(record)
                customer_info[account_code] = account_name
            
            return aging_records, customer_info
            
        except Exception as e:
            self.last_error = f"Excel reading error: {str(e)}"
            return None, {}
    
    def _normalize_column_names(self, df: pd.DataFrame) -> pd.DataFrame:
        """Normalize column names (lowercase, replace Turkish chars)"""
        new_columns = {}
        for col in df.columns:
            col_norm = col.lower().strip()
            col_norm = col_norm.replace('ş', 's').replace('ı', 'i').replace('ğ', 'g')
            col_norm = col_norm.replace('ü', 'u').replace('ö', 'o').replace('ç', 'c')
            col_norm = col_norm.replace(' ', '_')
            
            # Check against mapping
            for internal_name, mappings in self.COLUMN_MAPPING.items():
                if col_norm in mappings:
                    col_norm = internal_name
                    break
            
            new_columns[col] = col_norm
        
        df = df.rename(columns=new_columns)
        return df
    
    def excel_to_balance_sheet(self, file_path: str) -> List[Dict]:
        """Read financial data (Balance Sheet) from Excel"""
        try:
            df = pd.read_excel(file_path)
            df = self._normalize_column_names(df)
            
            if 'account_code' not in df.columns:
                self.last_error = "Account Code column not found."
                return []
                
            balance_sheet_list = []
            for _, row in df.iterrows():
                account_code = str(row.get('account_code', '')).strip()
                if not account_code: continue
                
                current_assets = self._get_column_value(row, 'current_assets', 0)
                short_term_liabilities = self._get_column_value(row, 'short_term_liabilities', 0)
                
                if short_term_liabilities > 0:
                    liquidity_ratio = current_assets / short_term_liabilities
                elif current_assets > 0:
                    liquidity_ratio = 10.0
                else:
                    liquidity_ratio = 1.0
                
                balance_sheet_list.append({
                    'account_code': account_code,
                    'account_name': str(row.get('account_name', '')).strip(),
                    'equity': self._get_column_value(row, 'equity', 0),
                    'current_assets': current_assets,
                    'short_term_liabilities': short_term_liabilities,
                    'liquidity_ratio': liquidity_ratio,
                    'net_profit': self._get_column_value(row, 'net_profit', 0),
                    'sector_risk_factor': self._get_column_value(row, 'sector_risk', 1.0),
                    'tax_no': str(row.get('tax_no', '')).strip() if 'tax_no' in row.index else ''
                })
            return balance_sheet_list
        except Exception as e:
            self.last_error = f"Balance sheet reading error: {str(e)}"
            return []

    def _get_column_value(self, row: pd.Series, key: str, default=0):
        """Get column value based on key/mapping with strict type validation"""
        if key in row.index:
            try:
                val = row[key]
                if pd.isna(val) or val == '': 
                    return default
                
                # Strip non-numeric artifacts if it's a string disguised as a number
                if isinstance(val, str):
                    val = val.replace(',', '').replace(' ', '')
                
                return float(val)
            except (ValueError, TypeError):
                # Log invalid data types if necessary (silent default for now)
                return default
        return default
    
    def create_template(self, file_path: str):
        """Creates sample Excel template"""
        data = {
            'account_code': ['C001', 'C002'],
            'account_name': ['Sample Corp', 'Test Ltd'],
            'overdue': [0, 15000],
            'days_1_30': [150000, 80000],
            'equity': [2500000, 1200000],
            'net_profit': [450000, -150000],
            'tax_no': ['1234567890', '0987654321']
        }
        df = pd.DataFrame(data)
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        df.to_excel(file_path, index=False)
        return file_path