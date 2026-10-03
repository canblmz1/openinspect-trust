"""Paper tables (markdown) generated from the frozen CSVs in reports/m7_final. Values rounded to 2 decimals."""
import ast
from pathlib import Path
import pandas as pd
ROOT = Path(__file__).resolve().parents[2]; F = ROOT / "reports/m7_final"; T = ROOT / "paper/tables"; T.mkdir(exist_ok=True)
f = lambda x: f"{x:+.2f}".replace("-", "−")
rep = pd.read_csv(F / "FINAL_REPLICATION_TABLE.csv"); main = rep[rep.seed.astype(str).str.fullmatch(r"\d")].copy()
L = ["# Table S1. C0 − C1 mAP50-95 (percentage points), every matched seed pair\n", "| design | seed | overall | probes | controls | probes − controls |", "|---|---|---|---|---|---|"]
for _, r in main.iterrows(): L.append(f"| {r.design} | {r.seed} | {f(r.overall)} | {f(r.probe)} | {f(r.control)} | {f(r.probe_minus_control)} |")
L.append(f"| unweighted mean (8 pairs) | | {f(main.overall.mean())} | {f(main.probe.mean())} | {f(main.control.mean())} | {f(main.probe_minus_control.mean())} |")
s = rep[~rep.seed.astype(str).str.fullmatch(r"\d")]
for _, r in s.iterrows(): L.append(f"| {r.design} (sensitivity) | {r.seed} | {f(r.overall)} | {f(r.probe)} | {f(r.control)} | {f(r.probe_minus_control)} |")
(T / "tableS1_seed_level.md").write_text("\n".join(L) + "\n", encoding="utf-8")
sa = pd.read_csv(F / "FINAL_SEED_AWARE_STATS.csv")
L = ["# Table S2. Design means and 95% intervals. A = test sampling (cluster bootstrap, seeds fixed); B = training seeds (t-interval); C = combined two-stage bootstrap\n",
     "| design | estimand | seeds | mean | A | B | C | P(≤0) under C |", "|---|---|---|---|---|---|---|---|"]
for _, r in sa.iterrows():
    A = f"{f(r.A_test_sampling_lo)}, {f(r.A_test_sampling_hi)}" if pd.notna(r.A_test_sampling_lo) else ""
    Bv = f"{f(r.B_seed_t_lo)}, {f(r.B_seed_t_hi)}" if pd.notna(r.get("B_seed_t_lo")) else ""
    P = f"{r.C_combined_P_le_0:.3f}" if pd.notna(r.C_combined_P_le_0) else ""
    n = int(r.n_seeds) if pd.notna(r.n_seeds) else 8
    L.append(f"| {r.design} | {r.estimand.replace('_', ' ')} | {n} | {f(r.point_mean)} | {A} | {Bv} | {f(r.C_combined_two_stage_lo)}, {f(r.C_combined_two_stage_hi)} | {P} |")
(T / "tableS2_seed_aware.md").write_text("\n".join(L) + "\n", encoding="utf-8")
pl = pd.read_csv(F / "FINAL_PLACEBO_RESULTS.csv")
L = ["# Table S3. Placebo: observed probe − control vs 10,000 source-stratified random relabellings of whole test groups (predictions fixed)\n",
     "| design | seeds | observed | null mean | null SD | one-sided p | two-sided p |", "|---|---|---|---|---|---|---|"]
for _, r in pl.iterrows(): L.append(f"| {r.design} | {r.n_seeds} | {f(r.observed_probe_minus_control)} | {f(r.null_mean)} | {r.null_sd:.2f} | {r.p_one_sided:.3f} | {r.p_two_sided:.3f} |")
(T / "tableS3_placebo.md").write_text("\n".join(L) + "\n", encoding="utf-8")
dr = pd.read_csv(F / "FINAL_DOSE_RESPONSE.csv")
L = ["# Table S4. C0 − C1 mAP50-95 by exposure stratum (per-seed values; strata fixed before the last three seed pairs were trained)\n",
     "| design | representation | stratum | test images | per seed | mean |", "|---|---|---|---|---|---|"]
for _, r in dr[dr.bin.str.startswith(("control", "probe"))].iterrows():
    ps = ", ".join(f(x) for x in ast.literal_eval(r.per_seed)); L.append(f"| {r.design} | {r.representation} | {r.bin} | {r.n_images} | {ps} | {f(r['mean'])} |")
