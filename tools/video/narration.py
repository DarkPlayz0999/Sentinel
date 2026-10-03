"""The SIH demo video: what is said, and what happens on screen while it is said.

Each section: `url` is opened before recording starts (a clean cut), `say` is
the narration (spoken by the TTS voice and shown as captions), `actions` run
while it is spoken. Every number said here was read off the running product
or its evaluation files; the comment beside a claim says where.

Action forms:
    ("wait", s)                      pause
    ("click", text)                  click the visible control whose text contains `text`
    ("clickx", text)                 same, exact text match
    ("select", label, option)        choose `option` in the <select> labelled `label`
    ("type", css, text)              type into an input
    ("scroll", dy, ms)               smooth scroll by dy pixels
    ("to", text_or_css, block)       smooth scroll so that element is in view
    ("top",)                         back to the top
    ("js", code)                     run code in the page
    ("until", js_condition, timeout) wait for the page to reach a state
"""

VOICE = "en-IN-PrabhatNeural"
RATE = "+10%"
WEB = "http://localhost:3000"

SECTIONS = [
    {
        "id": "01-problem", "title": "The problem", "url": f"{WEB}/",
        "say": (
            "Every chip that flies on an ISRO satellite first spends a week in an oven. "
            "Burn-in, at one hundred and twenty five degrees, with readings at zero, twenty four, "
            "ninety six and one hundred and sixty eight hours. The test asks one question: is every "
            "reading under the datasheet limit? A latent defect passes that test. "
            "In our data, every single latent defect passes the datasheet at one hundred and sixty "
            "eight hours. It ships, and it fails in orbit. This is SENTINEL. We catch the chips that "
            "pass every test, and are still wrong."),
        "actions": [("wait", 3), ("click", "L04-0348"), ("wait", 5), ("scroll", 520, 2600), ("wait", 5),
                    ("to", "How many does each screen catch", "center"), ("wait", 9), ("top",)],
    },
    {
        "id": "02-approach", "title": "How we solve it", "url": f"{WEB}/",
        "say": (
            "Look at chip L04-0348. Its supply current climbs from twenty two to forty nine "
            "microamps, still under the fifty microamp limit, so a static test ships it. SENTINEL "
            "compares every chip with its own batch, not with a number printed years ago. Against its "
            "batch, this chip is far outside. We add three things a static test does not have: "
            "lot-relative outlier detection with robust statistics, a drift forecast that predicts the "
            "one hundred and sixty eight hour value from the first twenty four hours, and a "
            "plain-language reason for every flag, so an inspector can check it."),
        # hero chip: 21.94 -> 49.45 uA, USL 50 (src/explain reason code for L04-0348)
        "actions": [("to", "#detection", "start"), ("wait", 5), ("to", "▶ Play week", "center"),
                    ("click", "▶ Play week"), ("wait", 9), ("to", "#forecast", "start"), ("wait", 6),
                    ("to", "#reasons", "start"), ("wait", 4)],
    },
    {
        "id": "03-results", "title": "Results at a glance", "url": f"{WEB}/console",
        "say": (
            "The results, on our simulated reference data: two thousand one hundred chips in six batches. "
            "One hundred and seventy four carry a hidden defect. The "
            "old test catches none of them. SENTINEL catches one hundred and forty one, eighty one "
            "percent, while sending only six percent of good chips for a second look. The reject line keeps every batch inside a five percent reject budget; three batches "
            "exceed it and go to engineering review. And here, the same results in plain language, "
            "written by our AI, with every number checked against the data."),
        # 174 / 0 / 141 (81%) / 6.0% read off /console
        "actions": [("wait", 9), ("scroll", 620, 2200), ("wait", 7), ("to", "The results in plain language", "center"),
                    ("wait", 10)],
    },
    {
        "id": "04-oven3d", "title": "The oven, in 3D", "url": f"{WEB}/console/twin",
        "say": (
            "This is the oven in three dimensions. One batch, three hundred and fifty chips, each column "
            "one chip's reading. The red sheet is the datasheet limit. The blue slab is the batch itself. "
            "Switch to batch L04 and to supply current, and play the week. One chip climbs out of its "
            "batch without ever touching the red limit. Press show me the hidden one, and SENTINEL "
            "jumps straight to the chip that passes every limit and is still a defect."),
        "actions": [("wait", 3), ("select", "Batch", "L04"), ("wait", 2),
                    ("select", "Measurement", "quiescent"), ("wait", 2),
                    ("click", "Play the week"), ("wait", 10),
                    ("click", "Show me the hidden one"), ("wait", 7)],
    },
    {
        "id": "05-lab", "title": "Fault-injection lab (digital twin)", "url": f"{WEB}/console/lab",
        "say": (
            "Now our digital twin: a 3D burn-in board with a real circuit behind every part. We simulate a lot of two hundred boards "
            "and hide a fault in one capacitor. Blind: not even we know which board. SENTINEL sees "
            "only what a real tester records. It ranks the lot, and rejects board ninety four first. Then the agent team investigates. The "
            "infrared camera shows capacitor C001 running hot against the same position on its sibling "
            "boards. The verdict: C001, ESR increase, evidence score ninety seven out of one hundred, a "
            "similarity, never a probability. We replace the part and rerun the burn-in: risk drops "
            "from fifty three to about twenty, and the board is accepted. Then we reveal the truth: "
            "C001, ESR increase, on board ninety four. SENTINEL was right, blind."),
        # B094 / evidence 97.3 / risk 53.1 -> 20.6 (live API run, docs/twin/sih-demo.md)
        "actions": [("click", "Run the demo, blind"),
                    ("until", "document.body.innerText.includes('INVESTIGATED')", 45),
                    ("wait", 1), ("clickx", "Thermal (IR)"), ("wait", 4), ("clickx", "Fault"), ("wait", 4),
                    ("to", "Agent investigation", "start"), ("wait", 5),
                    ("click", "Replace C001"), ("wait", 2), ("click", "Fit & rerun"),
                    ("until", "document.body.innerText.includes('Before / after')", 30),
                    ("to", "Before / after", "start"), ("wait", 3), ("top",),
                    ("click", "Reveal ground truth"), ("wait", 1),
                    ("to", "Ground truth and benchmark", "start"), ("wait", 5)],
    },
    {
        "id": "06-benchmark", "title": "Blind benchmark", "url": f"{WEB}/console/benchmark",
        "say": (
            "One demo proves nothing, so we benchmark blind, at scale. Four thousand two hundred "
            "simulated boards across seven scenarios. In distribution, SENTINEL catches sixty nine "
            "percent of faulty boards, and eighty percent of the faults the measurements can actually "
            "see. A noisier tester drops that to forty four percent. Faults subtler than anything it "
            "was tuned on: twenty eight percent. We show where it fails, not only where it wins. And we "
            "never report plain accuracy: predicting all good would look high, and catch nothing."),
        # docs/twin/evaluation.md: OOD seed 42, 28 runs x 150 boards
        "actions": [("wait", 2), ("click", "Out-of-distribution suite"), ("wait", 5),
                    ("to", "Recall, in-distribution vs out-of-distribution", "start"), ("wait", 10),
                    ("to", "In-distribution vs out-of-distribution", "start"), ("wait", 8)],
    },
    {
        "id": "07-realdata", "title": "Real data (NASA)", "url": f"{WEB}/console/realdata",
        "say": (
            "Simulation is not enough, so we tested on real, measured data: NASA's capacitor aging "
            "study, twenty four capacitors and one thousand seven hundred and fifty two measurements "
            "over two hundred and twenty six days, and forty two MOSFETs with over a million "
            "switching waveforms. We prepare the files without changing a single reading. Four "
            "capacitors reach end of life, all at fourteen volts. At day thirty five, SENTINEL's "
            "forecast flags ES14C4, thirty days before it crossed the line, with no false alarms, and "
            "it misses one. That rests on two capacitors, and we say so. On MOSFETs the early signal is "
            "weak, barely above chance, and we show that too."),
        # data/real/*/evaluation.json
        "actions": [("wait", 4), ("to", "Capacitance loss over the test", "start"), ("wait", 8),
                    ("click", "ESR"), ("wait", 4), ("to", "Early warning on real parts", "start"),
                    ("wait", 8), ("top",), ("click", "MOSFETs"), ("wait", 3),
                    ("to", "On-resistance at 25", "start"), ("wait", 6)],
    },
    {
        "id": "08-screen", "title": "Check a new batch", "url": f"{WEB}/console/screen",
        "say": (
            "This is how a test floor uses it. Load a tester data log: two batches, all four read "
            "points. Run the screen. In seconds every part has a verdict, a risk score, and the reasons "
            "behind it, in the units the tester wrote."),
        "actions": [("wait", 2), ("click", "Two lots, all read points"), ("wait", 3),
                    ("click", "Run screen"), ("until", "document.body.innerText.includes('REJECT')", 60),
                    ("wait", 2), ("scroll", 700, 2400), ("wait", 5)],
    },
    {
        "id": "09-batches", "title": "Batches", "url": f"{WEB}/console/lots",
        "say": (
            "Batches. SENTINEL judges every chip against its own lot, because lots differ. Batch L04 is "
            "shifted and wider than the others; a fixed limit tuned on one batch is wrong for the next. "
            "Each batch's normal range comes from the median and a robust spread, never the mean."),
        "actions": [("wait", 3), ("clickx", "L04"), ("wait", 5), ("scroll", 600, 2200), ("wait", 6)],
    },
    {
        "id": "10-chips", "title": "Every chip", "url": f"{WEB}/console/components",
        "say": (
            "Every chip is searchable. Here is L04-0348: its supply current rose from twenty two to "
            "forty nine microamps against a batch that barely moved. Datasheet: pass. SENTINEL: reject, "
            "with the reason written out."),
        "actions": [("wait", 2), ("type", "input[placeholder='L04-0348']", "L04-0348"), ("wait", 3),
                    ("click", "L04-0348"), ("wait", 8)],
    },
    {
        "id": "11-decides", "title": "How it decides", "url": f"{WEB}/console/analysis",
        "say": (
            "How it decides. The risk score is a weighted sum of five named checks: distance to the "
            "datasheet limit, how far the chip sits from its batch, the forecast drift, evidence pooled "
            "across parameters, and whether the drift is accelerating. The weights are visible. Missing "
            "a defect is priced one hundred times higher than scrapping a good chip, and the rules sit in "
            "plain view, for an inspector to challenge."),
        "actions": [("wait", 3), ("to", "Module A: detection against the lot", "start"), ("wait", 7),
                    ("to", "Module B: the forecast from hour 24", "start"), ("wait", 7),
                    ("to", "Decision policy", "start"), ("wait", 7)],
    },
    {
        "id": "12-report", "title": "Inspector report", "url": f"{WEB}/console/reports?id=L05-0276",
        "say": (
            "The inspector report is the record a QA engineer signs. For chip L05-0276, the forecast "
            "from the first twenty four hours alone breaks the safety slope, reason code R three zero "
            "one: remove it at hour twenty four. Every number is shown against its batch reference, "
            "ready to print."),
        # src/explain: L05-0276 R-301 "Recommend removal at hour 24"
        "actions": [("wait", 4), ("scroll", 500, 2200), ("wait", 5), ("scroll", 500, 2200), ("wait", 4)],
    },
    {
        "id": "13-agents", "title": "AI agents, live", "url": f"{WEB}/console/agents",
        "say": (
            "Behind all of this is an agent team. Run the workflow. A data quality agent checks the "
            "file and its hash. The anomaly and forecast agents run in parallel. A combine agent writes "
            "the verdicts. When SENTINEL flags a board, an investigation team takes over: diagnostic, "
            "root cause, QA and safety, a report, and an explainer agent that uses Mistral AI to write "
            "it in plain language. Every number it writes is checked against the data. No agent ever "
            "releases a part. That decision stays with a human."),
        "actions": [("wait", 2), ("select", "Dataset", "burnin_two_lots_168h"), ("wait", 1),
                    ("click", "Run workflow"), ("wait", 10), ("to", "Findings", "start"), ("wait", 6),
                    ("top",), ("wait", 4)],
    },
    {
        "id": "14-close", "title": "Ask SENTINEL AI", "url": f"{WEB}/console",
        "say": (
            "And anyone can ask. Which chips should I look at first? The answer uses only the facts on "
            "the page. The screening itself runs fully on-premise; the AI only words the results, and it "
            "can be switched off. Latent defects that pass every test, caught before they fly. "
            "This is SENTINEL."),
        "actions": [("wait", 1), ("click", "Ask SENTINEL AI"), ("wait", 2),
                    ("click", "Which chips should I look at first?"),
                    ("until", "!document.body.innerText.includes('Thinking')", 30), ("wait", 5)],
    },
]

