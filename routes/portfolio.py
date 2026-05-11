"""
Toplu portföy analizi rotaları.

GET  /portfoy          → portföy dashboard (geçmiş işler listesi)
POST /portfoy/tara     → yeni batch job başlat
GET  /portfoy/durum/<id> → job durum JSON (polling)
GET  /portfoy/sonuc/<id> → job sonuç sayfası
"""
import json
from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify
from flask_login import login_required, current_user

from database import get_session, BatchJob

portfolio_bp = Blueprint('portfolio', __name__, url_prefix='/portfoy')


def _tenant_id():
    return getattr(current_user, 'tenant_id', 1) or 1


@portfolio_bp.route('/', methods=['GET'])
@login_required
def index():
    db = get_session()
    try:
        jobs = (
            db.query(BatchJob)
            .filter(BatchJob.tenant_id == _tenant_id())
            .order_by(BatchJob.created_at.desc())
            .limit(20)
            .all()
        )
        return render_template('portfolio.html', jobs=jobs)
    finally:
        db.close()


@portfolio_bp.route('/tara', methods=['POST'])
@login_required
def tara():
    """Yeni portföy tarama işi başlat."""
    db = get_session()
    try:
        job = BatchJob(
            tenant_id=_tenant_id(),
            status='pending',
            job_type='portfolio_scan',
            created_by=current_user.id,
        )
        db.add(job)
        db.commit()
        db.refresh(job)
        job_id = job.id
    finally:
        db.close()

    # Celery görevi başlat (Redis yoksa CELERY_ALWAYS_EAGER ile senkron çalışır)
    try:
        from tasks import portfolio_scan
        portfolio_scan.delay(job_id=job_id, tenant_id=_tenant_id())
    except Exception as e:
        # Redis bağlantısı yoksa senkron fallback
        _run_sync(job_id, _tenant_id())

    flash('Portföy taraması başlatıldı.', 'success')
    return redirect(url_for('portfolio.sonuc', job_id=job_id))


def _run_sync(job_id, tenant_id):
    """Celery worker yoksa görevi doğrudan çalıştırır."""
    try:
        from tasks import portfolio_scan
        portfolio_scan(job_id=job_id, tenant_id=tenant_id)
    except Exception as e:
        db = get_session()
        try:
            job = db.query(BatchJob).filter(BatchJob.id == job_id).first()
            if job:
                job.status = 'error'
                job.error_message = str(e)
                db.commit()
        finally:
            db.close()


@portfolio_bp.route('/durum/<int:job_id>')
@login_required
def durum(job_id):
    """Job durumu JSON — frontend polling için."""
    db = get_session()
    try:
        job = db.query(BatchJob).filter(
            BatchJob.id == job_id,
            BatchJob.tenant_id == _tenant_id(),
        ).first()
        if not job:
            return jsonify({'error': 'bulunamadı'}), 404
        return jsonify({
            'status': job.status,
            'total': job.total,
            'processed': job.processed,
            'pct': round(job.processed / job.total * 100) if job.total else 0,
        })
    finally:
        db.close()


@portfolio_bp.route('/sonuc/<int:job_id>')
@login_required
def sonuc(job_id):
    """İş sonuç sayfası."""
    db = get_session()
    try:
        job = db.query(BatchJob).filter(
            BatchJob.id == job_id,
            BatchJob.tenant_id == _tenant_id(),
        ).first()
        if not job:
            flash('İş bulunamadı.', 'error')
            return redirect(url_for('portfolio.index'))

        summary = json.loads(job.summary_json) if job.summary_json else None
        return render_template('portfolio_result.html', job=job, summary=summary)
    finally:
        db.close()
