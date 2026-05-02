# Güvenlik Politikası — Radar

## Desteklenen Sürümler

| Sürüm | Destek |
|---|---|
| `main` (HEAD) | ✅ Aktif |
| Diğer branch'ler | ❌ |

## Güvenlik Açığı Bildirimi

Bir güvenlik açığı bulduysanız **lütfen public issue açmayın.**

Bunun yerine:
- **E-posta:** osmanedembele6361@gmail.com
- **Konu:** `[SECURITY] Radar - <kısa özet>`
- **İçerik:** Etki, yeniden üretim adımları, etkilenen sürüm/commit, varsa PoC

**Yanıt SLA:** 72 saat içinde ilk yanıt, 14 gün içinde fix veya azaltıcı önlem planı.

Açık doğrulanırsa sorumlu açıklama (responsible disclosure) sürecine geçilir; düzeltme yayınlandıktan sonra (varsayılan 30 gün) public açıklama yapılır ve katkı için credit verilir.

---

## Yapılan Güvenlik Önlemleri

### Kimlik Doğrulama & Oturum
- ✅ Şifreler **werkzeug.security** ile hash'lenir (PBKDF2-SHA256, salted)
- ✅ Mail doğrulama zorunlu — `URLSafeTimedSerializer` ile imzalı, süreli token
- ✅ Google OAuth — Authlib state parametresi otomatik doğrulanır (CSRF koruması)
- ✅ `flask-login` session cookie — `httponly`, prod'da `secure=True`
- ✅ Logout sonrası token invalidation

### Veri Erişimi & Çok Kiracılılık
- ✅ Multi-tenant izolasyon — her sorgu `tenant_id` filtresi içerir
- ✅ `is_sample=True` müşteriler sadece okunur, tenant izolasyonunu bypass etmez
- ✅ Rol-tabanlı yetkilendirme (RBAC) — `User`/`Role`/`UserRole` pivot
- ✅ Audit log — kimlik doğrulama, kritik admin aksiyonları kayıt altında

### Veritabanı
- ✅ SQLAlchemy ORM — parametrize sorgular (SQL injection koruması)
- ✅ Postgres advisory lock (`pg_advisory_lock(7382001)`) — concurrent worker init race koruması
- ✅ Lightweight migration `IF NOT EXISTS` paterniyle idempotent

### Sırlar & Konfigürasyon
- ✅ Tüm sırlar `.env` dosyasında, `.gitignore`'da
- ✅ Kod tabanında hardcoded secret yok (taranmıştır)
- ✅ `SECRET_KEY` env'den okunur, fallback yok

### Transport & Headers
- ✅ Prod'da TLS (nginx + Let's Encrypt)
- ✅ Cookie flag'leri (`HttpOnly`, `SameSite`)
- ✅ `network_mode: host` ile sadece nginx'in proxy'lediği path açık

### Bağımlılık Hijyeni
- ✅ `requirements.txt` pinned versions (kritik paketler)
- ✅ Tüm bağımlılıklar permissive lisanslı (MIT/BSD/Apache)
- ✅ `psycopg2-binary` (LGPL) ve `certifi` (MPL-2.0) — dynamic linking, sorun yok

---

## Bilinen Sınırlamalar / Yapılacaklar

| Konu | Durum | Plan |
|---|---|---|
| CSRF token (form'larda) | ⚠️ Manuel yok | `flask-wtf` entegrasyonu — kısa vade |
| Rate limiting (login bruteforce) | ⚠️ Yok | `flask-limiter` per-IP per-endpoint — kısa vade |
| 2FA (TOTP) | ⚠️ Yok | `pyotp` ile — özellikle admin rolleri için, orta vade |
| Audit log fiziksel silme | ⚠️ Hard delete | Soft delete + retention policy — orta vade |
| Webhook signature | ⚠️ Yok | HMAC-SHA256 outbound imza — orta vade |
| DB backup automation | ⚠️ Manuel | Cron + S3 push — kısa vade |
| Dependency vulnerability scan | ⚠️ CI'da yok | `pip-audit` GitHub Action — kısa vade |
| Log korelasyon ID'si | ⚠️ Yok | `request_id` middleware — kısa vade |
| SBOM (Software Bill of Materials) | ⚠️ Yok | CycloneDX export — orta vade |

---

## Güvenlik Testleri

`tests/security_smoke.py` aşağıdakileri kontrol eder:

- Tüm `routes/*.py` blueprint'lerinin login_required ile korunduğu (login/register/healthcheck hariç)
- `.env` ve hassas dosyaların git'te olmadığı
- Hardcoded SECRET_KEY/API_KEY/PASSWORD pattern'lerinin kod tabanında olmadığı
- SQLAlchemy raw SQL kullanımı yoksa string interpolation içermediği
- Cookie flag'lerinin prod konfigürasyonunda set olduğu

Çalıştırmak için:

```bash
pytest tests/ -v
```

---

## Şifreleme & Kriptografi

- **Parolalar:** PBKDF2-SHA256 (werkzeug default, ≥600k iter)
- **Token'lar:** HMAC-SHA256 (itsdangerous URLSafeTimedSerializer)
- **OAuth:** Authlib — JWS doğrulama RS256
- **TLS:** nginx — TLSv1.2 + TLSv1.3, modern cipher suite

---

## Veri Saklama & KVKK/GDPR

- Kullanıcı silme: hesap silinince ilgili `Customer`, `CreditScore`, `AgingRecord` kayıtları cascade silinir
- Audit log: silme talebi sonrası 30 gün retention (yasal gereksinim — finansal kayıtlar)
- Veri taşınabilirliği: Excel export her müşteri detayında mevcut
- Üçüncü taraf veri paylaşımı: **YOK** — hiçbir veri dışarı gönderilmez (Webhook hariç, ki tenant kontrolündedir)
