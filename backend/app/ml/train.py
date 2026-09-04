"""Trains the recovery-risk XGBoost model on synthetic data and saves artifacts.

Run with:  python -m app.ml.train

Outputs (both committed to the repo so it runs out of the box):
  app/ml/artifacts/recovery_risk_model.json  — the trained booster
  app/ml/artifacts/metrics.json              — evaluation metrics + metadata

Reminder: the training data is synthetic (see app/ml/synthetic_data.py).
This model demonstrates the ML pipeline; it is not a production financial
risk model.
"""

import json
from pathlib import Path

import xgboost as xgb
from sklearn.metrics import accuracy_score, log_loss, roc_auc_score
from sklearn.model_selection import train_test_split

from app.ml.features import FEATURE_NAMES
from app.ml.synthetic_data import RANDOM_SEED, generate_synthetic_dataset

ARTIFACT_DIR = Path(__file__).parent / "artifacts"
MODEL_PATH = ARTIFACT_DIR / "recovery_risk_model.json"
METRICS_PATH = ARTIFACT_DIR / "metrics.json"


def train() -> dict:
    df = generate_synthetic_dataset(n_rows=4000, seed=RANDOM_SEED)
    X = df[FEATURE_NAMES]
    y = df["recovered"]

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=RANDOM_SEED, stratify=y
    )

    model = xgb.XGBClassifier(
        n_estimators=200,
        max_depth=4,
        learning_rate=0.05,
        subsample=0.8,
        colsample_bytree=0.8,
        eval_metric="logloss",
        random_state=RANDOM_SEED,
    )
    model.fit(X_train, y_train)

    y_pred_proba = model.predict_proba(X_test)[:, 1]
    y_pred = model.predict(X_test)

    metrics = {
        "auc": round(float(roc_auc_score(y_test, y_pred_proba)), 4),
        "accuracy": round(float(accuracy_score(y_test, y_pred)), 4),
        "log_loss": round(float(log_loss(y_test, y_pred_proba)), 4),
        "n_train": int(len(X_train)),
        "n_test": int(len(X_test)),
        "positive_rate": round(float(y.mean()), 4),
        "feature_names": FEATURE_NAMES,
        "random_seed": RANDOM_SEED,
        "note": "Trained on synthetic data (app/ml/synthetic_data.py) — not a production financial model.",
    }

    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    model.save_model(str(MODEL_PATH))
    METRICS_PATH.write_text(json.dumps(metrics, indent=2) + "\n")

    return metrics


if __name__ == "__main__":
    result = train()
    print(json.dumps(result, indent=2))
