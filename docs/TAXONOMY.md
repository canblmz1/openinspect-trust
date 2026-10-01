# Normalized defect taxonomy (M4)

The configuration is [`configs/taxonomy.yaml`](../configs/taxonomy.yaml); the measured consequences are in [reports/m4/](../reports/m4/) ([taxonomy mapping](../reports/m4/taxonomy-mapping.md), [class overlap](../reports/m4/class-overlap.md), [label quality](../reports/m4/label-quality.md)). Decisions T29 to T31 in [DECISIONS](DECISIONS.md).

## The question and the answer

*Which defect classes can legitimately be compared across independent datasets without silently changing their meaning?*

**Four: `short`, `open`, `mouse_bite` and `spurious_copper`.** Each is reached by all three sources with an EXACT or COMPATIBLE mapping, checked against the source's own definition and against sampled boxes. Two of the twelve mappings behind them are COMPATIBLE rather than EXACT, with the difference stated: DsPCBSD+ `SC` (spurious copper) is broader than the other two sources (it includes residue in holes and on copper), and PCB-Defect's definition of `mouse_bite` also mentions board edges (its boxes are notches on trace edges). Everything else stays out of the cross-source comparison:

- shared by two sources only: `spur` (DsPCBSD+, PCB-Defect) and `scratch` (DsPCBSD+, PCB-IND, both COMPATIBLE);
- ambiguous, not merged: PCB-IND `copper_burr` (candidate `spur`) and `stain` (candidate `conductor_foreign_object`);
- source-specific: `missing_copper` (PCB-IND), `missing_pad` (PCB-Defect), `hole_breakout`, `conductor_foreign_object`, `base_material_foreign_object` (DsPCBSD+);
- rejected: PCB-Defect's Roboflow placeholder category `detecting-pcb-defects` (no annotation uses it).

The overlap was not maximised. Merging `copper_burr` into `spur` would have added a fifth benchmark class and about 1,000 PCB-IND images; the evidence does not support it (below), so it was not done.

## Rules

1. **Original labels are immutable.** Every box keeps `original_label` exactly as its source wrote it. `normalized_label`, `mapping_status` and `evidence` are added next to it (`artifacts/m4/taxonomy-map.parquet`); nothing is relabelled, and the mapping can be read backwards (the reverse table in the mapping report).
2. **Every source label is mapped exactly once**, with one status:

   | status | meaning |
   |---|---|
   | `EXACT` | the source's definition says what the normalized class says |
   | `COMPATIBLE` | the same concept, with a documented difference in scope or wording |
   | `AMBIGUOUS` | a candidate relation exists but the evidence does not settle it; the label keeps its own class and names the candidate |
   | `SOURCE_SPECIFIC` | no counterpart in another source; kept as its own class |
   | `REJECTED` | not a defect class (for example a placeholder category); never used |

3. **Evidence, not names.** A mapping cites the source's paper or documentation and is checked against sampled boxes. Equal names prove nothing (`scratch` in DsPCBSD+ is a conductor scratch, in PCB-IND also substrate damage); different names can mean the same thing (`open_circuit`, `OP`, `open`).
4. **When in doubt, keep it source-specific.** A false common class silently changes what a benchmark measures; a missing one only makes the benchmark smaller.
5. **A benchmark class** is a normalized class that every source reaches with `EXACT` or `COMPATIBLE`. Only benchmark classes enter a cross-source release.
6. **Whole images, never single boxes (SPEC 7.4).** An image with a box of any non-benchmark class is excluded from the cross-source release as a whole: dropping only the box would turn a real defect into background, which the model would then be punished for finding. The cost is measured per source in the class-overlap report.

`openinspect taxonomy check` enforces rules 2 and 5 against the source manifests and the ingest reports (every declared or used label mapped, no used label rejected, a mapped label that no manifest declares must be `REJECTED`); it runs in CI without data.

## Evidence

| source | definitions | read from |
|---|---|---|
| `dspcbsd-plus` | Lv et al., Sci Data 11, 811 (2024), Methods, defect categories | the article (open access) |
| `pcb-ind` | Sci Data (2026), doi:10.1038/s41597-026-07684-4, Table 3 (data dictionary) and the Fig. 3 caption | full text from PubMed Central (the article itself is CC BY-NC-ND: definitions are quoted briefly, nothing else is copied) |
| `pcb-defect` | Data in Brief 64, 112296 (2025), defect type descriptions | the article (open access) |

**Representative examples.** For every label involved in a candidate merge, twelve box crops were drawn with a fixed seed and laid out on a contact sheet with the box marked. They were inspected by the assistant that drafted the mapping. This is a check of the drafter's reading, **not an independent human review**; the statuses carry that limitation.

## Hierarchy

Level 0 is `defect`. Level 1 follows the grouping of the DsPCBSD+ paper, the only source that publishes one: `copper_residue` (short, spurious copper, spur, copper burr), `copper_deficiency` (open, mouse bite, missing copper, missing pad, hole breakout), `surface_damage` (scratch), `contamination` (stain and the two foreign-object classes). The families describe the taxonomy; no benchmark is built at family level.

