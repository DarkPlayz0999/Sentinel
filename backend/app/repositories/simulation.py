"""Storage for the digital twin: runs, components, measurements, faults,
ground truth, events, predictions, replacements and experiments.

Ground truth access is deliberately narrow. `GroundTruthRepository` is its own
class, and nothing on the screening or investigation path constructs one: the
service opens it only in reveal/benchmark, after a prediction exists. A test
monkeypatches it to raise during screening and investigation to prove that.
"""

from __future__ import annotations

from typing import Any, Iterable

from backend.app.models.database_models import connect, dumps, loads
from backend.app.repositories.repositories import _Repo, new_id, utc_now

__all__ = ["SimulationRepository", "GroundTruthRepository", "ExperimentRepository"]


class SimulationRepository(_Repo):
    _RUN_JSON = ("config", "options", "investigation", "error")

    # ----------------------------------------------------------- runs
    def create(self, *, mode: str, board_id: str, lot_id: str, boards: int,
               seed: int, config: dict, options: dict, software_version: str,
               model_version: str, actor: str | None) -> str:
        sid = new_id("sim")
        now = utc_now()
        with connect(self.db_path) as c:
            c.execute(
                """INSERT INTO simulation_runs(simulation_id, created_at, updated_at,
                   status, mode, board_id, lot_id, boards, random_seed, config, options,
                   software_version, model_version, actor)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (sid, now, now, "CREATED", mode, board_id, lot_id, boards, seed,
                 dumps(config), dumps(options), software_version, model_version, actor))
        return sid

    def _hydrate(self, row: dict | None) -> dict | None:
        if row:
            for k in self._RUN_JSON:
                row[k] = loads(row[k], None)
        return row

    def get(self, sid: str) -> dict | None:
        return self._hydrate(self._one(
            "SELECT * FROM simulation_runs WHERE simulation_id=?", (sid,)))

    def list(self, limit: int = 50) -> list[dict]:
        return [self._hydrate(r) for r in self._all(
            "SELECT * FROM simulation_runs ORDER BY created_at DESC, rowid DESC LIMIT ?",
            (limit,))]

    def update(self, sid: str, **fields: Any) -> None:
        if not fields:
            return
        fields["updated_at"] = utc_now()
        vals = [dumps(v) if k in self._RUN_JSON else v for k, v in fields.items()]
        sets = ", ".join(f"{k}=?" for k in fields)
        self._exec(f"UPDATE simulation_runs SET {sets} WHERE simulation_id=?", (*vals, sid))

    def claim(self, sid: str, from_status: Iterable[str], to_status: str) -> bool:
        """Atomic status transition; False if another worker got there first."""
        frm = tuple(from_status)
        marks = ",".join("?" * len(frm))
        with connect(self.db_path) as c:
            cur = c.execute(
                f"UPDATE simulation_runs SET status=?, updated_at=? WHERE simulation_id=?"
                f" AND status IN ({marks})", (to_status, utc_now(), sid, *frm))
            return bool(cur.rowcount)

    # --------------------------------------------------------- faults
    def add_faults(self, sid: str, faults: list[dict], *, seed: int, version: str) -> None:
        now = utc_now()
        with connect(self.db_path) as c:
            c.executemany(
                """INSERT INTO simulation_faults(fault_id, simulation_id, board_serial,
                   board_index, component_id, fault_type, severity, start_h, growth_rate,
                   source, timestamp, software_version, random_seed)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                [(new_id("flt"), sid, f["serial"], f["board"], f["component_id"],
                  f["fault_type"], f["severity"], f["start_h"], f["growth_rate"],
                  f.get("source", "injected"), now, version, seed) for f in faults])

    def faults(self, sid: str) -> list[dict]:
        return self._all("SELECT * FROM simulation_faults WHERE simulation_id=?"
                         " ORDER BY timestamp, rowid", (sid,))

    # ----------------------------------------------- components/measurements
    def replace_components(self, sid: str, phase: str, rows: list[dict], *,
                           seed: int, version: str) -> None:
        now = utc_now()
        with connect(self.db_path) as c:
            c.execute("DELETE FROM simulation_components WHERE simulation_id=? AND phase=?",
                      (sid, phase))
            c.executemany(
                """INSERT INTO simulation_components(simulation_id, phase, board_serial,
                   component_id, component_model, kind, as_built, state, timestamp,
                   software_version, random_seed) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                [(sid, phase, r["serial"], r["component_id"], r["model"], r["kind"],
                  dumps(r["as_built"]), dumps(r["state"]), now, version, seed) for r in rows])

    def add_measurements(self, sid: str, phase: str, rows: list[dict], *,
                         seed: int, version: str) -> None:
        now = utc_now()
        with connect(self.db_path) as c:
            c.executemany(
                """INSERT INTO simulation_measurements(simulation_id, phase, board_serial,
                   component_id, time_h, parameter, value, unit, measurement_source,
                   solver, timestamp, software_version, random_seed)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                [(sid, phase, r["serial"], r.get("component_id"), r["time_h"],
                  r["parameter"], r["value"], r["unit"], r["measurement_source"],
                  r.get("solver"), now, version, seed) for r in rows])

    def measurements(self, sid: str, *, serial: str | None = None,
                     phase: str | None = None, limit: int = 5000) -> list[dict]:
        sql = "SELECT * FROM simulation_measurements WHERE simulation_id=?"
        args: list = [sid]
        if serial:
            sql += " AND board_serial=?"
            args.append(serial)
        if phase:
            sql += " AND phase=?"
            args.append(phase)
        sql += " ORDER BY phase, time_h, parameter LIMIT ?"
        args.append(limit)
        return self._all(sql, args)

    def component_state(self, sid: str, serial: str, phase: str = "burn-in-1") -> list[dict]:
        rows = self._all("SELECT * FROM simulation_components WHERE simulation_id=?"
                         " AND board_serial=? AND phase=?", (sid, serial, phase))
        for r in rows:
            r["as_built"] = loads(r["as_built"], {})
            r["state"] = loads(r["state"], {})
        return rows

    # ---------------------------------------------------------- events
    def event(self, sid: str, event_type: str, payload: dict | None = None, *,
              serial: str | None = None, component_id: str | None = None,
              seed: int | None = None, version: str = "") -> None:
        self._exec(
            """INSERT INTO simulation_events(simulation_id, timestamp, event_type,
               board_serial, component_id, payload, software_version, random_seed)
               VALUES(?,?,?,?,?,?,?,?)""",
            (sid, utc_now(), event_type, serial, component_id, dumps(payload or {}),
             version, seed))

    def events_after(self, sid: str, seq: int, limit: int = 500) -> list[dict]:
        rows = self._all("SELECT * FROM simulation_events WHERE simulation_id=? AND seq > ?"
                         " ORDER BY seq LIMIT ?", (sid, seq, limit))
        for r in rows:
            r["payload"] = loads(r["payload"], {})
        return rows

    # ----------------------------------------------------- predictions
    def add_predictions(self, sid: str, phase: str, read_h: int, rows: list[dict], *,
                        run_id: str | None, dataset_id: str | None, model_version: str,
                        seed: int, version: str) -> None:
        now = utc_now()
        with connect(self.db_path) as c:
            c.execute("DELETE FROM simulation_predictions WHERE simulation_id=? AND phase=?"
                      " AND read_h=?", (sid, phase, read_h))
            c.executemany(
                """INSERT INTO simulation_predictions(prediction_id, simulation_id, phase,
                   read_h, board_serial, component_id, run_id, dataset_id, risk_score,
                   verdict, reason_codes, model_version, timestamp, software_version,
                   random_seed) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                [(new_id("prd"), sid, phase, read_h, r["serial"], r.get("component_id"),
                  run_id, dataset_id, r["risk_score"], r["verdict"],
                  dumps(r.get("reason_codes") or []), model_version, now, version, seed)
                 for r in rows])

    def set_suspect(self, sid: str, phase: str, read_h: int, serial: str,
                    component_id: str | None) -> None:
        self._exec("UPDATE simulation_predictions SET component_id=? WHERE simulation_id=?"
                   " AND phase=? AND read_h=? AND board_serial=?",
                   (component_id, sid, phase, read_h, serial))

    def predictions(self, sid: str, *, phase: str | None = None,
                    read_h: int | None = None) -> list[dict]:
        sql = "SELECT * FROM simulation_predictions WHERE simulation_id=?"
        args: list = [sid]
        if phase:
            sql += " AND phase=?"
            args.append(phase)
        if read_h is not None:
            sql += " AND read_h=?"
            args.append(read_h)
        rows = self._all(sql + " ORDER BY read_h, risk_score DESC", args)
        for r in rows:
            r["reason_codes"] = loads(r["reason_codes"], [])
        return rows

    # ---------------------------------------------------- replacements
    def add_replacement(self, sid: str, row: dict, *, seed: int, version: str,
                        model_version: str, actor: str | None) -> str:
        rid = new_id("rpl")
        self._exec(
            """INSERT INTO simulation_replacements(replacement_id, simulation_id, phase,
               board_serial, component_id, candidate_id, reel, candidate, hidden, before,
               after, removed_bench, outcome, run_id, dataset_id, timestamp,
               model_version, software_version, random_seed, actor)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (rid, sid, row["phase"], row["serial"], row["component_id"],
             row["candidate_id"], row["reel"], dumps(row["candidate"]),
             dumps(row["hidden"]), dumps(row.get("before")), dumps(row.get("after")),
             dumps(row.get("removed_bench")), row.get("outcome"), row.get("run_id"),
             row.get("dataset_id"), utc_now(), model_version, version, seed, actor))
        return rid

    def replacements(self, sid: str | None = None) -> list[dict]:
        if sid:
            rows = self._all("SELECT * FROM simulation_replacements WHERE simulation_id=?"
                             " ORDER BY timestamp, rowid", (sid,))
        else:
            rows = self._all("SELECT * FROM simulation_replacements ORDER BY timestamp")
        for r in rows:
            for k in ("candidate", "hidden", "before", "after", "removed_bench"):
                r[k] = loads(r[k], None)
        return rows


