"""
Webhook System
Phase 10: Integration & Event-Driven Architecture
"""

from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from database import Base, get_session
from datetime import datetime
import requests
import json
import logging
import time
from functools import wraps

# Retry policy: 3 attempt, exponential backoff (1s, 2s, 4s).
# 5xx ve network hatalarında retry; 4xx (client error) tek deneme.
WEBHOOK_MAX_ATTEMPTS = 3
WEBHOOK_BACKOFF_BASE = 1.0


def _post_with_retry(url, payload, headers, timeout=10):
    """Webhook POST + exponential backoff retry. Son response veya raise eden Exception döner."""
    last_exc = None
    last_resp = None
    for attempt in range(1, WEBHOOK_MAX_ATTEMPTS + 1):
        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=timeout)
            last_resp = resp
            # 5xx → retry; 2xx/3xx/4xx → final
            if resp.status_code < 500:
                return resp, None
        except requests.RequestException as e:
            last_exc = e
        if attempt < WEBHOOK_MAX_ATTEMPTS:
            time.sleep(WEBHOOK_BACKOFF_BASE * (2 ** (attempt - 1)))
    return last_resp, last_exc

logger = logging.getLogger(__name__)

class Webhook(Base):
    """Webhook configuration"""
    __tablename__ = 'webhooks'
    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey('tenants.id'), nullable=False)
    url = Column(String, nullable=False)
    event_type = Column(String, nullable=False)  # score.created, customer.updated, etc.
    active = Column(Boolean, default=True)
    secret = Column(String)  # For HMAC verification
    headers = Column(Text)  # JSON-encoded custom headers
    created_at = Column(DateTime, default=datetime.utcnow)
    last_triggered = Column(DateTime)
    failure_count = Column(Integer, default=0)
    
    tenant = relationship("Tenant")

class WebhookEvent(Base):
    """Webhook event log"""
    __tablename__ = 'webhook_events'
    id = Column(Integer, primary_key=True)
    webhook_id = Column(Integer, ForeignKey('webhooks.id'), nullable=False)
    event_type = Column(String, nullable=False)
    payload = Column(Text)  # JSON event data
    response_status = Column(Integer)
    response_body = Column(Text)
    error_message = Column(String)
    triggered_at = Column(DateTime, default=datetime.utcnow)
    
    webhook = relationship("Webhook")


class WebhookManager:
    """Manage webhooks and trigger events"""
    
    EVENTS = {
        'score.created': 'Credit score created',
        'score.updated': 'Credit score updated',
        'score.approved': 'Credit score approved',
        'customer.created': 'New customer created',
        'customer.updated': 'Customer updated',
        'customer.deleted': 'Customer deleted',
        'batch.completed': 'Batch scoring completed',
    }
    
    @staticmethod
    def register_webhook(tenant_id, url, event_type, secret=None, custom_headers=None):
        """Register new webhook"""
        session = get_session()
        
        webhook = Webhook(
            tenant_id=tenant_id,
            url=url,
            event_type=event_type,
            secret=secret,
            headers=json.dumps(custom_headers) if custom_headers else None
        )
        
        session.add(webhook)
        session.commit()
        session.close()
        
        return webhook
    
    @staticmethod
    def trigger_event(event_type, tenant_id, data, source_user_id=None):
        """Trigger webhook events"""
        session = get_session()
        
        webhooks = session.query(Webhook).filter(
            Webhook.tenant_id == tenant_id,
            Webhook.event_type == event_type,
            Webhook.active == True
        ).all()
        
        for webhook in webhooks:
            try:
                payload = {
                    'event': event_type,
                    'timestamp': datetime.utcnow().isoformat(),
                    'data': data,
                    'source_user_id': source_user_id
                }
                
                headers = {'Content-Type': 'application/json'}
                if webhook.headers:
                    headers.update(json.loads(webhook.headers))
                
                # Add HMAC signature if secret provided
                if webhook.secret:
                    import hmac
                    import hashlib
                    payload_str = json.dumps(payload)
                    signature = hmac.new(
                        webhook.secret.encode(),
                        payload_str.encode(),
                        hashlib.sha256
                    ).hexdigest()
                    headers['X-Webhook-Signature'] = signature
                
                response, exc = _post_with_retry(webhook.url, payload, headers, timeout=10)

                if exc is not None:
                    logger.error(f'Webhook {webhook.id} failed after retries: {exc}')
                    webhook.failure_count += 1
                    event_log = WebhookEvent(
                        webhook_id=webhook.id,
                        event_type=event_type,
                        payload=json.dumps(payload),
                        response_status=None,
                        response_body=None,
                        error_message=str(exc),
                    )
                else:
                    event_log = WebhookEvent(
                        webhook_id=webhook.id,
                        event_type=event_type,
                        payload=json.dumps(payload),
                        response_status=response.status_code,
                        response_body=response.text,
                        error_message=None,
                    )
                    if response.status_code >= 400:
                        webhook.failure_count += 1
                        if webhook.failure_count >= 5:
                            webhook.active = False
                            logger.warning(f'Webhook {webhook.id} disabled after {webhook.failure_count} failures')
                    else:
                        webhook.failure_count = 0

                webhook.last_triggered = datetime.utcnow()
                session.add(event_log)
                session.commit()
            except Exception as e:
                logger.exception(f'Webhook {webhook.id} unexpected failure: {e}')
                session.rollback()

        session.close()
    
    @staticmethod
    def get_webhooks(tenant_id):
        """Get webhooks for tenant"""
        session = get_session()
        webhooks = session.query(Webhook).filter(
            Webhook.tenant_id == tenant_id
        ).all()
        session.close()
        return webhooks
    
    @staticmethod
    def delete_webhook(webhook_id):
        """Delete webhook"""
        session = get_session()
        webhook = session.query(Webhook).filter(Webhook.id == webhook_id).first()
        if webhook:
            session.delete(webhook)
            session.commit()
        session.close()


def trigger_webhook(event_type):
    """Decorator for functions that trigger webhooks"""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            result = f(*args, **kwargs)
            
            # Extract tenant_id and user_id from context
            from flask import g
            tenant_id = getattr(g, 'user').tenant_id if hasattr(g, 'user') and g.user else None
            user_id = getattr(g, 'user').id if hasattr(g, 'user') and g.user else None
            
            if tenant_id and result:
                # Determine payload based on result type
                if isinstance(result, dict):
                    data = result
                else:
                    data = {'id': getattr(result, 'id', None)}
                
                WebhookManager.trigger_event(event_type, tenant_id, data, user_id)
            
            return result
        return decorated_function
    return decorator
