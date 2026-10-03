"use client";

import { Canvas, ThreeEvent, useThree } from "@react-three/fiber";
import { Html, OrbitControls } from "@react-three/drei";
import { useEffect, useLayoutEffect, useMemo, useRef } from "react";
import * as THREE from "three";
import { DeviationState, LotState, Socket, TRAY_COLS, trayRows } from "@/lib/twin";
import { C } from "@/lib/theme";

/* THE OVEN, IN THREE DIMENSIONS.
 *
 * One tray of 350 parts - a whole lot, because a lot is the population every
 * statistic in this system is computed over. A single board carrying one
 * capacitor has no siblings and no robust median, so there would be nothing
 * for the screening maths to work on.
 *
 * Two reference surfaces float over the tray:
 *   the RED ceiling is the datasheet limit. Nothing in this lot ever touches it.
 *   the BLUE slab is the batch itself, 5th to 95th percentile, recomputed at
 *   every instant of the soak.
 * A part that climbs out of the blue slab while staying under the red ceiling
 * is a latent defect: it passes every test it will ever be given, and it is
 * already behaving unlike its siblings. That is the whole problem, in one
 * picture.
 *
 * Column height is the measured value scaled by the datasheet limit, so the
 * ceiling sits at exactly 1.0 and heights are directly comparable. Colour
 * carries the deviation band, and the inspector panel repeats that band as
 * words and a glyph, so status never rests on colour alone. */

const H_USL = 4.2; // world height of the datasheet limit
const PITCH = 1.0;
const CHIP = 0.56;
const COL = 0.3;

const STATE_COLOR: Record<DeviationState, string> = {
  nominal: "#8EBBDD", // steel blue: the batch
  elevated: "#F2A365", // amber: leaving the batch
  far: "#FF7A6B", // red: far outside
};

const tmp = new THREE.Object3D();
const tmpColor = new THREE.Color();

/** Part packages in their sockets: fixed geometry, one instance each. */
function Packages({ sockets, onPick }: { sockets: Socket[]; onPick: (i: number) => void }) {
  const ref = useRef<THREE.InstancedMesh>(null!);

  useLayoutEffect(() => {
    sockets.forEach((s, i) => {
      tmp.position.set(s.px, 0.09, s.pz);
      tmp.rotation.set(0, 0, 0);
      tmp.scale.set(1, 1, 1);
      tmp.updateMatrix();
      ref.current.setMatrixAt(i, tmp.matrix);
    });
    ref.current.instanceMatrix.needsUpdate = true;
  }, [sockets]);

  return (
    <instancedMesh
      ref={ref}
      args={[undefined, undefined, sockets.length]}
      onPointerDown={(e: ThreeEvent<PointerEvent>) => {
        e.stopPropagation();
        if (e.instanceId != null) onPick(e.instanceId);
      }}
    >
      <boxGeometry args={[CHIP, 0.18, CHIP]} />
      <meshStandardMaterial color="#1A2B2E" roughness={0.65} metalness={0.25} />
    </instancedMesh>
  );
}

/** The measured value, as a column rising out of each package. */
function Columns({ sockets, lot, usl }: { sockets: Socket[]; lot: LotState; usl: number }) {
  const ref = useRef<THREE.InstancedMesh>(null!);

  useEffect(() => {
    const mesh = ref.current;
    sockets.forEach((s, i) => {
      const v = lot.values[i];
      const h = v == null ? 0.001 : Math.max(0.001, (v / usl) * H_USL);
      tmp.position.set(s.px, 0.18 + h / 2, s.pz);
      tmp.rotation.set(0, 0, 0);
      tmp.scale.set(1, h, 1);
      tmp.updateMatrix();
      mesh.setMatrixAt(i, tmp.matrix);
      mesh.setColorAt(i, tmpColor.set(STATE_COLOR[lot.state[i]]));
    });
    mesh.instanceMatrix.needsUpdate = true;
    if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true;
  }, [sockets, lot, usl]);

  return (
    <instancedMesh ref={ref} args={[undefined, undefined, sockets.length]} raycast={() => null}>
      <boxGeometry args={[COL, 1, COL]} />
      <meshStandardMaterial transparent opacity={0.78} roughness={0.4} />
    </instancedMesh>
  );
}

/**
 * The datasheet limit.
 *
 * A translucent sheet alone all but disappears when the camera is low, so the
 * limit also carries a bright outline and a caption. This is the line every
 * conventional test is drawn against, and the point of the whole screen is
 * that the interesting part never reaches it.
 */
function Ceiling({ y, w, d, label }: { y: number; w: number; d: number; label: string }) {
  const edges = useMemo(() => new THREE.EdgesGeometry(new THREE.PlaneGeometry(w, d)), [w, d]);
  return (
    <group position={[0, y, 0]} rotation={[-Math.PI / 2, 0, 0]}>
      <mesh raycast={() => null}>
        <planeGeometry args={[w, d]} />
        <meshBasicMaterial
          color={C.reject}
          transparent
          opacity={0.1}
          side={THREE.DoubleSide}
          depthWrite={false}
        />
      </mesh>
      <lineSegments geometry={edges} raycast={() => null}>
        <lineBasicMaterial color="#FF6B5E" transparent opacity={0.95} />
      </lineSegments>
      {/* Front-right corner. A selected part is captioned above its own
          column, and near the limit the two collide if this sits mid-edge. */}
      <Html position={[w * 0.2, d / 2 + 0.6, 0]} center distanceFactor={26} zIndexRange={[5, 0]}>
        <div className="wide whitespace-nowrap rounded bg-[#FF6B5E] px-2 py-0.5 text-[10px] font-black tracking-wide text-[#2A0703]">
          DATASHEET LIMIT {label}
        </div>
      </Html>
    </group>
  );
}

