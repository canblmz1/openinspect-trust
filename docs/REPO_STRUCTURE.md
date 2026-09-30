# Repository structure

Target layout (brief §34) with additions marked **+**. The last column says which milestone creates the item. Only M0 files exist today.

```
openinspect-trust/
├── src/openinspect/
│   ├── __init__.py, __main__.py, cli.py     + `python -m openinspect` and the `openinspect` script     M1
│   ├── provenance/                          schemas (SourceManifest, ImageRecord, …), registry,          M1–M2
│   │                                        manifest generator, validators
│   ├── ingest/                              downloaders, integrity checks, metadata, normalisation      M2
│   ├── dedup/                               exact, pHash, grouping, review files                        M3
│   ├── embeddings/                          DINOv2 / OpenCLIP extraction, nearest-neighbour search      M3
│   ├── taxonomy/                            mapping load, validate, apply                               M4
│   ├── audit/                               label-quality signals, review queue                         M4
│   ├── split/                               A0, A1, B (LOSO), invariants                                M5
│   ├── benchmark/                           InferenceProvider, evaluator, metrics, runner, reports      M7–M9
│   └── evren/                               client.py (HTTP), export.py (YOLO/COCO ZIP), EvrenProvider  M6–M8
├── configs/                                 licences.yaml (allowlist), calibrated thresholds            M1, M3
├── manifests/
│   ├── sources/                             one YAML per source + _template.yaml                        M0
│   ├── evidence/<slug>/                     + archived records, hashed in SHA256SUMS.txt                M0
│   ├── sha256/                              + per-source file hash lists                                M2
│   ├── images/                              + provenance JSONL per release                              M2
│   └── splits/                              + split files and meta                                      M5
├── taxonomy/                                mapping.csv                                                 M4
├── experiments/                             frozen experiment configs, DEVIATIONS.md, EVREN run notes   M7
├── benchmarks/                              run records, metrics, dedup_calibration/                    M3, M7
├── reports/                                 dedup, audit and gap reports (generated)                    M3+
├── scripts/                                 thin helpers only; logic lives in the package               as needed
├── tests/
│   ├── unit/, integration/
│   └── fixtures/                            + synthetic, seeded, generated (no real dataset images)     M1+
├── docs/
│   ├── SPEC.md, REPO_STRUCTURE.md, DEPENDENCIES.md, DATASET_INTAKE.md, LICENCE_CHECKLIST.md,
│   │   DEFINITION_OF_DONE.md, DECISIONS.md, EVREN.md                                                    M0
│   └── evren-feedback/                      local records of EVREN issues (brief §39)                   M0
├── .github/workflows/ci.yml                 lint, type-check, tests, manifest/licence/split checks     M1
├── README.md, DATA_CARD.md, PROVENANCE.md, METHODOLOGY.md, BENCHMARK.md,
│   SECURITY.md, CONTRIBUTING.md, CHANGELOG.md +, LICENSE +, ATTRIBUTION.md +                            M10
├── LICENSE_MATRIX.md                                                                                    M0
├── pyproject.toml, uv.lock +                                                                            M1
├── docker-compose.yml                       only when Postgres/pgvector or the backend is needed        later
└── .env.example, .gitignore, .gitattributes +                                                           M0
```

## Not in the repository

Heavy data lives outside git and outside OneDrive, under `OPENINSPECT_DATA_DIR`:

```
<OPENINSPECT_DATA_DIR>/
├── raw/<slug>/            downloaded archives (never edited)
├── extracted/<slug>/      unpacked files
├── release/<version>/     normalised images of a release
├── embeddings/            .npy files
└── exports/               YOLO/COCO ZIPs (the brief's `build/…zip`)
```

## What is tracked

| tracked | ignored |
|---|---|
| manifests (YAML), evidence (small JSON/PDF), provenance JSONL, dedup groups, taxonomy CSV, split files, run records, reports, docs, code, synthetic fixtures | images, archives, embeddings, weights, `.env`, caches, virtual environments |

## Conventions

- `src/` layout; package `openinspect`; Python 3.12.
- Slugs: lowercase letters, digits, hyphens; immutable once used in an image record.
- IDs: `OI_%06d` for images, `DUP-%03d` for duplicate groups.
- Text files use LF line endings (`.gitattributes`) so hashes of manifests do not depend on the operating system.
- Paths inside manifests are POSIX-style and relative.
