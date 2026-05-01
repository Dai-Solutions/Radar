"""
API Documentation & OpenAPI/Swagger Integration
Using Flasgger for auto-documentation
"""

from flasgger import Swagger
from flask import Blueprint

def init_swagger(app):
    """Initialize Swagger/OpenAPI documentation"""
    swagger = Swagger(app, template={
        "swagger": "2.0",
        "info": {
            "title": "Radar Credit Scoring API",
            "description": "Enterprise credit scoring and customer management API",
            "version": "2.0.0",
            "contact": {
                "name": "DAI Softwares",
                "url": "https://daisoftwares.com"
            }
        },
        "basePath": "/api/v1",
        "schemes": ["https"],
        "securityDefinitions": {
            "Bearer": {
                "type": "apiKey",
                "name": "Authorization",
                "in": "header",
                "description": "JWT token (Bearer token)"
            }
        },
        "tags": [
            {"name": "Auth", "description": "Authentication endpoints"},
            {"name": "Customers", "description": "Customer management"},
            {"name": "Scoring", "description": "Credit scoring operations"},
            {"name": "Admin", "description": "Administrative operations"},
            {"name": "Analytics", "description": "Analytics & reporting"},
            {"name": "Webhooks", "description": "Webhook management"}
        ]
    })
    
    return swagger

# API Blueprint Templates
api_bp = Blueprint('api', __name__, url_prefix='/api/v1')

# ============================================================================
# API ENDPOINT SPECIFICATIONS (Flasgger decorators)
# ============================================================================

API_SPECS = {
    'customers_list': {
        'tags': ['Customers'],
        'summary': 'List customers',
        'description': 'Get paginated list of customers for the current tenant',
        'parameters': [
            {'name': 'page', 'in': 'query', 'type': 'integer', 'default': 1},
            {'name': 'per_page', 'in': 'query', 'type': 'integer', 'default': 20},
            {'name': 'search', 'in': 'query', 'type': 'string', 'description': 'Search by account code or name'},
            {'name': 'sector', 'in': 'query', 'type': 'string', 'description': 'Filter by sector'}
        ],
        'responses': {
            200: {
                'description': 'Success',
                'schema': {
                    'type': 'object',
                    'properties': {
                        'data': {'type': 'array'},
                        'total': {'type': 'integer'},
                        'page': {'type': 'integer'},
                        'per_page': {'type': 'integer'}
                    }
                }
            },
            401: {'description': 'Unauthorized'},
            403: {'description': 'Forbidden'}
        },
        'security': [{'Bearer': []}]
    },
    
    'customer_create': {
        'tags': ['Customers'],
        'summary': 'Create customer',
        'description': 'Create a new customer record',
        'parameters': [
            {
                'name': 'body',
                'in': 'body',
                'required': True,
                'schema': {
                    'type': 'object',
                    'required': ['account_code', 'account_name'],
                    'properties': {
                        'account_code': {'type': 'string'},
                        'account_name': {'type': 'string'},
                        'tax_no': {'type': 'string'},
                        'sector': {'type': 'string', 'enum': ['general', 'retail', 'manufacturing', 'services']},
                        'email': {'type': 'string', 'format': 'email'},
                        'phone': {'type': 'string'}
                    }
                }
            }
        ],
        'responses': {
            201: {'description': 'Created'},
            400: {'description': 'Bad request'},
            401: {'description': 'Unauthorized'},
            403: {'description': 'Forbidden'}
        },
        'security': [{'Bearer': []}]
    },
    
    'scoring_calculate': {
        'tags': ['Scoring'],
        'summary': 'Calculate credit score',
        'description': 'Execute credit scoring for a customer',
        'parameters': [
            {
                'name': 'body',
                'in': 'body',
                'required': True,
                'schema': {
                    'type': 'object',
                    'required': ['customer_id', 'request_amount'],
                    'properties': {
                        'customer_id': {'type': 'integer'},
                        'request_amount': {'type': 'number'},
                        'currency': {'type': 'string', 'default': 'TL', 'enum': ['TL', 'USD', 'EUR']},
                        'period': {'type': 'string', 'description': 'Aging data period (YYYY-MM)'}
                    }
                }
            }
        ],
        'responses': {
            200: {
                'description': 'Success - Score calculated',
                'schema': {
                    'type': 'object',
                    'properties': {
                        'final_score': {'type': 'number'},
                        'credit_note': {'type': 'string'},
                        'recommended_limit': {'type': 'number'},
                        'z_score': {'type': 'number'},
                        'dscr_score': {'type': 'number'}
                    }
                }
            },
            400: {'description': 'Bad request'},
            401: {'description': 'Unauthorized'},
            403: {'description': 'Forbidden'}
        },
        'security': [{'Bearer': []}]
    },
    
    'analytics_kpis': {
        'tags': ['Analytics'],
        'summary': 'Get KPI metrics',
        'description': 'Retrieve real-time KPI metrics for dashboard',
        'parameters': [
            {'name': 'date_from', 'in': 'query', 'type': 'string', 'format': 'date'},
            {'name': 'date_to', 'in': 'query', 'type': 'string', 'format': 'date'}
        ],
        'responses': {
            200: {
                'description': 'Success',
                'schema': {
                    'type': 'object',
                    'properties': {
                        'total_customers': {'type': 'integer'},
                        'total_scores_calculated': {'type': 'integer'},
                        'avg_score': {'type': 'number'},
                        'risk_distribution': {'type': 'object'},
                        'daily_volume': {'type': 'array'}
                    }
                }
            }
        },
        'security': [{'Bearer': []}]
    },
    
    'webhooks_list': {
        'tags': ['Webhooks'],
        'summary': 'List webhooks',
        'description': 'Get configured webhooks for tenant',
        'responses': {
            200: {'description': 'Success', 'schema': {'type': 'array'}},
            401: {'description': 'Unauthorized'}
        },
        'security': [{'Bearer': []}]
    },
    
    'webhooks_register': {
        'tags': ['Webhooks'],
        'summary': 'Register webhook',
        'description': 'Register new webhook for events',
        'parameters': [
            {
                'name': 'body',
                'in': 'body',
                'required': True,
                'schema': {
                    'type': 'object',
                    'required': ['url', 'event_type'],
                    'properties': {
                        'url': {'type': 'string', 'format': 'uri'},
                        'event_type': {'type': 'string', 'enum': ['score.created', 'score.updated', 'customer.created', 'customer.updated']},
                        'active': {'type': 'boolean', 'default': True}
                    }
                }
            }
        ],
        'responses': {
            201: {'description': 'Created'},
            400: {'description': 'Bad request'},
            401: {'description': 'Unauthorized'}
        },
        'security': [{'Bearer': []}]
    }
}

def get_api_spec(endpoint_name):
    """Get API specification for endpoint"""
    return API_SPECS.get(endpoint_name, {})
