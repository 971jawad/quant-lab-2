import numpy as np
import pandas as pd
import pytest

from qlab.backtest import Costs, bt_trades, simulate
from qlab.metrics import full_metrics
from qlab.production import (simulate_targets, validate_bars, date_index,
                             completed_bars, freshness, walk_forward_choice,
                             trend_targets, cot_targets)
from run_live_update import append_closed_extension


def bars(opens, closes=None, start="2025-01-01"):
    closes = opens if closes is None else closes
    return pd.DataFrame({"open": opens, "close": closes,
                         "high": np.maximum(opens, closes), "low": np.minimum(opens, closes)},
                        index=pd.date_range(start, periods=len(opens)))


def test_new_position_cannot_earn_gap_before_entry():
    d = bars([100, 120, 150], [100, 132, 150])
    target = pd.DataFrame({"ES": [1., 0., 0.]}, index=d.index)
    s = simulate_targets({"ES": d}, target, costs={"ES": 0})
    assert s.returns.iloc[1] == pytest.approx(.1)
    assert s.returns.iloc[2] == pytest.approx(150 / 132 - 1)
    assert s.fills.iloc[0].price == 120
    assert np.allclose(s.contributions.sum(axis=1), s.returns)


def test_costs_include_entry_exit_and_flip_turnover():
    d = bars([100] * 4)
    target = pd.DataFrame({"ES": [1., -1., 0., 0.]}, index=d.index)
    s = simulate_targets({"ES": d}, target, costs={"ES": 1})
    assert s.fills.iloc[0]["cost"] == pytest.approx(.01)
    assert s.fills.iloc[1]["cost"] == pytest.approx(.0199)
    assert s.fills.iloc[2]["cost"] == pytest.approx(.0099)
    assert (1 + s.returns).prod() == pytest.approx(1 - s.fills["cost"].sum())


def test_missing_market_bar_does_not_create_fill():
    d = bars([100, 100, 100]).drop(pd.Timestamp("2025-01-02"))
    target = pd.DataFrame({"ES": [1., 1., 1.]}, index=pd.date_range("2025-01-01", periods=3))
    s = simulate_targets({"ES": d}, target, costs={"ES": 0})
    assert list(s.fills.date) == ["2025-01-03"]


def test_risk_halt_flattens_next_open_and_pays_gap_and_cost():
    d = bars([100, 100, 70, 70], [100, 80, 70, 70])
    target = pd.DataFrame({"ES": [1.] * 4}, index=d.index)
    s = simulate_targets({"ES": d}, target, costs={"ES": .1}, risk=True)
    assert s.halted and s.next_targets.ES == 0
    assert s.returns.iloc[1] < -.20
    assert s.returns.iloc[2] < -.12  # overnight gap isn't erased by the halt
    assert s.fills.iloc[1].target_exposure == 0
    assert s.returns.iloc[3] == 0


def test_first_loss_counts_toward_drawdown():
    r = pd.Series([-.10] + [0.] * 29)
    m = full_metrics(daily_ret=r)
    assert m["max_dd_pct"] == -10
    assert m["pct_time_underwater"] == 100


def test_sortino_uses_downside_deviation_over_all_observations():
    r = pd.Series([-.01, .02] * 30)
    m = full_metrics(daily_ret=r)
    expected = r.mean() / np.sqrt(np.minimum(r, 0).pow(2).mean()) * np.sqrt(252)
    assert m["sortino"] == round(expected, 2)


def test_annualization_applies_to_half_sample_statistics():
    r = pd.Series([-.01, .02] * 60)
    weekly = full_metrics(daily_ret=r, periods_per_year=52)
    daily = full_metrics(daily_ret=r, periods_per_year=252)
    assert weekly["sharpe_first_half"] == weekly["sharpe_second_half"]
    assert weekly["sharpe_first_half"] < daily["sharpe_first_half"]
    assert weekly["rolling_sharpe_min"] < daily["sharpe"]


def test_empty_trade_metrics_and_invalid_returns():
    assert full_metrics(trades_R=[np.nan]) == {}
    with pytest.raises(ValueError):
        full_metrics(daily_ret=[float("inf")] * 30)


def test_event_stop_fills_at_worse_gapped_open():
    sig = pd.DataFrame([{"i": 0, "dir": 1, "stop": 90, "conviction": 1}])
    tr = bt_trades(np.array([100, 100, 70]), np.array([101, 105, 80]),
                   np.array([99, 95, 60]), np.array([100, 100, 75]),
                   sig, 3, 10, Costs(0, 0, 0), 1)
    assert tr.iloc[0].R == -3


def test_event_time_exit_counts_entry_bar():
    sig = pd.DataFrame([{"i": 0, "dir": 1, "stop": 90, "conviction": 1}])
    a = np.array([100, 101, 102])
    tr = bt_trades(a, a + 1, a - 1, a, sig, 3, 1, Costs(0, 0, 0), 1)
    assert tr.iloc[0].exit_i == 1


