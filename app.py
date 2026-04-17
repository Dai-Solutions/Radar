from flask import Flask, render_template, request, redirect, url_for, flash, session, send_file, jsonify
from flask_mail import Mail, Message
from itsdangerous import URLSafeTimedSerializer, SignatureExpired
from werkzeug.middleware.proxy_fix import ProxyFix
import os
import json
from datetime import datetime
import pandas as pd
from dotenv import load_dotenv
from werkzeug.middleware.dispatcher import DispatcherMiddleware
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from authlib.integrations.flask_client import OAuth
from werkzeug.security import generate_password_hash, check_password_hash
import time
from functools import wraps
import logging
from logging.handlers import RotatingFileHandler

# Local modules (Englishified)
from database import init_db, Customer, AgingRecord as AgingRecordDB, CreditRequest, CreditScore, get_session, User, Feedback
from aging_analyzer import AgingAnalyzer, AgingRecord
from credit_scoring import CreditScorer, CreditRequestInput
from excel_import import ExcelImporter
from translations import translations

# Load environment variables
dotenv_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '.env'))
load_dotenv(dotenv_path, override=True)

app = Flask(__name__)
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'radar_1_0_secret_key')

# Prefix configuration for server deployment
APP_PREFIX = os.getenv('APP_PREFIX', '/radar')

# Wrap the application with DispatcherMiddleware for sub-path support
app.wsgi_app = DispatcherMiddleware(Flask('dummy'), {
    APP_PREFIX: app.wsgi_app
})

# Apply ProxyFix to handle X-Forwarded-Proto from Nginx
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

# Mail Configuration
app.config['MAIL_SERVER'] = os.getenv('MAIL_SERVER', 'smtp.gmail.com')
app.config['MAIL_PORT'] = int(os.getenv('MAIL_PORT', 587))
app.config['MAIL_USE_TLS'] = os.getenv('MAIL_USE_TLS', 'True') == 'True'
app.config['MAIL_USERNAME'] = os.getenv('MAIL_USERNAME', 'info@daisoftwares.com')
app.config['MAIL_PASSWORD'] = os.getenv('MAIL_PASSWORD')
app.config['MAIL_DEFAULT_SENDER'] = os.getenv('MAIL_USERNAME', 'info@daisoftwares.com')

# Session Cookie & Security Configuration (To avoid collision with other apps on the same domain)
app.config['SESSION_COOKIE_NAME'] = 'radar_session_id'
app.config['SESSION_COOKIE_PATH'] = APP_PREFIX
app.config['SESSION_COOKIE_SECURE'] = True
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

mail = Mail(app)
ts = URLSafeTimedSerializer(app.secret_key)

# Logging Configuration
if not os.path.exists('data'):
    os.makedirs('data')

log_formatter = logging.Formatter('%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]')
log_file = 'data/radar.log'
file_handler = RotatingFileHandler(log_file, maxBytes=10485760, backupCount=10)
file_handler.setFormatter(log_formatter)
file_handler.setLevel(logging.INFO)

app.logger.addHandler(file_handler)
app.logger.setLevel(logging.INFO)
app.logger.info('Radar 1.0 Startup - Production Hardening Mode Active')

# OAuth Configuration
oauth = OAuth(app)
oauth.register(
    name='google',
    client_id=os.getenv('GOOGLE_CLIENT_ID'),
    client_secret=os.getenv('GOOGLE_CLIENT_SECRET'),
    server_metadata_url=os.getenv('CONF_URL'),
    client_kwargs={
        'scope': 'openid email profile'
    }
)

# Force HTTPS for OAuth behind reverse proxy
os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '0'

# Login Configuration
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message = "Lütfen devam etmek için giriş yapın."
login_manager.login_message_category = "info"

class UserWrapper(UserMixin):
    def __init__(self, user_obj):
        self.id = user_obj.id
        self.email = user_obj.email
        self.full_name = user_obj.full_name
        self.email_verified = getattr(user_obj, 'email_verified', False)

