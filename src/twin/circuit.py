"""Netlists, a batched MNA solver, and the ngspice runner.

One netlist, two solvers
------------------------
Each ATE test is written ONCE as a SPICE-syntax netlist template (resistors,
independent voltage and current sources, `.op`). The same template is solved
two ways:

  * `Netlist.solve()` - modified nodal analysis in numpy, batched across every
    board of a lot at once. This is what the lot and the experiment campaigns
    run on. Values it produces are labelled PHYSICS_MODEL (solver "mna"):
    they are a real Kirchhoff solution of the circuit, not SPICE.
  * `run_ngspice()` - renders the template to a .cir file for one board and
    runs a local ngspice in batch mode. Values are labelled SPICE. Used to
    cross-check the inspected board when ngspice is installed; never inside a
    thousand-run sweep (a 200-board lot at four read points is thousands of
    process launches).

Both follow SPICE sign conventions, so their answers are directly comparable:
`I(Vx)` is the current flowing INTO the source's + terminal, and a current
source `I n+ n- val` pulls `val` out of n+ and pushes it into n-.

If ngspice fails it raises `SimulationFailed`, carrying stderr, the exit code
and the netlist. Nothing here ever substitutes a fabricated value for a failed
solve.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

__all__ = ["Element", "Netlist", "SimulationFailed", "find_ngspice",
           "run_ngspice", "parse_ngspice_output", "PROVENANCE"]

# Where a value came from. Every measurement record carries one.
PROVENANCE = ("SPICE", "PHYSICS_MODEL", "SYNTHETIC", "DATASET")


class SimulationFailed(RuntimeError):
    """A circuit solve that did not produce a trustworthy answer."""

    def __init__(self, message: str, *, netlist: str = "", stderr: str = "",
                 exit_code: int | None = None, simulation_id: str | None = None):
        super().__init__(message)
        self.netlist = netlist
        self.stderr = stderr
        self.exit_code = exit_code
        self.simulation_id = simulation_id

    def as_dict(self) -> dict:
        return {"status": "SIMULATION_FAILED", "message": str(self),
                "exit_code": self.exit_code, "stderr": self.stderr[-4000:],
                "netlist": self.netlist, "simulation_id": self.simulation_id}


@dataclass(frozen=True)
class Element:
    name: str          # SPICE name; the first letter sets the kind
    n1: str
    n2: str
    value: str         # key into the values mapping

    @property
    def kind(self) -> str:
        return self.name[0].upper()


@dataclass
class Netlist:
    title: str
    elements: list[Element] = field(default_factory=list)

    # ------------------------------------------------------------ build
    def add(self, name: str, n1: str, n2: str, value: str) -> "Netlist":
        if name[0].upper() not in "RVI":
            raise ValueError(f"only R, V and I elements are supported, got {name}")
        self.elements.append(Element(name, n1.lower(), n2.lower(), value))
        return self

    @property
    def nodes(self) -> list[str]:
        seen: list[str] = []
        for e in self.elements:
            for n in (e.n1, e.n2):
                if n != "0" and n not in seen:
                    seen.append(n)
        return seen

    @property
    def vsources(self) -> list[str]:
        return [e.name.lower() for e in self.elements if e.kind == "V"]

    # ------------------------------------------------------------ solve
    def solve(self, values: dict[str, np.ndarray | float]) -> dict[str, np.ndarray]:
        """Batched DC operating point by modified nodal analysis.

        ``values`` maps each element's value key to a scalar or an (N,) array.
        Returns node voltages under their node names and source currents under
        ``i(<vname>)``, each an (N,) array. Raises SimulationFailed on a
        singular system (a floating node) rather than returning garbage.
        """
        nodes, vs = self.nodes, self.vsources
        idx = {n: i for i, n in enumerate(nodes)}
        n, m = len(nodes), len(vs)
        size = n + m
        arrays = {k: np.atleast_1d(np.asarray(v, dtype=float)) for k, v in values.items()}
        batch = max((a.size for a in arrays.values()), default=1)

        def val(key: str) -> np.ndarray:
            if key not in arrays:
                raise KeyError(f"{self.title}: no value supplied for {key!r}")
            a = arrays[key]
            return np.broadcast_to(a, (batch,)) if a.size == 1 else a

        A = np.zeros((batch, size, size))
        z = np.zeros((batch, size))
        k = 0
        for e in self.elements:
            a = idx.get(e.n1)
            b = idx.get(e.n2)
            v = val(e.value)
            if e.kind == "R":
                if np.any(v <= 0) or not np.all(np.isfinite(v)):
                    raise SimulationFailed(
                        f"{self.title}: resistor {e.name} has a non-positive or "
                        "non-finite value", netlist=self.render_first(arrays))
                g = 1.0 / v
                if a is not None:
                    A[:, a, a] += g
                if b is not None:
                    A[:, b, b] += g
                if a is not None and b is not None:
                    A[:, a, b] -= g
                    A[:, b, a] -= g
            elif e.kind == "V":
                row = n + k
                if a is not None:
                    A[:, a, row] += 1.0
                    A[:, row, a] += 1.0
                if b is not None:
                    A[:, b, row] -= 1.0
                    A[:, row, b] -= 1.0
                z[:, row] = v
                k += 1
            else:  # I: out of n1, into n2
                if a is not None:
                    z[:, a] -= v
                if b is not None:
                    z[:, b] += v
        try:
            x = np.linalg.solve(A, z[..., None])[..., 0]
        except np.linalg.LinAlgError as exc:
            raise SimulationFailed(f"{self.title}: singular circuit matrix ({exc})",
                                   netlist=self.render_first(arrays)) from exc
        out = {name: x[:, i] for i, name in enumerate(nodes)}
        out.update({f"i({name})": x[:, n + j] for j, name in enumerate(vs)})
        return out

    # ----------------------------------------------------------- render
    def render(self, values: dict[str, float], *, board: str = "") -> str:
        """SPICE text for one board. `.op`, then print every vector."""
        lines = [f"* {self.title}" + (f" - board {board}" if board else "")]
        for e in self.elements:
            v = float(values[e.value])
            if e.kind == "R":
                lines.append(f"{e.name} {e.n1} {e.n2} {v:.9g}")
            else:
                lines.append(f"{e.name} {e.n1} {e.n2} DC {v:.9g}")
        lines += [".control", "op", "print all", "quit", ".endc", ".end", ""]
        return "\n".join(lines)

    def render_first(self, arrays: dict[str, np.ndarray]) -> str:
        """Render the first board of a batch, for a failure record."""
        try:
            return self.render({k: float(np.ravel(v)[0]) for k, v in arrays.items()})
        except Exception:  # noqa: BLE001 - diagnostic only, never masks the real error
            return f"* {self.title} (could not render)"


# ------------------------------------------------------------------ ngspice
def find_ngspice() -> str | None:
    """The ngspice executable: $SENTINEL_NGSPICE, else whatever is on PATH."""
    env = os.environ.get("SENTINEL_NGSPICE")
    if env:
        return env if Path(env).exists() else None
    for name in ("ngspice", "ngspice_con", "ngspice.exe", "ngspice_con.exe"):
        hit = shutil.which(name)
        if hit:
            return hit
    return None


_LINE = re.compile(r"^\s*([A-Za-z0-9_#().:+\-]+)\s*=\s*([-+0-9.eE]+)\s*$")


def parse_ngspice_output(text: str) -> dict[str, float]:
    """Parse `print all` after `.op` into {name: value}.

    ngspice prints node voltages as ``node = value`` (some builds as
    ``v(node) = value``) and source currents as ``vname#branch = value``.
    Names are normalised to the MNA solver's keys: ``node`` and ``i(vname)``.
    """
    out: dict[str, float] = {}
    for line in text.splitlines():
        m = _LINE.match(line)
        if not m:
            continue
        name, raw = m.group(1).lower(), m.group(2)
        try:
            val = float(raw)
        except ValueError:
            continue
        if name.endswith("#branch"):
            out[f"i({name[:-7]})"] = val
        elif name.startswith("v(") and name.endswith(")"):
            out[name[2:-1]] = val
        else:
            out[name] = val
    return out


def run_ngspice(netlist: Netlist, values: dict[str, float], *, board: str = "",
                timeout_s: float = 20.0, retries: int = 1,
                simulation_id: str | None = None,
                executable: str | list[str] | None = None) -> tuple[dict[str, float], str]:
    """Run one netlist through a local ngspice. Returns (solution, netlist text).

    ``executable`` may be a command prefix list (tests pass an interpreter
    plus a script). Retries once on a timeout (a cold first launch on Windows
    can be slow). Any other failure - missing binary, non-zero exit,
    unparsable output, a node missing from the answer - raises
    SimulationFailed with the evidence.
    """
    text = netlist.render(values, board=board)
    exe = executable or find_ngspice()
    if not exe:
        raise SimulationFailed(
            "ngspice is not installed or not on PATH. Set SENTINEL_NGSPICE to "
            "the ngspice executable, or use the built-in MNA solver.",
            netlist=text, simulation_id=simulation_id)

    last: SimulationFailed | None = None
    for _attempt in range(retries + 1):
        tmp = Path(tempfile.mkdtemp(prefix="sentinel_spice_"))
        try:
            cir = tmp / "circuit.cir"
            cir.write_text(text, encoding="utf-8")
            cmd = [*exe] if isinstance(exe, (list, tuple)) else [exe]
            try:
                proc = subprocess.run([*cmd, "-b", str(cir)], capture_output=True,
                                      text=True, timeout=timeout_s, cwd=tmp)
            except subprocess.TimeoutExpired as exc:
                last = SimulationFailed(
                    f"ngspice timed out after {timeout_s:.0f} s", netlist=text,
                    stderr=str(exc.stderr or ""), exit_code=None,
                    simulation_id=simulation_id)
                continue
            except OSError as exc:
                raise SimulationFailed(f"ngspice could not be started: {exc}",
                                       netlist=text, simulation_id=simulation_id) from exc
            if proc.returncode != 0:
                raise SimulationFailed(
                    f"ngspice exited with code {proc.returncode}", netlist=text,
                    stderr=proc.stderr or proc.stdout, exit_code=proc.returncode,
                    simulation_id=simulation_id)
            sol = parse_ngspice_output(proc.stdout)
            wanted = netlist.nodes + [f"i({v})" for v in netlist.vsources]
            missing = [w for w in wanted if w not in sol]
            if missing:
                raise SimulationFailed(
                    f"ngspice output is missing {', '.join(missing)}", netlist=text,
                    stderr=(proc.stderr or "") + "\n--- stdout ---\n" + proc.stdout,
                    exit_code=proc.returncode, simulation_id=simulation_id)
            return {w: sol[w] for w in wanted}, text
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    assert last is not None
    raise last
