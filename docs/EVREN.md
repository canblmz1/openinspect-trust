# EVREN: facts, unknowns and how each gets verified

Source of the facts below: the maintainer's statement of 2026-09-30, taken from the EVREN user guide. They could not be verified independently: EVREN's public explore page is a JavaScript application that returned no documentation to an automated fetch. Where a fact decides a result, the plan says how it gets verified.

Status codes: **GUIDE** = stated in the EVREN user guide (per the maintainer) · **OBSERVED** = seen by the maintainer in the EVREN web UI during the M6 smoke test on 2026-10-01, for the tested package only · **UNKNOWN** = not verified · **EXPERIMENT** = will be verified by a small test.

## Datasets

| fact | status | consequence |
|---|---|---|
| Modalities: VISION, AUDIO, NLP, MULTIMODAL | GUIDE | this project uses VISION |
| Import formats include YOLO Detection, YOLO Segmentation, YOLO OBB, COCO JSON, Pascal VOC, CreateML, Label Studio, CSV, classification folders | GUIDE | export YOLO Detection first, COCO JSON second |
| ZIP import limit: 30 GB | GUIDE | every v0.1 archive is far smaller |
| Each item can be assigned to train, val or test manually | GUIDE | the local split file can be applied item by item if folders are not kept |
| Auto Split is a separate, optional feature | GUIDE | never use it on a source-held-out dataset; not used in M6 |
| A YOLO Detection ZIP imports (format detected as "YOLO Detection") | **OBSERVED** (M6) | 20 images, 37 annotations, 4 classes, 0 unlabelled images, as packaged |
| Class names and box counts of the package become EVREN's classes | **OBSERVED** (M6) | `short` 8, `open` 8, `mouse_bite` 11, `spurious_copper` 10, as packaged |
| Does an imported ZIP keep its own train/val/test folders? | **OBSERVED: yes, for the M6 smoke package** | after import, without Auto Split: 10 / 5 / 5 as supplied, and one known item per split showed its expected split and labels; the other 17 items were not checked one by one, and other layouts or larger imports were not tested |
| Boxes are drawn where the defects are | **OBSERVED** on the 3 items opened | the maintainer's visual judgement, not a measurement |
| Dataset versions can be created and frozen | **OBSERVED** (M6) | version `v0.1-smoke`, "Versiyon oluşturuldu ve donduruldu", with "Alt Küme ile Versiyonla" and "Split Dağılımını Yeniden Ata" off |
| A frozen version keeps the supplied split | **OBSERVED** (M6) | the frozen version shows 20 items, 37 annotations, 4 classes and 10 / 5 / 5 |
| Dataset Health panel | **OBSERVED** (M6) | grade A, 81 (labelling 100%, split distribution 100%, class balance 73%, data volume 12%); an EVREN platform score, not an OpenInspect assurance result |
| File names, pixels and label files are kept byte for byte | UNKNOWN | the 3 opened items showed their global-id names; no EVREN export was downloaded and hashed |

**Rule.** The local manifest (`manifests/splits/*`, `manifests/experiments/*`) is the canonical split. M6 observed that EVREN kept the supplied split of one 20-item package; every later import is still re-checked against its split file (counts per split and known items) before a model is trained on it, with Auto Split off.

## M6: the import smoke test (result: PASS)

The package and its expected result exist before anything is uploaded (decision T36):

