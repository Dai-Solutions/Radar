from flask import Blueprint, request, redirect, url_for, flash, render_template, current_app, send_file, jsonify
from flask_login import login_required, current_user
import os
import json
import time

from database import get_session, Customer, AgingRecord as AgingRecordDB
from excel_import import ExcelImporter
from extensions import mail
from flask_mail import Message

admin_bp = Blueprint('admin', __name__)

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data')
SETTINGS_PATH = os.path.join(DATA_DIR, 'settings.json')
IMPORTS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'imports')

_settings_cache = {'data': None, 'time': 0}
CACHE_TTL = 300 

def get_settings():
    global _settings_cache
    now = time.time()
    if _settings_cache['data'] and (now - _settings_cache['time'] < CACHE_TTL):
        return _settings_cache['data']
        
    if not os.path.exists(SETTINGS_PATH):
        default_settings = {"interest_rate": 45.0, "inflation_rate": 55.0, "sector_risk": 1.0}
        os.makedirs(os.path.dirname(SETTINGS_PATH), exist_ok=True)
        with open(SETTINGS_PATH, 'w') as f:
            json.dump(default_settings, f)
        _settings_cache = {'data': default_settings, 'time': now}
        return default_settings
        
    with open(SETTINGS_PATH, 'r') as f:
        data = json.load(f)
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
def update_settings():
    settings = {
        'interest_rate': float(request.form.get('interest_rate', 45.0)),
        'inflation_rate': float(request.form.get('inflation_rate', 55.0)),
        'sector_risk': float(request.form.get('sector_risk', 1.0))
    }
    save_settings(settings)
    flash('Ayarlar güncellendi', 'success')
    return redirect(url_for('main.index'))

@admin_bp.route('/import_excel', methods=['GET', 'POST'])
@login_required
def import_excel():
    if request.method == 'POST':
        if 'excel_file' not in request.files:
            flash('Dosya seçilmedi', 'error')
            return redirect(url_for('admin.import_excel'))
        
        file = request.files['excel_file']
        os.makedirs(IMPORTS_DIR, exist_ok=True)
        temp_path = os.path.join(IMPORTS_DIR, f"tmp_{file.filename}")
        file.save(temp_path)
        
        importer = ExcelImporter()
        aging_recs, cust_map = importer.excel_to_aging_records(temp_path)
        balance_list = importer.excel_to_balance_sheet(temp_path)
        
        session = get_session()
        for b in balance_list:
            c = session.query(Customer).filter(Customer.account_code == b['account_code']).first()
            if not c:
                c = Customer(account_code=b['account_code'], account_name=b['account_name'])
                session.add(c)
                session.flush()
            
            c.account_name = b['account_name']
            c.equity = b['equity']
            c.net_profit = b.get('net_profit', 0)
            c.current_assets = b['current_assets']
            c.short_term_liabilities = b['short_term_liabilities']
            c.liquidity_ratio = b['liquidity_ratio']
            
        session.commit()
        session.close()
        flash('İçe aktarma tamamlandı', 'success')
        return redirect(url_for('main.index'))
    return render_template('import_excel.html')

@admin_bp.route('/download_sample')
@login_required
def download_sample():
    sample_path = os.path.join(current_app.root_path, 'static', 'radar_1_0_sample.xlsx')
    importer = ExcelImporter()
    importer.create_template(sample_path)
    return send_file(sample_path, as_attachment=True, download_name='radar_1_0_sample.xlsx')

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
