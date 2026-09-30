"""A local HTML contact sheet of the review queue, with both images of a pair side by side (M3I).

The page embeds small JPEG thumbnails of dataset images, so it is written to the data directory and
never committed. A reviewer records decisions in ``review-candidates.csv`` (``human_decision``,
``human_notes``); the page only shows what the machine measured and suggests. The metadata keys it
shows are the sources' own proxy keys, not ground truth.
"""

from __future__ import annotations

import base64
import io
import os
import random
from collections.abc import Mapping, Sequence
from html import escape
from pathlib import Path

from openinspect.dedup.audit_models import Audit
from openinspect.dedup.features import DecodeError, decode_rgb, read_verified
from openinspect.dedup.inventory import ImageItem

THUMB = 224
PACK = "review-pack.html"
DECISIONS = ("same_scene", "different", "unsure")
STYLE = """
body{font-family:system-ui,sans-serif;margin:16px;color:#111;background:#fff}
h1{font-size:20px}h2{font-size:16px;margin-top:28px}
table{border-collapse:collapse;width:100%}
td,th{border:1px solid #ccc;padding:6px;vertical-align:top;font-size:12px}
th{background:#f2f2f2;text-align:left}
img{max-width:224px;max-height:224px;display:block}
.missing{width:224px;height:60px;background:#eee;color:#666;font-size:11px;padding:4px}
.meta{white-space:nowrap}.strip img{display:inline-block;margin:2px}
"""


class ReviewError(Exception):
    """The review pack cannot be built."""


class Thumbnails:
    """JPEG thumbnails as data URIs, computed once per image (by SHA-256)."""

    def __init__(self, size: int = THUMB) -> None:
        self.size = size
        self._cache: dict[str, str | None] = {}

    def of(self, item: ImageItem | None) -> str | None:
        if item is None:
            return None
        if item.sha256 not in self._cache:
            try:
                image = decode_rgb(read_verified(item.path, item.sha256))
            except DecodeError:
                self._cache[item.sha256] = None
            else:
                image.thumbnail((self.size, self.size))
                buffer = io.BytesIO()
                image.save(buffer, format="JPEG", quality=85)
                encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
                self._cache[item.sha256] = f"data:image/jpeg;base64,{encoded}"
        return self._cache[item.sha256]


def _img(uri: str | None, label: str) -> str:
    if uri is None:
        return f'<div class="missing">image not available: {escape(label)}</div>'
    return f'<img src="{uri}" alt="{escape(label)}">'


def _side(row: Mapping[str, str], side: str) -> str:
    keys = [
        f"source {row[f'source_{side}']}",
        f"split {row[f'split_{side}'] or '-'}",
    ]
    if row[f"metadata_group_{side}"]:
        keys.append(f"metadata group {row[f'metadata_group_{side}']}")
    if row[f"metadata_subgroup_{side}"]:
        keys.append(f"metadata subgroup {row[f'metadata_subgroup_{side}']}")
    return "<br>".join(escape(k) for k in [row[f"image_{side}"], *keys])


def _header(audit: Audit | None, rows: int) -> list[str]:
    parts = [
        "<h1>OpenInspect-Trust M3 review pack</h1>",
        f"<p>{rows} pairs. The machine's category is a suggestion, not a verdict. Visual "
        "similarity is not proof of the same physical board. Record a decision per pair in "
        "<code>review-candidates.csv</code> (<code>human_decision</code>, <code>human_notes</code>): "
        + ", ".join(f"<code>{d}</code>" for d in DECISIONS)
        + ".</p>",
    ]
    if audit is not None:
        t = audit.thresholds
        parts.append(
            f"<p>Thresholds ({escape(t.model)}, rule {escape(t.rule)}): review {t.review}, "
            f"family {t.family}, near {t.near}, pHash candidate &le; {t.phash_candidate} bits.</p>"
        )
    return parts


