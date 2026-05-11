import os
import logging
from sqlalchemy import create_engine, Column, Integer, String, Float, ForeignKey, Boolean, Date, DateTime, Text, func, inspect, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from datetime import datetime
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

load_dotenv()

Base = declarative_base()

class Tenant(Base):
    """Multi-tenant support — her firma kendi tenant'ı"""
    __tablename__ = 'tenants'
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    slug = Column(String, unique=True, nullable=False)  # URL-friendly identifier
    description = Column(String)
    logo_url = Column(String)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    users = relationship("User", back_populates="tenant")
    customers = relationship("Customer", back_populates="tenant")
    audit_logs = relationship("AuditLog", back_populates="tenant", cascade="all, delete-orphan")

class Role(Base):
    """RBAC Roller"""
    __tablename__ = 'roles'
    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True, nullable=False)  # admin, credit_manager, analyst, approver
    description = Column(String)
    permissions = Column(String)  # JSON-encoded permissions
    created_at = Column(DateTime, default=datetime.utcnow)
    
    user_roles = relationship("UserRole", back_populates="role", cascade="all, delete-orphan")

class UserRole(Base):
    """User ↔ Role mapping"""
    __tablename__ = 'user_roles'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    role_id = Column(Integer, ForeignKey('roles.id'), nullable=False)
    assigned_at = Column(DateTime, default=datetime.utcnow)
    
    user = relationship("User", back_populates="roles")
    role = relationship("Role", back_populates="user_roles")

class AuditLog(Base):
    """Compliance & Audit logging"""
    __tablename__ = 'audit_logs'
    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey('tenants.id'), nullable=False)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=True)
    action = Column(String, nullable=False)  # create, update, delete, view, export
    entity_type = Column(String, nullable=False)  # Customer, CreditScore, User, etc.
    entity_id = Column(Integer)
    changes = Column(Text)  # JSON with before/after values
    ip_address = Column(String)
    user_agent = Column(String)
    status = Column(String, default='success')  # success, failure
    error_message = Column(String)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    # Soft delete — audit kayıtları compliance gereği fiziksel silinmez.
    # Retention dolduğunda deleted_at set edilir; pruning ayrı job ile yapılır.
    deleted_at = Column(DateTime, nullable=True, index=True)

    tenant = relationship("Tenant", back_populates="audit_logs")
    user = relationship("User")

class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)
    # nullable=True for backfill compatibility; new rows default to tenant 1
    tenant_id = Column(Integer, ForeignKey('tenants.id'), nullable=True, default=1, index=True)
    email = Column(String, unique=True, nullable=False)
    password_hash = Column(String, nullable=True)
    full_name = Column(String)
    google_id = Column(String)
    language = Column(String(5), default='tr')
    is_active = Column(Boolean, default=True)
    is_admin = Column(Boolean, default=False)
    email_verified = Column(Boolean, default=False)
    totp_secret = Column(String, nullable=True)
    totp_enabled = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    tenant = relationship("Tenant", back_populates="users")
    roles = relationship("UserRole", back_populates="user", cascade="all, delete-orphan")

class Customer(Base):
    __tablename__ = 'customers'
    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey('tenants.id'), nullable=True, default=1, index=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=True)
    is_sample = Column(Boolean, default=False)
    account_code = Column(String, unique=True, nullable=False)
    account_name = Column(String, nullable=False)
    tax_no = Column(String)
    phone = Column(String)
    email = Column(String)
    
    # Financial Data for Standard Scoring
    equity = Column(Float, default=0.0)
    annual_net_profit = Column(Float, default=0.0)
    current_assets = Column(Float, default=0.0)
    short_term_liabilities = Column(Float, default=0.0)
    liquidity_ratio = Column(Float, default=1.0)
    sector_risk_factor = Column(Float, default=1.0)
    
    # NEW: Advanced Financial Data for Altman Z-Score
    total_assets = Column(Float, default=0.0)
    total_liabilities = Column(Float, default=0.0)
    retained_earnings = Column(Float, default=0.0)
    ebit = Column(Float, default=0.0)
    sales = Column(Float, default=0.0)
    working_capital = Column(Float, default=0.0)
    
    # NEW: Cash Flow Data for DSCR
    interest_expenses = Column(Float, default=0.0)
    principal_payments = Column(Float, default=0.0)

    # Sektör — Z-Score katsayı setini belirler
    sector = Column(String(32), default='general')

    created_at = Column(DateTime, default=datetime.utcnow)

    tenant = relationship("Tenant", back_populates="customers")
    user = relationship("User")
    aging_records = relationship("AgingRecord", back_populates="customer", cascade="all, delete-orphan")
    credit_requests = relationship("CreditRequest", back_populates="customer", cascade="all, delete-orphan")
    kkb_reports = relationship("KKBReport", back_populates="customer", cascade="all, delete-orphan")

