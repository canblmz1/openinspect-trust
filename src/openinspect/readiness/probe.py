"""Can the source of an image be predicted trivially? (M5.5, P1-5)

The purpose is not to build a good source classifier; it is to learn whether the benchmark carries
obvious source signatures. If simple features (image size, file format, box statistics, colour
statistics) identify the source almost perfectly, then the source-held-out split B measures a
large domain shift, not only a subtle generalization gap. That does not invalidate B; it changes
how it is read.

Two simple models, both written here in NumPy so that the result depends on no extra library:
multinomial logistic regression on standardized features, and a decision tree of depth three
(Gini). Cross-validation is stratified by source (primary) and, as a check, group-aware (no A1
constraint group is split across folds).
"""

from __future__ import annotations

import hashlib
import math
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from numpy.typing import NDArray
from PIL import Image

from openinspect.provenance.schema import StrictModel
from openinspect.release.pool import Candidate

FEATURE_SETS: dict[str, tuple[str, ...]] = {
    "metadata": ("width", "height", "aspect", "log_pixels", "is_png"),
    "boxes": (
        "n_boxes",
        "mean_rel_side",
        "min_rel_side",
        "max_rel_side",
        "mean_cx",
        "mean_cy",
        "std_cx",
        "std_cy",
    ),
    "pixels": ("mean_r", "mean_g", "mean_b", "std_r", "std_g", "std_b", "grad_mean"),
}
FEATURE_SETS["boxes+pixels"] = FEATURE_SETS["boxes"] + FEATURE_SETS["pixels"]
FEATURE_SETS["all"] = FEATURE_SETS["metadata"] + FEATURE_SETS["boxes+pixels"]
FEATURES = FEATURE_SETS["all"]
FOLDS = 5
TREE_DEPTH = 3
MIN_LEAF = 5


def box_features(item: Candidate) -> dict[str, float]:
    sides, cx, cy = [], [], []
    area = item.width * item.height
    for b in item.boxes:
        x0, y0, x1, y1 = b.bbox
        sides.append(math.sqrt(max(x1 - x0, 0.0) * max(y1 - y0, 0.0) / area))
        cx.append((x0 + x1) / 2 / item.width)
        cy.append((y0 + y1) / 2 / item.height)
    return {
        "width": float(item.width),
        "height": float(item.height),
        "aspect": item.width / item.height,
        "log_pixels": math.log(area),
        "is_png": 1.0 if item.extension == ".png" else 0.0,
        "n_boxes": float(len(item.boxes)),
        "mean_rel_side": float(np.mean(sides)),
        "min_rel_side": float(np.min(sides)),
        "max_rel_side": float(np.max(sides)),
        "mean_cx": float(np.mean(cx)),
        "mean_cy": float(np.mean(cy)),
        "std_cx": float(np.std(cx)),
        "std_cy": float(np.std(cy)),
    }


def pixel_features(path: Path) -> dict[str, float]:
    """Colour statistics of the whole image and the mean gradient at a fixed 128x128 scale."""
    with Image.open(path) as opened:
        rgb = np.asarray(opened.convert("RGB"), dtype=np.float64) / 255.0
        small = np.asarray(
            opened.convert("L").resize((128, 128), Image.Resampling.BICUBIC), dtype=np.float64
        )
    gx = np.abs(np.diff(small, axis=1)).mean()
    gy = np.abs(np.diff(small, axis=0)).mean()
    return {
        "mean_r": float(rgb[..., 0].mean()),
        "mean_g": float(rgb[..., 1].mean()),
        "mean_b": float(rgb[..., 2].mean()),
        "std_r": float(rgb[..., 0].std()),
        "std_g": float(rgb[..., 1].std()),
        "std_b": float(rgb[..., 2].std()),
        "grad_mean": float((gx + gy) / 2 / 255.0),
    }


# --------------------------------------------------------------------------------- models


