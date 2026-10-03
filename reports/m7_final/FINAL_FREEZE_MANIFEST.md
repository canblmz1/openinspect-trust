# Final freeze manifest: OpenInspect-Trust M7

- **Date:** 2026-10-03 (generated 2026-10-03 17:43)
- **Git base commit:** `6c1fb955d0fc2efc602ebb78b5fd20927123b160` (Thu Oct 1 22:50:25 2026 +0300). The frozen files below are committed on top of this base in the publication-freeze commits, tagged `research-m7-final` (annotated).
- **Dataset release:** OpenInspect-Trust v0.1 (4,420 images, 5,297 boxes); manifest hashes below.
- **Experiment status:** **FROZEN — NO FURTHER TRAINING PLANNED**
- **Human validation status:** **NOT PERFORMED**
- **AI visual adjudication status:** **COMPLETED** (300 M3 candidate pairs; 90 probe–mate and control pairs, two blinded AI passes and adjudication)
- **Scientific verdict:** B — WORKSHOP / PREPRINT READY
- **Models:** 31 platform jobs; 25 checkpoints used (SHA-256 in `public/CHECKPOINT_MANIFEST_PUBLIC.csv`; one effective-configuration hash); Ultralytics 8.3.0 evaluation.
- **Verification:** the final analysis was re-run from the sanitised scripts and reproduced every statistic (`PUBLICATION_CONSISTENCY_AUDIT.md`).

## Dataset release and design inputs

| file | SHA-256 |
|---|---|
| `manifests/releases/v0.1/release.json` | `346587967a068e0db85b21bb5648527b496403a39e9408316fa500e3548087d5` |
| `manifests/releases/v0.1/items.parquet` | `aefa4792ff2cb86b7c219bc638e3d35eaed26fd40ee6cdd806f1f02df9e9dd9f` |
| `manifests/releases/v0.1/annotations.parquet` | `279052b2351277fadac19d2497264ae556507bc77188e5cf597e7b414b5c93ff` |
| `manifests/experiments/v0.1/B-natural-dspcbsd-plus__seed0.csv` | `718294cf6bc4181b85f81b3f3f0d585c393705eae580074b6e562796fda8dd04` |
| `manifests/experiments/v0.1/B-natural-pcb-defect__seed0.csv` | `d75ed433cd095c09e602844eee18db4e6b736e0ecbe949b825550dae9cf39c6c` |
| `manifests/experiments/v0.1/B-natural-pcb-ind__seed0.csv` | `0933e368f865fb80f241e6b43723ce85d228b001526954be74e777d98654b0ce` |
| `manifests/experiments/v0.1/C-design0-roles.csv` | `a39a5841df34e3e04755984e86c142722435536e368944d1b7994a297b1bbbe6` |
| `manifests/experiments/v0.1/C-design1-roles.csv` | `b2d14030f1123d819cb09db610eb0ca225da6c1b677a98c5c041c99c18c8759d` |
| `manifests/experiments/v0.1/C-design2-roles.csv` | `b12a74d80906d64c4ba2962af036617572a1f736800606c79af2ba2fe5686036` |
| `manifests/experiments/v0.1/C0__design0.csv` | `eee6f785a7a6e73953c703feda77dcc04f69b63cbdecce5b6833448e4f816ee0` |
| `manifests/experiments/v0.1/C0__design1.csv` | `397f661472888d012ceb73ffc0b10b91bfe8749d0a61210a7bcf71a0fc20a47b` |
| `manifests/experiments/v0.1/C0__design2.csv` | `305c8a77f1c16f467809ca543a7e755911632a02c4446a54dbade8d5c3388939` |
| `manifests/experiments/v0.1/C1__design0.csv` | `7b25fb3576b49d27d630fc53d72edc7fa0d6bbc3fd1e2aa3af5edfe02ac49222` |
| `manifests/experiments/v0.1/C1__design1.csv` | `38f26388511816a0c85da448d2c3a31b822349d947563373715fc79dd4cae6c5` |
| `manifests/experiments/v0.1/C1__design2.csv` | `7f46026a84d4a3f3f47b1d29bf49409764ce44fcecce576e72924199f7862b35` |

## Analysis scripts

