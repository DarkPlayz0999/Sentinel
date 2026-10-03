"""Build the SIH 2026 idea deck (six slides) inside the official template.

    python tools/deck/build_deck.py --template <SIH2026-IDEA-Presentation-Format.pptx>
                                    [--team-name "..."] [--team-id "..."]
    -> var/deck/SENTINEL_SIH26170.pptx   (render/export: tools/deck/render.ps1)

Every figure on the slides comes from the running product or its evaluation:
  python -m src.report                     screening numbers (seed 42, simulated)
  python -m src.twin.experiments --kind ood --seed 42 --runs 28 --boards 150
  python -m src.realdata.evaluate          NASA capacitor / MOSFET checks
Screenshots in var/deck/img are captures of the live web console.

The template's six headings, logo, footer and team badge are kept; the
instructions slide is removed (the rules cap the deck at six slides).
"""

from __future__ import annotations

import argparse
import copy
from pathlib import Path

from lxml import etree
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_CONNECTOR, MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Inches, Pt

ROOT = Path(__file__).resolve().parents[2]
IMG = ROOT / "var" / "deck" / "img"
OUT = ROOT / "var" / "deck" / "SENTINEL_SIH26170.pptx"

# one neutral system; colour always carries meaning and is paired with a shape or a word
INK = RGBColor(0x0B, 0x1F, 0x3A)
GRAPHITE = RGBColor(0x4A, 0x55, 0x68)
RULE = RGBColor(0xD0, 0xD5, 0xDD)
PANEL = RGBColor(0xF4, 0xF6, 0xF9)
BLUE = RGBColor(0x1F, 0x5F, 0xAD)
RED = RGBColor(0xC8, 0x10, 0x2E)
AMBER = RGBColor(0xB7, 0x7B, 0x00)      # text-safe amber
GREEN = RGBColor(0x00, 0x87, 0x6C)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
DARK = RGBColor(0x0E, 0x17, 0x26)
SANS, SEMI, MONO = "Segoe UI", "Segoe UI Semibold", "Consolas"


# ------------------------------------------------------------------ helpers

def _runs(tf, paras, size=12, color=INK, font=SANS, align=PP_ALIGN.LEFT, space_after=2, line=1.05):
    """paras: list of paragraphs; a paragraph is a str or a list of (text, {style}) runs.
    Paragraph-level style may be given as a dict as the first element: [{"bullet": True}, ...]."""
    tf.clear()
    first = True
    for para in paras:
        p = tf.paragraphs[0] if first else tf.add_paragraph()
        first = False
        pstyle = {}
        if isinstance(para, list) and para and isinstance(para[0], dict):
            pstyle, para = para[0], para[1:]
        p.alignment = pstyle.get("align", align)
        p.space_after = Pt(pstyle.get("after", space_after))
        p.line_spacing = pstyle.get("line", line)
        if pstyle.get("indent_only"):
            pPr = p._p.get_or_add_pPr()
            pPr.set("marL", str(int(Inches(pstyle["indent_only"]))))
        if pstyle.get("bullet"):
            pPr = p._p.get_or_add_pPr()
            pPr.set("marL", str(int(Inches(pstyle.get("indent", 0.16)))))
            pPr.set("indent", str(-int(Inches(pstyle.get("indent", 0.16)))))
            bu = etree.SubElement(pPr, qn("a:buChar"))
            bu.set("char", pstyle.get("char", "•"))
        items = [(para, {})] if isinstance(para, str) else [(it, {}) if isinstance(it, str) else it for it in para]
        for text, st in items:
            r = p.add_run()
            r.text = text
            f = r.font
            f.size = Pt(st.get("size", pstyle.get("size", size)))
            f.bold = st.get("bold", pstyle.get("bold", False))
            f.italic = st.get("italic", False)
            f.name = st.get("font", pstyle.get("font", font))
            f.color.rgb = st.get("color", pstyle.get("color", color))
    return tf


def text(slide, x, y, w, h, paras, anchor=MSO_ANCHOR.TOP, margin=0.02, **kw):
    tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = anchor
    for side in ("left", "right", "top", "bottom"):
        setattr(tf, f"margin_{side}", Inches(margin))
    _runs(tf, paras, **kw)
    return tb


def box(slide, x, y, w, h, fill=PANEL, line=RULE, lw=0.75, shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.06,
        paras=None, anchor=MSO_ANCHOR.TOP, margin=0.08, **kw):
    s = slide.shapes.add_shape(shape, Inches(x), Inches(y), Inches(w), Inches(h))
    if shape == MSO_SHAPE.ROUNDED_RECTANGLE:
        s.adjustments[0] = radius
    if fill is None:
        s.fill.background()
    else:
        s.fill.solid()
        s.fill.fore_color.rgb = fill
    if line is None:
        s.line.fill.background()
    else:
        s.line.color.rgb = line
        s.line.width = Pt(lw)
    s.shadow.inherit = False
    tf = s.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = anchor
    for side in ("left", "right", "top", "bottom"):
        setattr(tf, f"margin_{side}", Inches(margin))
    if paras is not None:
        _runs(tf, paras, **kw)
    return s


