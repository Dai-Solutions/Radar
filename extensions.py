from flask_mail import Mail
from itsdangerous import URLSafeTimedSerializer
from flask_login import LoginManager
from authlib.integrations.flask_client import OAuth

mail = Mail()
login_manager = LoginManager()
oauth = OAuth()

# Serializer will be initialized in app factory since it needs secret_key
ts = None

def init_extensions(app):
    global ts
    mail.init_app(app)
    login_manager.init_app(app)
    oauth.init_app(app)
    
    # Initialize serializer
    ts = URLSafeTimedSerializer(app.secret_key)
    
    # Configuration
    login_manager.login_view = 'auth.login'
    login_manager.login_message = "Lütfen devam etmek için giriş yapın."
    login_manager.login_message_category = "info"
