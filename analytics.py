"""
Analytics Engine & Real-time Dashboards
Phase 11: Analytics & BI
"""

from datetime import datetime, timedelta
from sqlalchemy import func
from database import get_session, Customer, CreditScore, CreditRequest, AuditLog
import json

class AnalyticsEngine:
    """Real-time analytics and metrics"""
    
    def __init__(self, tenant_id):
        self.tenant_id = tenant_id
        self.session = get_session()
    
    def get_kpi_metrics(self, date_from=None, date_to=None):
        """Get real-time KPI metrics"""
        if not date_from:
            date_from = datetime.utcnow() - timedelta(days=30)
        if not date_to:
            date_to = datetime.utcnow()
        
        metrics = {}
        
        # Total customers
        metrics['total_customers'] = self.session.query(Customer).filter(
            Customer.tenant_id == self.tenant_id
        ).count()
        
        # Scores calculated (in period)
        metrics['total_scores_calculated'] = self.session.query(CreditScore).filter(
            CreditScore.calculated_at >= date_from,
            CreditScore.calculated_at <= date_to
        ).count()
        
        # Average score
        avg_score = self.session.query(func.avg(CreditScore.final_score)).filter(
            CreditScore.calculated_at >= date_from,
            CreditScore.calculated_at <= date_to
        ).scalar()
        metrics['avg_score'] = float(avg_score) if avg_score else 0
        
        # Risk distribution (A/B/C)
        risk_dist = self.session.query(
            CreditScore.credit_note,
            func.count(CreditScore.id)
        ).filter(
            CreditScore.calculated_at >= date_from,
            CreditScore.calculated_at <= date_to
        ).group_by(CreditScore.credit_note).all()
        
        metrics['risk_distribution'] = {
            note: count for note, count in (risk_dist or [])
        }
        
        # Daily volume (scoring activity)
        daily_volumes = self.session.query(
            func.date(CreditScore.calculated_at).label('date'),
            func.count(CreditScore.id).label('count')
        ).filter(
            CreditScore.calculated_at >= date_from,
            CreditScore.calculated_at <= date_to
        ).group_by(func.date(CreditScore.calculated_at)).order_by('date').all()
        
        metrics['daily_volume'] = [
            {'date': str(date), 'count': count} 
            for date, count in (daily_volumes or [])
        ]
        
        # Sector distribution
        sector_dist = self.session.query(
            Customer.sector,
            func.count(Customer.id)
        ).filter(
            Customer.tenant_id == self.tenant_id
        ).group_by(Customer.sector).all()
        
        metrics['sector_distribution'] = {
            sector: count for sector, count in (sector_dist or [])
        }
        
        # Top risk customers
        top_risks = self.session.query(
            Customer.account_code,
            Customer.account_name,
            CreditScore.final_score,
            CreditScore.credit_note
        ).join(CreditScore, Customer.id == CreditScore.customer_id).filter(
            Customer.tenant_id == self.tenant_id
        ).order_by(CreditScore.final_score).limit(10).all()
        
        metrics['top_risk_customers'] = [
            {
                'code': code,
                'name': name,
                'score': float(score),
                'note': note
            }
            for code, name, score, note in (top_risks or [])
        ]
        
        return metrics
    
    def get_customer_trends(self, customer_id, months=12):
        """Get scoring trends for a customer"""
        start_date = datetime.utcnow() - timedelta(days=30*months)
        
        scores = self.session.query(
            func.date_trunc('month', CreditScore.calculated_at).label('month'),
            func.avg(CreditScore.final_score).label('avg_score'),
            func.count(CreditScore.id).label('count')
        ).filter(
            CreditScore.customer_id == customer_id,
            CreditScore.calculated_at >= start_date
        ).group_by(func.date_trunc('month', CreditScore.calculated_at)).order_by('month').all()
        
        return [
            {
                'month': str(month),
                'avg_score': float(avg_score),
                'count': count
            }
            for month, avg_score, count in (scores or [])
        ]
    
    def export_to_csv(self, entity_type='customers', filters=None):
        """Export data as CSV"""
        import csv
        import io
        
        output = io.StringIO()
        writer = None
        
        if entity_type == 'customers':
            customers = self.session.query(Customer).filter(
                Customer.tenant_id == self.tenant_id
            ).all()
            
            if customers:
                fieldnames = [
                    'account_code', 'account_name', 'email', 'phone',
                    'sector', 'equity', 'total_assets', 'created_at'
                ]
                writer = csv.DictWriter(output, fieldnames=fieldnames)
                writer.writeheader()
                
                for customer in customers:
                    writer.writerow({
                        'account_code': customer.account_code,
                        'account_name': customer.account_name,
                        'email': customer.email,
                        'phone': customer.phone,
                        'sector': customer.sector,
                        'equity': customer.equity,
                        'total_assets': customer.total_assets,
                        'created_at': customer.created_at.isoformat()
                    })
        
        elif entity_type == 'scores':
            scores = self.session.query(CreditScore).filter(
                CreditScore.customer_id == Customer.id,
                Customer.tenant_id == self.tenant_id
            ).all()
            
            if scores:
                fieldnames = [
                    'customer_code', 'final_score', 'credit_note', 'z_score',
                    'dscr_score', 'recommendation', 'calculated_at'
                ]
                writer = csv.DictWriter(output, fieldnames=fieldnames)
                writer.writeheader()
                
                for score in scores:
                    writer.writerow({
                        'customer_code': score.customer.account_code if score.customer else '',
                        'final_score': score.final_score,
                        'credit_note': score.credit_note,
                        'z_score': score.z_score,
                        'dscr_score': score.dscr_score,
                        'recommendation': score.decision_summary,
                        'calculated_at': score.calculated_at.isoformat()
                    })
        
        output.seek(0)
        return output.getvalue()
    
    def export_to_json(self, entity_type='kpis'):
        """Export data as JSON"""
        if entity_type == 'kpis':
            return json.dumps(self.get_kpi_metrics(), indent=2, default=str)
        
        elif entity_type == 'customers':
            customers = self.session.query(Customer).filter(
                Customer.tenant_id == self.tenant_id
            ).all()
            
            data = [
                {
                    'id': c.id,
                    'account_code': c.account_code,
                    'account_name': c.account_name,
                    'sector': c.sector,
                    'email': c.email,
                    'created_at': c.created_at.isoformat()
                }
                for c in customers
            ]
            
            return json.dumps(data, indent=2, default=str)
        
        return json.dumps({})
    
    def get_audit_trail(self, entity_type=None, limit=100):
        """Get audit trail for compliance"""
        query = self.session.query(AuditLog).filter(
            AuditLog.tenant_id == self.tenant_id
        )
        
        if entity_type:
            query = query.filter(AuditLog.entity_type == entity_type)
        
        logs = query.order_by(AuditLog.timestamp.desc()).limit(limit).all()
        
        return [
            {
                'id': log.id,
                'user_id': log.user_id,
                'action': log.action,
                'entity_type': log.entity_type,
                'entity_id': log.entity_id,
                'status': log.status,
                'timestamp': log.timestamp.isoformat()
            }
            for log in logs
        ]
    
    def close(self):
        """Close session"""
        self.session.close()


# Dashboard widgets
class DashboardWidget:
    """Base dashboard widget"""
    
    def __init__(self, title, widget_type):
        self.title = title
        self.type = widget_type
        self.data = {}
    
    def to_dict(self):
        return {
            'title': self.title,
            'type': self.type,
            'data': self.data
        }


class KPIWidget(DashboardWidget):
    """KPI card widget"""
    
    def __init__(self, title, value, unit='', trend=None):
        super().__init__(title, 'kpi')
        self.data = {
            'value': value,
            'unit': unit,
            'trend': trend
        }


class ChartWidget(DashboardWidget):
    """Chart widget (line, bar, etc.)"""
    
    def __init__(self, title, chart_type, labels, datasets):
        super().__init__(title, 'chart')
        self.data = {
            'chart_type': chart_type,
            'labels': labels,
            'datasets': datasets
        }
