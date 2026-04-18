from flask import Blueprint, request, redirect, url_for, flash, render_template, session as flask_session
from flask_login import login_required, current_user
from datetime import datetime
from functools import wraps
import time

from database import get_session, Customer, AgingRecord as AgingRecordDB, CreditRequest, CreditScore
from aging_analyzer import AgingAnalyzer, AgingRecord
from credit_scoring import CreditScorer
from routes.admin import get_settings

scoring_bp = Blueprint('scoring', __name__)

# Simple custom rate limiter (copied from app.py)
def request_limit(seconds=5):
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            if not current_user.is_authenticated:
                return f(*args, **kwargs)
            
            last_request_time = flask_session.get(f'last_req_{f.__name__}')
            now = time.time()
            if last_request_time and (now - last_request_time < seconds):
                flash(f"Lütfen çok hızlı talep göndermeyin. {int(seconds - (now - last_request_time))} saniye bekleyin.", 'error')
                return redirect(request.referrer or url_for('main.index'))
            
            flask_session[f'last_req_{f.__name__}'] = now
            return f(*args, **kwargs)
        return wrapper
    return decorator

@scoring_bp.route('/credit_request', methods=['POST'])
@login_required
@request_limit(seconds=10)
def credit_request():
    customer_id = request.form.get('customer_id')
    amount_str = request.form.get('amount')
    currency = request.form.get('currency', 'TL')
    
    try:
        amount = float(amount_str.replace('.', '').replace(',', '.'))
    except:
        flash('Geçersiz tutar', 'error')
        return redirect(url_for('main.index'))
        
    db_session = get_session()
    customer = db_session.query(Customer).filter(Customer.id == customer_id).first()
    
    if not customer:
        db_session.close()
        flash('Müşteri bulunamadı', 'error')
        return redirect(url_for('main.index'))
        
    db_records = db_session.query(AgingRecordDB).filter(
        AgingRecordDB.customer_id == customer_id
    ).order_by(AgingRecordDB.period.desc()).limit(12).all()
    
    calc_records = [AgingRecord(
        period=r.period, overdue=r.overdue, days_1_30=r.days_1_30,
        days_31_60=r.days_31_60, days_61_90=r.days_61_90, days_90_plus=r.days_90_plus,
        total_debt=r.total_debt, type=r.type
    ) for r in db_records]
    
    req = CreditRequest(customer_id=customer_id, request_amount=amount, currency=currency, request_date=datetime.now().date())
    db_session.add(req)
    db_session.flush()
    
    settings = get_settings()
    rate = settings.get('interest_rate', 45.0)
    risk = settings.get('sector_risk', 1.0)
    inflation = settings.get('inflation_rate', 55.0)
    
    fixed_records = []
    for r in calc_records:
        r.type = 'past' if r.type in ['TL', 'past', 'TL_past'] else r.type
        fixed_records.append(r)
        
    scorer = CreditScorer(customer_id, db_session=db_session)
    lang = flask_session.get('lang', 'tr')
    
    res = scorer.calculate(
        settings={'interest_rate': rate, 'sector_risk': risk, 'inflation_rate': inflation},
        request_input={'request_amount': amount, 'currency': currency},
        lang=lang
    )
    
    score_db = CreditScore(
        customer_id=customer_id, credit_request_id=req.id,
        historical_score=res.historical_score, future_score=res.future_score,
        request_score=res.request_score, debt_score=res.debt_score,
        final_score=res.final_score, credit_note=res.credit_note,
        avg_delay_days=res.avg_delay_days, avg_debt=res.avg_debt,
        next_6_months_total=res.future_6_months_total,
        recommended_limit=res.recommended_limit, max_capacity=res.max_capacity,
        instant_equity=customer.equity, instant_liquidity=customer.liquidity_ratio,
        instant_net_profit=customer.annual_net_profit,
        trend_score=res.momentum_score, trend_direction=res.trend_direction,
        assessment=res.assessment, decision_summary=res.decision_summary,
        vade_days=res.vade_days, vade_message=res.vade_message,
        z_score=res.z_score, z_score_note=res.z_score_note,
        dscr_score=res.dscr_score, volatility=res.volatility
    )
    db_session.add(score_db)
    db_session.commit()
    
    final_talep_id = req.id
    db_session.close()
    
    return redirect(url_for('scoring.rapor', talep_id=final_talep_id))

@scoring_bp.route('/report/<int:talep_id>', endpoint='rapor')
@login_required
def report_view(talep_id):
    db_session = get_session()
    skor = db_session.query(CreditScore).filter(CreditScore.credit_request_id == talep_id).first()
    
    if not skor:
        db_session.close()
        flash('Rapor bulunamadı', 'error')
        return redirect(url_for('main.index'))
    
    customer = db_session.query(Customer).filter(
        (Customer.id == skor.customer_id) & 
        ((Customer.is_sample == True) | (Customer.user_id == current_user.id))
    ).first()
    
    if not customer:
        db_session.close()
        return "Yetkisiz erişim", 403
        
    talep = db_session.query(CreditRequest).filter(CreditRequest.id == talep_id).first()
    
    from credit_scoring import CreditRequestInput
    
    # Re-calculate to get dynamic scenarios and experts
    settings = get_settings()
    scorer = CreditScorer(customer.id, db_session=db_session)
    
    # We use the request_amount from the talep record
    req_input = CreditRequestInput(request_amount=talep.request_amount, currency=talep.currency)
    
    res_dynamic = scorer.calculate(
        settings=settings,
        request_input=req_input,
        lang=lang
    )

    class ResultWrapper:
        def __init__(self, s, dyn):
            self.credit_note = s.credit_note
            self.final_score = s.final_score
            self.decision_summary = s.decision_summary
            self.trend_direction = s.trend_direction
            self.max_capacity = s.max_capacity
            self.recommended_limit = s.recommended_limit
            self.historical_score = s.historical_score
            self.future_score = s.future_score
            self.request_score = s.request_score
            self.momentum_score = s.trend_score
            self.assessment = s.assessment
            self.vade_days = s.vade_days
            self.vade_message = s.vade_message
            self.scenarios = dyn.scenarios
            self.volatility = getattr(s, 'volatility', 0) or 0
            self.dscr_score = getattr(s, 'dscr_score', 0) or 0
            self.z_score = getattr(s, 'z_score', 0) or 0
            self.z_score_note = getattr(s, 'z_score_note', 'N/A') or 'N/A'

    sonuc = ResultWrapper(skor, res_dynamic)
    db_session.close()
    return render_template('rapor.html', musteri=customer, talep=talep, skor=skor, sonuc=sonuc)