@login_manager.user_loader
def load_user(user_id):
    db_session = get_session()
    user = db_session.query(User).filter(User.id == int(user_id)).first()
    db_session.close()
    if user:
        return UserWrapper(user)
    return None

@app.context_processor
def inject_global_vars():
    from flask import session
    lang = session.get('lang', 'tr')
    
    # Total Users Counter (7 + Actual Users)
    db_session = get_session()
    user_count = db_session.query(User).count()
    db_session.close()
    
    return dict(
        lang=lang, 
        t=translations[lang], 
        all_langs=['tr', 'en'],
        total_users=user_count,
        app_version="Radar 1.0"
    )

@app.route('/set_language/<lang>')
def set_language(lang):
    from flask import session, request
    if lang in ['tr', 'en']:
        session['lang'] = lang
    return redirect(request.referrer or url_for('index'))

# Data storage
DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')
os.makedirs(DATA_DIR, exist_ok=True)
DATABASE_PATH = os.path.join(DATA_DIR, 'kredi.db')

IMPORTS_DIR = os.path.join(os.path.dirname(__file__), 'imports')
os.makedirs(IMPORTS_DIR, exist_ok=True)

# Settings persistence with simple cache
SETTINGS_PATH = os.path.join(DATA_DIR, 'settings.json')
_settings_cache = {'data': None, 'time': 0}
CACHE_TTL = 300 # 5 minutes

def get_settings():
    global _settings_cache
    now = time.time()
    if _settings_cache['data'] and (now - _settings_cache['time'] < CACHE_TTL):
        return _settings_cache['data']
        
    if not os.path.exists(SETTINGS_PATH):
        default_settings = {"interest_rate": 45.0, "inflation_rate": 55.0, "sector_risk": 1.0}
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
    with open(SETTINGS_PATH, 'w') as f:
        json.dump(settings, f)
    _settings_cache = {'data': settings, 'time': time.time()}

# Simple custom rate limiter
def request_limit(seconds=5):
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            if not current_user.is_authenticated:
                return f(*args, **kwargs)
            
            last_request_time = session.get(f'last_req_{f.__name__}')
            now = time.time()
            if last_request_time and (now - last_request_time < seconds):
                flash(f"Lütfen çok hızlı talep göndermeyin. {int(seconds - (now - last_request_time))} saniye bekleyin.", 'error')
                return redirect(request.referrer or url_for('index'))
            
            session[f'last_req_{f.__name__}'] = now
            return f(*args, **kwargs)
        return wrapper
    return decorator


@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        
        db_session = get_session()
        user = db_session.query(User).filter(User.email == email).first()
        
        if user and user.password_hash and check_password_hash(user.password_hash, password):
            if not getattr(user, 'email_verified', False):
                flash('Lütfen hesabınızı e-postanıza gönderdiğimiz onay maili ile doğrulayın.', 'error')
                db_session.close()
                return redirect(url_for('login'))
                
            login_user(UserWrapper(user))
            db_session.close()
            flash(f'Hoş geldiniz, {user.full_name or email}', 'success')
            return redirect(url_for('index'))
        
        db_session.close()
        flash('Geçersiz e-posta veya şifre.', 'error')
    
    return render_template('login.html')