def arrow(slide, x1, y1, x2, y2, color=GRAPHITE, w=1.5):
    c = slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, Inches(x1), Inches(y1), Inches(x2), Inches(y2))
    c.line.color.rgb = color
    c.line.width = Pt(w)
    ln = c.line._get_or_add_ln()
    tail = etree.SubElement(ln, qn("a:tailEnd"))
    tail.set("type", "triangle")
    tail.set("w", "med")
    tail.set("len", "med")
    return c


def pic(slide, name, x, y, w=None, h=None, border=True):
    p = slide.shapes.add_picture(str(IMG / name), Inches(x), Inches(y),
                                 Inches(w) if w else None, Inches(h) if h else None)
    if border:
        p.line.color.rgb = RULE
        p.line.width = Pt(0.75)
    return p


def chip(slide, x, y, label, color=INK, w=None, size=10):
    w = w or (0.12 + 0.075 * len(label))
    return box(slide, x, y, w, 0.27, fill=color, line=None, radius=0.3, margin=0.04,
               paras=[[{"align": PP_ALIGN.CENTER}, (label, {"bold": True, "color": WHITE, "size": size, "font": SEMI})]],
               anchor=MSO_ANCHOR.MIDDLE)


def label(slide, x, y, w, t, color=BLUE, size=11):
    """Small-caps style section label with a hairline under it."""
    text(slide, x, y, w, 0.26, [[(t.upper(), {"bold": True, "color": color, "size": size, "font": SEMI})]])
    ln = slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, Inches(x), Inches(y + 0.27), Inches(x + w), Inches(y + 0.27))
    ln.line.color.rgb = RULE
    ln.line.width = Pt(0.75)


def B(t, **st):
    return (t, {"bold": True, **st})


def M(t, **st):
    return (t, {"font": MONO, **st})


def bullets(lines, size=11, color=INK, after=3):
    out = []
    for ln in lines:
        runs = [(ln, {})] if isinstance(ln, str) else ln
        out.append([{"bullet": True, "size": size, "color": color, "after": after}, *runs])
    return out


def remove_slide(prs, index):
    sld = prs.slides._sldIdLst[index]
    prs.part.drop_rel(sld.get(qn("r:id")))
    prs.slides._sldIdLst.remove(sld)


def shape_named(slide, name):
    return next(s for s in slide.shapes if s.name == name)


def set_title(slide, t, size=None, left=None, width=None):
    title = slide.shapes.title
    tf = title.text_frame
    p = tf.paragraphs[0]
    run0 = copy.deepcopy(p.runs[0]._r) if p.runs else None
    for r in list(p.runs):
        p._p.remove(r._r)
    if run0 is not None:
        p._p.append(run0)
        p.runs[0].text = t
        if size:
            p.runs[0].font.size = Pt(size)
    else:
        p.text = t
    for extra in tf.paragraphs[1:]:
        extra._p.getparent().remove(extra._p)
    if left is not None:
        title.left = Inches(left)
    if width is not None:
        title.width = Inches(width)


def team_badge(slide, team_name):
    oval = next(s for s in slide.shapes if s.name.startswith("Oval"))
    tf = oval.text_frame
    p = tf.paragraphs[0]
    for r in p.runs[1:]:
        p._p.remove(r._r)
    for extra in tf.paragraphs[1:]:
        extra._p.getparent().remove(extra._p)
    p.runs[0].text = team_name
    p.runs[0].font.size = Pt(11)
    p.runs[0].font.bold = True


def drop_body(slide):
    body = next(s for s in slide.shapes if s.name == "TextBox 8")
    body._element.getparent().remove(body._element)


def footnote(slide, t):
    text(slide, 0.35, 6.6, 12.6, 0.3, [[(t, {"size": 9, "color": GRAPHITE, "italic": True})]])


# ------------------------------------------------------------------ slides