/**
 * The batch envelope: a slab from the lot 5th to its 95th percentile.
 *
 * This is the reference SENTINEL actually judges against, and it moves as the
 * lot ages. A part that stays inside it is behaving like its siblings no
 * matter what the datasheet says.
 */
function BatchSlab({ lot, usl, w, d }: { lot: LotState; usl: number; w: number; d: number }) {
  const lo = (lot.p05 / usl) * H_USL;
  const hi = (lot.p95 / usl) * H_USL;
  const h = Math.max(0.02, hi - lo);
  const y = 0.18 + lo + h / 2;
  return (
    <group>
      <mesh position={[0, y, 0]} raycast={() => null}>
        <boxGeometry args={[w, h, d]} />
        <meshBasicMaterial color={C.cobalt} transparent opacity={0.15} depthWrite={false} />
      </mesh>
      <Html position={[-w / 2 - 0.4, y, d / 2]} center distanceFactor={26} zIndexRange={[5, 0]}>
        <div className="wide whitespace-nowrap rounded bg-[#3B78A6] px-2 py-0.5 text-[10px] font-black tracking-wide text-white">
          THE BATCH
        </div>
      </Html>
    </group>
  );
}

/** Cyan cage around the part under inspection, with its identity floating above. */
function Selection({ socket, value, usl }: { socket: Socket; value: number | null; usl: number }) {
  const h = value == null ? 0.2 : Math.max(0.2, (value / usl) * H_USL);
  return (
    <group position={[socket.px, 0, socket.pz]}>
      <mesh position={[0, 0.18 + h / 2, 0]} raycast={() => null}>
        <boxGeometry args={[0.78, h, 0.78]} />
        <meshBasicMaterial color="#5BD7E0" wireframe transparent opacity={0.9} />
      </mesh>
      <Html position={[0, 0.34 + h, 0]} center distanceFactor={22} zIndexRange={[10, 0]}>
        <div className="wide whitespace-nowrap rounded bg-[#5BD7E0] px-2 py-1 text-[11px] font-black tracking-wide text-[#062225]">
          {socket.part.s}
        </div>
      </Html>
    </group>
  );
}

function Rig({ w, d }: { w: number; d: number }) {
  const { camera } = useThree();
  useEffect(() => {
    camera.position.set(w * 0.46, H_USL * 1.55, d * 1.62);
    camera.lookAt(0, H_USL * 0.5, 0);
  }, [camera, w, d]);
  return null;
}

export interface SceneProps {
  sockets: Socket[];
  lot: LotState;
  usl: number;
  selected: number | null;
  onPick: (i: number) => void;
  showCeiling: boolean;
  showBatch: boolean;
  /** Datasheet limit with its unit, captioned on the ceiling. */
  uslLabel: string;
}

export function TrayScene({
  sockets,
  lot,
  usl,
  selected,
  onPick,
  showCeiling,
  showBatch,
  uslLabel,
}: SceneProps) {
  const rows = trayRows(sockets.length);
  const w = TRAY_COLS * PITCH + 1.2;
  const d = rows * PITCH + 1.2;

  return (
    <Canvas
      dpr={[1, 2]}
      gl={{ antialias: true }}
      camera={{ fov: 38, near: 0.1, far: 400 }}
      onPointerMissed={() => onPick(-1)}
    >
      <color attach="background" args={[C.oven]} />
      <fog attach="fog" args={[C.oven, 34, 86]} />
      <Rig w={w} d={d} />

      <ambientLight intensity={0.55} />
      <directionalLight position={[8, 16, 10]} intensity={1.1} />
      <directionalLight position={[-10, 6, -8]} intensity={0.35} color="#9FD6CE" />

      {/* the tray itself */}
      <mesh position={[0, -0.06, 0]} raycast={() => null}>
        <boxGeometry args={[w, 0.12, d]} />
        <meshStandardMaterial color="#123A36" roughness={0.85} metalness={0.15} />
      </mesh>
      <gridHelper
        args={[Math.max(w, d), Math.round(Math.max(w, d) * 2), "#1B4A45", "#16403C"]}
        position={[0, 0.01, 0]}
      />

      <Packages sockets={sockets} onPick={onPick} />
      <Columns sockets={sockets} lot={lot} usl={usl} />

      {showBatch && <BatchSlab lot={lot} usl={usl} w={w} d={d} />}
      {showCeiling && <Ceiling y={0.18 + H_USL} w={w} d={d} label={uslLabel} />}

      {selected != null && selected >= 0 && sockets[selected] && (
        <Selection socket={sockets[selected]} value={lot.values[selected]} usl={usl} />
      )}

      <OrbitControls
        enablePan
        target={[0, H_USL * 0.5, 0]}
        minDistance={8}
        maxDistance={70}
        maxPolarAngle={Math.PI / 2.12}
        makeDefault
      />
    </Canvas>
  );
}
