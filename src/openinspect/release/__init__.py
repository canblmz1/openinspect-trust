"""Release assembly and canonical splits (Milestone 5).

The release is built from the ingest records, the taxonomy (M4) and the similarity audit (M3):
stable global ids, the crop policy D7, a deterministic class-stratified sample, the splits A0
(random), A1 (group-aware: metadata groups, visual similarity components, exact duplicates, crop
parents) and B (source-held-out), the leakage invariants, a machine-readable manifest, and the
packages for EVREN. Like the rest of the core, nothing here names a dataset: sources, keys,
labels and crop rules come from the configuration.
"""