def slide_title(s, team_id, team_name):
    sub = shape_named(s, "Subtitle 3")
    for p in sub.text_frame.paragraphs:
        if p.runs and p.runs[-1].text.strip() == "TITLE PAGE":
            p.runs[-1].text = "SENTINEL"
    fields = shape_named(s, "TextBox 9")
    fields.top = Inches(2.7)
    fields.height = Inches(3.6)
    values = {
        "Problem Statement ID": ("Problem Statement ID – ", "SIH26170"),
        "Problem Statement Title": ("Problem Statement Title – ",
                                    "AI-Driven Anomaly Detection in Component Burn-In & Screening"),
        "Theme": ("Theme – ", "Smart Automation"),
        "PS Category": ("PS Category – ", "Software"),
        "Team ID": ("Team ID – ", team_id),
        "Team Name": ("Team Name – ", team_name),
    }
    for p in fields.text_frame.paragraphs:
        key = next((k for k in values if p.text.strip().startswith(k)), None)
        p.line_spacing = 1.0
        p.space_before = Pt(0)
        if not key:
            if not p.text.strip():
                p.space_after = Pt(0)
                for r in p.runs:
                    r.font.size = Pt(4)
            continue
        lab, val = values[key]
        keep = p.runs[0]
        for r in p.runs[1:]:
            p._p.remove(r._r)
        keep.text = lab
        keep.font.size = Pt(17)
        r = p.add_run()
        r.text = val
        r.font.size = Pt(17)
        r.font.bold = False
        r.font.color.rgb = BLUE if key not in ("Team ID", "Team Name") else INK
        p.space_after = Pt(9)
    text(s, 0.45, 2.02, 6.6, 0.55, [[("Explainable AI screening for component burn-in: catch the chip that passes "
                                      "every datasheet limit and is still defective.",
                                      {"size": 14, "italic": True, "color": GRAPHITE})]])
    text(s, 0.45, 6.62, 7.1, 0.8, [
        [("Problem by: ", {"size": 11, "color": GRAPHITE}), B("Indian Space Research Organisation (ISRO)", size=11)],
        [("Reference data simulated (seed 42) with known ground truth; method also checked on NASA measured aging data.",
          {"size": 10, "color": GRAPHITE, "italic": True})],
    ])


def slide_idea(s):
    set_title(s, "SENTINEL: Screening Chips That Pass but Shouldn’t", size=24, left=1.9, width=8.7)
    drop_body(s)
    text(s, 0.35, 1.18, 12.6, 0.36, [[("❖ Proposed Solution ", {"size": 15, "bold": True, "color": BLUE}),
                                      ("(Describe your Idea/Solution/Prototype) — a working prototype, all outputs below are real",
                                       {"size": 12, "color": GRAPHITE})]])
    cols = [
        ("Detailed explanation of the proposed solution", [
            [B("Module A"), " flags a chip abnormal ", B("vs its own lot"), " — median & 1.4826·MAD, log-currents, per lot"],
            [B("Module B"), " forecasts the 168 h value from ", B("0 h + 24 h only"), "; rejects at hour 24 if the 90 % bound breaks the safety slope"],
            [B("Risk 0–100"), " = weighted sum of 5 named checks → ACCEPT / WATCH / REJECT"],
            [B("Reason codes R-101…R-601"), " state the value and the lot reference in plain English"],
        ]),
        ("How it addresses the problem", [
            ["Datasheet test catches ", B("0 of 174", color=RED), " latent defects; SENTINEL catches ", B("141 (81 %)", color=GREEN),
             " with 6.0 % of good chips re-checked"],
            ["REJECT band sized to the ", B("5 % PDA"), " budget; a lot above it gets an R-601 lot review"],
            ["Hour-24 triage frees ", B("144 oven-hours"), " per pulled part"],
            ["Signed inspector report + audit trail; ", B("a human decides"), " every disposition"],
        ]),
        ("Innovation and uniqueness of the solution", [
            [B("Lot-relative, not datasheet-relative"), " — dynamic limits for every lot"],
            ["Verdict is an ", B("auditable weighted sum"), ", never a black-box score"],
            [B("3D digital twin"), " (RB-1 board, 22 fault types) proves it ", B("blind"), " on 4,200 boards"],
            ["Checked on ", B("real NASA aging data"), "; AI agents explain in plain language, every number verified"],
        ]),
    ]
    x0, cw, gap = 0.35, 4.1, 0.15
    for i, (head, lines) in enumerate(cols):
        x = x0 + i * (cw + gap)
        box(s, x, 1.6, cw, 2.48, fill=PANEL, line=RULE)
        text(s, x + 0.12, 1.66, cw - 0.24, 0.3, [[(head, {"size": 11.5, "bold": True, "color": BLUE, "font": SEMI})]])
        text(s, x + 0.12, 1.98, cw - 0.24, 2.05, bullets(lines, size=10.5, after=3))
    # proof band: the problem statement's two-part minimum demo, as real console output
    y = 4.2
    chip(s, 0.35, y, "PART A · IN-SPEC LOT OUTLIER", color=RED, w=2.6)
    text(s, 3.02, y + 0.01, 3.9, 0.27, [[("chip L04-0348: legal on the datasheet, 18.65σ from its lot", {"size": 9.5, "color": GRAPHITE})]])
    pic(s, "gap.png", 0.35, y + 0.34, h=2.22)
    chip(s, 6.2 + 0.63, y, "PART B · EARLY DRIFT FLAG AT 24 h", color=AMBER, w=2.75)
    text(s, 9.64, y + 0.01, 3.4, 0.27, [[("chip L05-0276: R-301, remove at hour 24", {"size": 9.5, "color": GRAPHITE})]])
    pic(s, "report_b.png", 6.83, y + 0.34, h=2.22)
    text(s, 10.8, y + 0.36, 2.2, 2.2, [
        [{"after": 4}, B("What the inspector reads", size=10, color=BLUE)],
        [{"after": 4}, ("Forecast from the 0 h and 24 h reads alone breaks the safety slope by ", {"size": 9.5}),
         B("1.27×", size=9.5, color=RED)],
        [{"after": 4}, ("Decision made on the ", {"size": 9.5}), B("0.90-quantile bound", size=9.5),
         (", so a part is pulled only when even its optimistic case breaches.", {"size": 9.5})],
        [("Real console output · simulated data, seed 42", {"size": 8.5, "italic": True, "color": GRAPHITE})],
    ])


