"""Baseline for Module A. Run AFTER generate_burnin_dataset.py.

    python src/baseline.py

The hour-6 checkpoint and the number every fancier model must beat (rule 9).
Deliberately simple and fully explainable.

Rewritten from the version shipped with the blueprint so that it obeys the
repo's own rules: features come from src.features and metrics come from
src.evaluate. The original computed both inline, which is exactly the
duplication rule 8 exists to prevent - two definitions of robust_z drift apart
and then nobody can say which number is real.

Two scores are reported:

    blueprint parity   the four views the shipped baseline used - level at 0h
                       and 168h, early delta, total drift. This is what the
                       blueprint's section 12 table was measured on, so it is
                       the number to check reproduction against.
    with curvature     the same four views plus the acceleration ratio that
                       features.py adds. The blueprint predicts univariate
                       robust z plateaus near 0.65 recall; this shows where the
                       plateau actually sits once curvature is included.

Both aggregate the same way the blueprint's reference snippet does - worst-case
|z| across every parameter and view. Absolute value, not one-sided, even though
higher is worse for every parameter here (rule 4): a part that is abnormally
LOW on a current is usually a different defect, not a healthy part, and the
baseline's job is to be the dumb honest reference rather than the tuned one.
"""

from pathlib import Path

import pandas as pd

from src.evaluate import (
    evaluate_screening,
    format_report,
    recall_at_overkill,
    screening_metrics,
)
from src.features import build_features

DATA = Path(__file__).resolve().parent.parent / "data" / "burnin_wide.csv"

# The blueprint's section 12 table was measured on these four views.
PARITY_VIEWS = ("level_0h", "level_168h", "early", "drift")


def worst_case_z(feat: pd.DataFrame, views: tuple[str, ...] | None = None) -> pd.Series:
    """Worst-case |robust z| across parameters and views.

    skipna is deliberate: a part with a dropped 96h read has no curvature, and
    it must still get a score from its remaining views rather than falling out
    of the screen entirely.
    """
    cols = [c for c in feat.columns if c.startswith("z_")]
    if views is not None:
        cols = [c for c in cols if any(c.endswith(f"_{v}") for v in views)]
    if not cols:
        raise ValueError(f"no z-columns matched views={views}")
    return feat[cols].abs().max(axis=1, skipna=True)


def main() -> None:
    if not DATA.exists():
        raise SystemExit(
            f"{DATA} not found. Run:  python src/generate_burnin_dataset.py"
        )

    df = pd.read_csv(DATA)
    y = df.is_latent_defect.to_numpy()
    healthy = (df.true_class == "healthy").to_numpy()

    print(f"parts {len(df)}   lots {df.lot.nunique()}   "
          f"latent {int(y.sum())}   gross {int((df.true_class == 'gross').sum())}")
    print("overkill is measured against healthy parts only - flagging a gross "
          "failure is correct behaviour, not over-rejection.\n")

    # ---------------------------------------------------- L1: static limits
    # The baseline we exist to beat. Kept in the pipeline forever because the
    # demo needs to show it catching nothing.
    static = df.static_fail_168h.to_numpy()
    m = screening_metrics(y, static, healthy_mask=healthy)
    print("L1  static datasheet limits")
    print(f"      recall {m['recall']:.3f}   flagged {m['flagged']} "
          f"({100 * m['flagged_fraction']:.1f}%)   "
          f"overkill {100 * m['overkill_rate']:.1f}%")
    print("      ^ every one of the 174 latent defects passes the datasheet at "
          "168h. This is the gap.\n")

    # ---------------------------------------------------- L2: Dynamic PAT
    feat = build_features(df)

    for label, views in (("blueprint parity (4 views)", PARITY_VIEWS),
                         ("with curvature (5 views)", None)):
        score = worst_case_z(feat, views)
        print(f"L2  Dynamic PAT robust |z| - {label}")
        for k in (8.0, 6.0, 4.5):
            r = evaluate_screening(y, score, threshold=k, name=f"|z| >= {k}",
                                   healthy_mask=healthy)
            mm = r.metrics
            print(f"      |z|>={k:<4} recall {mm['recall']:.3f}  "
                  f"precision {mm['precision']:.3f}  F2 {mm['f_beta']:.3f}  "
                  f"flagged {mm['flagged']:>4} ({100 * mm['flagged_fraction']:.1f}%)  "
                  f"overkill {100 * mm['overkill_rate']:.1f}%")

        full = evaluate_screening(y, score, name=label, healthy_mask=healthy)
        print(f"      PR-AUC {full.pr_auc:.3f}")
        for budget in (0.05, 0.10):
            b = recall_at_overkill(y, score, budget=budget, healthy_mask=healthy)
            state = (f"recall {b['recall']:.3f} at |z|>={b['threshold']:.2f}"
                     if b["feasible"] else "infeasible")
            print(f"      recall @ {100 * budget:>2.0f}% overkill budget: {state}")
        print()

    # ------------------------------------------- cost-optimal operating point
    score = worst_case_z(feat)
    print("cost-minimising threshold on the full feature set (C_FN/C_FP = 100)")
    print(format_report(evaluate_screening(
        y, score, name="  DPAT worst-case |z|", healthy_mask=healthy)))
    print("\nTarget: recall > 0.85 at overkill < 10%. Univariate robust z is "
          "expected to plateau\nwell short of that - roughly a third of latent "
          "defects are subtle in every single\ndimension and only visible as a "
          "combination. That is Module A's L3 job.")


if __name__ == "__main__":
    main()
