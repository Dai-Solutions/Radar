"""
Celery görevleri — Radar toplu portföy analizi.

Görev: portfolio_scan
  - Bir tenanta ait tüm müşterileri tarar
  - Her müşteri için CreditScorer ile hızlı skor hesaplar
  - Özet istatistikleri (dağılım, ECL, RWA...) BatchJob.summary_json'a yazar
"""
import json
import logging
from datetime import datetime

from celery_app import celery

logger = logging.getLogger(__name__)

# Portföy taramasında kullanılan varsayılan kredi talebi tutarı (TL)
_DEFAULT_SCAN_AMOUNT = 100_000.0
_DEFAULT_SCAN_CURRENCY = 'TL'


@celery.task(bind=True, max_retries=3, default_retry_delay=10)
def portfolio_scan(self, job_id: int, tenant_id: int = 1):
    """
    Tüm müşterileri tara, BatchJob.summary_json'a özet yaz.

    summary_json şeması:
    {
      "total": int,
      "scored": int,
      "failed": int,
      "note_dist": {"AA": n, "AB": n, ...},
      "stage_dist": {"1": n, "2": n, "3": n},
      "total_ecl": float,
      "total_rwa": float,
      "avg_score": float,
      "high_risk_count": int,
      "customers": [
        {"id": int, "name": str, "code": str, "score": float,
         "note": str, "stage": int, "ecl": float, "rwa": float,
         "veto": str|null}
      ]
    }
    """
    from database import get_session, BatchJob, Customer, AgingRecord as AgingRecordDB
    from credit_scoring import CreditScorer, CreditRequestInput
    from routes.admin import get_settings

    db = get_session()
    try:
        job = db.query(BatchJob).filter(BatchJob.id == job_id).first()
        if not job:
            logger.error('BatchJob %s bulunamadı', job_id)
            return

        job.status = 'running'
        job.celery_task_id = self.request.id
        db.commit()

        customers = db.query(Customer).filter(
            Customer.tenant_id == tenant_id
        ).order_by(Customer.account_name).all()

        job.total = len(customers)
        db.commit()

        settings = get_settings()
        req_input = CreditRequestInput(
            request_amount=_DEFAULT_SCAN_AMOUNT,
            currency=_DEFAULT_SCAN_CURRENCY,
            period=datetime.utcnow().strftime('%Y-%m'),
        )

        note_dist: dict[str, int] = {}
        stage_dist: dict[str, int] = {'1': 0, '2': 0, '3': 0}
        total_ecl = 0.0
        total_rwa = 0.0
        score_sum = 0.0
        high_risk = 0
        customer_rows = []
        failed = 0

        for cust in customers:
            try:
                aging_records = db.query(AgingRecordDB).filter(
                    AgingRecordDB.customer_id == cust.id
                ).order_by(AgingRecordDB.period.desc()).limit(12).all()

                scorer = CreditScorer(
                    customer_data=cust,
                    aging_records=aging_records,
                )
                result = scorer.calculate(
                    settings=settings,
                    request_input=req_input,
                    skip_scenarios=True,
                    lang='tr',
                )

                note = result.credit_note or 'N/A'
                note_dist[note] = note_dist.get(note, 0) + 1

                stage_key = str(result.ifrs9_stage) if result.ifrs9_stage in (1, 2, 3) else '1'
                stage_dist[stage_key] = stage_dist.get(stage_key, 0) + 1

                total_ecl += result.ifrs9_ecl or 0.0
                total_rwa += result.ifrs9_rwa or 0.0
                score_sum += result.final_score or 0.0

                if (result.ifrs9_stage or 1) >= 2 or (result.final_score or 100) < 40:
                    high_risk += 1

                customer_rows.append({
                    'id': cust.id,
                    'name': cust.account_name,
                    'code': cust.account_code,
                    'score': round(result.final_score or 0, 1),
                    'note': note,
                    'stage': result.ifrs9_stage or 1,
                    'ecl': round(result.ifrs9_ecl or 0, 2),
                    'rwa': round(result.ifrs9_rwa or 0, 2),
                    'veto': result.kkb_veto,
                })
            except Exception as e:
                logger.warning('Müşteri %s tarama hatası: %s', cust.id, e)
                failed += 1
                customer_rows.append({
                    'id': cust.id,
                    'name': cust.account_name,
                    'code': cust.account_code,
                    'score': None,
                    'note': 'ERR',
                    'stage': None,
                    'ecl': 0.0,
                    'rwa': 0.0,
                    'veto': None,
                    'error': str(e),
                })

            job.processed = len(customer_rows)
            db.commit()

        scored = len(customers) - failed
        avg_score = round(score_sum / scored, 1) if scored > 0 else 0.0

        # Skora göre sırala (düşük önce)
        customer_rows.sort(key=lambda r: (r['score'] is None, r['score'] or 999))

        summary = {
            'total': len(customers),
            'scored': scored,
            'failed': failed,
            'note_dist': note_dist,
            'stage_dist': stage_dist,
            'total_ecl': round(total_ecl, 2),
            'total_rwa': round(total_rwa, 2),
            'avg_score': avg_score,
            'high_risk_count': high_risk,
            'customers': customer_rows,
            'scanned_at': datetime.utcnow().isoformat(),
        }

        job.status = 'done'
        job.summary_json = json.dumps(summary, ensure_ascii=False)
        job.finished_at = datetime.utcnow()
        db.commit()
        logger.info('portfolio_scan job_id=%s tamamlandı (%s müşteri)', job_id, scored)

    except Exception as exc:
        logger.error('portfolio_scan job_id=%s kritik hata: %s', job_id, exc)
        if db:
            try:
                job = db.query(BatchJob).filter(BatchJob.id == job_id).first()
                if job:
                    job.status = 'error'
                    job.error_message = str(exc)
                    job.finished_at = datetime.utcnow()
                    db.commit()
            except Exception:
                pass
        raise self.retry(exc=exc)
    finally:
        db.close()
