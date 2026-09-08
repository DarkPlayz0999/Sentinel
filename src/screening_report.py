"""One-page signed screening report per part, as a PDF.

    python -m src.screening_report                 # every REJECT, to reports/
    python -m src.screening_report L04-0262        # one part

Blueprint deliverable 11. Traceability is a hard requirement in real hi-rel QA:
a rejection has to produce a record a QA engineer could defend in a design
review, months later, without the notebook that made it.

Each page carries the serial, lot, verdict, risk score with its named sub-score
breakdown, the numbered reason codes in inspector-facing English, the measured
values against the lot medians, the drift plot with the lot envelope and the
Module B forecast, and the model version and UTC timestamp.

Nothing is computed here. Every number comes from src.pipeline, so the PDF, the
API and the dashboard cannot disagree about a part.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import matplotlib
import pandas as pd

matplotlib.use("Agg")                     # no display on a build box
import matplotlib.pyplot as plt           # noqa: E402

from reportlab.lib import colors           # noqa: E402
from reportlab.lib.pagesizes import A4     # noqa: E402
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet  # noqa: E402
from reportlab.lib.units import mm         # noqa: E402
from reportlab.platypus import (           # noqa: E402
    Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

from src.explain import MODEL_VERSION, drift_plot, reason_codes_for_part  # noqa: E402
from src.features import PARAMS, PARAM_NAMES                             # noqa: E402
from src.fusion import RiskWeights                                       # noqa: E402
from src.pipeline import ScreenResult, load_wide, screen                 # noqa: E402

__all__ = ["build_report", "build_reports", "REPORT_DIR"]

REPORT_DIR = Path(__file__).resolve().parent.parent / "reports"

# The report must fit ONE page - that is what makes it a signable record rather
# than a printout.
#
# Parts earn between 1 and 10 reason codes and the messages wrap unpredictably,
# so a fixed cap does not guarantee it: at 6 codes and a 66 mm plot, 56 of 105
# reports still spilled. Rather than guessing at sizes, the builder RENDERS and
# COUNTS, then shrinks and retries until the page count is 1. The invariant is
# enforced, not hoped for.
#
# Omitted codes are stated on the page; the complete set is always in the
# machine-readable record from GET /part/{serial}/report.
_LAYOUTS = [
    # (max reason codes, plot width mm, plot height mm)
    (6, 132, 66),
    (5, 126, 63),
    (4, 120, 60),
    (3, 112, 56),
    (2, 104, 52),
    (1, 96, 48),
]
MAX_CODES_ON_PAGE = _LAYOUTS[0][0]


class _PageCounter:
    """Counts rendered pages during build - no extra dependency needed."""

    def __init__(self):
        self.pages = 0

    def __call__(self, canvas, doc):
        self.pages += 1

VERDICT_COLOUR = {"ACCEPT": colors.HexColor("#1a7f37"),
                  "WATCH": colors.HexColor("#bf8700"),
                  "REJECT": colors.HexColor("#cf222e")}


def _styles():
    ss = getSampleStyleSheet()
    ss.add(ParagraphStyle("Small", parent=ss["Normal"], fontSize=7.5, leading=9.5))
    ss.add(ParagraphStyle("H", parent=ss["Heading2"], fontSize=10, spaceBefore=8,
                          spaceAfter=3, textColor=colors.HexColor("#24292f")))
    return ss


def _worst_param(df: pd.DataFrame, res: ScreenResult, i) -> str:
    """Which parameter to plot: the one the verdict actually turned on."""
    if res.module_b is not None and i in res.module_b.index:
        return str(res.module_b.at[i, "worst_param"])
    z = res.features.loc[i, [f"z_{p}_drift" for p in PARAM_NAMES
                             if f"z_{p}_drift" in res.features.columns]]
    return z.abs().idxmax().replace("z_", "").replace("_drift", "") if len(z) \
        else PARAM_NAMES[0]


def _drift_png(df: pd.DataFrame, res: ScreenResult, i, param: str,
               out: Path) -> Path:
    fc = (float(res.forecast_point.at[i, param])
          if param in getattr(res.forecast_point, "columns", []) else None)
    fig, ax = plt.subplots(figsize=(6.6, 3.3))
    drift_plot(df, i, param, ax=ax, forecast_168=fc)
    fig.tight_layout()
    fig.savefig(out, dpi=150)
    plt.close(fig)
    return out


def _build_once(df: pd.DataFrame, res: ScreenResult, i, out_dir: Path,
                layout: tuple[int, float, float]) -> tuple[Path, int]:
    """One render attempt. Returns (path, page count)."""
    max_codes, plot_w, plot_h = layout
    row = res.fused.loc[i]
    serial, lot, verdict = str(row.serial), str(row.lot), str(row.verdict)
    pdf_path = out_dir / f"screening_{serial}.pdf"

    ss = _styles()
    story = []

    # ---- header
    story.append(Paragraph(
        "<b>SENTINEL &mdash; Burn-In Screening Report</b>", ss["Title"]))
    story.append(Paragraph(
        "Environmental Stress Screening, 125 &deg;C burn-in, reads at "
        "0 / 24 / 96 / 168 h. <b>Simulated data.</b>", ss["Small"]))
    story.append(Spacer(1, 4 * mm))

    head = Table([
        ["Serial", serial, "Lot", lot],
        ["Verdict", verdict, "Risk score", f"{row.risk_score:.1f} / 100"],
        ["Model", MODEL_VERSION, "Generated (UTC)",
         datetime.now(timezone.utc).isoformat(timespec="seconds")],
    ], colWidths=[26 * mm, 58 * mm, 30 * mm, 56 * mm])
    head.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f6f8fa")),
        ("BACKGROUND", (2, 0), (2, -1), colors.HexColor("#f6f8fa")),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#d0d7de")),
        ("TEXTCOLOR", (1, 1), (1, 1), VERDICT_COLOUR[verdict]),
        ("FONTNAME", (1, 1), (1, 1), "Helvetica-Bold"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story.append(head)

    # ---- risk breakdown: the verdict is a weighted sum of NAMED sub-scores
    story.append(Paragraph("Screening risk score &mdash; weighted sub-scores", ss["H"]))
    w = RiskWeights().as_dict()
    rows = [["Sub-score", "Weight", "Value (0-100)", "Contribution"]]
    for k, weight in w.items():
        v = float(row[k]) if k in row.index else 0.0
        rows.append([k.replace("_", " "), f"{100 * weight:.0f}%",
                     f"{v:.1f}", f"{weight * v:.1f}"])
    rows.append(["", "", "Total", f"{row.risk_score:.1f}"])
    t = Table(rows, colWidths=[52 * mm, 22 * mm, 34 * mm, 32 * mm])
    t.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eaeef2")),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#d0d7de")),
        ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
    ]))
    story.append(t)

    # ---- reason codes
    codes = reason_codes_for_part(df, res.features, i, res.module_b)
    shown = codes[:max_codes]
    story.append(Paragraph(
        f"Reason codes ({len(codes)})" if len(codes) <= max_codes
        else f"Reason codes &mdash; {len(shown)} of {len(codes)}, worst first",
        ss["H"]))
    if not codes:
        story.append(Paragraph(
            "No reason codes. Nothing abnormal for this lot.", ss["Small"]))
    else:
        crows = [["Code", "Severity", "Finding"]]
        for c in shown:
            crows.append([c.code, c.severity,
                          Paragraph(c.message, ss["Small"])])
        ct = Table(crows, colWidths=[16 * mm, 18 * mm, 106 * mm])
        ct.setStyle(TableStyle([
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eaeef2")),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#d0d7de")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]))
        story.append(ct)
        if len(codes) > max_codes:
            story.append(Paragraph(
                f"<i>{len(codes) - max_codes} further code(s) omitted "
                f"for space; the complete set is in the machine-readable record "
                f"at GET /part/{serial}/report.</i>", ss["Small"]))

    # ---- measured values against the lot
    story.append(Paragraph(
        "Measured values against the lot &mdash; raw datasheet units", ss["H"]))
    lot_rows = df[df.lot == lot]
    mrows = [["Parameter", "0 h", "24 h", "96 h", "168 h",
              "Lot med 168 h", "USL", "Unit"]]
    for p in PARAM_NAMES:
        vals = []
        for h in (0, 24, 96, 168):
            col = f"{p}_{h}h"
            v = df.at[i, col] if col in df.columns else None
            vals.append("--" if v is None or pd.isna(v) else f"{v:.4g}")
        med = (f"{lot_rows[f'{p}_168h'].median():.4g}"
               if f"{p}_168h" in df.columns else "--")
        mrows.append([p] + vals + [med, f"{PARAMS[p]['usl']:g}",
                                   PARAMS[p]["unit"]])
    mt = Table(mrows, colWidths=[26 * mm, 19 * mm, 19 * mm, 19 * mm, 19 * mm,
                                 25 * mm, 16 * mm, 13 * mm])
    mt.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 7.5),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eaeef2")),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#d0d7de")),
        ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
    ]))
    story.append(mt)

    # ---- the plot that sells it
    param = _worst_param(df, res, i)
    story.append(Paragraph(
        f"Drift against the lot envelope &mdash; {param}", ss["H"]))
    png = _drift_png(df, res, i, param, out_dir / f".{serial}_{param}.png")
    story.append(Image(str(png), width=plot_w * mm, height=plot_h * mm))

    story.append(Spacer(1, 1.5 * mm))
    story.append(Paragraph(
        "Verdict bands: ACCEPT &lt; {:.0f} &le; WATCH &lt; {:.0f} &le; REJECT. "
        "Only REJECT counts against the {:.0f}% PDA gate. This screen adds "
        "rejections to the datasheet limits; it never removes one."
        .format(res.bands.watch, res.bands.reject, 100 * 0.05), ss["Small"]))

    counter = _PageCounter()
    SimpleDocTemplate(
        str(pdf_path), pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm,
        topMargin=11 * mm, bottomMargin=11 * mm,
        title=f"SENTINEL screening report {serial}",
        author=f"SENTINEL {MODEL_VERSION}",
    ).build(story, onFirstPage=counter, onLaterPages=counter)

    png.unlink(missing_ok=True)
    return pdf_path, counter.pages


def build_report(df: pd.DataFrame, res: ScreenResult, i,
                 out_dir: Path | str = REPORT_DIR) -> Path:
    """Render one part's screening report, guaranteed to be a single page.

    Renders, counts, shrinks and retries. The last layout is small enough that
    it always fits; if even that spilled we would rather raise than hand a QA
    engineer a two-page "one-page report".
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for layout in _LAYOUTS:
        path, pages = _build_once(df, res, i, out_dir, layout)
        if pages == 1:
            return path
    raise RuntimeError(
        f"screening report for {res.fused.at[i, 'serial']} still spans "
        f"{pages} pages at the smallest layout {_LAYOUTS[-1]}")


