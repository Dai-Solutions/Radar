"""Güvenlik katmanı: CSRF, rate limit, security headers, request_id korelasyonu."""
import logging
import os
import uuid

from flask import g, request
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_talisman import Talisman
from flask_wtf.csrf import CSRFProtect

logger = logging.getLogger(__name__)

csrf = CSRFProtect()

# Login bruteforce ve API spam'e karşı default limitler.
# Storage: in-memory (tek worker için OK; multi-worker'da Redis önerilir).
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["1000 per hour", "100 per minute"],
    storage_uri=os.getenv('LIMITER_STORAGE_URI', 'memory://'),
    headers_enabled=True,  # X-RateLimit-* yanıt header'ları
)


def init_security(app):
    """Tüm güvenlik katmanlarını sırayla bağlar."""

    # ── CSRF ────────────────────────────────────────────────
    csrf.init_app(app)
    # API blueprint'i token-tabanlı olduğu için CSRF muaf
    try:
        from api_docs import api_bp
        csrf.exempt(api_bp)
    except Exception as e:
        logger.warning(f'CSRF exempt for api_bp failed: {e}')

    # ── Rate Limiter ────────────────────────────────────────
    limiter.init_app(app)

    # ── Security Headers (Talisman) ─────────────────────────
    # CSP devre dışı: çok sayıda inline style/script var; ayrı bir refactor gerektirir.
    # Diğer header'lar (HSTS, X-Frame-Options, X-Content-Type-Options, Referrer-Policy)
    # default ile geliyor. force_https=False çünkü TLS terminate nginx'te.
    Talisman(
        app,
        force_https=False,
        strict_transport_security=True,
        strict_transport_security_max_age=31536000,
        session_cookie_secure=False,  # cookie config app.py'de yönetiliyor
        content_security_policy=None,
        frame_options='SAMEORIGIN',
        referrer_policy='strict-origin-when-cross-origin',
    )

    # ── Request ID middleware ───────────────────────────────
    # Her request'e UUID atayıp log korelasyonu için g.request_id'ye koyar,
    # response header'ında da X-Request-ID olarak dönder.
    @app.before_request
    def _attach_request_id():
        rid = request.headers.get('X-Request-ID') or uuid.uuid4().hex[:16]
        g.request_id = rid

    @app.after_request
    def _emit_request_id(response):
        rid = getattr(g, 'request_id', None)
        if rid:
            response.headers['X-Request-ID'] = rid
        return response

    logger.info('Security extensions initialized: CSRF + Limiter + Talisman + request_id')
