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
    
    calculated_at = Column(DateTime, default=datetime.utcnow)
    
    customer = relationship("Customer")
    request = relationship("CreditRequest", back_populates="score_result")

class Feedback(Base):
    __tablename__ = 'feedbacks'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    message = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    user = relationship("User")

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
    engine = get_engine()
    Base.metadata.create_all(engine)
    _run_lightweight_migrations(engine)
    return engine


# Columns added by Phase 8/9 that may be missing on pre-2.0 databases.
# create_all() only creates new tables, so we ALTER existing ones in-place.
_PENDING_COLUMNS = {
    'users': [
        ('tenant_id', 'INTEGER'),
        ('language', 'VARCHAR(5)'),
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