def send_welcome_email(email, full_name, verify_url):
    html_content = f"""
    <div style="font-family: 'Outfit', sans-serif; max-width: 600px; margin: auto; padding: 20px; border: 1px solid #333; border-radius: 12px; background-color: #111; color: #fff;">
        <div style="text-align: center; margin-bottom: 30px;">
            <h1 style="color: #3b82f6; margin: 0;">Radar 1.0</h1>
            <p style="color: #999; font-size: 14px; margin: 5px 0;">Let dai do it for you</p>
        </div>
        
        <p>Merhaba <strong>{full_name}</strong>,</p>
        
        <p>DAI Technology'nin geliştirdiği bu test uygulamasına giriş yaptığın için çok teşekkürler!</p>

        <p>Bizim çok inandığımız temel bir mottomuz var:<br>
        <strong>Pazara değil, insanlara hizmet ederiz.</strong></p>
        
        <p>Bu felsefeyle kurduğumuz VOID topluluğu altında, her zaman şeffaf ve açık kaynaklı çözümler üretmeye odaklanıyoruz. Şu an deneyimlediğin bu uygulama da tam olarak bu vizyonun bir parçası.</p>

        <p>Sistem henüz test aşamasında olduğu için, senin gibi değerli kullanıcıların geri bildirimleri bizim için altın değerinde. Gördüğün hataları, geliştirilebilecek yerleri veya aklına gelen fikirleri bizimle paylaşırsan harika olur.</p>

        <p>Ayrıca, bağımsız ve açık kaynaklı projeler üretmeye devam edebilmemiz için topluluk desteği çok önemli. Eğer vizyonumuzu ve uygulamalarımızı beğeniyorsan, bize yapacağın küçük bir bağış/destek, bu projeleri hayatta tutmamız ve "pazar" yerine "insanlara" hizmet etmeye devam etmemiz için en büyük gücümüz olacak.</p>

        <div style="text-align: center; margin: 40px 0;">
            <a href="{verify_url}" style="background-color: #3b82f6; color: white; padding: 15px 25px; text-decoration: none; border-radius: 8px; font-weight: bold; font-size: 16px;">HESABIMI DOĞRULA VE RADAR'A GİR</a>
        </div>

        <p style="color: #999; font-size: 14px;">Desteğin ve geri bildirimlerin için şimdiden teşekkürler!<br>Görüşmek üzere,</p>
        
        <p><strong>Ali</strong><br>
        Kothar Khasis<br>
        DynamicAI & VOID Topluluğu Kurucusu</p>
    </div>
    """
    msg = Message('Radar 1.0 - DAI Dünyasına Hoş Geldiniz!',
                  recipients=[email])
    msg.html = html_content
    mail.send(msg)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        full_name = request.form.get('full_name')
        email = request.form.get('email')
        password = request.form.get('password')
        
        session_db = get_session()
        existing_user = session_db.query(User).filter(User.email == email).first()
        
        if existing_user:
            session_db.close()
            flash('Bu e-posta adresi zaten kayıtlı.', 'error')
            return redirect(url_for('register'))
            
        new_user = User(
            full_name=full_name,
            email=email,
            password_hash=generate_password_hash(password),
            is_active=True,
            email_verified=False
        )
        session_db.add(new_user)
        session_db.commit()
        
        # Send Branded Verification Email
        try:
            token = ts.dumps(email, salt='email-confirm-key')
            verify_url = url_for('verify_email', token=token, _external=True, _scheme='https')
            send_welcome_email(email, full_name, verify_url)
            flash('Radar dünyasına Hoş Geldiniz! Ali\'den gelen onay e-postasını lütfen kontrol edin. Not: Onaylanmadan giriş yapılamaz. Kayıt olduğunuz için teşekkür ederiz. Lütfen devam etmek için mailinize gönderdiğimiz onay mailini kontrol ediniz.', 'success')
        except Exception as e:
            print(f"Mail sending failed: {e}")
            flash('Kaydınız yapıldı ancak onay e-postası gönderilemedi. Lütfen sistem yöneticisiyle iletişime geçin.', 'warning')
            
        session_db.close()
        return redirect(url_for('login'))
        
    return render_template('register.html')

@app.route('/verify_email/<token>')
def verify_email(token):
    try:
        email = ts.loads(token, salt='email-confirm-key', max_age=86400)
    except:
        flash('Geçersiz veya süresi dolmuş doğrulama linki.', 'error')
        return redirect(url_for('login'))
        
    session_db = get_session()
    user = session_db.query(User).filter(User.email == email).first()
    if user:
        user.email_verified = True
        session_db.commit()
        flash('Radar 1.0 dünyasına hoş geldiniz! Hesabınız başarıyla doğrulandı.', 'success')
    
    session_db.close()
    return redirect(url_for('login'))

@app.route('/login/google')
def login_google():
    # Force HTTPS for the redirect_uri
    redirect_uri = url_for('authorize', _external=True, _scheme='https')
    return oauth.google.authorize_redirect(redirect_uri, prompt='select_account')

