"""SENTINEL backend service layer.

The ML core lives in `src/` and is not moved: it carries the project's
non-negotiable rules and 150 tests. This package is the SERVICE layer around
it - ingestion, validation, persistence, jobs, audit and the HTTP API.

    backend/app  ->  imports  ->  src/   (features, module_a, module_b,
                                          fusion, explain, evaluate, pipeline)

Never the other way round. `src/` must stay runnable with no database, no
config and no web server, because that is what the test suite and the
reproducibility story depend on.
"""

