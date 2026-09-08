"""How much of the recall ceiling is metrology rather than algorithm?

    python -m src.sensitivity

The committed dataset assigns a flat 1.5% measurement noise to all four
parameters. That is a simplification, and a consequential one: on a real ATE
socket, relative repeatability on timing and voltage is far better than on
currents, which span decades. The flat figure therefore understates how well
timing-carried defects could be screened, and it is the binding constraint on
recall (rule 14).

This module re-runs the SAME physics, the SAME seed and the SAME scoring
pipeline under alternative noise assumptions, and reports what changes.

What it deliberately does NOT do
--------------------------------
It does not modify data/. Every run writes to a temporary directory and deletes
it. The committed dataset is what every reported number and every slide is
built on, and regenerating it mid-build would invalidate all of them.

More importantly: tuning a dataset until the method scores better is exactly
what a reviewer should be suspicious of, and there would be no clean way to
prove it had not been done iteratively. So the headline numbers stay on the
committed 1.5% data, and this runs alongside as a stated, reproducible
sensitivity analysis with its assumption written on the slide.

The claim it supports
---------------------
Recall on Tpd/Vol-carried defects is 0.24-0.38 at 1.5% measurement noise and
approaches 1.0 at 0.4%. The blind spot is a metrology limit, not an algorithm
limit. To catch timing-carried latent defects, invest in tester repeatability -
a better model cannot recover signal that was never measured.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import pandas as pd

from src.evaluate import pr_auc, recall_at_overkill
from src.features import PARAM_NAMES, build_features
from src.generate_burnin_dataset import MEAS_NOISE, build
from src.module_a import dpat_score, pooled_evidence_score

__all__ = ["NOISE_MODELS", "run_noise_model", "sensitivity_table", "main"]

# Named assumptions, so a slide can cite one by name.
NOISE_MODELS: dict[str, dict] = {
    "flat 1.5% (committed dataset)": {},
    "1.5% currents / 0.8% timing+voltage": {"Tpd_ns": 0.008, "Vol_mV": 0.008},
    "1.5% currents / 0.4% timing+voltage": {"Tpd_ns": 0.004, "Vol_mV": 0.004},
    "0.4% all parameters": {p: 0.004 for p in PARAM_NAMES},
}


def run_noise_model(noise: dict, seed: int = 42) -> dict:
    """Regenerate under `noise`, score it, return the metrics.

    Writes to a temporary directory that is always removed, so data/ is never
    touched whatever happens.
    """
    tmp = Path(tempfile.mkdtemp(prefix="sentinel_sens_"))
    try:
        build(outdir=tmp, noise=noise, seed=seed, verbose=False)
        df = pd.read_csv(tmp / "burnin_wide.csv")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    feat = build_features(df)
    y = df.is_latent_defect.to_numpy()
    healthy = (df.true_class == "healthy").to_numpy()
    score = pooled_evidence_score(feat).fillna(0.0).to_numpy()

    # Recall on defects carried by the low-drift parameters, at a 10% budget.
    from src.diagnose_why import recall_by_carrying_parameter
    thr = recall_at_overkill(y, score, 0.10, healthy)["threshold"]
    by_param = recall_by_carrying_parameter(
        df, pd.Series(score, index=df.index), thr, feat)

    return dict(
        pr_auc=pr_auc(y, score),
        recall_at_5=recall_at_overkill(y, score, 0.05, healthy)["recall"],
        recall_at_10=recall_at_overkill(y, score, 0.10, healthy)["recall"],
        recall_timing=float(by_param.loc[
            [p for p in by_param.index if p in ("Tpd_ns", "Vol_mV")], "caught"].sum()
            / max(by_param.loc[
                [p for p in by_param.index if p in ("Tpd_ns", "Vol_mV")],
                ["caught", "missed"]].to_numpy().sum(), 1)),
        recall_currents=float(by_param.loc[
            [p for p in by_param.index if p in ("Iddq_uA", "Ileak_nA")], "caught"].sum()
            / max(by_param.loc[
                [p for p in by_param.index if p in ("Iddq_uA", "Ileak_nA")],
                ["caught", "missed"]].to_numpy().sum(), 1)),
        n_latent=int(y.sum()),
    )


def sensitivity_table(models: dict | None = None) -> pd.DataFrame:
    models = NOISE_MODELS if models is None else models
    rows = {name: run_noise_model(noise) for name, noise in models.items()}
    return pd.DataFrame(rows).T


def main() -> None:
    print("SENSITIVITY ANALYSIS - how much of the recall ceiling is metrology?\n")
    print("Same physics, same seed 42, same L3 score. Only ATE repeatability")
    print("changes. data/ is NOT modified - each run uses a temp directory.\n")

    t = sensitivity_table()
    show = t.rename(columns={
        "pr_auc": "PR-AUC", "recall_at_5": "R@5%", "recall_at_10": "R@10%",
        "recall_timing": "R Tpd/Vol", "recall_currents": "R Iddq/Ileak",
    })[["PR-AUC", "R@5%", "R@10%", "R Tpd/Vol", "R Iddq/Ileak"]]
    print(show.round(3).to_string())

    base = t.loc["flat 1.5% (committed dataset)"]
    best = t.loc["1.5% currents / 0.4% timing+voltage"]
    print(f"\nHeadline: recall on timing/voltage-carried defects goes "
          f"{base.recall_timing:.2f} -> {best.recall_timing:.2f} "
          f"when timing repeatability improves from "
          f"{100*MEAS_NOISE:.1f}% to 0.4%,")
    print("with the model, the features and the threshold policy all unchanged.")
    print("\nThe blind spot is a metrology limit, not an algorithm limit. To catch")
    print("timing-carried latent defects, invest in tester repeatability - a better")
    print("model cannot recover signal that was never measured.")
    print("\nAll reported headline numbers use the committed flat-1.5% dataset.")


if __name__ == "__main__":
    main()
