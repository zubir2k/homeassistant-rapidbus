"""Render our own isometric 3D bus sprite set (one SVG per heading). Front of bus = bearing."""
import math, sys
from pathlib import Path

L, W, Z0, Z1 = 7.6, 3.3, 0.4, 4.0
H = Z1 - Z0
ELEV = math.radians(38)
VIEW = (0, -math.cos(ELEV), math.sin(ELEV))
LIGHT = (-0.45, 0.45, 0.77)
RED, WHITE, BLUE, NAVY, GLASS, TYRE, HUB, LAMP = "#e30613", "#fbfbfb", "#2b59c3", "#1b2a7a", "#3b74d9", "#2a2a2a", "#bfbfbf", "#ffe9a6"

def shade(hexc, k):
    r, g, b = (int(hexc[i:i+2], 16) for i in (1, 3, 5))
    return "#%02x%02x%02x" % tuple(min(255, int(c * k)) for c in (r, g, b))

def render(bearing, size=96):
    b = math.radians(bearing)
    cb, sb = math.cos(b), math.sin(b)
    def world(p):
        x, y, z = p  # x = right of bus, y = forward
        return (x * cb + y * sb, -x * sb + y * cb, z)
    def proj(p):
        X, Y, z = world(p)
        return (X, -(Y * math.sin(ELEV) + z * math.cos(ELEV)))
    def rot(n):
        return world(n)
    dot = lambda a, c: sum(i * j for i, j in zip(a, c))
    polys = []  # (points, fill, opacity)
    # ground shadow
    sh = [(-W/2-0.2, -L/2-0.2, 0), (W/2+0.2, -L/2-0.2, 0), (W/2+0.2, L/2+0.2, 0), (-W/2-0.2, L/2+0.2, 0)]
    def proj_world(X, Y):
        return (X, -(Y * math.sin(ELEV)))
    polys.append(([(lambda w: proj_world(w[0] + 0.6, w[1] - 0.5))(world(q)) for q in sh], "#000", 0.2))
    def face(origin, u, v, normal, base, decor):
        n = rot(normal)
        if dot(n, VIEW) <= 0.02:
            return
        k = 0.72 + 0.32 * max(0, dot(n, LIGHT))
        def pt(s, t):  # s 0..1 along u, t metres along v (or 0..1 for top)
            return proj(tuple(o + s * a + t * c for o, a, c in zip(origin, u, v)))
        polys.append(([pt(0, 0), pt(1, 0), pt(1, 1 if base[1] else H), pt(0, 1 if base[1] else H)], shade(base[0], k), 1))
        for kind, args, col in decor:
            if kind == "rect":
                s0, s1, t0, t1 = args
                polys.append(([pt(s0, t0), pt(s1, t0), pt(s1, t1), pt(s0, t1)], shade(col, k), 1))
            elif kind == "circle":
                s, t, r, scale = args  # r metres; s units -> metres via scale
                polys.append(([pt(s + r * math.cos(a) / scale, t + r * math.sin(a)) for a in [i * math.pi / 10 for i in range(20)]], shade(col, k), 1))
    side_bands = lambda: [
        ("rect", (0, 1, 0, 0.5), RED), ("rect", (0, 1, 0.5, 0.65), BLUE),
        ("rect", (0.05, 0.95, 1.5, 3.05), GLASS), ("rect", (0.05, 0.95, 2.6, 3.05), "#6f9bea"),
        *[("rect", (0.05 + i * 0.18, 0.05 + i * 0.18 + 0.03, 1.5, 3.05), WHITE) for i in range(1, 5)],
        ("rect", (0, 1, 3.3, 3.6), RED),
    ]
    def wheels(front_s, rear_s):
        out = []
        for s in (front_s, rear_s):
            out += [("circle", (s, 0.35, 0.72, L), TYRE), ("circle", (s, 0.35, 0.3, L), HUB)]
        return out
    # right side: u rear->front
    face((W/2, -L/2, Z0), (0, L, 0), (0, 0, 1), (1, 0, 0), (WHITE, False),
         side_bands() + wheels((L/2 + 2.3) / L, (L/2 - 2.4) / L))
    # left side: u front->rear
    face((-W/2, L/2, Z0), (0, -L, 0), (0, 0, 1), (-1, 0, 0), (WHITE, False),
         side_bands() + wheels((L/2 - 2.3) / L, (L/2 + 2.4) / L))
    # front
    face((W/2, L/2, Z0), (-W, 0, 0), (0, 0, 1), (0, 1, 0), (WHITE, False), [
        ("rect", (0, 1, 0, 0.5), RED), ("rect", (0.07, 0.93, 1.15, 3.0), GLASS), ("rect", (0.07, 0.93, 2.5, 3.0), "#6f9bea"),
        ("rect", (0.12, 0.88, 3.1, 3.45), "#111111"), ("rect", (0.3, 0.7, 3.15, 3.4), "#ff9e1b"),
        ("rect", (0.08, 0.26, 0.62, 0.9), LAMP), ("rect", (0.74, 0.92, 0.62, 0.9), LAMP)])
    # rear
    face((-W/2, -L/2, Z0), (W, 0, 0), (0, 0, 1), (0, -1, 0), (WHITE, False), [
        ("rect", (0, 1, 0, 0.5), RED), ("rect", (0.15, 0.85, 2.0, 3.1), GLASS),
        ("rect", (0.08, 0.22, 0.62, 0.95), "#c4001a"), ("rect", (0.78, 0.92, 0.62, 0.95), "#c4001a")])
    # roof (t in 0..1 along v)
    face((-W/2, -L/2, Z1), (W, 0, 0), (0, L, 0), (0, 0, 1), (RED, True), [
        ("rect", (0.2, 0.8, 0.25, 0.45), "#c0000f"), ("rect", (0.2, 0.8, 0.55, 0.7), "#c0000f"),
        ("rect", (0, 1, 0.94, 1.0), "#ff4a55")])
    pts = [p for poly, _, _ in polys for p in poly]
    span = 11.5  # fixed frame so the bus never jumps between angles
    cx = cy = 0
    cy = -1.3
    s = size / span
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size} {size}" width="{size}" height="{size}">']
    for poly, fill, op in polys:
        d = " ".join(f"{(x - cx) * s + size/2:.1f},{(y - cy) * s + size/2:.1f}" for x, y in poly)
        out.append(f'<polygon points="{d}" fill="{fill}"' + (f' opacity="{op}"' if op != 1 else '') + ' stroke="#0d1640" stroke-width="0.6" stroke-linejoin="round"/>' if op == 1 else f'<polygon points="{d}" fill="{fill}" opacity="{op}"/>')
    out.append("</svg>")
    return "\n".join(out)

if __name__ == "__main__":
    # writes custom_components/prasarana_bus/frontend/buses/bus_00.svg … (bus_00 = heading north)
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 32
    d = Path(__file__).resolve().parent.parent / "custom_components/prasarana_bus/frontend/buses"
    d.mkdir(parents=True, exist_ok=True)
    for old in d.glob("bus_*.svg"):
        old.unlink()
    for i in range(n):
        (d / f"bus_{i:02d}.svg").write_text(render(i * 360 / n))
    print(f"{n} sprites -> {d}  (set SPRITES = {n} in rapidbus-card.js)")
