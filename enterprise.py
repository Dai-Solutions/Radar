"""
Enterprise Features:
- Multi-tenant context & routing
- RBAC (Role-Based Access Control)
- Audit logging
"""

from functools import wraps
from flask import request, g, abort, jsonify
from datetime import datetime
from database import get_session, Tenant, AuditLog, User, UserRole, Role
import json
import logging

logger = logging.getLogger(__name__)

# ============================================================================
# MULTI-TENANT CONTEXT
# ============================================================================

def get_current_tenant():
    """Get current tenant from request context"""
    if not hasattr(g, 'current_tenant'):
        # Try from subdomain, URL parameter, or session
        tenant_id = request.args.get('tenant_id')
        if not tenant_id and hasattr(g, 'user') and g.user:
            tenant_id = g.user.tenant_id
        
        if tenant_id:
            session = get_session()
            tenant = session.query(Tenant).filter(Tenant.id == tenant_id).first()
            g.current_tenant = tenant
        else:
            g.current_tenant = None
    
    return g.current_tenant

def require_tenant(f):
    """Decorator: require active tenant"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        tenant = get_current_tenant()
        if not tenant or not tenant.is_active:
            return jsonify({'error': 'Invalid or inactive tenant'}), 403
        return f(*args, **kwargs)
    return decorated_function

# ============================================================================
# RBAC (Role-Based Access Control)
# ============================================================================

PERMISSION_GROUPS = {
    'customer': ['view', 'create', 'edit', 'delete', 'export'],
    'scoring': ['view', 'execute', 'edit_rules', 'export'],
    'admin': ['manage_users', 'manage_roles', 'view_audit', 'system_config'],
    'reporting': ['view_dashboard', 'export_reports', 'schedule_exports'],
}

ROLE_PERMISSIONS = {
    'admin': {
        'customer': ['view', 'create', 'edit', 'delete', 'export'],
        'scoring': ['view', 'execute', 'edit_rules', 'export'],
        'admin': ['manage_users', 'manage_roles', 'view_audit', 'system_config'],
        'reporting': ['view_dashboard', 'export_reports', 'schedule_exports'],
    },
    'credit_manager': {
        'customer': ['view', 'create', 'edit', 'export'],
        'scoring': ['view', 'execute', 'export'],
        'reporting': ['view_dashboard', 'export_reports'],
    },
    'analyst': {
        'customer': ['view', 'export'],
        'scoring': ['view', 'execute'],
        'reporting': ['view_dashboard'],
    },
    'approver': {
        'scoring': ['view'],
        'reporting': ['view_dashboard'],
    },
    'viewer': {
        'customer': ['view'],
        'reporting': ['view_dashboard'],
    },
}

def get_user_permissions(user):
    """Get all permissions for a user"""
    if not user:
        return {}
    
    session = get_session()
    user_roles = session.query(UserRole).filter(UserRole.user_id == user.id).all()
    
    permissions = {}
    for user_role in user_roles:
        role = user_role.role
        if role.name in ROLE_PERMISSIONS:
            for module, perms in ROLE_PERMISSIONS[role.name].items():
                if module not in permissions:
                    permissions[module] = []
                permissions[module].extend(perms)
    
    # Remove duplicates
    for module in permissions:
        permissions[module] = list(set(permissions[module]))
    
    return permissions

def has_permission(user, module, action):
    """Check if user has specific permission"""
    permissions = get_user_permissions(user)
    return action in permissions.get(module, [])

def require_permission(module, action):
    """Decorator: require specific permission"""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not hasattr(g, 'user') or not g.user:
                abort(401)
            
            if not has_permission(g.user, module, action):
                log_audit_action(
                    tenant_id=g.user.tenant_id,
                    user_id=g.user.id,
                    action='permission_denied',
                    entity_type=module,
                    status='failure',
                    error_message=f'Missing permission: {module}.{action}'
                )
                abort(403)
            
            return f(*args, **kwargs)
        return decorated_function
    return decorator

# ============================================================================
# AUDIT LOGGING
# ============================================================================

def log_audit_action(tenant_id, user_id, action, entity_type, entity_id=None, 
                     changes=None, status='success', error_message=None):
    """Log an action for compliance"""
    try:
        session = get_session()
        
        changes_json = json.dumps(changes) if changes else None
        
        log_entry = AuditLog(
            tenant_id=tenant_id,
            user_id=user_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            changes=changes_json,
            ip_address=request.remote_addr if request else None,
            user_agent=request.user_agent.string if request else None,
            status=status,
            error_message=error_message,
            timestamp=datetime.utcnow()
        )
        
        session.add(log_entry)
        session.commit()
        session.close()
    except Exception as e:
        logger.error(f'Audit log error: {str(e)}')

def log_customer_action(action, customer_id, user_id, tenant_id, changes=None):
    """Log customer-related action"""
    log_audit_action(
        tenant_id=tenant_id,
        user_id=user_id,
        action=action,
        entity_type='Customer',
        entity_id=customer_id,
        changes=changes,
        status='success'
    )

def log_scoring_action(action, credit_score_id, user_id, tenant_id, customer_id=None, changes=None):
    """Log scoring-related action"""
    log_audit_action(
        tenant_id=tenant_id,
        user_id=user_id,
        action=action,
        entity_type='CreditScore',
        entity_id=credit_score_id,
        changes=changes,
        status='success'
    )

def get_audit_logs(tenant_id, entity_type=None, user_id=None, limit=100):
    """Retrieve audit logs for compliance"""
    session = get_session()
    query = session.query(AuditLog).filter(AuditLog.tenant_id == tenant_id)
    
    if entity_type:
        query = query.filter(AuditLog.entity_type == entity_type)
    if user_id:
        query = query.filter(AuditLog.user_id == user_id)
    
    logs = query.order_by(AuditLog.timestamp.desc()).limit(limit).all()
    session.close()
    
    return logs

# ============================================================================
# INITIALIZATION
# ============================================================================

def init_enterprise_features(app):
    """Initialize RBAC roles and default permissions"""
    session = get_session()
    
    # Create default roles if they don't exist
    default_roles = {
        'admin': 'System Administrator - Full access',
        'credit_manager': 'Credit Manager - Manage credit processes',
        'analyst': 'Credit Analyst - View and execute scoring',
        'approver': 'Credit Approver - Approve credit decisions',
        'viewer': 'Viewer - Read-only access',
    }
    
    for role_name, description in default_roles.items():
        existing = session.query(Role).filter(Role.name == role_name).first()
        if not existing:
            permissions = json.dumps(ROLE_PERMISSIONS.get(role_name, {}))
            role = Role(name=role_name, description=description, permissions=permissions)
            session.add(role)
    
    session.commit()
    session.close()
    
    logger.info('Enterprise features initialized')
