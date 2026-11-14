"""Quant Lab 2's daily research engine.

Targets are decided at a completed ET day's close and executed at the next
available open. Returns mark actual units to each close; overnight gaps belong
to the existing position. This is a simulation, never a broker execution log.
"""
from dataclasses import dataclass

import numpy as np
import pandas as pd

ET = "America/New_York"
MARKETS = ("XAUUSD", "MNQ", "ES", "EURUSD", "USDJPY", "WTIUSD", "JPXJPY")
LONG_ONLY = {"MNQ", "ES", "JPXJPY"}
# Frozen-spec per-side spread/slippage/commission, in quote price points.
# Preserve the larger legacy value where it was already more conservative.
COST = {"XAUUSD": .45, "MNQ": 1.62, "ES": .62, "EURUSD": .00018,
        "USDJPY": .025, "WTIUSD": .07, "JPXJPY": 20.}
LOOKBACKS = (40, 80, 160, 240)
FIRST_TRAIN = 1010
FOLD = 250
TARGET_VOL = .10
# ET calendar-day data contains Sunday sessions (six observations/week).
PERIODS_PER_YEAR = 365.25 * 6 / 7


def date_index(index):
    """Naive dates already denote ET sessions; never reinterpret them as UTC."""
    idx = pd.DatetimeIndex(index)
    if idx.tz is not None:
        idx = idx.tz_convert(ET).tz_localize(None)
    return idx.normalize()


def validate_bars(data):
    d = data[["open", "high", "low", "close"]].copy()
    d.index = date_index(d.index)
    if d.empty or d.index.has_duplicates or not d.index.is_monotonic_increasing:
        raise ValueError("OHLC dates must be nonempty, unique and increasing")
    if not np.isfinite(d.to_numpy(dtype=float)).all() or (d <= 0).any().any():
        raise ValueError("OHLC prices must be finite and positive")
    if ((d.high < d[["open", "close", "low"]].max(axis=1)) |
            (d.low > d[["open", "close", "high"]].min(axis=1))).any():
        raise ValueError("OHLC range does not contain open/close")
    return d


def completed_bars(data, now=None):
    now = pd.Timestamp.now(tz=ET) if now is None else pd.Timestamp(now)
    now = now.tz_localize(ET) if now.tzinfo is None else now.tz_convert(ET)
    return data.loc[date_index(data.index) < now.tz_localize(None).normalize()]


def freshness(data, now=None, max_age=10):
    now = pd.Timestamp.now(tz=ET) if now is None else pd.Timestamp(now)
    now = now.tz_localize(ET) if now.tzinfo is None else now.tz_convert(ET)
    today = now.tz_localize(None).normalize()
    return {k: {"as_of": str(v.index[-1].date()),
                "age_days": int((today - v.index[-1]).days),
                "fresh": 0 <= (today - v.index[-1]).days <= max_age}
            for k, v in data.items()}


@dataclass
class Simulation:
    returns: pd.Series
    contributions: pd.DataFrame
    fills: pd.DataFrame
    next_targets: pd.Series
    halted: bool
    risk_events: list


