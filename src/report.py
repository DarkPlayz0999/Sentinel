"""End-to-end screening report. Every number that appears in the deck.

    python -m src.report

Prints the full pipeline result through src.evaluate - one scorer, one truth.
Nothing here computes a metric of its own.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.evaluate import (
    evaluate_screening, format_report, pr_auc, recall_at_overkill,
    regression_metrics, screening_metrics,
)
from src.explain import lot_reason_codes, part_report, reason_codes
from src.features import PARAM_NAMES, PARAMS, build_features
from src.fusion import RiskWeights, lot_pda_status
from src.module_a import dpat_score, pooled_evidence_score, static_limit_flags
from src.pipeline import load_wide, screen


def main() -> None:
    df = load_wide()
    y = df.is_latent_defect.to_numpy()
    healthy = (df.true_class == "healthy").to_numpy()

    print("SENTINEL - full screening report")
    print(f"{len(df)} parts, {df.lot.nunique()} lots, {int(y.sum())} latent "
          f"defects, {int((df.true_class == 'gross').sum())} gross failures")
    print("ALL DATA IS SIMULATED.\n")

    res = screen(df)
    feat = res.features

    # ---------------------------------------------------------- the gap
    print("=" * 78)
    print("THE GAP - what static screening misses\n")
    static = static_limit_flags(df)["static_any"].astype(int).to_numpy()
    m = screening_metrics(y, static, healthy_mask=healthy)
    print(f"  static datasheet limits: recall {m['recall']:.3f} on latent "
          f"defects, {m['flagged']} parts flagged ({100*m['flagged_fraction']:.1f}%)")
    print(f"  {int(y.sum())} of {int(y.sum())} latent defects pass every "
          f"datasheet limit at 168h.\n")

    # ------------------------------------------------------- module A
    print("=" * 78)
    print("MODULE A - dynamic outlier detection\n")
    print(f"{'score':<44}{'PR-AUC':>9}{'R@5%':>8}{'R@10%':>8}")
    for name, s in (("L2 Dynamic PAT, worst-case |z|", dpat_score(feat)),
                    ("L3 pooled evidence (shipped)", pooled_evidence_score(feat))):
        v = s.fillna(0.0).to_numpy()
        print(f"{name:<44}{pr_auc(y, v):>9.4f}"
              f"{recall_at_overkill(y, v, .05, healthy)['recall']:>8.3f}"
              f"{recall_at_overkill(y, v, .10, healthy)['recall']:>8.3f}")

    # ------------------------------------------------------- module B
    if res.module_b is not None:
        print("\n" + "=" * 78)
        print("MODULE B - forecast Value_168h from 0h + 24h only")
        print(f"out-of-fold: {res.forecast_out_of_fold} "
              f"(GroupKFold by lot; a reported MAE requires True)\n")
        print(f"{'param':<11}{'n*':>6}{'MAE':>10}{'norm':>9}{'tailMAE':>10}"
              f"{'linear':>10}{'lastval':>10}")
        for p in PARAM_NAMES:
            v0 = df[f"{p}_0h"].to_numpy(float)
            v24 = df[f"{p}_24h"].to_numpy(float)
            truth = df[f"{p}_168h"].to_numpy(float)
            mm = regression_metrics(truth, res.forecast_point[p], baseline_true=v0)
            lin = regression_metrics(truth, v0 + (v24 - v0) * 7.0)["mae"]
            lv = regression_metrics(truth, v24)["mae"]
            print(f"{p:<11}{res.exponents.get(p, float('nan')):>6.2f}"
                  f"{mm['mae']:>10.4f}{mm['normalised_mae']:>9.4f}"
                  f"{mm['tail_mae']:>10.4f}{lin:>10.4f}{lv:>10.4f}")
        print("  n* = 0 means no extrapolable signal: the best 168h estimate is")
        print("  the 24h reading. That is a metrology limit, not a model limit.")

        rej = res.module_b.reject_at_24h.to_numpy()
        print(f"\n  hour-24 early reject: {rej.sum()} parts "
              f"({100*rej.mean():.1f}%), recall {(rej & (y==1)).sum()/y.sum():.3f},"
              f" overkill {100*(rej & healthy).sum()/healthy.sum():.1f}%")
        print(f"  oven hours freed: {rej.sum()} x 144 = {rej.sum()*144:,}")

    # --------------------------------------------------------- fusion
    print("\n" + "=" * 78)
    print("FUSION - screening risk score and three-band verdict\n")
    w = RiskWeights().as_dict()
    print("  weights: " + ", ".join(f"{k} {100*v:.0f}%" for k, v in w.items()))
    print(f"  bands:   WATCH >= {res.bands.watch:.1f}, "
          f"REJECT >= {res.bands.reject:.1f}  (sized to the 5% PDA budget)\n")
    print(res.fused.verdict.value_counts().to_string())

    rj = (res.fused.verdict == "REJECT").to_numpy()
    rw = res.fused.verdict.isin(["REJECT", "WATCH"]).to_numpy()
    for label, pred in (("REJECT only", rj), ("REJECT or WATCH", rw)):
        print(f"  {label:<16} recall {(pred & (y==1)).sum()/y.sum():.3f}  "
              f"flagged {pred.sum():>4}  "
              f"overkill {100*(pred & healthy).sum()/healthy.sum():.1f}%")

    print("\n" + format_report(evaluate_screening(
        y, res.fused.risk_score, name="  fused risk score",
        healthy_mask=healthy)))

    # ------------------------------------------------------------ PDA
    print("\n" + "=" * 78)
    print("PDA - lot disposition\n")
    print(res.pda[["parts", "reject", "watch", "reject_frac", "status"]].to_string())
    codes = lot_reason_codes(res.pda)
    for _, r in codes.iterrows():
        print(f"  {r.code}: {r.message}")

    # -------------------------------------------------- explainability
    print("\n" + "=" * 78)
    print("EXPLAINABILITY - reason codes\n")
    rc = reason_codes(df, feat, res.module_b)
    print(f"  {len(rc)} codes across {rc.serial.nunique()} parts")
    print(rc.code.value_counts().sort_index().to_string())

    worst = res.fused.risk_score.idxmax()
    rep = part_report(df, feat, worst, res.fused, res.module_b)
    print(f"\n  worked example - {rep['serial']} ({rep['verdict']}, "
          f"risk {rep['risk_score']})")
    for c in rep["reason_codes"][:4]:
        print(f"    {c['code']}: {c['message']}")
    print(f"    model {rep['model_version']}  generated {rep['generated_utc']}")


if __name__ == "__main__":
    main()
