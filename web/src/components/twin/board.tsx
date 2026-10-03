"use client";

import { Canvas, ThreeEvent, useFrame } from "@react-three/fiber";
import { Html, Line, OrbitControls } from "@react-three/drei";
import { useEffect, useMemo, useRef } from "react";
import * as THREE from "three";
import type { BoardComponent, Catalogue } from "@/lib/sim-api";

/* THE BOARD, IN THREE DIMENSIONS - reference board RB-1 as an engineering twin.
 *
 * Every object here is keyed by the backend component ID (C001, Q001, ...),
 * and its position and size come from the board definition the API serves
 * (src/twin/board.py). Nothing is placed by hand in this file, so the 3D
 * object, the backend record and the simulation model cannot disagree.
 *
 * Four views, each a restrained engineering visualisation:
 *   normal      the assembly, status glyphs on every part
 *   thermal     heat map from the IR camera readings (OBSERVED, noise included)
 *   electrical  rails coloured by the monitored rail voltage, current flow
 *   fault       the part the agents suspect, its neighbourhood, the rest dimmed
 *
 * Status is never colour alone: every label carries a glyph (circle OK,
 * triangle WATCH, square REJECT) and a word in the side panel. Heat-map
 * colours are visualisation states, not certification limits. */

export type BoardView = "normal" | "thermal" | "electrical" | "fault";
export type PartStatus = "OK" | "WATCH" | "REJECT";

const S = 0.1; // world units per millimetre
const GLYPH: Record<PartStatus, string> = { OK: "●", WATCH: "▲", REJECT: "■" };
const STATUS_COLOR: Record<PartStatus, string> = { OK: "#CFE3DE", WATCH: "#F2C14E", REJECT: "#FF6B5E" };
const SELECT = "#5BD7E0";

export interface BoardSceneProps {
  catalogue: Catalogue;
  view: BoardView;
  /** IR temperature of each tracked part at the current hour, C (observed). */
  temps: Record<string, number | null>;
  /** What the heat map subtracts: the chamber, or each position's lot median. */
  baseline: Record<string, number | null> | number;
  /** Rise, C, at which the heat map saturates. */
  heatFullC: number;
  status: Record<string, PartStatus>;
  selected: string | null;
  suspect: string | null;
  neighbours: string[];
  ambiguity: string[];
  /** Monitored rail voltage (observed), for the electrical view. */
  railV: number | null;
  onPick: (cid: string | null) => void;
}

function useLayout(cat: Catalogue) {
  return useMemo(() => {
    const [W, H] = cat.board.size_mm;
    const at = (x: number, y: number): [number, number] => [(x - W / 2) * S, (H / 2 - y) * S];
    const byId: Record<string, BoardComponent> = {};
    cat.board.components.forEach((c) => (byId[c.component_id] = c));
    return { W, H, at, byId };
  }, [cat]);
}

// ------------------------------------------------------------------ parts
function Pins({ n, len, side, w, d }: { n: number; len: number; side: "x" | "z"; w: number; d: number }) {
  const pins = [];
  for (let i = 0; i < n; i++) {
    const f = n === 1 ? 0 : (i / (n - 1) - 0.5) * 0.8;
    for (const s of [-1, 1]) {
      const pos: [number, number, number] =
        side === "z" ? [f * w, -0.02, s * (d / 2 + len / 2)] : [s * (w / 2 + len / 2), -0.02, f * d];
      const size: [number, number, number] = side === "z" ? [0.035, 0.03, len] : [len, 0.03, 0.035];
      pins.push(
        <mesh key={`${i}${s}`} position={pos} raycast={() => null}>
          <boxGeometry args={size} />
          <meshStandardMaterial color="#C9CDD2" metalness={0.8} roughness={0.3} />
        </mesh>,
      );
    }
  }
  return <>{pins}</>;
}

function bodyColor(c: BoardComponent): string {
  switch (c.type) {
    case "capacitor":
      return c.part_number.includes("tantalum") ? "#C98A2E" : c.part_number.includes("C0G") ? "#B9A487" : "#C7B28E";
    case "resistor":
      return "#1F2326";
    case "ic":
    case "mosfet":
      return "#1A1D20";
    case "connector":
      return "#2B2F33";
    case "test_point":
      return "#D4AF37";
    default:
      return "#B87333";
  }
}

