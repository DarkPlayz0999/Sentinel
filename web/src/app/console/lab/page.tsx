"use client";

import dynamic from "next/dynamic";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Card, CardHead, Notice, PageHead, ReasonCode, Risk, Stamp, num,
} from "@/components/ui/kit";
import type { BoardView, PartStatus } from "@/components/twin/board";
import { AiSummary } from "@/components/ai/ai-summary";
import {
  BeforeAfter, BenchmarkView, Btn, CandidateTable, Chip, ClosedLoop, EventLog, HypothesisList,
  KV, LotStrip, PARAM_LABEL, QAList, Sparkline, StatusGlyph, UNITS, fmtParam, si,
} from "@/components/twin/lab-panels";
import {
  Catalogue, ComponentsView, LotBoard, Offer, Replacement, Reveal, SimEvent, Simulation,
  Timeline, sampleAt, simApi, useSimEvents,
} from "@/lib/sim-api";
import { ApiError } from "@/lib/screen-api";
import { C } from "@/lib/theme";
import { cn } from "@/lib/utils";

/* FAULT-INJECTION LAB - the closed loop, live.
 *
 *   create board -> burn-in -> fault develops -> measurements -> Sentinel
 *   -> agents investigate -> component identified -> 3D highlight -> reason
 *   -> replace -> rerun -> before/after -> ground truth -> benchmark
 *
 * The browser computes none of it. src/twin simulates the lot and generates
 * the four ATE reads; Sentinel's unmodified pipeline screens them; the agent
 * team investigates. In BLIND mode the API withholds the fault and every
 * internal value until the prediction exists and the operator reveals it.
 * All time on this page is ACCELERATED SIMULATION TIME. */

const BoardScene = dynamic(() => import("@/components/twin/board").then((m) => m.BoardScene), {
  ssr: false,
  loading: () => <div className="grid h-full place-items-center text-sm text-[#8FA8A2]">Loading the board…</div>,
});

const SPEEDS = [1, 10, 100, 1000];
const REFRESH_ON = new Set([
  "CHECKPOINT_REACHED", "BURN_IN_COMPLETE", "SENTINEL_RESULT", "DIAGNOSIS_COMPLETE",
  "RERUN_COMPLETED", "GROUND_TRUTH_REVEALED", "SIMULATION_FAILED", "SIMULATION_ERROR",
  "SENTINEL_INTERIM_SCREEN",
]);
const VIEWS: { k: BoardView; label: string }[] = [
  { k: "normal", label: "Assembly" },
  { k: "thermal", label: "Thermal (IR)" },
  { k: "electrical", label: "Electrical" },
  { k: "fault", label: "Fault" },
];