| item | value |
|---|---|
| package | `<OPENINSPECT_DATA_DIR>/exports/v0.1/openinspect-trust-v0.1-evren-smoke-yolo.zip` (never committed) |
| SHA-256 | `7a3bafd5d7b1e19be1023f880cf8ab4569f3f76930342ec4a642610df63c08c4` |
| format | YOLO Detection: `data.yaml` (`nc: 4`, names `0 short`, `1 open`, `2 mouse_bite`, `3 spurious_copper`), `images/<split>/`, `labels/<split>/` |
| content | 20 items of split A1: 10 train, 5 val, 5 test; JPEG patches and PNG crops; file names are global ids |
| expected result | [manifests/releases/v0.1/evren-smoke/expected-splits.csv](../manifests/releases/v0.1/evren-smoke/expected-splits.csv) and `smoke.json` (every member's SHA-256) |

**Result (2026-10-01): PASS.** Every observation matched the expectation committed before the upload, and the ZIP in the data directory still has the recorded SHA-256 ([reports/m6/evren-smoke-test.md](../reports/m6/evren-smoke-test.md), `artifacts/m6/evren-smoke-test.json`, observations in `manifests/releases/v0.1/evren-smoke/observed.yaml`). No screenshot is committed, and no training was started.

Planned steps (T36), all in the EVREN UI with the maintainer's authenticated session: (1) create a test dataset (VISION) and import the ZIP as YOLO Detection with Auto Split off; (2) check the four class names and ids; (3) check the box counts of a few items against `expected-splits.csv`; (4) list the item names per split and compare them with `expected-splits.csv`; (5) look at the dataset health and version pages; (6) freeze or version the dataset if the UI offers it; (7) record what was seen. What was done is recorded in `observed.yaml`: steps 1, 5 and 6 in full; step 2 by class names and box counts per class; steps 3 and 4 for one opened item per split (its split and labels), not for every item; step 7 as text. The UNKNOWN on split preservation above changed only on that direct evidence.

## Training

- Architectures: YOLO26, YOLO11, YOLOv10, YOLOv9, YOLOv8, RT-DETR. Tasks: detection, segmentation, OBB, pose, classification (GUIDE).
- No training job has been started on EVREN (M6 stopped before training on purpose). M7 runs only after the maintainer approves the compute; the run matrix is [reports/m5_5/m7-plan.md](../reports/m5_5/m7-plan.md).
- This project: first benchmark **YOLO11n**; second model family **RT-DETR** (experiment E4).
- Price of the lowest tier: 1 GPU = 15 CR/hour. The largest described configuration: 48 GPU = 1,680 CR/hour, so the per-GPU price is not constant across tiers (35 vs 15 CR/hour) and must not be extrapolated. Priority queue: +50% cost (GUIDE).
- Smoke tests use a small dataset and a nano model, **never priority**.
- Cost of one run on the lowest tier: `hours × 15 CR` (× 1.5 with priority). The duration of a YOLO11n run on this dataset is unknown and is measured in the M7 smoke test. Budget: about 40 runs with three seeds, about 18 with one (SPEC §8).

## Inference API

| fact | status |
|---|---|
| Trained models expose an authenticated inference API; the model detail page has an API tab with Python, JavaScript and cURL snippets | GUIDE |
| Authentication: Bearer token | GUIDE |
| Documented parameters: model/version selection, confidence threshold, IoU threshold, JPEG quality | GUIDE |
| `max_det` | **UNKNOWN**: do not code against it until the official snippet has been seen |
| Lowest allowed confidence threshold (can it reach 0.001?) | UNKNOWN: read it in the API tab |
| Response schema (box format, class names, score field) | UNKNOWN: take it from the official snippet |
| Rate limits and quotas | UNKNOWN |

Consequences for `EvrenProvider`:

- A JPEG-quality parameter implies images are sent as JPEG. Send the highest allowed quality, and let the `LocalProvider` parity check (SPEC §5) prove that the encoding does not change results.
- If the confidence threshold cannot go low enough, EVREN numbers are operating-point metrics only, and headline mAP comes from `LocalProvider` on exported weights (SPEC §11, R5).
- Secrets live in `.env` (`EVREN_API_KEY`, `EVREN_MODEL_ENDPOINT`) and are never committed.

## Automation boundary

Only the inference API is confirmed. **Do not** invent or code against dataset-create, dataset-upload, dataset-version, training-create or experiment endpoints: a UI feature is not an API. Automation is added only after an official endpoint has been seen. Until then those actions are done in the EVREN UI (M6, M7) and each is recorded in a run record.
