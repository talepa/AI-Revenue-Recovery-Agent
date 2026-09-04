"""Inference for the (synthetic-data-trained) recovery-risk model.

See app/ml/train.py / app/ml/synthetic_data.py for training details and
the "not a production financial model" caveat.
"""

import functools
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import xgboost as xgb

from app.ml.features import FEATURE_NAMES, RiskFeatures
from app.models.enums import RiskLevel

MODEL_PATH = Path(__file__).parent / "artifacts" / "recovery_risk_model.json"

# risk_score = (1 - recovery_probability) * 100; thresholds chosen so the
# seed-data narrative's hand-authored scores (Northwind 22.5=LOW,
# Bluepeak/Sundial ~48-55=MEDIUM, Vertex 82=HIGH) land in the same bands
# the model would assign, keeping demo and model-scored cases consistent.
LOW_RISK_MAX = 35.0
MEDIUM_RISK_MAX = 65.0


@dataclass
class RiskScore:
    risk_score: float  # 0-100, higher = riskier
    risk_level: RiskLevel
    recovery_probability: float  # 0-1


@functools.lru_cache(maxsize=1)
def _load_model() -> xgb.XGBClassifier:
    model = xgb.XGBClassifier()
    model.load_model(str(MODEL_PATH))
    return model


def score(features: RiskFeatures) -> RiskScore:
    model = _load_model()
    row = pd.DataFrame([features.to_row()], columns=FEATURE_NAMES)
    recovery_probability = float(model.predict_proba(row)[0][1])
    risk_score = round((1 - recovery_probability) * 100, 2)

    if risk_score < LOW_RISK_MAX:
        risk_level = RiskLevel.LOW
    elif risk_score < MEDIUM_RISK_MAX:
        risk_level = RiskLevel.MEDIUM
    else:
        risk_level = RiskLevel.HIGH

    return RiskScore(
        risk_score=risk_score,
        risk_level=risk_level,
        recovery_probability=round(recovery_probability, 4),
    )