## Decisions, class by class

**`short` (EXACT ×3).** All three definitions describe an unintended connection between distinct conductors. PCB-Defect also mentions solder bridging; its boards are bare etched copper, so the defects are copper bridges.

**`open` (EXACT ×3).** "Connection path within the conductor is interrupted" (DsPCBSD+ `OP`), "broken or interrupted conductive line" (PCB-IND), "a discontinuity in a circuit trace or pad" (PCB-Defect `open_circuit`).

**`mouse_bite` (EXACT, EXACT, COMPATIBLE).** DsPCBSD+ and PCB-IND describe a local notch at a conductor edge that narrows the line without breaking it. PCB-Defect's text says the notches are "usually at the board's edges or within conductor paths", which also evokes depaneling perforations; its defects were designed on conductors and its sampled boxes are notches on trace edges, so the mapping holds with the wording difference recorded.

**`spurious_copper` (COMPATIBLE, EXACT, EXACT).** PCB-IND ("isolated unwanted copper fragments") and PCB-Defect ("random, unwanted pieces of copper that remain after etching") agree. DsPCBSD+ `SC` covers "irregular or unwanted copper residue found on base material, within holes, or on copper surfaces": a superset, hence COMPATIBLE.

**`spur` (DsPCBSD+ and PCB-Defect, EXACT).** Both describe a protrusion from a trace or pad edge. It is not a benchmark class because PCB-IND has no label with that meaning established.

**`copper_burr` (PCB-IND, AMBIGUOUS, candidate `spur`).** The definition ("tiny protruding copper burrs along trace edges, difficult to distinguish from normal roughness") is close to a spur, but the sampled boxes sit mostly at hole and pad edges, unlike the trace-edge spurs of the other two sources, and the authors report confusion of copper burr with short. Not merged.

**`scratch` (DsPCBSD+ `CS` and PCB-IND, COMPATIBLE).** DsPCBSD+ means linear damage on conductors; PCB-IND's data dictionary says "on copper" and its text adds substrate. Two sources only.

**`stain` (PCB-IND, AMBIGUOUS, candidate `conductor_foreign_object`).** Oxidation, oil or fingerprints on copper is part of DsPCBSD+'s conductor foreign object, which also covers particles, bubbles and deposits. Not merged: the candidate is broader than the label.

**`missing_copper` (PCB-IND) and `missing_pad` (PCB-Defect), SOURCE_SPECIFIC.** An area of absent copper foil and an absent pad are different defects; whether PCB-IND's class includes missing pads is not stated, so they were not merged.

**`hole_breakout`, `conductor_foreign_object`, `base_material_foreign_object` (DsPCBSD+), SOURCE_SPECIFIC.** No other source labels hole-to-pad registration defects or foreign objects.

**`detecting-pcb-defects` (PCB-Defect), REJECTED.** Category 0 of the Roboflow COCO export, the project name; no annotation uses it (M2 anomaly `unused_category`).

## Consequences for the release

From the M4 audit ([class overlap](../reports/m4/class-overlap.md)): DsPCBSD+ keeps 3,292 of 10,259 images (32%) as whole images, PCB-IND 1,713 of 4,789 (36%) plus 127 images without boxes, and PCB-Defect none: every one of its 230 scans holds a `spur` or `missing_pad` box. PCB-Defect's 1,132 benchmark-class boxes can therefore enter a release only as crops that contain no box of another class, which is the crop policy D7 fixed at the start of M5. In pixels the classes also differ (a DsPCBSD+ `mouse_bite` box has a median long side of 16 px in a 226 px patch, PCB-IND's 25 px in a 300 px patch); the report lists the sizes so that later results can be read against them.

## Generic fields

The code knows no PCB label. Every box carries the generic fields `source_id`, `group_id`, `subgroup_id`, `acquisition_id`, `split`, `original_label`, `normalized_label`, `mapping_status` and `evidence`; what the keys mean per source is declared in `configs/dedup.yaml` (`sources:`), what the labels mean in `configs/taxonomy.yaml`. Another domain needs a configuration, not code.

## Changing the taxonomy

Edit `configs/taxonomy.yaml` (with evidence), run `openinspect taxonomy check`, then `openinspect taxonomy audit --all` to rewrite `artifacts/m4/` and `reports/m4/`; the committed reports are tested against the committed audit and the taxonomy's SHA-256. The taxonomy used by a release is frozen by the release manifest (M5), which records its hash.

## Limitations

- The mapping was drafted and checked by the assistant under the maintainer's autonomous-execution directive; it has not been reviewed by an independent person.
- Definitions in papers are short; two annotators can apply one definition differently. COMPATIBLE mappings carry a stated scope difference that can still move results.
- The label-quality queue (`artifacts/m4/review-required.csv`) has not been reviewed; it holds rule-based findings, and no label was changed because of it.