def simulate_targets(data, targets, costs=None, risk=False):
    """Simulate target notional / prior-close equity with real unit turnover.

    A target on date t is first eligible on a later date with a bar. Markets
    without a bar retain their units, not fictitious fills. Halt decisions made
    at a close flatten at subsequent opens, including their gaps and exit costs.
    The 3% daily threshold is an alert; daily OHLC cannot enforce an intraday cap.
    """
    columns = list(targets.columns)
    costs = COST if costs is None else costs
    idx = targets.index
    opening = pd.DataFrame({k: data[k].open.reindex(idx) for k in columns})
    closing = pd.DataFrame({k: data[k].close.reindex(idx) for k in columns})
    desired = targets.shift(1).fillna(0.).to_numpy(dtype=float)
    if not np.isfinite(desired).all():
        raise ValueError("Non-finite target exposure")
    op, cl = opening.to_numpy(), closing.to_numpy()
    unit = np.zeros(len(columns))
    prior = np.full(len(columns), np.nan)
    eq = peak = 1.
    cooloff = 0
    returns, contributions, fills, events = [], [], [], []
    for i, dt in enumerate(idx):
        start = eq
        pnl = np.zeros(len(columns))
        halted_today = cooloff > 0
        for j, name in enumerate(columns):
            if np.isnan(op[i, j]):
                continue
            gap = 0. if np.isnan(prior[j]) else unit[j] * (op[i, j] - prior[j])
            target = 0. if halted_today else desired[i, j]
            new_unit = start * target / op[i, j]
            change = new_unit - unit[j]
            fee = abs(change) * costs[name]
            pnl[j] = gap + new_unit * (cl[i, j] - op[i, j]) - fee
            if abs(change) > 1e-12:
                fills.append({"date": str(dt.date()), "market": name,
                              "price": float(op[i, j]), "units_per_initial_equity": float(change),
                              "target_exposure": float(target), "cost": float(fee),
                              "kind": "SIMULATED"})
            unit[j], prior[j] = new_unit, cl[i, j]
        eq += pnl.sum()
        if eq <= 0 or not np.isfinite(eq):
            raise ValueError(f"Simulation insolvent at {dt.date()}")
        ret = eq / start - 1
        returns.append(ret)
        contributions.append(pnl / start)
        peak = max(peak, eq)
        if risk:
            if halted_today:
                cooloff -= 1
                if cooloff == 0:
                    peak = eq
                    events.append({"date": str(dt.date()), "event": "60-bar cool-off completed"})
            else:
                if ret <= -.03:
                    events.append({"date": str(dt.date()), "event": "daily loss alert (not an intraday stop)"})
                window = np.array(returns[-313:])
                sharpe = window.mean() / (window.std(ddof=1) + 1e-12) * np.sqrt(PERIODS_PER_YEAR) if len(window) == 313 else 0.
                if eq / peak - 1 <= -.12 or sharpe <= -1.:
                    cooloff = 60
                    events.append({"date": str(dt.date()), "event": "halt: flatten at next available opens"})
    next_targets = targets.iloc[-1].copy() if len(targets) else pd.Series(dtype=float)
    if cooloff:
        next_targets[:] = 0.
    return Simulation(pd.Series(returns, index=idx, name="ret"),
                      pd.DataFrame(contributions, index=idx, columns=columns),
                      pd.DataFrame(fills), next_targets, bool(cooloff), events)


def walk_forward_choice(candidates, first_train=FIRST_TRAIN, fold=FOLD, warmup=260):
    """Choice on close t can use returns through t, for execution after t.

    No minimum final test length: adding future bars never changes an existing
    fold. This includes the final, partial fold that the old code omitted.
    """
    choice = pd.Series(np.nan, index=candidates.index)
    for start in range(first_train, len(candidates) + 1, fold):
        train = candidates.iloc[warmup:start]
        score = train.mean() / (train.std() + 1e-12)
        if not score.notna().any():
            continue
        best = score.idxmax()
        choice.iloc[start - 1:min(start + fold - 1, len(choice))] = best
    return choice


def trend_targets(d, market, lookbacks=LOOKBACKS, first_train=FIRST_TRAIN, fold=FOLD):
    vol = d.close.pct_change(fill_method=None).rolling(60).std()
    leverage = (TARGET_VOL / np.sqrt(PERIODS_PER_YEAR) / vol.replace(0., np.nan)).clip(0, 3).fillna(0.)
    signals, targets, candidates = {}, {}, {}
    for lb in lookbacks:
        sig = np.sign(d.close.pct_change(lb, fill_method=None)).fillna(0.)
        if market in LONG_ONLY:
            sig = sig.clip(lower=0.)
        signals[lb] = sig
        targets[lb] = sig * leverage
        candidates[lb] = simulate_targets({market: d}, targets[lb].to_frame(market)).returns
    selected = walk_forward_choice(pd.DataFrame(candidates), first_train, fold)
    target = pd.Series(0., index=d.index)
    direction = target.copy()
    for lb in lookbacks:
        mask = selected == lb
        target.loc[mask] = targets[lb].loc[mask]
        direction.loc[mask] = signals[lb].loc[mask]
    return target.to_frame(market), selected, direction


