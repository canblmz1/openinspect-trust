# Security

## Reporting a vulnerability

Do not open a public issue with details of a vulnerability. Use GitHub's "Report a vulnerability" button on the Security tab of this repository if it is available. Otherwise open an issue titled "security contact request" that contains no details, and the maintainer will arrange a private channel.

## What must never be committed

- Secrets of any kind: the EVREN API key (`EVREN_API_KEY`), endpoint URLs that embed credentials, tokens, passwords. They live in a local `.env` file, which is git-ignored; `.env.example` stays empty.
- Dataset images, archives and model weights (they are large and carry third-party licences).
- Personal data.

## Handling of secrets in code

- Secrets are read from the environment only; the EVREN client (planned) never logs or stores a token and never writes it to a run record.
- Evidence snapshots under `manifests/evidence/` are public registry metadata. Do not add files there that came from an authenticated session.

## Supply chain

- GitHub Actions are pinned to full commit SHAs; dependencies are pinned by `uv.lock`.
- Dependency licences are audited; the AGPL-3.0 package Ultralytics is an optional extra and is never bundled ([docs/DEPENDENCIES.md](docs/DEPENDENCIES.md)).

## Security issues in EVREN or in third-party services

Do not exploit them and do not try to reach other users' data. Verify the minimum needed to describe the problem, then report it privately to the operator. Normal bugs are recorded under `docs/evren-feedback/`.
