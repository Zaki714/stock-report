"""輕量 SVG 圖表產生器。

刻意不引入圖表庫（Chart.js / ECharts）——GitHub Pages 是靜態站，
這幾種圖用手寫 SVG 就夠，檔案小、無外部相依、深色主題直接吃 CSS 變數。

每個函式都回傳一段 SVG 字串；資料不足時回傳空字串，模板用 {% if %} 略過即可。
顏色沿用 base.html 的變數，維持台股紅漲綠跌。
"""
from __future__ import annotations

from html import escape


def _pts(values: list[float], w: float, h: float, pad: float) -> list[tuple[float, float]]:
    lo, hi = min(values), max(values)
    span = (hi - lo) or 1.0
    n = len(values)
    step = (w - 2 * pad) / max(n - 1, 1)
    return [
        (pad + i * step, h - pad - (v - lo) / span * (h - 2 * pad))
        for i, v in enumerate(values)
    ]


def line_chart(labels: list[str], values: list[float], *,
               width: int = 560, height: int = 200, unit: str = "") -> str:
    """單線折線圖：題材信心度變化、指數走勢等。

    labels 與 values 一一對應；values 內的 None 會連同對應 label 一起被剔除。
    """
    labels = list(labels or [])
    if len(labels) < len(values):
        labels += [""] * (len(values) - len(labels))
    pairs = [(lab, v) for lab, v in zip(labels, values) if v is not None]
    if len(pairs) < 2:
        return ""
    labels = [p[0] for p in pairs]
    vals = [p[1] for p in pairs]

    pad = 28.0
    pts = _pts(vals, width, height, pad)
    poly = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
    area = f"{pad:.1f},{height - pad:.1f} " + poly + f" {pts[-1][0]:.1f},{height - pad:.1f}"

    last, first = vals[-1], vals[0]
    stroke = "var(--red)" if last >= first else "var(--green)"

    dots = "".join(
        f'<circle cx="{x:.1f}" cy="{y:.1f}" r="2.5" fill="{stroke}"/>' for x, y in pts
    )
    xlabels = ""
    for i in sorted({0, len(labels) - 1, len(labels) // 2}):
        if labels[i]:
            x = pts[i][0]
            xlabels += (f'<text x="{x:.1f}" y="{height - 8:.1f}" fill="var(--text-muted)" '
                        f'font-size="10" text-anchor="middle">{escape(str(labels[i]))}</text>')

    return (
        f'<svg viewBox="0 0 {width} {height}" width="100%" '
        f'preserveAspectRatio="xMidYMid meet" role="img" '
        f'style="max-width:{width}px;height:auto">'
        f'<polygon points="{area}" fill="{stroke}" opacity="0.10"/>'
        f'<polyline points="{poly}" fill="none" stroke="{stroke}" stroke-width="2" '
        f'stroke-linejoin="round" stroke-linecap="round"/>'
        f'{dots}'
        f'<text x="{pad:.1f}" y="16" fill="var(--text-secondary)" font-size="11">'
        f'{first:g}{escape(unit)}</text>'
        f'<text x="{width - pad:.1f}" y="16" fill="{stroke}" font-size="11" '
        f'text-anchor="end">{last:g}{escape(unit)}</text>'
        f'{xlabels}'
        f'</svg>'
    )


def diverging_bars(rows: list[dict], *, width: int = 560, row_h: int = 26,
                   value_key: str = "value", label_key: str = "label",
                   unit: str = " 億") -> str:
    """左負右正的分向長條圖：法人買賣超趨勢等。紅正綠負（台股慣例）。"""
    data = [r for r in rows if r.get(value_key) is not None]
    if not data:
        return ""

    height = row_h * len(data) + 16
    mid = width * 0.52
    peak = max((abs(r[value_key]) for r in data), default=1.0) or 1.0
    max_bar = width * 0.4

    parts = [f'<svg viewBox="0 0 {width} {height}" width="100%" '
             f'preserveAspectRatio="xMidYMid meet" role="img" '
             f'style="max-width:{width}px;height:auto">']
    parts.append(f'<line x1="{mid}" y1="6" x2="{mid}" y2="{height - 10}" '
                 f'stroke="var(--hairline)" stroke-width="1"/>')

    for i, r in enumerate(data):
        v = r[value_key]
        y = 8 + i * row_h
        bar = abs(v) / peak * max_bar
        colour = "var(--red)" if v >= 0 else "var(--green)"
        if v >= 0:
            x = mid
        else:
            x = mid - bar
        parts.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar:.1f}" height="{row_h - 10}" '
                     f'rx="2" fill="{colour}" opacity="0.85"/>')
        parts.append(f'<text x="6" y="{y + row_h - 14:.1f}" fill="var(--text-secondary)" '
                     f'font-size="11">{escape(str(r.get(label_key, "")))}</text>')
        parts.append(f'<text x="{width - 4}" y="{y + row_h - 14:.1f}" fill="{colour}" '
                     f'font-size="11" text-anchor="end">{v:+.1f}{escape(unit)}</text>')
    parts.append("</svg>")
    return "".join(parts)


def sparkline(values: list[float], *, width: int = 120, height: int = 32) -> str:
    """迷你走勢線，塞在表格或卡片角落。"""
    vals = [v for v in values if v is not None]
    if len(vals) < 2:
        return ""
    pts = _pts(vals, width, height, 3.0)
    poly = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
    stroke = "var(--red)" if vals[-1] >= vals[0] else "var(--green)"
    return (f'<svg viewBox="0 0 {width} {height}" width="{width}" height="{height}" '
            f'role="img" aria-hidden="true">'
            f'<polyline points="{poly}" fill="none" stroke="{stroke}" stroke-width="1.5" '
            f'stroke-linejoin="round" stroke-linecap="round"/></svg>')
