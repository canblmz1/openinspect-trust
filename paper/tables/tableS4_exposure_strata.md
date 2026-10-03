# Table S4. C0 − C1 mAP50-95 by exposure stratum (per-seed values; strata fixed before the last three seed pairs were trained)

| design | representation | stratum | test images | per seed | mean |
|---|---|---|---|---|---|
| D0 | DINOv2-small | control | 213 | −0.56, −1.40, +1.46 | −0.17 |
| D0 | DINOv2-small | probe delta<0.02 | 69 | +2.33, +2.62, −0.84 | +1.37 |
| D0 | DINOv2-small | probe 0.02-0.08 | 61 | +0.70, +5.58, −1.54 | +1.58 |
| D0 | DINOv2-small | probe delta>0.08 | 64 | +6.21, +7.91, +6.28 | +6.80 |
| D0 | DINOv2-base | control | 213 | −0.56, −1.40, +1.46 | −0.17 |
| D0 | DINOv2-base | probe delta<0.02 | 95 | +3.05, +4.08, +1.20 | +2.77 |
| D0 | DINOv2-base | probe 0.02-0.08 | 53 | +3.97, +6.17, +0.63 | +3.59 |
| D0 | DINOv2-base | probe delta>0.08 | 46 | +5.96, +7.93, +6.02 | +6.64 |
| D1 | DINOv2-small | control | 215 | +3.09, −0.75, −1.68 | +0.22 |
| D1 | DINOv2-small | probe delta<0.02 | 82 | +0.73, −0.73, −2.61 | −0.87 |
| D1 | DINOv2-small | probe 0.02-0.08 | 61 | +3.36, +7.76, +2.46 | +4.53 |
| D1 | DINOv2-small | probe delta>0.08 | 50 | +7.43, +10.01, +5.71 | +7.72 |
| D1 | DINOv2-base | control | 215 | +3.09, −0.75, −1.68 | +0.22 |
| D1 | DINOv2-base | probe delta<0.02 | 87 | +0.79, +2.17, −0.40 | +0.86 |
| D1 | DINOv2-base | probe 0.02-0.08 | 64 | +0.21, +4.70, +0.80 | +1.90 |
| D1 | DINOv2-base | probe delta>0.08 | 42 | +13.65, +11.63, +5.94 | +10.41 |
| D2 | DINOv2-small | control | 215 | +0.02, +1.68 | +0.85 |
| D2 | DINOv2-small | probe delta<0.02 | 75 | +1.64, −3.11 | −0.74 |
| D2 | DINOv2-small | probe 0.02-0.08 | 60 | +3.55, −2.62 | +0.47 |
| D2 | DINOv2-small | probe delta>0.08 | 59 | +6.69, +4.52 | +5.61 |
| D2 | DINOv2-base | control | 215 | +0.02, +1.68 | +0.85 |
| D2 | DINOv2-base | probe delta<0.02 | 88 | +3.88, +0.40 | +2.14 |
| D2 | DINOv2-base | probe 0.02-0.08 | 62 | +3.50, +1.14 | +2.32 |
| D2 | DINOv2-base | probe delta>0.08 | 44 | +8.46, +6.30 | +7.38 |

Continuous: Spearman ρ between Δ and per-image recall gain (probes), 95% cluster-bootstrap interval

| design | representation | ρ | 95% CI |
|---|---|---|---|
| D0 | DINOv2-small | 0.15 | 0.03 to 0.29 |
| D0 | DINOv2-base | 0.11 | -0.03 to 0.27 |
| D1 | DINOv2-small | 0.12 | -0.01 to 0.27 |
| D1 | DINOv2-base | 0.13 | -0.01 to 0.29 |
| D2 | DINOv2-small | 0.08 | -0.07 to 0.24 |
| D2 | DINOv2-base | 0.11 | -0.04 to 0.25 |
