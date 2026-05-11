# Radar — Proje Görev & Context Dosyası

Son güncelleme: 2026-05-11

---

## Proje Özeti

**Brocum Radar** — kurumsal kredi risk değerlendirme platformu.
Hedef: KKB entegrasyonu, IFRS 9 / Basel III motoru, kurumsal SSO ve ML overlay ile bankacılık düzeyine çıkarmak.

**Konum:** `/home/dai/VOID/Projelerim/Kurumsal/Radar/`
**Branch:** `main` — son commit 2026-05-03 (`15395da docs: 4 dilde teknik dokümantasyon`)
**Venv:** `venv/bin/python3` (Python 3.12 — sistem Python 3.13 ile SQLAlchemy 2.0.23 uyumsuz)
**DB:** PostgreSQL (prod) / SQLite (geliştirme) — migration pattern: `_PENDING_COLUMNS` dict → `ALTER TABLE IF NOT EXISTS`
**URL prefix:** `/solutions/radar` (prod) — `APP_PREFIX` env değişkeni
**Lisans:** AGPL-3.0 (open-source)

---

## ⚠️ Repo Durumu (2026-05-11)

`main` branch'i 2026-05-03'te 4 dilde dokümantasyon ile dondu. O tarihten beri yapılan **"Bankacılık Düzeyi Yükseltme" işi (Adım 1-11) commit edilmedi**:

- 16 modified file (app.py, credit_scoring.py, database.py, requirements.txt, routes/{admin,auth,customer,scoring}.py, 6 template, style.css, task.md)
- 23 untracked file (kkb_adapter, ifrs9_engine, sso_manager, ml_overlay, bddk_reporter, openbanking_adapter, celery_app, tasks, routes/{bddk,ml,openbanking,portfolio}, templates/2fa_*, vs.)
- Toplam: +2114 / -447 satır working tree'de

**Açık karar:** bu işi tek commit mi, faz faz mı, ayrı branch mi olarak commit edeceğiz? Karar verilmeden başka iş başlatmak çakışma riski taşır.

---

## Tech Stack

| Katman | Teknoloji |
|--------|-----------|
| Backend | Flask 3.0, SQLAlchemy 2.0, gunicorn×4 |
| DB | PostgreSQL 16 / SQLite (dev) |
| Frontend | Bootstrap 5.3, Jinja2, Chart.js |
| Auth | Flask-Login, Authlib (Google OAuth), Flask-WTF CSRF |
| Güvenlik | Flask-Limiter, Flask-Talisman, pyotp (2FA) |
| SSO | python3-saml 1.16.0 (SAML 2.0), ldap3 2.9.1 (LDAP/AD) |
| ML | scikit-learn 1.8, xgboost 3.2 |
| Async | Celery 5.3 + Redis (CELERY_ALWAYS_EAGER sync fallback) |
| Raporlama | xml.etree (XBRL-XML, BDDK taksonomisi) |

---

## Tamamlanan Tüm Adımlar

### Önceki Fazlar (Phase 1–7) — `main`'de commit'li
- [x] Radar 1.0: temel scoring motoru, Monte Carlo, matematiksel iyileştirme, volatilite/DSCR/Z-Score
- [x] Faz 1-4: HTML injection fix, scoped session, dead code temizlik, Piotroski + ICR + Aging + sektör enum + 3 senaryo
- [x] Production hardening: Docker Compose V2, PostgreSQL pooling, structured logging, Excel validation
- [x] Nginx `/solutions/radar` prefix, Google OAuth, errors.html ayrıştırma, deploy.sh

### Faz 8-11 — `main`'de commit'li (ce96012 ve sonrası)
- [x] **i18n** — TR / EN / ES / DE 4 dilde tam çeviri (rapor değerlendirme metinleri dahil)
- [x] **Multi-tenant + RBAC** — kullanıcı rolleri, tenant izolasyonu
- [x] **Audit log** — soft-delete + filtreleme + CSV export (`routes/admin.py`)
- [x] **Swagger / API docs** — `api_docs.py`
- [x] **Webhooks** — retry policy ile
- [x] **Analytics** — `analytics.py`, finance KPI panel
- [x] **Güvenlik sertleştirme** (68abc8f): CSRF, rate limit (Redis backend), security headers, request_id, audit soft-delete, DB backup
- [x] **5 yeni değerlendirme notu + 3 isimli stres testi** (31a8eac)
- [x] **OSS hazırlık**: AGPL-3.0 lisans, güvenlik testleri (b0cb479)
- [x] **4 dilde teknik dokümantasyon** — md + pdf (15395da)
- [x] **Postgres advisory lock**: `init_db()` gunicorn worker'lar arasında serialize
- [x] **Prod hardening**: Redis backend rate limiter + 5xx admin alert + .env.example (0e7fe7a)