def test_entry_cost_cannot_hide_a_gap_through_stop():
    sig = pd.DataFrame([{"i": 0, "dir": 1, "stop": 100, "conviction": 1}])
    a = np.array([101., 99.9])
    tr = bt_trades(a, a + 1, a - 1, a, sig, 3, 1, Costs(.4, 0, 0), 1)
    assert tr.empty


def test_position_capacity_not_freed_by_future_intrabar_exit():
    sig = pd.DataFrame([{"i": i, "dir": 1, "stop": 90, "conviction": 1} for i in [0, 1]])
    a = np.array([100., 100., 100., 100.])
    tr = bt_trades(a, a + 1, a - 1, a, sig, 3, 2, Costs(0, 0, 0), 1)
    assert len(tr) == 1 and tr.iloc[0].exit_i == 2


def test_event_daily_series_keeps_first_day_pnl():
    tr = pd.DataFrame([dict(entry_i=0, exit_i=0, R=-1, conviction=1)])
    result = simulate(tr, pd.date_range("2025-01-01", periods=2).date, .1, want_daily=True)
    assert result["daily_returns"].iloc[0] == pytest.approx(-.1)


def test_naive_session_dates_do_not_shift_back_a_day():
    assert date_index(pd.to_datetime(["2025-01-06"]))[0] == pd.Timestamp("2025-01-06")
    assert date_index(pd.to_datetime(["2025-01-06T05:00:00Z"]))[0] == pd.Timestamp("2025-01-06")


def test_complete_feed_outage_is_stale_against_wall_clock():
    d = bars([100] * 3)
    assert not freshness({"ES": d}, "2025-02-01T12:00Z")["ES"]["fresh"]


def test_incomplete_et_day_excluded_even_after_us_cash_close():
    d = bars([100] * 3)
    result = completed_bars(d, "2025-01-04T01:00Z")
    assert result.index[-1] == pd.Timestamp("2025-01-02")


def test_append_keeps_old_completed_bars_and_ignores_provider_revisions(tmp_path):
    path = tmp_path / "ES_ext.csv"
    old = bars([100, 101, 102])
    old.to_csv(path)
    original_bytes = path.read_bytes()
    incoming = bars([202, 103, 104], start="2025-01-03")
    result = append_closed_extension(path, incoming, "2025-01-05T20:00Z")
    assert result.loc["2025-01-03", "close"] == 102
    assert result.index[0] == old.index[0]
    assert result.index[-1] == pd.Timestamp("2025-01-04")
    assert path.read_bytes().startswith(original_bytes)


def test_ohlc_validation_rejects_duplicates_and_impossible_ranges():
    d = bars([100, 101])
    with pytest.raises(ValueError):
        validate_bars(pd.concat([d, d]))
    d.loc[d.index[0], "high"] = 90
    with pytest.raises(ValueError):
        validate_bars(d)


def test_partial_fold_is_covered_and_future_rows_do_not_rewrite_choices():
    idx = pd.date_range("2025-01-01", periods=90)
    rng = np.random.default_rng(3)
    candidates = pd.DataFrame(rng.normal(.001, .01, (90, 2)), columns=[2, 4], index=idx)
    full = walk_forward_choice(candidates, first_train=30, fold=20, warmup=0)
    prefix = walk_forward_choice(candidates.iloc[:75], first_train=30, fold=20, warmup=0)
    pd.testing.assert_series_equal(full.iloc[:75], prefix)
    assert prefix.iloc[-1] in (2, 4)


def test_trend_signals_and_returns_are_prefix_invariant():
    rng = np.random.default_rng(7)
    close = 100 * np.exp(np.cumsum(rng.normal(0, .01, 400)))
    d = bars(close, start="2020-01-01")
    a, _, _ = trend_targets(d, "ES", lookbacks=(20, 40), first_train=280, fold=50)
    b, _, _ = trend_targets(d.iloc[:350], "ES", lookbacks=(20, 40), first_train=280, fold=50)
    pd.testing.assert_frame_equal(a.iloc[:350], b)
    assert (a.ES >= 0).all()


def test_cot_signal_waits_for_release_and_expires():
    dates = pd.date_range("2020-01-07", periods=110, freq="W-TUE")
    cot = pd.DataFrame({"date": dates, "sym": "NQ", "oi": 1000,
                        "nc_long": 100 + np.arange(110) % 10, "nc_short": 100})
    cot.loc[109, "nc_long"] = 0
    effective = dates[-1] + pd.Timedelta(days=6)
    idx = pd.date_range(effective - pd.Timedelta(days=100), periods=130)
    close = 100 + np.sin(np.arange(len(idx)))
    d = bars(close, start=idx[0])
    targets = cot_targets(d, cot)
    assert targets.loc[effective - pd.Timedelta(days=2), "MNQ"] == 0
    assert targets.loc[effective - pd.Timedelta(days=1), "MNQ"] > 0
    assert targets.loc[effective + pd.Timedelta(days=15), "MNQ"] == 0
