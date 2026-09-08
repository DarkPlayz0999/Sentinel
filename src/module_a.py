"""Module A - dynamic outlier detection.

Flags parts that are abnormal relative to their own lot, not relative to the
datasheet. Four layers, each independently runnable and independently
demonstrable:

    L1  static datasheet limits   the baseline we exist to beat. Keep it in the
                                  pipeline forever - the demo needs to show it
                                  catching approximately none of the latent
                                  defects.
    L2  Dynamic PAT               robust z per lot, per parameter, per view.
                                  Limits = median +/- k * 1.4826 * MAD, k tuned
                                  on the FN-weighted metric (typically 4.5-6).
    L3  multivariate              robust Mahalanobis (MinCovDet) on the delta
                                  vector, per lot; distance decomposed per
                                  parameter so every flag can name its axis.
    L4  supervised ensemble       gradient-boosted classifier over the full
                                  feature set, blended with the L2 and L3
                                  scores. Blend weights are reported, not
                                  hidden - showing them is an explainability
                                  win in itself.

Consumes features from src.features only. Emits per-part sub-scores, never a
verdict - the verdict is assembled in src.fusion.

Univariate robust z alone plateaus near 0.65 recall: roughly a third of latent
defects are subtle in every single dimension and only visible as a combination.
L3 is what lifts it.

TODO: implement, L1 and L2 first. Numbers to beat are in src/baseline.py and
blueprint section 12.
"""
