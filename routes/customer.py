from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from database import get_session, Customer, AgingRecord as AgingRecordDB, CreditRequest, CreditScore

customer_bp = Blueprint('customer', __name__)

@customer_bp.route('/new_customer', methods=['GET', 'POST'])
@login_required
def new_customer():
    if request.method == 'POST':
        db_session = get_session()
        account_code = request.form.get('account_code', '').strip()
        account_name = request.form.get('account_name', '').strip()
        
        if not account_code or not account_name:
            flash('Hesap kodu ve ismi zorunludur', 'error')
            return redirect(url_for('customer.new_customer'))
            
        new_c = Customer(
            user_id=current_user.id,
            is_sample=False,
            account_code=account_code,
            account_name=account_name,
            tax_no=request.form.get('tax_no', ''),
            phone=request.form.get('phone', ''),
            email=request.form.get('email', ''),
            equity=float(request.form.get('equity', '0') or 0),
            annual_net_profit=float(request.form.get('net_profit', '0') or 0),
            current_assets=float(request.form.get('current_assets', '0') or 0),
            short_term_liabilities=float(request.form.get('st_liabilities', '0') or 0)
        )
        
        if new_c.short_term_liabilities > 0:
            new_c.liquidity_ratio = new_c.current_assets / new_c.short_term_liabilities
        else:
            new_c.liquidity_ratio = 1.0
            
        db_session.add(new_c)
        db_session.commit()
        db_session.close()
        
        flash(f'{account_name} başarıyla oluşturuldu', 'success')
        return redirect(url_for('main.index'))
    return render_template('yeni_musteri.html')

@customer_bp.route('/customer/<int:customer_id>')
@login_required
def customer_detail(customer_id):
    session = get_session()
    customer = session.query(Customer).filter(
        (Customer.id == customer_id) & 
        ((Customer.is_sample == True) | (Customer.user_id == current_user.id))
    ).first()
    
    if not customer:
        session.close()
        return "Yetkiniz yok veya müşteri bulunamadı", 403
    
    aging_records = session.query(AgingRecordDB).filter(
        AgingRecordDB.customer_id == customer_id
    ).order_by(AgingRecordDB.period.desc()).all()
    
    requests = session.query(CreditRequest).filter(
        CreditRequest.customer_id == customer_id
    ).order_by(CreditRequest.request_date.desc()).all()
    
    request_list = []
    for r in requests:
        score = session.query(CreditScore).filter(
            CreditScore.credit_request_id == r.id
        ).first()
        
        request_list.append({
            'id': r.id,
            'amount': r.request_amount,
            'currency': r.currency,
            'date': r.request_date,
            'status': r.approval_status,
            'note': score.credit_note if score else '-',
            'score': score.final_score if score else 0
        })
    
    session.close()
    return render_template('musteri_detay.html', customer=customer, aging_records=aging_records, requests=request_list)