| file | SHA-256 |
|---|---|
| `reports/m7_final/scripts/final_analysis.py` | `4a3f3808e7114957f10ddaed8e25f2c1282c1becbfd9f3c52421985fae48213d` |
| `reports/m7_final/scripts/lib.py` | `fc2bb46b4a2c9a9c093ca3c5fc2fffc3dd2a9def8da621dec246914429303e88` |
| `reports/m7_final/scripts/make_freeze_manifest.py` | `dfc3c60c20fa73e92922bfdba0488160a322659d9cad453ee6ca86a8f9e1920e` |
| `scripts/m7_evaluate.py` | `b710082286acf2765949e8969d689b771ae4059cfcaeebcee9febb0ac9694ce1` |
| `paper/scripts/audit_numbers.py` | `b61d90c261f9a73e11facafcea29ee80bdebca49fdf71e167d64d876b2a27846` |
| `paper/scripts/check_latex.py` | `95ed36a33e72177b76119573cc00e59cbcc34ab0b89659cc2cf3d7ccc14da745` |
| `paper/scripts/make_figures.py` | `5a57c56c9c823dc3608b0e9adfd0afcb9bd73a9d1eb790a976b01f951a6db338` |
| `paper/scripts/make_submission.py` | `62b5fd593c62d13b6ae463c382a90b55718b0aab3ac6acc602db7bfc8a3522d4` |
| `paper/scripts/make_tables.py` | `5db24d46eded4089363fe5c0923e85da993b0f996bafcaede14266332ddf6624` |
| `paper/scripts/md_to_latex.py` | `d12b5518cfa2c272c809527fed9a5a887d9660c8798ff8ea34d1fb73057e2c42` |
| `paper/scripts/split_sections.py` | `0af770950f04acfe0e38c341c7176958b725f0a2161c647f4e1252029440764c` |

## Final result files

| file | SHA-256 |
|---|---|
| `reports/m7_final/FINAL_DOSE_RESPONSE.csv` | `b2932c7af019b32b97fcf787848a3c2ea4047f752d02d77a949d46110e1025a8` |
| `reports/m7_final/FINAL_PLACEBO_RESULTS.csv` | `6ddc6be028fc9faa62f48c8ec8d55ce4a3975199adb14dfe4d6c169cb762a9d5` |
| `reports/m7_final/FINAL_REPLICATION_TABLE.csv` | `2281eadf5c13d2e18e2d13e8aca7198bf9478b033dc243410d5a56f79ca0f2c3` |
| `reports/m7_final/FINAL_SEED_AWARE_STATS.csv` | `12a8be10fb1f612cdc656c11cfea822f750727e43bc5ae91a363dc8ee78b74df` |
| `reports/m7_final/replication_summary.csv` | `7c2514daf63d0db2191db4279d52ea96a2fbb05e6e7e39a79888a036d735f226` |
| `reports/m7_final/probe_link_split.csv` | `d03ef676950f39c9f06f21256372abc13a8dc4afd46eb97e1627a6049dcff811` |
| `reports/m7_final/visual_category_gain_D0.csv` | `6399ed0ea35f6c1e0d139e590eeb7fc483a4a94d9fbfcb889b05fecd6f6f4021` |
| `reports/m7_final/analysis_meta.json` | `dffcff656d3a5044aed504ab1f21316985b755dc1c00cf48022748d075b60093` |
| `reports/m7_final/public/CHECKPOINT_MANIFEST_PUBLIC.csv` | `3328eb32fad7112eac2bbe9221d32456f2f867486cc6e85de2069254ca7ef764` |
| `reports/m7_final/public/RUN_INVENTORY_PUBLIC.csv` | `26bf732107277e3b9ae8f7e32508a56700fedeb7826b65351d1bcdfa42495ca5` |
| `reports/m7_independent_review/AI_PM_ADJUDICATED.csv` | `e84e83bb6ddecb32590cd6bcf306ddbc34e76d64f3848c892746eb82df3f7b96` |
| `reports/m7_independent_review/data/exposure.csv` | `986968c7eba00e2d13958f650d480733f6a2fbb25f7196240cbb898eacbeee2d` |

## Figures

| file | SHA-256 |
|---|---|
| `paper/figures/fig1_exposure_gain.png` | `e634aa9663fb538d9fd5ffab0eec3e6bb0689a2f69b3a00994dbd0f50faed037` |
| `paper/figures/fig2_source_shift.png` | `992eb9167e035998bd4e903e913aa864cef303f84e34200324bc7941e17db6ab` |
| `paper/figures/fig3_replication.png` | `34d8772a996bbda6e3991cc8406fe53f8bab753a07b5d9af6e0bd115da664685` |

## Paper files