def build_reports(df: pd.DataFrame, res: ScreenResult, serials=None,
                  verdict: str | None = "REJECT", limit: int | None = None,
                  out_dir: Path | str = REPORT_DIR) -> list[Path]:
    """Render reports for a set of serials, or for every part with ``verdict``."""
    if serials is not None:
        idx = [res.part(s) for s in serials]
        if any(i is None for i in idx):
            missing = [s for s, i in zip(serials, idx) if i is None]
            raise KeyError(f"unknown serial(s): {missing}")
    else:
        sel = res.fused if verdict is None else res.fused[res.fused.verdict == verdict]
        idx = list(sel.sort_values("risk_score", ascending=False).index)
    if limit is not None:
        idx = idx[:limit]
    return [build_report(df, res, i, out_dir) for i in idx]


def main(argv: list[str]) -> None:
    df = load_wide()
    res = screen(df)
    if argv:
        paths = build_reports(df, res, serials=argv)
    else:
        paths = build_reports(df, res, verdict="REJECT")
        print(f"rendering every REJECT ({len(paths)} parts)")
    for p in paths[:10]:
        print("  ", p)
    if len(paths) > 10:
        print(f"   ... and {len(paths) - 10} more")
    print(f"\n{len(paths)} report(s) in {REPORT_DIR}")


if __name__ == "__main__":
    main(sys.argv[1:])
