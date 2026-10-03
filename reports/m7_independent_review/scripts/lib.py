# Provenance copy of an analysis script from the 2026-10-03 independent review. Local paths are redacted
# (<REPO>, <SCRATCH>, <LOCAL>); the maintained, runnable versions are in reports/m7_final/scripts/.
"""Independent mAP-on-subset machinery for the review (own implementation of COCO-101 AP)."""
from pathlib import Path
import numpy as np
import pandas as pd

EVAL = Path("C:/data/openinspect/m7/eval")
REPO = Path("<REPO>")
X101 = np.linspace(0, 1, 101)


class Model:
    """Per-image detections of one model on one population, indexed for fast subset mAP."""

    def __init__(self, name):
        det = pd.read_parquet(EVAL / f"{name}.parquet")
        tgt = pd.read_parquet(EVAL / f"{name}.targets.parquet")
        imgs = pd.read_parquet(EVAL / f"{name}.images.parquet").image.tolist()
        self.images = imgs
        self.idx = {k: i for i, k in enumerate(imgs)}
        o = np.argsort(-det.conf.values, kind="stable")
        det = det.iloc[o]
        self.d_img = det.image.map(self.idx).values
        self.d_cls = det.cls.values.astype(int)
        bits = det.tp_bits.values.astype(np.int64)
        self.d_tp = ((bits[:, None] >> np.arange(10)) & 1).astype(np.float64)
        self.d_conf = det.conf.values
        self.t_img = tgt.image.map(self.idx).values
        self.t_cls = tgt.cls.values.astype(int)

    def counts(self, w):
        """w: per-image integer weights (bootstrap multiplicities; 0/1 for subsets)."""
        return w[self.d_img], w[self.t_img]

    def map(self, w, per_class=False):
        dw, tw = self.counts(np.asarray(w, dtype=np.float64))
        classes = np.unique(self.t_cls[tw > 0])
        aps = []
        for c in classes:
            nt = tw[self.t_cls == c].sum()
            sel = (self.d_cls == c) & (dw > 0)
            if not sel.any():
                aps.append(np.zeros(10)); continue
            wt = dw[sel][:, None]
            tpc = np.cumsum(self.d_tp[sel] * wt, axis=0)
            fpc = np.cumsum((1 - self.d_tp[sel]) * wt, axis=0)
            rec = tpc / (nt + 1e-16)
            prec = tpc / (tpc + fpc)
            ap = np.empty(10)
            for j in range(10):
                mrec = np.concatenate(([0.0], rec[:, j], [1.0]))
                mpre = np.concatenate(([1.0], prec[:, j], [0.0]))
                mpre = np.flip(np.maximum.accumulate(np.flip(mpre)))
                ap[j] = np.trapezoid(np.interp(X101, mrec, mpre), X101)
            aps.append(ap)
        aps = np.array(aps)
        if per_class:
            return dict(zip(classes.tolist(), aps.mean(1)))
        return float(aps.mean()) if len(aps) else np.nan

    def mask(self, ids):
        w = np.zeros(len(self.images))
        for i in ids:
            w[self.idx[i]] = 1
        return w

    def per_image_recall(self, conf=0.25):
        """Per-image share of GT boxes recovered (TP at conf>=thr), averaged over the 10 IoU thresholds."""
        keep = self.d_conf >= conf
        tp = np.zeros((len(self.images), 10))
        np.add.at(tp, self.d_img[keep], self.d_tp[keep])
        nt = np.bincount(self.t_img, minlength=len(self.images))
        fp = np.bincount(self.d_img[keep], weights=(1 - self.d_tp[keep, 0]), minlength=len(self.images))
        return pd.DataFrame({"recall5095": tp.mean(1) / np.maximum(nt, 1), "fp50": fp, "n_gt": nt}, index=self.images)
