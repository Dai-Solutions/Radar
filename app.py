import os
import logging
from logging.handlers import RotatingFileHandler
from flask import Flask, render_template, session
from werkzeug.middleware.proxy_fix import ProxyFix
from dotenv import load_dotenv

# Shared extensions
from extensions import init_extensions, login_manager

# Blueprints
from routes.auth import auth_bp
from routes.main import main_bp
from routes.customer import customer_bp
from routes.scoring import scoring_bp
from routes.admin import admin_bp

# Logic & Utils
from database import init_db, get_session, remove_session, User
from translations import translations

def create_app():
    # Load environment variables
    dotenv_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '.env'))
    load_dotenv(dotenv_path, override=True)
    
    app = Flask(__name__)
    app.secret_key = os.getenv('FLASK_SECRET_KEY', 'radar_1_0_secret_key')
    # Global upload tavanı (10 MB) — admin Excel import'u için yeterli, DoS yüzeyi azaltır
    app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024
    
    # Apply ProxyFix to handle X-Forwarded-Proto and X-Forwarded-Prefix from Nginx
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)
    
    # Prefix configuration for internal logic (branding/cookies)
    APP_PREFIX = os.getenv('APP_PREFIX', '/solutions/radar')
    
    # Session Cookie & Security Configuration
    app.config['SESSION_COOKIE_NAME'] = 'radar_session_id'
    app.config['SESSION_COOKIE_PATH'] = APP_PREFIX
    app.config['SESSION_COOKIE_SECURE'] = True
    app.config['SESSION_COOKIE_HTTPONLY'] = True
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
    
    # Mail Config (inherited from .env)
    app.config['MAIL_SERVER'] = os.getenv('MAIL_SERVER', 'smtp.gmail.com')
    app.config['MAIL_PORT'] = int(os.getenv('MAIL_PORT', 587))
    app.config['MAIL_USE_TLS'] = os.getenv('MAIL_USE_TLS', 'True') == 'True'
    app.config['MAIL_USERNAME'] = os.getenv('MAIL_USERNAME', 'info@daisoftwares.com')
    app.config['MAIL_PASSWORD'] = os.getenv('MAIL_PASSWORD')
    app.config['MAIL_DEFAULT_SENDER'] = os.getenv('MAIL_USERNAME', 'info@daisoftwares.com')
    
    # Branding & Domain
    app.config['DOMAIN_NAME'] = os.getenv('DOMAIN_NAME', 'daisoftwares.com')
    app.config['ADMIN_EMAIL'] = os.getenv('ADMIN_EMAIL', 'info@daisoftwares.com')
    app.config['APP_VERSION'] = os.getenv('APP_VERSION', 'Radar 1.0')
    app.config['APP_PREFIX'] = APP_PREFIX
    
    # OAuth Config
    app.config['GOOGLE_CLIENT_ID'] = os.getenv('GOOGLE_CLIENT_ID')
    app.config['GOOGLE_CLIENT_SECRET'] = os.getenv('GOOGLE_CLIENT_SECRET')
    # Authlib reads from app.config if we use oauth.register(name='google', ...)
    # But currently auth.py uses oauth.register directly. We'll fix it in extensions or auth.
    
    # Initialize extensions
    init_extensions(app)
    
    # Register Google OAuth (needs to be done with secret info)
    from extensions import oauth
    oauth.register(
        name='google',
        client_id=app.config['GOOGLE_CLIENT_ID'],
        client_secret=app.config['GOOGLE_CLIENT_SECRET'],
        server_metadata_url=os.getenv('CONF_URL'),
        client_kwargs={'scope': 'openid email profile'}
    )
    
    # Register blueprints
    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(customer_bp)
    app.register_blueprint(scoring_bp)
    app.register_blueprint(admin_bp)
    
    # Çeviri sözlüklerini app start'ta bir kez prefix ile materialize et
    import json as _json
    _prefix = app.config.get('APP_PREFIX', os.getenv('APP_PREFIX', '/solutions/radar'))
    _translations_resolved = {
        _lang: _json.loads(_json.dumps(_dict).replace('{prefix}', _prefix))
        for _lang, _dict in translations.items()
    }

    # User count cache (60 saniye TTL) — her request'te COUNT(*) atmamak için
    _user_count_cache = {'value': 0, 'expires_at': 0.0}
    USER_COUNT_TTL = 60.0

    def _get_user_count():
        import time as _time
        now = _time.time()
        if now < _user_count_cache['expires_at']:
            return _user_count_cache['value']
        s = get_session()
        try:
            count = s.query(User).count()
        finally:
            s.close()
        _user_count_cache['value'] = count
        _user_count_cache['expires_at'] = now + USER_COUNT_TTL
        return count

    @app.context_processor
    def inject_global_vars():
        lang = session.get('lang', 'tr')
        return dict(
            lang=lang,
            t=_translations_resolved.get(lang, _translations_resolved['tr']),
            all_langs=['tr', 'en'],
            total_users=_get_user_count(),
            app_version=app.config['APP_VERSION']
        )
    
    # Error Handlers
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
    
    # Logger
    from logger import setup_logger
    setup_logger(app)

    @app.teardown_appcontext
    def _cleanup_session(exception=None):
        remove_session()

    return app

app = create_app()

if __name__ == '__main__':
    init_db()
    app.run(debug=True, port=8001)
