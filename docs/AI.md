# SENTINEL AI: plain-language explanations (Mistral)

The AI **explains**; it never decides. Verdicts, risk scores and reason codes
still come from `src/pipeline.py` and the agent team. The AI words them for a
QA inspector, a manager or a jury.

## Where it appears

| Place | What it does |
|---|---|
| **Ask SENTINEL AI** (bottom-right, every console page) | answers questions about the page you are on |
| Results at a glance | the whole screening run in plain language |
| Inspector report | one part: why it was flagged, against its batch |
| Agent operations | what each agent did and what matters |
| Fault-injection lab | what is happening in this lot, now; updates as the loop advances |
| Blind benchmark | what a campaign shows, and what it does not |
| **Explainer agent** | a fifth investigation agent (after Report): the investigation in plain words |

## Switch Mistral on

```powershell
$env:MISTRAL_API_KEY = "<your key>"                      # never commit it
$env:SENTINEL_LLM_MODEL = "ministral-8b-latest"          # optional; this is the default
powershell -ExecutionPolicy Bypass -File start_app.ps1   # or: uvicorn src.api:app --port 8000
```

If the main model is rate-limited (HTTP 429) the client backs off, retries, then
uses `SENTINEL_LLM_FALLBACK_MODEL` (default `mistral-small-latest`). Every text is
labelled with the model that actually wrote it.

`GET /v1/ai/status` reports whether it is on. Without a key everything still
works: every card and the Explainer agent use a built-in plain-language summary,
and the assistant says it cannot answer free-form questions.

`SENTINEL_LLM_BASE_URL` points it at any server with the same
`/chat/completions` API (for example a local model), and `SENTINEL_AI=0`
switches it off even when a key is set.

## Why the text can be trusted

1. **Grounded.** The model receives one fact sheet built only from what that
   page already shows (`backend/app/ai/facts.py`), plus rules: use only these
   facts, no new numbers, never call a score a probability, never say a part is
   safe or certified.
2. **Number-checked.** Every number and every ID in the answer (C001, R-401,
   SIM0004-B094) must appear in the fact sheet, allowing rounding and
   fraction-to-percent. One unmatched number and the answer is **discarded**; the
   built-in summary is shown with the reason (`backend/app/ai/narrator.py`).
3. **Labelled.** Every text says who wrote it: "AI · model · numbers checked" or
   "Built-in summary". "Show the facts it used" lists the exact inputs.
4. **Blind-safe.** In a BLIND simulation the fact sheet comes from the same
   API view that withholds the injected fault, so the model cannot leak it.
5. **Cached.** The same facts give the same text until the facts change.

Tests: `tests/test_ai.py` (a stand-in model: a grounded answer is kept, one that
invents "92% chance of failing" is discarded).

## Data leaving the machine

With a key set, the fact sheet of the page being explained is sent to Mistral.
It holds measurements, scores and IDs from the screen, never an API key, a file
path, or blind-mode ground truth. Leave the key unset to stay fully local.