def _pairs_table(
    rows: Sequence[Mapping[str, str]],
    by_key: Mapping[tuple[str, str], ImageItem],
    thumbs: Thumbnails,
) -> list[str]:
    parts = [
        "<table><tr><th>pair</th><th>image A</th><th>image B</th><th>A</th><th>B</th>"
        "<th>measures</th></tr>"
    ]
    for row in rows:
        a = by_key.get((row["source_a"], row["image_a"]))
        b = by_key.get((row["source_b"], row["image_b"]))
        measures = [
            f"machine category {row['machine_category']}",
            f"stratum {row['stratum']}",
            f"cosine {row['cosine']}",
            f"pHash {row['phash_distance']} bits",
            f"dHash {row['dhash_distance']} bits",
        ]
        if row["component_near"]:
            measures.append(f"near component {row['component_near']}")
        if row["component_family"]:
            measures.append(f"family component {row['component_family']}")
        parts.append(
            f"<tr><td class='meta'>{escape(row['pair_id'])}</td>"
            f"<td>{_img(thumbs.of(a), row['image_a'])}</td>"
            f"<td>{_img(thumbs.of(b), row['image_b'])}</td>"
            f"<td>{_side(row, 'a')}</td><td>{_side(row, 'b')}</td>"
            f"<td class='meta'>{'<br>'.join(escape(m) for m in measures)}</td></tr>"
        )
    parts.append("</table>")
    return parts


def sample_groups(
    groups: Sequence[Mapping[str, object]], *, per_source: int, seed: int, level: str = "family"
) -> list[Mapping[str, object]]:
    """A seeded random sample of multi-member groups of one level, per source (for a qualitative look)."""
    chosen: list[Mapping[str, object]] = []
    by_source: dict[str, list[Mapping[str, object]]] = {}
    for group in groups:
        sources = group.get("sources")
        if group.get("level") == level and isinstance(sources, list) and len(sources) == 1:
            by_source.setdefault(str(sources[0]), []).append(group)
    for source in sorted(by_source):
        pool = sorted(by_source[source], key=lambda g: str(g.get("group_id")))
        rng = random.Random(f"groups:{seed}:{source}")  # noqa: S311 - reproducible sampling
        chosen.extend(rng.sample(pool, min(per_source, len(pool))))
    return chosen


def _groups_section(
    groups: Sequence[Mapping[str, object]],
    by_key: Mapping[tuple[str, str], ImageItem],
    thumbs: Thumbnails,
    members_shown: int,
) -> list[str]:
    parts = [
        "<h2>Seeded sample of similarity groups (qualitative look, protocol section 9f)</h2>",
        "<table><tr><th>group</th><th>members (first shown)</th></tr>",
    ]
    for group in groups:
        members = group.get("members")
        names = [str(m) for m in members] if isinstance(members, list) else []
        strip = []
        for member in names[:members_shown]:
            source, _, item_id = member.partition(":")
            strip.append(_img(thumbs.of(by_key.get((source, item_id))), member))
        splits = group.get("splits")
        weakest = group.get("all_pairs_min_similarity")
        gap = group.get("chaining_gap")
        info = [
            str(group.get("group_id")),
            f"{len(names)} images",
            "splits "
            + (", ".join(str(s) for s in splits) if isinstance(splits, list) and splits else "-"),
            "min pairwise cosine "
            + (f"{weakest:.3f}" if isinstance(weakest, int | float) else "-"),
            "chaining gap " + (f"{gap:.3f}" if isinstance(gap, int | float) else "-"),
        ]
        parts.append(
            f"<tr><td class='meta'>{'<br>'.join(escape(i) for i in info)}</td>"
            f"<td class='strip'>{''.join(strip)}</td></tr>"
        )
    parts.append("</table>")
    return parts


def write_review_pack(
    rows: Sequence[Mapping[str, str]],
    items: Sequence[ImageItem],
    target: Path,
    *,
    audit: Audit | None = None,
    groups: Sequence[Mapping[str, object]] = (),
    members_shown: int = 8,
) -> Path:
    """Write ``<target>/review-pack.html`` (self-contained: the thumbnails are embedded)."""
    if not rows:
        raise ReviewError("the review queue is empty")
    by_key = {(item.source, item.item_id): item for item in items}
    thumbs = Thumbnails()
    parts = [
        "<!DOCTYPE html>",
        '<html lang="en"><head><meta charset="utf-8">',
        "<title>M3 review pack</title>",
        f"<style>{STYLE}</style></head><body>",
        *_header(audit, len(rows)),
        *_pairs_table(rows, by_key, thumbs),
    ]
    if groups:
        parts.extend(_groups_section(groups, by_key, thumbs, members_shown))
    parts.append("</body></html>")
    target.mkdir(parents=True, exist_ok=True)
    path = target / PACK
    temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    temporary.write_text("\n".join(parts) + "\n", encoding="utf-8")
    os.replace(temporary, path)
    return path
