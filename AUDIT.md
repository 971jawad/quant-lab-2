# Quant Lab 2 audit and result

Reviewed source: `971jawad/quant-lab`, commit `943f322`. Work completed in the independent [971jawad/quant-lab-2](https://github.com/971jawad/quant-lab-2) project. The user created the destination repository after the connection denied repository creation. No changes were pushed to the original.

## Does it have an edge?

**Not established.** The original README's roughly 1.4 Sharpe is not sufficient evidence because the underlying accounting, chronology, data refresh and performance labels have material defects.

The corrected **nine-leg** model, using prices through 2026-11-13, produces:

| Window | Sharpe | CAGR | Maximum drawdown |
|---|---:|---:|---:|
| Development, before July 2022 | −0.02 | −0.35% | −20.90% |
| Reused evaluation, July 2022 onward | 0.97 | 8.71% | −16.28% |
| Full simulation, March 2013 onward | 0.36 | 2.47% | −20.90% |

The full-sample Sharpe's descriptive 95% block-bootstrap interval is **[−0.210, 0.908]**. Zero is inside it. Reused-evaluation Sharpe has interval **[0.031, 1.908]**, but this does not adjust for strategy selection, thousands of prior trials, repeated evaluation, data revisions or omitted real costs.

A simple fixed-momentum comparator earns full-sample Sharpe **0.46**, CAGR **3.53%**, and maximum drawdown **−23.13%** under the same costs, volatility overlay and halt rules. The new model's annual arithmetic mean excess over that comparator is **−1.07 percentage points**, with interval **[−5.55, +3.20]**. Its reused-evaluation excess interval is **[−0.63, +14.38]**. Neither demonstrates incremental edge over basic momentum.

A Sharpe ratio describes return relative to variability, not the probability of making money. These findings suggest a possible regime-dependent momentum effect worth forward testing; they do not establish robust alpha or justify the original confidence. The new nine-leg simulation excludes an unverified event leg and changes accounting, sizing and costs, so the difference from the old ten-leg headline cannot all be attributed to one bug.

## Confirmed findings and disposition

| Severity | Finding in original source | Effect / repair |
|---|---|---|
| Critical | `run_superbook.cot_leg_daily` spreads future weekly P&L with `repeat(5)/5`, then constructs an unrelated business-date range | Artificial smoothing and misplaced P&L. New pipeline holds released positioning signals and marks actual daily positions. Legacy artifacts remain unvalidated. |
| Critical | `run_ensembler` uses shifted targets times close-to-close returns, while trade exports claim next-open fills | New entries earn gaps that precede their fills. Shared unit accounting now separates overnight and intraday P&L. |
| Critical | Trade exporters choose today's lookback and apply it across historical trades | Historical trades are reconstructed using later selection. New engine records per-fold decisions; misleading exporters are retired. |
| High | Walk-forward loops require more than 100 remaining rows | The last partial fold can disappear; adding future rows changes which past dates exist. New folds include every eligible partial tail and pass prefix-invariance tests. |
| High | Naive session dates are converted as UTC then shifted to ET | Dates move back a day. Original `run_relive.py` fails its own overlap proof: correlation **−0.040185**, max difference **0.0860**. Date handling now preserves session dates and the pipeline rebuilds cross-sectional positions directly. |
| High | Cross-sectional costs average quote-price points across FX, gold and indices and miss leverage turnover | Incompatible price units and wrong turnover accounting. New book costs are computed per actual market-unit change. |
| High | Two layers of leg volatility targeting; book multiplier 2 is described like a total leverage cap | Changed risk profile and uncontrolled aggregate target notional. One explicit leg sizing stage and a separate final 2x gross target cap. |
| High | Freshness is measured against the newest market | All feeds can freeze together and still look fresh. New wall-clock checks suppress stale targets and show degraded state. |
| High | Hourly Yahoo resampling includes the still-open ET day; workflow ran at 23:00 UTC | Signals can use partial days. Filter incomplete days; scheduled refresh moved to 06:00 UTC. |
| High | Yahoo extension is overwritten from a rolling download and newly estimated splice ratio | Historical bars can be revised or lost. Preserve completed rows, append only, anchor new levels to the existing overlap and reject unexplained gaps. |
| High | Workflow downloads CFTC ZIPs without updating `cot_weekly.csv` | Model consumes stale positioning despite successful downloads. New stable-contract-code refresher appended ten observations; latest survey 2026-11-03. |
| High | Risk engine's daily cap only logs an event, and published positions ignore halt state | Report overstates protection. New daily-cap label is an alert; halt state drives actual simulated flattening and published zero targets. Gap losses and costs still apply. |
| High | Event backtester fills gapped stops at the stop price | Losses understated. Stop fills use the worse opening price; concurrency, time-exit count and break-even close confirmation also corrected. |
| High | Event equity simulation drops first-day P&L from daily returns | First-day loss disappears from time-series statistics. Preserve the first return relative to starting capital. |
| Medium | Drawdown starts at first ending balance; Sortino uses standard deviation of only negative returns; subperiod metrics hard-code 252 | First loss omitted and inconsistent metrics. Initial equity is included, downside deviation uses all observations, and supplied frequency applies consistently. |
| Medium | ET data has Sunday observations but production annualizes as 252 weekdays | Scaling mismatch. New production uses approximately 313 ET sessions/year and states the convention. |
| High | Yahoo extension start is called an untouched "LIVE" track record | Downloaded/rebuilt history is not proof of prospective decisions or executions. Dashboard now says research simulation; timestamped snapshots are observations only. |
| Medium | Old verification checks an expected Sharpe band rather than accounting; skipped archive checks are printed PASS | A plausible headline can pass despite wrong mechanics. New verification independently reconciles returns, contributions, chart and reported metrics; feed health is separate. |
| Medium | Deployment rebuilds append `n_configs=1` to research trial ledger | Rebuilding the same model inflates trial counts. New rebuilds never mutate the research trial ledger. |

## What was tested

- Original source build reproduced the approximate old headline (1.44 full-sample Sharpe on the original stored inputs); original cross-sectional refresh failed as described above.
- **25 automated regression tests passed.** They cover execution gaps, costs, risk halts, initial losses, metrics, incomplete days, stale feeds, immutable extensions, date handling, fold/return prefix invariance and COT timing/parser failures.
- Offline end-to-end rebuild and independent verification reconcile **4,257** simulated return observations, all market contributions, final chart equity and risk exposure targets.
- Real Yahoo refresh: six markets updated through **2026-11-13**. WTI refused at correlation **0.336**, below **0.70**. It remains stale since 2023-12-01.
- Six inherited 2026-11-06 bars had been saved at 21:33 ET before their day finished. Those provisional bars and locally appended rows anchored to them were rebuilt from the last completed inherited observation. Original rows and rationale are recorded in `research/inherited_bar_corrections.json`. Earlier completed bars were preserved.
- Real CFTC request succeeded; consumed NQ table updated through survey **2026-11-03**. Actual release timestamps remain unverified.
- Chromium/Playwright: desktop and 390px mobile rendering, no JavaScript runtime errors, seven market rows, chart rendering, no horizontal page overflow, and visible HTTP-error state.
- No broker orders were placed, no real executions were verified, and no claim of profitability was tested by risking capital.

## Remaining limits and excluded work

This is a detailed production-path audit, not a proof that every historical research experiment is correct. The repository contains many one-off studies, cached results and old statistical conclusions. They are retained as historical material and are not published as validated Quant Lab 2 claims. In particular:

- The original MNQ event leg needs intraday-path and open-position daily mark-to-market validation before admission. Daily OHLC alone cannot reconstruct the claimed path.
- WTI cannot safely be revived from the currently failing vendor overlap. Existing exposure to an unpriced instrument is not made risk-free by a zero new target.
- COT release calendars, holiday delays, revisions and contract history need point-in-time data. Tuesday + 6 days is an assumption.
- Continuous futures roll gaps, spot/futures basis, session differences and broker contract mapping can change real results. No integer-contract account implementation exists.
- Financing, borrowing, cash interest, real roll execution, liquidity/market impact, taxes and actual execution slippage are not fully modelled.
- The simulator provides daily close valuation, not intraday margin/prop-firm rule enforcement. The original prop pass-rate claims are not carried forward.
- Repeatedly inspected evaluation data cannot be made pristine by correcting code. A timestamped forward paper record with frozen criteria is the next meaningful test.

The repaired software can serve as a reproducible research tool. It is not yet demonstrated to be a profitable live trading system.