class AgingRecord(Base):
    __tablename__ = 'aging_records'
    id = Column(Integer, primary_key=True)
    customer_id = Column(Integer, ForeignKey('customers.id'), nullable=False)
    period = Column(String, nullable=False)
    overdue = Column(Float, default=0.0)
    days_1_30 = Column(Float, default=0.0)
    days_31_60 = Column(Float, default=0.0)
    days_61_90 = Column(Float, default=0.0)
    days_90_plus = Column(Float, default=0.0)
    total_debt = Column(Float, default=0.0)
    type = Column(String, default='past')
    
    customer = relationship("Customer", back_populates="aging_records")

class CreditRequest(Base):
    __tablename__ = 'credit_requests'
    id = Column(Integer, primary_key=True)
    customer_id = Column(Integer, ForeignKey('customers.id'), nullable=False)
    request_amount = Column(Float, nullable=False)
    currency = Column(String(5), default='TL')
    request_date = Column(Date, default=lambda: datetime.utcnow().date())
    approval_status = Column(String, default='Pending')
    
    customer = relationship("Customer", back_populates="credit_requests")
    score_result = relationship("CreditScore", back_populates="request", uselist=False)

class CreditScore(Base):
    __tablename__ = 'credit_scores'
    id = Column(Integer, primary_key=True)
    customer_id = Column(Integer, ForeignKey('customers.id'), nullable=False)
    credit_request_id = Column(Integer, ForeignKey('credit_requests.id'), nullable=False)
    
    historical_score = Column(Float)
    future_score = Column(Float)
    request_score = Column(Float)
    debt_score = Column(Float)
    final_score = Column(Float)
    credit_note = Column(String(2))
    
    # Altman Z-Score Fields
    z_score = Column(Float)
    z_score_note = Column(String)
    dscr_score = Column(Float)
    volatility = Column(Float) # NEW: Growth stability metric
    
    avg_delay_days = Column(Float)
    avg_debt = Column(Float)
    next_6_months_total = Column(Float)
    recommended_limit = Column(Float)
    max_capacity = Column(Float)
    
    instant_equity = Column(Float)
    instant_liquidity = Column(Float)
    instant_net_profit = Column(Float)
    
    trend_score = Column(Float)
    trend_direction = Column(String)
    
    assessment = Column(Text)
    decision_summary = Column(Text)
    scenarios_json = Column(Text)

    # Faz 4 — Ek analiz metrikleri
    piotroski_score = Column(Integer)   # 0-9 puan
    piotroski_grade = Column(String(8)) # Güçlü / Orta / Zayıf
    icr_score = Column(Float)           # Interest Coverage Ratio
    aging_concentration = Column(Float) # 90+ gün yüzdesi

    # Hierarchical Vade Result
    vade_days = Column(Integer)
    vade_message = Column(String)

    # KKB entegrasyon sonuçları
    kkb_veto = Column(String(50), nullable=True)
    kkb_enriched = Column(Boolean, default=False)

    # IFRS 9 / Basel III
    ifrs9_stage = Column(Integer, nullable=True)          # 1, 2, 3
    ifrs9_pd = Column(Float, nullable=True)               # Temerrüt olasılığı
    ifrs9_lgd = Column(Float, nullable=True)              # Temerrüt kayıp oranı
    ifrs9_ead = Column(Float, nullable=True)              # Maruz kalım (TL)
    ifrs9_ecl = Column(Float, nullable=True)              # Beklenen kredi zararı (TL)
    ifrs9_rwa = Column(Float, nullable=True)              # Risk ağırlıklı varlık (TL)
    ifrs9_capital_req = Column(Float, nullable=True)      # Sermaye gereksinimi (TL)
    
    calculated_at = Column(DateTime, default=datetime.utcnow)
    
    customer = relationship("Customer")
    request = relationship("CreditRequest", back_populates="score_result")

