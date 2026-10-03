"""Summaries and questions, grounded and number-checked.

    summarize(context, **ids)          plain-language summary of one page's facts
    ask(context, question, **ids)      answer a question using only those facts

Flow for both:
    facts.build() -> cache lookup -> Mistral (if configured) -> number check
      -> accepted: source "mistral"
      -> rejected or unavailable: the built-in template, source "built-in",
         with the reason recorded (never a silent fallback)

The number check: every number in the model's answer must match a number in the
fact sheet - equal after rounding, or the same value written as a percentage.
Identifiers that contain digits (C001, SIM0002-B094, R-401, L04) are only
allowed if they appear in the facts. One unmatched number and the answer is
discarded. This is what makes a fluent answer also a correct one.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone

from backend.app.ai import facts as F
from backend.app.ai.llm import LLMError, chat, config
from backend.app.core.config import get_settings
from backend.app.core.logging import get_logger, log_event
from backend.app.models.database_models import connect, dumps, loads

__all__ = ["summarize", "ask", "narrate_sheet", "check_numbers", "SYSTEM_PROMPT"]

log = get_logger("ai")

SYSTEM_PROMPT = """You are the explainer inside SENTINEL, a burn-in screening system for \
high-reliability electronic parts. Your readers are QA inspectors, managers and \
students, not statisticians.