# Where each spoken figure comes from (rendered into script.md). Check these before a slide.
SOURCES = {
    "01-problem": "100% of latent defects pass the datasheet at 168 h: CLAUDE.md measured facts; landing page, "
                  "section 'The gap'.",
    "02-approach": "L04-0348: Iddq 21.94 -> 49.45 uA, datasheet 50 uA, R-102 at 18.7 sigma against lot L04 "
                   "(inspector report for L04-0348).",
    "03-results": "/console tiles, from web/public/data/console.json (python web/scripts/export_lab_data.py): 2,100 "
                  "chips, 6 batches, 174 hidden defects, old test 0, SENTINEL 141 (81%), good chips checked twice "
                  "6.0%; L01, L04, L06 over the 5% PDA reject budget.",
    "04-oven3d": "web/public/data/console.json: 350 chips per batch; red sheet = datasheet limit, blue slab = batch "
                 "5th-95th percentile.",
    "05-lab": "Live run of the SIH scenario (backend/app/services/simulation_service.py SIH_DEMO: C001 ESR_INCREASE, "
              "severity 0.8 from 24 h). Board B094 REJECT at risk 53.1 (R-401), C001 evidence 97.3, rerun risk "
              "20.6 ACCEPT.",
    "06-benchmark": "Experiment exp_5d7c194678fa48a0 (python -m src.twin.experiments --kind ood --seed 42 --runs 28 "
                    "--boards 150): 4,200 boards, 7 scenarios; in-distribution recall 0.694, observable faults 0.80, "
                    "noisier tester 0.444, unseen severity 0.278.",
    "07-realdata": "data/real/capacitors/evaluation.json and metadata.json (python -m src.realdata.evaluate): 24 "
                   "capacitors, 1,752 reads, 226 days; EOL ES14C1, ES14C6 (day 3), ES14C8 (day 63), ES14C4 (day 65); "
                   "at day 35 the forecast flags ES14C4 with 0 false positives and misses ES14C8. MOSFETs: 42 "
                   "devices, 1,182,867 waveforms; early read PR-AUC 0.63 against chance 0.62.",
    "08-screen": "Live POST /v1/screen on the bundled sample 'Two lots, all read points'.",
    "09-batches": "web/public/data/console.json lot references: L04 Iddq median 13.6 uA, robust sigma 4.2 at 168 h; "
                  "other batches 10.2-11.8 uA, sigma 1.7-3.1.",
    "10-chips": "L04-0348 part record (as section 02).",
    "11-decides": "src/fusion.py weights 30/25/20/15/10 on static margin, lot outlier, predicted drift, pooled "
                  "evidence, curvature; C_FN/C_FP = 100 (CLAUDE.md rule 7).",
    "12-report": "Inspector report for L05-0276: R-301, forecast drift 1.3x the safety slope from the 0 h and 24 h "
                 "reads, 'Recommend removal at hour 24'.",
    "13-agents": "Live run on burnin_two_lots_168h.csv (700 rows): backend/app/agents/graph.py (data_quality re-checks "
                 "the dataset hash; anomaly and forecast in parallel; combine) and backend/app/agents/investigation.py.",
    "14-close": "Live POST /v1/ai/ask; numbers in the answer are checked against the page facts "
                "(backend/app/ai/narrator.py). With Mistral on, the page facts are sent to the Mistral API.",
}
