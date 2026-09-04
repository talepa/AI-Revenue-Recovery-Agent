"""Synthetic training data for the recovery-risk model.

IMPORTANT: This data is entirely synthetic. There is no real-world
collections dataset behind it — no real customers, no real payment
outcomes. It exists so a portfolio project can demonstrate a working
ML training pipeline; the resulting model is NOT a production financial
risk model and must not be treated as one.

Generative process (documented so the model's behavior is explainable,
not a black box): each row's "recovered" label is a Bernoulli draw from
a probability computed as a logistic function of the 9 features, using
weights chosen by hand to encode plausible, directionally sensible
relationships (e.g. more days overdue -> lower recovery probability;
a longer track record of on-time payments -> higher). Gaussian noise is
added before the sigmoid so the relationship isn't perfectly learnable
and the label balance is drawn from realistic-looking feature ranges,
not real invoices.
"""

import numpy as np
import pandas as pd

from app.ml.features import FEATURE_NAMES

RANDOM_SEED = 42


def _sigmoid(z: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-z))


def generate_synthetic_dataset(n_rows: int = 4000, seed: int = RANDOM_SEED) -> pd.DataFrame:
    rng = np.random.default_rng(seed)

    invoice_amount = np.clip(rng.lognormal(mean=12.3, sigma=1.0, size=n_rows), 15_000, 5_000_000)
    days_overdue = np.clip(rng.gamma(shape=2.0, scale=15.0, size=n_rows), 1, 120).round().astype(int)

    # Fraction of the invoice still outstanding — most rows are fully unpaid,
    # a minority are partially paid.
    outstanding_fraction = np.where(rng.random(n_rows) < 0.85, 1.0, rng.uniform(0.2, 0.8, size=n_rows))
    outstanding_balance = invoice_amount * outstanding_fraction

    avg_historical_payment_delay = np.clip(rng.normal(loc=5.0, scale=9.0, size=n_rows), -10, 45)

    total_prior_invoices = rng.integers(2, 11, size=n_rows)
    # Customers with a higher average delay skew toward a higher late fraction.
    late_fraction = np.clip(_sigmoid((avg_historical_payment_delay - 5) / 8.0), 0.05, 0.95)
    num_prior_late_payments = np.round(total_prior_invoices * late_fraction).astype(int)
    num_prior_on_time_payments = total_prior_invoices - num_prior_late_payments

    customer_tenure_days = rng.integers(30, 1800, size=n_rows)

    # 20% of rows simulate a customer with no prior recovery-case history
    # (the real feature extractor uses 0.5 as a neutral prior in that case).
    has_track_record = rng.random(n_rows) >= 0.2
    prior_recovery_success_rate = np.where(
        has_track_record,
        rng.beta(a=3.0, b=2.0, size=n_rows),
        0.5,
    )

    num_open_invoices = np.clip(rng.poisson(lam=1.0, size=n_rows), 0, 6)

    z = (
        2.1
        - 0.032 * days_overdue
        - 0.28 * np.log1p(invoice_amount / 100_000)
        - 0.045 * avg_historical_payment_delay
        - 0.22 * num_prior_late_payments
        + 0.14 * num_prior_on_time_payments
        + 0.0009 * customer_tenure_days
        + 1.7 * prior_recovery_success_rate
        - 0.30 * num_open_invoices
        + rng.normal(0, 0.6, size=n_rows)
    )
    recovery_probability_true = _sigmoid(z)
    recovered = rng.binomial(1, recovery_probability_true)

    df = pd.DataFrame(
        {
            "invoice_amount": invoice_amount,
            "days_overdue": days_overdue,
            "outstanding_balance": outstanding_balance,
            "avg_historical_payment_delay": avg_historical_payment_delay,
            "num_prior_late_payments": num_prior_late_payments,
            "num_prior_on_time_payments": num_prior_on_time_payments,
            "customer_tenure_days": customer_tenure_days,
            "prior_recovery_success_rate": prior_recovery_success_rate,
            "num_open_invoices": num_open_invoices,
            "recovered": recovered,
        }
    )
    assert list(df.columns[:-1]) == FEATURE_NAMES
    return df