def slide_tech(s):
    drop_body(s)
    # ---- pipeline
    label(s, 0.35, 1.17, 12.6, "Methodology — one pipeline, one scorer, verdict by named sub-scores")
    y, h = 1.58, 1.62
    nodes = [
        (0.35, 1.45, PANEL, INK, "ATE data log", ["CSV · 0 / 24 / 96 / 168 h", "Iddq · Ileak · Tpd · Vol"]),
        (2.0, 1.55, WHITE, INK, "Data Quality agent", ["schema · units · hash", "bad file → quarantine"]),
        (3.75, 1.9, WHITE, BLUE, "features.py (one place)", ["log currents; per-lot median", "& 1.4826·MAD robust z", "drift · early rise · curvature"]),
    ]
    for x, w, fill, edge, head, sub in nodes:
        box(s, x, y + 0.2, w, h - 0.4, fill=fill, line=edge, lw=1.5, paras=[
            [{"align": PP_ALIGN.CENTER, "after": 3}, B(head, size=10.5, color=INK)],
            *[[{"align": PP_ALIGN.CENTER, "after": 1}, M(t, size=8.5, color=GRAPHITE)] for t in sub]],
            anchor=MSO_ANCHOR.MIDDLE)
    arrow(s, 1.8, y + h / 2, 2.0, y + h / 2)
    arrow(s, 3.55, y + h / 2, 3.75, y + h / 2)
    # modules A and B stacked
    ax, aw = 5.9, 2.55
    box(s, ax, y - 0.02, aw, 0.8, fill=WHITE, line=AMBER, lw=1.5, paras=[
        [{"after": 1}, B("Module A · lot-relative outliers", size=10)],
        [M("L1 datasheet · L2 Dynamic PAT |z|", size=8.5, color=GRAPHITE)],
        [M("L3 pooled evidence Σ z² (4 axes)", size=8.5, color=GRAPHITE)]], margin=0.06)
    box(s, ax, y + 0.86, aw, 0.8, fill=WHITE, line=BLUE, lw=1.5, paras=[
        [{"after": 1}, B("Module B · forecast from 24 h", size=10)],
        [M("X̂168 = X0·(1 + A·(t/168)^n*)", size=8.5, color=GRAPHITE)],
        [M("+ LightGBM residual · q0.90 bound", size=8.5, color=GRAPHITE)]], margin=0.06)
    arrow(s, 5.65, y + h / 2, 5.9, y + 0.38)
    arrow(s, 5.65, y + h / 2, 5.9, y + 1.26)
    fx, fw = 8.75, 2.1
    box(s, fx, y + 0.05, fw, h - 0.1, fill=WHITE, line=INK, lw=1.5, paras=[
        [{"after": 2}, B("Fusion · risk 0–100", size=10)],
        [M("30% static margin", size=8.5, color=GRAPHITE)],
        [M("25% lot outlier (L2)", size=8.5, color=GRAPHITE)],
        [M("20% forecast drift (B)", size=8.5, color=GRAPHITE)],
        [M("15% pooled evidence (L3)", size=8.5, color=GRAPHITE)],
        [M("10% curvature", size=8.5, color=GRAPHITE)]], margin=0.07)
    arrow(s, ax + aw, y + 0.38, fx, y + h / 2)
    arrow(s, ax + aw, y + 1.26, fx, y + h / 2)
    dx = 11.1
    box(s, dx, y + 0.05, 1.88, h - 0.1, fill=INK, line=None, paras=[
        [{"after": 3}, B("Decision + reasons", size=10, color=WHITE)],
        [M("■ REJECT  ▲ WATCH  ● ACCEPT", size=8, color=WHITE)],
        [M("R-101 … R-601", size=8.5, color=WHITE)],
        [("inspector report · audit log · human sign-off", {"size": 8.5, "color": WHITE})]], margin=0.08,
        anchor=MSO_ANCHOR.MIDDLE)
    arrow(s, fx + fw, y + h / 2, dx, y + h / 2)
    text(s, 0.35, 3.26, 12.6, 0.3, [[
        B("Rules of the method:  ", size=9.5, color=BLUE),
        ("statistics per lot · median & MAD, never mean & σ · currents log-transformed · validation GroupKFold by lot · "
         "threshold minimises C_FN·FN + C_FP·FP (C_FN/C_FP = 100) · plain accuracy is refused by the scorer", {"size": 9.5})]])
    # ---- bottom row
    yb = 3.7
    label(s, 0.35, yb, 4.55, "Digital twin + AI agent team (built)")
    pic(s, "lab_crop.png", 0.35, yb + 0.38, w=2.18)
    pic(s, "agents.png", 2.62, yb + 0.38, w=2.28)
    text(s, 0.35, yb + 1.45, 4.55, 1.5, bullets([
        [B("RB-1 board twin: "), "circuit solver, thermal model, 22 fault types, blind mode — truth hidden until Sentinel commits"],
        [B("LangGraph agents: "), "screening team (DQ → Anomaly ∥ Forecast → Combine) + investigation team "
         "(diagnostic, root cause, QA/safety, report, AI explainer)"],
        [B("No agent releases a part."), " The Mistral explainer only words computed facts; numbers are checked, else a built-in template is used."],
    ], size=9.5, after=2))
    label(s, 5.1, yb, 3.75, "Technologies used")
    stack = [
        ("Data & models", "Python · pandas · NumPy · SciPy · scikit-learn · LightGBM"),
        ("Service", "FastAPI · SQLite · LangGraph · ReportLab (signed PDFs)"),
        ("Interface", "Next.js 14 · React Three Fiber (3D) · Tailwind"),
        ("AI (optional)", "Mistral API behind a number-check guardrail"),
        ("Real data", "h5py / SciPy .mat readers for NASA PCoE sets"),
    ]
    text(s, 5.1, yb + 0.38, 3.75, 2.6, [
        p for k, v in stack for p in ([{"after": 0}, B(k, size=10, color=INK)], [{"after": 5}, (v, {"size": 9.5, "color": GRAPHITE})])])
    label(s, 9.05, yb, 3.93, "Working prototype (screens)")
    pic(s, "twin3d.png", 9.05, yb + 0.38, h=1.95)
    text(s, 11.4, yb + 0.38, 1.6, 2.2, [
        [{"after": 3}, B("3D oven", size=10, color=INK)],
        [{"after": 6}, ("350 chips of lot L04; one leaves its batch without touching the red datasheet sheet", {"size": 9, "color": GRAPHITE})],
        [{"after": 3}, B("One command", size=10, color=INK)],
        [M("start_app.ps1", size=9, color=GRAPHITE)],
        [("API · console · agents", {"size": 9, "color": GRAPHITE})],
    ])