def _standardize(
    train: NDArray[np.float64], test: NDArray[np.float64]
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    mean = train.mean(axis=0)
    std = train.std(axis=0)
    std[std == 0] = 1.0
    return (train - mean) / std, (test - mean) / std


def fit_logistic(
    x: NDArray[np.float64],
    y: NDArray[np.int64],
    classes: int,
    *,
    l2: float = 1e-3,
    steps: int = 800,
) -> NDArray[np.float64]:
    """Multinomial logistic regression by full-batch gradient descent (deterministic)."""
    xb = np.hstack([x, np.ones((len(x), 1))])
    target = np.eye(classes)[y]
    weights = np.zeros((xb.shape[1], classes))
    rate = 0.5
    for _ in range(steps):
        logits = xb @ weights
        logits -= logits.max(axis=1, keepdims=True)
        prob = np.exp(logits)
        prob /= prob.sum(axis=1, keepdims=True)
        grad = xb.T @ (prob - target) / len(xb)
        grad[:-1] += l2 * weights[:-1]
        weights -= rate * grad
    return weights


def predict_logistic(weights: NDArray[np.float64], x: NDArray[np.float64]) -> NDArray[np.int64]:
    xb = np.hstack([x, np.ones((len(x), 1))])
    return np.asarray((xb @ weights).argmax(axis=1), dtype=np.int64)


@dataclass(frozen=True)
class Node:
    label: int
    feature: int = -1
    threshold: float = 0.0
    left: Node | None = None
    right: Node | None = None


def _gini(counts: NDArray[np.float64]) -> NDArray[np.float64]:
    total = counts.sum(axis=-1, keepdims=True)
    share = np.divide(counts, total, out=np.zeros_like(counts), where=total > 0)
    return np.asarray(1.0 - (share**2).sum(axis=-1), dtype=np.float64)


def fit_tree(
    x: NDArray[np.float64], y: NDArray[np.int64], classes: int, depth: int = TREE_DEPTH
) -> Node:
    counts = np.bincount(y, minlength=classes)
    label = int(counts.argmax())
    if depth == 0 or len(y) < 2 * MIN_LEAF or counts.max() == len(y):
        return Node(label)
    best: tuple[float, int, float] | None = None
    parent = float(_gini(counts.astype(np.float64)[None, :])[0])
    for f in range(x.shape[1]):
        order = np.argsort(x[:, f], kind="stable")
        values = x[order, f]
        onehot = np.eye(classes)[y[order]]
        left = np.cumsum(onehot, axis=0)[:-1]
        right = counts - left
        n_left = np.arange(1, len(y))
        valid = (values[1:] > values[:-1]) & (n_left >= MIN_LEAF) & (len(y) - n_left >= MIN_LEAF)
        if not valid.any():
            continue
        score = (n_left * _gini(left) + (len(y) - n_left) * _gini(right)) / len(y)
        score = np.where(valid, score, np.inf)
        k = int(score.argmin())
        if score[k] < parent - 1e-12 and (best is None or score[k] < best[0] - 1e-12):
            best = (float(score[k]), f, float((values[k] + values[k + 1]) / 2))
    if best is None:
        return Node(label)
    _, feature, threshold = best
    mask = x[:, feature] <= threshold
    return Node(
        label,
        feature,
        threshold,
        fit_tree(x[mask], y[mask], classes, depth - 1),
        fit_tree(x[~mask], y[~mask], classes, depth - 1),
    )


def predict_tree(node: Node, x: NDArray[np.float64]) -> NDArray[np.int64]:
    out = np.empty(len(x), dtype=np.int64)
    for i, row in enumerate(x):
        current = node
        while current.left is not None and current.right is not None:
            current = current.left if row[current.feature] <= current.threshold else current.right
        out[i] = current.label
    return out


def describe_tree(
    node: Node, names: Sequence[str], classes: Sequence[str], indent: str = ""
) -> list[str]:
    if node.left is None or node.right is None:
        return [f"{indent}-> {classes[node.label]}"]
    return [
        f"{indent}if {names[node.feature]} <= {node.threshold:.4g}:",
        *describe_tree(node.left, names, classes, indent + "  "),
        f"{indent}else:",
        *describe_tree(node.right, names, classes, indent + "  "),
    ]


# --------------------------------------------------------------------------------- folds


def _hash(*parts: object) -> str:
    return hashlib.sha256(":".join(str(p) for p in parts).encode("utf-8")).hexdigest()


def stratified_folds(ids: Sequence[str], labels: Sequence[int], k: int, seed: int) -> list[int]:
    """Fold of every item: within each class, items in seeded order dealt to folds in turn."""
    fold = [0] * len(ids)
    for cls in sorted(set(labels)):
        members = sorted(
            (i for i, c in enumerate(labels) if c == cls), key=lambda i: _hash(seed, ids[i])
        )
        for rank, i in enumerate(members):
            fold[i] = rank % k
    return fold


def group_folds(groups: Sequence[str], labels: Sequence[int], k: int, seed: int) -> list[int]:
    """Whole groups to folds, largest first, into the fold with the fewest items of their class."""
    members: dict[str, list[int]] = {}
    for i, g in enumerate(groups):
        members.setdefault(g, []).append(i)
    filled: list[Counter[int]] = [Counter() for _ in range(k)]
    fold = [0] * len(groups)
    for g in sorted(members, key=lambda g: (-len(members[g]), _hash(seed, g))):
        main = Counter(labels[i] for i in members[g]).most_common(1)[0][0]
        target = min(range(k), key=lambda f: (filled[f][main], sum(filled[f].values()), f))
        for i in members[g]:
            fold[i] = target
            filled[target][labels[i]] += 1
    return fold


# ------------------------------------------------------------------------------- results


class ProbeScore(StrictModel):
    features: str
    model: str
    folds: str
    accuracy: float
    balanced_accuracy: float
    recall: dict[str, float]  # source -> recall
    confusion: dict[str, dict[str, int]]  # true source -> predicted source -> items


class ProbeResult(StrictModel):
    items: int
    sources: dict[str, int]
    majority_baseline: float
    scores: list[ProbeScore]
    trees: dict[str, list[str]]  # feature set -> the tree fitted on all items
    features: dict[str, list[str]]
    reading: str


def _score(
    truth: NDArray[np.int64],
    pred: NDArray[np.int64],
    classes: Sequence[str],
    features: str,
    model: str,
    folds: str,
) -> ProbeScore:
    recall = {
        name: float(((pred == k) & (truth == k)).sum() / max((truth == k).sum(), 1))
        for k, name in enumerate(classes)
    }
    confusion = {
        name: {other: int(((truth == k) & (pred == m)).sum()) for m, other in enumerate(classes)}
        for k, name in enumerate(classes)
    }
    return ProbeScore(
        features=features,
        model=model,
        folds=folds,
        accuracy=round(float((truth == pred).mean()), 6),
        balanced_accuracy=round(float(np.mean(list(recall.values()))), 6),
        recall={k: round(v, 6) for k, v in recall.items()},
        confusion=confusion,
    )


def run_probe(
    table: Mapping[str, Sequence[float]],
    sources: Sequence[str],
    ids: Sequence[str],
    groups: Sequence[str],
    *,
    seed: int = 0,
) -> ProbeResult:
    classes = sorted(set(sources))
    y = np.array([classes.index(s) for s in sources], dtype=np.int64)
    fold_sets = {
        "stratified": np.array(stratified_folds(ids, list(y), FOLDS, seed), dtype=np.int64),
        "group-aware": np.array(group_folds(groups, list(y), FOLDS, seed), dtype=np.int64),
    }
    scores: list[ProbeScore] = []
    trees: dict[str, list[str]] = {}
    for name, columns in FEATURE_SETS.items():
        x = np.array(
            [[float(table[c][i]) for c in columns] for i in range(len(ids))], dtype=np.float64
        )
        trees[name] = describe_tree(fit_tree(x, y, len(classes)), columns, classes)
        for fold_name, fold in fold_sets.items():
            pred_lr = np.empty(len(y), dtype=np.int64)
            pred_tree = np.empty(len(y), dtype=np.int64)
            for f in range(FOLDS):
                test = fold == f
                train = ~test
                if not test.any() or len(set(y[train].tolist())) < 2:
                    pred_lr[test] = pred_tree[test] = Counter(y[train].tolist()).most_common(1)[0][
                        0
                    ]
                    continue
                xs_train, xs_test = _standardize(x[train], x[test])
                weights = fit_logistic(xs_train, y[train], len(classes))
                pred_lr[test] = predict_logistic(weights, xs_test)
                pred_tree[test] = predict_tree(fit_tree(x[train], y[train], len(classes)), x[test])
            scores.append(_score(y, pred_lr, classes, name, "logistic regression", fold_name))
            scores.append(
                _score(
                    y, pred_tree, classes, name, f"decision tree (depth {TREE_DEPTH})", fold_name
                )
            )
    counts = Counter(sources)
    best = max((s for s in scores if s.folds == "stratified"), key=lambda s: s.balanced_accuracy)
    content = max(
        (s for s in scores if s.folds == "stratified" and s.features == "boxes+pixels"),
        key=lambda s: s.balanced_accuracy,
    )
    reading = (
        f"The best simple model reaches {best.balanced_accuracy:.1%} balanced accuracy "
        f"({best.model}, {best.features} features); without file metadata (boxes and pixels only) "
        f"{content.balanced_accuracy:.1%}. The majority baseline is {max(counts.values()) / len(sources):.1%}."
    )
    return ProbeResult(
        items=len(sources),
        sources=dict(sorted(counts.items())),
        majority_baseline=round(max(counts.values()) / len(sources), 6),
        scores=scores,
        trees=trees,
        features={k: list(v) for k, v in FEATURE_SETS.items()},
        reading=reading,
    )
