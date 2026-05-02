import os
import logging
from logging.handlers import RotatingFileHandler
from flask import Flask, render_template, session, redirect, url_for, request
from werkzeug.middleware.proxy_fix import ProxyFix
from dotenv import load_dotenv

# Shared extensions
from extensions import init_extensions, login_manager

# i18n & Enterprise
from i18n_utils import init_babel
from enterprise import init_enterprise_features
from api_docs import init_swagger, api_bp

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
    
    # Apply ProxyFix to handle X-Forwarded-Proto/For/Host from Nginx/Cloudflare
    # x_prefix omitted — SCRIPT_NAME is forced below from APP_PREFIX env var
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    # Prefix configuration for internal logic (branding/cookies)
    APP_PREFIX = os.getenv('APP_PREFIX', '/solutions/radar')

    # Force SCRIPT_NAME from APP_PREFIX so url_for() generates prefixed URLs
    # even when Cloudflare/CDN strips X-Forwarded-Prefix headers
    if APP_PREFIX and APP_PREFIX != '/':
        _inner_wsgi = app.wsgi_app
        def _force_script_name(environ, start_response, _p=APP_PREFIX, _w=_inner_wsgi):
            environ['SCRIPT_NAME'] = _p
            return _w(environ, start_response)
        app.wsgi_app = _force_script_name
    
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
    app.config['APP_VERSION'] = os.getenv('APP_VERSION', 'Radar 2.0')
    app.config['APP_PREFIX'] = APP_PREFIX
    
    # OAuth Config
    app.config['GOOGLE_CLIENT_ID'] = os.getenv('GOOGLE_CLIENT_ID')
    app.config['GOOGLE_CLIENT_SECRET'] = os.getenv('GOOGLE_CLIENT_SECRET')
    # Authlib reads from app.config if we use oauth.register(name='google', ...)
    # But currently auth.py uses oauth.register directly. We'll fix it in extensions or auth.
    
    # Initialize extensions
    init_extensions(app)

    # Security layer: CSRF, rate limit, headers, request_id
    from security_extensions import init_security
    init_security(app)
    
    # Initialize i18n (Babel for multi-language support)
    init_babel(app)
    
    # Initialize Swagger/OpenAPI documentation
    init_swagger(app)
    
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
    app.register_blueprint(api_bp)  # API documentation & endpoints
    
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
        from flask_login import current_user
        from routes.auth import is_admin_user
        lang = session.get('lang', 'tr')
        is_admin = current_user.is_authenticated and is_admin_user(current_user)
        return dict(
            lang=lang,
            t=_translations_resolved.get(lang, _translations_resolved['tr']),
            all_langs=['tr', 'en', 'es', 'de'],  # Added German (de)
            total_users=_get_user_count(),
            app_version=app.config['APP_VERSION'],
            is_admin=is_admin,
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

    # Schema bootstrap + lightweight migrations (must run before enterprise init,
    # which inserts Role rows). Runs under gunicorn too, not just __main__.
    init_db()

    # Initialize enterprise features (default tenant backfill, RBAC roles)
    init_enterprise_features(app)

    return app

app = create_app()

# Google Auth Compatibility Route (Console matches /solutions/radar)
@app.route('/solutions/radar/login/google/callback')
def google_callback_compatibility():
    return redirect(url_for('auth.authorize', **request.args))

if __name__ == '__main__':
    app.run(host="0.0.0.0", port=8005)
