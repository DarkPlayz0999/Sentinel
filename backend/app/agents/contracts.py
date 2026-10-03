"""Typed contracts between agents.

Every agent returns one of these reports; the LangGraph state carries only
these (small, JSON-safe) plus accumulated findings. DataFrames never enter the
state - they are recomputed from `dataset_id` if a checkpoint is resumed in a
new process, which is safe because every step is deterministic (seed 42,
checksum-verified model artifact).

No field here is produced by a language model. Phase 1 has no LLM at all; when
one arrives (Report agent) it may only word findings these contracts already
hold - it never computes a number, sets a verdict, or releases a component.
"""

from __future__ import annotations

import operator
from typing import Annotated, Literal, TypedDict

from pydantic import BaseModel, ConfigDict, Field

AgentName = Literal["data_quality", "anomaly", "forecast", "combine", "quarantine",
                    # investigation team (backend/app/agents/investigation.py)
                    "diagnostic", "root_cause", "qa_safety", "report", "explainer"]
Severity = Literal["info", "warning", "error", "critical"]
DataClass = Literal["simulated", "experimental", "unknown"]


class Finding(BaseModel):
    agent: AgentName
    severity: Severity
    code: str                      # machine-readable, e.g. DQ-HASH-MISMATCH
    message: str                   # inspector-facing English, numbers from code only
    data: dict = Field(default_factory=dict)


class DataQualityReport(BaseModel):
    valid: bool
    rows: int
    lots: int
    read_points: list[int]
    module_b_available: bool
    hash_verified: bool
    data_class: DataClass
    source: str
    error_codes: list[str] = Field(default_factory=list)
    warning_codes: list[str] = Field(default_factory=list)


class AnomalyReport(BaseModel):
    """Module A, as computed by src/module_a.py - counts only, no new statistics."""
    parts: int
    static_breaches: int
    l2_over_6_sigma: int           # |robust z| >= 6, the DPAT convention
    l3_over_threshold: int | None  # pooled evidence > chi2(0.999); None if no drift reads
    l3_threshold: float


class ForecastReport(BaseModel):
    """Module B, as computed by src/pipeline.run_module_b."""
    model_config = ConfigDict(protected_namespaces=())   # field `model_artifact_id`
    available: bool
    model_artifact_id: str | None
    out_of_fold: bool
    reject_at_24h: int
    exponents: dict[str, float] = Field(default_factory=dict)
    population_k: float | None = None


class CombineReport(BaseModel):
    run_id: str
    verdicts: dict[str, int]
    lots_over_pda: list[str]
    human_review_required: bool    # always true if anything was flagged


class Hypothesis(BaseModel):
    """One root-cause hypothesis. `evidence_score` is a similarity x 100."""
    rank: int
    component_id: str
    fault_type: str
    mechanism: str
    evidence_score: float
    implied_severity: float
    signature: list[str] = Field(default_factory=list)


class DiagnosticReport(BaseModel):
    boards: dict[str, dict]                 # serial -> src.twin.diagnose output
    focus_serial: str
    suspect_component: str | None
    ambiguity_group: list[str] = Field(default_factory=list)


class RootCauseReport(BaseModel):
    focus_serial: str
    hypotheses: list[Hypothesis]
    score_kind: str = "evidence score (cosine similarity x 100), not a probability"


class QACheck(BaseModel):
    check: str
    status: Literal["PASS", "WARN", "FAIL", "INFO"]
    detail: str


class QASafetyReport(BaseModel):
    status: Literal["PASS", "REVIEW"]
    checks: list[QACheck]


class InvestigationReport(BaseModel):
    simulation_id: str
    focus_serial: str
    verdict: str
    risk_score: float
    primary_reason: dict | None
    suspect_component: str | None
    suspect_fault_type: str | None
    evidence_score: float | None
    ambiguity_group: list[str]
    discriminating_tests: list[dict]
    qa_status: str
    recommended_actions: list[str]
    summary: str
    disclaimers: list[str]


class InvestigationState(TypedDict, total=False):
    workflow_id: str
    simulation_id: str
    dataset_id: str
    run_id: str
    actor: str | None
    serials: list[str]              # flagged boards, highest risk first
    diagnostic: dict
    root_cause: dict
    qa_safety: dict
    report: dict
    explanation: dict               # plain-language wording of the report (AI or built-in)
    findings: Annotated[list[dict], operator.add]


class WorkflowState(TypedDict, total=False):
    workflow_id: str
    dataset_id: str
    actor: str | None
    data_quality: dict             # DataQualityReport
    anomaly: dict                  # AnomalyReport
    forecast: dict                 # ForecastReport
    result: dict                   # CombineReport
    # Parallel agents both append; the reducer concatenates instead of clobbering.
    findings: Annotated[list[dict], operator.add]