class KKBReport(Base):
    """
    KKB (Kredi Kayıt Bürosu) kurumsal risk raporu.

    Her sorgu önbelleğe alınır (expires_at). Cache süresi dolmadan
    aynı vergi no için API çağrısı yapılmaz. Hard veto alanları
    (has_bounced_check, active_enforcement) CreditScorer'da öncelikli
    kontrol edilir; pozitifse skor hesaplanmadan ret kararı üretilir.

    source: 'kkb_api' | 'manual' | 'mock'
    """
    __tablename__ = 'kkb_reports'

    id = Column(Integer, primary_key=True)
    customer_id = Column(Integer, ForeignKey('customers.id'), nullable=True)
    tenant_id = Column(Integer, ForeignKey('tenants.id'), nullable=True, default=1, index=True)
    tax_no = Column(String(11), nullable=False, index=True)

    # KRS — Kurumsal Risk Sistemi: tüm bankalardan konsolide borç
    total_bank_exposure = Column(Float)     # Toplam kredi borcu (TL)
    npl_amount = Column(Float, default=0.0) # Takipteki alacak tutarı
    npl_flag = Column(Boolean, default=False)

    # RSK — ödeme geçmişi, son 12 ay
    max_days_past_due = Column(Integer, default=0)
    num_late_payments = Column(Integer, default=0)

    # Hard veto — pozitifse skor hesaplanmadan ret
    has_bounced_check = Column(Boolean, default=False)
    active_enforcement = Column(Boolean, default=False)

    # GKD — KKB'nin kendi derecelendirmesi (opsiyonel, her bankada gelmeyebilir)
    kkb_score = Column(Integer)   # 1–1900 arası puan
    kkb_grade = Column(String(2)) # A / B / C / D

    # KVKK — sorgu için açık rıza zorunlu
    consent_given = Column(Boolean, default=False)
    consent_timestamp = Column(DateTime)

    # Meta
    fetched_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=False)  # varsayılan 30 gün TTL
    raw_response = Column(Text)  # ham XML/JSON — audit ve debug için
    source = Column(String(20), default='mock')

    customer = relationship("Customer", back_populates="kkb_reports")
    tenant = relationship("Tenant")


class OpenBankingRecord(Base):
    """
    Open Banking hesap/işlem özeti.

    Her IBAN için önbelleklenir (expires_at). Cashflow ve bakiye
    verileri CreditScorer'da historical + future skor zenginleştirmesinde kullanılır.

    source: 'mock' | 'sandbox' | 'live'
    """
    __tablename__ = 'openbanking_records'

    id = Column(Integer, primary_key=True)
    customer_id = Column(Integer, ForeignKey('customers.id'), nullable=True)
    tenant_id = Column(Integer, ForeignKey('tenants.id'), nullable=True, default=1, index=True)
    iban = Column(String(34), nullable=False, index=True)

    # Hesap özeti (12 ay ortalama)
    avg_monthly_balance = Column(Float, default=0.0)   # Aylık ort. bakiye (TL)
    avg_monthly_inflow = Column(Float, default=0.0)    # Aylık ort. giren para
    avg_monthly_outflow = Column(Float, default=0.0)   # Aylık ort. çıkan para
    overdraft_count = Column(Integer, default=0)        # Negatif bakiye gün sayısı
    cashflow_regularity = Column(Float, default=1.0)    # 0–1: 1=çok düzenli

    # Banka çeşitliliği
    bank_count = Column(Integer, default=1)            # Farklı banka hesabı sayısı

    # KVKK — açık rıza
    consent_given = Column(Boolean, default=False)
    consent_timestamp = Column(DateTime)

    # Meta
    fetched_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=False)
    raw_response = Column(Text)
    source = Column(String(20), default='mock')

    customer = relationship("Customer")
    tenant = relationship("Tenant")


