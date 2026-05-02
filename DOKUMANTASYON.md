# Radar — A'dan Z'ye Teknik Dokümantasyon

> Cari risk skorlama ve kredi karar destek platformu.
> Son güncelleme: 2026-05-03

---

## 1. Proje Özeti

**Radar**, KOBİ ve kurumsal firmalara yönelik bir **kredi skorlama / cari risk değerlendirme** uygulamasıdır. Findeks benzeri bir derecelendirme servisinin firma-içi (private) muadili olarak konumlanır.

**Temel iş akışı:**
1. Kullanıcı müşteri (cari) açar
2. Yaşlandırma (aging) ve kredi talebi verisi girer veya Excel'den toplu içe aktarır
3. Sistem; ödeme disiplini, finansal rasyolar (Z-Score, F-Score, DSCR, ICR), sektör risk faktörleri ve makro koşullar üzerinden bir **kredi notu** üretir
4. Monte Carlo simülasyonu + isimli stres testleri ile senaryo dağılımı hesaplanır
5. Çok dilli (TR/EN/ES/DE) detaylı PDF/HTML rapor sunulur

---

## 2. Teknoloji Yığını

| Katman | Teknoloji |
|---|---|
| Backend | Python 3.11, **Flask 3.0** (Blueprints) |
| ORM | **SQLAlchemy 2.0** (scoped_session) |
| DB | PostgreSQL (prod) / SQLite (dev) — dual target |
| Auth | flask-login + **Authlib** (Google OAuth) + itsdangerous (mail verify) |
| Mail | flask-mail (SMTP) |
| i18n | **flask-babel 4.x** (locale_selector pattern) |
| Templating | Jinja2 + Bootstrap 5.3 + Bootstrap Icons |
| API Docs | **Flasgger** (OpenAPI/Swagger) |
| Async | Celery + Redis (planlı, henüz aktif değil) |
| Container | Docker + docker-compose, `network_mode: host` |
| WSGI | gunicorn 4 worker |
| Reverse Proxy | nginx — `technodai.com/radar/` → `127.0.0.1:5001` |
| Excel | pandas + openpyxl |

---

## 3. Mimari (Yüksek Seviye)

```
┌────────────────────────────────────────────────────────┐
│  Browser (TR/EN/ES/DE)                                 │
└──────────────────────┬─────────────────────────────────┘
                       │ https://technodai.com/radar
                       ▼
                 ┌──────────┐
                 │  nginx   │  TLS, prefix routing
                 └────┬─────┘
                      │ proxy_pass :5001
                      ▼
              ┌──────────────────┐
              │  gunicorn × 4    │  Docker (host net)
              │   ↓              │
              │  Flask app       │
              │   ├ blueprints/  │  auth, main, customer,
              │   │              │  scoring, admin, api
              │   ├ enterprise/  │  i18n, RBAC, audit, webhooks
              │   └ analytics/   │
              └────────┬─────────┘
                       │
            ┌──────────┼──────────┐
            ▼          ▼          ▼
       PostgreSQL   SMTP      Google OAuth
       (advisory   (verify     (login)
        locks)     mails)
```

---

## 4. Modül Haritası

### 4.1 Çekirdek

| Dosya | Sorumluluk |
|---|---|
| `app.py` | Flask factory (`create_app`), blueprint kayıt, `init_db()`, enterprise feature init |
| `database.py` | SQLAlchemy modeller, dual-DB engine, lightweight ALTER migration, **Postgres advisory lock** (concurrent worker safety) |
| `extensions.py` | `login_manager`, `mail`, `ts` (URLSafeTimedSerializer) — modül seviyesinde paylaşılan singleton'lar |
| `credit_scoring.py` | `CreditScorer` sınıfı — skor hesaplama, expert assessment notları, Monte Carlo + isimli stres testleri |
| `aging_analyzer.py` | Yaşlandırma kayıtlarından gecikme metriği üretme |
| `excel_import.py` | Toplu müşteri/kayıt import (pandas) |
| `currency.py` | TL formatlama, FX dönüşüm yardımcıları |
| `logger.py` | Yapılandırılmış logging |
| `translations.py` | 4 dil sözlüğü (TR/EN/ES/DE) — düz dict, ~70 kB |

