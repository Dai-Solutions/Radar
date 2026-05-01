from flask import Blueprint, render_template, redirect, url_for, session, request
from flask_login import login_required, current_user
from database import get_session, Customer, CreditScore, CreditRequest, AgingRecord as AgingRecordDB
from translations import translations

main_bp = Blueprint('main', __name__)

@main_bp.route('/')
@login_required
def index():
    from routes.admin import get_settings
    db_session = get_session()
    try:
        customers = db_session.query(Customer).filter(
            (Customer.is_sample == True) | (Customer.user_id == current_user.id)
        ).order_by(Customer.account_name).all()

        customer_list = []
        for c in customers:
            score = db_session.query(CreditScore).filter(
                CreditScore.customer_id == c.id
            ).order_by(CreditScore.calculated_at.desc()).first()

            latest_request = db_session.query(CreditRequest).filter(
                CreditRequest.customer_id == c.id
            ).order_by(CreditRequest.request_date.desc()).first()

            customer_list.append({
                'id': c.id,
                'account_code': c.account_code,
                'account_name': c.account_name,
                'last_score': score.credit_note if score else '-',
                'last_request': f"{latest_request.request_amount:,.0f} TL" if latest_request else '-',
                'record_count': db_session.query(AgingRecordDB).filter(AgingRecordDB.customer_id == c.id).count()
            })

        settings = get_settings()
        return render_template('index.html', customers=customer_list, settings=settings)
    finally:
        db_session.close()

@main_bp.route('/set_language/<lang>')
def set_language(lang):
    if lang in ('tr', 'en', 'es', 'de'):
        session['lang'] = lang
    return redirect(request.referrer or url_for('main.index'))

@main_bp.route('/nedir')
@login_required
def nedir():
    lang = session.get('lang', 'tr')
    t = translations[lang]
    return render_template('nedir.html', t=t, lang=lang)

@main_bp.route('/guvenlik')
@login_required
def guvenlik():
    lang = session.get('lang', 'tr')
    t = translations[lang]
    return render_template('guvenlik.html', t=t, lang=lang)