function Part({
  c, at, status, dim, glow, onPick,
}: {
  c: BoardComponent;
  at: (x: number, y: number) => [number, number];
  status: PartStatus;
  dim: boolean;
  glow: boolean;
  onPick: (cid: string) => void;
}) {
  const [x, z] = at(c.position_mm[0], c.position_mm[1]);
  const w = c.size_mm[0] * S;
  const d = c.size_mm[1] * S;
  const h = Math.max(c.size_mm[2] * S, 0.02);
  const mat = useRef<THREE.MeshStandardMaterial>(null!);

  useFrame(({ clock }) => {
    if (!mat.current) return;
    const pulse = glow ? 0.35 + 0.3 * Math.sin(clock.elapsedTime * 3) : 0;
    mat.current.emissiveIntensity = pulse;
  });

  const pick = (e: ThreeEvent<PointerEvent>) => {
    e.stopPropagation();
    onPick(c.component_id);
  };

  if (c.type === "test_point") {
    return (
      <group position={[x, 0, z]} onPointerDown={pick}>
        <mesh position={[0, 0.02, 0]}>
          <cylinderGeometry args={[w / 2, w / 2, 0.04, 20]} />
          <meshStandardMaterial ref={mat} color={bodyColor(c)} metalness={0.9} roughness={0.25}
            emissive="#FF3B2F" transparent opacity={dim ? 0.35 : 1} />
        </mesh>
      </group>
    );
  }
  if (c.type === "power_rail") {
    return (
      <group position={[x, 0, z]} onPointerDown={pick}>
        <mesh position={[0, 0.012, 0]}>
          <boxGeometry args={[w, 0.02, d]} />
          <meshStandardMaterial ref={mat} color="#C07A3C" metalness={0.85} roughness={0.35}
            emissive="#FF3B2F" transparent opacity={dim ? 0.35 : 0.95} />
        </mesh>
      </group>
    );
  }

  return (
    <group position={[x, h / 2 + 0.01, z]} onPointerDown={pick}>
      <mesh castShadow>
        <boxGeometry args={[w, h, d]} />
        <meshStandardMaterial ref={mat} color={bodyColor(c)} roughness={0.55} metalness={0.15}
          emissive="#FF3B2F" emissiveIntensity={0} transparent opacity={dim ? 0.3 : 1} />
      </mesh>
      {c.type === "resistor" && (
        <>
          {[-1, 1].map((s) => (
            <mesh key={s} position={[s * (w / 2 - w * 0.08), 0, 0]} raycast={() => null}>
              <boxGeometry args={[w * 0.16, h * 1.02, d * 1.02]} />
              <meshStandardMaterial color="#D8DCDF" metalness={0.7} roughness={0.35} transparent opacity={dim ? 0.3 : 1} />
            </mesh>
          ))}
        </>
      )}
      {c.type === "capacitor" && c.part_number.includes("tantalum") && (
        <mesh position={[-w / 2 + w * 0.12, h / 2 + 0.002, 0]} raycast={() => null}>
          <boxGeometry args={[w * 0.12, 0.004, d * 0.95]} />
          <meshStandardMaterial color="#6B4513" />
        </mesh>
      )}
      {c.type === "ic" && <Pins n={4} len={0.1} side="z" w={w} d={d} />}
      {c.type === "mosfet" && <Pins n={2} len={0.06} side="z" w={w} d={d} />}
      {c.type === "connector" && (
        <>
          {[-1.5, -0.5, 0.5, 1.5].map((i) => (
            <mesh key={i} position={[0, h / 2 + 0.12, i * 0.254]} raycast={() => null}>
              <boxGeometry args={[0.064, 0.24, 0.064]} />
              <meshStandardMaterial color="#D4AF37" metalness={0.9} roughness={0.2} />
            </mesh>
          ))}
        </>
      )}
      {c.type === "ic" && (
        <mesh position={[-w / 2 + 0.07, h / 2 + 0.002, -d / 2 + 0.07]} raycast={() => null}>
          <cylinderGeometry args={[0.03, 0.03, 0.004, 12]} />
          <meshStandardMaterial color="#555" />
        </mesh>
      )}
    </group>
  );
}

// ----------------------------------------------------------------- copper
function manhattan(a: [number, number], b: [number, number]): [number, number, number][] {
  const y = 0.006;
  return [[a[0], y, a[1]], [b[0], y, a[1]], [b[0], y, b[1]]];
}

