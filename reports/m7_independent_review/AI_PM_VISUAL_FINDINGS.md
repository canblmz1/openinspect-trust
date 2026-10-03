# Probe–mate review: what the images show

AI visual adjudication was completed. Two independent AI review passes were performed. They used the same underlying model in separate blinded contexts. The final labels are adjudicated (`AI_PM_ADJUDICATED.csv`).

Categories: A near-exact duplicate; B same physical board or capture series likely; C same design or layout family; D related design or strong structural similarity; E generically similar, probably independent; F unrelated; G ambiguous.

## Final labels

| set | n | A | B | C | D | E | F | G |
|---|---|---|---|---|---|---|---|---|
| probe → nearest exposing mate | 60 | **0** | 4 | 9 | 28 | 16 | 0 | 3 |
| control → nearest C0-train image | 30 | 0 | 0 | 4 | 14 | 12 | 0 | 0 |
| all | 90 | 0 | 4 | 13 | 42 | 28 | 0 | 3 |

By link type (probes):

| link type | n | A | B | C | D | E | G | typical observation |
|---|---|---|---|---|---|---|---|---|
| crop sibling (PCB-Defect) | 12 | 0 | 0 | 0 | 12 | 0 | 0 | same hand-etched green-FR4 board style and scratch texture; *different regions*, no shared geometry |
| same component (DsPCBSD+) | 12 | 0 | 0 | 1 | 11 | 0 | 0 | the same repeated pattern type (square-pad arrays, diagonal buses, ring pads), but pitch and scale not shown to match |
| similar pair (mostly DsPCBSD+) | 16 | 0 | 2 | 8 | 3 | 2 | 1 | same trace geometry with defects at the same relative place (C); two show the same defect on the same traces (B) |
| same metadata group (PCB-IND same board ID) | 20 | 0 | 2 | 0 | 2 | 14 | 2 | mostly different regions in the same dark-mask style; 2 overlapping crops |

Controls are useful as a baseline. Their nearest C0-train neighbour is just as often "structurally similar" (D 47%) as a probe's nearest mate (D 47%). Only probes produced B labels (4 vs 0), and C is similar (15% probes vs 13% controls). **At the D level, probes and controls look alike. What distinguishes the probes is a small number of same-instance and same-design links.**

## Notable cases

- **No near-exact duplicate (A) survived.** One reviewer called the oval-ring pair A, a possible 180° rotation. Because the content is symmetric, a rotated copy cannot be separated from two adjacent crops of one capture, so it was adjudicated **B**.
- The 4 B pairs: an identical bubble defect on the same three traces (DsPCBSD+); an oval ring split across two adjacent crops; a rounded pad with the same bright damage streak in overlapping crops (PCB-IND); and a dark blob with a matching lobed copper contour (PCB-IND).
- 3 pairs stayed G: near-empty dark images or very blurry fragments.

## PCB-IND same-board-ID subset (Phase 7)

These are the 20 probes linked to their mates only by the source's board-ID metadata. In the full D0 set this subset gains +11.3 pp.

| relation (visual evidence only) | n |
|---|---|
| same exact physical board (near-duplicate) | 0 |
| **same physical board region from another crop (visually likely)** | **2** |
| same batch / layout only (similar layout elements, no matching specifics) | 2 |
| same design but distinct board | 0 |
| visually unrelated (different regions; dark-mask style only, or sparse content) | 14 |
| ambiguous | 2 |

A shared board ID in the file name does **not** come with visible evidence of a shared specimen in 18 of 20 pairs. In 14 the nearest mate shows a different region with nothing in common beyond the dark solder-mask style. The ID implies a common physical board, but that is provenance, not something these images show.

Limitation: the reviewed mate is the DINO-nearest one. Another mate from the same board ID might overlap the probe more, so 2/20 is a lower bound on visible overlap within those groups, not an upper bound.

## Bottom line

- Literal duplicates: **0 of 60** probe–mate pairs (0 of 90 overall).
- Same specimen or capture visible: **4 of 60** (7%).
- Same design or layout: 9 of 60 (15%).
- Structural similarity only: 28 of 60 (47%).
- Not meaningfully related: 16 of 60 (27%). Ambiguous: 3 of 60 (5%).
- The visual relationship behind M7's "exposure" is overwhelmingly **same family or style** (C/D, 62%) or **none visible** (27%). It is not duplication.
