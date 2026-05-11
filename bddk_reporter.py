"""
BDDK Düzenleyici Raporlama — XML / XBRL çıktısı

Desteklenen rapor türleri:
  1. portfoy_kredi_riski  — Portföy kredi riski özeti (müşteri bazlı ECL, stage)
  2. ifrs9_karsılik       — IFRS 9 karşılık tablosu (stage bazlı toplam ECL/RWA)
  3. sermaye_yeterliligi  — Basel III sermaye yeterliliği özeti

Çıktı formatı: XBRL-benzeri XML (BDDK GL taksonomisine uyumlu iskelet)
  - xmlns:bddk namespace
  - <context> blokları (dönem + kurum)
  - <unit> bloğu (TRY)
  - Her olgu <bddk:fact> elemanı olarak temsil edilir
"""

import math
from datetime import datetime, date
from typing import Optional
import xml.etree.ElementTree as ET


# ──────────────────────────────────────────────────────────────
# Namespace & yardımcılar
# ──────────────────────────────────────────────────────────────

NSMAP = {
    'xmlns': 'http://www.bddk.org.tr/radar/xbrl/2024',
    'xmlns:xbrli': 'http://www.xbrl.org/2003/instance',
    'xmlns:iso4217': 'http://www.xbrl.org/2003/iso4217',
    'xmlns:bddk': 'http://www.bddk.org.tr/taxonomy/2024',
}


def _fmt_decimal(val: float, places: int = 2) -> str:
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return '0.00'
    return f'{val:.{places}f}'


def _today_str() -> str:
    return date.today().isoformat()


def _build_xbrl_root(period_start: str, period_end: str, entity_name: str) -> ET.Element:
    root = ET.Element('xbrl')
    for k, v in NSMAP.items():
        root.set(k, v)
    root.set('schemaRef', 'http://www.bddk.org.tr/taxonomy/2024/bddk-kredi-risk.xsd')

    # Context: dönem
    ctx = ET.SubElement(root, 'xbrli:context', id='ctx_donem')
    entity = ET.SubElement(ctx, 'xbrli:entity')
    ET.SubElement(entity, 'xbrli:identifier', scheme='http://www.bddk.org.tr').text = entity_name
    period = ET.SubElement(ctx, 'xbrli:period')
    ET.SubElement(period, 'xbrli:startDate').text = period_start
    ET.SubElement(period, 'xbrli:endDate').text = period_end

    # Context: raporlama tarihi (anlık)
    ctx2 = ET.SubElement(root, 'xbrli:context', id='ctx_anlik')
    entity2 = ET.SubElement(ctx2, 'xbrli:entity')
    ET.SubElement(entity2, 'xbrli:identifier', scheme='http://www.bddk.org.tr').text = entity_name
    instant = ET.SubElement(ctx2, 'xbrli:period')
    ET.SubElement(instant, 'xbrli:instant').text = _today_str()

    # Unit: TRY
    unit = ET.SubElement(root, 'xbrli:unit', id='TRY')
    ET.SubElement(unit, 'xbrli:measure').text = 'iso4217:TRY'

    # Unit: saf sayı
    unit2 = ET.SubElement(root, 'xbrli:unit', id='PURE')
    ET.SubElement(unit2, 'xbrli:measure').text = 'xbrli:pure'

    # Rapor meta
    meta = ET.SubElement(root, 'bddk:RaporMeta')
    ET.SubElement(meta, 'bddk:UretimTarihi').text = datetime.utcnow().isoformat()
    ET.SubElement(meta, 'bddk:Versiyon').text = '1.0'
    ET.SubElement(meta, 'bddk:RaporlayiciSistem').text = 'Radar Risk Platform'

    return root


def _fact(parent: ET.Element, tag: str, value: str,
          contextRef: str = 'ctx_donem', unitRef: str = 'TRY',
          decimals: str = '2') -> ET.Element:
    el = ET.SubElement(parent, f'bddk:{tag}',
                       contextRef=contextRef, unitRef=unitRef, decimals=decimals)
    el.text = value
    return el


