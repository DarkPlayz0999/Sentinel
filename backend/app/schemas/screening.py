"""Dataset, job, run and component response models."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "DatasetUploadResponse", "DatasetSummary", "JobResponse",
    "RunSummary", "ComponentResult", "LotDisposition",
]


class DatasetUploadResponse(BaseModel):
    model_config = ConfigDict(json_schema_extra={"example": {
        "dataset_id": "ds_4f1c8a90b2e7d311",
        "status": "validated",
        "filename": "burnin_lot_L04.csv",
        "sha256": "d631da679b8a1db7a776c0b2…",
        "rows": 2100,
        "lots": 6,
        "read_points": [0, 24, 96, 168],
        "module_b_available": True,
        "deduplicated": False,
        "warnings": [{
            "field": "lot", "error_code": "INSUFFICIENT_LOT_POPULATION",
            "message": "1 lot(s) have fewer than 30 components.",
            "severity": "warning", "count": 1,
        }],
        "errors": [],
    }})

    dataset_id: str
    status: str = Field(..., description="'validated' — an upload that failed returns 422 instead.")
    filename: str
    sha256: str = Field(..., description="Content hash of the parsed frame; the reproducibility key.")
    rows: int
    lots: int
    read_points: list[int]
    module_b_available: bool
    deduplicated: bool = Field(
        False, description="True when identical content was already registered.")
    warnings: list[dict] = Field(default_factory=list)
    errors: list[dict] = Field(default_factory=list)


class DatasetSummary(BaseModel):
    dataset_id: str
    filename: str
    sha256: str
    uploaded_at: str
    row_count: int
    lot_count: int
    source: str = Field(..., examples=["upload"])
    adapter: str | None = Field(
        None, description="Set when an external dataset was normalised by an adapter.")


class JobResponse(BaseModel):
    model_config = ConfigDict(json_schema_extra={"example": {
        "job_id": "job_7c2e19ab44f0d853",
        "job_type": "SCREENING",
        "status": "RUNNING",
        "run_id": "run_a18b6f20c9d4e772",
        "dataset_id": "ds_4f1c8a90b2e7d311",
        "created_at": "2026-09-15T09:31:04+00:00",
        "started_at": "2026-09-15T09:31:04+00:00",
        "completed_at": None,
        "error": None,
    }})

    job_id: str
    job_type: str
    status: str = Field(..., description="QUEUED | RUNNING | COMPLETED | FAILED")
    run_id: str | None = None
    dataset_id: str | None = None
    created_at: str
    started_at: str | None = None
    completed_at: str | None = None
    error: str | None = None
    error_code: str | None = None


class LotDisposition(BaseModel):
    lot: str = Field(..., examples=["L04"])
    parts: int = Field(..., examples=[350])
    accept: int = Field(..., examples=[275])
    watch: int = Field(..., examples=[41])
    reject: int = Field(..., examples=[34])
    mean_risk: float = Field(..., examples=[31.4])
    reject_fraction: float = Field(..., examples=[0.0971])
    pda_limit: float = Field(..., examples=[0.05])
    status: str = Field(..., examples=["LOT REVIEW"])


class RunSummary(BaseModel):
    model_config = ConfigDict(protected_namespaces=(), json_schema_extra={"example": {
        "run_id": "run_a18b6f20c9d4e772",
        "dataset_id": "ds_4f1c8a90b2e7d311",
        "dataset_sha256": "d631da679b8a1db7a776c0b2…",
        "status": "COMPLETED",
        "row_count": 2100,
        "duration_s": 1.84,
        "summary": {"ACCEPT": 1785, "WATCH": 210, "REJECT": 105},
        "bands": {"watch": 36.3, "reject": 61.2},
        "model_version": "sentinel-0.3.0",
        "pipeline_version": "pipeline-1.1.0",
        "feature_version": "features-1.0.0",
        "policy_version": "policy-1.0.0",
        "config_hash": "cfg-d6cad87c7cbe8eb2",
        "forecast_out_of_fold": True,
        "module_b_available": True,
    }})

    run_id: str
    dataset_id: str
    dataset_sha256: str
    status: str
    started_at: str | None = None
    completed_at: str | None = None
    duration_s: float | None = None
    row_count: int | None = None
    summary: dict = Field(default_factory=dict)
    bands: dict = Field(default_factory=dict)
    model_version: str
    pipeline_version: str
    feature_version: str
    policy_version: str
    config_hash: str
    model_artifact_id: str | None = None
    model_sha256: str | None = None
    forecast_out_of_fold: bool = False
    module_b_available: bool = False
    error: str | None = None
    lot_summary: list[LotDisposition] = Field(default_factory=list)


class ComponentResult(BaseModel):
    """One screened component.

    `evidence` carries structured Module A and Module B payloads; `explanation`
    carries the decision path with its primary and supporting reasons. Both are
    documented in the services that build them.
    """

    model_config = ConfigDict(json_schema_extra={"example": {
        "run_id": "run_a18b6f20c9d4e772",
        "serial": "L04-0348",
        "lot": "L04",
        "wafer": "W01",
        "risk_score": 78.9,
        "verdict": "REJECT",
        "static_breach": False,
        "module_a_score": 18.65,
        "module_a_pooled": 348.5,
        "module_b_score": 0.36,
        "sub_scores": {
            "static_margin": 98.0, "dynamic_outlier": 100.0,
            "predicted_drift": 35.7, "multivariate": 100.0, "curvature": 23.2,
        },
        "explanation": {
            "verdict": "REJECT",
            "primary_reason": {
                "code": "R-102",
                "title": "Lot-relative parametric anomaly",
                "parameter": "Iddq_uA",
                "z_score": 18.65,
                "message": ("Iddq_uA is 18.7 robust sigma from its lot on the "
                            "0 to 168 h drift, against a Dynamic PAT limit of "
                            "6 sigma."),
            },
        },
    }})

    run_id: str
    serial: str
    lot: str
    wafer: str | None = None
    risk_score: float
    verdict: str = Field(..., description="ACCEPT | WATCH | REJECT")
    static_breach: bool
    module_a_score: float | None = None
    module_a_pooled: float | None = None
    module_b_score: float | None = None
    predicted_168h: dict | None = None
    prediction_upper: dict | None = None
    sub_scores: dict
    evidence: dict | None = None
    explanation: dict | None = None
    reason_codes: list[dict] = Field(default_factory=list)