def slide_feasibility(s):
    drop_body(s)
    label(s, 0.35, 1.17, 5.9, "Analysis of feasibility — it already runs, blind and on real data")
    pic(s, "bench.png", 0.35, 1.55, w=5.9)
    text(s, 0.35, 3.62, 5.9, 0.4, [[
        B("Blind benchmark: ", size=9.5, color=BLUE),
        ("4,200 simulated boards, 7 scenarios, truth hidden until Sentinel commits. We show where it fails too "
         "(unseen severity 27.8 %).", {"size": 9.5})]])
    pic(s, "caps.png", 0.35, 4.08, w=3.55)
    text(s, 4.0, 4.08, 2.25, 2.5, [
        [{"after": 3}, B("Real NASA data", size=10, color=BLUE)],
        [{"after": 4}, ("24 capacitors, 1,752 reads, 226 days. At day 35 the forecast flags ", {"size": 9}),
         B("ES14C4", size=9), (" 30 days before end of life, ", {"size": 9}), B("0 false alarms", size=9, color=GREEN),
         ("; misses ES14C8.", {"size": 9})],
        [{"after": 4}, ("Rests on 2 failures — a check, not a benchmark.", {"size": 9, "italic": True, "color": GRAPHITE})],
        [("42 MOSFETs, 1.18 M waveforms: early signal weak (PR-AUC 0.63 vs chance 0.62). Reported, not hidden.",
          {"size": 9, "color": GRAPHITE})],
    ])
    # risks -> mitigations
    label(s, 6.55, 1.17, 6.43, "Potential challenges & risks → strategies for overcoming them", color=RED)
    rows = [
        ("No ISRO burn-in dataset", "Simulated lots with known ground truth + blind 3D twin + NASA measured aging data"),
        ("Recall capped by tester noise", "Stated with its operating point: Tpd/Vol defects 0.24–0.42; same pipeline reaches 0.92 at 0.4 % ATE noise"),
        ("Scrapping good silicon (overkill)", "REJECT sized to the 5 % PDA; WATCH ships with a flag; C_FN/C_FP is a parameter, not a magic number"),
        ("Lot shifts, new part variants", "Every statistic per lot; out-of-distribution suite measures the drop (44–78 % recall)"),
        ("AI states a wrong number", "AI only words computed facts; any number not in the data is rejected → built-in text; AI never decides"),
        ("Sensitive data, air-gapped lab", "Runs fully on-prem on a CPU; AI is optional and can be switched off"),
    ]
    y = 1.55
    for risk, fix in rows:
        box(s, 6.55, y, 2.35, 0.62, fill=WHITE, line=RED, lw=1.25, paras=[[B("✕ " + risk, size=9.5, color=INK)]],
            anchor=MSO_ANCHOR.MIDDLE, margin=0.07)
        arrow(s, 8.92, y + 0.31, 9.12, y + 0.31)
        box(s, 9.14, y, 3.84, 0.62, fill=WHITE, line=GREEN, lw=1.25, paras=[[("✓ " + fix, {"size": 9, "color": INK})]],
            anchor=MSO_ANCHOR.MIDDLE, margin=0.07)
        y += 0.7
    tiles = [
        ("Technical", "Open-source stack, CPU only; prototype, API, agents and twin run today; one scorer for every number"),
        ("Operational", "Adds flags on top of spec rejects, never overrides them; the QA inspector / MRB signs off"),
        ("Economic", "No licences; runs on a lab PC beside the burn-in rack; frees chamber sockets"),
    ]
    x = 6.55
    for head, body in tiles:
        box(s, x, 5.82, 2.08, 0.9, fill=PANEL, line=RULE, paras=[
            [{"after": 1}, B(head, size=9.5, color=BLUE)], [(body, {"size": 8.5, "color": INK})]], margin=0.06)
        x += 2.175


