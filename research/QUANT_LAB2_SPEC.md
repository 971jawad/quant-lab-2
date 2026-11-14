# Quant Lab 2 implementation specification

This is a correctness repair and explicit new nine-leg model, not a claim that the original champion's performance survived. Existing evaluation data is reused. No model changes in this repair were selected to maximize the resulting Sharpe.

## Inputs and timing

- Preserve ET calendar-day OHLC, including Sunday sessions. Naive dates already mean ET dates; do not interpret them as UTC.
- Only completed ET days may inform a decision. A decision at a close becomes eligible at the next available open for that instrument.
- Initial historical data is never overwritten by a live extension. Completed extension bars remain immutable. Latest vendor corrections are not a point-in-time historical database.
- Missing bars do not generate fills. Existing units retain their last valuation until another valid bar; stale quotes therefore leave valuation uncertainty, especially for discontinued WTI.
- Freshness uses wall-clock ET dates, not the newest market. Price tolerance: 10 calendar days. COT source tolerance: 25 days; observations expire after 14 days from assumed/actual availability.

## Leg definitions

1. Seven market trend legs: XAUUSD, MNQ, ES, EURUSD, USDJPY, WTIUSD, JPXJPY.
2. Cross-sectional momentum: ES, MNQ, XAUUSD, EURUSD; long highest momentum and short lowest, normalized by gross exposure. Ties do not create contradictory positions.
3. Nasdaq COT washout: net noncommercial positioning divided by open interest, trailing 104-report z-score below −1.5; long only. Mark actual daily positions rather than spreading future weekly returns into synthetic daily rows.

The original MNQ_pull_C event leg is excluded pending intraday path and daily open-position mark-to-market validation. It was not simply "missing intraday bars": the legacy fallback could rebuild on daily OHLC, which still does not prove the claimed intraday path or equity curve.

Trend/Cross-sectional lookback grid: 40/80/160/240 observations, inherited from the original. Anchored training begins after 1,010 observations, with a 260-observation warmup and 250-observation folds. Include short final folds. Train only on settled past returns; store the actual per-date selection. MNQ/ES/JPXJPY trend legs remain long-only; the cross-sectional leg can offset them.

Trend/COT sizing uses trailing 60-observation return volatility, 10% annual target, leverage clip 3. Cross-sectional sizing uses trailing 60-observation realized strategy volatility with the same target/clip. ET bars contain six sessions per week, so the production annualization constant is `365.25 * 6 / 7`, not a weekday-only 252. Annualized metrics remain estimates; Sharpe uses zero cash/risk-free return.

## Portfolio and execution

Allocation: trailing 756-observation nonnegative Sharpe + 0.1, multiplied by inverse-sum absolute trailing 120-observation correlations, normalized. Update when a weight drifts more than 0.02. Weights observed at a close only influence later executions. No second layer of leg vol targeting.

Book overlay: trailing 20-observation realized raw-book volatility, 10% annual target, multiplier capped at 2. Final gross target exposure is separately capped at 2x equity. That is a target cap, not a guarantee about leverage after an overnight gap.

Net market positions combine all legs. Set desired units at the open from target exposure and prior-close equity. Existing units earn/lose the overnight gap; new units earn/lose the open-to-close movement. Charge absolute unit turnover times the per-side spread/slippage/commission cost. The inherited conservative cost values were not lowered; EURUSD is raised to the declared frozen-spec floor. No futures contract integer sizing or actual broker routing is modelled.

Risk: 3% daily loss is an alert, not an enforceable intraday cap. A 12% drawdown or one-year realized Sharpe below −1 schedules flattening at next available opens, including gap losses and closing costs. Remain flat for 60 subsequent observations, then reset the drawdown clock. The published next target is zero while halted.

## Evaluation

Development: before 2022-07-01. Reused evaluation: from 2022-07-01. Neither is newly untouched data. No period is labelled a live broker track record.

Benchmark: fixed 313-session momentum, both directions, equal market allocation, identical cost, volatility overlay, halt and target-cap conventions. This is a descriptive comparator, not a claim of causal alpha.

Uncertainty: paired circular 20-session block bootstrap, 2,000 draws, seed 42, 95% intervals. These intervals do not adjust for model selection or repeated evaluation. Legacy deflated-Sharpe values are heuristic diagnostics, not literal probabilities that a tradeable edge exists.

Future evidence must come from versioned targets recorded before their eligible execution, independently verified prices/fills, actual financing/roll/borrow costs, and a preregistered evaluation without retuning to that period.
