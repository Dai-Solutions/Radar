"""Security smoke tests — repository hijyeni ve temel auth korumaları.

Hızlı çalışan, DB gerektirmeyen kontroller. CI'da her PR'da koşmalı.
"""
import os
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

# ── Repo hijyeni ────────────────────────────────────────────────────────────

@pytest.mark.security
def test_env_not_tracked():
    """`.env` git'e commit edilmemiş olmalı."""
    result = subprocess.run(
        ['git', 'ls-files', '.env'], cwd=ROOT, capture_output=True, text=True
    )
    assert result.stdout.strip() == '', '.env git\'e commit edilmiş!'


@pytest.mark.security
def test_no_other_env_files_tracked():
    """`.env.local`, `.env.prod` gibi varyantlar da commit edilmemeli."""
    result = subprocess.run(
        ['git', 'ls-files'], cwd=ROOT, capture_output=True, text=True
    )
    forbidden = re.compile(r'(^|/)\.env(\.|$)(?!example)')
    leaked = [f for f in result.stdout.splitlines() if forbidden.search(f)]
    assert not leaked, f'Hassas env dosyaları git\'te: {leaked}'


@pytest.mark.security
def test_no_private_keys_tracked():
    """`.pem`, `.key`, `id_rsa` gibi anahtar dosyaları repoda olmamalı."""
    result = subprocess.run(
        ['git', 'ls-files'], cwd=ROOT, capture_output=True, text=True
    )
    pattern = re.compile(r'\.(pem|key|p12|pfx)$|(^|/)id_(rsa|dsa|ed25519)$')
    leaked = [f for f in result.stdout.splitlines() if pattern.search(f)]
    assert not leaked, f'Özel anahtar dosyaları repoda: {leaked}'


@pytest.mark.security
def test_no_hardcoded_secrets_in_python():
    """Python kodunda hardcoded secret pattern'i olmamalı.

    `os.environ`, `getenv`, `config[]` gibi env okuma kalıpları muaftır.
    """
    suspicious = re.compile(
        r'''(SECRET_KEY|PASSWORD|API_KEY|TOKEN|CLIENT_SECRET)\s*=\s*['"][A-Za-z0-9+/=_\-]{16,}['"]'''
    )
    safe_context = re.compile(r'os\.environ|getenv|config\[|\.env|example|change-me')

    leaks = []
    for py in ROOT.rglob('*.py'):
        if any(part in py.parts for part in ('venv', '__pycache__', '.git', 'tests')):
            continue
        try:
            text = py.read_text(encoding='utf-8', errors='ignore')
        except Exception:
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            if suspicious.search(line) and not safe_context.search(line):
                leaks.append(f'{py.relative_to(ROOT)}:{lineno}: {line.strip()[:80]}')

    assert not leaks, f'Olası hardcoded secret\'lar:\n  ' + '\n  '.join(leaks)


# ── Bağımlılık & lisans ─────────────────────────────────────────────────────

@pytest.mark.security
def test_requirements_no_unpinned_critical():
    """Kritik güvenlik paketleri pinli olmalı."""
    req = (ROOT / 'requirements.txt').read_text()
    critical = {'flask', 'sqlalchemy', 'authlib', 'itsdangerous', 'flasgger'}
    for line in req.splitlines():
        line = line.strip().lower()
        if not line or line.startswith('#'):
            continue
        name = re.split(r'[<>=!~]', line)[0]
        if name in critical and not re.search(r'[<>=]', line):
            pytest.fail(f'Kritik paket pinli değil: {line}')


# ── App-level auth korumaları ───────────────────────────────────────────────

@pytest.mark.security
def test_protected_routes_require_login():
    """Public route'lar dışındaki tüm GET endpoint'leri 302 (login redirect) dönmeli."""
    os.environ.setdefault('FLASK_SECRET_KEY', 'test-secret-key-for-pytest-only')
    from app import create_app
    app = create_app()
    app.config['TESTING'] = True
    client = app.test_client()

    public = {'/login', '/register', '/logout',
              '/verify_email', '/forgot_password', '/reset_password',
              '/google/login', '/google/callback', '/health',
              '/static', '/apidocs', '/apispec',
              '/oauth2-redirect.html',  # Flasgger Swagger UI
              '/flasgger_static'}

    failures = []
    for rule in app.url_map.iter_rules():
        if 'GET' not in rule.methods:
            continue
        path = str(rule)
        if any(path.startswith(p) for p in public) or '<' in path:
            continue
        try:
            resp = client.get(path, follow_redirects=False)
        except Exception:
            continue
        # 302 (login redirect) veya 401 kabul; 200 = açıkta
        if resp.status_code == 200:
            failures.append(f'{path} -> 200 (login_required eksik?)')

    assert not failures, 'Korumasız route\'lar:\n  ' + '\n  '.join(failures)


@pytest.mark.security
def test_secret_key_required():
    """`FLASK_SECRET_KEY` env yoksa app başlamamalı (veya warning vermeli)."""
    from app import create_app
    app = create_app()
    assert app.secret_key, 'app.secret_key set değil — session güvensiz olur'
    assert app.secret_key != 'dev', 'Default dev secret kullanılıyor'
    assert len(app.secret_key) >= 16, 'SECRET_KEY çok kısa'


# ── License kontrolü ────────────────────────────────────────────────────────

@pytest.mark.security
def test_license_file_present():
    """LICENSE dosyası AGPL-3.0 olmalı."""
    license_file = ROOT / 'LICENSE'
    assert license_file.exists(), 'LICENSE dosyası yok'
    text = license_file.read_text()
    assert 'AFFERO GENERAL PUBLIC LICENSE' in text.upper(), 'AGPL değil'
    assert 'Version 3' in text, 'Versiyon 3 değil'
