from flask import Blueprint, render_template, request, redirect, url_for, flash, session, current_app, jsonify
from flask_login import login_user, logout_user, current_user, UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from flask_mail import Message
import datetime
import time

from extensions import login_manager, oauth, mail, ts
from database import get_session, User, Feedback
from translations import translations

auth_bp = Blueprint('auth', __name__)

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

def send_welcome_email(email, full_name, verify_url):
    html_content = f"""
    <div style="font-family: 'Outfit', sans-serif; max-width: 600px; margin: auto; padding: 20px; border: 1px solid #333; border-radius: 12px; background-color: #111; color: #fff;">
        <div style="text-align: center; margin-bottom: 30px;">
            <h1 style="color: #3b82f6; margin: 0;">{current_app.config['APP_VERSION']}</h1>
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
            <a href="{verify_url}" style="background-color: #3b82f6; color: white; padding: 15px 25px; text-decoration: none; border-radius: 8px; font-weight: bold; font-size: 16px;">HESABIMI DOĞRULA VE GİRİŞ YAP</a>
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

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))
    
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password')
        
        db_session = get_session()
        user = db_session.query(User).filter(User.email == email).first()
        
        if user and user.password_hash and check_password_hash(user.password_hash, password):
            if not getattr(user, 'email_verified', False):
                flash('Lütfen hesabınızı e-postanıza gönderdiğimiz onay maili ile doğrulayın.', 'error')
                db_session.close()
                return redirect(url_for('auth.login'))
                
            login_user(UserWrapper(user))
            db_session.close()
            flash(f'Hoş geldiniz, {user.full_name or email}', 'success')
            return redirect(url_for('main.index'))
        
        db_session.close()
        flash('Geçersiz e-posta veya şifre.', 'error')
    
    return render_template('login.html')

@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))
    
    if request.method == 'POST':
        full_name = request.form.get('full_name')
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password')
        
        session_db = get_session()
        existing_user = session_db.query(User).filter(User.email == email).first()
        
        if existing_user:
            session_db.close()
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
        
        # Send Branded Verification Email
        try:
            from extensions import ts
            token = ts.dumps(email, salt='email-confirm-key')
            verify_url = url_for('auth.verify_email', token=token, _external=True, _scheme='https')
            send_welcome_email(email, full_name, verify_url)
            flash(f"{current_app.config['APP_VERSION']} dünyasına Hoş Geldiniz! Dynamic AI'dan gelen onay e-postasını lütfen kontrol edin.", 'success')
        except Exception as e:
            current_app.logger.error(f"Mail sending failed: {e}")
            flash('Kaydınız yapıldı ancak onay e-postası gönderilemedi.', 'warning')
            
        session_db.close()
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
    user = session_db.query(User).filter(User.email == email).first()
    if user:
        user.email_verified = True
        session_db.commit()
        flash(f"{current_app.config['APP_VERSION']} dünyasına hoş geldiniz! Hesabınız başarıyla doğrulandı.", 'success')
    
    session_db.close()
    return redirect(url_for('auth.login'))

@auth_bp.route('/login/google')
def login_google():
    redirect_uri = url_for('auth.authorize', _external=True, _scheme='https')
    return oauth.google.authorize_redirect(redirect_uri, prompt='select_account')

@auth_bp.route('/login/google/callback')
def authorize():
    token = oauth.google.authorize_access_token()
    userinfo = token.get('userinfo')
    if userinfo:
        email = userinfo['email'].strip().lower()
        session_db = get_session()
        user = session_db.query(User).filter(User.email == email).first()
        
        if not user:
            name = userinfo.get('name', '')
            user = User(email=email, full_name=name, is_active=True, email_verified=False)
            session_db.add(user)
            session_db.commit()
            session_db.refresh(user)
            
            try:
                from extensions import ts
                verify_token = ts.dumps(email, salt='email-confirm-key')
                verify_url = url_for('auth.verify_email', token=verify_token, _external=True, _scheme='https')
                send_welcome_email(email, name, verify_url)
                flash(f"{current_app.config['APP_VERSION']} dünyasına Hoş Geldiniz! Lütfen mailinize gönderdiğimiz onay mailini kontrol ediniz.", 'info')
            except Exception as e:
                current_app.logger.error(f"Branded mail failed: {e}")
                
            session_db.close()
            return redirect(url_for('auth.login'))
        else:
            if not getattr(user, 'email_verified', False):
                flash('Lütfen e-postanıza gönderdiğimiz onay linkine tıklayın.', 'info')
                session_db.close()
                return redirect(url_for('auth.login'))
        
        login_user(UserWrapper(user))
        session_db.close()
        return redirect(url_for('main.index'))
    
    flash('Giriş başarısız oldu.', 'error')
    return redirect(url_for('auth.login'))

@auth_bp.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('auth.login'))
