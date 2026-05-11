"""
Open Banking yönetim rotaları.

GET  /openbanking/          → konfigürasyon + test paneli
POST /openbanking/test      → IBAN ile test sorgusu çalıştır
POST /openbanking/sorgula   → müşteri IBAN'ı ile gerçek/mock sorgu → DB kaydet
GET  /openbanking/kayitlar  → tüm OpenBankingRecord listesi
"""
from flask import Blueprint, render_template, request, flash, redirect, url_for, jsonify
from flask_login import login_required

from routes.auth import admin_required
from database import get_session, OpenBankingRecord, Customer

ob_bp = Blueprint('openbanking', __name__, url_prefix='/openbanking')


@ob_bp.route('/')
@login_required
@admin_required
def panel():
    import os
    config = {
        'mode': os.getenv('OB_MODE', 'mock'),
        'base_url': os.getenv('OB_BASE_URL', ''),
        'client_id': os.getenv('OB_CLIENT_ID', ''),
        'cache_days': os.getenv('OB_CACHE_DAYS', '7'),
    }
    db = get_session()
    try:
        total = db.query(OpenBankingRecord).count()
        recent = (
            db.query(OpenBankingRecord)
            .order_by(OpenBankingRecord.fetched_at.desc())
            .limit(10)
            .all()
        )
        return render_template('openbanking.html', config=config,
                               total=total, recent=recent)
    finally:
        db.close()


@ob_bp.route('/test', methods=['POST'])
@login_required
@admin_required
def test_sorgu():
    """Verilen IBAN için mock/sandbox sorgusunu çalıştır, JSON döner."""
    iban = request.form.get('iban', '').strip().replace(' ', '')
    if not iban:
        return jsonify({'error': 'IBAN boş olamaz'}), 400

    from openbanking_adapter import OpenBankingAdapter
    adapter = OpenBankingAdapter()
    data = adapter._fetch(iban)
    return jsonify({'iban': iban, 'mode': adapter.mode, 'data': data})


@ob_bp.route('/sorgula', methods=['POST'])
@login_required
@admin_required
def sorgula():
    """Müşteriye ait IBAN için Open Banking verisi çek ve DB'ye kaydet."""
    customer_id = request.form.get('customer_id')
    iban = request.form.get('iban', '').strip().replace(' ', '')
    consent = request.form.get('consent') == '1'

    if not iban or not customer_id:
        flash('Müşteri ve IBAN gereklidir.', 'error')
        return redirect(url_for('openbanking.panel'))

    db = get_session()
    try:
        customer = db.query(Customer).filter(Customer.id == int(customer_id)).first()
        if not customer:
            flash('Müşteri bulunamadı.', 'error')
            return redirect(url_for('openbanking.panel'))

        from openbanking_adapter import OpenBankingAdapter
        adapter = OpenBankingAdapter()
        record = adapter.get_account_summary(
            iban=iban,
            customer_id=customer.id,
            tenant_id=customer.tenant_id or 1,
            session=db,
            consent_given=consent,
        )
        flash(
            f'{customer.account_name} için Open Banking verisi alındı. '
            f'Ort. bakiye: {record.avg_monthly_balance:,.0f} ₺ | '
            f'Cashflow düzenliliği: {record.cashflow_regularity:.0%}',
            'success',
        )
    except Exception as e:
        flash(f'Sorgu hatası: {e}', 'error')
    finally:
        db.close()

    return redirect(url_for('openbanking.panel'))


@ob_bp.route('/kayitlar')
@login_required
@admin_required
def kayitlar():
    db = get_session()
    try:
        records = (
            db.query(OpenBankingRecord)
            .order_by(OpenBankingRecord.fetched_at.desc())
            .limit(100)
            .all()
        )
        return render_template('openbanking_kayitlar.html', records=records)
    finally:
        db.close()