def slide_impact(s):
    drop_body(s)
    label(s, 0.35, 1.17, 7.3, "Potential impact — latent defects caught before they fly")
    pic(s, "results.png", 0.35, 1.55, w=7.3)
    text(s, 0.35, 4.28, 7.3, 0.3, [[("Simulated reference run: 2,100 chips, 6 lots, 174 hidden defects (seed 42). "
                                     "Plain accuracy deliberately not reported — ‘all good’ would score 92 %.",
                                     {"size": 9, "italic": True, "color": GRAPHITE})]])
    # chamber-hour ledger
    label(s, 7.95, 1.17, 5.03, "Chamber-hour ledger (0 → 168 h at 125 °C)")
    lx, lw_ = 7.95, 5.03
    text(s, lx, 1.55, lw_, 0.25, [[B("Today", size=10), ("  every part, full 168 h, limit check at the end", {"size": 9, "color": GRAPHITE})]])
    box(s, lx, 1.83, lw_, 0.32, fill=GRAPHITE, line=None, radius=0.1, shape=MSO_SHAPE.ROUNDED_RECTANGLE,
        paras=[[{"align": PP_ALIGN.CENTER}, M("168 h", size=9, color=WHITE)]], anchor=MSO_ANCHOR.MIDDLE, margin=0.02)
    text(s, lx, 2.28, lw_, 0.25, [[B("With SENTINEL", size=10), ("  decide the worst parts at hour 24", {"size": 9, "color": GRAPHITE})]])
    w24 = lw_ * 24 / 168
    box(s, lx, 2.56, w24, 0.32, fill=INK, line=None, radius=0.1,
        paras=[[{"align": PP_ALIGN.CENTER}, M("24 h", size=9, color=WHITE)]], anchor=MSO_ANCHOR.MIDDLE, margin=0.02)
    box(s, lx + w24 + 0.03, 2.56, lw_ - w24 - 0.03, 0.32, fill=WHITE, line=RED, lw=1.25, radius=0.1,
        paras=[[{"align": PP_ALIGN.CENTER}, M("■ early REJECT → 144 h of socket time freed", size=9, color=RED)]],
        anchor=MSO_ANCHOR.MIDDLE, margin=0.02)
    box(s, lx, 3.02, lw_, 1.2, fill=PANEL, line=RULE, paras=[
        [{"after": 3}, M("104", size=18, bold=True, color=INK), ("  parts pulled at hour 24  →  ", {"size": 10}),
         M("14,976", size=18, bold=True, color=GREEN), (" oven-hours freed", {"size": 10})],
        [{"after": 2}, ("168 h at 125 °C ≈ 18 years at 25 °C (Arrhenius, Ea 0.7 eV): a drift seen in burn-in consumes the mission.",
                        {"size": 9, "color": GRAPHITE})],
        [("Hour-24 layer is triage: 9.8 % of latent defects at 2.5 % overkill; the full screen still runs at 168 h.",
          {"size": 9, "italic": True, "color": GRAPHITE})]], margin=0.1)
    # benefit tiles
    label(s, 0.35, 4.66, 12.63, "Benefits — social, economic, environmental, strategic")
    tiles = [
        ("Mission reliability", RED, "Parts that pass every limit but are degrading are pulled before integration; "
                                     "no repair is possible in orbit."),
        ("Cost & schedule", BLUE, "Fewer escapes and re-work; faster lot disposition; chamber sockets freed at hour 24."),
        ("Energy", GREEN, "Fewer powered oven-hours at 125 °C for parts already known to be bad."),
        ("Trust & audit", INK, "Every flag has a reason code with the value and the lot reference; the inspector signs a one-page report."),
        ("Atmanirbhar & reuse", AMBER, "In-house, air-gap-ready screening IP; the same method serves defence, automotive "
                                       "(AEC-Q001 PAT) and medical-implant screening."),
    ]
    x, tw = 0.35, 2.45
    for head, col, body in tiles:
        box(s, x, 5.02, tw, 1.3, fill=WHITE, line=col, lw=1.5, paras=[
            [{"after": 3}, B(head, size=10.5, color=col)], [(body, {"size": 9, "color": INK})]], margin=0.09)
        x += tw + 0.095
    text(s, 0.35, 6.42, 12.6, 0.28, [[
        B("Target users: ", size=9, color=BLUE),
        ("ISRO component screening labs, QA inspectors and the Material Review Board; any high-reliability part screening line.",
         {"size": 9, "color": GRAPHITE})]])