class SSOConfig(Base):
    """
    Tenant başına SSO yapılandırması — SAML 2.0 veya LDAP/AD.

    provider_type: 'saml' | 'ldap'
    Tüm alanlar opsiyonel; aktif provider_type'a göre doldurulur.
    """
    __tablename__ = 'sso_configs'

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey('tenants.id'), nullable=False, unique=True, index=True)
    provider_type = Column(String(10), nullable=False, default='saml')  # 'saml' | 'ldap'
    is_active = Column(Boolean, default=False)

    # SAML 2.0 — IdP bilgileri
    idp_entity_id = Column(String)
    idp_sso_url = Column(String)
    idp_slo_url = Column(String)
    idp_x509_cert = Column(Text)
    sp_entity_id = Column(String)

    # LDAP / Active Directory
    ldap_host = Column(String)
    ldap_port = Column(Integer, default=389)
    ldap_use_ssl = Column(Boolean, default=False)
    ldap_base_dn = Column(String)
    ldap_bind_dn = Column(String)
    ldap_bind_password = Column(String)
    ldap_user_search_filter = Column(String, default='(sAMAccountName={username})')
    ldap_email_attr = Column(String, default='mail')
    ldap_name_attr = Column(String, default='displayName')

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    tenant = relationship("Tenant")


class Feedback(Base):
    __tablename__ = 'feedbacks'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    message = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User")


