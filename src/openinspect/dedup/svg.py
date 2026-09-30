"""Small dependency-free SVG line charts for the audit reports (M3J).

The reports commit their figures as text, so diffs are readable and the output is deterministic.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from html import escape

PALETTE = ("#1f77b4", "#d62728", "#2ca02c", "#ff7f0e", "#9467bd", "#7f7f7f", "#8c564b", "#17becf")


@dataclass(frozen=True)
class Series:
    name: str
    points: Sequence[tuple[float, float]]
    color: str | None = None
    dashed: bool = False


@dataclass(frozen=True)
class Marker:
    """A vertical reference line, for example a chosen threshold."""

    x: float
    label: str


def _ticks(low: float, high: float, count: int = 5) -> list[float]:
    step = (high - low) / count
    return [round(low + step * i, 6) for i in range(count + 1)]


def _fmt(value: float) -> str:
    text = f"{value:.4f}".rstrip("0").rstrip(".")
    return text or "0"


def line_chart(
    title: str,
    x_label: str,
    y_label: str,
    series: Sequence[Series],
    *,
    x_range: tuple[float, float],
    y_range: tuple[float, float],
    markers: Sequence[Marker] = (),
    width: int = 640,
    height: int = 400,
) -> str:
    """One chart as an SVG document (UTF-8 text)."""
    left, right, top, bottom = 64, 168, 34, 52
    plot_w, plot_h = width - left - right, height - top - bottom
    x0, x1 = x_range
    y0, y1 = y_range

    def px(x: float) -> float:
        return left + (x - x0) / (x1 - x0) * plot_w

    def py(y: float) -> float:
        return top + plot_h - (y - y0) / (y1 - y0) * plot_h

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
        f'width="{width}" height="{height}" font-family="sans-serif" font-size="11">',
        f'<rect width="{width}" height="{height}" fill="white"/>',
        f'<text x="{left}" y="20" font-size="13" font-weight="bold">{escape(title)}</text>',
        f'<rect x="{left}" y="{top}" width="{plot_w}" height="{plot_h}" fill="none" stroke="#999"/>',
    ]
    for tick in _ticks(x0, x1):
        parts.append(
            f'<line x1="{px(tick):.1f}" y1="{top}" x2="{px(tick):.1f}" y2="{top + plot_h}" stroke="#eee"/>'
            f'<text x="{px(tick):.1f}" y="{top + plot_h + 15}" text-anchor="middle">{_fmt(tick)}</text>'
        )
    for tick in _ticks(y0, y1):
        parts.append(
            f'<line x1="{left}" y1="{py(tick):.1f}" x2="{left + plot_w}" y2="{py(tick):.1f}" stroke="#eee"/>'
            f'<text x="{left - 6}" y="{py(tick) + 4:.1f}" text-anchor="end">{_fmt(tick)}</text>'
        )
    parts.append(
        f'<text x="{left + plot_w / 2:.0f}" y="{height - 10}" text-anchor="middle">{escape(x_label)}</text>'
        f'<text transform="translate(16 {top + plot_h / 2:.0f}) rotate(-90)" text-anchor="middle">'
        f"{escape(y_label)}</text>"
    )
    for marker in markers:
        if x0 <= marker.x <= x1:
            parts.append(
                f'<line x1="{px(marker.x):.1f}" y1="{top}" x2="{px(marker.x):.1f}" y2="{top + plot_h}" '
                f'stroke="#555" stroke-dasharray="4 3"/>'
                f'<text x="{px(marker.x) + 3:.1f}" y="{top + 12}" fill="#555">{escape(marker.label)}</text>'
            )
    for index, item in enumerate(series):
        color = item.color or PALETTE[index % len(PALETTE)]
        coordinates = " ".join(f"{px(x):.1f},{py(y):.1f}" for x, y in item.points)
        dash = ' stroke-dasharray="5 3"' if item.dashed else ""
        if coordinates:
            parts.append(
                f'<polyline fill="none" stroke="{color}" stroke-width="1.6"{dash} points="{coordinates}"/>'
            )
        legend_y = top + 14 + index * 16
        parts.append(
            f'<line x1="{left + plot_w + 12}" y1="{legend_y - 4}" x2="{left + plot_w + 30}" '
            f'y2="{legend_y - 4}" stroke="{color}" stroke-width="2"{dash}/>'
            f'<text x="{left + plot_w + 35}" y="{legend_y}">{escape(item.name)}</text>'
        )
    parts.append("</svg>")
    return "\n".join(parts) + "\n"
