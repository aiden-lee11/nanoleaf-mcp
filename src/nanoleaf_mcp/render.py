"""ASCII / ANSI renderer for panel layouts and per-panel colours.

Draws the layout as it appears in the Nanoleaf app (rotated by globalOrientation) into a character grid.
Plain mode uses shade blocks (░▒▓█ by brightness) with edge lines and panel ids; ANSI mode paints
24-bit background colours so the terminal shows the real colours.
"""
from __future__ import annotations

import math
from typing import Any

from .effects import hsb_to_rgb, parse_color

SIDE = 150
H = SIDE * math.sqrt(3) / 2
CHAR_ASPECT = 0.5  # a terminal cell is ~twice as tall as wide


def _rot(x: float, y: float, deg: float) -> tuple[float, float]:
    a = math.radians(deg)
    return x * math.cos(a) - y * math.sin(a), x * math.sin(a) + y * math.cos(a)


def oriented_triangles(position_data: list[dict], global_orientation: float, side: float = SIDE) -> list[dict]:
    """[{id, verts: [(x,y)x3], cx, cy}] in app orientation (y up)."""
    h = side * math.sqrt(3) / 2
    base = [(0, 2 * h / 3), (-side / 2, -h / 3), (side / 2, -h / 3)]
    out = []
    for p in position_data:
        verts = []
        for vx, vy in base:
            x, y = _rot(vx, vy, p.get("o", 0))
            x, y = _rot(x + p["x"], y + p["y"], -global_orientation)
            verts.append((x, y))
        cx = sum(v[0] for v in verts) / 3
        cy = sum(v[1] for v in verts) / 3
        out.append({"id": p["panelId"], "verts": verts, "cx": cx, "cy": cy})
    return out


def _inside(pt: tuple[float, float], tri: list[tuple[float, float]]) -> bool:
    (x, y), (x1, y1), (x2, y2), (x3, y3) = pt, *tri
    d1 = (x - x2) * (y1 - y2) - (x1 - x2) * (y - y2)
    d2 = (x - x3) * (y2 - y3) - (x2 - x3) * (y - y3)
    d3 = (x - x1) * (y3 - y1) - (x3 - x1) * (y - y1)
    return not ((d1 < 0 or d2 < 0 or d3 < 0) and (d1 > 0 or d2 > 0 or d3 > 0))


def _edge_char(pt: tuple[float, float], tri: list[tuple[float, float]]) -> str:
    """Slope of the nearest edge -> '/', '\\' or '_'."""
    best, ch = None, "_"
    for (ax, ay), (bx, by) in zip(tri, tri[1:] + tri[:1]):
        dx, dy = bx - ax, by - ay
        L2 = dx * dx + dy * dy
        t = max(0.0, min(1.0, ((pt[0] - ax) * dx + (pt[1] - ay) * dy) / L2))
        d = math.hypot(pt[0] - (ax + t * dx), pt[1] - (ay + t * dy))
        if best is None or d < best:
            best = d
            ang = math.degrees(math.atan2(dy, dx)) % 180
            ch = "_" if ang < 20 or ang > 160 else ("/" if ang < 90 else "\\")
    return ch


def _shade(b: float) -> str:
    return "░" if b < 25 else "▒" if b < 50 else "▓" if b < 75 else "█"


