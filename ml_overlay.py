"""
ML Overlay — Logistic Regression / XGBoost temerrüt tahmini.

Kural tabanlı IFRS 9 PD değerine ML tahminini %35 ağırlıkla karıştırır.
Yeterli eğitim verisi yoksa (MIN_SAMPLES) tamamen kural tabanlı kalır.

Eğitim kaynağı: credit_scores tablosu
Hedef (y): ifrs9_stage >= 3  → temerrüt = 1, değil = 0
           Sahte etiket yedek: final_score < 40 (stage hiç kaydedilmemişse)

Model seçimi:
  - n_samples < 200  → LogisticRegression
  - n_samples >= 200 → XGBoostClassifier (daha iyi kalibrasyon)

Model dosyası: data/ml_model.pkl
"""

import os
import pickle
import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

MODEL_PATH = os.path.join(os.path.dirname(__file__), 'data', 'ml_model.pkl')
MIN_SAMPLES = 30          # eğitim için minimum kayıt
ML_BLEND_WEIGHT = 0.35    # ML katkısı: blended_pd = (1-w)*rule_pd + w*ml_pd

FEATURES = [
    'final_score',
    'historical_score',
    'future_score',
    'z_score',
    'dscr_score',
    'volatility',
    'piotroski_score',
    'icr_score',
    'aging_concentration',
    'avg_delay_days',
]


# ──────────────────────────────────────────────────────────────────
# Model yükleme / kaydetme yardımcıları
# ──────────────────────────────────────────────────────────────────

def _load_model() -> Optional[dict]:
    if not os.path.exists(MODEL_PATH):
        return None
    try:
        with open(MODEL_PATH, 'rb') as f:
            return pickle.load(f)
    except Exception as e:
        logger.warning('ML model yüklenemedi: %s', e)
        return None


def _save_model(bundle: dict):
    os.makedirs(os.path.dirname(MODEL_PATH), exist_ok=True)
    with open(MODEL_PATH, 'wb') as f:
        pickle.dump(bundle, f)


# ──────────────────────────────────────────────────────────────────
# Eğitim
# ──────────────────────────────────────────────────────────────────

def train(db_session) -> dict:
    """
    DB'deki credit_scores kayıtlarıyla modeli eğit.
    Returns: metrics dict (accuracy, roc_auc, n_samples, model_type, trained_at)
    """
    from database import CreditScore
    import numpy as np

    rows = db_session.query(CreditScore).all()
    if len(rows) < MIN_SAMPLES:
        raise ValueError(
            f'Yetersiz veri: {len(rows)} kayıt var, en az {MIN_SAMPLES} gerekli.'
        )

    X_list, y_list = [], []
    for r in rows:
        feat = [
            float(getattr(r, 'final_score') or 0),
            float(getattr(r, 'historical_score') or 0),
            float(getattr(r, 'future_score') or 0),
            float(getattr(r, 'z_score') or 0),
            float(getattr(r, 'dscr_score') or 0),
            float(getattr(r, 'volatility') or 0),
            float(getattr(r, 'piotroski_score') or 0),
            float(getattr(r, 'icr_score') or 0),
            float(getattr(r, 'aging_concentration') or 0),
            float(getattr(r, 'avg_delay_days') or 0),
        ]
        # Hedef: stage 3 veya düşük skor → temerrüt
        stage = getattr(r, 'ifrs9_stage', None)
        if stage is not None:
            y = 1 if stage >= 3 else 0
        else:
            y = 1 if feat[0] < 40 else 0  # sahte etiket yedek

        X_list.append(feat)
        y_list.append(y)

    X = np.array(X_list, dtype=float)
    y = np.array(y_list, dtype=int)

    # NaN / Inf temizle
    X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)

    from sklearn.model_selection import train_test_split
    from sklearn.preprocessing import StandardScaler
    from sklearn.metrics import roc_auc_score, accuracy_score
    from sklearn.linear_model import LogisticRegression

    # Sınıf dengesi (temerrüt genellikle az)
    n_pos = y.sum()
    n_neg = len(y) - n_pos
    if n_pos == 0 or n_neg == 0:
        raise ValueError('Eğitim setinde tek sınıf var — temerrüt çeşitliliği yetersiz.')

    # Yeterli veri varsa test split yap
    if len(y) >= 60:
        X_tr, X_te, y_tr, y_te = train_test_split(
            X, y, test_size=0.2, random_state=42, stratify=y
        )
    else:
        X_tr, X_te, y_tr, y_te = X, X, y, y

    scaler = StandardScaler()
    X_tr_s = scaler.fit_transform(X_tr)
    X_te_s = scaler.transform(X_te)

    model_type = 'LogisticRegression'
    if len(y) >= 200:
        try:
            from xgboost import XGBClassifier
            scale_pos = n_neg / max(1, n_pos)
            clf = XGBClassifier(
                n_estimators=100,
                max_depth=4,
                learning_rate=0.1,
                scale_pos_weight=scale_pos,
                eval_metric='logloss',
                verbosity=0,
                random_state=42,
            )
            # XGBoost ham X kullanır (scaler'a gerek yok ama tutarlılık için)
            clf.fit(X_tr, y_tr)
            proba = clf.predict_proba(X_te)[:, 1]
            model_type = 'XGBoost'
            use_scaler = False
        except Exception as e:
            logger.warning('XGBoost başarısız, LR fallback: %s', e)
            clf = None
    else:
        clf = None

    if clf is None or model_type == 'LogisticRegression':
        clf = LogisticRegression(
            class_weight='balanced',
            max_iter=500,
            random_state=42,
        )
        clf.fit(X_tr_s, y_tr)
        proba = clf.predict_proba(X_te_s)[:, 1]
        model_type = 'LogisticRegression'
        use_scaler = True

    y_pred = (proba >= 0.5).astype(int)
    acc = round(accuracy_score(y_te, y_pred), 4)
    auc = round(roc_auc_score(y_te, proba), 4) if len(set(y_te)) > 1 else None

    # Feature importance (LR: |coef|, XGBoost: feature_importances_)
    if model_type == 'LogisticRegression':
        importances = dict(zip(FEATURES, [round(abs(float(c)), 4) for c in clf.coef_[0]]))
    else:
        importances = dict(zip(FEATURES, [round(float(v), 4) for v in clf.feature_importances_]))

    bundle = {
        'model': clf,
        'scaler': scaler if use_scaler else None,
        'model_type': model_type,
        'use_scaler': use_scaler,
        'n_samples': len(y),
        'n_defaults': int(n_pos),
        'accuracy': acc,
        'roc_auc': auc,
        'importances': importances,
        'trained_at': datetime.utcnow().isoformat(),
    }
    _save_model(bundle)
    logger.info('ML model eğitildi: %s, n=%d, acc=%.3f, auc=%s',
                model_type, len(y), acc, auc)
    return {k: v for k, v in bundle.items() if k not in ('model', 'scaler')}