def slide_refs(s):
    drop_body(s)
    label(s, 0.35, 1.17, 5.6, "How SENTINEL compares")
    cols = ["", "Datasheet limits (today)", "Dynamic PAT (AEC-Q001)", "SENTINEL"]
    rows = [
        ("Hard datasheet reject", "●", "●", "●"),
        ("In-spec outlier vs its own lot", "—", "●", "●"),
        ("Evidence pooled across parameters", "—", "—", "●"),
        ("Drift forecast from 24 h + early reject", "—", "—", "●"),
        ("Reject on the 90 % bound, not the estimate", "—", "—", "●"),
        ("Reason code with value + lot reference", "—", "○", "●"),
        ("Blind twin benchmark + real-data check", "—", "—", "●"),
    ]
    widths = [2.5, 1.05, 1.05, 1.0]
    tbl = s.shapes.add_table(len(rows) + 1, 4, Inches(0.35), Inches(1.55), Inches(sum(widths)), Inches(0.36 * (len(rows) + 1))).table
    for j, wdt in enumerate(widths):
        tbl.columns[j].width = Inches(wdt)
    for i in range(len(rows) + 1):
        for j in range(4):
            cell = tbl.cell(i, j)
            val = cols[j] if i == 0 else rows[i - 1][j]
            color = INK
            if i and j:
                color = GREEN if val == "●" else (AMBER if val == "○" else GRAPHITE)
            cell.fill.solid()
            cell.fill.fore_color.rgb = (INK if i == 0 else (RGBColor(0xE8, 0xF3, 0xEF) if j == 3 else (PANEL if i % 2 else WHITE)))
            tf = cell.text_frame
            tf.word_wrap = True
            cell.margin_left = cell.margin_right = Inches(0.05)
            cell.margin_top = cell.margin_bottom = Inches(0.02)
            cell.vertical_anchor = MSO_ANCHOR.MIDDLE
            _runs(tf, [[{"align": PP_ALIGN.LEFT if j == 0 else PP_ALIGN.CENTER},
                        (val, {"size": 8.5 if i == 0 else (9 if j == 0 else 13), "bold": i == 0 or (j and val != "—"),
                               "color": WHITE if i == 0 else color})]])
    text(s, 0.35, 4.5, 5.6, 0.3, [[("● met   ○ partial   — absent.  PAT per AEC-Q001: median ± 6 robust σ per lot.",
                                    {"size": 8.5, "color": GRAPHITE})]])
    box(s, 0.35, 4.9, 5.6, 1.72, fill=PANEL, line=RULE, paras=[
        [{"after": 3}, B("Reproduce every number", size=10, color=BLUE)],
        [{"after": 1}, M("python -m src.report", size=9)],
        [{"after": 1}, M("python -m src.twin.experiments --kind ood --seed 42 --runs 28 --boards 150", size=9)],
        [{"after": 4}, M("python -m src.realdata.evaluate", size=9)],
        [{"after": 4}, ("Seed 42, one scorer (src/evaluate.py), metrics: recall, precision, F2, PR-AUC, recall at a stated overkill budget.",
          {"size": 9, "color": GRAPHITE})],
        [{"after": 2}, B("234 automated tests pass", size=9, color=GREEN), (" (1 skipped: ngspice cross-check needs ngspice installed)", {"size": 9, "color": GRAPHITE})],
        [("Code: ", {"size": 9, "color": GRAPHITE}), M("github.com/DarkPlayz0999/Sentinel", size=9, color=BLUE)]], margin=0.1)
    label(s, 6.25, 1.17, 6.73, "Details / links of the reference and research work")
    refs = [
        ("SIH26170 problem statement (ISRO)", "https://www.sihbuddy.in/ps/SIH26170"),
        ("MIL-STD-883 Method 1015 burn-in, JPL flight-part verification", "https://parts.jpl.nasa.gov/asic/Sect.4.3.html"),
        ("MIL-PRF-38535 (PDA 5 %)", "https://landandmaritimeapps.dla.mil/Downloads/MilSpec/Docs/MIL-PRF-38535/prf38535.pdf"),
        ("ESCC 9000 generic specification (drift vs initial reading)", "https://escies.org/download/specdraftapppub?id=3659"),
        ("AEC-Q001 Rev D, Part Average Testing (robust PAT)", "http://www.aecouncil.com/Documents/AEC_Q001_Rev_D.pdf"),
        ("NIST/SEMATECH e-Handbook: MAD-based outlier detection", "https://www.itl.nist.gov/div898/handbook/eda/section3/eda35h.htm"),
        ("JPL: microelectronics reliability and drift physics", "https://nepp.nasa.gov/DocUploads/996E1F0E-3EB7-4309-9C9FB38BD53543FC/07-102%20White_JPL%20Microelectronics%20Reliability.pdf"),
        ("SemiEngineering: using analytics to reduce burn-in", "https://semiengineering.com/using-analytics-to-reduce-burn-in/"),
        ("NASA PCoE data repository (capacitor electrical stress; MOSFET thermal overstress)", "https://www.nasa.gov/intelligent-systems-division/discovery-and-systems-health/pcoe/pcoe-data-set-repository/"),
        ("ISRO URSC: usage of COTS EEE parts, screening flow and PDA < 5 %", "http://www.drsvsharma.com/wp-content/uploads/2023/09/USAGE-OF-COTS-EEE-PARTS-DrSVSharma-Deputy-Director-ISRO-URSC.pdf"),
        ("EASA AI Concept Paper Issue 2 (human-assisted ML, Level 1)", "https://www.easa.europa.eu/en/document-library/general-publications/easa-artificial-intelligence-concept-paper-issue-2"),
    ]
    paras = []
    for i, (t, url) in enumerate(refs, 1):
        paras.append([{"after": 0}, M(f"{i:>2}. ", size=9, color=BLUE), B(t, size=9)])
        paras.append([{"after": 4, "indent_only": 0.3}, (url, {"size": 7.5, "color": GRAPHITE, "font": MONO})])
    tb = text(s, 6.25, 1.55, 6.73, 5.15, paras)
    # make the URLs clickable
    for p in tb.text_frame.paragraphs:
        for r in p.runs:
            u = r.text.strip()
            if u.startswith("http"):
                r.hyperlink.address = u


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--template", required=True)
    ap.add_argument("--team-name", default="‹Team Name›")
    ap.add_argument("--team-id", default="‹Team ID›")
    ap.add_argument("--out", default=str(OUT))
    a = ap.parse_args()
    prs = Presentation(a.template)
    remove_slide(prs, 6)                  # the "IMPORTANT INSTRUCTIONS" slide: max six slides
    sl = list(prs.slides)
    slide_title(sl[0], a.team_id, a.team_name)
    for s in sl[1:]:
        team_badge(s, a.team_name)
    slide_idea(sl[1])
    slide_tech(sl[2])
    slide_feasibility(sl[3])
    slide_impact(sl[4])
    slide_refs(sl[5])
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    prs.save(a.out)
    print("deck:", a.out)


if __name__ == "__main__":
    main()
