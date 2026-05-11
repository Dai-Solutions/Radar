"""
BDDK düzenleyici raporlama rotaları.

GET  /bddk/           → rapor seçim paneli
POST /bddk/indir      → XML raporu oluştur + indir
"""
from datetime import date
from flask import Blueprint, render_template, request, Response, flash, redirect, url_for
from flask_login import login_required

from routes.auth import admin_required
from database import get_session

bddk_bp = Blueprint('bddk', __name__, url_prefix='/bddk')

RAPOR_TURLERI = {
    'portfoy_kredi_riski': {
        'label': 'Portföy Kredi Riski Raporu',
        'aciklama': 'Müşteri bazlı ECL, PD, LGD, RWA özeti (BDDK KR-1)',
        'icon': 'bi-file-earmark-bar-chart',
    },
    'ifrs9_karsılik': {
        'label': 'IFRS 9 Karşılık Tablosu',
        'aciklama': 'Aşama bazlı ECL toplamları ve ortalama risk parametreleri (BDDK KR-3)',
        'icon': 'bi-table',
    },
    'sermaye_yeterliligi': {
        'label': 'Sermaye Yeterliliği Özeti',
        'aciklama': 'Basel III IRB sermaye gereksinimi ve CAR tahmini (BDDK SY-1)',
        'icon': 'bi-bank',
    },
}


@bddk_bp.route('/')
@login_required
@admin_required
def panel():
    return render_template('bddk.html', rapor_turleri=RAPOR_TURLERI,
                           today=date.today().isoformat())


@bddk_bp.route('/indir', methods=['POST'])
@login_required
@admin_required
def indir():
    rapor_turu = request.form.get('rapor_turu', '')
    period_start = request.form.get('period_start') or None
    period_end = request.form.get('period_end') or None
    entity_name = request.form.get('entity_name', 'Radar Kullanıcı').strip() or 'Radar Kullanıcı'

    if rapor_turu not in RAPOR_TURLERI:
        flash('Geçersiz rapor türü.', 'error')
        return redirect(url_for('bddk.panel'))

    db = get_session()
    try:
        import bddk_reporter
        tenant_id = getattr(__import__('flask_login', fromlist=['current_user']).current_user,
                            'tenant_id', 1) or 1

        if rapor_turu == 'portfoy_kredi_riski':
            xml_bytes = bddk_reporter.portfoy_kredi_riski(
                db, tenant_id=tenant_id,
                period_start=period_start, period_end=period_end,
                entity_name=entity_name,
            )
        elif rapor_turu == 'ifrs9_karsılik':
            xml_bytes = bddk_reporter.ifrs9_karsılik(
                db, tenant_id=tenant_id,
                period_start=period_start, period_end=period_end,
                entity_name=entity_name,
            )
        else:
            xml_bytes = bddk_reporter.sermaye_yeterliligi(
                db, tenant_id=tenant_id,
                period_start=period_start, period_end=period_end,
                entity_name=entity_name,
            )
    except Exception as e:
        flash(f'Rapor oluşturma hatası: {e}', 'error')
        return redirect(url_for('bddk.panel'))
    finally:
        db.close()

    tarih = date.today().strftime('%Y%m%d')
    filename = f'BDDK_{rapor_turu}_{tarih}.xml'
    return Response(
        xml_bytes,
        mimetype='application/xml',
        headers={'Content-Disposition': f'attachment; filename="{filename}"'},
    )
