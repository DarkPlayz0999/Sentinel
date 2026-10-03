# Tech Pioneers (SIH 2025) deck teardown + SIH 2026 Playbook + Easy-vs-Difficult guide + README

Source files (all local, primary):
- TP = [SIH_2025_Tech_Pioneers_High_Quality.pdf](file:///Users/himanshusolanki/Downloads/sih/SIH-Winners-PPt-and-Sources/SIH_2025_Tech_Pioneers_High_Quality.pdf) (6 pages, 1920x1080 pt, image-only: every page is one embedded raster of about 1300x730 px, so there is no selectable text; the file has no metadata)
- PB = [SIH_2026_Playbook_TechDoodles_Final.pdf](file:///Users/himanshusolanki/Downloads/sih/SIH-Winners-PPt-and-Sources/SIH_2026_Playbook_TechDoodles_Final.pdf) (12 pages, portrait 474x663 pt, DejaVu Sans, real text)
- ED = [SIH 2026 - Easy vs Difficult Problem Statements.pdf](file:///Users/himanshusolanki/Downloads/sih/SIH-Winners-PPt-and-Sources/SIH%202026%20-%20Easy%20vs%20Difficult%20Problem%20Statements.pdf) (6 pages A4, made with wkhtmltopdf, created 2026-08-23, Poppins and Liberation Sans)
- RM = [README.md](file:///Users/himanshusolanki/Downloads/sih/SIH-Winners-PPt-and-Sources/README.md), [assets/sih-logo.jpeg](file:///Users/himanshusolanki/Downloads/sih/SIH-Winners-PPt-and-Sources/assets/sih-logo.jpeg), [assets/sih-winners.jpeg](file:///Users/himanshusolanki/Downloads/sih/SIH-Winners-PPt-and-Sources/assets/sih-winners.jpeg)

Every page was rendered to PNG and inspected visually, with zoomed crops of the slide-2 architecture diagram, the slide-4 green facts box and the slide-6 comparison table. Hex colours below are approximate, taken from rendered pixels and by eye.

## Q1. Tech Pioneers (SIH 2025) deck: slide-by-slide teardown

### Takeaway
This is a 6-slide deck that follows the official SIH 2025 idea template to the letter: Title, then Idea Title/Proposed Solution, Technical Approach, Feasibility & Viability, Impact & Benefits, Research & References. It is text-heavy and white-backgrounded, in Office-default styling. What it does well is **coverage**. Every template pointer is answered, it has a real architecture diagram, a four-way impact tree, hard-sounding numbers ("70-90% reduction", "15-60 minutes advance notice", "$2-5 million annually") and, strongest of all, a **feature-comparison matrix against 4 named competitors** where only their column is all green ticks. It wins on completeness and a clear competitive table, not on visual polish.

### Cited Findings

**Global style (all slides)** — [TP](file:///Users/himanshusolanki/Downloads/sih/SIH-Winners-PPt-and-Sources/SIH_2025_Tech_Pioneers_High_Quality.pdf)
- 16:9, white/very light-grey background (#F0F0F0 to #FFFFFF dominates every page). There is no background art except faint grey hexagons behind the logo on slide 1.
- Recurring header on slides 2-6: a hand-drawn purple-grey **oval** at top-left reading "Tech Pioneers" (outline about #8E7CC3, black sans text), a **large black serif all-caps title** in the centre (Times New Roman style bold), and the official **SIH 2025 lightbulb-brain logo** at top-right (orange circuit half about #F58220, green binary half about #1E7B34, grey "SMART INDIA HACKATHON 2025" wordmark).
- Section sub-headings use a "❖" four-diamond bullet plus a **blue underlined sans heading** (about #2E5597, Office "Dark Blue, Text 2" style), e.g. "❖ Proposed Solution", "❖ Technology Stack", "❖ Benefits of the solution", "❖ Refrences".
- Body text is black Calibri/Carlito-style sans at about 14-16 pt equivalent, with bold lead-in labels ("Technical:", "Economic:"). Bullets are "➢" arrowheads, "•" dots or numbered lists.
- Text density is very high. Rough word counts: slide 2 about 150, slide 3 about 110 (plus about 30 logos), slide 4 about 380, slide 5 about 330, slide 6 about 80 plus a 9x6 table.
- Three different font families are mixed: serif titles, Arial-like on slide 1, Calibri-like body.

**Slide 1: Title**
- Top: "SMART INDIA HACKATHON 2025" in large bold navy serif (about #1B4A7A). The final "5" collides with and is overlapped by the SIH logo at top-right, which is a visible layout bug.
- "TECHPIONEERS" as a centred black serif sub-title.
- Bullets (bold label plus regular value):
  - "Problem Statement ID – SIH25071"
  - "Problem Statement Title- AI-Based Rockfall Prediction and Alert System for Open-Pit Mines"
  - "Theme- Disaster Management"
  - "PS Category- Software"
  - "Team ID-" (**left blank**)
  - "Team Name (Registered on portal): TECHPIONEERS"
- Right half: a large version of the SIH brain-bulb logo over pale grey hexagon outlines. It is purely decorative.
- Meaning: this is the mandatory template title slide, unmodified. There is no hook, no tagline and no product name here. The product name "RockVision AI" first appears on slide 2.

**Slide 2: "RockVision AI" (Idea title slot), sub-heading "❖ Proposed Solution"**
- The left 60% is 7 "➢" bullets, each with a bold feature name and a one-line description. Verbatim leads:
  - "Comprehensive RockVision AI Association Platform: A robust web and mobile application ecosystem to predict rockfall prediction in open pit mining."
  - "Real-Time Monitoring: Utilizes AI-driven algorithms to suggest overview with real-time risk status of rockfall."
  - "Historical Data: Stored the data which is predicted through AI-driven algorithms upto last 30 days only."
  - "AI Chat & Consultation Features: Intelligent mining assistant provided 24/7 availability for safety Q&A."
  - "PPSA model- Pre-Project Safety Analysis- provide equipment requirement analysis and safety verification and Automatic risk scoring based on project parameter through AI."
  - "BP&S Management-Blast Planning & Safety - facilitates blast management system to detect stability assessment and monitoring with safety and minimal geological impact."
  - "Alert System- Evacuation from rockfall site via notification on SMS and Email"
- Right 40%: a **system architecture / data-flow diagram**, black-line draw.io style with icon nodes and orthogonal arrows. Reading the zoomed crop, top to bottom:
  1. Source layer at the top: a cluster of sensor/IoT node icons (circles with signal waves) plus a **drone** icon. Both feed arrows right and down into
  2. a red **Node-RED** block (IoT flow ingestion), which points down into
  3. a blue stacked-server **backend/database** icon. This is linked bidirectionally to a blue globe/network **API/web server** icon, and to a right-hand store labelled "influxdb" plus PostgreSQL elephant, and a blue "SQL" cylinder.
  4. The API server sends "Client Req/Res" (label written "Client Req/Res") left to a rounded box of **client platforms**: Chrome, Android and Apple icons, with a small phone/server icon above.
  5. The API server also feeds down-left into a tall box with a businessman icon labelled "**Authorization + Authentication**". That box has a long arrow right into
  6. a three-row **feature panel**: "Real Time Monitoring" (dashboard icon), "history and trend analysis" (HISTORY server icon) and "Pre-Project Safety Analysis" (worker plus checklist/shield icon).
  - Visual encoding: vendor icons stand in for technology names, and the top-down flow means sensing, then ingestion, then storage/API, then users. The labels are tiny (about 6 pt equivalent) and blurry. The diagram's real meaning is "we have an IoT-to-cloud pipeline with time-series storage and role-gated feature modules". There is no ML model node drawn explicitly, so AI is implied rather than shown.
- Framing: the USP here is breadth, because the platform goes beyond prediction to chat assistant, blast planning and pre-project safety. There is no problem-statement or pain slide. The deck skips problem framing entirely, since the 2025 template has no separate "problem" slot.

**Slide 3: "TECHNICAL APPROACH", sub-heading "❖ Technology Stack"**
- Left: five bold-labelled paragraphs. Verbatim:
  - "Frontend : React.js ,React Native, vite, Redux,D3.js, Typescript,Next.js, Material-UI v5,chart.js, video.js, HLS.js, Tailwind CSS, socket.io."
  - "Backend:FastAPI, Python, InfluxDB, PostgreSQL, MongoDB, MinIO, Pandas, Redix, Kong, Celery, SQLAlchemy,Elasticsearch."
  - "AI/ML: Pytorch, openCV, TensorFlow, YOLOv8,Transformar, SpaCy, ONNX Runtime, scikit-learn, XGBoost, LightGBM, Keras, mlflow,."
  - "API Services : OpenAI API,OpenWeatherMapAPI,Seismic Monitoring API,Satellite image APIs,Twilio,SendGrid,Strips."
  - "Cloud and Deployment: Kubernetes,AWS,Docker,Grafana,GitHub lab,pytest,Prometheus."
- Right: a **logo wall** of about 25 tech logos in a rough 5-column grid with no grouping or flow: HTML5, CSS3, JS, PostgreSQL, TS, Node, Prometheus, InfluxDB, Python, Kubernetes, MLflow-style logo, LightGBM, Grafana, TensorFlow, Node-RED, OpenCV, React, D3, Three.js-style, XGBoost, Tailwind, MongoDB, Docker, AWS.
- Meaning: the slide signals "industrial-grade stack" to the judges. There is no process flowchart on this slide, even though the template asks for a methodology/flowchart; the architecture diagram lives on slide 2 instead. It has several typos ("Redix", "Transformar", "Strips" for Stripe, "GitHub lab"). With about 45 technologies listed, the stack cannot plausibly be built in 36 hours, so it reads as stack-padding.

**Slide 4: "FEASIBILITY AND VIABILITY"**
- Two text columns, each block introduced by a small clip-art icon: scales labelled "FEASIBILITY", a person-with-gear, a climber-with-gear, a folder-tree, a lightbulb-and-bar-chart, and a hand holding a lightbulb.
- Left column, numbered continuously 1-12:
  - "Feasibility:" 1. "Technical: Feasible via mature tech (AI, IoT), using sensor data to predict rockfalls and send alerts." 2. "Economic: High costs are justified by significant returns in safety, damage reduction, and efficiency from preventing rockfalls." 3. "Operational: Success depends on seamless integration and staff acceptance, requiring a user-friendly design and proper training."
  - "Viability:" 4. "Market opportunities: … strong market opportunity due to the mining industry's need for safety … highly scalable, and has broad applications in other geotechnical fields." 5. "Sustainability and future-proofing: … its AI model improves with data, its modular design adapts to new tech…"
  - "**Challenges:**" 6. "Data Scarcity: high-quality dataset of rockfall events is a major hurdle." 7. "False Alerts: The model must minimize false positives and negatives to be reliable." 8. "Dynamic Environments: system needs to continuously adapt to changing geological conditions"
  - "Use Cases" 9. "Real-Time Alerts: Instantly warn personnel of danger for timely evacuation." 10. "Smarter Planning: Use risk maps to optimize work in unstable areas." 11. "Proactive Maintenance: Identify early signs of slope failure to prevent collapses." 12. "Improved Design: Use historical data to enhance future mine layouts .."
- Right column:
  - "Business Potential :" 1. "Subscription-Based Service" 2. "Tiered Pricing: … based on mine size and desired features." 3. "Strategic Partnerships: Partner with sensor and equipment companies…" 4. "Consulting and Support".
  - "Solutions:", which map onto the challenges: 5. "Robust Data & Algorithms: We'll use a mix of historical and real-time sensor data (LiDAR, drones) to continuously improve our AI models, reducing false alarms." 6. "Seamless Integration: … modular design…" 7. "User-Centric Design: A simple interface will ensure staff can effectively use and trust the system."
- Bottom-right: a **green gradient rounded panel** (bright green about #1A9A1A at the top fading to white) with a large green shield-and-white-tick icon overlapping its top-left corner. The centred text is tiny and nearly illegible: "Supporting Facts for Feasibility and Viability / Supporting Facts / Rockfalls are a major safety hazard in open-pit mines, causing fatalities and significant financial losses from equipment damage and operational / AI and machine learning have already shown promising results in geotechnical engineering for predicting slope stability and rockfall probability. / The system's predictive capabilities can provide a competitive advantage by moving from reactive to proactive rockfall management, greatly improving safety and efficiency."
- Meaning: this is the deck's **risk framing**. Challenges are paired with Solutions, which is the "risks + mitigation" pattern judges look for, although the pairing is only implied by the list order and never drawn visually. The facts box is the only "problem/why-now" content in the deck, and it has no numbers or citations.

**Slide 5: "IMPACT AND BENEFITS"**
- Top-left: a **hierarchy/tree diagram**. A wide orange-to-peach gradient root box reads "Benefits of the solution", with a green tick on top. One arrow goes down to a horizontal bus that splits into four arrows to four staggered rounded boxes, each with a small icon:
  - "Social" (sage/dark green about #6E9E6E, people icon)
  - "Economic" (lavender about #A393C7, coins/chart icon)
  - "Technological" (salmon about #F4827A, globe-tech icon)
  - "Environmental" (bright green about #3CB44B, earth icon)
  - Meaning: the diagram previews the four-category structure of the right-hand text, so it works as a visual table of contents for impact. The staggered up/down placement adds rhythm but carries no data.
- Bottom-left: "❖ Potential impact on the target audience:" as **stakeholder bullets**: "Mining Executives: Protects profits and reputation by preventing costly accidents and operational disruptions." / "Miners & Engineers: A life-saving tool that boosts confidence and enables proactive safety decisions." / "Regulators: Provides a transparent, data-driven system for ensuring continuous safety compliance." / "Local Communities: Builds trust by proactively eliminating the risk of catastrophic events, ensuring their safety.."
- Right: "❖ Benefits of the solution" with four bold headings (Social / Technological / Economic / Environmental) and 3 bullets each. The key quantified lines are all under Economic:
  - "Enhances the safety improvement through **70-90% reduction** in rockfall-related incidents."
  - "Generates early warning time in **15-60 minutes advance notice** (vs current reactive approach)."
  - "Accelerates cost savings upto **$2-5 million annually** per large mining operation."
  - Other lines: "Promotes accuracy over latency during realtime rockfall site." / "Reduces land disturbance by proactively preventing rockfalls." / "Less need for additional,unplanned work, which in turn lowers the mine's carbon footprint."
- Meaning: this is the **impact framing**. There is a stakeholder-wise value statement, a four-pillar (social/tech/economic/environmental) benefit model, and three headline numbers. None of the numbers is sourced, and none maps to SDGs.

**Slide 6: "RESEARCH AND REFERENCES"**
- Left: "❖ Refrences" (typo). "Research & Best Practices:" with 7 links that are just domain roots or truncated paths: sciencedirect.com/, youtu.be/DEM/, academia.edu/, researchgate.net/, farmonaut.com/open-pit, agupubs.onlinelibrary.wiley.com/, maptek.com/. Then "Open-pit Mining Platforms: MineGAURD: https://www.mineguard-ai.com/" and "GeoAlert: Geoalert AI mapping and geoanalytics platform" (as a hyperlink).
- Right: "❖ Comparision with Existing Systems" (typo) as a **feature comparison matrix**: 9 feature rows by 5 product columns (RockVision AI, MineGUARD, RockWatch Pro, SafeMine 360, GeoAlert). It has a light-grey header row and green ✓ / red ✗ glyphs, with small grey qualifiers in brackets.
  - Rows: Real-Time Monitoring (all ✓) / 30-Day Historical Analysis (RockVision ✓; MineGUARD ✓ "(90 days)"; RockWatch ✓ "(60 days)"; SafeMine ✗ "(7 days only)"; GeoAlert ✓) / AI-Powered Risk Prediction (RockWatch ✗, GeoAlert ✗) / Multi-Channel Alerts (SMS/Email/Push) (all ✓) / Document Repository System (only RockVision ✓, RockWatch "✓ (Basic)") / AI Chat Assistant (only RockVision ✓) / Project Planning & Risk Assessment (RockVision, SafeMine ✓) / Blast Management System (only RockVision ✓) / 4K Video Processing & Analysis (RockVision, SafeMine ✓; MineGUARD "✓ (Basic)").
  - Visual encoding: the RockVision AI column is solid green ticks top to bottom, while competitors turn red in the lower rows. Rows are ordered from parity features (top) to differentiators (bottom). This is the deck's **USP proof**.
  - Self-own: in the "30-Day Historical Analysis" row, two competitors store 60-90 days against RockVision's 30. That row actually shows RockVision is weaker, yet it still gets a green tick.

**Most attractive element (my judgement from visual inspection):** the slide-6 comparison matrix. It is the only element a judge can read in 3 seconds ("their column is all green, competitors go red lower down"). The slide-2 architecture diagram comes second because it shows real engineering intent (IoT, Node-RED, time-series DB, API, multi-platform clients).

**Weaknesses (observed):**
- Image-only PDF with low-res rasters (about 1300 px source upscaled onto 1920 pt pages). Small text is blurry, and the slide-4 green box and the slide-2 diagram labels are illegible.
- Team ID is left blank on the title slide.
- There is no explicit problem/pain slide and no user story. The hook is absent, and the only problem facts sit in the tiny green box.
- Impact numbers (70-90%, 15-60 min, $2-5M) have no citation. The references are bare domain homepages rather than specific papers.
- Competitor names "RockWatch Pro" and "SafeMine 360" do not appear in the references, and could not be verified from the deck.
- Stack bloat (about 45 tools) plus many typos: "Refrences", "Comparision", "Redix", "Transformar", "Strips", "MineGAURD" vs "MineGUARD", "GitHub lab", "predict rockfall prediction".
- Inconsistent typography (3 font families), a logo collision on slide 1, and clip-art icons of mixed styles.
- AI is claimed everywhere but the model is never specified: no algorithm, features, training data, or accuracy metric. Only "mix of historical and real-time sensor data (LiDAR, drones)".
- There is no timeline, no team slide, and no prototype screenshots.

### Inferences
- Despite the weak design, the deck made the cut. This suggests SIH idea-round screeners reward (a) strict adherence to the 6-slide template slots, (b) visible architecture, (c) explicit challenges-with-mitigations, (d) quantified impact, and (e) a competitor matrix. For SIH26170 (ISRO burn-in anomaly detection), a team can beat this deck by keeping the same slot coverage but adding: a readable vector architecture with an explicit ML node, cited numbers, a specific model and metric, a named ISRO user workflow, and a clean comparison matrix (e.g. vs manual limit-check screening / MIL-STD PDA-style fixed thresholds / generic SPC).
- Row ordering in the matrix, from parity features to differentiators, is a reusable persuasion trick. Avoid rows where you are weaker.
- The four-pillar impact tree (Social/Economic/Technological/Environmental) is a pattern likely expected by judges. For ISRO it can be re-cast as Mission reliability / Cost & schedule / Technology (Atmanirbhar) / Safety.

### Gaps
- The deck gives no evidence that Tech Pioneers actually won (final result, finale nodal centre). The file name says "SIH_2025", and the README gives no provenance.
- The underlying rasters are too low-res to read the green facts box precisely. My transcription is best-effort.
- No judging scores or feedback for this deck are available.

## Q2. SIH 2026 Playbook (TechDoodles): template rules, selection, judging, mistakes, timelines, design

### Takeaway
The playbook is a **third-party** guide ("by TechDoodles") despite its cover badge "OFFICIAL PLAYBOOK • STUDENT EDITION" and its MoE/AICTE/MIC logos. It does **not** state the official template's slide count, PDF requirement, or Team ID/idea-title fields. It only says to "follow the official SIH PPT template and format shared on the SIH portal". It proposes its own **9-slide** structure, which conflicts with the official idea template's **6-slide maximum, PDF-only** rule (confirmed from secondary sources for SIH 2025). Its most useful content is PS selection (a 5-step method and a 25-point scorecard), stage-wise elimination causes, what judges reward, the 36-hour build plan, and a submission checklist.

### Cited Findings — [PB](file:///Users/himanshusolanki/Downloads/sih/SIH-Winners-PPt-and-Sources/SIH_2026_Playbook_TechDoodles_Final.pdf)

**Cover (p1), visual:** deep navy gradient (about #0F2A55 to #0B1F3F) with a white top logo strip (Ministry of Education, AICTE, MoE's Innovation Cell, SIH 2026) and a tricolour diagonal-striped right edge. There is a pill badge "OFFICIAL PLAYBOOK • STUDENT EDITION". The title "SMART INDIA HACKATHON **2026** PLAYBOOK" has 2026 in gold (about #F5B942). The subtitle reads "A complete strategy guide to selecting the right Problem Statement, generating winning Open Innovation ideas, and building a pitch deck that gets you to the Grand Finale." Below that are the SIH brain-bulb, "#SmartIndiaHackathon" / "World's Biggest Open Innovation Model", three gold-ruled callouts "COVERS PS Selection Framework / INCLUDES Top 10 Open Innovation Ideas / BONUS Best PPT / Pitch Tools 2026", and a footer "Prepared for SIH 2026 Aspirants … by TechDoodles".

**Interior design language (p2-12):** white pages with a letter-spaced orange eyebrow ("S E C T I O N 0 1", about #F26B3A), a navy bold H1 (about #0B1F3F) with a navy underline rule, and navy table headers with white caps text. Zebra rows are about #F5F7FB. Callouts are a light-blue box with a navy left bar ("Why this matters", "Reminder") or a mint box with a teal bar ("Storytelling tip"). Stat tiles are navy with gold numbers. The page footer reads "SIH 2026 Playbook / by TechDoodles".

**p2 How to use:** "Read Sections 2–3 before you touch the problem statement list. Read Section 5 only for inspiration — SIH judges reward original thinking, so treat these as starting points to customise, not copy."

**p3 SIH 2026 at a Glance**
- Organiser: "organised by the Ministry of Education's Innovation Cell (MIC) and AICTE, inviting students to build real, deployable solutions for problems submitted by government ministries, PSUs, and industry partners."
- Four navy stat tiles: "6 MEMBERS / TEAM", "36 hrs GRAND FINALE BUILD", "2 EDITIONS: SW & HW", "1 FEMALE MEMBER MIN."
- Table "The Journey, Stage by Stage", laid out as STAGE / WHAT HAPPENS / WHAT GETS YOU ELIMINATED:
  - Team Formation: "Form a 6-member cross-functional team under a faculty SPOC". Eliminated by: "Skill overlap with no domain/design/business balance"
  - PS Selection: "Browse published software & hardware problem statements and shortlist 3–5". Eliminated by: "Picking on "coolness" instead of team-fit and feasibility"
  - **Internal Hackathon**: "Compete within your own institution to earn SPOC nomination". Eliminated by: "**Presenting only slides, no working demo**"
  - **National Submission**: "SPOC uploads your idea PPT and demo video to the national portal". Eliminated by: "**Weak problem understanding, vague impact metrics**"
  - Grand Finale: "36-hour non-stop build at a nodal centre, judged live". Eliminated by: "Prototype that doesn't run, poor time management"
- Priority sectors: Healthcare; Agriculture & Food; Education; Smart Cities / IoT; Sustainability; Cybersecurity; Disaster Management & Emergency Response; Tourism, Transportation & Mobility. **Space/defence is not listed.**
- "Why this matters: Judges in 2026 explicitly expect meaningful AI integration — not AI for the sake of AI. A well-scoped, boring-sounding idea with a working model will consistently beat a flashy idea with mock screens."

**p4 How to Choose the Right PS**
- "Problem statement selection is the single biggest predictor of SIH success. Most teams lose not because of bad execution, but because they picked a PS that was either too competitive, too vague, or mismatched with their skills."
- The 5-Step Selection Method:
  1. "Audit Your Team's Real Skills First … Choose a PS your team can execute — not one that merely sounds impressive to judges. Feasibility is scored explicitly at every stage."
  2. "Read Every Shortlisted PS at Least 10 Times … Underline the actual pain point — not the feature you assume they want."
  3. "Filter for "Impactful but Less Competitive" … generic chatbots, generic dashboards attract hundreds of teams nationally."
  4. "Run a Root-Cause Check … ask "why does this problem exist today?" three times."
  5. "Validate With a Feasibility Sketch … If you cannot picture an end-to-end demo — even a rough one — the PS is too broad."
- "Common mistake: Choosing a PS because "it sounds like our final year project." Judges can tell when a solution is retrofitted onto a problem statement … problem understanding is scored as a separate criterion."
- SW vs HW table:
  - Best for: SW "Strong app/web/AI-ML skills"; HW "Electronics, IoT, embedded skills"
  - Demo risk: SW "Lower — cloud/local demo"; HW "Higher — physical failure risk on stage"
  - Differentiation: SW "Harder (more competition)"; HW "Easier if you have real hardware access"
  - Judging focus: SW "**UX, scalability, data handling**"; HW "Build quality, cost-effectiveness, robustness"

**p5 PS Shortlisting Scorecard**
- "Score every candidate problem statement out of 5 on each factor … Anything scoring under **15/25** total should be dropped."
- Criteria, with anchors for 1 / 3 / 5:
  - Team Skill Fit: "Requires tech nobody on the team knows" / "Partial overlap, needs learning" / "Matches 2+ members' core strengths"
  - Clarity of Ask: "Vague…" / "Somewhat defined outcome" / "Clear department, clear expected output"
  - Feasibility in 36 hrs: "Needs data/hardware you can't access" / "Achievable with workarounds" / "End-to-end demo is realistic"
  - Competition Level: "Generic, high-visibility topic" / "Moderately common" / "Niche but genuinely needed"
  - Real-World Impact: "Impact hard to measure/explain" / "Some measurable benefit" / "Clear beneficiary + measurable metric"
- "Pro tip: Score at least 5 problem statements before your internal hackathon … Teams that shortlist a backup PS rarely lose momentum if their first choice gets contested internally."
- Red flags include: "Building even a partial demo needs licensed data, paid APIs, or hardware you cannot source" and "No one on your team can explain the domain problem in plain language without notes".
- Green flags: "The ministry/organisation names a specific current gap", "can realistically produce a working, clickable/functional prototype in 36 hours", "partial domain knowledge", "room for a creative, non-obvious technical approach".

**p6 Open Innovation: what judges reward**
- "Judging lens for Open Innovation: **Novelty of approach, technical depth, feasibility of the working prototype, scalability, cost-effectiveness, and the size/clarity of real-world impact.**"
- Winning traits include: "Meaningful use of AI/ML — prediction, vision, or NLP — not decoration", "A believable path to real deployment (cost, scale, adoption)", "Clear before/after metrics: time saved, cost reduced, lives improved", "A demo that runs live, even if the dataset is small", "Original framing — a familiar problem solved in an unfamiliar way", "A narrow, well-defined user group".

**p7-8 Top 10 Open Innovation ideas:** Offline AI Health Screening; Crop Advisory & Disease Detection; Disaster Early-Warning & Evacuation Router; Regional-language Micro-Learning; Grievance Transparency Tracker; Smart Waste & Route Optimisation; MSME Compliance Copilot; Elderly Fall Detection wearable; Water Quality & Leak Network; Student Mental Wellness Companion. Each is shown as a numbered card with coloured tag chips. The closing caution: "Judges specifically check for incremental improvement over prior years — add a genuinely new technical angle, dataset, or deployment model." None of these ideas is space-related.

**p9 Prototype & roles**
- "A polished slide with mockups will not beat a rough but working prototype. Structure your 36 hours … around a demo-first build, not a design-first one."
- 6 roles: Tech Lead; Frontend/UX Owner; Domain Researcher ("Validates the problem, gathers real data/stats"); Integration Engineer; QA & Demo Owner ("prepares a fallback for live failures"); Pitch & Documentation Lead ("Builds the PPT, writes the narrative, rehearses the pitch").
- "Judges' most common complaint: "The prototype didn't work live." Always carry a recorded backup demo video on a local device".
- Timeline: Hours 0–4 architecture and scope lock ("do not code before this"); 4–20 core end-to-end path; 20–28 integrate; 28–32 polish UI; 32–36 rehearse, backup demo, "sleep in shifts".

**p10 PPT tools**
- "Your national-round submission is judged heavily on the PPT before anyone sees your code."
- Tools: Gamma ("export to PowerPoint before final submission since native export can lose some formatting"), Canva, "Microsoft PowerPoint + Copilot — NATIVE SIH-FORMAT COMPLIANCE: Since SIH mandates a specific PPT template, building directly in PowerPoint … keeps formatting fully compliant", Beautiful.ai, Plus AI, and "Napkin AI — turning text into diagrams — useful for the "system architecture" slide judges always ask about."
- "Reminder: Whichever tool you use, the final file must follow the official SIH PPT template and format shared on the SIH portal — download and cross-check the mandated slide order before final upload."

**p11 Pitch Deck Structure That Wins** (a 9-row table)
- "Judges spend very little time per slide during screening. Every slide must earn its place."
- Slides and what each must answer:
  1. Title & Team: "PS number, title, team name, institution"
  2. Problem Understanding: "What is the real problem, who suffers, how big is it (with data)"
  3. Proposed Solution: "What you're building, in one clear sentence"
  4. Innovation & Uniqueness: "What's different from existing solutions"
  5. Technical Approach: "Architecture diagram, tech stack, data flow"
  6. Feasibility & Prototype: "What already works, what's demoable today"
  7. Impact & Scalability: "Who benefits, measurable outcome, path to scale"
  8. Business/Deployment Model: "Cost, sustainability, who adopts it and how"
  9. Team & Roles: "Why this team can execute this specific PS"
- "Storytelling tip: Open with a real (or realistic) beneficiary scenario … Judges retain narratives better than feature lists, and it immediately proves problem understanding."

**p12 Final checklist**
- Checklist items are grouped under Problem Statement & Idea / Prototype / Presentation / Team Readiness. Presentation items:
  - "Follows the official SIH PPT template exactly (slide count, order, format)"
  - "Every slide answers one clear question — no filler slides"
  - "Rehearsed as a team at least twice against a timer"
  - "Video demonstration recorded, clear audio, under time limit"
- Others: "Checked for duplicate/near-duplicate past submissions", "Idea has a clear, named beneficiary and measurable impact", "Backup demo video recorded locally", "Tested on a device/browser different from the one used to build it".
- "You're ready when: Any single team member — not just the presenter — can walk a stranger through the problem, the solution, and the demo in under two minutes. That is the real test SIH judges apply."

**Official template rules (external, since the playbook omits them)**
- SIH 2025 idea template: "maximum slides limit is six (6), including the title slide"; "save the file in PDF and upload the same on portal. No PPT, Word Doc or any other format will be supported"; "avoid paragraphs and post your idea in points/diagrams/Infographics/pictures"; "only use provided template … without changing the idea details pointers". This comes from a web-search summary of the SIH2025 IDEA Presentation Format, not the official portal: [Scribd: SIH2025 IDEA Presentation Format](https://www.scribd.com/presentation/884917405/SIH2025-IDEA-Presentation-Format), [Scribd copy](https://www.scribd.com/document/906083636/SIH2025-IDEA-Presentation-Format).
- Template slot order: Title Page (PS ID, theme, category, team details), Idea Title/Proposed Solution, Technical Approach, Feasibility and Viability, Impact and Benefits, Research and References — [Let's Code guide](https://www.lets-code.co.in/blogs/sih-2025-complete-guide-ppt-template/). The Tech Pioneers deck matches this exactly ([TP](file:///Users/himanshusolanki/Downloads/sih/SIH-Winners-PPt-and-Sources/SIH_2025_Tech_Pioneers_High_Quality.pdf)).
- SIH 2026 timeline (secondary blogs, not official):
  - Launch "August 21, 2026"; PS release August; internal hackathons September; "Online evaluation and shortlisting" October–November; Grand Finale December 2026 (36 h) — [Reskilll](https://reskilll.com/blogs/smart-india-hackathon-2026-launched-timeline-registration-how-to-participate/)
  - The search summary also cited: internal idea submission 9 Sep 2026, SPOC nomination by 20 Sep 2026, national idea submission deadline 30 Sep 2026 — [thenewviews](https://thenewviews.com/smart-india-hackathon/), [FirstVidya](https://firstvidya.com/sih-2026-guide/). These dates were not fetched or verified.
  - Team rule: "Exactly 6 students from same institution", "Minimum 1 female member" — [Reskilll](https://reskilll.com/blogs/smart-india-hackathon-2026-launched-timeline-registration-how-to-participate/)

### Inferences
- **Conflict:** the playbook's 9-slide "Pitch Deck Structure That Wins" cannot be submitted as-is if the 2026 idea template keeps the 6-slide cap. The practical move is to fold its content into the 6 official slots:
  - Problem Understanding and a beneficiary story go onto the Title slide or the top of the Proposed Solution slide.
  - Innovation & Uniqueness goes into Proposed Solution (and the comparison table into Research & References, as Tech Pioneers did).
  - Business/Deployment goes into Feasibility & Viability.
- For an ISRO PS, the "Business model" can be reframed as a deployment/adoption path: which ISRO centre or test lab uses it, integration with existing ATE/burn-in rack logs, cost vs manual review.
- The SW-edition judging focus is "UX, scalability, data handling". SIH26170 is data-heavy, so the deck should foreground the data pipeline (sensor/parametric logs, drift features, labelled failure data) and a working demo on synthetic or public burn-in data.
- "Presenting only slides, no working demo" eliminates teams at the internal round. Bring a runnable anomaly-detection notebook or dashboard to the internal hackathon.

### Gaps
- The official SIH 2026 idea PPT template (slide count, fields, video length, PDF size limit) was not verified from sih.gov.in. The 6-slide/PDF rule is confirmed only for 2025, via third-party copies.
- The playbook gives no concrete dates and no rubric weights. Its internal-hackathon evaluation criteria are limited to the elimination causes quoted above.
- It gives no specific design advice (colours, fonts, word limits) beyond the tool list, "no filler slides", "one clear question" per slide, and diagram tools.

## Q3. Easy vs Difficult guide: classification, where ISRO/HW/SW fall, strategy

### Takeaway
The guide ranks the official **226 SIH 2026 PSs (172 software + 54 hardware)** using an **unofficial keyword heuristic**: hardware requirement, AI/ML, sensors, real-time, robotics and cryptography keywords, plus description depth. It publishes only the 5 lowest-scoring ("Easy") and 5 highest-scoring ("Difficult") PSs. **No ISRO PS appears in either list, and SIH26170 is not mentioned.** "Anomaly detection" plus AI on sensor data pushes a PS toward the Difficult end: SIH26057 "AI-Powered Underwater Marine Debris & Anomaly Detection" is rated Difficult.

### Cited Findings — [ED](file:///Users/himanshusolanki/Downloads/sih/SIH-Winners-PPt-and-Sources/SIH%202026%20-%20Easy%20vs%20Difficult%20Problem%20Statements.pdf)

- **Method (p1):** "the SIH portal doesn't publish an official difficulty rating, so every one of the 226 PS was scored on hardware requirement, technical keywords (AI/ML, sensors, real-time, robotics, cryptography etc.) and description depth."
- **p1 stats tiles:** "226 TOTAL PS REVIEWED", "172+54 SOFTWARE + HARDWARE", "5+5 EASY + DIFFICULT PICKS".
- **Easy definition:** "Pure software, CRUD-style portals with a clear, bounded scope. No AI research, sensors or hardware needed to reach a working demo."
- **Easy 5:**
  - SIH26044 (Ministry of Ayush, Academia–Industry Portal)
  - SIH26034 (Consumer Affairs, Packaged Commodities Compliance Checker)
  - SIH26036 (Consumer Affairs, Instrument Verification)
  - SIH26063 (MoES NCPOR, Polar Science Outreach Portal, category "**Space Technology**")
  - SIH26075 (MoES, CAPACITY CONNECT LMS)
  - All are Software.
- **Difficult definition:** "Defense hardware, robotics, real-time perception and adversarial ML — genuinely research-adjacent problems from DRDO, Qualcomm and MathWorks. Pick these only if your team has shipped hardware or ML systems before."
- **Difficult 5:**
  - SIH26050 (DRDO anti-drone high altitude, HW)
  - SIH26057 (MoES, "AI-Powered Underwater Marine Debris & Anomaly Detection via Side-Scan Sonar", SW)
  - SIH26104 (AICTE, voice-cloning detection, SW)
  - SIH26177 (Qualcomm, SAR drone, HW)
  - SIH26037 (MathWorks, path planning on Indian roads, SW)
  - Note that 3 of the 5 difficult picks are Software, so the SW/HW label is not the difficulty driver.
- **"Why these are hard":** "each needs either real hardware engineering under extreme conditions, live perception on unusual data (sonar, cloned audio), or full-stack robotics autonomy — genuinely research-adjacent work that a 36-hour team can only partially prototype."
- **Deep-dive format (p3, p5):** each PS card uses a fixed 5-field schema, "PROBLEM → WHY EASY/HARD → APPROACH → TECH STACK → MVP", explicitly framed as "Everything needed to draft the idea PPT". The analogous difficult anomaly case (SIH26057):
  - APPROACH "Fine-tune a CV model on public side-scan sonar datasets to flag debris vs seafloor features"
  - STACK "PyTorch/TensorFlow, sonar image preprocessing, transfer learning, GIS overlay"
  - MVP "A model flagging candidate debris regions on sample sonar image tiles."
  - The difficult set's MVPs are scoped "in 36–120 hours".
- **Strategy (p6, "Before you commit"):**
  - "Team has shipped ML or embedded systems before? The Difficult 5 offer a far less crowded field and a much stronger "wow factor" on stage."
  - "First SIH team … Start from the Easy 5 — you can still add a smart feature (OCR, matching algorithm) to stand out."
  - "Difficulty here is a heuristic, not official"
  - "scope your MVP down to the one feature above and get it fully working before adding anything else."
  - Closing: "Match the PS to your team's real skill level — not your ambition."
- **Visual design:**
  - Cream page (about #FAF6EE) and navy headings (about #12294A), with "vs" in orange (#F47B20).
  - Green-tinted "Easiest 5" and pink-tinted "Hardest 5" panels.
  - PS cards carry an outlined orange ordinal ("01"), a red left border for difficult cards, and pill tags (blue "SOFTWARE"/"HARDWARE", green "EASY", red "DIFFICULT").
  - The p6 summary table has columns PS NO. / TITLE / ORGANIZATION / CATEGORY / LEVEL.

### Inferences
- Under this guide's heuristic, SIH26170 ("AI-Driven Anomaly Detection in Component Burn-In & Screening") contains the keywords AI, anomaly detection, and sensor/real-time test data. It would therefore likely score in the upper (harder) half, though not the top 5, which were dominated by physical hardware and robotics.
- Treated as a software build on test-log data, it resembles SIH26057 (AI anomaly detection on specialised data), so it inherits the same "less crowded field, stronger wow factor" advantage. The deck should mirror the guide's PROBLEM → WHY HARD → APPROACH → STACK → MVP logic, and state a tightly scoped MVP. For example: "flag anomalous parameter drift in N burn-in channels from a sample log, with explainable per-component scores".
- The "Space Technology" category tag on an easy portal PS (SIH26063) shows that category labels do not predict difficulty. Judges and competition density depend on the actual technical ask.

### Gaps
- The guide does not publish the scores of the other 216 PSs, so SIH26170's exact placement is unknown.
- It does not cover the ISRO PS count or competition levels.

## Q4. README and assets: what the repo claims about sources

### Takeaway
The README makes **no provenance claim** for the PDFs. It calls the repo "a curated collection of Smart India Hackathon winning project presentations" and pushes a paid external "SIH Winners Vault" link. The folder structure it describes (Winners-PPTs/, Resources/, PPT-Guides/) does not match the actual repo, where all PDFs sit at the root.

### Cited Findings — [RM](file:///Users/himanshusolanki/Downloads/sih/SIH-Winners-PPt-and-Sources/README.md)
- "This repository is a curated collection of **Smart India Hackathon winning project presentations, resources, preparation materials, and useful references**".
- Promo block: "🔥 Want Previous SIH Winners' PPTs & Source Code? 🏆 ACCESS THE SIH WINNERS VAULT (2023–2025) 🚀" linking to superprofile.bio/vp/sih-winners-vault-2026-… (a commercial storefront).
- Stated locations "📁 Location: `Winners-PPTs/`", "`Resources/`", "`PPT-Guides/`". None of these exist. The actual contents are 8 PDFs at the root plus assets/.
- Contribution line: "Sharing publicly available presentations", which implies the decks are publicly sourced, but no source is given for any deck.
- Recommended 10-step structure: "1. Title & Team Introduction → 2. Problem Statement → 3. Proposed Solution → 4. How the Solution Works → 5. System Architecture → 6. Technology Stack → 7. Innovation / Unique Features → 8. Implementation & Feasibility → 9. Impact & Benefits → 10. Future Scope". This also exceeds the 6-slide official cap.
- Tips: "Focus on the Problem, Not Just the Technology … Simple + Practical + Innovative + Impactful = Strong SIH Project"; "Don't copy projects—learn from their approach".
- [assets/sih-winners.jpeg](file:///Users/himanshusolanki/Downloads/sih/SIH-Winners-PPt-and-Sources/assets/sih-winners.jpeg): a stage photo of a winning team of 6 in black tees holding trophies and "SIH 2024" posters, with officials, in front of an SIH backdrop (MoE / AICTE / MIC logos, starfield, brain-bulb). The backdrop date is partly occluded, reading "11th & 12th August 202…". The photo is from an SIH 2024 grand finale.
- [assets/sih-logo.jpeg](file:///Users/himanshusolanki/Downloads/sih/SIH-Winners-PPt-and-Sources/assets/sih-logo.jpeg): the brain-bulb logo with "SIH 2026" in the bulb base and "SMART INDIA HACKATHON" in heavy black sans above an orange/green underline split by a dot.

### Inferences
- The decks' "winner" status is asserted by filename and repo framing only. Treat the Tech Pioneers deck as "a deck that passed/competed in SIH 2025" rather than a verified national winner.
- The playbook and easy/difficult guide reuse official MoE/AICTE/MIC logos but are third-party content (TechDoodles, and an unattributed wkhtmltopdf export). Their advice is useful but not authoritative. Cross-check against sih.gov.in.

### Gaps
- There is no git history or commit authorship analysed for provenance. `.git` exists, but the environment reports "not a git repository", so this was not attempted.
- The sih-logo.jpeg "2026" version could not be confirmed as an official asset.