### Bankacılık Düzeyi Yükseltme (Adım 1–11) — ⚠️ COMMIT EDİLMEDİ, working tree'de duruyor

- [x] **Adım 1:** KKBReport DB modeli + KKBAdapter (mock / manual / live)
  - `kkb_adapter.py` — SOAP sorgu, cache (30 gün TTL), mock fixture
  - `database.py` — `KKBReport` tablosu

- [x] **Adım 2:** CreditScorer KKB entegrasyonu
  - Hard veto: karşılıksız çek, aktif icra, NPL → skor hesaplanmaz
  - `enrich_scores()` — %30 KKB ağırlığı ile historical + debt skor zenginleştirme

- [x] **Adım 3:** KVKK rıza akışı
  - Rıza formu, `consent_given` + `consent_timestamp` DB kayıtları
  - Rıza olmadan KKB sorgusu engellenir

- [x] **Adım 4:** Audit log UI
  - Filtreleme (kullanıcı, eylem, tarih aralığı), CSV export
  - `routes/admin.py` — `/admin/audit-log`

- [x] **Adım 5:** IFRS 9 / Basel III motoru
  - `ifrs9_engine.py` — scipy bağımlılığı yok (Peter Acklam PPF)
  - Aşama 1/2/3 ECL, Basel III IRB Foundation RWA + Pillar 1 sermaye gereksinimi

- [x] **Adım 6:** Kurumsal SSO — SAML 2.0 + LDAP/AD
  - `sso_manager.py` — SAMLProvider (python3-saml) + LDAPProvider (ldap3)
  - `routes/auth.py` — `/sso/saml/*`, `/sso/ldap/login`
  - `templates/sso_config.html` — admin yapılandırma paneli

- [x] **Adım 7:** 2FA / TOTP
  - `pyotp` + `qrcode[pil]`
  - `/2fa/setup` → QR kod + manuel anahtar göster
  - `/2fa/setup/confirm` → kodu doğrula + etkinleştir
  - `/2fa/verify` → login adım 2 (şifre doğrulama sonrası)
  - `/2fa/disable` → şifre ile devre dışı bırak
  - `database.py` — `User.totp_secret`, `User.totp_enabled` + migration

- [x] **Adım 8:** Toplu portföy analizi + Celery
  - `celery_app.py` — Celery factory (Redis broker, sync fallback)
  - `tasks.py` — `portfolio_scan` görevi: tüm müşterileri CreditScorer ile tarar
  - `database.py` — `BatchJob` tablosu (status, total, processed, summary_json)
  - `routes/portfolio.py` — `/portfoy/` liste, `/tara` başlat, `/durum/<id>` polling, `/sonuc/<id>` sonuç
  - `templates/portfolio.html` + `portfolio_result.html`
  - Sonuç: not dağılımı (doughnut) + IFRS 9 aşama dağılımı + müşteri tablosu

- [x] **Adım 9:** ML Overlay — Logistic Regression / XGBoost
  - `ml_overlay.py` — `train()`, `predict_pd()`, `blend_pd()`, `get_info()`
  - n < 200 → LogisticRegression; n ≥ 200 → XGBoostClassifier
  - Hedef: `ifrs9_stage >= 3` (temerrüt = 1)
  - Harmanlama: `ifrs9_pd = 0.65 × kural_pd + 0.35 × ml_pd`
  - Model pickle: `data/ml_model.pkl`
  - `routes/ml.py` — `/ml/panel`, `/ml/train`, `/ml/info` (admin-only)
  - `CreditScoreResult` — `ml_pd`, `ml_adjusted` alanları eklendi

- [x] **Adım 10:** BDDK Düzenleyici Raporlama — XML / XBRL
  - `bddk_reporter.py` — 3 rapor üretici:
    - `portfoy_kredi_riski()` → BDDK KR-1 (müşteri bazlı ECL/PD/LGD/RWA)
    - `ifrs9_karsılik()` → BDDK KR-3 (aşama bazlı ECL toplamları)
    - `sermaye_yeterliligi()` → BDDK SY-1 (Basel III RWA, CAR tahmini, not dağılımı)
  - XBRL-benzeri XML: `xmlns:bddk`, `xbrli:context`, `xbrli:unit`, fact elemanları
  - `routes/bddk.py` — `/bddk/` panel + `/bddk/indir` XML download (admin-only)
  - `templates/bddk.html` — rapor türü / dönem / kurum seçimi

