# Changelog

All notable changes are recorded here. Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Versions follow PEP 440.

## [Unreleased]

### Added — licence

- `LICENSE`: Apache-2.0 for the code (decision D3, chosen by the maintainer); `pyproject.toml` declares it.

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