class BatchJob(Base):
    """Celery toplu portföy analizi iş takibi."""
    __tablename__ = 'batch_jobs'
    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey('tenants.id'), nullable=True, default=1)
    celery_task_id = Column(String(64), nullable=True, index=True)
    job_type = Column(String(32), default='portfolio_scan')  # portfolio_scan | ...
    status = Column(String(16), default='pending')           # pending | running | done | error
    total = Column(Integer, default=0)
    processed = Column(Integer, default=0)
    summary_json = Column(Text, nullable=True)   # JSON özet: dağılım, ECL, vs.
    error_message = Column(Text, nullable=True)
    created_by = Column(Integer, ForeignKey('users.id'), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    finished_at = Column(DateTime, nullable=True)

from sqlalchemy.orm import sessionmaker, relationship, scoped_session

_engine = None
_Session = None  # tek scoped_session registry

def get_db_uri():
    uri = os.getenv('DATABASE_URL')
    if not uri:
        db_path = os.path.join(os.getcwd(), 'data', 'kredi.db')
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        uri = f'sqlite:///{db_path}'
    return uri

def get_engine():
    global _engine
    if _engine is None:
        uri = get_db_uri()
        if uri.startswith('postgresql'):
            _engine = create_engine(
                uri,
                pool_size=10,
                max_overflow=20,
                pool_timeout=30,
                pool_recycle=1800,
                pool_pre_ping=True,
            )
        else:
            _engine = create_engine(uri, connect_args={"check_same_thread": False})
    return _engine

def init_db():
    """Bootstrap schema + run lightweight migrations.

    Concurrency-safe under multiple gunicorn workers: uses a Postgres advisory
    lock (no-op on SQLite) so only one process runs CREATE/ALTER at a time;
    the rest wait, then see tables already exist and return.
    """
    engine = get_engine()
    is_postgres = engine.url.get_backend_name() == 'postgresql'

    if is_postgres:
        with engine.connect() as conn:
            # Arbitrary 64-bit key for Radar schema bootstrap
            conn.execute(text('SELECT pg_advisory_lock(7382001)'))
            try:
                Base.metadata.create_all(conn)
                conn.commit()
                _run_lightweight_migrations(engine)
            finally:
                conn.execute(text('SELECT pg_advisory_unlock(7382001)'))
                conn.commit()
    else:
        Base.metadata.create_all(engine)
        _run_lightweight_migrations(engine)
    return engine


# Columns added by Phase 8/9 that may be missing on pre-2.0 databases.
# create_all() only creates new tables, so we ALTER existing ones in-place.
_PENDING_COLUMNS = {
    'users': [
        ('tenant_id', 'INTEGER'),
        ('language', 'VARCHAR(5)'),
        ('totp_secret', 'VARCHAR(64)'),
        ('totp_enabled', 'BOOLEAN DEFAULT FALSE'),
    ],
    'customers': [
        ('tenant_id', 'INTEGER'),
        # Faz 4 — Altman Z-Score & DSCR fields (may be missing on pre-Faz-4 DBs)
        ('total_assets', 'FLOAT'),
        ('total_liabilities', 'FLOAT'),
        ('retained_earnings', 'FLOAT'),
        ('ebit', 'FLOAT'),
        ('sales', 'FLOAT'),
        ('working_capital', 'FLOAT'),
        ('interest_expenses', 'FLOAT'),
        ('principal_payments', 'FLOAT'),
        ('sector', 'VARCHAR(32)'),
    ],
    'credit_requests': [
        ('currency', "VARCHAR(8) DEFAULT 'TRY'"),
    ],
    'audit_logs': [
        ('deleted_at', 'TIMESTAMP'),
    ],
    'batch_jobs': [],           # yeni tablo, create_all yönetir
    'openbanking_records': [],  # yeni tablo, create_all yönetir
    'credit_scores': [
        # Faz 4 — Altman, DSCR, volatility
        ('z_score', 'FLOAT'),
        ('z_score_note', 'VARCHAR(32)'),
        ('dscr_score', 'FLOAT'),
        ('volatility', 'FLOAT'),
        # Faz 4 — Piotroski, ICR, aging
        ('piotroski_score', 'INTEGER'),
        ('piotroski_grade', 'VARCHAR(8)'),
        ('icr_score', 'FLOAT'),
        ('aging_concentration', 'FLOAT'),
        # Faz 4 — Vade
        ('vade_days', 'INTEGER'),
        ('vade_message', 'VARCHAR(128)'),
        # Faz 5 — KKB
        ('kkb_veto', 'VARCHAR(50)'),
        ('kkb_enriched', 'BOOLEAN'),
        # Faz 4 — assessment/summary/scenarios (pre-Faz-4 DBs may be missing these)
        ('assessment', 'TEXT'),
        ('decision_summary', 'TEXT'),
        ('scenarios_json', 'TEXT'),
        # Faz 5 — IFRS 9 / Basel III
        ('ifrs9_stage', 'INTEGER'),
        ('ifrs9_pd', 'FLOAT'),
        ('ifrs9_lgd', 'FLOAT'),
        ('ifrs9_ead', 'FLOAT'),
        ('ifrs9_ecl', 'FLOAT'),
        ('ifrs9_rwa', 'FLOAT'),
        ('ifrs9_capital_req', 'FLOAT'),
        # ML Overlay
        ('ml_pd', 'FLOAT'),
        ('ob_enriched', 'BOOLEAN'),
    ],
}


def _table_columns(conn, table):
    """Fresh column list for a table (avoids stale inspector cache after ALTER)."""
    return {c['name'] for c in inspect(conn).get_columns(table)}


def _run_lightweight_migrations(engine):
    """Add missing columns to existing tables and backfill default tenant.

    Safe to run on every startup: each step re-reads the current schema.
    """
    with engine.begin() as conn:
        existing_tables = set(inspect(conn).get_table_names())

        for table, cols in _PENDING_COLUMNS.items():
            if table not in existing_tables:
                continue
            current = _table_columns(conn, table)
            for col_name, col_type in cols:
                if col_name not in current:
                    try:
                        conn.execute(text(f'ALTER TABLE {table} ADD COLUMN {col_name} {col_type}'))
                        logger.info(f'Migration: added {table}.{col_name}')
                    except Exception as e:
                        logger.warning(f'Migration skip {table}.{col_name}: {e}')

        # Ensure default tenant exists and backfill NULL tenant_id rows.
        if 'tenants' in existing_tables:
            row = conn.execute(text('SELECT id FROM tenants WHERE id = 1')).first()
            if not row:
                conn.execute(text(
                    "INSERT INTO tenants (id, name, slug, is_active, created_at) "
                    "VALUES (1, 'Default', 'default', :active, :ts)"
                ), {'active': True, 'ts': datetime.utcnow()})
                logger.info('Migration: created default tenant id=1')

            for table in ('users', 'customers'):
                if table in existing_tables and 'tenant_id' in _table_columns(conn, table):
                    conn.execute(text(f'UPDATE {table} SET tenant_id = 1 WHERE tenant_id IS NULL'))

def _ensure_session_registry():
    global _Session
    if _Session is None:
        _Session = scoped_session(sessionmaker(bind=get_engine(), expire_on_commit=False))
    return _Session

def get_session():
    """Return a thread-local session bound to the singleton scoped_session registry."""
    return _ensure_session_registry()()

def remove_session():
    """Tear down the thread-local session — bağla teardown_appcontext."""
    if _Session is not None:
        _Session.remove()