function Traces({
  cat, at, view, railV, dimAll,
}: {
  cat: Catalogue;
  at: (x: number, y: number) => [number, number];
  view: BoardView;
  railV: number | null;
  dimAll: boolean;
}) {
  const byId = useMemo(() => {
    const m: Record<string, BoardComponent> = {};
    cat.board.components.forEach((c) => (m[c.component_id] = c));
    return m;
  }, [cat]);

  const rail = railV == null ? null : Math.max(0, Math.min(1, (3.3 - railV) / 0.4));
  const netColor = (net: string) => {
    if (view !== "electrical") return "#B87333";
    if (net === "VDD" || net === "VDD_IN") {
      // Rail colour follows the monitored dynamic rail voltage: neutral copper
      // at nominal, amber as it droops. A visual state, not a limit.
      if (rail == null) return "#B87333";
      return new THREE.Color("#7FD6A8").lerp(new THREE.Color("#F2A365"), rail).getStyle();
    }
    if (net === "OUT") return "#8EBBDD";
    if (net === "GATE" || net === "DRV") return "#B79CE0";
    if (net === "GND") return "#5F7A76";
    return "#C9D8D4";
  };

  const lines: { key: string; pts: [number, number, number][]; color: string; w: number }[] = [];
  Object.entries(cat.board.nets).forEach(([net, members]) => {
    if (net === "GND" && view !== "electrical") return;
    for (let i = 1; i < members.length; i++) {
      const a = byId[members[i - 1]];
      const b = byId[members[i]];
      if (!a || !b) continue;
      lines.push({
        key: `${net}${i}`,
        pts: manhattan(at(a.position_mm[0], a.position_mm[1]), at(b.position_mm[0], b.position_mm[1])),
        color: netColor(net),
        w: net === "VDD" || net === "VDD_IN" ? 3 : net === "GND" ? 1 : 2,
      });
    }
  });

  return (
    <>
      {lines.map((l) => (
        <Line key={l.key} points={l.pts} color={l.color} lineWidth={l.w} transparent
          opacity={dimAll ? 0.25 : 0.9} />
      ))}
      {view === "electrical" && <Flow cat={cat} at={at} />}
    </>
  );
}

/** Current flow along the supply path: dots moving J001 -> R001 -> U001. */
function Flow({ cat, at }: { cat: Catalogue; at: (x: number, y: number) => [number, number] }) {
  const path = useMemo(() => {
    const byId: Record<string, BoardComponent> = {};
    cat.board.components.forEach((c) => (byId[c.component_id] = c));
    const seq = ["J001", "R001", "C001", "U001", "R002", "Q001"].map((id) => byId[id]).filter(Boolean);
    const pts: THREE.Vector3[] = [];
    for (let i = 1; i < seq.length; i++) {
      manhattan(at(seq[i - 1].position_mm[0], seq[i - 1].position_mm[1]),
        at(seq[i].position_mm[0], seq[i].position_mm[1])).forEach((p) => pts.push(new THREE.Vector3(p[0], 0.02, p[2])));
    }
    return new THREE.CatmullRomCurve3(pts, false, "catmullrom", 0.01);
  }, [cat, at]);
  const refs = useRef<THREE.Mesh[]>([]);
  const N = 14;
  useFrame(({ clock }) => {
    refs.current.forEach((m, i) => {
      if (!m) return;
      const u = ((clock.elapsedTime * 0.08 + i / N) % 1 + 1) % 1;
      m.position.copy(path.getPointAt(u));
    });
  });
  return (
    <>
      {Array.from({ length: N }, (_, i) => (
        <mesh key={i} ref={(m) => { if (m) refs.current[i] = m; }} raycast={() => null}>
          <sphereGeometry args={[0.035, 10, 10]} />
          <meshBasicMaterial color="#FFE08A" />
        </mesh>
      ))}
    </>
  );
}

