"""
Radar - Örnek Müşteri & Kredi Talebi Seed Scripti
Sunucuda çalıştır:
  cd /home/daiadmin/apps/radar
  venv/bin/python3 seed_sample_data.py
"""
import sys, os, datetime, random
sys.path.insert(0, '.')
from dotenv import load_dotenv; load_dotenv()

from app import app

SAMPLE_CUSTOMERS = [
    {
        "account_code": "SMPL-001",
        "account_name": "Ege Tekstil San. ve Tic. A.Ş.",
        "tax_no": "1234567890",
        "phone": "02324001122",
        "sector": "manufacturing",
        "equity": 4_200_000,
        "annual_net_profit": 780_000,
        "current_assets": 2_900_000,
        "short_term_liabilities": 1_100_000,
        "total_assets": 8_500_000,
        "total_liabilities": 4_300_000,
        "retained_earnings": 1_800_000,
        "ebit": 1_100_000,
        "sales": 11_500_000,
        "working_capital": 1_800_000,
        "interest_expenses": 220_000,
        "principal_payments": 350_000,
        "aging": [
            {"period": "2024 Q1", "overdue": 0,       "days_1_30": 180_000, "days_31_60": 40_000, "days_61_90": 0,      "days_90_plus": 0},
            {"period": "2024 Q2", "overdue": 15_000,  "days_1_30": 210_000, "days_31_60": 55_000, "days_61_90": 10_000, "days_90_plus": 0},
            {"period": "2024 Q3", "overdue": 0,       "days_1_30": 195_000, "days_31_60": 30_000, "days_61_90": 0,      "days_90_plus": 0},
            {"period": "2024 Q4", "overdue": 0,       "days_1_30": 240_000, "days_31_60": 45_000, "days_61_90": 0,      "days_90_plus": 0},
        ],
        "requests": [
            {"amount": 500_000, "currency": "TL", "days_ago": 90},
            {"amount": 750_000, "currency": "TL", "days_ago": 30},
        ],
    },
    {
        "account_code": "SMPL-002",
        "account_name": "Akdeniz Gıda Dağıtım Ltd. Şti.",
        "tax_no": "9876543210",
        "phone": "02424113344",
        "sector": "retail",
        "equity": 1_500_000,
        "annual_net_profit": 210_000,
        "current_assets": 980_000,
        "short_term_liabilities": 670_000,
        "total_assets": 3_200_000,
        "total_liabilities": 1_700_000,
        "retained_earnings": 450_000,
        "ebit": 320_000,
        "sales": 5_800_000,
        "working_capital": 310_000,
        "interest_expenses": 95_000,
        "principal_payments": 180_000,
        "aging": [
            {"period": "2024 Q1", "overdue": 45_000,  "days_1_30": 320_000, "days_31_60": 80_000, "days_61_90": 30_000, "days_90_plus": 15_000},
            {"period": "2024 Q2", "overdue": 60_000,  "days_1_30": 290_000, "days_31_60": 95_000, "days_61_90": 40_000, "days_90_plus": 20_000},
            {"period": "2024 Q3", "overdue": 30_000,  "days_1_30": 310_000, "days_31_60": 70_000, "days_61_90": 25_000, "days_90_plus": 10_000},
            {"period": "2024 Q4", "overdue": 80_000,  "days_1_30": 350_000, "days_31_60": 110_000,"days_61_90": 55_000, "days_90_plus": 35_000},
        ],
        "requests": [
            {"amount": 200_000, "currency": "TL", "days_ago": 60},
            {"amount": 350_000, "currency": "TL", "days_ago": 15},
        ],
    },
    {
        "account_code": "SMPL-003",
        "account_name": "İstanbul İnşaat & Yapı A.Ş.",
        "tax_no": "5544332211",
        "phone": "02122334455",
        "sector": "construction",
        "equity": 8_900_000,
        "annual_net_profit": 1_450_000,
        "current_assets": 5_600_000,
        "short_term_liabilities": 2_200_000,
        "total_assets": 18_000_000,
        "total_liabilities": 9_100_000,
        "retained_earnings": 3_200_000,
        "ebit": 2_100_000,
        "sales": 22_000_000,
        "working_capital": 3_400_000,
        "interest_expenses": 480_000,
        "principal_payments": 720_000,
        "aging": [
            {"period": "2024 Q1", "overdue": 0,       "days_1_30": 850_000, "days_31_60": 120_000,"days_61_90": 0,       "days_90_plus": 0},
            {"period": "2024 Q2", "overdue": 0,       "days_1_30": 920_000, "days_31_60": 95_000, "days_61_90": 0,       "days_90_plus": 0},
            {"period": "2024 Q3", "overdue": 25_000,  "days_1_30": 780_000, "days_31_60": 150_000,"days_61_90": 30_000,  "days_90_plus": 0},
            {"period": "2024 Q4", "overdue": 0,       "days_1_30": 1_100_000,"days_31_60": 200_000,"days_61_90": 0,      "days_90_plus": 0},
        ],
        "requests": [
            {"amount": 1_500_000, "currency": "TL", "days_ago": 120},
            {"amount": 2_000_000, "currency": "TL", "days_ago": 45},
            {"amount": 2_500_000, "currency": "TL", "days_ago": 7},
        ],
    },
    {
        "account_code": "SMPL-004",
        "account_name": "Bordo Teknoloji Hizmetleri Ltd.",
        "tax_no": "1122334455",
        "phone": "02166778899",
        "sector": "service",
        "equity": 680_000,
        "annual_net_profit": 95_000,
        "current_assets": 430_000,
        "short_term_liabilities": 310_000,
        "total_assets": 1_100_000,
        "total_liabilities": 420_000,
        "retained_earnings": 180_000,
        "ebit": 130_000,
        "sales": 1_800_000,
        "working_capital": 120_000,
        "interest_expenses": 28_000,
        "principal_payments": 55_000,
        "aging": [
            {"period": "2024 Q1", "overdue": 0,      "days_1_30": 95_000, "days_31_60": 15_000, "days_61_90": 0,      "days_90_plus": 0},
            {"period": "2024 Q2", "overdue": 5_000,  "days_1_30": 110_000,"days_31_60": 20_000, "days_61_90": 5_000,  "days_90_plus": 0},
            {"period": "2024 Q3", "overdue": 0,      "days_1_30": 105_000,"days_31_60": 18_000, "days_61_90": 0,      "days_90_plus": 0},
            {"period": "2024 Q4", "overdue": 0,      "days_1_30": 120_000,"days_31_60": 22_000, "days_61_90": 0,      "days_90_plus": 0},
        ],
        "requests": [
            {"amount": 100_000, "currency": "TL", "days_ago": 45},
            {"amount": 150_000, "currency": "TL", "days_ago": 10},
        ],
    },
    {
        "account_code": "SMPL-005",
        "account_name": "Kuzey Nakliyat ve Lojistik A.Ş.",
        "tax_no": "9988776655",
        "phone": "03124445566",
        "sector": "service",
        "equity": 2_800_000,
        "annual_net_profit": 380_000,
        "current_assets": 1_600_000,
        "short_term_liabilities": 900_000,
        "total_assets": 6_200_000,
        "total_liabilities": 3_400_000,
        "retained_earnings": 850_000,
        "ebit": 610_000,
        "sales": 8_500_000,
        "working_capital": 700_000,
        "interest_expenses": 145_000,
        "principal_payments": 280_000,
        "aging": [
            {"period": "2024 Q1", "overdue": 20_000,  "days_1_30": 420_000, "days_31_60": 65_000, "days_61_90": 15_000, "days_90_plus": 5_000},
            {"period": "2024 Q2", "overdue": 35_000,  "days_1_30": 450_000, "days_31_60": 80_000, "days_61_90": 20_000, "days_90_plus": 8_000},
            {"period": "2024 Q3", "overdue": 10_000,  "days_1_30": 410_000, "days_31_60": 55_000, "days_61_90": 10_000, "days_90_plus": 0},
            {"period": "2024 Q4", "overdue": 50_000,  "days_1_30": 490_000, "days_31_60": 90_000, "days_61_90": 35_000, "days_90_plus": 18_000},
        ],
        "requests": [
            {"amount": 400_000, "currency": "TL", "days_ago": 75},
            {"amount": 600_000, "currency": "TL", "days_ago": 20},
            {"amount": 500_000, "currency": "EUR", "days_ago": 5},
        ],
    },
]


