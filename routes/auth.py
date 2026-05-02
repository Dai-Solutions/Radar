from flask import Blueprint, render_template, request, redirect, url_for, flash, session, current_app, jsonify
from flask_login import login_user, logout_user, current_user, UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from flask_mail import Message
from markupsafe import escape
import datetime
import time

from extensions import login_manager, oauth, mail
from security_extensions import limiter
# NOTE: `ts` (URLSafeTimedSerializer) is NOT imported here — it's None at module
# import time and only gets set inside init_extensions(). All callsites use
# `from extensions import ts as _ts` locally to capture the live value.
from database import get_session, User, Feedback
from translations import translations

auth_bp = Blueprint('auth', __name__)

class UserWrapper(UserMixin):
    def __init__(self, user_obj):
        self.id = user_obj.id
        self.email = user_obj.email
        self.full_name = user_obj.full_name
        self.email_verified = getattr(user_obj, 'email_verified', False)
        self.is_admin = bool(getattr(user_obj, 'is_admin', False))

@login_manager.user_loader
def load_user(user_id):
    db_session = get_session()
    user = db_session.query(User).filter(User.id == int(user_id)).first()
    db_session.close()
    if user:
        return UserWrapper(user)
    return None

def send_welcome_email(email, full_name, verify_url):
    safe_name = escape(full_name or '')
    safe_url = escape(verify_url)
    safe_version = escape(current_app.config['APP_VERSION'])
    html_content = f"""
    <div style="font-family: 'Outfit', sans-serif; max-width: 600px; margin: auto; padding: 20px; border: 1px solid #333; border-radius: 12px; background-color: #111; color: #fff;">
        <div style="text-align: center; margin-bottom: 30px;">
            <h1 style="color: #3b82f6; margin: 0;">{safe_version}</h1>
            <p style="color: #999; font-size: 14px; margin: 5px 0;">Let dai do it for you</p>
        </div>

        <p>Merhaba <strong>{safe_name}</strong>,</p>
        
        <p>DAI Technology'nin geliştirdiği bu test uygulamasına giriş yaptığın için çok teşekkürler!</p>
        
        <p>Bizim çok inandığımız temel bir mottomuz var:<br>
        <strong>Pazara değil, insanlara hizmet ederiz.</strong></p>
        
        <p>Bu felsefeyle kurduğumuz VOID topluluğu altında, her zaman şeffaf ve açık kaynaklı çözümler üretmeye odaklanıyoruz. Şu an deneyimlediğin bu uygulama da tam olarak bu vizyonun bir parçası.</p>
        
        <p>Sistem henüz test aşamasında olduğu için, senin gibi değerli kullanıcıların geri bildirimleri bizim için altın değerinde. Gördüğün hataları, geliştirilebilecek yerleri veya aklına gelen fikirleri bizimle paylaşırsan harika olur.</p>
        
        <p>Ayrıca, bağımsız ve açık kaynaklı projeler üretmeye devam edebilmemiz için topluluk desteği çok önemli. Eğer vizyonumuzu ve uygulamalarımızı beğeniyorsan, bize yapacağın küçük bir bağış/destek, bu projeleri hayatta tutmamız ve "pazar" yerine "insanlara" hizmet etmeye devam etmemiz için en büyük gücümüz olacak.</p>
        
        <div style="text-align: center; margin: 40px 0;">
            <a href="{safe_url}" style="background-color: #3b82f6; color: white; padding: 15px 25px; text-decoration: none; border-radius: 8px; font-weight: bold; font-size: 16px;">HESABIMI DOĞRULA VE GİRİŞ YAP</a>
        </div>
 
        <p style="color: #999; font-size: 14px;">Desteğin ve geri bildirimlerin için şimdiden teşekkürler!<br>Görüşmek üzere,</p>
        
        <p><strong>Dynamic AI</strong><br>
        Kothar Khasis<br>
        DynamicAI & VOID Topluluğu Kurucusu</p>
    </div>
    """
    msg = Message(f"{current_app.config['APP_VERSION']} - DAI Dünyasına Hoş Geldiniz!",
                  recipients=[email])
    msg.html = html_content
    mail.send(msg)


def is_admin_user(user):
    """Check if a user (UserWrapper or User row) has admin privileges."""
    if user is None:
        return False
    if getattr(user, 'is_admin', False):
        return True
    admin_email = (current_app.config.get('ADMIN_EMAIL') or '').strip().lower()
    user_email = (getattr(user, 'email', '') or '').strip().lower()
    return bool(admin_email) and admin_email == user_email


def admin_required(f):
    """Decorator that allows only admins through."""
    from functools import wraps
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated or not is_admin_user(current_user):
            flash('Bu işlem için yetkiniz yok.', 'error')
            return redirect(url_for('main.index'))
        return f(*args, **kwargs)
    return wrapper