### 4.2 Routes (Blueprints)

| Blueprint | Path | Sorumluluk |
|---|---|---|
| `auth` | `/login`, `/register`, `/logout`, `/google-login`, `/verify/<token>` | Kullanıcı kimlik doğrulama |
| `main` | `/`, `/nedir`, `/guvenlik`, `/set_language/<lang>` | Anasayfa, statik içerik, dil değişimi |
| `customer` | `/musteri/...` | CRUD + detay |
| `scoring` | `/skor/...`, `/rapor/<id>` | Skor hesaplama, rapor render |
| `admin` | `/admin/...` | Ayarlar, kullanıcı yönetimi, audit log |
| `api` | `/api/v1/...` | REST endpoint'ler (Flasgger ile dokümante) |

### 4.3 Enterprise Katmanı (Phase 8-11)

| Dosya | Sorumluluk |
|---|---|
| `enterprise.py` | `init_enterprise_features(app)` — RBAC, audit, multi-tenant init |
| `i18n_utils.py` | flask-babel 4.x locale selector |
| `analytics.py` | Tenant-level metrik toplama |
| `api_docs.py` | Flasgger Swagger UI yapılandırması |
| `webhooks.py` | Outbound webhook gönderimi (Slack, Discord, custom) |

---

## 5. Veri Modeli

```
Tenant 1───* User 1───* Customer 1───* AgingRecord
                              │
                              ├───* CreditRequest
                              └───* CreditScore (history)

User *───* Role  (UserRole pivot)
Tenant 1───* AuditLog
```

**Önemli:**
- `tenant_id` her tablo için `nullable=True default=1` — eski kayıtlar default tenant'a atanır
- `is_sample=True` müşteriler tüm kullanıcılara görünür (demo data)
- `CreditScore` versiyonludur — her hesaplama yeni bir kayıt yaratır, geçmiş silinmez

---

## 6. Deployment Mimarisi

### Prod (technodai.com)

```
~/apps/radar/                 # git clone
├── docker-compose.yml        # local-only port binding (5001)
├── .env                      # SECRET_KEY, DB_URL, OAuth, SMTP
└── data/                     # SQLite fallback + uploads (volume)
```

- Container `radar_v1_app`, restart: always, host network
- Postgres `radar` DB, advisory lock (`pg_advisory_lock(7382001)`) ile 4 worker init race'i önlenir
- nginx vhost: `/radar/` prefix `proxy_pass http://127.0.0.1:5001/`

### Lokal (dev)

- Aynı compose file (Desktop symlink), port `8005`
- SQLite fallback ile DB-siz çalışabilir

### Dağıtım Akışı

```
lokal düzenleme
   ↓ git commit + push
   ↓ ssh prod
cd ~/apps/radar && git pull
sudo docker compose up -d --build
   ↓ smoke test
curl -I https://technodai.com/radar/
```

---

## 7. Geliştirme Workflow'u

1. **Branch**: `main` üzerinde küçük commit'ler. Büyük feature'lar için topic branch.
2. **Migration**: `database.py:_run_lightweight_migrations()` içinde `ALTER TABLE IF NOT EXISTS` paterni — Alembic yok (kasıtlı, küçük şema için aşırı).
3. **Seed**: `seed_sample_data.py` — yeni kurulumda demo müşteri seti.
4. **Test**: `tests/integrity_check.py` (manuel) — birim test henüz yok.
5. **i18n**: Yeni metin ekleyince `translations.py` 4 blokta da güncellenmeli. CI henüz key parity check'i yapmıyor (eklenebilir).
6. **Commit mesajı**: `<type>(<scope>): <özet>` — `feat`, `fix`, `chore`, `refactor`.

---

## 8. Kullanım Akışı (Son Kullanıcı)

