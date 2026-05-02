# Radar

> Açık kaynak cari risk skorlama ve kredi karar destek platformu.
> Türk KOBİ ve kurumsal segment için Findeks benzeri firma-içi (private) derecelendirme.

[![License: AGPL v3](https://img.shields.io/badge/License-AGPL_v3-blue.svg)](https://www.gnu.org/licenses/agpl-3.0)
![Python](https://img.shields.io/badge/python-3.11-blue)
![Flask](https://img.shields.io/badge/flask-3.0-green)

---

## Ne Yapar?

- Müşteri (cari) hesaplarınızın **kredi notunu** hesaplar (Z-Score, F-Score, DSCR, ICR + ödeme disiplini)
- **Monte Carlo** simülasyonu + isimli stres testleri (faiz şoku, sektör çöküşü, likidite donması) ile senaryo dağılımı çıkarır
- 4 dilde (TR/EN/ES/DE) detaylı yönetici raporu üretir
- Excel ile toplu yaşlandırma (aging) verisi içe aktarır
- Multi-tenant + RBAC + audit log + webhook desteği

## Hızlı Başlangıç

### Docker (önerilen)

```bash
git clone https://github.com/Dai-Solutions/Radar.git
cd Radar
cp .env.example .env       # SECRET_KEY, SMTP, OAuth doldur
docker compose up -d --build
# → http://localhost:8005
```

### Lokal Python

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python app.py              # SQLite ile (PG_URL boşsa)
```

### Demo Verisi

```bash
python seed_sample_data.py
```

## Mimari

```
nginx → gunicorn (4 worker) → Flask 3 → PostgreSQL
                                      ↘ Authlib (Google OAuth)
                                      ↘ flask-mail (verify)
                                      ↘ flask-babel (TR/EN/ES/DE)
```

Detaylı mimari, modül haritası ve yol haritası için: [DOKUMANTASYON.md](DOKUMANTASYON.md)

## Test

```bash
pytest tests/ -v
```

## Güvenlik

Açık bildirimleri için: [SECURITY.md](SECURITY.md)

## Katkı

PR'lar memnuniyetle karşılanır. Lütfen:

1. Issue açarak değişikliği önce tartışın
2. `main` branch'inden topic branch açın
3. Commit mesajı: `<type>(<scope>): <özet>` (`feat`, `fix`, `chore`, `refactor`)
4. PR'da test ve i18n parity'sini kontrol edin

## Lisans

[AGPL-3.0](LICENSE) © 2025 DynamicAI

> AGPL nedeniyle: Radar'ı **kendiniz host ederek hizmet sunarsanız**, modifiye ettiğiniz kaynak kodu kullanıcılara sağlamak zorundasınız. İç kullanım için bu zorunluluk yoktur.

## Sponsor

Bu proje açık kaynaktır ve sponsorlar tarafından desteklenir:
- [OpenCollective](https://opencollective.com/dynamicai)
- [Patreon](https://www.patreon.com/c/DynamicAI)
