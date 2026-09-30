# Changelog

All notable changes are recorded here. Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Versions follow PEP 440.

## [Unreleased]

### Added — licence

- `LICENSE`: Apache-2.0 for the code (decision D3, chosen by the maintainer); `pyproject.toml` declares it.

### Added — M2: ingest

- `openinspect ingest download | extract | inspect | run | report`.
  - `download` fetches each accepted archive from its manifest URL, resumes interrupted transfers, retries with backoff, and keeps a file only if its size and the repository's checksum (MD5 or SHA-256) match; it computes the SHA-256 and writes `download_date` (first download only) and `archive_sha256` into the manifest.
  - `extract` checks the CRC-32 of every zip member and extracts safely: no path traversal, absolute paths, reserved Windows names, case-insensitive collisions or symlinks; member-count and size limits; a `.partial` directory that is renamed on success; SHA-256 of every file.
  - `inspect` prints the extracted file tree; `run` does all of the above, reads the annotations, decodes every image and writes records and reports; `report` rebuilds the Markdown report.
- One adapter per source, written after looking at the real archives: `dspcbsd-plus` (COCO canonical, YOLO cross-check), `pcb-ind` (YOLO canonical, COCO and VOC cross-check), `pcb-defect` (COCO). Orphan images, orphan annotations, degenerate boxes and disagreements between formats are reported as anomalies, not repaired silently.
- Image and annotation records (SHA-256, size, format, EXIF orientation, 64-bit dHash, original split, group key, labels) as JSONL under the data directory. In git: `manifests/ingest/<slug>/report.json` and `download.json`, `manifests/ingest/cross_source.json`, and `reports/m2-ingest-report.md` (images, annotations, classes, original splits, grouping key, anomalies and adapter status per source).
- Reconciliation of each manifest with its archive (ingest gate G7): counts, class counts, sizes and splits are recomputed and compared. The three manifests now carry the measured values (class counts, image sizes, group keys, weaknesses).
- Exact-duplicate check (SHA-256) inside each source and across sources: none found.
- `openinspect.settings`: the data directory comes from `--data-dir`, `OPENINSPECT_DATA_DIR` or `.env`; a directory inside the repository or OneDrive is refused; free-space check.
- Dependencies: `httpx`, `pillow`, `defusedxml`; dev: `types-defusedxml`.
- 367 tests (unit tests on synthetic archives with the real layouts, plus integration tests that check the committed reports against the manifests), 99% coverage.
- Decisions T8–T14 in [docs/DECISIONS.md](docs/DECISIONS.md).

### Added — M1: source registry

- `openinspect source add | list | show | validate` (Typer CLI, also `python -m openinspect`).
  - `add` registers a pending or rejected source from flags, or any complete manifest with `--from-file`; it refuses duplicate slugs (`--force` replaces only the file named after the slug) and cannot create an `accepted` source from flags.
  - `list` and `show` support `--json`; `list` can filter by `--status`.
  - `validate` checks schema, licence allowlist, evidence hashes against `manifests/evidence/SHA256SUMS.txt`, slug/file consistency and duplicate slugs; `--release public` fails for accepted sources whose redistribution or derivative-work answer is not `allowed`; `--strict` turns warnings into errors; exit code 1 on failure.
- Pydantic v2 schema of the source manifest with status rules (two tiers: accepted = admitted for internal use; public release needs redistribution and derivative work allowed).
- `configs/licences.yaml`: allowlist CC0-1.0 and CC-BY-4.0; NC, ND and SA terms are refused with an explanation.
- 161 tests (unit and integration), `ruff`, `mypy --strict`, 98% coverage.
- GitHub Actions: lint, type-check, tests (Ubuntu and Windows), manifest validation; actions pinned to commit SHAs.
- `README.md`, `SECURITY.md`.

### Added — M0: specification

- Technical specification, scope, repository structure, dependency list, dataset intake format, licence acceptance checklist, definition of done, decision log, EVREN facts and unknowns (`docs/`).
- Source manifests: `dspcbsd-plus`, `pcb-ind`, `pcb-defect` accepted (CC BY 4.0); `deeppcb` rejected (README limits use to research, LICENSE file says MIT).
- Licence evidence from the repository records, DataCite and Crossref, archived and hashed (`manifests/evidence/`); `scripts/hash_evidence.py` regenerates the hash list.