def render(position_data: list[dict], global_orientation: float, colors: dict[Any, Any] | None = None,
           *, width: int = 100, ansi: bool = False, legend: bool = True, labels: bool | None = None,
           side: float = SIDE) -> str:
    """labels: draw panel ids. Default: yes in plain mode, no in colour mode (just the colours)."""
    if labels is None:
        labels = not ansi
    tris = oriented_triangles(position_data, global_orientation, side)
    if not tris:
        return "(no panels)"
    xs = [v[0] for t in tris for v in t["verts"]]
    ys = [v[1] for t in tris for v in t["verts"]]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    sx = (width - 3) / max(1.0, x1 - x0)          # columns per layout unit
    sy = sx * CHAR_ASPECT                         # rows per layout unit
    x0 -= 1 / sx; x1 += 1 / sx; y0 -= 0.5 / sy; y1 += 0.5 / sy   # one cell of padding
    cols = width
    rows = max(1, int(math.ceil((y1 - y0) * sy)) + 1)

    rgb: dict[int, tuple[int, int, int]] = {}
    hsb: dict[int, tuple[int, int, int]] = {}
    for k, v in (colors or {}).items():
        h, s, b = parse_color(v)
        hsb[int(k)] = (h, s, b)
        rgb[int(k)] = hsb_to_rgb(h, s, b)

    # cells: (char, panel_id or None, is_edge)
    grid: list[list[tuple[str, int | None, bool]]] = [[(" ", None, False) for _ in range(cols)] for _ in range(rows)]
    for r in range(rows):
        for c in range(cols):
            px = x0 + (c + 0.5) / sx
            py = y1 - (r + 0.5) / sy
            for t in tris:
                if _inside((px, py), t["verts"]):
                    # edge if any 4-neighbour cell centre falls outside this triangle
                    edge = False
                    for dc, dr in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                        qx = x0 + (c + dc + 0.5) / sx
                        qy = y1 - (r + dr + 0.5) / sy
                        if not _inside((qx, qy), t["verts"]):
                            edge = True
                            break
                    if edge:
                        ch = _edge_char((px, py), t["verts"])
                    elif t["id"] in hsb:
                        ch = _shade(hsb[t["id"]][2])
                    else:
                        ch = " "
                    grid[r][c] = (ch, t["id"], edge)
                    break

    # labels at centroids
    for t in (tris if labels else []):
        label = str(t["id"])
        c = int((t["cx"] - x0) * sx) - len(label) // 2
        r = int((y1 - t["cy"]) * sy)
        if 0 <= r < rows:
            for i, ch in enumerate(label):
                if 0 <= c + i < cols:
                    _, pid, edge = grid[r][c + i]
                    grid[r][c + i] = (ch, pid if pid is not None else t["id"], edge)

    lines = []
    for row in grid:
        if ansi:
            out = []
            current = None  # (bg, fg) currently active, so we only emit escapes on change
            for ch, pid, edge in row:
                if pid is None or pid not in rgb:
                    if current is not None:
                        out.append("\x1b[0m"); current = None
                    out.append(ch if ch.strip() or pid is None else " ")
                    continue
                r_, g_, b_ = rgb[pid]
                if edge:
                    r_, g_, b_ = int(r_ * 0.55), int(g_ * 0.55), int(b_ * 0.55)
                lum = 0.2126 * r_ + 0.7152 * g_ + 0.0722 * b_
                # bg first, fg last, and fg components that never end a sequence with a single-digit
                # SGR code (e.g. ";4m" = underline) — some ANSI filters strip those and lose the colour.
                style = (f"48;2;{r_};{g_};{b_}", "38;2;16;16;16" if lum > 140 else "38;2;250;250;250")
                if style != current:
                    out.append(f"\x1b[{style[0]};{style[1]}m"); current = style
                out.append(ch if ch.isdigit() else " ")
            if current is not None:
                out.append("\x1b[0m")
            lines.append("".join(out))
        else:
            lines.append("".join(ch for ch, _, _ in row).rstrip())
    art = "\n".join(lines)
    if legend and hsb:
        order = sorted(tris, key=lambda t: (t["cx"], -t["cy"]))
        items = [f"{t['id']}={_fmt(hsb[t['id']])}" for t in order if t["id"] in hsb]
        art += "\n\nlegend (left→right): " + "  ".join(items)
    return art


def _fmt(h: tuple[int, int, int]) -> str:
    r, g, b = hsb_to_rgb(*h)
    return f"#{r:02x}{g:02x}{b:02x}"


def anim_data_colors(anim_data: str) -> dict[int, str]:
    """Static/custom animData -> {panelId: '#rrggbb'} using each panel's first frame."""
    nums = [int(float(x)) for x in anim_data.split()]
    n, i, out = nums[0], 1, {}
    for _ in range(n):
        pid, frames = nums[i], nums[i + 1]
        r, g, b = nums[i + 2], nums[i + 3], nums[i + 4]
        out[pid] = f"#{r:02x}{g:02x}{b:02x}"
        i += 2 + frames * 5
    return out


