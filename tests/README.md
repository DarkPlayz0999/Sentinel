# Tests

Run from the repo root:

```
python -m pytest tests/ -q
```

`pytest.ini` puts the repo root on `sys.path`, so tests import as
`from src.features import ...`.

## What must have a test

Per the definition of done in `CLAUDE.md`, a change needs a test if it touches
`src/features.py` or `src/evaluate.py`. Those two modules are the ones every
other module trusts: features because training and inference must compute them
identically, and evaluate because it is the only source of any number that
reaches a slide.

Planned files:

| File | Covers |
|---|---|
| `test_features.py` | log-transform applied to currents only; per-lot grouping; robust z equals 0 at the lot median; no NaN leakage from the dropped 96h reads; feature names stable |
| `test_evaluate.py` | recall/precision/F-beta against hand-computed confusion matrices; cost-minimising threshold picks the known argmin; `GroupKFold` never puts one lot on both sides of a split |
| `test_module_b.py` | the power-law forecast reproduces `X_168 = X_0 * (1 + A)` for a synthetic part with known `A` and `n` |

Keep at least one test that asserts a mean/std-based limit is *not* used on the
current parameters — the domain rule most likely to be violated by accident.
