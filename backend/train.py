"""Train and register the Module B forecaster.

    python -m backend.train                    # train on data/burnin_wide.csv
    python -m backend.train --dataset x.csv    # train on another data log
    python -m backend.train --seed 7

Training is an explicit, offline operation. A screening request loads the
artifact this writes; it never fits a model of its own. That separation is what
makes inference fast (measured: ~45x on the shipped dataset) and what makes a
screening run reproducible across restarts.

The out-of-fold comparison against both baselines is measured here and stored
in the artifact, so `GET /v1/models/performance` reports a number that was
computed under GroupKFold rather than one typed into a slide.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

from backend.app.core.config import get_settings
from backend.app.core.logging import configure_logging
from backend.app.models.database_models import init_db
from backend.app.services.dataset_service import DatasetService
from backend.app.services.model_service import ModelService


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Train the SENTINEL Module B forecaster.")
    ap.add_argument("--dataset", type=Path, default=None,
                    help="CSV to train on (default: data/burnin_wide.csv)")
    ap.add_argument("--seed", type=int, default=42,
                    help="Recorded in the artifact for reproducibility")
    ap.add_argument("--model-version", default=None)
    args = ap.parse_args(argv)

    settings = get_settings()
    configure_logging(settings.log_level)
    settings.ensure_dirs()
    init_db(settings.sqlite_path)

    from src.pipeline import load_wide
    df = pd.read_csv(args.dataset) if args.dataset else load_wide()

    # Register the training frame too, so the artifact's training hash points
    # at a dataset the service can actually show you.
    datasets = DatasetService(settings)
    label = args.dataset.name if args.dataset else "burnin_wide.csv"
    ds = datasets.register_local_frame(df, label, actor="cli:train",
                                       source="training")

    print(f"training on {len(df):,} rows, {df.lot.nunique()} lots "
          f"(dataset {ds['dataset_id']}, sha {ds['sha256'][:16]}…)")
    print("fitting the forecaster and measuring it out-of-fold… "
          "(this is the slow part, and it happens exactly once)")

    art = ModelService(settings).train(df, seed=args.seed,
                                       model_version=args.model_version,
                                       actor="cli:train")

    print(f"\nregistered {art['artifact_id']}  "
          f"({art['model_version']}, sha {art['artifact_sha256'][:16]}…)")
    print(f"  exponents: {art.get('exponents')}")
    metrics = (art.get("metrics") or {}).get("parameters", [])
    if metrics:
        print(f"\n  {'parameter':11s} {'n*':>5s} {'MAE':>9s} {'linear':>9s} "
              f"{'last-val':>9s}  verdict")
        for m in metrics:
            better = "beats both" if m["beats_last_value"] else \
                "LOSES to last-value (exponent 0: no extrapolable signal)"
            print(f"  {m['parameter']:11s} {m['fitted_exponent']:5.2f} "
                  f"{m['model_mae']:9.4f} {m['linear_baseline_mae']:9.4f} "
                  f"{m['last_value_baseline_mae']:9.4f}  {better}")
    print("\nInference now loads this artifact. Start the service with:")
    print("  uvicorn src.api:app --port 8000")
    return 0


if __name__ == "__main__":
    sys.exit(main())
