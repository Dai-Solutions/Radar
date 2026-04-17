import sys
import os
from datetime import datetime, timedelta

# Proje dizinini ekle
sys.path.append('/home/dai/Desktop/DAI/Projects/Kredi_Puanı')

from database import get_session, Musteri, Aging, KrediTalep, KrediSkoru, init_db
from credit_scoring import KrediScorer
from aging_analyzer import AgingAnalyzer, AgingRecord

def seed_advanced():
    # Eski DB'yi temizle veya yeni kayıtlar ekle
    session = get_session()
    
    # Mevcut test datalarını temizle (Çakışma önlemek için)
    session.query(Musteri).filter(Musteri.cari_kod.in_(['MODA-TREND', 'KRIZ-GIDA'])).delete(synchronize_session=False)
    session.commit()
    
    # 1. İYİYE GİDEN MODA (Momentum Bonusu + Karlı)
    m1 = Musteri(
        cari_kod="MODA-TREND",
        cari_ad="Trend Moda Tekstil Ltd",
        oz_kaynak=5000000,
        donen_varliklar=4000000,
        kisa_vadeli_borclar=2000000,
        yillik_net_kar=1500000, # Çok karlı
        likidite_orani=2.0,
        sektor_risk_katsayisi=1.1
    )
    session.add(m1)
    session.flush()
    # İlk 3 ay 25 gün gecikme, son 3 ay 0 gün (İYİLEŞME)
    for i in range(3):
        session.add(Aging(musteri_id=m1.id, donem=f"2023-1{i}", vadesi_gecmis=10000, gun_1_30=50000, tip='gecmis')) # Kötü dönem
    for i in range(3):
        session.add(Aging(musteri_id=m1.id, donem=f"2024-0{i+1}", vadesi_gecmis=0, gun_1_30=0, tip='gecmis')) # Mükemmel dönem

    # 2. KRİZ GIDA (Negatif Momentum + Zarar)
    m2 = Musteri(
        cari_kod="KRIZ-GIDA",
        cari_ad="Kriz Gıda Lojistik",
        oz_kaynak=10000000,
        donen_varliklar=8000000,
        kisa_vadeli_borclar=6000000,
        yillik_net_kar=-2000000, # Zarar ediyor
        likidite_orani=1.33,
        sektor_risk_katsayisi=1.0
    )
    session.add(m2)
    session.flush()
    # İlk 3 ay 0 gecikme, son 3 ay artan gecikmeler (KÖTÜLEŞME)
    for i in range(3):
        session.add(Aging(musteri_id=m2.id, donem=f"2023-1{i}", vadesi_gecmis=0, gun_1_30=0, tip='gecmis')) # İyi dönem
    for i in range(3):
        session.add(Aging(musteri_id=m2.id, donem=f"2024-0{i+1}", vadesi_gecmis=50000, gun_1_30=150000, tip='gecmis')) # Giderek bozulan

    session.commit()
    print("Momentum ve Karlılık senaryoları eklendi!")
    session.close()

if __name__ == "__main__":
    seed_advanced()