def _fact_text(parent: ET.Element, tag: str, value: str,
               contextRef: str = 'ctx_donem') -> ET.Element:
    el = ET.SubElement(parent, f'bddk:{tag}', contextRef=contextRef)
    el.text = str(value)
    return el


def _fact_int(parent: ET.Element, tag: str, value, contextRef: str = 'ctx_donem') -> ET.Element:
    el = ET.SubElement(parent, f'bddk:{tag}',
                       contextRef=contextRef, unitRef='PURE', decimals='0')
    el.text = str(int(value or 0))
    return el


def _to_xml_bytes(root: ET.Element) -> bytes:
    ET.indent(root, space='  ')
    return ET.tostring(root, encoding='unicode', xml_declaration=False).encode('utf-8')


# ──────────────────────────────────────────────────────────────
# Rapor 1: Portföy Kredi Riski
# ──────────────────────────────────────────────────────────────

def portfoy_kredi_riski(db_session, tenant_id: int = 1,
                        period_start: Optional[str] = None,
                        period_end: Optional[str] = None,
                        entity_name: str = 'Radar Kullanıcı') -> bytes:
    """
    Her müşteri için son kredi skoru + ECL/RWA bilgisi içeren XML raporu.
    BDDK Tablo: KR-1 Kredi Riski Genel Özeti
    """
    from database import CreditScore, Customer, CreditRequest

    period_end = period_end or _today_str()
    period_start = period_start or date.today().replace(day=1).isoformat()

    root = _build_xbrl_root(period_start, period_end, entity_name)

    # Son skoru olan müşterileri çek
    from sqlalchemy import func
    subq = (
        db_session.query(
            CreditScore.customer_id,
            func.max(CreditScore.calculated_at).label('max_date'),
        )
        .join(Customer, CreditScore.customer_id == Customer.id)
        .filter(Customer.tenant_id == tenant_id)
        .group_by(CreditScore.customer_id)
        .subquery()
    )
    scores = (
        db_session.query(CreditScore)
        .join(subq, (CreditScore.customer_id == subq.c.customer_id) &
                    (CreditScore.calculated_at == subq.c.max_date))
        .join(Customer, CreditScore.customer_id == Customer.id)
        .all()
    )

    tablo = ET.SubElement(root, 'bddk:KR1_KrediRiskiGenelOzet')
    _fact_int(tablo, 'ToplamMusteriSayisi', len(scores))

    toplam_ecl = sum(float(s.ifrs9_ecl or 0) for s in scores)
    toplam_rwa = sum(float(s.ifrs9_rwa or 0) for s in scores)
    toplam_ead = sum(float(s.ifrs9_ead or 0) for s in scores)

    _fact(tablo, 'ToplamBeklenenKrediZarari_TRY', _fmt_decimal(toplam_ecl))
    _fact(tablo, 'ToplamRiskAgirlikliVarlik_TRY', _fmt_decimal(toplam_rwa))
    _fact(tablo, 'ToplamMaruzKalinimTutari_TRY', _fmt_decimal(toplam_ead))

    musteri_listesi = ET.SubElement(tablo, 'bddk:MusteriListesi')
    for s in scores:
        cust = db_session.query(Customer).filter(Customer.id == s.customer_id).first()
        item = ET.SubElement(musteri_listesi, 'bddk:Musteri')
        ET.SubElement(item, 'bddk:HesapKodu').text = getattr(cust, 'account_code', '') or ''
        ET.SubElement(item, 'bddk:HesapAdi').text = getattr(cust, 'account_name', '') or ''
        ET.SubElement(item, 'bddk:KrediNotu').text = s.credit_note or 'N/A'
        ET.SubElement(item, 'bddk:NihaiSkor').text = _fmt_decimal(s.final_score or 0)
        ET.SubElement(item, 'bddk:IFRS9Asama').text = str(s.ifrs9_stage or 1)
        ET.SubElement(item, 'bddk:TemerrütOlasiligi').text = _fmt_decimal(s.ifrs9_pd or 0, 4)
        ET.SubElement(item, 'bddk:KayipOraniTemerrut').text = _fmt_decimal(s.ifrs9_lgd or 0, 4)
        ET.SubElement(item, 'bddk:MaruzKalinimTutari_TRY').text = _fmt_decimal(s.ifrs9_ead or 0)
        ET.SubElement(item, 'bddk:BeklenenKrediZarari_TRY').text = _fmt_decimal(s.ifrs9_ecl or 0)
        ET.SubElement(item, 'bddk:RiskAgirlikliVarlik_TRY').text = _fmt_decimal(s.ifrs9_rwa or 0)
        ET.SubElement(item, 'bddk:SermayeGereksinimi_TRY').text = _fmt_decimal(s.ifrs9_capital_req or 0)
        ET.SubElement(item, 'bddk:HesaplamaTarihi').text = (
            s.calculated_at.isoformat() if s.calculated_at else ''
        )

    return _to_xml_bytes(root)


