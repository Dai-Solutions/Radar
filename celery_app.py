"""
Celery factory — Redis broker + backend.

Kullanım:
  celery -A celery_app.celery worker --loglevel=info

Geliştirme ortamında Redis yoksa CELERY_ALWAYS_EAGER=true ile
görevler senkron çalışır.
"""
import os
from celery import Celery

REDIS_URL = os.getenv('REDIS_URL', 'redis://localhost:6379/0')
ALWAYS_EAGER = os.getenv('CELERY_ALWAYS_EAGER', 'false').lower() == 'true'


def make_celery(app=None):
    celery = Celery(
        'radar',
        broker=REDIS_URL,
        backend=REDIS_URL,
        include=['tasks'],
    )
    celery.conf.update(
        task_serializer='json',
        result_serializer='json',
        accept_content=['json'],
        timezone='Europe/Istanbul',
        enable_utc=True,
        task_always_eager=ALWAYS_EAGER,
        task_eager_propagates=True,
        broker_connection_retry_on_startup=True,
    )
    if app is not None:
        class ContextTask(celery.Task):
            def __call__(self, *args, **kwargs):
                with app.app_context():
                    return super().__call__(*args, **kwargs)
        celery.Task = ContextTask
    return celery


celery = make_celery()