// ---------------------------------------------------------------- thermal
/** Heat map from IR readings: each part spreads its rise over the chamber. */
function HeatMap({
  cat, temps, baseline, full,
}: {
  cat: Catalogue; temps: Record<string, number | null>;
  baseline: Record<string, number | null> | number; full: number;
}) {
  const [W, H] = cat.board.size_mm;
  const tex = useMemo(() => {
    const cw = 280;
    const ch = Math.round((cw * H) / W);
    const canvas = document.createElement("canvas");
    canvas.width = cw;
    canvas.height = ch;
    const t = new THREE.CanvasTexture(canvas);
    t.colorSpace = THREE.SRGBColorSpace;
    return t;
  }, [W, H]);

  useEffect(() => {
    const canvas = tex.image as HTMLCanvasElement;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    const img = ctx.createImageData(canvas.width, canvas.height);
    const srcs = cat.board.components
      .filter((c) => temps[c.component_id] != null)
      .map((c) => ({
        x: c.position_mm[0], y: c.position_mm[1],
        dt: Math.max(0, (temps[c.component_id] as number) - (typeof baseline === "number"
          ? baseline : baseline[c.component_id] ?? (temps[c.component_id] as number))),
        s: Math.max(2.5, Math.max(c.size_mm[0], c.size_mm[1]) * 0.6 + 2),
      }));
    // A stated visual range, not a limit.
    const FULL = full;
    const stops = [
      [0.0, [18, 58, 54, 0]],
      [0.15, [59, 120, 166, 150]],
      [0.45, [242, 193, 78, 200]],
      [0.75, [242, 131, 76, 220]],
      [1.0, [255, 80, 70, 235]],
    ] as const;
    const col = (u: number) => {
      for (let i = 1; i < stops.length; i++) {
        if (u <= stops[i][0]) {
          const f = (u - stops[i - 1][0]) / (stops[i][0] - stops[i - 1][0]);
          return stops[i - 1][1].map((a, k) => a + f * (stops[i][1][k] - a));
        }
      }
      return stops[stops.length - 1][1] as unknown as number[];
    };
    for (let py = 0; py < canvas.height; py++) {
      const ymm = H - (py / canvas.height) * H;
      for (let px = 0; px < canvas.width; px++) {
        const xmm = (px / canvas.width) * W;
        let dt = 0;
        for (const s of srcs) {
          const d2 = (xmm - s.x) ** 2 + (ymm - s.y) ** 2;
          dt += s.dt * Math.exp(-d2 / (2 * s.s * s.s));
        }
        const c = col(Math.min(1, dt / FULL));
        const o = (py * canvas.width + px) * 4;
        img.data[o] = c[0];
        img.data[o + 1] = c[1];
        img.data[o + 2] = c[2];
        img.data[o + 3] = c[3];
      }
    }
    ctx.putImageData(img, 0, 0);
    tex.needsUpdate = true;
  }, [cat, temps, baseline, full, tex, W, H]);

  return (
    <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.03, 0]} raycast={() => null}>
      <planeGeometry args={[W * S, H * S]} />
      <meshBasicMaterial map={tex} transparent depthWrite={false} />
    </mesh>
  );
}

// ------------------------------------------------------------ overlays
function Ring({ at, c, color, r, pulse }: {
  at: (x: number, y: number) => [number, number]; c: BoardComponent; color: string; r: number; pulse?: boolean;
}) {
  const ref = useRef<THREE.Mesh>(null!);
  const [x, z] = at(c.position_mm[0], c.position_mm[1]);
  useFrame(({ clock }) => {
    if (pulse && ref.current) {
      const s = 1 + 0.08 * Math.sin(clock.elapsedTime * 3);
      ref.current.scale.set(s, s, s);
    }
  });
  return (
    <mesh ref={ref} rotation={[-Math.PI / 2, 0, 0]} position={[x, 0.015, z]} raycast={() => null}>
      <ringGeometry args={[r * 0.86, r, 48]} />
      <meshBasicMaterial color={color} transparent opacity={0.9} side={THREE.DoubleSide} />
    </mesh>
  );
}

function Region({ at, c }: { at: (x: number, y: number) => [number, number]; c: BoardComponent }) {
  const [x, z] = at(c.position_mm[0], c.position_mm[1]);
  return (
    <mesh rotation={[-Math.PI / 2, 0, 0]} position={[x, 0.009, z]} raycast={() => null}>
      <circleGeometry args={[12 * S, 48]} />
      <meshBasicMaterial color="#FF6B5E" transparent opacity={0.12} depthWrite={false} />
    </mesh>
  );
}

function Cage({ at, c }: { at: (x: number, y: number) => [number, number]; c: BoardComponent }) {
  const [x, z] = at(c.position_mm[0], c.position_mm[1]);
  const w = c.size_mm[0] * S + 0.12;
  const d = c.size_mm[1] * S + 0.12;
  const h = Math.max(c.size_mm[2] * S, 0.05) + 0.1;
  return (
    <mesh position={[x, h / 2, z]} raycast={() => null}>
      <boxGeometry args={[w, h, d]} />
      <meshBasicMaterial color={SELECT} wireframe transparent opacity={0.95} />
    </mesh>
  );
}

