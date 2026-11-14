# Quant Lab 2

An independent audit and repair of [971jawad/quant-lab](https://github.com/971jawad/quant-lab), based on commit `943f322`. The original repository is unchanged.

**What it does:** builds daily research targets, simulates next-open execution with transaction costs and marked-to-market P&L, checks data integrity, and generates a dashboard.

**Does it have an edge?** A durable tradable edge is **not established**. In the corrected nine-leg simulation through 2026-11-13, full-sample Sharpe is **0.36**, CAGR **2.47%**, and maximum drawdown **−20.90%**. The reused July 2022 onward evaluation has Sharpe **0.97**. The full-sample Sharpe's descriptive 95% block-bootstrap interval is **−0.21 to 0.91**, and excess return over simple momentum is not statistically distinguished from zero. See [AUDIT.md](AUDIT.md) for interpretation and limitations.

These are a new simulation, not a revalidation of the original ten-leg champion. The unverified event leg is excluded. The code places no orders and these figures do not include verified financing, borrow, futures rolls, real broker fills, or interest on cash. No pristine holdout remains in the existing data.

## Run locally

Python 3.12 is the tested runtime. No credentials or network access are needed for an offline rebuild.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-lock.txt
python -m pytest -q
python run_quant_lab2.py
python verify_quant_lab2.py
# Optional browser check: install Chromium with python -m playwright install chromium
python tests/browser_smoke.py
python -m http.server 8765 --directory docs
```

Open `http://localhost:8765`. Serve the directory over HTTP; opening the HTML directly cannot reliably fetch its JSON report.

The report is written to `docs/data.json`. Detailed returns, market contributions, target history, simulated fills and the benchmark are written to `artifacts/`. Build and verification commands exit nonzero on accounting failures. `--require-fresh` also fails on stale inputs or a risk halt.

## Refresh external data

```bash
python run_live_update.py
python run_refresh_cot.py
python run_quant_lab2.py --record-snapshot
python verify_quant_lab2.py
```

Each refresh preserves existing completed observations. A refused source returns nonzero; you can still rebuild an honestly degraded report from valid available data. As of this audit, six of seven price feeds update. WTI remains stale because its Yahoo return correlation fails the guard (0.336 versus the 0.70 minimum). Do not weaken that guard to make the report green.

The COT refresher updates the table the model actually consumes, using the consolidated Nasdaq contract code. Survey dates still lack verified historical release timestamps. The model's default Tuesday + 6 day availability assumption is explicitly provisional.

The scheduled workflow runs at 06:00 UTC Monday–Saturday, after the preceding ET calendar day has finished. It tests before building and surfaces source failures even when it saves a degraded dashboard. It does not deploy a website or place orders. Forward snapshots record when targets were observed; they are never called executions.

## Design and evidence

- [Audit, measured results and outstanding issues](AUDIT.md)
- [Quant Lab 2 model specification](research/QUANT_LAB2_SPEC.md)
- `qlab/production.py`: causal decisions, execution, costs, allocation and risk state
- `qlab/evidence.py`: descriptive paired block-bootstrap checks
- `tests/`: accounting, chronology, data integrity and regression coverage
- `verify_quant_lab2.py`: independent report/artifact reconciliation
- `requirements-lock.txt`: tested dependency versions

`run_ensembler.py`, `build_site.py` and `run_verify.py` now invoke the new pipeline/checks. Legacy pick/trade exporters are retired because their reconstructed history was misleading. Other `run_*.py`, `results*`, weights, and older `research/` reports remain **historical research material**, not certified outputs of Quant Lab 2. Their old performance claims do not carry over. The old README is retained in `research/README_original.md`; the full original code remains in Git history.

The code inherited the original project's MIT licence declaration. Market data remains subject to its providers' terms.
