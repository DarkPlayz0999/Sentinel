"""Explainability - reason codes, attributions, and the plot that sells it.

A third of the marking scheme, and the cheapest third to win. The audience is a
QA inspector who must be able to sign the verdict, not an ML engineer.

Reason codes (rule 12: every flag emits one, containing the ACTUAL value and
the LOT reference value, in inspector-facing English):

    R-101  robust_z(level) > 6 on any parameter
    R-201  robust_z(early delta) > 5
    R-301  predicted slope > safety slope
    R-401  Mahalanobis > chi2(0.999)
    R-501  curvature ratio > 2
    R-601  lot-level: flagged fraction > PDA

Codes are emitted from RULES, not from a model - they must be reproducible and
auditable. SHAP is supporting evidence, not the justification. Worked example
of the register a code should be written in:

    R-101  "Iddq at 168h is 8.4 robust sigma above the lot median (31.2 uA vs
            lot median 10.4 uA). Within the datasheet limit of 50 uA but
            abnormal for this lot."

Also owns:
    * the per-part drift plot - four read points against the lot's 5th-95th
      percentile envelope, the Module B forecast dashed out to 168h, the
      datasheet USL as a red line. One glance and the part is visibly walking
      out of the herd. The most persuasive artefact in the demo.
    * SHAP TreeExplainer waterfall for the boosted sub-scores. For the robust-z
      layers attribution is free: the contribution IS the z-score.
    * the one-page signed screening report - serial, lot, verdict, risk score,
      reason codes, plot, measured values against lot statistics, model version
      and timestamp. Traceability is a hard requirement in real hi-rel QA.

TODO: implement.
"""
