from flask import Blueprint, request, redirect, url_for, flash, render_template, current_app, send_file, jsonify, Response
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
import csv
import io
import os
import json
import time
import uuid
from datetime import datetime, timedelta

from database import get_session, Customer, AgingRecord as AgingRecordDB, AuditLog, User, SSOConfig
from excel_import import ExcelImporter
from extensions import mail
from flask_mail import Message
from routes.auth import admin_required

admin_bp = Blueprint('admin', __name__)

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data')
SETTINGS_PATH = os.path.join(DATA_DIR, 'settings.json')
IMPORTS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'imports')

_settings_cache = {'data': None, 'time': 0}
CACHE_TTL = 300

ALLOWED_EXCEL_EXT = {'.xlsx', '.xls', '.csv'}
MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB

def get_settings():
    global _settings_cache
    now = time.time()
    if _settings_cache['data'] and (now - _settings_cache['time'] < CACHE_TTL):
        return _settings_cache['data']
        
    DEFAULTS = {"interest_rate": 45.0, "inflation_rate": 55.0, "sector_risk": 1.0,
                "monte_carlo_iterations": 500}

    if not os.path.exists(SETTINGS_PATH):
        os.makedirs(os.path.dirname(SETTINGS_PATH), exist_ok=True)
        with open(SETTINGS_PATH, 'w') as f:
            json.dump(DEFAULTS, f)
        _settings_cache = {'data': DEFAULTS, 'time': now}
        return DEFAULTS

    with open(SETTINGS_PATH, 'r') as f:
        data = json.load(f)
    # eksik anahtarları varsayılanlarla doldur (geriye dönük uyumlu)
    for k, v in DEFAULTS.items():
        data.setdefault(k, v)
    _settings_cache = {'data': data, 'time': now}
    return data

def save_settings(settings):
    global _settings_cache
    os.makedirs(os.path.dirname(SETTINGS_PATH), exist_ok=True)
    with open(SETTINGS_PATH, 'w') as f:
        json.dump(settings, f)
    _settings_cache = {'data': settings, 'time': time.time()}

@admin_bp.route('/update_settings', methods=['POST'])
@login_required
@admin_required
def update_settings():
    settings = {
        'interest_rate': float(request.form.get('interest_rate', 45.0)),
        'inflation_rate': float(request.form.get('inflation_rate', 55.0)),
        'sector_risk': float(request.form.get('sector_risk', 1.0)),
        'monte_carlo_iterations': int(request.form.get('monte_carlo_iterations', 500))
    }
    save_settings(settings)
    flash('Ayarlar güncellendi', 'success')
    return redirect(url_for('main.index'))

@admin_bp.route('/import_excel', methods=['GET', 'POST'])
@login_required
@admin_required
def import_excel():
    if request.method == 'POST':
        if 'excel_file' not in request.files:
            flash('Dosya seçilmedi', 'error')
            return redirect(url_for('admin.import_excel'))

        file = request.files['excel_file']
        if not file or not file.filename:
            flash('Dosya seçilmedi', 'error')
            return redirect(url_for('admin.import_excel'))

        original = secure_filename(file.filename)
        ext = os.path.splitext(original)[1].lower()
        if ext not in ALLOWED_EXCEL_EXT:
            flash('Sadece .xlsx, .xls veya .csv dosyaları kabul edilir.', 'error')
            return redirect(url_for('admin.import_excel'))

        # Boyut kontrolü (stream cursor üzerinden)
        file.stream.seek(0, os.SEEK_END)
        size = file.stream.tell()
        file.stream.seek(0)
        if size > MAX_UPLOAD_BYTES:
            flash('Dosya 10 MB sınırını aşıyor.', 'error')
            return redirect(url_for('admin.import_excel'))
        if size == 0:
            flash('Dosya boş.', 'error')
            return redirect(url_for('admin.import_excel'))

        os.makedirs(IMPORTS_DIR, exist_ok=True)
        # Path traversal'ı engellemek için isimde sadece secure_filename + uuid kullan
        safe_name = f"upload_{uuid.uuid4().hex}{ext}"
        temp_path = os.path.join(IMPORTS_DIR, safe_name)
        file.save(temp_path)

        try:
            importer = ExcelImporter()
            aging_recs, cust_map = importer.excel_to_aging_records(temp_path)
            balance_list = importer.excel_to_balance_sheet(temp_path)
        finally:
            try:
                os.remove(temp_path)
            except OSError:
                pass
        
        session = get_session()
        for b in balance_list:
            c = session.query(Customer).filter(Customer.account_code == b['account_code']).first()
            if not c:
                c = Customer(account_code=b['account_code'], account_name=b['account_name'],
                             user_id=current_user.id)
                session.add(c)
                session.flush()
            
            c.account_name = b['account_name']
            c.equity = b['equity']
            c.annual_net_profit = b.get('net_profit', 0)
            c.current_assets = b['current_assets']
            c.short_term_liabilities = b['short_term_liabilities']
            c.liquidity_ratio = b['liquidity_ratio']
            c.sector_risk_factor = b.get('sector_risk_factor', 1.0)
            if b.get('tax_no'):
                c.tax_no = b['tax_no']
            
        session.commit()
        session.close()
        flash('İçe aktarma tamamlandı', 'success')
        return redirect(url_for('main.index'))
    return render_template('import_excel.html')

