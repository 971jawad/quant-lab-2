"""Descriptive uncertainty checks; reused data cannot certify a new edge."""
import numpy as np
import pandas as pd

from .production import PERIODS_PER_YEAR


def block_uncertainty(returns, benchmark=None, draws=2000, block=20, seed=42):
    frame = pd.DataFrame({"strategy": returns})
    if benchmark is not None:
        frame["benchmark"] = benchmark
    frame = frame.dropna()
    if len(frame) < 60:
        return {"observations": len(frame), "status": "insufficient sample"}
    rng = np.random.default_rng(seed)
    values = frame.to_numpy()
    n = len(values)
    starts = rng.integers(0, n, size=(draws, int(np.ceil(n / block))))
    indices = ((starts[:, :, None] + np.arange(block)) % n).reshape(draws, -1)[:, :n]
    samples = values[indices, 0]
    sharpe = samples.mean(axis=1) / (samples.std(axis=1, ddof=1) + 1e-12) * np.sqrt(PERIODS_PER_YEAR)
    result = {"observations": n, "method": f"circular block bootstrap, {block} sessions, {draws} draws",
              "sharpe_ci95": np.quantile(sharpe, [.025, .975]).round(3).tolist(),
              "selection_adjusted": False,
              "interpretation": "Descriptive interval only; it does not correct strategy selection, repeated holdout use or data revisions."}
    if benchmark is not None:
        excess = (values[indices, 0] - values[indices, 1]).mean(axis=1) * PERIODS_PER_YEAR * 100
        result["annual_mean_excess_vs_momentum_pct"] = round(float((frame.strategy - frame.benchmark).mean() * PERIODS_PER_YEAR * 100), 3)
        result["annual_mean_excess_ci95_pct"] = np.quantile(excess, [.025, .975]).round(3).tolist()
    return result
