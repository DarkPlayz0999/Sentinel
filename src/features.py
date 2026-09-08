"""Feature engineering - THE single definition of every feature.

Rule 8 of CLAUDE.md: feature logic lives only here. Training, evaluation, the
API and the dashboard all import from this module. Never inline feature code in
a notebook or an endpoint; a feature computed two ways is a feature you cannot
trust.

Contract
--------
build_features(df) -> pd.DataFrame
    Input : the wide burn-in frame (one row per part) as written by
            generate_burnin_dataset.py. Must contain `serial`, `lot`, and
            {PARAM}_{0,24,96,168}h columns.
    Output: one row per part, indexed identically to the input, containing only
            engineered features. No labels; nothing that leaks a 168h value
            into the feature set Module B is allowed to see at hour 24.

Invariants this module must uphold
----------------------------------
* Currents (Iddq_uA, Ileak_nA) are log-transformed before any statistic.
  Timing/voltage (Tpd_ns, Vol_mV) are used raw.
* Every statistic is computed within a lot (groupby("lot")), never globally.
* Robust location and spread only: median and 1.4826 * MAD. Never mean/std.
* Higher is worse for every parameter in this dataset, so one-sided logic is
  acceptable - but say so in the comment where it is used.
* Feature names are frozen once agreed. Half of all hackathon merge conflicts
  are column names.

Planned feature views (blueprint 7, layer L2)
---------------------------------------------
    z_{param}_level       robust z of the level at 0h / 168h
    z_{param}_early       robust z of (V_24h - V_0h)      <- Module B's input
    z_{param}_drift       robust z of (V_168h - V_0h)
    z_{param}_curvature   robust z of (V_168h - V_96h) / (V_24h - V_0h)

Everything here must be computable at inference time from the lot in front of
you. Per-lot statistics are unsupervised and may legitimately be recomputed on
test data; no supervised quantity may be.

TODO: implement. Requires a test (definition of done).
"""