# ──────────────────────────────────────────────────────────────────
# Tahmin & Harmanlama
# ──────────────────────────────────────────────────────────────────

_bundle_cache: Optional[dict] = None


def _get_bundle() -> Optional[dict]:
    global _bundle_cache
    if _bundle_cache is None:
        _bundle_cache = _load_model()
    return _bundle_cache


def reload():
    """Disk'ten yeniden yükle (eğitim sonrası çağrılır)."""
    global _bundle_cache
    _bundle_cache = _load_model()


def is_ready() -> bool:
    b = _get_bundle()
    return b is not None and b.get('n_samples', 0) >= MIN_SAMPLES


def predict_pd(features: dict) -> float:
    """
    features: FEATURES anahtarlarını içeren dict.
    Returns: PD tahmini [0.0, 1.0]. Model yoksa -1.0 döner (sinyalsiz).
    """
    bundle = _get_bundle()
    if bundle is None:
        return -1.0

    import numpy as np
    x = np.array([[float(features.get(f, 0) or 0) for f in FEATURES]])
    x = np.nan_to_num(x, nan=0.0, posinf=0.0, neginf=0.0)

    try:
        clf = bundle['model']
        if bundle.get('use_scaler') and bundle['scaler'] is not None:
            x = bundle['scaler'].transform(x)
        pd_val = float(clf.predict_proba(x)[0][1])
        return round(pd_val, 4)
    except Exception as e:
        logger.warning('ML tahmin hatası: %s', e)
        return -1.0


def blend_pd(rule_pd: float, features: dict) -> tuple[float, bool]:
    """
    Kural tabanlı PD ile ML PD'yi harmanlıyor.
    Returns: (blended_pd, ml_adjusted)
    """
    ml_pd = predict_pd(features)
    if ml_pd < 0:
        return rule_pd, False
    blended = (1 - ML_BLEND_WEIGHT) * rule_pd + ML_BLEND_WEIGHT * ml_pd
    return round(blended, 4), True


def get_info() -> Optional[dict]:
    """Model meta bilgisi — route'larda kullanılır."""
    bundle = _get_bundle()
    if bundle is None:
        return None
    return {k: v for k, v in bundle.items() if k not in ('model', 'scaler')}