# ──────────────────────────────────────────────────────────────
# Rapor 2: IFRS 9 Karşılık Tablosu
# ──────────────────────────────────────────────────────────────

def ifrs9_karsılik(db_session, tenant_id: int = 1,
                   period_start: Optional[str] = None,
                   period_end: Optional[str] = None,
                   entity_name: str = 'Radar Kullanıcı') -> bytes:
    """
    Aşama bazlı ECL toplamları — BDDK Tablo: KR-3 IFRS 9 Karşılık Tablosu
    """
    from database import CreditScore, Customer
    from sqlalchemy import func

    period_end = period_end or _today_str()
    period_start = period_start or date.today().replace(day=1).isoformat()

    root = _build_xbrl_root(period_start, period_end, entity_name)

    subq = (
        db_session.query(
            CreditScore.customer_id,
            func.max(CreditScore.calculated_at).label('max_date'),
        )
        .join(Customer, CreditScore.customer_id == Customer.id)
        .filter(Customer.tenant_id == tenant_id)
        .group_by(CreditScore.customer_id)
        .subquery()
    )
    scores = (
        db_session.query(CreditScore)
        .join(subq, (CreditScore.customer_id == subq.c.customer_id) &
                    (CreditScore.calculated_at == subq.c.max_date))
        .all()
    )

    tablo = ET.SubElement(root, 'bddk:KR3_IFRS9KarsilikTablosu')

    def _stage_rows(stage: int) -> list:
        return [s for s in scores if (s.ifrs9_stage or 1) == stage]

    for stage in (1, 2, 3):
        rows = _stage_rows(stage)
        stage_el = ET.SubElement(tablo, f'bddk:Asama{stage}')
        label = {1: '12 Aylık ECL', 2: 'Ömür Boyu ECL (Artış)', 3: 'Ömür Boyu ECL (Değer Düşüklüğü)'}
        ET.SubElement(stage_el, 'bddk:AsamaAciklamasi').text = label[stage]
        _fact_int(stage_el, 'MusteriSayisi', len(rows))
        _fact(stage_el, 'ToplamEAD_TRY', _fmt_decimal(sum(float(r.ifrs9_ead or 0) for r in rows)))
        _fact(stage_el, 'ToplamECL_TRY', _fmt_decimal(sum(float(r.ifrs9_ecl or 0) for r in rows)))
        _fact(stage_el, 'OrtPD', _fmt_decimal(
            sum(float(r.ifrs9_pd or 0) for r in rows) / len(rows) if rows else 0, 4))
        _fact(stage_el, 'OrtLGD', _fmt_decimal(
            sum(float(r.ifrs9_lgd or 0) for r in rows) / len(rows) if rows else 0, 4))

    # Toplam
    toplam = ET.SubElement(tablo, 'bddk:Toplam')
    _fact(toplam, 'ToplamECL_TRY', _fmt_decimal(sum(float(s.ifrs9_ecl or 0) for s in scores)))
    _fact(toplam, 'ToplamEAD_TRY', _fmt_decimal(sum(float(s.ifrs9_ead or 0) for s in scores)))
    _fact_int(toplam, 'ToplamMusteriSayisi', len(scores))

    return _to_xml_bytes(root)


