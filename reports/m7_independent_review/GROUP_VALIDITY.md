# Group validity: how often a machine-detected pair is visually related

Basis: final AI-adjudicated labels on the 300 M3 review pairs (`VISUAL_REVIEW_300.csv`). **AI visual adjudication was performed on 300/300 review pairs. This is not a substitute for independent human validation.**

"Duplicate-like" means A+B (exact duplicate, or the same scene or capture). "Related" means A+B+C (C adds the same design family). Percentages carry Wilson 95% intervals. The sample is stratified with about 9 pairs per stratum, so each row estimates *that stratum*. The rows are not weighted to the population of 14,653 graph pairs.

## By machine category (the M3 threshold level)

| machine category | n | duplicate-like (A+B) | related (A+B+C) | not related (D+E) | ambiguous (F) |
|---|---|---|---|---|---|
| NEAR_DUPLICATE (cosine ≥ near) | 75 | 22 (29%, 20–40) | 44 (59%, 47–69) | 29 (39%, 28–50) | 2 |
| SAME_FAMILY_OR_SCENE (≥ family) | 78 | 11 (14%, 8–24) | 27 (35%, 25–46) | 51 (65%, 54–75) | 0 |
| REVIEW_REQUIRED (pHash-only) | 61 | 9 (15%, 8–26) | 13 (21%, 13–33) | 48 (79%, 67–87) | 0 |
| BELOW_REVIEW | 86 | 11 (13%, 7–21) | 16 (19%, 12–28) | 66 (77%, 67–84) | 4 |

The NEAR_DUPLICATE label is right about duplicates less than a third of the time. Even counting "same family", it is right only 59% of the time. BELOW_REVIEW still holds 13% duplicate-like pairs, so the graph also has misses.

## By source × category (the most decision-relevant table)

| stratum | n | A+B | A+B+C | D+E |
|---|---|---|---|---|
| NEAR / DsPCBSD+ | 18 | 39% | **94%** | 6% |
| NEAR / PCB-IND | 27 | 33% | 67% | 26% |
| NEAR / PCB-Defect | 18 | 33% | 50% | 50% |
| NEAR / cross-source | 12 | 0% | **0%** | 100% |
| FAMILY / DsPCBSD+ | 18 | 17% | 50% | 50% |
| FAMILY / PCB-IND | 24 | 33% | 71% | 29% |
| FAMILY / PCB-Defect | 18 | 0% | **6%** | 94% |
| FAMILY / cross-source | 18 | 0% | 0% | 100% |
| REVIEW / DsPCBSD+ | 18 | 0% | 0% | 100% |
| REVIEW / PCB-IND | 25 | 36% | 52% | 48% |
| REVIEW / cross-source | 18 | 0% | 0% | 100% |
| BELOW / PCB-IND | 36 | 25% | 31% | 67% |

Wilson intervals are in `data/` and are wide, around ±20 points at n = 18.

## By score region and pair type

| DINOv2-small cosine | n | A+B | A+B+C |
|---|---|---|---|
| < 0.85 | 92 | 10% | 15% |
| 0.85–0.918 | 55 | 20% | 27% |
| 0.918–0.934 (family band) | 79 | 14% | 34% |
| 0.934–0.96 (near band) | 63 | 21% | 52% |
| ≥ 0.96 | 11 | **82%** | **100%** |

| pHash distance | n | A+B | A+B+C |
|---|---|---|---|
| 0–4 | 69 | 22% | 29% |
| 5–10 | 7 | 86% | 100% |
| 11–20 | 25 | 44% | 76% |
| > 20 | 199 | 11% | 27% |

| pair type | n | A+B | A+B+C |
|---|---|---|---|
| same-source | 234 | 23% (18–28) | 42% (36–49) |
| cross-source | 66 | 0% (0–6) | 2% (0–8) |

## Error modes

1. **Cross-source chaining.** No cross-source pair was visually related. Yet constraint groups do cross sources: e.g. a PCB-IND item has constraint group `OI_dspcbsd-plus_009a9317de3b`. Constraints of that kind are spurious.
2. **Generic-texture matches.** Parallel traces, square pad grids, holes with burrs and copper particles on a dark field all score high in DINO and in pHash without sharing a specimen. This is the main source of D at the near and family thresholds.
3. **PCB-Defect family level.** Inside one family of DIY boards, DINO cannot tell "same design region" from "same style". At the family threshold the related rate is 6%. This is consistent with the 859/939 giant component that M5.5 rated verdict E.
4. **Low pHash distance is not duplication.** Many pairs at pHash 0–4 are near-uniform crops, so pHash 0–4 is less precise than pHash 5–20.
5. **Mirrored duplicates are missed by both measures.** Flipped copies (several A pairs) often fall below both thresholds.

## Reading

- Only one subset deserves the word "near-duplicate" without qualification: DsPCBSD+ pairs at cosine ≥ 0.96 or in the near band (A+B+C 94%).
- The groups behind the M7 probes are, on this evidence, mostly **same-family or same-scene groups with substantial noise**. They are not near-duplicate groups.
- No graph-wide precision is reported. The sample was not drawn for that purpose, and weighting 9-pair strata to 14,653 pairs would produce intervals too wide to be useful.