| Adım | Sayfa | Aksiyon |
|---|---|---|
| 1 | `/register` | E-posta/şifre veya Google ile kayıt → mail doğrulama |
| 2 | `/` | Müşteri listesi — yeni müşteri ekle |
| 3 | `/musteri/yeni` | Cari bilgileri (sektör, özkaynak, ciro vb.) |
| 4 | `/musteri/<id>` | Yaşlandırma satırı + kredi talebi gir |
| 5 | `/musteri/<id>/import` | Excel ile toplu içe aktar |
| 6 | `/skor/<id>` | Skor hesapla — admin ayarları (faiz, enflasyon) uygulanır |
| 7 | `/rapor/<id>` | Detaylı rapor — yönetici değerlendirmesi, senaryolar, isimli stres testleri |
| 8 | `/admin` | Ayarlar, kullanıcı yönetimi, audit log |

---

## 9. Yol Haritası — Eklenecekler

### 9.1 Kısa Vade (1-2 hafta)

- [ ] **Vade modülü genişletme**: Şu an statik kademeli vade (`vade_15..90`); ödeme disiplini bandına göre dinamik hesaplama (DSO + sektör mediyanı)
- [ ] **Translations CI guard**: 4 dil arası key parity test (eksik anahtar = build fail)
- [ ] **PDF export**: Rapor `?format=pdf` için WeasyPrint entegrasyonu
- [ ] **Birim test iskeleti**: `pytest` + `pytest-flask`, en az `credit_scoring` için %70 coverage
- [ ] **Audit log UI**: Mevcut tablo görüntülenmiyor — admin panele filtrelenebilir liste

### 9.2 Orta Vade (1-2 ay)

- [ ] **Celery aktivasyon**: Excel import + skor batch'i async kuyruğa al (büyük dosyalarda timeout problemi var)
- [ ] **Webhook event genişletme**: `score.calculated`, `customer.high_risk`, `request.spike` event'leri
- [ ] **Rate limiting (per-tenant API)**: Login/register için Redis-backed kota aktif; `/api/v1/*` için per-tenant kota açık iş
- [ ] **Sektör verisi enjeksiyonu**: Halka açık sektör rasyo benchmark'ı (KGK / TÜİK / Findeks rapor) — şu an sadece peer median
- [ ] **Notification channels**: E-posta + Slack + Discord — yüksek risk alarmları
- [ ] **Multi-currency**: Şu an her şey TL — USD/EUR cari için FX snapshot tablosu

### 9.3 Uzun Vade (3+ ay)

- [ ] **ML katmanı**: Mevcut kural-tabanlı skor + opsiyonel logistic regression / gradient boosting overlay (kayıt sayısı yeterli olduğunda)
- [ ] **Open Banking**: Hesap hareketi pull → otomatik aging
- [ ] **Mobile app**: PWA veya React Native — okuma odaklı (skor görüntüleme, alarm)
- [ ] **Marketplace tenant onboarding**: Self-serve SaaS (şu an manuel tenant açma)
- [ ] **GDPR/KVKK paneli**: Veri ihracı, silme talebi, retention policy
- [ ] **2FA**: TOTP (pyotp) — özellikle admin rolleri için
- [ ] **Audit log export**: SIEM (Splunk, ELK) için JSON akışı

---

## 10. Sürekli İyileştirme — Tamamlanan Sertleştirmeler

| Konu | Yapılan İyileştirme | Durum |
|---|---|---|
| docker-compose `version` field obsolete | Field kaldırıldı | ✅ |
| Webhook retry yok | `_post_with_retry` — 3 deneme + exponential backoff (1s/2s/4s); 5xx ve network hataları retry, 4xx tek deneme | ✅ |
| Log korelasyon ID'si yok | `request_id` middleware — her request'e UUID16, `X-Request-ID` response header + `g.request_id` log binding | ✅ |
| Audit log fiziksel silme | `AuditLog.deleted_at` kolonu — soft delete pattern (compliance retention) | ✅ |
| DB backup automation yok | `scripts/backup.sh` — Postgres/SQLite otomatik tespit, gzip, retention rotation; **prod cron 03:00** | ✅ |
| Flask 3.0.0 CVE-2026-27205 | `flask>=3.1.3` pin'i + CI'da pip/wheel/setuptools upgrade | ✅ |
| Rate limiter `memory://` workers arası bölünüyordu | `LIMITER_STORAGE_URI=redis://localhost:6379/1` — paylaşımlı sayaç, 11. wrong-pass'tan 429 döndüğü prod'da doğrulandı | ✅ |
| Yönetici Değerlendirmesi rapor sonradan açıldığında dile uyumsuz (donmuş TR metni) | `assessment_i18n` / `decision_summary_i18n` — 4 dil JSON dict olarak DB'ye yazılır, view aktif dile düşer; eski kayıtlar geri uyumlu | ✅ |
| Excel import'ta yeni `Customer` kayıtlarına `user_id` atanmıyordu | `current_user.id` ataması — sahipsiz kayıt sorunu giderildi | ✅ |
| Menüde `Excel Yükleme` non-admin kullanıcıya görünüyordu (tıklayınca redirect) | `context_processor` `is_admin` bayrağı + `{% if is_admin %}` gating; redundant `Panel` linki kaldırıldı | ✅ |
| 5xx hatasında bildirim yok | `errorhandler(500)` — `ADMIN_EMAIL`'e `request_id` + path + user + exception özetli mail | ✅ |