export default function LabPage() {
  const [cat, setCat] = useState<Catalogue | null>(null);
  const [err, setErr] = useState<ApiError | null>(null);
  const [sid, setSid] = useState<string | null>(null);
  const [sim, setSim] = useState<Simulation | null>(null);
  const [lot, setLot] = useState<LotBoard[]>([]);
  const [serial, setSerial] = useState<string | null>(null);
  const [phase, setPhase] = useState("burn-in-1");
  const [tl, setTl] = useState<Timeline | null>(null);
  const [cv, setCv] = useState<ComponentsView | null>(null);
  const [comp, setComp] = useState<string | null>(null);
  const [view, setView] = useState<BoardView>("normal");
  const [thermalLot, setThermalLot] = useState(true);
  const [t, setT] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(10);
  const [events, setEvents] = useState<SimEvent[]>([]);
  const [offer, setOffer] = useState<Offer | null>(null);
  const [repls, setRepls] = useState<Replacement[]>([]);
  const [reveal, setReveal] = useState<Reveal | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [recent, setRecent] = useState<Awaited<ReturnType<typeof simApi.list>>>([]);
  const raf = useRef<number>();

  const fail = (e: unknown) => setErr(e instanceof ApiError ? e : new ApiError(String(e)));

  // ------------------------------------------------------------- bootstrap
  useEffect(() => {
    simApi.catalogue().then(setCat).catch(fail);
    simApi.list().then(setRecent).catch(() => undefined);
    const q = new URLSearchParams(window.location.search).get("sim");
    if (q) setSid(q);
  }, []);

  const open = useCallback((id: string | null) => {
    setSid(id);
    setSim(null); setLot([]); setSerial(null); setTl(null); setCv(null); setComp(null);
    setEvents([]); setOffer(null); setRepls([]); setReveal(null); setPhase("burn-in-1"); setT(0);
    const url = id ? `?sim=${id}` : window.location.pathname;
    window.history.replaceState(null, "", url);
    if (!id) simApi.list().then(setRecent).catch(() => undefined);
  }, []);

  const refresh = useCallback(async (id: string) => {
    try {
      const [s, b, c] = await Promise.all([simApi.get(id), simApi.boards(id), simApi.comparison(id)]);
      setSim(s);
      setLot(b.boards);
      setRepls(c.replacements);
      setSerial((cur) => cur ?? s.focus_serial ?? b.boards[0]?.serial ?? null);
      setErr(null);
    } catch (e) {
      fail(e);
    }
  }, []);

  useEffect(() => {
    if (sid) refresh(sid);
  }, [sid, refresh]);

  // Jump to the board Sentinel ranked first the moment it exists.
  const focus = sim?.focus_serial ?? null;
  useEffect(() => {
    if (focus) setSerial(focus);
  }, [focus]);

  // Timeline and component explorer for the board in view.
  const simTime = sim?.sim_time_h ?? 0;
  const status = sim?.status;
  useEffect(() => {
    if (!sid || !serial) return;
    simApi.timeline(sid, serial, phase).then((x) => {
      setTl(x);
      setT((cur) => (playing ? cur : Math.max(0, x.hours[x.hours.length - 1] ?? 0)));
    }).catch(() => setTl(null));
    simApi.components(sid, serial).then(setCv).catch(() => setCv(null));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sid, serial, phase, simTime, status, sim?.revealed_at, repls.length]);

  // Live progress over SSE, with a slow poll as the fallback.
  const pending = useRef<ReturnType<typeof setTimeout>>();
  const connected = useSimEvents(sid, (e) => {
    setEvents((ev) => (ev.some((x) => x.id === e.id) ? ev : [...ev, e].slice(-400)));
    if (REFRESH_ON.has(e.type) && sid) {
      clearTimeout(pending.current);
      pending.current = setTimeout(() => refresh(sid), 250);
    }
  });
  const running = status === "QUEUED" || status === "RUNNING" || status === "SCREENING";
  useEffect(() => {
    if (!sid || !running) return;
    const h = setInterval(() => refresh(sid), 1500);
    return () => clearInterval(h);
  }, [sid, running, refresh]);

  // -------------------------------------------------------------- playback
  const tMax = tl?.hours.length ? tl.hours[tl.hours.length - 1] : 0;
  useEffect(() => {
    if (!playing) return;
    let last = performance.now();
    const tick = (now: number) => {
      const dt = (now - last) / 1000;
      last = now;
      setT((cur) => {
        const nx = cur + dt * speed;
        if (nx >= tMax) {
          setPlaying(false);
          return tMax;
        }
        return nx;
      });
      raf.current = requestAnimationFrame(tick);
    };
    raf.current = requestAnimationFrame(tick);
    return () => { if (raf.current) cancelAnimationFrame(raf.current); };
  }, [playing, speed, tMax]);

  // ------------------------------------------------------------- actions
  const act = async (label: string, fn: () => Promise<unknown>) => {
    setBusy(label);
    try {
      await fn();
      if (sid) await refresh(sid);
    } catch (e) {
      fail(e);
    } finally {
      setBusy(null);
    }
  };

  const createSim = async (body: Record<string, unknown>, start: boolean) => {
    setBusy("create");
    try {
      const s = await simApi.create(body, start);
      open(s.simulation_id);
    } catch (e) {
      fail(e);
    } finally {
      setBusy(null);
    }
  };

  // ------------------------------------------------------------- derived
  const inv = sim?.investigation ?? null;
  const diag = serial && inv?.boards ? inv.boards[serial] ?? null : null;
  const suspect = phase === "burn-in-1" ? diag?.suspect_component ?? null : null;
  const temps = useMemo(() => {
    const out: Record<string, number | null> = {};
    if (!tl) return out;
    for (const [cid, ys] of Object.entries(tl.observed.ir_temp_c)) out[cid] = sampleAt(tl.hours, ys, t);
    return out;
  }, [tl, t]);
  const lotMedian = useMemo(() => {
    const out: Record<string, number | null> = {};
    if (!tl?.observed.ir_lot_median_c) return out;
    for (const [cid, ys] of Object.entries(tl.observed.ir_lot_median_c)) out[cid] = sampleAt(tl.hours, ys, t);
    return out;
  }, [tl, t]);
  const railV = tl ? sampleAt(tl.hours, tl.observed.rail_v, t) : null;
  const statusMap = useMemo(() => {
    const m: Record<string, PartStatus> = {};
    if (phase !== "burn-in-1") return m;
    cv?.components.forEach((c) => (m[c.component_id] = (c.status as PartStatus) ?? "OK"));
    return m;
  }, [cv, phase]);
  const selComp = cv?.components.find((c) => c.component_id === comp) ?? null;
  const board = lot.find((b) => b.serial === serial) ?? null;
  const revealed = !!sim?.revealed_at;
  const replaceable = cat?.replaceable_kinds ?? [];
  const blind = sim?.mode === "BLIND";

  const steps = sim ? [
    { k: "Board created", done: true },
    { k: "Burn-in", done: sim.sim_time_h >= 168 && !["CREATED", "PAUSED"].includes(sim.status), active: running || sim.status === "PAUSED", note: `${sim.sim_time_h} h` },
    { k: "Measurements", done: sim.sim_time_h >= 168 },
    { k: "Sentinel analyses", done: !!sim.run_id, active: sim.status === "SCREENING" },
    { k: "Agents investigate", done: !!inv },
    { k: "Component identified", done: !!inv?.report?.suspect_component },
    { k: "Replace", done: repls.length > 0 },
    { k: "Rerun + compare", done: repls.length > 0 },
    { k: "Ground truth", done: revealed },
  ] : [];

  // --------------------------------------------------------------- render
  if (!cat) {
    return (
      <>
        <PageHead title="Fault-injection lab" lede="A digital twin of a burn-in board that feeds Sentinel real, simulated measurements." />
        {err ? <Offline err={err} /> : <p className="text-sm text-graphite">Connecting to the screening service…</p>}
      </>
    );
  }

  if (!sid) {
    return (
      <>
        <PageHead
          title="Fault-injection lab"
          lede={<>Build a lot of burn-in boards, hide a fault in one component, and watch the unmodified Sentinel pipeline find it from the four ATE measurements alone. Then replace the part, rerun, and check the answer against the simulator&apos;s ground truth.</>}
          right={<Chip tone="copper">ACCELERATED SIMULATION TIME</Chip>}
        />
        {err && <Offline err={err} />}
        <Setup cat={cat} busy={busy === "create"} onCreate={createSim} />
        {recent.length > 0 && (
          <Card className="mt-6">
            <CardHead title="Recent simulations" />
            <ul className="divide-y divide-hair">
              {recent.map((r) => (
                <li key={r.simulation_id}>
                  <button type="button" onClick={() => open(r.simulation_id)}
                    className="flex w-full flex-wrap items-center gap-x-4 gap-y-1 px-4 py-2.5 text-left text-sm hover:bg-well">
                    <strong>{r.lot_id}</strong>
                    <span className="text-graphite">{r.label || (r.scenario === "sih_demo" ? "SIH demo" : "custom")}</span>
                    <Chip>{r.mode}</Chip>
                    <span className="text-graphite">{r.boards} boards · seed {r.random_seed}</span>
                    <span className="ml-auto text-xs font-bold text-graphite">{r.status}</span>
                  </button>
                </li>
              ))}
            </ul>
          </Card>
        )}
        <Honesty />
      </>
    );
  }

  return (
    <>
      <PageHead
        title={`Fault-injection lab · ${sim?.lot_id ?? "…"}`}
        lede={sim ? (
          <>
            {sim.boards} RB-1 boards, {sim.config.stress_temp_c} °C soak, seed {sim.random_seed}.{" "}
            {blind && !revealed
              ? "BLIND: the fault, its component and its severity are hidden until you reveal them."
              : blind ? "Ground truth revealed." : "VISIBLE debug mode: the injected fault is shown."}
          </>
        ) : "Loading…"}
        right={
          <div className="flex flex-wrap items-center gap-2">
            <Chip tone="copper">ACCELERATED SIMULATION TIME</Chip>
            {sim && <Chip tone={blind && !revealed ? "reject" : "ink"}>{sim.mode}{blind && revealed ? " · revealed" : ""}</Chip>}
            <span className="text-xs text-graphite">{connected ? "● live" : "○ polling"}</span>
            <Btn kind="secondary" onClick={() => open(null)}>New simulation</Btn>
          </div>
        }
      />
      {err && <Offline err={err} />}
      {sim && <div className="mb-5"><ClosedLoop steps={steps} /></div>}
      {sim && !["CREATED", "QUEUED", "RUNNING", "SCREENING"].includes(sim.status) && (
        <AiSummary subject={{ context: "simulation", id: sid }}
          watch={`${sim.status}|${sim.revealed_at}|${repls.length}`}
          title="What is happening in this lot, in plain language" className="mb-5" />
      )}
      {sim?.error && (
        <Notice tone="danger" title={sim.status === "SIMULATION_FAILED" ? "SIMULATION_FAILED" : "Run failed"} className="mb-4">
          {String((sim.error as Record<string, unknown>).message ?? "")}
        </Notice>
      )}

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_400px]">
        {/* ------------------------------------------------ the twin */}
        <div className="min-w-0 space-y-4">
          <div className="overflow-hidden rounded-card border border-rule bg-[#0B2D2A]">
            <div className="flex flex-wrap items-center gap-2 border-b border-white/10 px-3 py-2">
              {VIEWS.map((v) => (
                <button key={v.k} type="button" onClick={() => setView(v.k)}
                  className={cn("rounded-ctl px-2.5 py-1 text-xs font-bold",
                    view === v.k ? "bg-[#F2A365] text-[#2A1405]" : "text-[#CFE3DE] hover:bg-white/10")}>
                  {v.label}
                </button>
              ))}
              {view === "thermal" && (
                <span className="ml-2 flex overflow-hidden rounded-ctl border border-white/20 text-[11px]">
                  {[[true, "Against its lot"], [false, "Absolute"]].map(([v, l]) => (
                    <button key={String(v)} type="button" onClick={() => setThermalLot(v as boolean)}
                      className={cn("px-2 py-0.5", thermalLot === v ? "bg-white/20 font-bold text-white" : "text-[#9FB5B0]")}>
                      {l as string}
                    </button>
                  ))}
                </span>
              )}
              <span className="ml-auto text-xs text-[#9FB5B0]">
                {serial ?? "no board"}{phase !== "burn-in-1" ? ` · ${phase} (second soak)` : ""}
              </span>
            </div>
            <div className="relative h-[clamp(360px,56vh,600px)]">
              <BoardScene
                catalogue={cat}
                view={view}
                temps={temps}
                baseline={thermalLot ? lotMedian : sim?.config.stress_temp_c ?? 125}
                heatFullC={thermalLot ? 5 : 20}
                status={statusMap}
                selected={comp}
                suspect={suspect}
                neighbours={view === "fault" ? diag?.neighbours ?? [] : []}
                ambiguity={view === "fault" ? diag?.ambiguity_group ?? [] : []}
                railV={railV}
                onPick={setComp}
              />
              <Legend view={view} thermalLot={thermalLot} />
            </div>
            <TimeBar
              t={t} tMax={tMax} playing={playing} speed={speed}
              setT={(v) => { setPlaying(false); setT(v); }}
              togglePlay={() => { if (t >= tMax) setT(0); setPlaying((p) => !p); }}
              setSpeed={setSpeed}
              reads={sim?.config.checkpoints ?? [0, 24, 96, 168]}
            />
          </div>

          <Card>
            <CardHead
              title={`The lot · ${lot.length} boards`}
              meta={sim?.verdicts ? `${sim.verdicts.REJECT} REJECT · ${sim.verdicts.WATCH} WATCH · ${sim.verdicts.ACCEPT} ACCEPT` : "not screened yet"}
              right={<span className="text-xs text-graphite">● accept ▲ watch ■ reject · copper ring = Sentinel&apos;s first-ranked board</span>}
            />
            <div className="p-4">
              <LotStrip boards={lot} selected={serial} focus={focus} onPick={(s) => { setSerial(s); setPhase("burn-in-1"); setComp(null); }} />
              {sim?.verdicts && (
                <p className="mt-3 text-xs text-graphite">
                  Sentinel sizes its REJECT band to the 5 % PDA budget of every lot, so a lot holding a single defect still
                  shows about 5 % REJECT and 10 % WATCH. The ranking is what finds the defect; the benchmark after the
                  reveal reports the overkill this policy costs.
                </p>
              )}
            </div>
          </Card>

          {tl && <Measurements tl={tl} t={t} />}
        </div>

        {/* ------------------------------------------------ the panels */}
        <aside className="min-w-0 space-y-4">
          {sim && (
            <Card>
              <CardHead title="Run" meta={`${sim.status} · ${sim.sim_time_h} h`} />
              <div className="flex flex-wrap gap-2 p-4">
                {(sim.status === "CREATED" || sim.status === "PAUSED") && (
                  <>
                    <Btn kind="copper" disabled={!!busy} onClick={() => act("start", () => simApi.start(sid))}>Run the burn-in</Btn>
                    <Btn kind="secondary" disabled={!!busy} onClick={() => act("step", () => simApi.step(sid))}>Step one read point</Btn>
                  </>
                )}
                {sim.status === "SIMULATED" && (
                  <Btn disabled={!!busy} onClick={() => act("screen", () => simApi.screen(sid))}>Send measurements to Sentinel</Btn>
                )}
                {running && <span className="text-sm text-graphite">Working… progress arrives live.</span>}
                {(sim.status === "SCREENED" || sim.status === "INVESTIGATED") && !revealed && (
                  <Btn kind="secondary" disabled={!!busy} onClick={() => act("reveal", async () => setReveal(await simApi.reveal(sid)))}>
                    Reveal ground truth
                  </Btn>
                )}
                {revealed && !reveal && (
                  <Btn kind="secondary" disabled={!!busy} onClick={() => act("reveal", async () => setReveal(await simApi.reveal(sid)))}>
                    Show the benchmark
                  </Btn>
                )}
                {busy && <span className="self-center text-xs text-graphite">{busy}…</span>}
              </div>
            </Card>
          )}

          {board && (
            <Card className="overflow-hidden">
              <CardHead title={board.serial} right={board.verdict ? <Stamp v={board.verdict} /> : <span className="text-xs text-mute">not screened</span>} />
              <div className="px-4 pb-4">
                {board.risk_score != null && board.verdict && (
                  <div className="mt-3"><Risk r={board.risk_score} v={board.verdict} /></div>
                )}
                {board.is_faulty != null && (
                  <p className="mt-2 text-xs font-semibold" style={{ color: board.is_faulty ? C.reject : C.pass }}>
                    Ground truth: {board.is_faulty ? "an injected fault is on this board" : "no injected fault"}
                  </p>
                )}
                {cv && cv.reason_codes.length > 0 && (
                  <ul className="mt-2 divide-y divide-hair">
                    {cv.reason_codes.map((r) => (
                      <ReasonCode key={r.code} r={{ code: r.code, severity: r.severity, message: r.message, feature: r.contributing_feature, value: r.feature_value, ref: r.lot_reference_value }} />
                    ))}
                  </ul>
                )}
                {cv?.forecast?.predicted_168h && (
                  <div className="mt-3">
                    <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-mute">Module B forecast of the 168 h read (model output)</p>
                    {Object.entries(cv.forecast.predicted_168h).map(([p, v]) => (
                      <KV key={p} k={PARAM_LABEL[p] ?? p} v={`${num(v, 3)} ${UNITS[p]}`}
                        sub={cv.forecast?.upper_168h ? `upper ${num(cv.forecast.upper_168h[p], 3)}` : undefined} />
                    ))}
                  </div>
                )}
              </div>
            </Card>
          )}

          {selComp && (
            <Card>
              <CardHead title={`${selComp.component_id} · ${selComp.label}`} right={<StatusGlyph s={phase === "burn-in-1" ? selComp.status : "OK"} />} />
              <div className="px-4 pb-4 pt-2">
                <KV k="Type / model" v={`${selComp.type} / ${selComp.component_model}`} />
                <KV k="Part" v={selComp.part_number} />
                {Object.entries(selComp.nominal).map(([p, v]) => (
                  <KV key={p} k={`Nominal ${selComp.param_labels[p] ?? p}`} v={si(v, selComp.units[p])} />
                ))}
                <KV k={`IR temperature at ${t.toFixed(0)} h`} v={temps[selComp.component_id] != null ? `${num(temps[selComp.component_id], 2)} °C` : "not tracked"} sub="observed, camera noise included" />
                <KV k="Anomaly score" v={selComp.anomaly_score != null ? `${num(selComp.anomaly_score, 0)} / 100` : "—"} sub="diagnostic evidence score, a similarity - not a probability" />
                <KV k="Failure probability" v="not computed" sub="nothing here is calibrated to be one" />
                {tl?.truth?.components[selComp.component_id] ? (
                  <TruthBlock tl={tl} cid={selComp.component_id} t={t} units={selComp.units} />
                ) : (
                  Object.keys(selComp.nominal).length > 0 && sim?.truth_visible === false && (
                    <p className="mt-2 text-xs text-graphite">Internal values, health and stress are simulator truth: hidden in BLIND mode until the reveal.</p>
                  )
                )}
                {replaceable.includes(selComp.type) && sim?.run_id && phase === "burn-in-1" && (
                  <Btn kind="secondary" className="mt-3" disabled={!!busy}
                    onClick={() => act("candidates", async () => setOffer(await simApi.candidates(sid, board!.serial, selComp.component_id)))}>
                    Replacement candidates for {selComp.component_id}
                  </Btn>
                )}
              </div>
            </Card>
          )}
          {!selComp && sim && (
            <Notice>Click any component on the board to open it in the explorer.</Notice>
          )}

          {inv && serial && inv.boards[serial] && phase === "burn-in-1" && (
            <Card>
              <CardHead title="Agent investigation" meta={serial === inv.report.focus_serial ? `QA/safety: ${inv.report.qa_status}` : "diagnostic agent"} />
              <div className="space-y-4 px-4 pb-4 pt-3">
                {serial === inv.report.focus_serial && <p className="text-sm">{inv.report.summary}</p>}
                {serial === inv.report.focus_serial && inv.explanation && (
                  <div className="rounded-ctl border border-[#6D4AB8]/35 bg-[#F6F3FC] px-3 py-2">
                    <p className="text-xs font-bold text-[#3E2A74]">
                      ✦ Explainer agent · {inv.explanation.source === "mistral"
                        ? `Mistral ${inv.explanation.model}, numbers checked` : "built-in wording"}
                    </p>
                    <p className="mt-1 whitespace-pre-line text-sm">{inv.explanation.plain_summary}</p>
                  </div>
                )}
                <div>
                  <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-mute">Root-cause hypotheses · evidence score (not a probability)</p>
                  <HypothesisList hyps={inv.boards[serial].hypotheses.slice(0, 5)} onPick={setComp} />
                </div>
                {inv.boards[serial].ambiguity_group.length > 0 && (
                  <Notice tone="warn" title="Ambiguity group">
                    {inv.boards[serial].ambiguity_group.join(", ")} produce the same signature on every measurement. Separate them with:
                    <ul className="mt-1 list-disc pl-5">
                      {inv.boards[serial].discriminating_tests.map((d) => <li key={d.component_id}><strong>{d.component_id}</strong>: {d.test}</li>)}
                    </ul>
                  </Notice>
                )}
                <div className="text-xs text-graphite">
                  <p>Evidence Sentinel handed over: drift z {Object.entries(inv.boards[serial].observed.ate_drift_z).map(([p, z]) => `${p.split("_")[0]} ${z}`).join(" · ")}</p>
                  {inv.boards[serial].hot_components.length > 0 && <p>IR hot spot: {inv.boards[serial].hot_components.join(", ")}</p>}
                  {inv.boards[serial].neighbours.length > 0 && <p>Neighbours of the suspect: {inv.boards[serial].neighbours.join(", ")}; shares nets with {inv.boards[serial].electrical_dependencies.join(", ") || "none"}</p>}
                </div>
                {serial === inv.report.focus_serial && inv.qa_safety && (
                  <details>
                    <summary className="cursor-pointer text-sm font-semibold">QA / safety checks</summary>
                    <QAList checks={inv.qa_safety.checks} />
                  </details>
                )}
                {serial === inv.report.focus_serial && (
                  <div>
                    <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-mute">Recommended</p>
                    <ul className="list-disc space-y-1 pl-5 text-sm">
                      {inv.report.recommended_actions.map((a) => <li key={a}>{a}</li>)}
                    </ul>
                    <div className="mt-3 flex flex-wrap gap-2">
                      {inv.report.suspect_component && (
                        <Btn kind="copper" disabled={!!busy}
                          onClick={() => act("candidates", async () => {
                            setComp(inv.report.suspect_component);
                            setOffer(await simApi.candidates(sid, serial, inv.report.suspect_component!));
                          })}>
                          Replace {inv.report.suspect_component}
                        </Btn>
                      )}
                      {["HOLD", "SCRAP"].map((d) => (
                        <Btn key={d} kind="secondary" disabled={!!busy}
                          onClick={() => act("decision", () => simApi.decide(sid, serial, d, "recorded from the lab"))}>
                          Record {d.toLowerCase()}
                        </Btn>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </Card>
          )}

          {offer && (
            <Card>
              <CardHead title={`Replace ${offer.component_id} on ${offer.serial}`} />
              <div className="p-4">
                <p className="mb-3 text-xs text-graphite">Ranked on stated, measurable criteria. The score is a ranking score: {offer.score_kind}. Each candidate&apos;s real condition is only known after the rerun.</p>
                <CandidateTable cands={offer.candidates} busy={!!busy}
                  onFit={(id) => act("rerun", async () => {
                    const r = await simApi.replace(sid, offer.serial, offer.component_id, id);
                    setRepls(r.replacements);
                    setOffer(null);
                  })} />
              </div>
            </Card>
          )}

          {repls.length > 0 && (
            <Card>
              <CardHead title="Before / after" meta={`${repls.length} rework${repls.length > 1 ? "s" : ""}`} />
              <div className="space-y-4 p-4">
                {repls.map((r) => (
                  <div key={r.replacement_id}>
                    <div className="mb-2 flex flex-wrap items-center gap-2 text-sm">
                      <strong>{r.board_serial}</strong>
                      <span className="text-graphite">{r.component_id} → {r.candidate_id} · {r.phase}</span>
                      <Btn kind="secondary" className="ml-auto !px-2 !py-1 text-xs"
                        onClick={() => { setSerial(r.board_serial); setPhase(r.phase); setComp(r.component_id); }}>
                        View the rerun in 3D
                      </Btn>
                    </div>
                    <BeforeAfter r={r} keyParams={cat.key_params[cat.board.components.find((c) => c.component_id === r.component_id)?.type ?? ""] ?? []} />
                    {r.truth && (
                      <p className="mt-2 text-xs text-graphite">
                        Truth: removed {Object.entries(r.truth.truth_before).map(([k, v]) => `${k} ${fmtParam(k, v)}`).join(", ")}
                        {r.truth.latent_fault ? " · the new part carried its own latent defect" : " · the new part was sound"}.
                      </p>
                    )}
                  </div>
                ))}
                {phase !== "burn-in-1" && (
                  <Btn kind="secondary" onClick={() => setPhase("burn-in-1")}>Back to the original soak</Btn>
                )}
              </div>
            </Card>
          )}

          {reveal && (
            <Card>
              <CardHead title="Ground truth and benchmark" meta={reveal.operating_point} />
              <div className="space-y-4 p-4">
                <div>
                  <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-mute">Injected faults</p>
                  {reveal.faults.map((f) => (
                    <p key={`${f.board_serial}${f.component_id}`} className="text-sm">
                      <button type="button" className="font-bold underline underline-offset-2" onClick={() => { setSerial(f.board_serial); setPhase("burn-in-1"); setComp(f.component_id); }}>{f.board_serial}</button>{" "}
                      {f.component_id} {f.fault_type.replace(/_/g, " ").toLowerCase()} · severity {f.severity.toFixed(2)} from {f.start_h.toFixed(0)} h ({f.source})
                      {" → "}Sentinel: {reveal.faulty_boards.find((b) => b.serial === f.board_serial)?.sentinel_verdict ?? "—"}
                    </p>
                  ))}
                  {reveal.replacements.map((r) => (
                    <p key={r.board_serial + r.replaced} className="text-sm text-graphite">
                      Rework on {r.board_serial}: replaced {r.replaced} - {r.was_the_faulty_part ? "the faulty part" : "NOT the faulty part"}, rerun {r.outcome}.
                    </p>
                  ))}
                </div>
                <BenchmarkView b={reveal.benchmark} compact />
              </div>
            </Card>
          )}

          <Card>
            <CardHead title="Audit trail" meta="live, from the simulation event table" />
            <div className="p-4"><EventLog events={events} /></div>
          </Card>
        </aside>
      </div>
      <Honesty />
    </>
  );
}

// ================================================================ pieces
function Offline({ err }: { err: ApiError }) {
  return (
    <Notice tone="danger" title="The screening service is not reachable" className="mb-4">
      {err.message}
      {err.hint && <code className="mt-1 block">{err.hint}</code>}
    </Notice>
  );
}

function Honesty() {
  return (
    <p className="mt-10 max-w-prose text-xs text-mute">
      <strong className="font-semibold text-graphite">Simulated research tool.</strong> Measurements come from
      src/twin (MNA circuit solves and a lumped thermal model; ngspice when installed), in accelerated simulation
      time. Not flight certified, not space qualified, not a validated burn-in: decision support only. Evidence
      scores are similarities and ranking scores are rankings; neither is a probability.{" "}
      <Link href="/console/benchmark" className="underline underline-offset-2">Blind benchmark campaigns →</Link>
    </p>
  );
}

function Legend({ view, thermalLot }: { view: BoardView; thermalLot: boolean }) {
  const item = (c: string, t: string) => (
    <span key={t} className="flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-sm" style={{ background: c }} />{t}</span>
  );
  return (
    <div className="pointer-events-none absolute bottom-2 left-2 flex max-w-[95%] flex-wrap gap-x-3 gap-y-1 rounded bg-[#071816]/80 px-2 py-1.5 text-[11px] text-[#CFE3DE]">
      {view === "thermal" && (thermalLot
        ? [item("#3B78A6", "+0.8 °C"), item("#F2C14E", "+2 °C"), item("#F2834C", "+4 °C"), item("#FF5046", "+5 °C above the same part on sibling boards")]
        : [item("#3B78A6", "+3 °C"), item("#F2C14E", "+9 °C"), item("#F2834C", "+15 °C"), item("#FF5046", "+20 °C over the chamber")])}
      {view === "electrical" && [item("#7FD6A8", "VDD at nominal"), item("#F2A365", "VDD drooping"), item("#8EBBDD", "OUT"), item("#B79CE0", "gate drive"), item("#FFE08A", "current flow")]}
      {view === "fault" && [item("#FF6B5E", "suspect + affected region"), item("#F2C14E", "neighbours"), item("#F2A365", "ambiguity group")]}
      {view === "normal" && <span>● OK · ▲ WATCH · ■ REJECT - status from the agents, never colour alone</span>}
      {view !== "normal" && <span className="text-[#8FA8A2]">visual states, not certification limits</span>}
    </div>
  );
}

function TimeBar({
  t, tMax, playing, speed, setT, togglePlay, setSpeed, reads,
}: {
  t: number; tMax: number; playing: boolean; speed: number; setT: (v: number) => void;
  togglePlay: () => void; setSpeed: (v: number) => void; reads: number[];
}) {
  return (
    <div className="border-t border-white/10 px-3 py-3 text-[#CFE3DE]">
      <div className="flex flex-wrap items-center gap-3">
        <button type="button" onClick={togglePlay} disabled={tMax <= 0}
          className="rounded-ctl bg-[#9C4F1F] px-3 py-1.5 text-sm font-bold text-white disabled:opacity-40">
          {playing ? "Pause" : t >= tMax && tMax > 0 ? "Replay" : "Play"}
        </button>
        <button type="button" onClick={() => setT(Math.min(tMax, Math.floor(t / 3) * 3 + 3))}
          className="rounded-ctl border border-white/20 px-2 py-1.5 text-xs font-bold">Step +3 h</button>
        <input type="range" min={0} max={Math.max(tMax, 0.001)} step={0.5} value={Math.min(t, tMax)}
          onChange={(e) => setT(Number(e.target.value))}
          className="min-w-[160px] flex-1 accent-[#F2A365]" aria-label="Simulated hour" />
        <span className="wide w-16 text-right text-lg font-black tabular-nums text-[#F2A365]">{t.toFixed(0)} h</span>
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-2 text-[11px]">
        {reads.map((h) => (
          <button key={h} type="button" disabled={h > tMax} onClick={() => setT(h)}
            className="rounded border border-white/15 px-1.5 py-0.5 hover:text-[#F7C49A] disabled:opacity-30">{h} h</button>
        ))}
        <span className="ml-2 text-[#8FA8A2]">speed</span>
        {SPEEDS.map((s) => (
          <button key={s} type="button" onClick={() => setSpeed(s)}
            className={cn("rounded px-1.5 py-0.5", speed === s ? "bg-[#F2A365] font-bold text-[#2A1405]" : "hover:text-[#F7C49A]")}>
            {s}×
          </button>
        ))}
        <span className="ml-auto text-[#8FA8A2]">1× = one simulated hour per second · ACCELERATED SIMULATION TIME</span>
      </div>
    </div>
  );
}

function TruthBlock({ tl, cid, t, units }: { tl: Timeline; cid: string; t: number; units: Record<string, string> }) {
  const c = tl.truth!.components[cid];
  const at = (ys: (number | null)[] | null) => sampleAt(tl.hours, ys, t);
  const health = at(c.health);
  return (
    <div className="mt-3 rounded-ctl border border-dashed border-copper/60 bg-copper/5 p-3">
      <p className="mb-1 text-xs font-bold uppercase tracking-wide text-copper">Simulator truth (visible)</p>
      {Object.entries(c.values).map(([p, ys]) => (
        <KV key={p} k={`Now: ${p}`} v={si(at(ys), units[p] ?? "")} />
      ))}
      {health != null && <KV k="Health / degradation" v={`${(health * 100).toFixed(0)} % / ${((1 - health) * 100).toFixed(0)} %`} sub="simulator index vs end-of-life change" />}
      {c.stress && <KV k="Stress" v={num(at(c.stress), 2)} sub="max of dissipation/rating and temperature/Tmax" />}
      {c.temp_c && (
        <div className="mt-2">
          <Sparkline hours={tl.hours} ys={c.temp_c} t={t} color={C.copper} label={`${cid} true temperature, °C`} fmt={(v) => `${v.toFixed(1)} °C`} />
        </div>
      )}
      {tl.truth!.faults.filter((f) => f.component_id === cid).map((f) => (
        <p key={f.fault_type} className="mt-2 text-xs font-semibold text-reject">
          Injected: {f.fault_type.replace(/_/g, " ").toLowerCase()}, severity {f.severity.toFixed(2)}, onset {f.start_h.toFixed(0)} h
        </p>
      ))}
    </div>
  );
}

function Measurements({ tl, t }: { tl: Timeline; t: number }) {
  return (
    <Card>
      <CardHead title="What the tester and the camera saw" meta={`${tl.serial} · observed values only · provenance ${tl.provenance.Iddq_uA?.measurement_source} (${tl.provenance.Iddq_uA?.solver})`} />
      <div className="grid gap-4 p-4 sm:grid-cols-2">
        {Object.entries(tl.observed.ate).map(([p, rows]) => (
          <div key={p}>
            <p className="text-xs font-semibold text-graphite">{PARAM_LABEL[p] ?? p}</p>
            <div className="mt-1 flex gap-3 text-sm tabular-nums">
              {rows.map((r) => (
                <span key={r.time_h} className={cn(r.time_h <= t ? "text-ink" : "text-mute")}>
                  <span className="block text-[11px] text-mute">{r.time_h} h</span>
                  {r.value == null ? "drop" : num(r.value, p === "Vol_mV" ? 1 : 3)}
                </span>
              ))}
              <span className="self-end text-xs text-mute">{UNITS[p]}</span>
            </div>
          </div>
        ))}
        <div className="sm:col-span-2">
          <p className="text-xs font-semibold text-graphite">Rail monitor, dynamic VDD (observed)</p>
          <Sparkline hours={tl.hours} ys={tl.observed.rail_v} t={t} label="VDD under burn-in load, V" fmt={(v) => `${v.toFixed(3)} V`} />
        </div>
      </div>
    </Card>
  );
}

// ================================================================= setup
interface FaultRow { component_id: string; fault_type: string; severity: number; start_h: number; growth_rate: number; board: string }

function Setup({ cat, busy, onCreate }: {
  cat: Catalogue; busy: boolean; onCreate: (body: Record<string, unknown>, start: boolean) => void;
}) {
  const parts = cat.board.components.filter((c) => c.type !== "test_point");
  const [mode, setMode] = useState<"VISIBLE" | "BLIND">("VISIBLE");
  const [boards, setBoards] = useState(200);
  const [seed, setSeed] = useState(42);
  const [temp, setTemp] = useState(125);
  const [noise, setNoise] = useState(1.5);
  const [irNoise, setIrNoise] = useState(0.5);
  const [hidden, setHidden] = useState(1);
  const [label, setLabel] = useState("");
  const [faults, setFaults] = useState<FaultRow[]>([
    { component_id: "Q001", fault_type: "VTH_DRIFT", severity: 0.6, start_h: 24, growth_rate: 0.01, board: "" },
  ]);
  const kindOf = (cid: string) => cat.board.components.find((c) => c.component_id === cid)?.type ?? "";
  const upd = (i: number, patch: Partial<FaultRow>) => setFaults((fs) => fs.map((f, j) => (j === i ? { ...f, ...patch } : f)));

  const body = (): Record<string, unknown> => {
    const n = noise / 100;
    return {
      mode, boards, seed, stress_temp_c: temp, label,
      noise: { current_noise: n, voltage_noise: n, timing_noise: n, temperature_noise_c: irNoise },
      faults: mode === "VISIBLE" ? faults.map((f) => ({ ...f, board: f.board === "" ? undefined : Number(f.board) })) : [],
      hidden_faults: mode === "BLIND" ? { count: hidden } : undefined,
    };
  };

  return (
    <div className="grid gap-6 lg:grid-cols-[360px_minmax(0,1fr)]">
      <Card className="border-copper/50">
        <CardHead title="The SIH demonstration" />
        <div className="space-y-3 p-4 text-sm">
          <p>
            One capacitor on one board, somewhere in a lot of 200, develops ESR degradation during accelerated burn-in.
            Healthy at 0 h, a small deviation by 24 h, clear drift by 96 h, significant by 168 h - and it never breaks a
            datasheet limit.
          </p>
          <p className="text-graphite">Runs BLIND: the board, the part and the severity stay hidden until Sentinel and the agents have committed to an answer.</p>
          <Btn kind="copper" disabled={busy} onClick={() => onCreate({ scenario: "sih_demo" }, true)}>Run the demo, blind</Btn>
          <Btn kind="secondary" className="ml-2" disabled={busy} onClick={() => onCreate({ scenario: "sih_demo", auto_screen: true }, false)}>Step through it</Btn>
        </div>
      </Card>

      <Card>
        <CardHead title="Build your own experiment" />
        <div className="grid gap-4 p-4 sm:grid-cols-2">
          <div className="space-y-3 text-sm">
            <div className="flex gap-2">
              {(["VISIBLE", "BLIND"] as const).map((m) => (
                <button key={m} type="button" onClick={() => setMode(m)}
                  className={cn("flex-1 rounded-ctl border px-3 py-2 text-left", mode === m ? "border-ink bg-ink text-sheet" : "border-rule")}>
                  <span className="block text-sm font-bold">{m === "VISIBLE" ? "Visible debug" : "Blind evaluation"}</span>
                  <span className="text-xs opacity-80">{m === "VISIBLE" ? "you see the injected fault" : "the simulator hides it"}</span>
                </button>
              ))}
            </div>
            <Field label={`Lot size: ${boards} boards`}><input type="range" min={60} max={400} step={20} value={boards} onChange={(e) => setBoards(+e.target.value)} className="w-full accent-[#9C4F1F]" /></Field>
            <Field label={`Soak temperature: ${temp} °C`}><input type="range" min={85} max={150} step={5} value={temp} onChange={(e) => setTemp(+e.target.value)} className="w-full accent-[#9C4F1F]" /></Field>
            <Field label={`Tester repeatability: ${noise.toFixed(1)} %`}><input type="range" min={0.4} max={3.5} step={0.1} value={noise} onChange={(e) => setNoise(+e.target.value)} className="w-full accent-[#9C4F1F]" /></Field>
            <Field label={`IR camera noise: ${irNoise.toFixed(1)} °C`}><input type="range" min={0} max={2} step={0.1} value={irNoise} onChange={(e) => setIrNoise(+e.target.value)} className="w-full accent-[#9C4F1F]" /></Field>
            <div className="flex gap-3">
              <Field label="Seed"><input type="number" value={seed} onChange={(e) => setSeed(+e.target.value)} className="w-24 rounded-ctl border border-rule px-2 py-1.5" /></Field>
              <Field label="Label"><input value={label} onChange={(e) => setLabel(e.target.value)} className="w-full rounded-ctl border border-rule px-2 py-1.5" /></Field>
            </div>
          </div>

          <div className="space-y-3 text-sm">
            {mode === "BLIND" ? (
              <>
                <Field label={`Hidden faults the simulator draws: ${hidden}`}>
                  <input type="range" min={1} max={20} value={hidden} onChange={(e) => setHidden(+e.target.value)} className="w-full accent-[#9C4F1F]" />
                </Field>
                <p className="text-xs text-graphite">Drawn from faults that move at least one observable on this board, with random board, part, severity (0.4–1.0) and onset. Nobody - including you - sees them until the reveal.</p>
              </>
            ) : (
              <>
                <p className="text-xs font-semibold uppercase tracking-wide text-mute">Fault injection</p>
                {faults.map((f, i) => {
                  const models = cat.faults[kindOf(f.component_id)] ?? [];
                  const ch = cat.detectability[f.component_id]?.[f.fault_type] ?? [];
                  return (
                    <div key={i} className="space-y-2 rounded-ctl border border-rule p-2">
                      <div className="flex gap-2">
                        <select value={f.component_id} className="flex-1 rounded-ctl border border-rule px-2 py-1.5"
                          onChange={(e) => upd(i, { component_id: e.target.value, fault_type: cat.faults[kindOf(e.target.value)]?.[0]?.fault_type ?? "" })}>
                          {parts.map((c) => <option key={c.component_id} value={c.component_id}>{c.component_id} · {c.label}</option>)}
                        </select>
                        <button type="button" className="text-xs text-reject" onClick={() => setFaults((fs) => fs.filter((_, j) => j !== i))}>remove</button>
                      </div>
                      <select value={f.fault_type} onChange={(e) => upd(i, { fault_type: e.target.value })} className="w-full rounded-ctl border border-rule px-2 py-1.5">
                        {models.map((m) => <option key={m.fault_type} value={m.fault_type}>{m.fault_type.replace(/_/g, " ").toLowerCase()}</option>)}
                      </select>
                      <p className={cn("text-xs", ch.length ? "text-graphite" : "text-reject")}>
                        {ch.length ? `Observable via: ${ch.join(", ")}` : "No modelled effect on any measurement of this board - Sentinel cannot see it."}
                      </p>
                      <Field label={`Severity ${f.severity.toFixed(2)} (fraction of full scale at 168 h)`}><input type="range" min={0.1} max={1.5} step={0.05} value={f.severity} onChange={(e) => upd(i, { severity: +e.target.value })} className="w-full accent-[#9C4F1F]" /></Field>
                      <Field label={`Onset ${f.start_h} h · growth ${f.growth_rate.toFixed(3)}/h`}>
                        <div className="flex gap-2">
                          <input type="range" min={0} max={144} step={6} value={f.start_h} onChange={(e) => upd(i, { start_h: +e.target.value })} className="flex-1 accent-[#9C4F1F]" />
                          <input type="range" min={0} max={0.03} step={0.002} value={f.growth_rate} onChange={(e) => upd(i, { growth_rate: +e.target.value })} className="flex-1 accent-[#9C4F1F]" />
                        </div>
                      </Field>
                      <Field label="Board index (blank = chosen from the seed)"><input value={f.board} onChange={(e) => upd(i, { board: e.target.value.replace(/\D/g, "") })} className="w-24 rounded-ctl border border-rule px-2 py-1" /></Field>
                    </div>
                  );
                })}
                <Btn kind="secondary" onClick={() => setFaults((fs) => [...fs, { component_id: "C001", fault_type: "ESR_INCREASE", severity: 0.8, start_h: 24, growth_rate: 0.015, board: "" }])}>
                  Add a fault
                </Btn>
              </>
            )}
            <div className="flex gap-2 pt-2">
              <Btn kind="copper" disabled={busy} onClick={() => onCreate(body(), true)}>Create and run</Btn>
              <Btn kind="secondary" disabled={busy} onClick={() => onCreate(body(), false)}>Create, then step</Btn>
            </div>
          </div>
        </div>
      </Card>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block text-xs text-graphite">
      {label}
      <div className="mt-1 text-sm text-ink">{children}</div>
    </label>
  );
}