@app.route('/login/google/callback')
def authorize():
    token = oauth.google.authorize_access_token()
    userinfo = token.get('userinfo')
    if userinfo:
        email = userinfo['email']
        session_db = get_session()
        user = session_db.query(User).filter(User.email == email).first()
        
        if not user:
            name = userinfo.get('name', '')
            # Universal Rule: All new users, including Google, must verify via Ali's email
            user = User(email=email, full_name=name, is_active=True, email_verified=False)
            session_db.add(user)
            session_db.commit()
            session_db.refresh(user)
            
            # Send Branded Welcome/Verification Email for the first time
            try:
                verify_token = ts.dumps(email, salt='email-confirm-key')
                verify_url = url_for('verify_email', token=verify_token, _external=True, _scheme='https')
                send_welcome_email(email, name, verify_url)
                flash('Radar dünyasına Hoş Geldiniz! Ali\'den gelen onay e-postasını lütfen kontrol edin. Not: Onaylanmadan giriş yapılamaz. Kayıt olduğunuz için teşekkür ederiz. Lütfen devam etmek için mailinize gönderdiğimiz onay mailini kontrol ediniz.', 'info')
            except Exception as e:
                print(f"Branded mail failed: {e}")
                
            session_db.close()
            return redirect(url_for('login'))
        else:
            if not getattr(user, 'email_verified', False):
                flash('Lütfen e-postanıza gönderdiğimiz onay linkine tıklayın.', 'info')
                session_db.close()
                return redirect(url_for('login'))
        
        login_user(UserWrapper(user))
        session_db.close()
        return redirect(url_for('index'))
    
    flash('Giriş başarısız oldu.', 'error')
    return redirect(url_for('login'))

@app.route('/send_feedback', methods=['POST'])
@login_required
def send_feedback():
    feedback_text = request.form.get('feedback')
    if not feedback_text:
        return jsonify({'status': 'error', 'message': 'Mesaj boş olamaz.'}), 400
    
    try:
        msg = Message(f'Radar 1.0 - Yeni Geri Bildirim: {current_user.full_name}',
                      recipients=['info@daisoftwares.com'])
        msg.body = f"""
Radar 1.0 Platformundan Yeni Geri Bildirim:

Kullanıcı: {current_user.full_name} ({current_user.email})
Tarih: {datetime.now().strftime('%d/%m/%Y %H:%M')}

Geri Bildirim:
----------------------------------------
{feedback_text}
----------------------------------------

Pazara değil, insanlara hizmet ederiz.
Radar 1.0 Feedback System
"""
        mail.send(msg)
        return jsonify({'status': 'success', 'message': 'Geri bildiriminiz Ali\'ye başarıyla iletildi. Teşekkürler!'})
    except Exception as e:
        print(f"Feedback mail failed: {e}")
        return jsonify({'status': 'error', 'message': 'Geri bildirim gönderilemedi.'}), 500

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/')
@login_required
def index():
    db_session = get_session()
    # Filter: Show samples OR records owned by the current user
    customers = db_session.query(Customer).filter(
        (Customer.is_sample == True) | (Customer.user_id == current_user.id)
    ).order_by(Customer.account_name).all()
    
    customer_list = []
    for c in customers:
        # Last credit score if exists
        score = db_session.query(CreditScore).filter(
            CreditScore.customer_id == c.id
        ).order_by(CreditScore.calculated_at.desc()).first()
        
        # Last credit request
        latest_request = db_session.query(CreditRequest).filter(
            CreditRequest.customer_id == c.id
        ).order_by(CreditRequest.request_date.desc()).first()
        
        customer_list.append({
            'id': c.id,
            'account_code': c.account_code,
            'account_name': c.account_name,
            'last_score': score.credit_note if score else '-',
            'last_request': f"{latest_request.request_amount:,.0f} TL" if latest_request else '-',
            'record_count': db_session.query(AgingRecordDB).filter(AgingRecordDB.customer_id == c.id).count()
        })
    
    db_session.close()
    settings = get_settings()
    return render_template('index.html', customers=customer_list, settings=settings)