@admin_bp.route('/download_sample')
@login_required
@admin_required
def download_sample():
    sample_path = os.path.join(current_app.root_path, 'static', 'radar_1_0_sample.xlsx')
    importer = ExcelImporter()
    importer.create_template(sample_path)
    return send_file(sample_path, as_attachment=True, download_name='radar_1_0_sample.xlsx')

@admin_bp.route('/audit-log')
@login_required
@admin_required
def audit_log():
    session = get_session()
    try:
        PAGE_SIZE = 50
        page = max(1, int(request.args.get('page', 1)))

        action_filter      = request.args.get('action', '').strip()
        entity_filter      = request.args.get('entity_type', '').strip()
        status_filter      = request.args.get('status', '').strip()
        from_date_str      = request.args.get('from_date', '').strip()
        to_date_str        = request.args.get('to_date', '').strip()

        tenant_id = getattr(current_user, 'tenant_id', 1) or 1
        q = session.query(AuditLog).filter(AuditLog.tenant_id == tenant_id)

        if action_filter:
            q = q.filter(AuditLog.action == action_filter)
        if entity_filter:
            q = q.filter(AuditLog.entity_type == entity_filter)
        if status_filter:
            q = q.filter(AuditLog.status == status_filter)
        if from_date_str:
            try:
                q = q.filter(AuditLog.timestamp >= datetime.strptime(from_date_str, '%Y-%m-%d'))
            except ValueError:
                pass
        if to_date_str:
            try:
                end = datetime.strptime(to_date_str, '%Y-%m-%d') + timedelta(days=1)
                q = q.filter(AuditLog.timestamp < end)
            except ValueError:
                pass

        # soft-deleted kayıtları gizle
        q = q.filter(AuditLog.deleted_at.is_(None))

        total = q.count()
        logs  = (q.order_by(AuditLog.timestamp.desc())
                  .offset((page - 1) * PAGE_SIZE)
                  .limit(PAGE_SIZE)
                  .all())

        # kullanıcı e-posta eşleme
        user_ids = {l.user_id for l in logs if l.user_id}
        users = {u.id: u.email for u in session.query(User).filter(User.id.in_(user_ids)).all()}

        # filtre seçenekleri — dropdown'lar için mevcut değerler
        distinct_actions = [r[0] for r in
            session.query(AuditLog.action).filter(AuditLog.tenant_id == tenant_id)
                   .filter(AuditLog.deleted_at.is_(None)).distinct().all() if r[0]]
        distinct_entities = [r[0] for r in
            session.query(AuditLog.entity_type).filter(AuditLog.tenant_id == tenant_id)
                   .filter(AuditLog.deleted_at.is_(None)).distinct().all() if r[0]]

        total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)

        return render_template(
            'audit_log.html',
            logs=logs,
            users=users,
            page=page,
            total=total,
            total_pages=total_pages,
            page_size=PAGE_SIZE,
            distinct_actions=sorted(distinct_actions),
            distinct_entities=sorted(distinct_entities),
            # aktif filtreler template'e geri
            f_action=action_filter,
            f_entity=entity_filter,
            f_status=status_filter,
            f_from=from_date_str,
            f_to=to_date_str,
        )
    finally:
        session.close()


