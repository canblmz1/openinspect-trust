# Repository structure

Target layout (brief §34) with additions marked **+**. The last column says which milestone creates the item. M0 to M3 files exist today; the rest appears with its milestone.

```
openinspect-trust/
├── src/openinspect/
│   ├── __init__.py, __main__.py, cli/       + `python -m openinspect`, the `openinspect` script      M1
│   ├── settings.py                          + data directory from flag, env or .env; safety checks      M2
│   ├── provenance/                          schemas (SourceManifest, ImageRecord, …), registry,          M1–M2
│   │                                        manifest generator, validators
│   ├── ingest/                              download, extract, adapters/, records, report               M2
│   ├── dedup/                               SHA-256, pHash, DINOv2 embeddings and their cache, exact     M3
│   │                                        cosine search, calibration, groups, split leakage, tables,
│   │                                        reports, review pack (embeddings/ was merged in here, T19)
│   ├── taxonomy/                            mapping load, validate, apply                               M4
│   ├── audit/                               label-quality signals, review queue                         M4
│   ├── split/                               A0, A1, B (LOSO), invariants                                M5
│   ├── benchmark/                           InferenceProvider, evaluator, metrics, runner, reports      M7–M9
│   └── evren/                               client.py (HTTP), export.py (YOLO/COCO ZIP), EvrenProvider  M6–M8
├── configs/                                 licences.yaml (allowlist), dedup.yaml (pinned models)       M1, M3
├── artifacts/m3/                          + audit.json (every M3 number), leakage groups, candidate    M3
│                                            pairs, review queue; the neighbour table is ignored (T20)
├── manifests/
│   ├── sources/                             one YAML per source + _template.yaml                        M0
│   ├── evidence/<slug>/                     + archived records, hashed in SHA256SUMS.txt                M0
│   ├── ingest/<slug>/                       + download.json, report.json; cross_source.json             M2
│   ├── images/                              + provenance JSONL per release (release assembly)           M5
│   └── splits/                              + split files and meta                                      M5
├── taxonomy/                                mapping.csv                                                 M4
├── experiments/                             frozen experiment configs, DEVIATIONS.md, EVREN run notes   M7
├── benchmarks/                              run records, metrics, dedup_calibration/                    M3, M7
├── reports/                                 ingest (M2), m3/ similarity and leakage reports with SVG     M2+
│                                            figures, later audit and gap reports (all generated)
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
├── extracted/<slug>/      unpacked files (never edited)
├── records/<slug>/        image and annotation JSONL, files.sha256 (regenerable; their digests are in the ingest report)
├── release/<version>/     normalised images of a release
├── embeddings/            one .npy per image: <model>@<revision>/<preprocessing>/<backend>/ (T19)
├── models/                pinned model weights (Hugging Face cache layout, SHA-256 checked)
├── m3/                    pHash store, synthetic copies, run records, logs, the HTML review pack
└── exports/               YOLO/COCO ZIPs (the brief's `build/…zip`)
```

## What is tracked

| tracked | ignored |
|---|---|
| manifests (YAML), evidence (small JSON/PDF), ingest reports, the M3 audit JSON and small tables, release provenance JSONL, taxonomy CSV, split files, run records, reports, docs, code, synthetic fixtures | images, archives, embeddings, weights, the M3 neighbour table and review pack, `.env`, caches, virtual environments |

## Conventions

- `src/` layout; package `openinspect`; Python 3.12.
- Slugs: lowercase letters, digits, hyphens; immutable once used in an image record.
- IDs: `OI_%06d` for images (assigned at release assembly, T8; ingest records are keyed by source and item path), `DUP-%03d` for duplicate groups.
- Text files use LF line endings (`.gitattributes`) so hashes of manifests do not depend on the operating system.
- Paths inside manifests are POSIX-style and relative.