# ──────────────────────────────────────────────────────────────
# Rapor 3: Sermaye Yeterliliği Özeti
# ──────────────────────────────────────────────────────────────

def sermaye_yeterliligi(db_session, tenant_id: int = 1,
                        period_start: Optional[str] = None,
                        period_end: Optional[str] = None,
                        entity_name: str = 'Radar Kullanıcı') -> bytes:
    """
    Basel III IRB sermaye gerekliliği özeti — BDDK Tablo: SY-1
    """
    from database import CreditScore, Customer
    from sqlalchemy import func

    period_end = period_end or _today_str()
    period_start = period_start or date.today().replace(day=1).isoformat()

    root = _build_xbrl_root(period_start, period_end, entity_name)

    subq = (
        db_session.query(
            CreditScore.customer_id,
            func.max(CreditScore.calculated_at).label('max_date'),
        )
        .join(Customer, CreditScore.customer_id == Customer.id)
        .filter(Customer.tenant_id == tenant_id)
        .group_by(CreditScore.customer_id)
        .subquery()
    )
    scores = (
        db_session.query(CreditScore)
        .join(subq, (CreditScore.customer_id == subq.c.customer_id) &
                    (CreditScore.calculated_at == subq.c.max_date))
        .all()
    )

    toplam_rwa = sum(float(s.ifrs9_rwa or 0) for s in scores)
    toplam_cr = sum(float(s.ifrs9_capital_req or 0) for s in scores)
    toplam_ead = sum(float(s.ifrs9_ead or 0) for s in scores)

    # Ağırlıklı ort PD
    ort_pd = (
        sum(float(s.ifrs9_pd or 0) * float(s.ifrs9_ead or 0) for s in scores) / toplam_ead
        if toplam_ead > 0 else 0.0
    )

    tablo = ET.SubElement(root, 'bddk:SY1_SermayeYeterlilikOzeti')

    _fact_int(tablo, 'ToplamMaruzKalinimSayisi', len(scores))
    _fact(tablo, 'ToplamMaruzKalinimTutari_TRY', _fmt_decimal(toplam_ead))
    _fact(tablo, 'ToplamRiskAgirlikliVarlik_TRY', _fmt_decimal(toplam_rwa))
    _fact(tablo, 'Pillar1SermayeGereksinimi_TRY', _fmt_decimal(toplam_cr))
    _fact(tablo, 'AgirliklıOrtPD', _fmt_decimal(ort_pd, 4))

    # CAR tahmini (basit: CR / EAD)
    car_est = (toplam_cr / toplam_ead * 100) if toplam_ead > 0 else 0.0
    _fact(tablo, 'SermayeYeterlilikRasyoTahmini_Yuzde', _fmt_decimal(car_est, 4),
          unitRef='PURE')

    # Not dağılımı
    not_dagılımı = ET.SubElement(tablo, 'bddk:KrediNotuDagilimi')
    from collections import Counter
    note_counts = Counter(s.credit_note or 'N/A' for s in scores)
    for note, count in sorted(note_counts.items()):
        el = ET.SubElement(not_dagılımı, 'bddk:NotGrubu')
        ET.SubElement(el, 'bddk:Not').text = note
        ET.SubElement(el, 'bddk:Adet').text = str(count)
        group_ecl = sum(float(s.ifrs9_ecl or 0) for s in scores if (s.credit_note or 'N/A') == note)
        ET.SubElement(el, 'bddk:ToplamECL_TRY').text = _fmt_decimal(group_ecl)

    return _to_xml_bytes(root)