def want_color(force: bool | None = None) -> bool:
    """ANSI colour when forced, or when stdout is a terminal (Ghostty, iTerm, Terminal all do 24-bit)."""
    import os, sys
    if force is not None:
        return force
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("FORCE_COLOR") or os.environ.get("CLICOLOR_FORCE"):
        return True
    return sys.stdout.isatty()


def render_svg(position_data: list[dict], global_orientation: float, colors: dict[Any, Any] | None = None,
               *, scale: float = 0.6, side: float = SIDE, background: str = "#1b1b1f") -> str:
    """Same picture as an SVG (real colours), for saving or converting to an image."""
    tris = oriented_triangles(position_data, global_orientation, side)
    xs = [v[0] for t in tris for v in t["verts"]]; ys = [v[1] for t in tris for v in t["verts"]]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    pad = 24
    w, h = (x1 - x0) * scale + 2 * pad, (y1 - y0) * scale + 2 * pad
    polys = []
    for t in tris:
        pts = " ".join(f"{(vx - x0) * scale + pad:.1f},{(y1 - vy) * scale + pad:.1f}" for vx, vy in t["verts"])
        fill = "#3a3a44"
        if colors and t["id"] in {int(k) for k in colors}:
            r, g, b = hsb_to_rgb(*parse_color(colors[[k for k in colors if int(k) == t["id"]][0]]))
            fill = f"#{r:02x}{g:02x}{b:02x}"
        lum = int(fill[1:3], 16) * 0.2126 + int(fill[3:5], 16) * 0.7152 + int(fill[5:7], 16) * 0.0722
        fg = "#000" if lum > 140 else "#fff"
        polys.append(f'<polygon points="{pts}" fill="{fill}" stroke="{background}" stroke-width="3"/>'
                     f'<text x="{(t["cx"] - x0) * scale + pad:.1f}" y="{(y1 - t["cy"]) * scale + pad + 5:.1f}" '
                     f'font-family="Helvetica,Arial" font-size="15" text-anchor="middle" fill="{fg}" opacity="0.85">{t["id"]}</text>')
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w:.0f}" height="{h:.0f}" viewBox="0 0 {w:.0f} {h:.0f}">'
            f'<rect width="100%" height="100%" fill="{background}"/>' + "".join(polys) + "</svg>")


def anim_data_frames(anim_data: str) -> dict[int, list[tuple[tuple[int, int, int], int]]]:
    """Static/custom animData -> {panelId: [((r, g, b), transition_tenths), ...]}."""
    nums = [int(float(x)) for x in anim_data.split()]
    n, i, out = nums[0], 1, {}
    for _ in range(n):
        pid, frames = nums[i], nums[i + 1]
        i += 2
        seq = []
        for _ in range(frames):
            r, g, b, _w, t = nums[i:i + 5]
            seq.append(((r, g, b), max(0, t)))
            i += 5
        out[pid] = seq
    return out


def anim_loop_tenths(frames: dict[int, list[tuple[tuple[int, int, int], int]]]) -> int:
    return max((sum(t for _, t in seq) for seq in frames.values()), default=0)


def colors_at(frames: dict[int, list[tuple[tuple[int, int, int], int]]], at_tenths: float) -> dict[int, str]:
    """Colour of every panel at a moment in the (looping) animation, interpolating through transitions."""
    out = {}
    for pid, seq in frames.items():
        total = sum(t for _, t in seq)
        if not seq or total == 0:
            out[pid] = "#%02x%02x%02x" % seq[0][0] if seq else "#000000"
            continue
        t = at_tenths % total
        prev = seq[-1][0]          # looping: the frame before the first is the last
        elapsed = 0
        for col, dur in seq:
            if t < elapsed + dur:
                u = (t - elapsed) / dur if dur else 1.0
                r, g, b = (round(p + (c - p) * u) for p, c in zip(prev, col))
                out[pid] = f"#{r:02x}{g:02x}{b:02x}"
                break
            elapsed += dur
            prev = col
        else:
            out[pid] = "#%02x%02x%02x" % seq[-1][0]
    return out