Rules you must follow:
1. Use ONLY the facts in the JSON you are given. Never invent parts, values, causes or events.
2. Every number you write must appear in the facts. You may round it, or write a fraction \
as a percentage. Do not calculate new numbers (no differences, no averages).
3. Do not claim anything the facts do not state: no customers, no field returns, no shipping \
history, no causes beyond those named.
4. You explain; you do not decide. Verdicts come from the screening system and final \
dispositions from a human. Never say a part is safe, certified, qualified or guaranteed.
5. Evidence scores and ranking scores are similarities or rankings, NOT probabilities. \
Never call them probability, confidence or likelihood.
6. If the data is simulated, say so once.
7. Plain language: short sentences, no jargon. Explain technical terms ONLY with the \
meanings in the facts' "glossary"; never guess what an abbreviation stands for.
8. Format: 3 to 5 sentences of explanation, then up to 3 lines starting with "- " \
saying what to look at next. Plain text only: no bold, no italics, no headings, no tables."""

_NUM = re.compile(r"(?<![\w.])[-+]?\d+(?:,\d{3})*(?:\.\d+)?%?")
_ID = re.compile(r"\b(?=[A-Za-z0-9_-]*\d)(?=[A-Za-z0-9_-]*[A-Za-z])[A-Za-z0-9]+(?:[-_][A-Za-z0-9]+)*\b")
SMALL_INTS = {0, 1, 2, 3}      # "one board", "the top 3": list-size language
# A number glued to a unit word ("168-hour", "125C", "4.5-sigma") is a number, not an
# ID: its numeric part is still checked; only the ID test is skipped.
_UNIT_WORD = re.compile(
    r"\d+(?:\.\d+)?-?(?:h|hr|hrs|hour|hours|day|days|c|ns|mv|ua|na|v|ohm|ohms|s|x|fold|"
    r"sigma|percent|pct|st|nd|rd|th|k|khz|hz|uf|mhz|mm|w|point|points|part|parts|board|boards)",
    re.I)


# --------------------------------------------------------------- numbers
def _fact_numbers(obj) -> tuple[list[float], set[str]]:
    nums: list[float] = []
    ids: set[str] = set()

    def walk(o):
        if isinstance(o, bool) or o is None:
            return
        if isinstance(o, (int, float)):
            nums.append(float(o))
        elif isinstance(o, str):
            for t in _ID.findall(o):
                ids.add(t.lower())
            for m in _NUM.findall(o):
                try:
                    nums.append(float(m.rstrip("%").replace(",", "")))
                except ValueError:
                    pass
        elif isinstance(o, dict):
            for k, v in o.items():
                walk(k)
                walk(v)
        elif isinstance(o, (list, tuple)):
            for v in o:
                walk(v)

    walk(obj)
    return nums, ids


def check_numbers(text: str, facts: dict) -> list[str]:
    """Numbers (and digit-bearing identifiers) in `text` not supported by `facts`."""
    nums, ids = _fact_numbers(facts)
    bad = []
    stripped = text
    for t in set(_ID.findall(text)):
        if t.lower() in ids:
            stripped = re.sub(rf"\b{re.escape(t)}\b", " ", stripped)
        elif _UNIT_WORD.fullmatch(t):
            continue          # "168-hour", "3rd": the number part is checked below
        else:
            bad.append(t)
            stripped = re.sub(rf"\b{re.escape(t)}\b", " ", stripped)
    for m in _NUM.findall(stripped):
        pct = m.endswith("%")
        try:
            x = float(m.rstrip("%").replace(",", ""))
        except ValueError:
            continue
        if not pct and float(x).is_integer() and abs(x) in SMALL_INTS:
            continue
        ok = False
        for v in nums:
            # Honest rounding of a fact (36.3 -> 36, 97.34 -> 97.3) or the fact itself,
            # and the same for a fraction written as a percentage (0.25 -> 25 %).
            forms = [v] + ([100 * v] if abs(v) <= 1.0 else [])
            if any(abs(abs(x) - abs(round(f, d))) < 1e-9 or abs(abs(x) - abs(f)) <= 0.0005 * max(1.0, abs(f))
                   for f in forms for d in (0, 1, 2, 3)):
                ok = True
                break
        if not ok:
            bad.append(m)
    return sorted(set(bad))


# ----------------------------------------------------------------- cache
_DDL = """CREATE TABLE IF NOT EXISTS ai_summaries (
    cache_key TEXT PRIMARY KEY, kind TEXT NOT NULL, context TEXT NOT NULL,
    subject TEXT NOT NULL, question TEXT, source TEXT NOT NULL, model TEXT,
    payload TEXT NOT NULL, created_at TEXT NOT NULL)"""


def _db():
    return get_settings().sqlite_path


def _cache_get(key: str) -> dict | None:
    with connect(_db()) as c:
        c.execute(_DDL)
        row = c.execute("SELECT payload FROM ai_summaries WHERE cache_key=?", (key,)).fetchone()
    return loads(row["payload"]) if row else None


def _cache_put(key: str, kind: str, out: dict, question: str | None) -> None:
    with connect(_db()) as c:
        c.execute(_DDL)
        c.execute("INSERT OR REPLACE INTO ai_summaries(cache_key, kind, context, subject, question,"
                  " source, model, payload, created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                  (key, kind, out["context"], out["subject"], question, out["source"],
                   out.get("model"), dumps(out), out["generated_at"]))


# -------------------------------------------------------------- templates
_ACRONYMS = {"esr": "ESR", "vth": "Vth", "rds": "Rds", "ic": "IC"}


def _fault(ft) -> str:
    """ESR_INCREASE -> 'ESR increase'."""
    return " ".join(_ACRONYMS.get(w, w) for w in str(ft or "").lower().split("_"))


def _num(v) -> str:
    return f"{v:g}" if isinstance(v, float) else str(v)


def _pct(x) -> str:
    return "—" if x is None else f"{100 * x:.0f}%" if abs(x) <= 1 else f"{x:.0f}%"


def template(context: str, f: dict) -> str:
    """Deterministic plain-language summary. Used when the AI is off or rejected."""
    if context == "overview":
        v = f.get("verdicts", {})
        top = f.get("flagged_parts_a_datasheet_test_would_have_passed") or []
        lines = [
            f"SENTINEL screened {f['parts']} simulated parts in {f['lots']} batches: "
            f"{v.get('REJECT', 0)} rejected, {v.get('WATCH', 0)} on watch and {v.get('ACCEPT', 0)} accepted.",
            f"Only {f['parts_breaking_a_datasheet_limit']} parts break a datasheet limit; the rest of the flags come from "
            "parts that behave unlike the other parts in their own batch.",
        ]
        if f.get("lots_over_pda"):
            lines.append(f"Batches {', '.join(f['lots_over_pda'])} reject more than the {CONST_PDA(f)}% "
                         "budget, so they go to engineering review.")
        if top:
            lines.append(f"- Look first at {top[0]['serial']}: risk {top[0]['risk_score']}, "
                         f"{top[0]['verdict']}, although it passes every datasheet limit.")
        return "\n".join(lines)
    if context == "lot":
        return (f"Batch {f['lot']} has {f['parts']} parts: {f['reject']} rejected ({f['reject_percent']}%) "
                f"and {f['watch']} on watch. Its status is {f['status']} against a "
                f"{f['pda_limit_percent']}% limit on rejects.")
    if context == "part":
        codes = f.get("reason_codes") or []
        why = codes[0]["message"] if codes else "no single reason code fired; the weighted score placed it here"
        return (f"Part {f['serial']} from batch {f['lot']} is {f['verdict']} with a risk score of "
                f"{f['risk_score']} out of 100. "
                f"It {'passes' if f['passes_datasheet'] else 'breaks'} the datasheet limits. "
                f"Main reason: {why}")
    if context == "simulation":
        lines = [f"This is a simulated lot of {f['boards']} boards ({f['mode']} mode), "
                 f"status {f['status']} after {_num(f['simulated_hours'])} simulated hours."]
        v = f.get("sentinel_verdicts")
        if v:
            lines.append(f"Sentinel rejected {v.get('REJECT', 0)}, put {v.get('WATCH', 0)} on watch and "
                         f"accepted {v.get('ACCEPT', 0)}; it ranked {f.get('board_ranked_first_by_sentinel')} first.")
        inv = f.get("investigation")
        if inv:
            lines.append(f"The agents point to {inv.get('suspect_component')} "
                         f"({_fault(inv.get('suspect_fault_type'))}) with an "
                         f"evidence score of {inv.get('evidence_score_out_of_100')} out of 100 - a match "
                         "score, not a probability.")
        r = f.get("replacement")
        if r:
            lines.append(f"After replacing {r['replaced']} the board went from {r['before']['verdict']} "
                         f"(risk {r['before']['risk_score']}) to {r['after']['verdict']} "
                         f"(risk {r['after']['risk_score']}).")
        if f.get("after_reveal"):
            a = f["after_reveal"]
            lines.append(f"Against the revealed truth, recall was {_pct(a['recall'])} and precision "
                         f"{_pct(a['precision'])}.")
        return "\n".join(lines)
    if context == "experiment":
        o = f.get("overall", {})
        return (f"This simulated {f['kind'].replace('_', ' ')} campaign scored {f.get('boards_scored')} boards "
                f"over {f['runs']} lots. Sentinel caught {_pct(o.get('recall'))} of faulty boards "
                f"({_pct(o.get('recall_observable_faults'))} of faults the measurements can see), with "
                f"{_pct(o.get('precision'))} of its flags being real faults. Plain accuracy is not reported "
                "because it looks high even when nothing is caught.")
    if context == "realdata":
        if "capacitors" in f:
            eol = f.get("reached_end_of_life") or []
            names = ", ".join(e["capacitor"] for e in eol) or "none"
            later = f.get("failed_later_in_the_test") or []
            return (f"This is real NASA data: {f['capacitors']} capacitors measured over "
                    f"{f['test_days']} days of electrical stress. {len(eol)} reached end of life "
                    f"({names}), all at the highest stress voltage. The first weeks show a stress "
                    "transient in every capacitor, so early reads must be read with care. "
                    f"The early-warning evaluation rests on the {len(later)} capacitors that fail "
                    "later in the test, so it is a check on real data, not a benchmark.")
        return (f"This is real NASA data: {f.get('devices')} MOSFETs aged by thermal overstress. "
                f"{f.get('devices_with_two_or_more_runs')} have two or more runs and can be labelled; "
                f"{len(f.get('reached_end_of_life') or [])} of them reached end of life, meaning their "
                "on-resistance rose by 20 % or more and stayed there. The early-warning signal from the "
                "first run is weak on this data.")
    if context == "investigation":
        lines = [f.get("report_summary") or "The investigation found no matching fault signature."]
        amb = f.get("ambiguity_group") or []
        if amb:
            lines.append(f"The measurements cannot separate {', '.join(amb)}; a bench test after "
                         "removal is needed to tell which one it is.")
        lines.append("Evidence scores are match scores between the observed pattern and each fault's "
                     "modelled pattern, not probabilities. A person makes the final decision.")
        for a in (f.get("recommended_actions") or [])[:3]:
            lines.append(f"- {a}")
        return "\n".join(lines)
    if context == "workflow":
        agents = ", ".join(f"{a['agent']} ({a['status'].lower()})" for a in f.get("agents", []))
        crit = [x for x in f.get("findings", []) if x["severity"] in ("critical", "error")]
        return (f"This agent workflow was triggered by '{f['trigger']}' and ended {f['status']}. "
                f"Agents: {agents}. "
                + (f"Most important finding: {crit[0]['message']}" if crit else "No critical findings."))
    return json.dumps(f)[:600]


def CONST_PDA(f: dict):
    return (f.get("constants") or {}).get("pda_budget_percent", 5)


# ------------------------------------------------------------------ core
def _plain(text: str) -> str:
    """Strip markdown emphasis and headings the model may add despite the rules."""
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"__(.+?)__", r"\1", text)
    text = re.sub(r"(?<![\w*])\*(?!\s)([^*\n]+?)(?<!\s)\*", r"\1", text)
    text = re.sub(r"^#+\s*", "", text, flags=re.M)
    return text.strip()


def _split(text: str) -> tuple[str, list[str]]:
    body, bullets = [], []
    for line in text.splitlines():
        s = line.strip()
        if s.startswith(("- ", "* ", "• ")):
            bullets.append(s[2:].strip())
        elif s:
            body.append(s)
    return " ".join(body), bullets


def _run(kind: str, context: str, ids: dict, question: str | None, refresh: bool) -> dict:
    return narrate_sheet(kind, F.build(context, **ids), question=question, refresh=refresh)


def narrate_sheet(kind: str, sheet: dict, *, question: str | None = None,
                  refresh: bool = False) -> dict:
    """Narrate an already-built fact sheet ({context, subject, title, facts}).

    Used by the Explainer agent, which builds its sheet from the investigation
    state rather than from a page.
    """
    context = sheet["context"]
    cfg = config()
    blob = json.dumps(sheet["facts"], sort_keys=True, default=str)
    key = hashlib.sha256("|".join([kind, context, sheet["subject"], question or "",
                                   cfg.model if cfg.enabled else "built-in", blob]).encode()).hexdigest()
    if not refresh:
        hit = _cache_get(key)
        if hit:
            return {**hit, "cached": True}

    base = template(context, sheet["facts"])
    source, model, text, rejected, note = "built-in", None, base, [], None
    if cfg.enabled:
        user = (f"Page: {sheet['title']}\nFacts (JSON):\n{blob}\n\n"
                + (f"Question from the user: {question}\nAnswer it using only the facts. If the facts "
                   "do not contain the answer, say so plainly." if question else
                   "Write the plain-language summary of this page."))
        try:
            used: dict = {}
            convo = [{"role": "system", "content": SYSTEM_PROMPT},
                     {"role": "user", "content": user}]
            answer = _plain(chat(convo, cfg=cfg, meta=used))
            rejected = check_numbers(answer, sheet["facts"])
            if rejected:
                # One correction: tell the model exactly what failed the check.
                convo += [{"role": "assistant", "content": answer},
                          {"role": "user", "content":
                           "These numbers or IDs in your answer are not in the facts: "
                           f"{', '.join(rejected[:8])}. Rewrite the answer using only numbers "
                           "and IDs that appear in the facts. Do not calculate new numbers."}]
                answer = _plain(chat(convo, cfg=cfg, meta=used))
                rejected = check_numbers(answer, sheet["facts"])
            if rejected:
                note = ("The AI answer was discarded because it contained numbers or IDs that are "
                        f"not in the data ({', '.join(rejected[:6])}). Showing the built-in summary.")
            else:
                source, model, text = "mistral", used.get("model", cfg.model), answer
        except LLMError as exc:
            note = f"AI unavailable ({exc}). Showing the built-in summary."
    elif question:
        note = ("The AI assistant is not configured (set MISTRAL_API_KEY), so it cannot answer "
                "free-form questions. Here is the built-in summary of this page.")

    body, bullets = _split(text)
    out = {"kind": kind, "context": context, "subject": sheet["subject"], "title": sheet["title"],
           "question": question, "text": text, "summary": body, "next_steps": bullets,
           "source": source, "model": model, "grounded": source == "built-in" or not rejected,
           "number_check": "passed" if source == "mistral" else ("rejected" if rejected else "not needed"),
           "rejected_numbers": rejected, "note": note, "facts": sheet["facts"],
           "ai": cfg.public(),
           "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "cached": False}
    _cache_put(key, kind, out, question)
    log_event("AI_TEXT_GENERATED", log, kind=kind, context=context, source=source,
              rejected=len(rejected))
    return out


def summarize(context: str, *, refresh: bool = False, **ids) -> dict:
    return _run("summary", context, ids, None, refresh)


def ask(context: str, question: str, **ids) -> dict:
    q = question.strip()[:500]
    if not q:
        raise ValueError("empty question")
    return _run("answer", context, ids, q, refresh=False)
