"""
Kurumsal SSO — SAML 2.0 + LDAP/Active Directory

SAML 2.0 : python3-saml (OneLogin) kütüphanesi
LDAP/AD   : ldap3 kütüphanesi

SP-initiated SSO akışı (SAML):
    1. /sso/saml/login  → IdP'ye yönlendir
    2. IdP → POST /sso/saml/acs  → assertion doğrula → giriş
    3. /sso/saml/metadata  → SP metadata XML (IdP'ye kayıt için)

LDAP akışı:
    1. Servis hesabı bind → kullanıcı DN bul
    2. Kullanıcı DN + şifre bind → doğrula
    3. mail + displayName oku → giriş
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────
# SAML 2.0 Provider
# ──────────────────────────────────────────────────────────────

class SAMLProvider:
    """
    SP-initiated SAML 2.0 SSO.

    IdP metadata (entity ID, SSO URL, X.509 sertifikası) SSOConfig
    tablosundan okunur; SP callback URL'leri app_prefix'ten türetilir.
    """

    def __init__(self, sso_config, app_prefix: str = '/radar'):
        self.config = sso_config
        self.app_prefix = app_prefix.rstrip('/')

    def _build_settings(self, base_url: str) -> dict:
        c = self.config
        return {
            'strict': True,
            'debug': False,
            'sp': {
                'entityId': c.sp_entity_id or f'{base_url}/sso/saml/metadata',
                'assertionConsumerService': {
                    'url': f'{base_url}/sso/saml/acs',
                    'binding': 'urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST',
                },
                'singleLogoutService': {
                    'url': f'{base_url}/sso/saml/logout',
                    'binding': 'urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect',
                },
                'NameIDFormat': 'urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress',
                'x509cert': '',
                'privateKey': '',
            },
            'idp': {
                'entityId': c.idp_entity_id or '',
                'singleSignOnService': {
                    'url': c.idp_sso_url or '',
                    'binding': 'urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect',
                },
                'singleLogoutService': {
                    'url': c.idp_slo_url or c.idp_sso_url or '',
                    'binding': 'urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect',
                },
                'x509cert': (c.idp_x509_cert or '').strip(),
            },
            'security': {
                'authnRequestsSigned': False,
                'wantAssertionsSigned': True,
                'wantMessagesSigned': False,
                'signMetadata': False,
            },
        }

    def _prepare_request(self, flask_request) -> dict:
        """Flask request nesnesi → python3-saml formatı."""
        return {
            'https': 'on' if flask_request.is_secure else 'off',
            'http_host': flask_request.host,
            'script_name': flask_request.path,
            'get_data': flask_request.args.copy(),
            'post_data': flask_request.form.copy(),
            'query_string': flask_request.query_string.decode('utf-8'),
        }

    def _base_url(self, flask_request) -> str:
        scheme = 'https' if flask_request.is_secure else 'http'
        return f"{scheme}://{flask_request.host}{self.app_prefix}"

    def init_auth(self, flask_request):
        """OneLogin_Saml2_Auth nesnesi döndürür."""
        try:
            from onelogin.saml2.auth import OneLogin_Saml2_Auth
        except ImportError:
            raise RuntimeError('python3-saml kurulu değil: pip install python3-saml')

        settings = self._build_settings(self._base_url(flask_request))
        return OneLogin_Saml2_Auth(self._prepare_request(flask_request), settings)

    def get_login_url(self, auth) -> str:
        return auth.login()

    def get_metadata(self, flask_request) -> tuple[str, list]:
        """SP metadata XML ve varsa hata listesini döndürür."""
        try:
            from onelogin.saml2.settings import OneLogin_Saml2_Settings
        except ImportError:
            return '', ['python3-saml kurulu değil']

        settings_obj = OneLogin_Saml2_Settings(self._build_settings(self._base_url(flask_request)))
        metadata = settings_obj.get_sp_metadata()
        errors = settings_obj.validate_metadata(metadata)
        return metadata, errors

    def process_response(self, auth) -> dict:
        """
        ACS POST'unu işler.
        Başarılıysa {'email': ..., 'name': ..., 'attributes': {...}} döner.
        Başarısızsa ValueError fırlatır.
        """
        auth.process_response()
        errors = auth.get_errors()
        if errors:
            reason = auth.get_last_error_reason() or ', '.join(errors)
            raise ValueError(f'SAML doğrulama hatası: {reason}')

        if not auth.is_authenticated():
            raise ValueError('SAML kimlik doğrulaması başarısız')

        attrs = auth.get_attributes()
        name_id = auth.get_nameid() or ''

        # E-posta: NameID > claim URI > kısa attr adı sırasıyla dener
        email = name_id
        for key in (
            'mail', 'email',
            'http://schemas.xmlsoap.org/ws/2005/05/identity/claims/emailaddress',
            'http://schemas.xmlsoap.org/claims/EmailAddress',
        ):
            val = attrs.get(key)
            if val:
                email = val[0] if isinstance(val, list) else val
                break

        # Görünen ad
        name = ''
        for key in (
            'displayName', 'cn',
            'http://schemas.microsoft.com/identity/claims/displayname',
            'http://schemas.xmlsoap.org/ws/2005/05/identity/claims/name',
        ):
            val = attrs.get(key)
            if val:
                name = val[0] if isinstance(val, list) else val
                break
        if not name:
            given = (attrs.get('givenName') or [''])[0]
            sn = (attrs.get('sn') or [''])[0]
            name = f'{given} {sn}'.strip()

        return {'email': email.strip().lower(), 'name': name, 'attributes': attrs}


# ──────────────────────────────────────────────────────────────
# LDAP / Active Directory Provider
# ──────────────────────────────────────────────────────────────

class LDAPProvider:
    """
    LDAP / Active Directory kimlik doğrulama.

    Akış:
        1. Servis hesabı (bind_dn) ile bağlan → kullanıcı DN bul
        2. Kullanıcı DN + şifresiyle bağlan → doğrula
        3. mail + displayName attr'larını oku → döndür
    """

    def __init__(self, sso_config):
        self.config = sso_config

    def authenticate(self, username: str, password: str) -> dict:
        """
        Kullanıcı adı + şifre ile LDAP kimlik doğrulama.
        Başarılıysa {'email': ..., 'name': ...} döner.
        Başarısızsa ValueError fırlatır.
        """
        try:
            from ldap3 import Server, Connection, ALL
        except ImportError:
            raise RuntimeError('ldap3 kurulu değil: pip install ldap3')

        c = self.config
        host = c.ldap_host or 'localhost'
        port = int(c.ldap_port or 389)
        use_ssl = bool(c.ldap_use_ssl)
        email_attr = c.ldap_email_attr or 'mail'
        name_attr = c.ldap_name_attr or 'displayName'
        search_filter = (
            c.ldap_user_search_filter or '(sAMAccountName={username})'
        ).format(username=username)

        server = Server(host, port=port, use_ssl=use_ssl, get_info=ALL)

        # Adım 1: servis hesabı bind → kullanıcı DN bul
        try:
            svc = Connection(
                server,
                user=c.ldap_bind_dn,
                password=c.ldap_bind_password,
                auto_bind=True,
            )
        except Exception as e:
            logger.error('LDAP service bind failed: %s', e)
            raise ValueError('LDAP servis bağlantısı kurulamadı')

        svc.search(
            search_base=c.ldap_base_dn or '',
            search_filter=search_filter,
            attributes=[email_attr, name_attr, 'distinguishedName'],
        )

        if not svc.entries:
            svc.unbind()
            raise ValueError('Kullanıcı bulunamadı')

        entry = svc.entries[0]
        user_dn = str(entry.entry_dn)
        svc.unbind()

        # Adım 2: kullanıcı DN + şifre bind → doğrula
        try:
            user_conn = Connection(server, user=user_dn, password=password, auto_bind=True)
        except Exception:
            raise ValueError('Kullanıcı adı veya şifre hatalı')

        # Adım 3: kullanıcı bilgilerini oku
        user_conn.search(
            search_base=user_dn,
            search_filter='(objectClass=*)',
            attributes=[email_attr, name_attr],
            search_scope='BASE',
        )

        email = ''
        name = ''
        if user_conn.entries:
            ue = user_conn.entries[0]
            raw_email = getattr(ue, email_attr, None)
            raw_name = getattr(ue, name_attr, None)
            email = str(raw_email) if raw_email else ''
            name = str(raw_name) if raw_name else ''

        user_conn.unbind()

        # mail attr boşsa domain'den türet
        if not email:
            email = f'{username}@{host}'

        return {'email': email.strip().lower(), 'name': name}