@app.route('/customer/<int:customer_id>')
@login_required
def customer_detail(customer_id):
    session = get_session()
    customer = session.query(Customer).filter(
        (Customer.id == customer_id) & 
        ((Customer.is_sample == True) | (Customer.user_id == current_user.id))
    ).first()
    
    if not customer:
        session.close()
        return "Not authorized or Not found", 403
    
    aging_records = session.query(AgingRecordDB).filter(
        AgingRecordDB.customer_id == customer_id
    ).order_by(AgingRecordDB.period.desc()).all()
    
    requests = session.query(CreditRequest).filter(
        CreditRequest.customer_id == customer_id
    ).order_by(CreditRequest.request_date.desc()).all()
    
    request_list = []
    for r in requests:
        score = session.query(CreditScore).filter(
            CreditScore.credit_request_id == r.id
        ).first()
        
        request_list.append({
            'id': r.id,
            'amount': r.request_amount,
            'currency': r.currency,
            'date': r.request_date,
            'status': r.approval_status,
            'note': score.credit_note if score else '-',
            'score': score.final_score if score else 0
        })
    
    session.close()
    return render_template('musteri_detay.html', customer=customer, aging_records=aging_records, requests=request_list)

@app.route('/new_customer', methods=['GET', 'POST'])
@login_required
def new_customer():
    if request.method == 'POST':
        db_session = get_session()
        account_code = request.form.get('account_code', '').strip()
        account_name = request.form.get('account_name', '').strip()
        
        if not account_code or not account_name:
            flash('Account code and name are required', 'error')
            return redirect(url_for('new_customer'))
            
        new_c = Customer(
            user_id=current_user.id, # Set current user as owner
            is_sample=False,
            account_code=account_code,
            account_name=account_name,
            tax_no=request.form.get('tax_no', ''),
            phone=request.form.get('phone', ''),
            email=request.form.get('email', ''),
            equity=float(request.form.get('equity', '0') or 0),
            annual_net_profit=float(request.form.get('net_profit', '0') or 0),
            current_assets=float(request.form.get('current_assets', '0') or 0),
            short_term_liabilities=float(request.form.get('st_liabilities', '0') or 0)
        )
        
        if new_c.short_term_liabilities > 0:
            new_c.liquidity_ratio = new_c.current_assets / new_c.short_term_liabilities
        else:
            new_c.liquidity_ratio = 1.0
            
        db_session.add(new_c)
        db_session.commit()
        db_session.close()
        
        flash(f'{account_name} created successfully', 'success')
        return redirect(url_for('index'))
    return render_template('yeni_musteri.html')

