"""
ML Overlay yönetim rotaları — sadece admin erişebilir.

GET  /ml/panel      → model bilgi paneli
POST /ml/train      → modeli yeniden eğit
GET  /ml/info       → model meta JSON
"""
from flask import Blueprint, render_template, redirect, url_for, flash, jsonify
from flask_login import login_required

from routes.auth import admin_required

ml_bp = Blueprint('ml', __name__, url_prefix='/ml')


@ml_bp.route('/panel')
@login_required
@admin_required
def panel():
    import ml_overlay
    info = ml_overlay.get_info()
    ready = ml_overlay.is_ready()
    return render_template('ml_panel.html', info=info, ready=ready)


@ml_bp.route('/train', methods=['POST'])
@login_required
@admin_required
def train():
    from database import get_session
    import ml_overlay

    db = get_session()
    try:
        metrics = ml_overlay.train(db)
        ml_overlay.reload()
        flash(
            f"Model eğitildi: {metrics['model_type']} | "
            f"n={metrics['n_samples']} | acc={metrics['accuracy']} | "
            f"AUC={metrics.get('roc_auc', 'N/A')}",
            'success',
        )
    except ValueError as e:
        flash(str(e), 'error')
    except Exception as e:
        flash(f'Eğitim hatası: {e}', 'error')
    finally:
        db.close()

    return redirect(url_for('ml.panel'))


@ml_bp.route('/info')
@login_required
@admin_required
def info():
    import ml_overlay
    data = ml_overlay.get_info()
    return jsonify(data or {'status': 'model yok'})
