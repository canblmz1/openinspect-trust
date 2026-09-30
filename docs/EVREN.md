# EVREN: facts, unknowns and how each gets verified

Source of the facts below: the maintainer's statement of 2026-09-30, taken from the EVREN user guide. They could not be verified independently: EVREN's public explore page is a JavaScript application that returned no documentation to an automated fetch. Where a fact decides a result, the plan says how it gets verified.

Status codes: **GUIDE** = stated in the EVREN user guide (per the maintainer) · **UNKNOWN** = not verified · **EXPERIMENT** = will be verified by a small test.

## Datasets

| fact | status | consequence |
|---|---|---|
| Modalities: VISION, AUDIO, NLP, MULTIMODAL | GUIDE | this project uses VISION |
| Import formats include YOLO Detection, YOLO Segmentation, YOLO OBB, COCO JSON, Pascal VOC, CreateML, Label Studio, CSV, classification folders | GUIDE | export YOLO Detection first, COCO JSON second |
| ZIP import limit: 30 GB | GUIDE | every v0.1 archive is far smaller |
| Each item can be assigned to train, val or test manually | GUIDE | the local split file can be applied item by item if folders are not kept |
| Auto Split is a separate, optional feature | GUIDE | never use it on a source-held-out dataset |
| Does an imported ZIP keep its own train/val/test folders? | **UNKNOWN → EXPERIMENT** | first small import in M6: compare EVREN's per-split item names and counts with the local split file |

**Rule.** The local manifest (`manifests/splits/*`) is the canonical split. The source-held-out guarantee is not entrusted to EVREN until the experiment passes, and it is re-checked after every import.

## Training

- Architectures: YOLO26, YOLO11, YOLOv10, YOLOv9, YOLOv8, RT-DETR. Tasks: detection, segmentation, OBB, pose, classification (GUIDE).
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
