"""Training readiness of a release (Milestone 5.5).

Before any model is trained, these checks ask whether a difference between two training runs
could be explained by one experimental factor: the controlled common-evaluation design, the
representation sensitivity of the group-aware split, the release items that the label audit
flagged, how predictable the source of an image is, the two source-held-out regimes, the
negative policy, and an export validation that shares no code with the exporter. Nothing here
changes a release, a split or a label of an earlier milestone.
"""