function Label({ at, c, status, strong }: {
  at: (x: number, y: number) => [number, number]; c: BoardComponent; status: PartStatus; strong: boolean;
}) {
  const [x, z] = at(c.position_mm[0], c.position_mm[1]);
  const h = Math.max(c.size_mm[2] * S, 0.04);
  return (
    <Html position={[x, h + 0.22, z]} center distanceFactor={6} zIndexRange={[20, 0]}>
      <div
        className="pointer-events-none whitespace-nowrap rounded px-1 py-px text-[9px] font-bold tracking-wide"
        style={{
          background: strong ? STATUS_COLOR[status] : "rgba(7,24,22,0.78)",
          color: strong ? "#1A0705" : STATUS_COLOR[status],
          border: `1px solid ${STATUS_COLOR[status]}`,
        }}
      >
        {GLYPH[status]} {c.component_id}
      </div>
    </Html>
  );
}

// -------------------------------------------------------------- scene
export function BoardScene(props: BoardSceneProps) {
  const { catalogue: cat, view, temps, baseline, heatFullC, status, selected, suspect, neighbours, ambiguity, railV, onPick } = props;
  const { W, H, at, byId } = useLayout(cat);
  const faultView = view === "fault";
  const focus = new Set([suspect, ...neighbours, ...ambiguity].filter(Boolean) as string[]);

  return (
    <Canvas
      dpr={[1, 2]}
      gl={{ antialias: true }}
      camera={{ position: [0, 6.6, 6.2], fov: 38, near: 0.05, far: 100 }}
      onPointerMissed={() => onPick(null)}
    >
      <color attach="background" args={["#0B2D2A"]} />
      <ambientLight intensity={0.6} />
      <directionalLight position={[4, 8, 5]} intensity={1.15} />
      <directionalLight position={[-6, 4, -4]} intensity={0.35} color="#9FD6CE" />

      {/* the PCB: FR-4 core under green solder mask */}
      <mesh position={[0, -0.08, 0]} raycast={() => null}>
        <boxGeometry args={[W * S, 0.16, H * S]} />
        <meshStandardMaterial color="#1D5A3A" roughness={0.7} metalness={0.05} />
      </mesh>
      <mesh position={[0, -0.161, 0]} raycast={() => null}>
        <boxGeometry args={[W * S + 0.02, 0.002, H * S + 0.02]} />
        <meshStandardMaterial color="#C9B98F" />
      </mesh>

      <Traces cat={cat} at={at} view={view} railV={railV} dimAll={faultView} />
      {view === "thermal" && <HeatMap cat={cat} temps={temps} baseline={baseline} full={heatFullC} />}

      {cat.board.components.map((c) => (
        <Part
          key={c.component_id}
          c={c}
          at={at}
          status={status[c.component_id] ?? "OK"}
          dim={faultView && !focus.has(c.component_id)}
          glow={faultView && c.component_id === suspect}
          onPick={onPick}
        />
      ))}

      {faultView && suspect && byId[suspect] && (
        <>
          <Region at={at} c={byId[suspect]} />
          <Ring at={at} c={byId[suspect]} color="#FF6B5E" r={0.62} pulse />
        </>
      )}
      {faultView && neighbours.filter((n) => byId[n] && n !== suspect).map((n) => (
        <Ring key={n} at={at} c={byId[n]} color="#F2C14E" r={0.4} />
      ))}
      {faultView && ambiguity.filter((n) => byId[n] && n !== suspect).map((n) => (
        <Ring key={`a${n}`} at={at} c={byId[n]} color="#F2A365" r={0.5} pulse />
      ))}
      {selected && byId[selected] && <Cage at={at} c={byId[selected]} />}

      {cat.board.components
        .filter((c) => c.type !== "test_point" || selected === c.component_id)
        .map((c) => (
          <Label key={c.component_id} at={at} c={c} status={status[c.component_id] ?? "OK"}
            strong={c.component_id === suspect || c.component_id === selected} />
        ))}

      <OrbitControls makeDefault target={[0, 0, 0]} minDistance={2.5} maxDistance={16}
        maxPolarAngle={Math.PI / 2.1} />
    </Canvas>
  );
}