def run():
    import json
    from database import get_session, Customer, AgingRecord, CreditRequest
    from database import AgingRecord as AgingRecordDB, CreditScore
    from credit_scoring import CreditScorer, CreditRequestInput, AgingRecord as CalcRecord
    from routes.admin import get_settings

    db = get_session()
    today = datetime.date.today()
    created = 0

    for data in SAMPLE_CUSTOMERS:
        # Zaten varsa atla
        existing = db.query(Customer).filter_by(account_code=data["account_code"]).first()
        if existing:
            print(f"  SKIP (exists): {data['account_code']} - {data['account_name']}")
            continue

        c = Customer(
            account_code=data["account_code"],
            account_name=data["account_name"],
            tax_no=data.get("tax_no"),
            phone=data.get("phone"),
            sector=data.get("sector", "general"),
            equity=data.get("equity", 0),
            annual_net_profit=data.get("annual_net_profit", 0),
            current_assets=data.get("current_assets", 0),
            short_term_liabilities=data.get("short_term_liabilities", 0),
            total_assets=data.get("total_assets", 0),
            total_liabilities=data.get("total_liabilities", 0),
            retained_earnings=data.get("retained_earnings", 0),
            ebit=data.get("ebit", 0),
            sales=data.get("sales", 0),
            working_capital=data.get("working_capital", 0),
            interest_expenses=data.get("interest_expenses", 0),
            principal_payments=data.get("principal_payments", 0),
            is_sample=True,
        )
        db.add(c)
        db.flush()  # id al

        # Aging kayıtları
        for ag in data.get("aging", []):
            total = sum([ag.get("overdue",0), ag.get("days_1_30",0), ag.get("days_31_60",0), ag.get("days_61_90",0), ag.get("days_90_plus",0)])
            db.add(AgingRecord(
                customer_id=c.id,
                period=ag["period"],
                overdue=ag.get("overdue", 0),
                days_1_30=ag.get("days_1_30", 0),
                days_31_60=ag.get("days_31_60", 0),
                days_61_90=ag.get("days_61_90", 0),
                days_90_plus=ag.get("days_90_plus", 0),
                total_debt=total,
                type="past",
            ))

        # Kredi talepleri
        for req in data.get("requests", []):
            req_date = today - datetime.timedelta(days=req.get("days_ago", 0))
            cr = CreditRequest(
                customer_id=c.id,
                request_amount=req["amount"],
                currency=req.get("currency", "TL"),
                request_date=req_date,
                approval_status="Scored",
            )
            db.add(cr)

        db.commit()
        print(f"  ✓ Eklendi: {data['account_code']} - {data['account_name']}")
        created += 1

    db.close()
    print(f"\nToplam {created} müşteri eklendi.")

    print("\nKredi skorları hesaplanıyor...")
    settings = get_settings()
    rate      = settings.get('interest_rate', 45.0)
    risk      = settings.get('sector_risk', 1.0)
    inflation = settings.get('inflation_rate', 55.0)

    db2 = get_session()
    sample_customers = db2.query(Customer).filter(Customer.is_sample == True).all()
    for c in sample_customers:
        for req in c.credit_requests:
            if req.score_result is None:
                try:
                    scorer = CreditScorer(c.id, db_session=db2)
                    req_input = CreditRequestInput(request_amount=req.request_amount, currency=req.currency)
                    res = scorer.calculate(
                        settings={'interest_rate': rate, 'sector_risk': risk, 'inflation_rate': inflation},
                        request_input=req_input, lang='tr'
                    )
                    scenarios_payload = json.dumps([
                        {'name': s.name, 'description': s.description, 'impact': s.impact, 'score': s.score}
                        for s in (res.scenarios or [])
                    ])
                    score_db = CreditScore(
                        customer_id=c.id, credit_request_id=req.id,
                        historical_score=res.historical_score, future_score=res.future_score,
                        request_score=res.request_score, debt_score=res.debt_score,
                        final_score=res.final_score, credit_note=res.credit_note,
                        avg_delay_days=res.avg_delay_days, avg_debt=res.avg_debt,
                        next_6_months_total=res.future_6_months_total,
                        recommended_limit=res.recommended_limit, max_capacity=res.max_capacity,
                        instant_equity=c.equity, instant_liquidity=c.liquidity_ratio,
                        instant_net_profit=c.annual_net_profit,
                        trend_score=res.momentum_score, trend_direction=res.trend_direction,
                        assessment=res.assessment, decision_summary=res.decision_summary,
                        scenarios_json=scenarios_payload,
                        vade_days=res.vade_days, vade_message=res.vade_message,
                        z_score=res.z_score, z_score_note=res.z_score_note,
                        dscr_score=res.dscr_score, volatility=res.volatility,
                        piotroski_score=getattr(res, 'piotroski_score', None),
                        piotroski_grade=getattr(res, 'piotroski_grade', None),
                        icr_score=getattr(res, 'icr_score', None),
                        aging_concentration=getattr(res, 'aging_concentration', None),
                    )
                    db2.add(score_db)
                    db2.commit()
                    print(f"  Skorlandı: {c.account_code} talep #{req.id} → {res.credit_note} ({res.final_score:.1f})")
                except Exception as e:
                    db2.rollback()
                    print(f"  Skorlama hatası {c.account_code} #{req.id}: {e}")
    db2.close()
    print("Tamamlandı.")



if __name__ == "__main__":
    with app.app_context():
        run()
