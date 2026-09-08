"""Fusion - the 0-100 Screening Risk Score and the three-band verdict.

Rule 11 of CLAUDE.md: the top-level verdict is a weighted sum of NAMED
sub-scores, never a raw model output. ML improves the sub-scores; it does not
make the decision. The weights are visible, tunable, and defensible in a design
review.

    Screening Risk Score =
        30% * static_margin_score     how close to the datasheet limit at 168h
      + 25% * dynamic_outlier_score   max robust |z| across params/views, capped
      + 20% * predicted_drift_score   predicted slope / safety slope, capped
      + 15% * multivariate_score      robust Mahalanobis distance percentile
      + 10% * curvature_score         late drift / early drift

    Verdict bands (tunable - the tuning is the point):
        0-39     ACCEPT   ship
        40-69    WATCH    ship with the serial flagged for extra scrutiny
        70-100   REJECT   remove from the lot before final electrical test

The three-band verdict beats a binary flag: it matches how QA actually
operates, and it softens the overkill cost.

Band edges are not magic numbers. They follow from minimising
C_FN * FN + C_FP * FP with C_FN/C_FP = 100 by default (rule 7), and the ratio is
exposed as a slider rather than hard-coded. The PDA gate - more than ~5% of a
lot flagged triggers lot review - caps how aggressive the policy may be.

TODO: implement.
"""
