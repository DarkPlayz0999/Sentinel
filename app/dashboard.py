"""Streamlit QA-inspector dashboard.

    streamlit run app/dashboard.py

Renders only. Every number comes from src.pipeline / src.evaluate - nothing is
computed here, so what the inspector sees is what the API returns.

Screens, in the order the demo walks them:

    Lot Overview        lot cards, PDA status, the bad lot standing out
    Part Table          sortable by risk, colour-coded verdict chips
    Part Detail         the drift plot with lot envelope and forecast, the risk
                        breakdown, the reason codes
    Distributions       per-parameter histogram, log and linear, with DPAT and
                        datasheet limits overlaid
    Model Performance   confusion matrix, recall-vs-overkill curve, MAE table
    Decision Policy     the cost-ratio slider. The demo centrepiece.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.evaluate import (                                        # noqa: E402
    cost_minimising_threshold, pr_auc, recall_overkill_curve,
    regression_metrics, screening_metrics,
)
from src.explain import drift_plot, reason_codes_for_part          # noqa: E402
from src.features import PARAMS, PARAM_NAMES, dpat_limits, transform  # noqa: E402
from src.fusion import Bands, RiskWeights, bands_for_pda, fuse, lot_pda_status  # noqa: E402
from src.pipeline import load_wide, screen                        # noqa: E402

st.set_page_config(page_title="SENTINEL", page_icon="🛰", layout="wide")

VERDICT_COLOUR = {"ACCEPT": "#1a7f37", "WATCH": "#bf8700", "REJECT": "#cf222e"}


@st.cache_data(show_spinner="Screening the lot…")
def _load():
    df = load_wide()
    return df, screen(df)


try:
    df, res = _load()
except SystemExit as exc:
    st.error(str(exc))
    st.stop()

y = df.is_latent_defect.to_numpy()
healthy = (df.true_class == "healthy").to_numpy()

st.sidebar.title("SENTINEL")
st.sidebar.caption("Explainable burn-in screening. **All data is simulated.**")
page = st.sidebar.radio("Screen", [
    "Lot Overview", "Part Table", "Part Detail", "Distributions",
    "Model Performance", "Decision Policy"])
st.sidebar.metric("Parts screened", len(df))
st.sidebar.metric("Latent defects (ground truth)", int(y.sum()))
st.sidebar.caption(f"bands: WATCH ≥ {res.bands.watch:.1f}, "
                   f"REJECT ≥ {res.bands.reject:.1f}")


# ------------------------------------------------------------ lot overview
if page == "Lot Overview":
    st.title("Lot overview")
    st.caption("Only REJECT counts against the PDA gate. WATCH parts ship with "
               "the serial flagged, so they do not consume PDA budget.")

    cols = st.columns(len(res.pda))
    for col, (lot, r) in zip(cols, res.pda.iterrows()):
        with col:
            st.metric(lot, f"{100 * r.reject_frac:.1f}%",
                      delta=f"{int(r.reject)} rejected",
                      delta_color="inverse")
            st.caption(f"{int(r.watch)} watch · mean risk {r.mean_risk:.0f}")
            if r.status == "LOT REVIEW":
                st.error("R-601 · exceeds PDA")
            else:
                st.success("within PDA")

    st.dataframe(res.pda, use_container_width=True)
    st.info("L04 is the deliberately bad lot: shifted centre, 1.45× spread and "
            "3× the defect rate. The screen finds it without being told.")


# -------------------------------------------------------------- part table
elif page == "Part Table":
    st.title("Parts by screening risk")
    c1, c2 = st.columns([1, 3])
    with c1:
        lots = st.multiselect("Lot", sorted(df.lot.unique()),
                              default=sorted(df.lot.unique()))
        verdicts = st.multiselect("Verdict", ["REJECT", "WATCH", "ACCEPT"],
                                  default=["REJECT", "WATCH"])
    tab = res.fused[res.fused.lot.isin(lots) & res.fused.verdict.isin(verdicts)]
    tab = tab.sort_values("risk_score", ascending=False)
    with c2:
        st.caption(f"{len(tab)} parts")
        st.dataframe(
            tab[["serial", "lot", "verdict", "risk_score", "static_margin",
                 "dynamic_outlier", "predicted_drift", "multivariate",
                 "curvature"]].round(1),
            use_container_width=True, height=560)


# ------------------------------------------------------------- part detail
elif page == "Part Detail":
    st.title("Part detail")
    ranked = res.fused.sort_values("risk_score", ascending=False)
    serial = st.selectbox("Serial", ranked.serial.tolist(), index=0)
    i = res.part(serial)
    row = res.fused.loc[i]

    c1, c2, c3 = st.columns([1, 1, 2])
    c1.metric("Risk score", f"{row.risk_score:.1f}")
    c2.markdown(
        f"<h3 style='color:{VERDICT_COLOUR[row.verdict]}'>{row.verdict}</h3>",
        unsafe_allow_html=True)
    c3.caption(f"lot {row.lot} · ground truth: **{df.at[i, 'true_class']}** "
               f"(shown for the demo only; the screen never sees it)")

    st.subheader("Risk score breakdown")
    w = RiskWeights().as_dict()
    breakdown = pd.DataFrame({
        "sub-score": list(w), "weight": list(w.values()),
        "value (0-100)": [round(float(row[k]), 1) for k in w],
    })
    breakdown["contribution"] = (breakdown["weight"]
                                 * breakdown["value (0-100)"]).round(1)
    st.dataframe(breakdown, use_container_width=True, hide_index=True)

    st.subheader("Reason codes")
    codes = reason_codes_for_part(df, res.features, i, res.module_b)
    if not codes:
        st.success("No reason codes — nothing abnormal for this lot.")
    for c in codes:
        st.markdown(f"**{c.code}** ({c.severity}) — {c.message}")

    st.subheader("Drift against the lot envelope")
    param = st.selectbox("Parameter", PARAM_NAMES)
    fc = (float(res.forecast_point.at[i, param])
          if param in res.forecast_point.columns else None)
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(8, 4.4))
    drift_plot(df, i, param, ax=ax, forecast_168=fc)
    st.pyplot(fig)


# ----------------------------------------------------------- distributions
elif page == "Distributions":
    st.title("Distribution explorer")
    st.caption("Currents are lognormal. On a linear axis the tail inflates σ "
               "and hides the outliers; on a log axis the DPAT limits bite.")
    param = st.selectbox("Parameter", PARAM_NAMES)
    lot = st.selectbox("Lot", sorted(df.lot.unique()))
    hours = st.select_slider("Read point", [0, 24, 96, 168], value=168)

    sub = df[df.lot == lot]
    vals = sub[f"{param}_{hours}h"].dropna()
    logscale = PARAMS[param]["is_current"]

    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(9, 4.2))
    t = transform(vals, param)
    ax.hist(t, bins=60, color="tab:blue", alpha=0.7)
    lo, hi = dpat_limits(t, k=6.0)
    ax.axvline(hi, color="darkorange", lw=2, label="DPAT +6 robust σ")
    usl_t = float(transform(pd.Series([PARAMS[param]["usl"]]), param).iloc[0])
    if usl_t <= t.max() * 1.6:
        ax.axvline(usl_t, color="crimson", lw=2, label="datasheet USL")
    ax.set_xlabel(f"{'log ' if logscale else ''}{param} "
                  f"({PARAMS[param]['unit']})")
    ax.set_ylabel("parts")
    ax.legend()
    st.pyplot(fig)

    n_over_dpat = int((t > hi).sum())
    n_over_usl = int((vals > PARAMS[param]["usl"]).sum())
    c1, c2 = st.columns(2)
    c1.metric("Beyond dynamic (DPAT) limit", n_over_dpat)
    c2.metric("Beyond datasheet limit", n_over_usl)


# ------------------------------------------------------ model performance
elif page == "Model Performance":
    st.title("Model performance")
    st.warning("Plain accuracy is not reported. ~8% of parts are defective, so "
               "predicting 'all good' scores 92% while catching nothing.")

    score = res.fused.risk_score
    thr = st.slider("Risk-score threshold", 0.0, 100.0,
                    float(res.bands.reject), 0.5)
    m = screening_metrics(y, (score >= thr).astype(int), healthy_mask=healthy)

    c = st.columns(5)
    c[0].metric("Recall", f"{m['recall']:.3f}")
    c[1].metric("Precision", f"{m['precision']:.3f}")
    c[2].metric("F2", f"{m['f_beta']:.3f}")
    c[3].metric("PR-AUC", f"{pr_auc(y, score):.3f}")
    c[4].metric("Overkill", f"{100 * m['overkill_rate']:.1f}%")

    st.subheader("Confusion matrix (real counts)")
    st.dataframe(pd.DataFrame(
        [[m["tn"], m["fp"]], [m["fn"], m["tp"]]],
        index=["actually good", "actually latent"],
        columns=["predicted good", "predicted defective"]),
        use_container_width=True)

    st.subheader("Recall vs overkill budget")
    curve = recall_overkill_curve(y, score.to_numpy(), healthy)
    st.line_chart(curve.set_index("overkill_rate")[["recall"]])

    if res.module_b is not None:
        st.subheader("Module B — MAE on Value_168h (out-of-fold, GroupKFold by lot)")
        rows = []
        for p in PARAM_NAMES:
            v0 = df[f"{p}_0h"].to_numpy(float)
            truth = df[f"{p}_168h"].to_numpy(float)
            mm = regression_metrics(truth, res.forecast_point[p], baseline_true=v0)
            rows.append(dict(parameter=p, unit=PARAMS[p]["unit"],
                             MAE=round(mm["mae"], 4),
                             normalised=round(mm["normalised_mae"], 4),
                             tail_MAE=round(mm["tail_mae"], 4),
                             n_star=round(res.exponents.get(p, float("nan")), 2)))
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        st.caption("n* = 0 means the fit found no extrapolable signal on that "
                   "axis: the best 168h estimate is the 24h reading.")


# ---------------------------------------------------------- decision policy
elif page == "Decision Policy":
    st.title("Decision policy")
    st.caption("A false negative is a dead satellite. A false positive is a "
               "$40 part. That ratio is a business decision, so it is a slider "
               "rather than a hard-coded constant.")

    ratio = st.slider("Cost ratio  C_FN : C_FP", 1, 500, 100, 1)
    score = res.fused.risk_score.to_numpy()
    best = cost_minimising_threshold(y, score, c_fn=float(ratio), c_fp=1.0,
                                     healthy_mask=healthy)

    c = st.columns(4)
    c[0].metric("Cost-optimal threshold", f"{best['threshold']:.1f}")
    c[1].metric("Recall", f"{best['recall']:.3f}")
    c[2].metric("Overkill", f"{100 * best['overkill_rate']:.1f}%")
    c[3].metric("Parts flagged", best["flagged"])

    if best["overkill_rate"] > 0.05:
        st.error(
            f"At {ratio}:1 the cost-optimal threshold flags "
            f"{100 * best['overkill_rate']:.0f}% of good parts — far beyond the "
            "5% PDA gate. Exceed the PDA and the whole lot goes to review, so "
            "this operating point scraps good lots rather than saving them. "
            "This is why the verdict has three bands: REJECT is sized to the "
            "PDA budget and WATCH absorbs the rest of the recall.")

    st.subheader("PDA-aware bands")
    target = st.slider("REJECT budget (PDA)", 0.01, 0.20, 0.05, 0.01)
    b = bands_for_pda(res.fused.risk_score, target_reject=target)
    retuned = fuse(df, res.features, res.module_b, bands=b)
    rej = (retuned.verdict == "REJECT").to_numpy()
    rw = retuned.verdict.isin(["REJECT", "WATCH"]).to_numpy()

    c = st.columns(4)
    c[0].metric("REJECT recall", f"{(rej & (y == 1)).sum() / y.sum():.3f}")
    c[1].metric("REJECT + WATCH recall", f"{(rw & (y == 1)).sum() / y.sum():.3f}")
    c[2].metric("REJECT overkill",
                f"{100 * (rej & healthy).sum() / healthy.sum():.1f}%")
    c[3].metric("Lots over PDA",
                int((lot_pda_status(retuned).status == "LOT REVIEW").sum()))
    st.dataframe(lot_pda_status(retuned), use_container_width=True)