@auth_bp.route('/login', methods=['GET', 'POST'])
@limiter.limit("10 per minute; 50 per hour", methods=['POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))
    
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password')

        db_session = get_session()
        try:
            user = db_session.query(User).filter(User.email == email).first()

            if user and user.password_hash and check_password_hash(user.password_hash, password):
                if not getattr(user, 'email_verified', False):
                    flash('Lütfen hesabınızı e-postanıza gönderdiğimiz onay maili ile doğrulayın.', 'error')
                    return redirect(url_for('auth.login'))

                login_user(UserWrapper(user))
                flash(f'Hoş geldiniz, {user.full_name or email}', 'success')
                return redirect(url_for('main.index'))

            flash('Geçersiz e-posta veya şifre.', 'error')
        finally:
            db_session.close()

    return render_template('login.html')

@auth_bp.route('/register', methods=['GET', 'POST'])
@limiter.limit("5 per minute; 20 per hour", methods=['POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))
    
    if request.method == 'POST':
        full_name = request.form.get('full_name')
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password')
        
        session_db = get_session()
        try:
            existing_user = session_db.query(User).filter(User.email == email).first()
            if existing_user:
                lang = session.get('lang', 'tr')
                flash(translations[lang]['already_registered_hint'], 'error')
                return redirect(url_for('auth.register'))

            new_user = User(
                full_name=full_name,
                email=email,
                password_hash=generate_password_hash(password),
                is_active=True,
                email_verified=False
            )
            session_db.add(new_user)
            session_db.commit()
        except Exception:
            session_db.rollback()
            raise
        finally:
            session_db.close()

        try:
            # extensions.ts module-level binding gets set in init_extensions(),
            # but `from extensions import ts` at top captured the original None.
            # Re-import inside function to get the live serializer.
            from extensions import ts as _ts
            verify_token = _ts.dumps(email, salt='email-confirm-key')
            domain = current_app.config.get('DOMAIN_NAME', 'daisoftwares.com')
            prefix = current_app.config.get('APP_PREFIX', '/solutions/radar')
            verify_url = f"https://{domain}{prefix}/verify_email/{verify_token}"
            send_welcome_email(email, full_name, verify_url)
            flash(f"{current_app.config['APP_VERSION']} dünyasına Hoş Geldiniz! Dynamic AI'dan gelen onay e-postasını lütfen kontrol edin.", 'success')
        except Exception as e:
            current_app.logger.error(f"Mail sending failed: {e}")
            flash('Kaydınız yapıldı ancak onay e-postası gönderilemedi.', 'warning')

        return redirect(url_for('auth.login'))
        
    return render_template('register.html')

@auth_bp.route('/verify_email/<token>')
def verify_email(token):
    from extensions import ts
    try:
        email = ts.loads(token, salt='email-confirm-key', max_age=86400).strip().lower()
    except:
        flash('Geçersiz veya süresi dolmuş doğrulama linki.', 'error')
        return redirect(url_for('auth.login'))
        
    session_db = get_session()
    try:
        user = session_db.query(User).filter(User.email == email).first()
        if user:
            user.email_verified = True
            session_db.commit()
            flash(f"{current_app.config['APP_VERSION']} dünyasına hoş geldiniz! Hesabınız başarıyla doğrulandı.", 'success')
    finally:
        session_db.close()
    return redirect(url_for('auth.login'))

@auth_bp.route('/login/google')
def login_google():
    # Google Console'da tanımlı olan adrese sadık kalıyoruz (technodai.com/radar)
    redirect_uri = "https://technodai.com/radar/login/google/callback"
    return oauth.google.authorize_redirect(redirect_uri, prompt='select_account')

@auth_bp.route('/login/google/callback')
def authorize():
    # authlib >=1.3 redirect_uri'yi state'ten otomatik okur; açıkça geçmek
    # "multiple values for keyword argument 'redirect_uri'" hatasına yol açar.
    token = oauth.google.authorize_access_token()
    userinfo = token.get('userinfo')
    if userinfo:
        email = userinfo['email'].strip().lower()
        session_db = get_session()
        try:
            user = session_db.query(User).filter(User.email == email).first()

            if not user:
                name = userinfo.get('name', '')
                user = User(email=email, full_name=name, is_active=True, email_verified=False)
                session_db.add(user)
                session_db.commit()
                session_db.refresh(user)

                try:
                    from extensions import ts as _ts
                    verify_token = _ts.dumps(email, salt='email-confirm-key')
                    domain = current_app.config.get('DOMAIN_NAME', 'technodai.com')
                    prefix = current_app.config.get('APP_PREFIX', '/radar')
                    verify_url = f"https://{domain}{prefix}/verify_email/{verify_token}"
                    send_welcome_email(email, name, verify_url)
                    flash(f"Radar dünyasına Hoş Geldiniz! Lütfen e-postanıza ({email}) gönderdiğimiz onay linkine tıklayınız.", 'info')
                except Exception as e:
                    current_app.logger.error(f"Mail failed: {e}")

                return redirect(url_for('auth.login'))

            if not getattr(user, 'email_verified', False):
                flash('Lütfen e-postanıza gönderdiğimiz onay linkine tıklayın.', 'info')
                return redirect(url_for('auth.login'))

            login_user(UserWrapper(user))
            return redirect(url_for('main.index'))
        finally:
            session_db.close()
    
    flash('Giriş başarısız oldu.', 'error')
    return redirect(url_for('auth.login'))

@auth_bp.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('auth.login'))
