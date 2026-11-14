import io
import zipfile

import numpy as np
import pandas as pd
import pytest

from qlab.evidence import block_uncertainty
from qlab.production import simulate_targets
from run_refresh_cot import parse_archive, COLUMNS, CONTRACT


def test_paired_uncertainty_zero_for_identical_benchmark():
    series = pd.Series(np.random.default_rng(0).normal(0, .01, 100))
    result = block_uncertainty(series, series, draws=100)
    assert result["annual_mean_excess_ci95_pct"] == [0., 0.]
    assert not result["selection_adjusted"]


def archive(date="2026-01-06", code=CONTRACT):
    values = {column: [date if value == "date" else 100] for column, value in COLUMNS.items()}
    values["CFTC Contract Market Code"] = [code]
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as z:
        z.writestr("annual.txt", pd.DataFrame(values).to_csv(index=False))
    return buffer.getvalue()


def test_cot_parser_uses_stable_contract_code():
    parsed = parse_archive(archive(), "2026-02-01T00:00Z")
    assert len(parsed) == 1 and parsed.iloc[0].sym == "NQ"


def test_cot_parser_refuses_wrong_contract_and_future_dates():
    with pytest.raises(ValueError, match="absent"):
        parse_archive(archive(code="wrong"), "2026-02-01T00:00Z")
    with pytest.raises(ValueError, match="Future"):
        parse_archive(archive(date="2027-01-05"), "2026-02-01T00:00Z")


def test_future_targets_cannot_change_prior_returns():
    index = pd.date_range("2020-01-01", periods=100)
    close = 100 * np.exp(np.cumsum(np.random.default_rng(2).normal(0, .01, 100)))
    d = pd.DataFrame({"open": close, "close": close}, index=index)
    target = pd.DataFrame({"ES": np.sin(np.arange(100))}, index=index)
    before = simulate_targets({"ES": d}, target).returns
    target.iloc[70:] *= -2
    after = simulate_targets({"ES": d}, target).returns
    pd.testing.assert_series_equal(before.iloc[:71], after.iloc[:71])
