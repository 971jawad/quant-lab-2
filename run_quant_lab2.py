"""Rebuild the audited Quant Lab 2 research dashboard from committed daily data.

Run without network: python run_quant_lab2.py
Refresh prices explicitly first: python run_live_update.py
"""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from qlab.metrics import full_metrics
from qlab.evidence import block_uncertainty
from qlab.production import (COST, MARKETS, PERIODS_PER_YEAR, allocation_weights,
                             completed_bars, cot_targets, date_index, freshness,
                             simulate_targets, trend_targets, validate_bars,
                             xsec_targets)

ROOT = Path(__file__).resolve().parent
DEV_END = pd.Timestamp("2022-07-01")


def read_market(root, name, now=None):
    frozen = pd.read_csv(root / "data/daily" / f"{name}.csv", index_col=0, parse_dates=True)
    frozen = validate_bars(frozen)
    path = root / "data/live" / f"{name}_ext.csv"
    if path.exists():
        ext = validate_bars(pd.read_csv(path, index_col=0, parse_dates=True))
        if (ext.index <= frozen.index[-1]).any():
            raise ValueError(f"{name}: live bars overlap frozen history")
        frozen = pd.concat([frozen, ext])
    out = completed_bars(validate_bars(frozen), now)
    if out.empty:
        raise ValueError(f"{name}: no completed bars")
    return out


def clean_json(value):
    if isinstance(value, dict):
        return {str(k): clean_json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean_json(v) for v in value]
    if isinstance(value, (float, np.floating)):
        return float(value) if np.isfinite(value) else None
    if isinstance(value, np.integer):
        return int(value)
    return value


def write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(clean_json(payload), indent=2, allow_nan=False) + "\n")
    temp.replace(path)