@app.route('/credit_request', methods=['POST'])
@login_required
@request_limit(seconds=10)
def credit_request():
    customer_id = request.form.get('customer_id')
    amount_str = request.form.get('amount')
    currency = request.form.get('currency', 'TL')
    
    try:
        amount = float(amount_str.replace('.', '').replace(',', '.'))
    except:
        flash('Invalid amount', 'error')
        return redirect(url_for('index'))
        
    db_session = get_session()
    customer = db_session.query(Customer).filter(Customer.id == customer_id).first()
    
    if not customer:
        session.close()
        flash('Customer not found', 'error')
        return redirect(url_for('index'))
        
    # Get aging records for calculation
    db_records = db_session.query(AgingRecordDB).filter(
        AgingRecordDB.customer_id == customer_id
    ).order_by(AgingRecordDB.period.desc()).limit(12).all()
    
    calc_records = [AgingRecord(
        period=r.period, overdue=r.overdue, days_1_30=r.days_1_30,
        days_31_60=r.days_31_60, days_61_90=r.days_61_90, days_90_plus=r.days_90_plus,
        total_debt=r.total_debt, type=r.type
    ) for r in db_records]
    
    # Create request
    req = CreditRequest(customer_id=customer_id, request_amount=amount, currency=currency, request_date=datetime.now().date())
    db_session.add(req)
    db_session.flush()
    
    # Calculate score
    settings = get_settings()
    rate = settings.get('interest_rate', 45.0)
    risk = settings.get('sector_risk', 1.0)
    inflation = settings.get('inflation_rate', 55.0)
    
    base_vol = (float(customer.equity or 0) * float(customer.liquidity_ratio or 1.0)) / 12.0
    
    analyzer = AgingAnalyzer()
    
    # Fix: Ensure all records from DB are categorized as 'past' or 'future' if they have 'TL' or similar
    fixed_records = []
    for r in calc_records:
        r.type = 'past' if r.type in ['TL', 'past', 'TL_past'] else r.type
        fixed_records.append(r)
        
    analysis = analyzer.analyze(fixed_records, customer.account_code, customer.account_name, interest_rate=rate)
    
    # Yeni Mimari: Puanlama Motoru (Self-Loading)
    scorer = CreditScorer(customer_id, db_session=db_session)
    from flask import session as flask_session
    lang = flask_session.get('lang', 'tr')
    
    scoring_settings = {
        'interest_rate': rate,
        'sector_risk': risk,
        'inflation_rate': inflation
    }
    
    scoring_request = {
        'request_amount': amount,
        'currency': currency
    }
    
    res = scorer.calculate(scoring_settings, scoring_request, lang=lang)
    
    # Save score
    score_db = CreditScore(
        customer_id=customer_id, credit_request_id=req.id,
        historical_score=res.historical_score, future_score=res.future_score,
        request_score=res.request_score, debt_score=res.debt_score,
        final_score=res.final_score, credit_note=res.credit_note,
        avg_delay_days=res.avg_delay_days, avg_debt=res.avg_debt,
        next_6_months_total=res.future_6_months_total,
        recommended_limit=res.recommended_limit, max_capacity=res.max_capacity,
        instant_equity=customer.equity, instant_liquidity=customer.liquidity_ratio,
        instant_net_profit=customer.annual_net_profit,
        trend_score=res.momentum_score, trend_direction=res.trend_direction,
        assessment=res.assessment,
        decision_summary=res.decision_summary,
        vade_days=res.vade_days,
        vade_message=res.vade_message
    )
    db_session.add(score_db)
    db_session.commit()
    db_session.close()
    
    return redirect(url_for('rapor', talep_id=req.id))

@app.route('/report/<int:talep_id>', endpoint='rapor')
@login_required
def report_view(talep_id):
    db_session = get_session()
    skor = db_session.query(CreditScore).filter(CreditScore.credit_request_id == talep_id).first()
    
    if not skor:
        db_session.close()
        flash('Report not found', 'error')
        return redirect(url_for('index'))
    
    # Auth check: Owner or Sample
    customer = db_session.query(Customer).filter(
        (Customer.id == skor.customer_id) & 
        ((Customer.is_sample == True) | (Customer.user_id == current_user.id))
    ).first()
    
    if not customer:
        db_session.close()
        return "Unauthorized", 403
        
    talep = db_session.query(CreditRequest).filter(CreditRequest.id == talep_id).first()
    
    # Mocking the Scenario results for the view (Since we don't store them all yet)
    from credit_scoring import ScenarioResult
    from flask import session as flask_session
    lang = flask_session.get('lang', 'tr')
    if lang == 'tr':
        scenarios = [
            ScenarioResult("İyimser", "Ödemelerin düzenli devam etmesi", 5.0, skor.final_score + 5),
            ScenarioResult("Kritik", "Yeni bir 30+ gün gecikme", -15.0, skor.final_score - 15)
        ]
    else:
        scenarios = [
            ScenarioResult("Optimistic", "Steady payments continue", 5.0, skor.final_score + 5),
            ScenarioResult("Critical", "New 30+ day delay", -15.0, skor.final_score - 15)
        ]
    
    # Reconstruct the Result-like object for the template
    class ResultWrapper:
        def __init__(self, s, scens):
            self.credit_note = s.credit_note
            self.final_score = s.final_score
            self.decision_summary = s.decision_summary
            self.trend_direction = s.trend_direction
            self.max_capacity = s.max_capacity
            self.recommended_limit = s.recommended_limit
            self.historical_score = s.historical_score
            self.future_score = s.future_score
            self.request_score = s.request_score
            self.momentum_score = s.trend_score
            self.assessment = s.assessment
            self.vade_days = s.vade_days
            self.vade_message = s.vade_message
            self.scenarios = scens
            self.volatility = getattr(s, 'volatility', 0)
            self.dscr_score = getattr(s, 'dscr_score', 0)
            self.z_score = getattr(s, 'z_score', 0)
            self.z_score_note = getattr(s, 'z_score_note', 'N/A')

    sonuc = ResultWrapper(skor, scenarios)
    
    db_session.close()
    return render_template('rapor.html', musteri=customer, talep=talep, skor=skor, sonuc=sonuc)