### Açık (yol haritasında)

| Konu | Etki | Plan |
|---|---|---|
| Alembic yok | Lightweight ALTER yeterli; karmaşıklaşırsa geç | Şema 30+ tabloyu geçtiğinde |
| Test coverage düşük | Refactor riskli | Pytest skeleton var, kritik path coverage hedefi %50 |
| `translations.py` tek dosya 70 kB | Merge conflict mıknatısı | Dil başına ayrı dosya + lazy load |
| Authlib deprecation (`authlib.jose`) | 2.0'da kırılacak | `joserfc`'e geç |
| Sunucudaki override docker-compose | Her pull'da stash | `docker-compose.override.yml` ayrıştır |

---

## 11. Güvenlik Notları — Aktif Önlemler

### Kimlik & Oturum
- ✅ Parolalar werkzeug PBKDF2-SHA256 (salted)
- ✅ Mail verify zorunlu (URLSafeTimedSerializer, süreli)
- ✅ Google OAuth — Authlib state validation (CSRF koruması)
- ✅ Cookie flag'leri: `HttpOnly`, `SameSite=Lax`, prod'da `Secure`

### Web Katmanı (flask-wtf, flask-limiter, flask-talisman)
- ✅ **CSRF koruması**: Tüm POST formlarda `csrf_token`; API blueprint muaf (token-based)
- ✅ **Rate limiting**: `/login` 10/dk + 50/saat, `/register` 5/dk + 20/saat; default 100/dk + 1000/saat. **Prod backend Redis** (`LIMITER_STORAGE_URI=redis://localhost:6379/1`) — workers arası paylaşımlı sayaç.
- ✅ **Security headers** (Talisman): HSTS (1 yıl), `X-Frame-Options: SAMEORIGIN`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: strict-origin-when-cross-origin`
- ✅ **Request ID**: Her request `X-Request-ID` header'ı taşır → log korelasyonu
- ✅ **Menü admin gating**: `is_admin` context bayrağı, `@admin_required` gerektiren linkler non-admin kullanıcıdan gizleniyor

### Veri Erişimi
- ✅ Multi-tenant izolasyon — her sorgu `tenant_id` filtresi
- ✅ SQLAlchemy ORM — parametrize sorgular (SQL injection koruması)
- ✅ `is_sample` flag tenant izolasyonunu bypass etmiyor
- ✅ Postgres advisory lock — concurrent init race koruması
- ✅ Audit log soft-delete — fiziksel silme yok, compliance retention

### Operasyonel
- ✅ Sırlar `.env`'de, repoda yok (`.gitignore` + 8 güvenlik testi)
- ✅ DB backup script + retention rotation (`scripts/backup.sh`) — **prod cron her gece 03:00**
- ✅ Bağımlılıklar pinli, CI'da `pip-audit --strict` (Flask CVE bump dahil)
- ✅ Upload tavanı 10 MB (DoS yüzeyi azaltma)
- ✅ **5xx admin alert**: `errorhandler(500)` `ADMIN_EMAIL` adresine request_id + exception bildirir

### Yol Haritası (Açık)
- ⚠️ 2FA (TOTP) — özellikle admin rolleri için
- ⚠️ Webhook outbound HMAC imzası varsayılan zorunlu
- ⚠️ CSP (Content Security Policy) — şu an inline style/script var, refactor gerek
- ⚠️ Authlib `joserfc` geçişi (2.0 deprecation)

---

## 12. Operasyonel Komutlar

```bash
# Lokal dev
python app.py                                    # SQLite ile

