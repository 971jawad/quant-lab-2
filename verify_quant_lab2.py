"""Independently reconcile a generated report with its numerical artifacts."""
import json
from pathlib import Path

import numpy as np
import pandas as pd

from qlab.metrics import full_metrics
from qlab.production import PERIODS_PER_YEAR

ROOT = Path(__file__).resolve().parent


def verify(root=ROOT):
    def invalid_constant(value):
        raise ValueError(f"Non-JSON numeric value: {value}")
    report = json.loads((root / "docs/data.json").read_text(), parse_constant=invalid_constant)
    if report["schema_version"] != 2:
        raise ValueError("Wrong report schema")
    returns = pd.read_csv(root / "artifacts/returns.csv", index_col=0, parse_dates=True).ret
    contributions = pd.read_csv(root / "artifacts/contributions.csv", index_col=0, parse_dates=True)
    targets = pd.read_csv(root / "artifacts/target_history.csv", index_col=0, parse_dates=True)
    if returns.index.has_duplicates or not returns.index.is_monotonic_increasing:
        raise ValueError("Returns have invalid dates")
    if not np.isfinite(returns).all() or (returns <= -1).any():
        raise ValueError("Invalid portfolio returns")
    if not np.allclose(contributions.sum(axis=1).reindex(returns.index), returns, atol=1e-10):
        raise ValueError("Market contributions fail to reconcile")
    if not np.isfinite(targets).all().all() or (targets.abs().sum(axis=1) > 2 + 1e-10).any():
        raise ValueError("Invalid target exposure")
    recomputed = full_metrics(daily_ret=returns, periods_per_year=PERIODS_PER_YEAR, n_trials=4572)
    for key in ("sharpe", "cagr_pct", "max_dd_pct", "total_return_pct"):
        if report["metrics"]["full"][key] != recomputed[key]:
            raise ValueError(f"Reported {key} does not reproduce")
    if abs(report["curve"][-1]["equity"] - (1 + returns).prod()) > 1e-10:
        raise ValueError("Chart endpoint does not reconcile")
    for position in report["positions"]:
        if (not position["fresh"] or report["risk"]["halted"]) and position["next_open_exposure"] != 0:
            raise ValueError("Stale/halted target published")
    print(f"PASS: {len(returns)} returns reconcile; report metrics, chart, contributions and exposure limits verified")
    print(f"Operational state: {report['operational']} (separate from accounting correctness)")
    return report


if __name__ == "__main__":
    verify()
