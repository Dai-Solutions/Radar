"""
Internationalization (i18n) utilities
Supports Turkish (tr), English (en), Spanish (es)
"""

from flask import session, request
from flask_babel import Babel, gettext, ngettext, lazy_gettext

SUPPORTED_LOCALES = ['tr', 'en', 'es', 'de']


def _select_locale():
    """Select language from session, URL param, or Accept-Language header."""
    lang = session.get('lang')
    if lang in SUPPORTED_LOCALES:
        return lang

    lang = request.args.get('lang')
    if lang in SUPPORTED_LOCALES:
        session['lang'] = lang
        return lang

    best_match = request.accept_languages.best_match(SUPPORTED_LOCALES)
    return best_match or 'tr'


def init_babel(app):
    """Initialize Flask-Babel (4.x API: locale_selector kwarg)."""
    app.config.setdefault('BABEL_DEFAULT_LOCALE', 'tr')
    app.config.setdefault('BABEL_DEFAULT_TIMEZONE', 'UTC')
    return Babel(app, locale_selector=_select_locale)

def set_language(lang):
    """Set user's preferred language"""
    if lang in ['tr', 'en', 'es', 'de']:
        session['lang'] = lang
        return True
    return False

def get_supported_languages():
    """Get list of supported languages"""
    return {
        'tr': {'name': 'Türkçe', 'flag': '🇹🇷'},
        'en': {'name': 'English', 'flag': '🇬🇧'},
        'es': {'name': 'Español', 'flag': '🇪🇸'},
        'de': {'name': 'Deutsch', 'flag': '🇩🇪'}
    }

# Translation shortcuts
_ = gettext
_n = ngettext
_l = lazy_gettext

# Common translations dictionary for consistency
COMMON_TRANSLATIONS = {
    'tr': {
        'ok': 'Tamam',
        'cancel': 'İptal',
        'save': 'Kaydet',
        'delete': 'Sil',
        'edit': 'Düzenle',
        'back': 'Geri',
        'next': 'İleri',
        'previous': 'Önceki',
        'search': 'Ara',
        'filter': 'Filtre',
        'export': 'Dışa Aktar',
        'import': 'İçe Aktar',
        'loading': 'Yükleniyor...',
        'error': 'Hata',
        'success': 'Başarılı',
        'warning': 'Uyarı',
        'info': 'Bilgi',
    },
    'en': {
        'ok': 'OK',
        'cancel': 'Cancel',
        'save': 'Save',
        'delete': 'Delete',
        'edit': 'Edit',
        'back': 'Back',
        'next': 'Next',
        'previous': 'Previous',
        'search': 'Search',
        'filter': 'Filter',
        'export': 'Export',
        'import': 'Import',
        'loading': 'Loading...',
        'error': 'Error',
        'success': 'Success',
        'warning': 'Warning',
        'info': 'Information',
    },
    'es': {
        'ok': 'Aceptar',
        'cancel': 'Cancelar',
        'save': 'Guardar',
        'delete': 'Eliminar',
        'edit': 'Editar',
        'back': 'Atrás',
        'next': 'Siguiente',
        'previous': 'Anterior',
        'search': 'Buscar',
        'filter': 'Filtrar',
        'export': 'Exportar',
        'import': 'Importar',
        'loading': 'Cargando...',
        'error': 'Error',
        'success': 'Éxito',
        'warning': 'Advertencia',
        'info': 'Información',
    },
    'de': {
        'ok': 'OK',
        'cancel': 'Abbrechen',
        'save': 'Speichern',
        'delete': 'Löschen',
        'edit': 'Bearbeiten',
        'back': 'Zurück',
        'next': 'Weiter',
        'previous': 'Vorherige',
        'search': 'Suchen',
        'filter': 'Filtern',
        'export': 'Exportieren',
        'import': 'Importieren',
        'loading': 'Wird geladen...',
        'error': 'Fehler',
        'success': 'Erfolg',
        'warning': 'Warnung',
        'info': 'Information',
    }
}