def xsec_targets(data, first_train=FIRST_TRAIN, fold=FOLD):
    names = ("ES", "MNQ", "XAUUSD", "EURUSD")
    closes = pd.DataFrame({k: data[k].close for k in names}).dropna()
    frames, candidates = {}, {}
    for lb in LOOKBACKS:
        momentum = closes.pct_change(lb, fill_method=None)
        # Equal ranks (including all-flat prices) give no contradictory trades.
        hi, lo = momentum.max(axis=1), momentum.min(axis=1)
        weights = momentum.eq(hi, axis=0).astype(float) - momentum.eq(lo, axis=0).astype(float)
        weights = weights.div(weights.abs().sum(axis=1).replace(0, np.nan), axis=0).fillna(0.)
        raw = simulate_targets(data, weights).returns
        lev = (TARGET_VOL / (raw.rolling(60).std() * np.sqrt(PERIODS_PER_YEAR)).replace(0, np.nan)).clip(0, 3).fillna(0.)
        frames[lb] = weights.mul(lev, axis=0)
        candidates[lb] = simulate_targets(data, frames[lb]).returns
    selected = walk_forward_choice(pd.DataFrame(candidates), first_train, fold)
    target = pd.DataFrame(0., index=closes.index, columns=names)
    for lb, frame in frames.items():
        target.loc[selected == lb] = frame.loc[selected == lb]
    return target


def cot_targets(d, cot):
    """Daily mark-to-market, using only released COT observations.

    available_at may supply actual release timestamps. Without it, use the
    legacy conservative Tuesday + 6 calendar days assumption, explicitly
    reported by the pipeline. Expire an observation after 14 days.
    """
    c = cot[cot.sym == "NQ"].sort_values("date").drop_duplicates("date", keep="last").copy()
    c["date"] = pd.to_datetime(c.date)
    net = (c.nc_long - c.nc_short) / c.oi.replace(0, np.nan)
    z = (net - net.rolling(104).mean()) / net.rolling(104).std().replace(0, np.nan)
    available = (pd.to_datetime(c.available_at, utc=True).dt.tz_convert(ET).dt.tz_localize(None)
                 if "available_at" in c else c.date + pd.Timedelta(days=6) - pd.Timedelta(nanoseconds=1))
    observations = pd.DataFrame({"available": available, "signal": (z < -1.5).astype(float)})
    observations["available"] = observations.available.astype("datetime64[ns]")
    observations = observations.sort_values("available")
    decisions = pd.DataFrame({"decision": d.index + pd.Timedelta(days=1) - pd.Timedelta(nanoseconds=1)})
    decisions["decision"] = decisions.decision.astype("datetime64[ns]")
    aligned = pd.merge_asof(decisions, observations, left_on="decision", right_on="available", tolerance=pd.Timedelta(days=14))
    signal = pd.Series(aligned.signal.fillna(0.).to_numpy(), index=d.index)
    vol = d.close.pct_change(fill_method=None).rolling(60).std()
    lev = (TARGET_VOL / np.sqrt(PERIODS_PER_YEAR) / vol.replace(0, np.nan)).clip(0, 3).fillna(0.)
    return (signal * lev).to_frame("MNQ")


def allocation_weights(returns):
    corr = returns.rolling(120).corr().abs().groupby(level=0).sum().reindex(returns.index)
    inverse = (1. / corr.replace(0, np.nan)).fillna(1.)
    strength = (returns.rolling(756).mean() / (returns.rolling(756).std() + 1e-12) * np.sqrt(PERIODS_PER_YEAR)).clip(lower=0).fillna(0) + .1
    weights = inverse * strength
    weights = weights.div(weights.sum(axis=1), axis=0)
    previous, rows = None, []
    for _, current in weights.iterrows():
        if previous is None or (current - previous).abs().max() > .02:
            previous = current
        rows.append(previous)
    return pd.DataFrame(rows, index=returns.index)