| file | SHA-256 |
|---|---|
| `paper/manuscript.md` | `6d55ff42deb9889f4d238748a9dc3e1c117d96404998b672c871963c84a27684` |
| `paper/arxiv/main.tex` | `8450f57dfb13546b0fa25f5d24fe1a5ddb77626a48a7ec2148141ed55916b453` |
| `paper/arxiv/main_anonymous.tex` | `fbf9d66aafbbaa94f1f18777daf00f1e67b80125796d774a818964f6f04dbafa` |
| `paper/arxiv/references.bib` | `b00daaae893a122acdc79fd86bca3f7ec8c2adca6e4d992ca5836b3bf113eda7` |
| `paper/arxiv/main.pdf` | `7678a9a6d97359ab375986baaeeb325c908a1e1a0bf7fb51f28f03a59fac93f7` |
| `paper/arxiv/main_anonymous.pdf` | `05abd5bd6e637f1cc353a2671c2768c28f116e009c8d986eea3eb3cacaa71636` |
| `paper/arxiv/ARXIV_UPLOAD_MANIFEST.txt` | `d8487f90752d8b89eb9893fb153fff3840680d6cc89e7433795966a9d2f6701d` |
| `paper/tables/tableS1_seed_level.md` | `71810f46b9a42cc67c79c92f36cf2fb992582fa800d69e4b3d699edadaabb636` |
| `paper/tables/tableS2_seed_aware.md` | `34e033cd072d471a34475193e46ff132b03d44a9ea26791f21970115966ab09c` |
| `paper/tables/tableS3_placebo.md` | `138f2cd9d16999886250f4c289a7cc029ad15f0b2822ad07f4ba877123a0ba42` |
| `paper/tables/tableS4_exposure_strata.md` | `796bb7cbee4d4122dc28583d6bb24aa2ca8504cc20692d32571eebf88142206b` |
| `paper/tables/tableS5_source_shift.md` | `17d0ea6aa9e681568ddc4292eaaf8d13769a1e4e3e69688ca4f0ba18aae9c17b` |
| `paper/tables/tableS6_visual_adjudication.md` | `854a1b60f992dc9972cd3192262e65d61bd013aff73c34f8b456cb8a0eb5280f` |
| `paper/tables/tableS7_prior_art.md` | `fa6e0f64c5957148d4af3c455ac4d4ef347ddec5d0ef08279e806e480319af7d` |
| `paper/tables/tableS8_probe_link_split.md` | `0f4a77be79a282835029d2fb22a09982d32134d1afbafdfe3aa5a1590ca04548` |
| `paper/submission/ABSTRACT.txt` | `e4f92d647e5bb49512334acd770573dd57ad0fda95f719b5726ef96af0a1011c` |
| `paper/submission/ANONYMIZED_MANUSCRIPT.md` | `6db198c107194579e43768ca1d462563c328e7a43caf4568483e78aa26909bd3` |
| `paper/submission/AUTHOR_CHECKLIST.md` | `a636066449a39a81de9e1683f0ff80eb30cfc9bb625909f2cf987fb89abc5a34` |
| `paper/submission/DATA_AVAILABILITY.md` | `494a4e659c498bc33ee973ca0ad8fe7c1b44178bcdc7edc32a0580e1c61a731b` |
| `paper/submission/ETHICS_AND_LIMITATIONS.md` | `ae1c7f65d60cb6a39d0cf3f2c79291418f3587be9a42759943bd1a70cf879854` |
| `paper/submission/KEYWORDS.txt` | `6c7f89525853137be167d75819330fdefb36211165c929e8339a686ef73d91ea` |
| `paper/submission/NON_ANONYMIZED_MANUSCRIPT.md` | `92a7754a0fc83d4b9c8de11c4d91a75d3c2a9a5a285e0a32e7911a4e88aa93e4` |
| `paper/submission/REPRODUCIBILITY_STATEMENT.md` | `f82e0da16c68ef0e48693c527e2862ba359ffe925180f912cca75507682c85a4` |
| `paper/submission/SUBMISSION_READY.md` | `012d7db96c00bbe22f1236eb346ba8739e2f7fd8c032487f57a7fcc0695b0aa7` |
| `paper/submission/TITLE.txt` | `1b00c6b8a6eaa3d3c006fce893abc447c864bb5a9e2b768398ec0d1c82549b05` |

## Final reports

| file | SHA-256 |
|---|---|
| `reports/m7_final/FINAL_D1_DIAGNOSIS.md` | `5e47ee7172e2acdf4dc0d6dcd5f8c25d9df014f335874289cc293ce5baf62709` |
| `reports/m7_final/FINAL_EXECUTIVE_SUMMARY_TR.md` | `afaf3f70acf96451667f4acce984132189312db8aee9af10eb36d04d20500ccd` |
| `reports/m7_final/FINAL_GROUP_EXPOSURE_RESULT.md` | `35b17c3820ca4b010b559d5defa65d15fe23de42cf9cd9a5b121a0b8e7531053` |
| `reports/m7_final/FINAL_SAFE_CLAIMS.md` | `20fb50a26cc919312e249ba846401682ae60d70fc2e1375f4582d31f262e1f5d` |
| `reports/m7_final/FINAL_SCIENTIFIC_VERDICT.md` | `c0de0aad26b428ff170edf6e2dad97178400b67f17b929806794c9462ba3ce5c` |
| `reports/m7_final/FINAL_SOURCE_SHIFT_RESULT.md` | `9a80c412749b72f883d686a3cdae5a9e1ef0ba34c7dc5fd1618ec5903bb84b7f` |
| `reports/m7_final/PUBLICATION_CONSISTENCY_AUDIT.md` | `78abb3aea1b4e48f140c606721f81f1723c2ace951bee7f8c81542448cd02ca9` |
| `reports/m7_final/PUBLICATION_RELEASE_CHECKLIST.md` | `2d1fb69666f3e8285d976cde896ef8a782c2f82b7590fd365fa1e258215ae775` |
| `paper/CITATION_AUDIT.md` | `efe7c2a5ca680acfa2e31d563d35300fad235c0a9199917f7e74a277705c1a8d` |
| `paper/FINAL_REVIEWER_2_AUDIT.md` | `4f32c7c695ab893b8c97723a3251e28d081d858875e04bf46d3d1536eaceed38` |

This manifest does not hash itself.