@app.route('/update_settings', methods=['POST'])
@login_required
def update_settings():
    settings = {
        'interest_rate': float(request.form.get('interest_rate', 45.0)),
        'inflation_rate': float(request.form.get('inflation_rate', 55.0)),
        'sector_risk': float(request.form.get('sector_risk', 1.0))
    }
    save_settings(settings)
    flash('Settings updated', 'success')
    return redirect(url_for('index'))

@app.route('/import_excel', methods=['GET', 'POST'])
@login_required
def import_excel():
    if request.method == 'POST':
        if 'excel_file' not in request.files:
            flash('No file selected', 'error')
            return redirect(url_for('import_excel'))
        
        file = request.files['excel_file']
        temp_path = os.path.join(IMPORTS_DIR, f"tmp_{file.filename}")
        file.save(temp_path)
        
        importer = ExcelImporter()
        aging_recs, cust_map = importer.excel_to_aging_records(temp_path)
        balance_list = importer.excel_to_balance_sheet(temp_path)
        
        session = get_session()
        # Process balance data
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
        flash('Import completed', 'success')
        return redirect(url_for('index'))
    return render_template('import_excel.html')

@app.route('/download_sample')
@login_required
def download_sample():
    sample_path = os.path.join('static', 'radar_1_0_sample.xlsx')
    importer = ExcelImporter()
    importer.create_template(sample_path)
    return send_file(sample_path, as_attachment=True, download_name='radar_1_0_sample.xlsx')

@app.errorhandler(404)
def error_404(e):
    return render_template('errors.html', code=404, message="Aradığınız sayfa bulunamadı."), 404

@app.errorhandler(500)
def error_500(e):
    return render_template('errors.html', code=500, message="Sunucu tarafında bir hata oluştu. Lütfen teknik ekibe bildirin."), 500

from sqlalchemy.exc import OperationalError
@app.errorhandler(OperationalError)
def handle_db_error(e):
    return render_template('errors.html', code="DB", message="Veritabanı bağlantısında bir sorun oluştu. Lütfen tekrar deneyin."), 503

@app.route('/submit_feedback', methods=['POST'])
@login_required
def submit_feedback():
    message = request.json.get('message')
    if not message:
        return jsonify({'status': 'error', 'message': 'Mesaj boş olamaz.'}), 400
    
    session = get_session()
    try:
        new_feedback = Feedback(
            user_id=current_user.id,
            message=message
        )
        session.add(new_feedback)
        session.commit()
        
        # Optional: Send Alert Email to Ali (DynamicAI Founder)
        try:
            admin_msg = Message('Radar 1.0 - Yeni Geri Bildirim Geldi!',
                                recipients=['info@daisoftwares.com'])
            admin_msg.body = f"Kullanıcı: {current_user.full_name} ({current_user.email})\nMesaj: {message}"
            mail.send(admin_msg)
        except Exception as mail_err:
            print(f"Feedback alert email failed: {mail_err}")

        return jsonify({'status': 'success', 'message': 'Geri bildiriminiz Ali\'ye iletildi. Teşekkür ederiz!'})
    except Exception as e:
        session.rollback()
        return jsonify({'status': 'error', 'message': f'Hata: {str(e)}'}), 500
    finally:
        session.close()

if __name__ == '__main__':
    init_db(DATABASE_PATH)
    app.run(debug=True, host='0.0.0.0', port=5001)