- [x] **Adım 11:** Open Banking Entegrasyonu — BKM / Berlin Group NextGenPSD2
  - `openbanking_adapter.py` — 3 mod: mock (IBAN hash deterministik) / sandbox / live
  - `_parse_transactions()` — Berlin Group yanıtından cashflow metrikleri
  - `enrich_scores()` — `historical_score` (cashflow_regularity ×%25) + `future_score` (avg_balance ×%25)
  - `database.py` — `OpenBankingRecord` tablosu (bakiye, cashflow, overdraft, KVKK, 7 gün TTL)
  - `routes/openbanking.py` — panel, IBAN test (JSON), müşteri sorgula/kaydet, kayıtlar listesi
  - `CreditScoreResult` — `ob_enriched` alanı eklendi

---

## Kritik Dosyalar

| Dosya | İçerik |
|-------|--------|
| `database.py` | Tüm modeller + `_PENDING_COLUMNS` migration + `init_db()` |
| `credit_scoring.py` | `CreditScorer` (KKB + OB + ML entegrasyonlu), `CreditScoreResult` |
| `ifrs9_engine.py` | IFRS 9 ECL + Basel III IRB Foundation |
| `kkb_adapter.py` | KKBAdapter mock/manual/live |
| `openbanking_adapter.py` | OpenBankingAdapter mock/sandbox/live |
| `ml_overlay.py` | LR/XGBoost PD; train, blend_pd, get_info |
| `bddk_reporter.py` | XBRL-XML 3 rapor türü |
| `celery_app.py` | Celery factory |
| `tasks.py` | `portfolio_scan` Celery görevi |
| `sso_manager.py` | SAMLProvider + LDAPProvider |
| `routes/auth.py` | Login + Google OAuth + SSO + 2FA |
| `routes/admin.py` | Admin panel + audit log + SSO config |
| `routes/scoring.py` | credit_request() + rapor_view() |
| `routes/portfolio.py` | Portföy tarama + polling + sonuç |
| `routes/ml.py` | ML panel + train (admin) |
| `routes/bddk.py` | BDDK rapor indirme (admin) |
| `routes/openbanking.py` | Open Banking yönetim paneli (admin) |
| `aging_analyzer.py` | AgingAnalyzer, AgingRecord |
| `analytics.py` | Finance KPI / analytics paneli (committed) |
| `api_docs.py` | Swagger / OpenAPI tanımları (committed) |
| `webhooks.py` | Webhook dispatch + retry (committed) |
| `security_extensions.py` | CSRF, rate limit, headers, request_id, DB backup (committed) |
| `enterprise.py` | Multi-tenant + RBAC katmanı (committed) |
| `i18n_utils.py` + `translations.py` | TR/EN/ES/DE i18n altyapısı (committed) |

---

## Önemli Notlar

- **Migration pattern:** `_PENDING_COLUMNS` → `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` — Alembic yok, her startup'ta güvenli çalışır
- **Venv shebang bozuk** (proje taşındı): `venv/bin/pip` çalışmaz → `venv/bin/python3 -m pip` kullan
- **Celery sync fallback:** `CELERY_ALWAYS_EAGER=true` veya Redis yoksa görev senkron çalışır
- **ML model yok iken:** `predict_pd()` → `-1.0` döner, `blend_pd()` kural tabanlı PD'yi değiştirmez
- **OB mock modu:** IBAN hash'inden deterministik veri — aynı IBAN her zaman aynı sonucu verir
- **Navbar admin linkleri:** Portföy · ML · BDDK · OB (tümü `{% if is_admin %}` bloğunda)

---

## Env Değişkenleri (tam liste)

```
# Core
FLASK_SECRET_KEY=...
DATABASE_URL=postgresql+psycopg2://...
APP_PREFIX=/solutions/radar
DOMAIN_NAME=daisoftwares.com
APP_VERSION=Radar 2.0
ADMIN_EMAIL=...

# OAuth
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
CONF_URL=https://accounts.google.com/.well-known/openid-configuration

# Mail
MAIL_SERVER=smtp.gmail.com
MAIL_PORT=587
MAIL_USERNAME=...
MAIL_PASSWORD=...

# KKB
KKB_MODE=mock          # mock | manual | live
KKB_ENDPOINT=...       # live modda
KKB_MEMBER_CODE=...
KKB_CERT=...
KKB_KEY=...
KKB_CACHE_DAYS=30

# Open Banking
OB_MODE=mock           # mock | sandbox | live
OB_BASE_URL=...        # live/sandbox modda
OB_CLIENT_ID=...
OB_CLIENT_SECRET=...
OB_CACHE_DAYS=7

# Celery
REDIS_URL=redis://localhost:6379/0
CELERY_ALWAYS_EAGER=false  # true = sync mod (Redis yoksa)
```