class GroundTruthRepository(_Repo):
    """The only door to ground truth. See the module docstring."""

    def write(self, sid: str, phase: str, rows: list[dict], *, seed: int, version: str) -> None:
        now = utc_now()
        with connect(self.db_path) as c:
            c.execute("DELETE FROM simulation_ground_truth WHERE simulation_id=? AND phase=?",
                      (sid, phase))
            c.executemany(
                """INSERT INTO simulation_ground_truth(simulation_id, phase, board_serial,
                   component_id, is_faulty, truth, timestamp, software_version, random_seed)
                   VALUES(?,?,?,?,?,?,?,?,?)""",
                [(sid, phase, r["serial"], r.get("component_id"), int(r["is_faulty"]),
                  dumps(r["truth"]), now, version, seed) for r in rows])

    def read(self, sid: str, phase: str = "burn-in-1") -> list[dict]:
        rows = self._all("SELECT * FROM simulation_ground_truth WHERE simulation_id=?"
                         " AND phase=? ORDER BY board_serial", (sid, phase))
        for r in rows:
            r["truth"] = loads(r["truth"], {})
        return rows


class ExperimentRepository(_Repo):
    _JSON = ("spec", "progress", "summary")

    def create(self, *, kind: str, spec: dict, seed: int, runs: int, model_version: str,
               software_version: str, actor: str | None) -> str:
        eid = new_id("exp")
        self._exec(
            """INSERT INTO simulation_experiments(experiment_id, created_at, status, kind,
               spec, random_seed, runs, model_version, software_version, actor)
               VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (eid, utc_now(), "QUEUED", kind, dumps(spec), seed, runs, model_version,
             software_version, actor))
        return eid

    def update(self, eid: str, **fields: Any) -> None:
        vals = [dumps(v) if k in self._JSON else v for k, v in fields.items()]
        sets = ", ".join(f"{k}=?" for k in fields)
        self._exec(f"UPDATE simulation_experiments SET {sets} WHERE experiment_id=?",
                   (*vals, eid))

    def _hydrate(self, row):
        if row:
            for k in self._JSON:
                row[k] = loads(row[k], None)
        return row

    def get(self, eid: str) -> dict | None:
        return self._hydrate(self._one(
            "SELECT * FROM simulation_experiments WHERE experiment_id=?", (eid,)))

    def list(self, limit: int = 50) -> list[dict]:
        return [self._hydrate(r) for r in self._all(
            "SELECT * FROM simulation_experiments ORDER BY created_at DESC, rowid DESC"
            " LIMIT ?", (limit,))]