# Docker (lokal port 8005)
docker compose up -d --build
docker compose logs -f radar-app

# Prod deploy (lokal makineden)
sshpass -p "$SERVER_PASS" ssh "$SERVER_USER@$SERVER_IP" \
  "cd ~/apps/radar && git pull && \
   echo \$PASS | sudo -S docker compose up -d --build"

# Smoke test
curl -I https://technodai.com/radar/

# DB backup (prod'da)
sudo docker exec radar_v1_app pg_dump -U radar radar > backup_$(date +%F).sql

# Migration (lightweight, otomatik init_db'de çalışır)
python -c "from database import init_db; init_db()"

# Seed
python seed_sample_data.py

# Translation key parity (manuel)
python -c "from translations import translations; \
  ks = {l: set(translations[l]['expert_assessments'].keys()) for l in translations}; \
  print('diff:', ks['tr'] ^ ks['en'])"
```

---

## 13. Karar Kayıtları (ADR-mini)

1. **Alembic yerine lightweight ALTER**: Şema küçük, downtime kabul edilebilir. Karmaşıklık artarsa revize edilir.
2. **`network_mode: host`**: nginx ile aynı host'ta, port mapping karmaşıklığı yok. Multi-host'a geçerken değişir.
3. **flask-babel 4.x**: Flask 3.0 ile 3.x uyumsuz (`locked_cached_property` kaldırıldı).
4. **Tek tenant default ID=1**: Eski kayıtlar geriye dönük taşındı; multi-tenant'a geçiş kesintisiz.
5. **Postgres advisory lock anahtarı 7382001**: Sabit magic number — tüm worker'lar aynı kilidi alır, ilki tablo yaratır, diğerleri bekler.
6. **Sponsor pill footer'da**: Navbar'da yer kalmıyordu, görünürlük düşmesin diye footer'a alındı.

---

## 14. Lisans & Açık Kaynak

- **Proje lisansı:** [AGPL-3.0](LICENSE) — host edip hizmet sunan herkes kaynak kodu paylaşmak zorunda
- **Bağımlılıklar:** Tümü permissive (MIT/BSD/Apache); GPL/AGPL yok → AGPL ile uyumlu
- **Dikkat çeken bağımlılıklar:**
  - `psycopg2-binary` (LGPL) — dynamic linking, sorun yok
  - `certifi` (MPL-2.0) — dosya-bazlı copyleft, dokunmadığımız sürece OK
- **Lisans denetimi:** `pip-licenses` ile yapıldı, çıktı temiz

## 15. Test & Kalite

### Mevcut Testler
- `tests/security_smoke.py` — 8 güvenlik kontrolü:
  - `.env` ve sırlar git'te değil
  - Özel anahtar dosyaları yok
  - Hardcoded SECRET/PASSWORD/API_KEY yok
  - Kritik paketler pinli (flask, sqlalchemy, authlib, itsdangerous, flasgger)
  - Tüm protected route'lar `@login_required` ile sarılı
  - SECRET_KEY set ve uzun
  - LICENSE dosyası AGPL-3.0
- `tests/integrity_check.py` — manuel skor doğrulama (DB gerektirir)

### CI (GitHub Actions)
- `.github/workflows/ci.yml` — her push/PR'da:
  - pytest security suite
  - `pip-audit` ile bağımlılık güvenlik taraması
  - Translation key parity (TR/EN/ES/DE arası eşitlik)

### Çalıştırma
```bash
pytest tests/ -v                   # tüm testler
pytest -m security                 # sadece güvenlik smoke
pip-audit                          # CVE taraması
```

## 16. Referanslar

- Repo: `git@github.com:Dai-Solutions/Radar.git`
- Prod: https://technodai.com/radar/
- Sponsor: OpenCollective + Patreon (`https://www.patreon.com/c/DynamicAI`)
- Findeks (rakip): https://www.findeks.com/
