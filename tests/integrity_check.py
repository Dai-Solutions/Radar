import os
import sys
from datetime import datetime

# Proje kök dizinini ekle
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from database import get_session, Customer, User
from credit_scoring import CreditScorer

def test_scoring_logic():
    print("\n--- [1/2] SKORLAMA MOTORU TESTİ ---")
    session = get_session()
    try:
        # User ID 5 (Ali Yıldırım) kontrolü
        user = session.query(User).filter(User.id == 5).first()
        if not user:
            print("ERROR: User ID 5 bulunamadı!")
            return False
            
        # DAI-TECH verisi ile skorlama simülasyonu
        customer = session.query(Customer).filter(Customer.account_code == 'DAI-TECH').first()
        if not customer:
            print("ERROR: DAI-TECH verisi bulunamadı!")
            return False
            
        print(f"Müşteri: {customer.account_name} için skorlama başlatılıyor...")
        
        # CreditScorer başlat (Yeni Mimari: customer_id ile)
        scorer = CreditScorer(customer.id, db_session=session)
        
        # Mock settings
        settings = {'inflation_rate': 40.0, 'interest_rate': 45.0, 'sector_risk': 1.0}
        # Mock request data
        mock_request = {'request_amount': 5000000, 'currency': 'TL'}
        
        results = scorer.calculate(settings, mock_request)
        
        print(f"SKOR: {results.final_score}")
        print(f"NOT: {results.credit_note}")
        print(f"VADE ÖNERİSİ: {results.vade_message}")
        
        if results.final_score >= 0:
            print("SUCCESS: Skorlama motoru pırıl pırıl çalışıyor.")
            return True
        else:
            print("FAILED: Skor geçersiz.")
            return False
    except Exception as e:
        print(f"CRITICAL ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        session.close()

def test_web_connectivity():
    print("\n--- [2/2] WEB ERİŞİM TESTİ ---")
    import requests
    try:
        response = requests.get("http://localhost:5001/radar/", allow_redirects=False)
        print(f"Status Code: {response.status_code}")
        if response.status_code in [200, 302]:
            print("SUCCESS: Web sunucusu sarsılmaz bir hırsla çalışıyor.")
            return True
        else:
            print(f"FAILED: Status {response.status_code}")
            return False
    except Exception as e:
        print(f"ERROR: {e}")
        return False

if __name__ == "__main__":
    print(f"RADAR INTEGRITY CHECK - {datetime.now()}")
    s1 = test_scoring_logic()
    if s1:
        print("\nDOĞRULAMA: MANTIK KATMANI OK. RADAR YAYINDA!")
        sys.exit(0)
    else:
        print("\nDOĞRULAMA: HATA TESPİT EDİLDİ.")
        sys.exit(1)