L += ["", "Continuous: Spearman ρ between Δ and per-image recall gain (probes), 95% cluster-bootstrap interval", "", "| design | representation | ρ | 95% CI |", "|---|---|---|---|"]
for _, r in dr[dr.bin.str.startswith("continuous")].iterrows(): L.append(f"| {r.design} | {r.representation} | {r['mean']:.2f} | {r.ci_lo:.2f} to {r.ci_hi:.2f} |")
(T / "tableS4_exposure_strata.md").write_text("\n".join(L) + "\n", encoding="utf-8")
(T / "tableS5_source_shift.md").write_text("""# Table S5. Source-held-out evaluation (mAP50-95; one seed per model)

| held-out source | held-out test images | in-distribution reference (other same-source test images) | B-strict (source held out) | B-natural (machine-linked items kept) | difference (strict − reference) |
|---|---|---|---|---|---|
| DsPCBSD+ | 1,768 | 43.74 (A1) | 16.37 | 15.21 | −27.37 |
| PCB-IND | 1,713 | 56.82 (A1) | 19.17 | 19.72 | −37.65 |
| PCB-Defect | 939 | 47.62 (A0) | 0.33 | — (identical to strict) | −47.29 |

Same 93 PCB-Defect images: A0 47.62 vs held-out model 0.27. Source identity predicted from width, height and format: 100% balanced accuracy.
""", encoding="utf-8")
(T / "tableS6_visual_adjudication.md").write_text("""# Table S6. AI-assisted visual adjudication (not human-validated)

Two blinded passes by separate instances of the same model family, then adjudication. Fine-scale κ = 0.17 (95% CI 0.03–0.30); coarse: same-instance κ = 0.49, same-family-or-closer κ = 0.45, ambiguous κ = 0.74. Agreement measures internal consistency, not inter-rater reliability.

| coarse category | D0 probe → nearest exposing mate (n = 60) | control → nearest C0 training image (n = 30) |
|---|---|---|
| near-exact duplicate | 0 | 0 |
| same specimen / capture series likely | 4 | 0 |
| same design / layout family | 9 | 4 |
| structurally related | 28 | 14 |
| not meaningfully related | 16 | 12 |
| ambiguous | 3 | 0 |

Earlier AI review of 300 similarity-audit candidate pairs: 0 of 66 cross-source pairs duplicate-like.
""", encoding="utf-8")
(T / "tableS7_prior_art.md").write_text("""# Table S7. Closest prior work vs this study (from abstracts / landing pages; see paper/CITATION_AUDIT.md)

| work | task | leakage unit | fixed common test set across conditions | controlled exposure manipulation | within-test negative control | multiple training seeds | source/domain-held-out arm |
|---|---|---|---|---|---|---|---|
| Barz & Denzler 2020 [1] | classification | near-duplicate images | no (test set purged) | no | no | not central | no |
| Laroca et al. 2023 [2] | licence-plate recognition | same plate | no (fair split) | retraining on fair split | no | multiple models | no |
| Tampu et al. 2022 [3] | OCT classification | subject/volume | no | split strategy | no | repeated | no |
| Figueiredo & Mendes 2024 [4] | video object detection | correlated frames | no | split strategy | no | not verified | no |
| Babu et al. 2024 [6] | automotive object detection | injected test images | yes | yes (injection rate) | no | repeated (not verified in detail) | no |
| DataSAIL 2025 [5] | biomedical ML | similarity | no | splitting tool | no | — | out-of-distribution splits |
| this study | PCB object detection | machine-detected visual-similarity groups | yes (byte-identical) | yes (group-mates vs matched replacements) | yes (unexposed controls) | 8 matched seed pairs | yes |
""", encoding="utf-8")
lk = pd.read_csv(F / "probe_link_split.csv")
L = ["# Table S8. Pre-planned split of probes by link type: C0 − C1 mAP50-95 (per-seed values)\n", "| design | link type | probes | per seed | mean |", "|---|---|---|---|---|"]
for _, r in lk.iterrows(): L.append(f"| {r.design} | {r.probe_link} | {r.n_probes} | {', '.join(f(v) for v in ast.literal_eval(r.per_seed))} | {f(r['mean'])} |")
(T / "tableS8_probe_link_split.md").write_text("\n".join(L) + "\n", encoding="utf-8")
print("tables ok")