def build(root=ROOT, now=None, record_snapshot=False):
    now = pd.Timestamp.now(tz="UTC") if now is None else pd.Timestamp(now)
    if now.tzinfo is None:
        now = now.tz_localize("UTC")
    data = {name: read_market(root, name, now) for name in MARKETS}
    status = freshness(data, now)
    index = pd.DatetimeIndex(sorted(set().union(*(d.index for d in data.values()))))
    legs, selected = {}, {}
    for name, d in data.items():
        target, choices, directions = trend_targets(d, name)
        legs[f"trend_{name}"] = target
        selected[name] = {"lookback": int(choices.iloc[-1]) if pd.notna(choices.iloc[-1]) else None,
                          "direction": float(directions.iloc[-1])}
    legs["xsec_ALL"] = xsec_targets(data)
    cot_path = root / "data/external/cot_weekly.csv"
    cot = pd.read_csv(cot_path, parse_dates=["date"])
    cot_end = cot.loc[cot.sym == "NQ", "date"].max()
    cot_age = int((now.tz_localize(None).normalize() - cot_end).days)
    legs["COT_NQ_washout"] = cot_targets(data["MNQ"], cot)

    # Missing-market days do not receive fabricated OHLC or fills. Targets may
    # persist across a normal weekend but expire after 10 calendar days.
    frames, leg_returns = {}, {}
    for name, frame in legs.items():
        expanded = frame.reindex(index).ffill().fillna(0.)
        last_seen = pd.Series(frame.index, index=frame.index).reindex(index).ffill()
        expired = (index.to_series(index=index) - last_seen).dt.days > 10
        expanded.loc[expired] = 0.
        frames[name] = expanded
        leg_returns[name] = simulate_targets(data, expanded).returns
    rets = pd.DataFrame(leg_returns)
    weights = allocation_weights(rets)
    raw_targets = pd.DataFrame(0., index=index, columns=MARKETS)
    for name, frame in frames.items():
        raw_targets[frame.columns] += frame.mul(weights[name], axis=0)
    raw = simulate_targets(data, raw_targets)
    vol = raw.returns.rolling(20).std() * np.sqrt(PERIODS_PER_YEAR)
    overlay = (.10 / vol.replace(0., np.nan)).clip(0, 2).fillna(0.)
    target = raw_targets.mul(overlay, axis=0)
    # Unlike a 2x multiplier on already-levered legs, enforce a real book cap.
    gross = target.abs().sum(axis=1)
    target = target.mul((2. / gross.replace(0., np.nan)).clip(upper=1).fillna(1.), axis=0)
    sim = simulate_targets(data, target, risk=True)
    start = min(frame.index[1010] for frame in data.values() if len(frame) > 1010)
    returns = sim.returns.loc[start:]
    metrics = {name: full_metrics(daily_ret=segment, n_trials=4572, periods_per_year=PERIODS_PER_YEAR)
               for name, segment in (("development", returns[returns.index < DEV_END]),
                                     ("reused_evaluation", returns[returns.index >= DEV_END]),
                                     ("full", returns))}
    # Fixed 313-session momentum, equal market allocation: no selection grid.
    benchmark_targets = pd.DataFrame(0., index=index, columns=MARKETS)
    for name, d in data.items():
        vol = d.close.pct_change(fill_method=None).rolling(60).std()
        signal = np.sign(d.close.pct_change(313, fill_method=None)).fillna(0.)
        exposure = signal * (.10 / np.sqrt(PERIODS_PER_YEAR) / vol.replace(0, np.nan)).clip(0, 3).fillna(0.) / len(MARKETS)
        expanded = exposure.reindex(index).ffill().fillna(0.)
        last_seen = pd.Series(d.index, index=d.index).reindex(index).ffill()
        expanded.loc[(index.to_series(index=index) - last_seen).dt.days > 10] = 0.
        benchmark_targets[name] = expanded
    benchmark_raw = simulate_targets(data, benchmark_targets).returns
    benchmark_vol = benchmark_raw.rolling(20).std() * np.sqrt(PERIODS_PER_YEAR)
    benchmark_overlay = (.10 / benchmark_vol.replace(0, np.nan)).clip(0, 2).fillna(0.)
    benchmark_targets = benchmark_targets.mul(benchmark_overlay, axis=0)
    gross_benchmark = benchmark_targets.abs().sum(axis=1)
    benchmark_targets = benchmark_targets.mul((2. / gross_benchmark.replace(0, np.nan)).clip(upper=1).fillna(1.), axis=0)
    benchmark = simulate_targets(data, benchmark_targets, risk=True).returns.loc[start:]
    evidence = {name: block_uncertainty(segment, benchmark.reindex(segment.index))
                for name, segment in (("full", returns), ("reused_evaluation", returns[returns.index >= DEV_END]))}
    benchmark_metrics = full_metrics(daily_ret=benchmark, periods_per_year=PERIODS_PER_YEAR)
    positions = []
    for name in MARKETS:
        fresh = status[name]["fresh"]
        exposure = float(sim.next_targets[name]) if fresh else 0.
        positions.append({"market": name, **status[name], **selected[name],
                          "next_open_exposure": exposure,
                          "side": "LONG" if exposure > 1e-8 else "SHORT" if exposure < -1e-8 else "FLAT",
                          "last_close": float(data[name].close.iloc[-1]),
                          "status": "HALTED" if sim.halted else "READY" if fresh else "STALE / NO NEW TARGET"})
    issues = []
    stale = [name for name in MARKETS if not status[name]["fresh"]]
    if stale:
        issues.append("Stale price feeds: " + ", ".join(stale) + ". New targets are suppressed; an existing position still needs a real market exit.")
    if cot_age > 25:
        issues.append(f"COT input is {cot_age} days old. Expired observations generate no position.")
    issues.extend([
        "MNQ_pull_C is excluded: its old realized-exit P&L is not a marked-to-market, intraday-verified record.",
        "This is a corrected nine-leg simulation, not a reproduction of the original ten-leg champion. No parameters were tuned to its evaluation results.",
        "COT uses actual release timestamps when supplied; this input only has survey dates, so Tuesday + 6 days is assumed. Holiday/delayed releases need point-in-time release data.",
        "Yahoo continuous futures and spot/cash proxies have contract-roll, basis and session differences. Fees are modelled; financing, borrow, roll execution and broker fills are not verified.",
        "The evaluation window has already been inspected and used in earlier research. It is not an untouched holdout or a live broker track record.",
        "Daily bars can report a loss alert and schedule a next-open halt, but cannot guarantee an intraday loss limit or prop-firm compliance.",
    ])
    checks = [
        {"name": "OHLC valid, ordered, unique; frozen history preserved", "passed": True},
        {"name": "Finite simulated returns", "passed": bool(np.isfinite(returns).all())},
        {"name": "Market contributions reconcile to portfolio returns", "passed": bool(np.allclose(sim.contributions.sum(axis=1), sim.returns, atol=1e-12))},
        {"name": "Target gross exposure never exceeds 2x", "passed": bool((target.abs().sum(axis=1) <= 2 + 1e-12).all())},
        {"name": "Stale feeds have no new published exposure", "passed": all(p["next_open_exposure"] == 0 for p in positions if not p["fresh"])},
        {"name": "All price feeds fresh", "passed": not stale, "operational": True},
        {"name": "COT source fresh", "passed": cot_age <= 25, "operational": True},
    ]
    fingerprint = hashlib.sha256()
    for pattern in ("data/daily/*.csv", "data/live/*.csv", "data/external/cot_weekly.csv",
                    "qlab/production.py", "qlab/metrics.py", "qlab/evidence.py", "run_quant_lab2.py"):
        for path in sorted(root.glob(pattern)):
            fingerprint.update(str(path.relative_to(root)).encode())
            fingerprint.update(path.read_bytes())
    equity = (1 + returns).cumprod()
    sampled = equity.iloc[::5]
    sampled = pd.concat([sampled, equity.iloc[-1:]]).loc[lambda s: ~s.index.duplicated()]
    payload = {
        "project": "Quant Lab 2", "schema_version": 2,
        "generated_utc": now.isoformat(), "data_as_of": str(index[-1].date()),
        "input_and_engine_sha256": fingerprint.hexdigest(),
        "mode": "RESEARCH SIMULATION", "operational": "HALTED" if sim.halted else "DEGRADED" if stale or cot_age > 25 else "READY",
        "execution": "Decision at completed ET-day close; simulated fill at next available bar open. Not necessarily midnight and not a broker quote.",
        "periods_per_year": PERIODS_PER_YEAR,
        "metrics": metrics, "positions": positions,
        "evidence": evidence,
        "benchmark": {"description": "Fixed 313-session momentum, both directions, seven markets, equal allocations, same cost model, volatility overlay, halt rules and 2x target cap; no parameter selection.", "full_metrics": benchmark_metrics},
        "allocations": {name: float(weights[name].iloc[-1]) for name in weights},
        "curve": [{"date": str(dt.date()), "equity": float(value)} for dt, value in sampled.items()],
        "checks": checks, "limitations": issues,
        "risk": {"halted": sim.halted, "events": sim.risk_events[-20:], "count": len(sim.risk_events)},
        "fills": sim.fills.tail(60).to_dict("records"),
        "verdict": "The software produces reproducible simulated targets and P&L. A durable tradable edge and live execution are not established.",
    }
    out = root / "artifacts"
    out.mkdir(exist_ok=True)
    returns.to_csv(out / "returns.csv")
    sim.contributions.loc[start:].to_csv(out / "contributions.csv")
    sim.fills.to_csv(out / "simulated_fills.csv", index=False)
    target.to_csv(out / "target_history.csv")
    benchmark.to_csv(out / "benchmark_returns.csv", header=["ret"])
    write_json(out / "report.json", payload)
    write_json(root / "docs/data.json", payload)
    if record_snapshot:
        # An observation recorded now is not evidence of an earlier execution.
        snapshot = {k: payload[k] for k in ("generated_utc", "data_as_of", "input_and_engine_sha256", "positions", "operational")}
        dest = root / "research/forward_snapshots" / (now.strftime("%Y%m%dT%H%M%S%fZ") + ".json")
        dest.parent.mkdir(exist_ok=True)
        with dest.open("x") as handle:
            json.dump(snapshot, handle, indent=2, allow_nan=False)
    print(json.dumps({"status": payload["operational"], "data_as_of": payload["data_as_of"],
                      "metrics": metrics, "report": str(out / "report.json")}, indent=2))
    if not all(c["passed"] for c in checks if not c.get("operational")):
        raise RuntimeError("Accounting/integrity verification failed")
    return payload


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--record-snapshot", action="store_true", help="Record a timestamped observation; never label it a fill")
    parser.add_argument("--require-fresh", action="store_true", help="Exit nonzero if feeds are stale or the book is halted")
    args = parser.parse_args()
    report = build(record_snapshot=args.record_snapshot)
    raise SystemExit(1 if args.require_fresh and report["operational"] != "READY" else 0)