@admin_bp.route('/audit-log/export')
@login_required
@admin_required
def audit_log_export():
    """Mevcut filtreyi CSV olarak indir."""
    session = get_session()
    try:
        action_filter  = request.args.get('action', '').strip()
        entity_filter  = request.args.get('entity_type', '').strip()
        status_filter  = request.args.get('status', '').strip()
        from_date_str  = request.args.get('from_date', '').strip()
        to_date_str    = request.args.get('to_date', '').strip()

        tenant_id = getattr(current_user, 'tenant_id', 1) or 1
        q = session.query(AuditLog).filter(
            AuditLog.tenant_id == tenant_id,
            AuditLog.deleted_at.is_(None),
        )
        if action_filter:
            q = q.filter(AuditLog.action == action_filter)
        if entity_filter:
            q = q.filter(AuditLog.entity_type == entity_filter)
        if status_filter:
            q = q.filter(AuditLog.status == status_filter)
        if from_date_str:
            try:
                q = q.filter(AuditLog.timestamp >= datetime.strptime(from_date_str, '%Y-%m-%d'))
            except ValueError:
                pass
        if to_date_str:
            try:
                q = q.filter(AuditLog.timestamp < datetime.strptime(to_date_str, '%Y-%m-%d') + timedelta(days=1))
            except ValueError:
                pass

        logs = q.order_by(AuditLog.timestamp.desc()).limit(5000).all()

        user_ids = {l.user_id for l in logs if l.user_id}
        users = {u.id: u.email for u in session.query(User).filter(User.id.in_(user_ids)).all()}

        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(['timestamp', 'user', 'action', 'entity_type', 'entity_id',
                         'status', 'ip_address', 'error_message'])
        for log in logs:
            writer.writerow([
                log.timestamp.strftime('%Y-%m-%d %H:%M:%S') if log.timestamp else '',
                users.get(log.user_id, str(log.user_id or '')),
                log.action or '',
                log.entity_type or '',
                log.entity_id or '',
                log.status or '',
                log.ip_address or '',
                log.error_message or '',
            ])

        filename = f"audit_log_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv"
        return Response(
            buf.getvalue(),
            mimetype='text/csv',
            headers={'Content-Disposition': f'attachment; filename={filename}'},
        )
    finally:
        session.close()


@admin_bp.route('/sso-config', methods=['GET', 'POST'])
@login_required
@admin_required
def sso_config():
    """Kurumsal SSO yapılandırması — SAML 2.0 veya LDAP/AD."""
    db_session = get_session()
    try:
        config = db_session.query(SSOConfig).filter(SSOConfig.tenant_id == 1).first()

        if request.method == 'POST':
            provider_type = request.form.get('provider_type', 'saml')

            if not config:
                config = SSOConfig(tenant_id=1)
                db_session.add(config)

            config.provider_type = provider_type
            config.is_active = bool(request.form.get('is_active'))

            if provider_type == 'saml':
                config.idp_entity_id = request.form.get('idp_entity_id', '').strip()
                config.idp_sso_url = request.form.get('idp_sso_url', '').strip()
                config.idp_slo_url = request.form.get('idp_slo_url', '').strip()
                config.idp_x509_cert = request.form.get('idp_x509_cert', '').strip()
                config.sp_entity_id = request.form.get('sp_entity_id', '').strip()
            else:
                config.ldap_host = request.form.get('ldap_host', '').strip()
                config.ldap_port = int(request.form.get('ldap_port') or 389)
                config.ldap_use_ssl = bool(request.form.get('ldap_use_ssl'))
                config.ldap_base_dn = request.form.get('ldap_base_dn', '').strip()
                config.ldap_bind_dn = request.form.get('ldap_bind_dn', '').strip()
                pw = request.form.get('ldap_bind_password', '')
                if pw:
                    config.ldap_bind_password = pw
                config.ldap_user_search_filter = (
                    request.form.get('ldap_user_search_filter', '').strip()
                    or '(sAMAccountName={username})'
                )
                config.ldap_email_attr = request.form.get('ldap_email_attr', '').strip() or 'mail'
                config.ldap_name_attr = request.form.get('ldap_name_attr', '').strip() or 'displayName'

            db_session.commit()
            flash('SSO yapılandırması kaydedildi.', 'success')
            return redirect(url_for('admin.sso_config'))

        return render_template('sso_config.html', config=config)
    finally:
        db_session.close()


@admin_bp.route('/submit_feedback', methods=['POST'])
@login_required
def submit_feedback():
    message = request.json.get('message')
    if not message:
        return jsonify({'status': 'error', 'message': 'Mesaj boş olamaz.'}), 400
    
    from database import Feedback
    session = get_session()
    try:
        new_feedback = Feedback(user_id=current_user.id, message=message)
        session.add(new_feedback)
        session.commit()
        
        try:
            admin_msg = Message(f"{current_app.config['APP_VERSION']} - Yeni Geri Bildirim Geldi!",
                                recipients=[current_app.config['ADMIN_EMAIL']])
            admin_msg.body = f"Kullanıcı: {current_user.full_name} ({current_user.email})\nMesaj: {message}"
            mail.send(admin_msg)
        except Exception as mail_err:
            current_app.logger.error(f"Feedback alert email failed: {mail_err}")

        return jsonify({'status': 'success', 'message': 'Geri bildiriminiz iletildi.'})
    except Exception as e:
        session.rollback()
        return jsonify({'status': 'error', 'message': str(e)}), 500
    finally:
        session.close()
