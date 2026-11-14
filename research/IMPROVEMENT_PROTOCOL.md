# Improvement experiment, declared before candidate results

Baseline source: Quant Lab 2 commit 9b754fb. Data through 2026-11-13.

Goal: find lower drawdown and better risk-adjusted returns, not maximize an attractive in-sample statistic. A claim of simultaneously improving return, Sharpe, Calmar and profit factor requires actual evidence; risk reduction alone is not a new edge.

All historical data has already been examined in this project. The tests below are chronological, algorithmic out-of-sample tests on reused historical data. They are NOT a new pristine holdout. No future performance is known.

## Frozen candidate list (six; no post-result grids)

All new candidates use the six operational price markets (XAUUSD, MNQ, ES, EURUSD, USDJPY, JPXJPY); WTI is excluded on data-operability grounds. They omit COT release-time assumptions and the unsupported event leg. Trend lookbacks and risk windows are inherited or fixed here, not optimized by evaluation results.

1. `multispeed`: equal-weight average sign momentum at 40/80/160/240 sessions; equity indices long-only, FX/gold both directions. Equal allocation; max(20-session,60-session) volatility sizing.
2. `buffered`: multispeed with a 5 percentage-point notional/equity no-trade band; always allow flattening and direction changes.
3. `weekly`: multispeed, rebalance once at the first available market bar of each ISO week; risk exits remain daily.
4. `capped`: buffered, each market target capped at 35%, combined equity-index gross capped at 60%, total gross capped at 120%.
5. `smooth`: continuous EMA50–EMA200 trend normalized by 60-session volatility and clipped to [-1,1], with the same buffer and concentration caps.
6. `pullback_mix`: 80% capped trend + 20% equal ES/MNQ long pullback sleeve: below the trailing 5-session mean while above the trailing 200-session mean, exit above the 5-session mean or after 5 sessions. No stop-path assumption; next-open fills.

Shared target volatility 10%, 20-session book overlay capped at 2, and the existing drawdown/rolling-Sharpe halt rules. Same inherited costs, never reduced. Final target cap 2 unless the candidate uses the stricter 1.2 cap.

## Selection and evaluation

- Candidate selection inputs end 2022-06-30. Primary validation is annual anchored walk-forward tests from 2017 through 2021, training only on earlier observations. Between-fold carry, exits and transition costs must be included, not spliced from precomputed equity curves.
- Rank eligible candidates in each training window by the mean of percentile ranks of Sharpe and Calmar. Eligibility: positive CAGR, at least 3 years, maximum drawdown no worse than 25%. Fallback is cash if none qualify. Profit factor is reported, not optimized.
- Choose one final candidate using development data alone. Lock its identity before evaluating July 2022 onward.
- Report the frozen original baseline, the historical walk-forward selector and every declared candidate, including failures. No retries with different parameters after viewing evaluation results.
- Stress all candidates at double costs and with one extra full-session execution delay. The actual 06:00 UTC publishing job runs after ET midnight; ideal next-open fills are not guaranteed achievable from published targets. Delay sensitivity is therefore material, not optional.
- Promotion requires validation Sharpe >= baseline + 0.10, validation Calmar >= baseline, validation CAGR >= baseline, and less severe validation max drawdown; the chosen model must also have positive delayed/double-cost validation return. The reused evaluation must not reverse the drawdown/risk-adjusted improvements. Otherwise retain the baseline and publish the candidate only as an experiment.
- Performance metrics include CAGR, Sharpe, Calmar, max drawdown, daily-return profit factor and separately fully closed inventory-cycle profit factor. Open cycles and cross-window cycles are excluded from closed-trade PF and disclosed.
- Record all trials and evaluation windows. No renewed claim of untouched OOS. New forward snapshots are the start of prospective evidence.
