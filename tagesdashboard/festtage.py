"""
Festtage: Grafiken für Heiligabend/Weihnachten, Silvester/Neujahr und Geburtstage.

Alles wird als SVG in den sechs Displayfarben gezeichnet (Schwarz, Weiß, Rot, Gelb, Blau, Grün),
mit kräftigen Konturen und ohne Verläufe. Zufällige Details (Schneeflocken, Konfetti,
Feuerwerk) hängen am Datum: Am selben Tag sieht das Bild bei jeder Aktualisierung gleich aus.

  scene(kind, W, H, …)   großes Bild für die Festansicht
  icon(kind)             kleines Symbol für den Gruß im Kopf
"""

import math
import random
from html import escape

try:
    from . import nachtgrafik as ng
except ImportError:  # pragma: no cover - Tests und Prototypen ohne Paket
    import nachtgrafik as ng

BLACK, WHITE, RED, YELLOW, BLUE, GREEN = "#000000", "#FFFFFF", "#E3001B", "#FFE500", "#0082C9", "#2E9E3F"
NAVY = ng.SKY
FONT = "Jost, sans-serif"


def _r(v):
    return f"{v:.1f}"


# ======================================================================
# Bausteine
# ======================================================================
def city(x, base, s, fill, windows=None, rnd=None, cap=None, cap_w=3.5):
    """Bonner Stadtsilhouette (aus nachtgrafik.CITY) an Position x, Grundlinie base, Maßstab s.

    cap: Farbe eines Randes oben (z. B. Schnee), gezeichnet als versetzte Kopie dahinter."""
    out = []
    t = f'transform="translate({_r(x)},{_r(base)}) scale({s:.3f}) translate(0,-{ng.WATER})"'
    if cap:
        out.append(f'<g transform="translate({_r(x)},{_r(base - cap_w)}) scale({s:.3f}) translate(0,-{ng.WATER})">'
                   + "".join(f'<path d="{p}" fill="{cap}"/>' for p in ng.CITY) + "</g>")
    out.append(f"<g {t}>" + "".join(f'<path d="{p}" fill="{fill}"/>' for p in ng.CITY))
    if windows and rnd:
        for x0, x1, y0, y1, k in ng.WINDOWS:
            for _ in range(k + 4):
                c = windows[0] if rnd.random() > 0.18 or len(windows) == 1 else rnd.choice(windows[1:])
                out.append(f'<rect x="{rnd.uniform(x0, x1 - 4):.0f}" y="{rnd.uniform(y0, y1 - 4):.0f}" width="4" height="4" fill="{c}"/>')
    out.append("</g>")
    return "".join(out)


def hills(x, base, s, fill, cap=None, cap_w=3.5, lights=None):
    out = []
    if cap:
        out.append(f'<g transform="translate({_r(x)},{_r(base - cap_w)}) scale({s:.3f}) translate(0,-{ng.WATER})">'
                   f'<path d="{ng.HILLS}" fill="{cap}"/></g>')
    out.append(f'<g transform="translate({_r(x)},{_r(base)}) scale({s:.3f}) translate(0,-{ng.WATER})">'
               f'<path d="{ng.HILLS}" fill="{fill}"/>'
               f'<rect x="{ng.HOTEL[0]}" y="{ng.HOTEL[1]}" width="{ng.HOTEL[2]}" height="{ng.HOTEL[3]}" fill="{fill}"/>')
    if lights:
        out.append(f'<rect x="72" y="64" width="3" height="2" fill="{lights}"/><rect x="80" y="64" width="3" height="2" fill="{lights}"/>')
    out.append("</g>")
    return "".join(out)


def star_path(cx, cy, r_out, r_in, n=5, rot=-90):
    pts = []
    for i in range(n * 2):
        r = r_out if i % 2 == 0 else r_in
        a = math.radians(rot + i * 180 / n)
        pts.append(f"{cx + r * math.cos(a):.1f},{cy + r * math.sin(a):.1f}")
    return "M" + " L".join(pts) + " Z"


def snowflake(cx, cy, r, color=WHITE, w=None):
    w = w or max(1.6, r / 4)
    out = []
    for k in range(3):
        a = math.radians(k * 60 + 90)
        dx, dy = r * math.cos(a), r * math.sin(a)
        out.append(f'<line x1="{cx - dx:.1f}" y1="{cy - dy:.1f}" x2="{cx + dx:.1f}" y2="{cy + dy:.1f}"/>')
        for sgn in (1, -1):  # kleine Äste an jedem Arm
            bx, by = cx + sgn * dx * 0.55, cy + sgn * dy * 0.55
            for side in (1, -1):
                b = a + side * math.radians(45) + (0 if sgn > 0 else math.pi)
                out.append(f'<line x1="{bx:.1f}" y1="{by:.1f}" x2="{bx + r * 0.32 * math.cos(b):.1f}" '
                           f'y2="{by + r * 0.32 * math.sin(b):.1f}"/>')
    return f'<g stroke="{color}" stroke-width="{w:.1f}" stroke-linecap="round">{"".join(out)}</g>'


def swag(x0, x1, y, sag):
    """Bogen einer Girlande als Pfad und Funktion für Punkte darauf."""
    def at(t):
        x = x0 + (x1 - x0) * t
        return x, y + sag * 4 * t * (1 - t)
    path = f"M{x0:.1f},{y:.1f} Q{(x0 + x1) / 2:.1f},{y + 2 * sag:.1f} {x1:.1f},{y:.1f}"
    return path, at


def fairy_lights(W, y, sag, colors, wire, n_swags=2, per=9):
    out = []
    step = W / n_swags
    k = 0
    for i in range(n_swags):
        path, at = swag(i * step - 4, (i + 1) * step + 4, y, sag)
        out.append(f'<path d="{path}" fill="none" stroke="{wire}" stroke-width="2.2"/>')
        for j in range(1, per + 1):
            x, yy = at(j / (per + 1))
            c = colors[k % len(colors)]
            k += 1
            out.append(f'<rect x="{x - 2.5:.1f}" y="{yy - 1:.1f}" width="5" height="5" fill="{wire}"/>'
                       f'<ellipse cx="{x:.1f}" cy="{yy + 10:.1f}" rx="5" ry="7.5" fill="{c}" stroke="{BLACK}" stroke-width="1.6"/>')
    return "".join(out)


def text(x, y, s, size, fill, anchor="start", stroke=None, sw=0):
    st = f' stroke="{stroke}" stroke-width="{sw}" paint-order="stroke" stroke-linejoin="round"' if stroke else ""
    return (f'<text x="{_r(x)}" y="{_r(y)}" font-family="{FONT}" font-weight="600" font-size="{size:.0f}" '
            f'fill="{fill}" text-anchor="{anchor}"{st}>{escape(str(s))}</text>')  # Namen können & oder < enthalten


# ======================================================================
# Heiligabend / Weihnachten
# ======================================================================
def tree(cx, ground, h, rnd):
    """Geschmückter Tannenbaum: drei Etagen von unten nach oben, Lichterbögen, Kugeln, Stern."""
    out = [f'<rect x="{cx - h * 0.05:.1f}" y="{ground - h * 0.12:.1f}" width="{h * 0.1:.1f}" height="{h * 0.13:.1f}" '
           f'fill="{BLACK}"/>']
    tiers = [(0.10, 0.56, 0.66), (0.36, 0.78, 0.5), (0.58, 0.95, 0.34)]  # (Basis, Spitze, Breite) in h
    for b, t, wf in tiers:
        yb, yt, half = ground - h * b, ground - h * t, h * wf / 2
        out.append(f'<path d="M{cx - half:.1f},{yb:.1f} Q{cx:.1f},{yb + h * 0.05:.1f} {cx + half:.1f},{yb:.1f} L{cx:.1f},{yt:.1f} Z" '
                   f'fill="{GREEN}" stroke="{BLACK}" stroke-width="2.6" stroke-linejoin="round"/>')
        for k in range(6):  # Lichterbogen kurz über der Basis
            u = (k + 0.5) / 6
            x = cx - half * 0.78 + half * 1.56 * u
            y = yb - h * 0.07 + h * 0.035 * 4 * u * (1 - u)
            out.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{h * 0.017:.1f}" fill="{YELLOW}"/>')
        for k in range(3):  # Kugeln
            u = (k + 0.5) / 3 + rnd.uniform(-0.08, 0.08)
            x = cx - half * 0.66 + half * 1.32 * u
            y = yb - h * rnd.uniform(0.015, 0.03)
            c = (RED, BLUE, RED, YELLOW)[(k + int(b * 10)) % 4]
            r = h * 0.033
            out.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r:.1f}" fill="{c}" stroke="{BLACK}" stroke-width="1.8"/>'
                       f'<circle cx="{x - r * 0.35:.1f}" cy="{y - r * 0.35:.1f}" r="{r * 0.28:.1f}" fill="{WHITE}"/>')
    top = ground - h * 0.95
    out.append(f'<path d="{star_path(cx, top - h * 0.02, h * 0.075, h * 0.032)}" fill="{YELLOW}" stroke="{BLACK}" stroke-width="2"/>')
    return "".join(out)


def _free(x, y, r, boxes):
    """Liegt ein Kreis (x, y, r) außerhalb aller Rechtecke (x0, y0, x1, y1)?"""
    for x0, y0, x1, y1 in boxes:
        dx, dy = max(x0 - x, 0, x - x1), max(y0 - y, 0, y - y1)
        if math.hypot(dx, dy) < r:
            return False
    return True


def scene_weihnachten(W, H, seed=0, greeting="Frohe Weihnachten"):
    rnd = random.Random(seed)
    port = W < H * 1.6
    out = [f'<svg viewBox="0 0 {W} {H}" class="fest-svg" xmlns="http://www.w3.org/2000/svg">',
           f'<rect width="{W}" height="{H}" fill="{NAVY}"/>']
    base = H - (52 if not port else 60)
    s = (W * (0.66 if not port else 0.98)) / 400
    # kleine Sterne
    for _ in range(int(40 * W / 800)):
        out.append(f'<circle cx="{rnd.uniform(4, W - 4):.0f}" cy="{rnd.uniform(46, base - 110 * s):.0f}" r="{rnd.choice((1.2, 1.6, 2))}" fill="{YELLOW}"/>')
    # Stern über dem Münster mit Schweif
    sx, sy = 114 * s, base - (104 - 22) * s - 32
    tail_dx, tail_dy = W * 0.16, -34
    # Schweif: ein Fächer aus drei Strahlen, der sich nach hinten öffnet, und funkelnde Punkte
    for k, (dy, wdt) in enumerate(((-16, 7), (0, 10), (16, 7))):
        ex, ey = sx + tail_dx, sy + tail_dy + dy
        nx, ny = -(ey - sy), ex - sx
        L = math.hypot(nx, ny) or 1
        nx, ny = nx / L * wdt, ny / L * wdt
        out.append(f'<path d="M{sx:.1f},{sy:.1f} L{ex + nx:.1f},{ey + ny:.1f} L{ex - nx:.1f},{ey - ny:.1f} Z" fill="{YELLOW}"/>')
    for _ in range(9):
        u = rnd.uniform(0.3, 1.15)
        x, y = sx + tail_dx * u + rnd.uniform(-8, 8), sy + tail_dy * u + rnd.uniform(-22, 22)
        out.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{rnd.choice((1.8, 2.4))}" fill="{YELLOW}"/>')
    out.append(f'<path d="{star_path(sx, sy, 24, 7, n=4, rot=-90)}" fill="{YELLOW}"/>'
               f'<path d="{star_path(sx, sy, 13, 5, n=4, rot=-45)}" fill="{YELLOW}"/>'
               f'<circle cx="{sx:.1f}" cy="{sy:.1f}" r="4" fill="{WHITE}"/>')
    # Stadt mit Schnee auf den Dächern, warmes Licht in den Fenstern
    hill_s = s * (0.95 if not port else 0.7)  # Berge hinter der Stadt
    out.append(hills(W - 300 * hill_s, base, hill_s, BLACK, cap=WHITE, cap_w=4, lights=YELLOW))
    out.append(city(0, base, s, BLACK, windows=[YELLOW, RED], rnd=rnd, cap=WHITE, cap_w=4))
    # Rhein mit Spiegelungen, vorne ein verschneites Ufer
    out.append(f'<rect y="{base}" width="{W}" height="{H - base}" fill="{BLACK}"/>')
    for x in (222 * s, 281 * s, 330 * s, sx):
        for k in range(3):
            out.append(f'<rect x="{x - 10 + k * 5:.0f}" y="{base + 5 + k * 6}" width="{20 - k * 6}" height="2.4" fill="{YELLOW}"/>')
    bank = H - (20 if not port else 24)
    out.append(f'<path d="M0,{bank} C{W * 0.2:.0f},{bank - 10} {W * 0.45:.0f},{bank + 6} {W * 0.62:.0f},{bank - 4} '
               f'C{W * 0.8:.0f},{bank - 16} {W * 0.92:.0f},{bank - 6} {W},{bank - 12} L{W},{H} L0,{H} Z" fill="{WHITE}"/>')
    # Baum am Ufer
    th = H * (0.62 if not port else 0.4)
    out.append(tree(W - (W * 0.12 if not port else W * 0.17), bank + 4, th, rnd))
    # Gruß im Himmel; Schneeflocken lassen ihn frei
    size = 52 if not port else 40
    ty = 98 if not port else 92
    tw = len(greeting) * size * 0.5
    box = (W / 2 - tw / 2 - 8, ty - size * 0.85, W / 2 + tw / 2 + 8, ty + size * 0.25)
    out.append(text(W / 2, ty, greeting, size, WHITE, anchor="middle", stroke=NAVY, sw=6))
    # Schnee: große Flocken und viele kleine
    for _ in range(int(150 * W / 800)):
        x, y = rnd.uniform(0, W), rnd.uniform(40, bank)
        if _free(x, y, 3, [box]):
            out.append(f'<circle cx="{x:.0f}" cy="{y:.0f}" r="{rnd.choice((1.6, 2, 2.4))}" fill="{WHITE}"/>')
    flakes = 0
    for _ in range(200):
        if flakes >= int(12 * W / 800) + 4:
            break
        x, y, r = rnd.uniform(14, W - 14), rnd.uniform(50, base - 30), rnd.uniform(6, 11)
        if _free(x, y, r + 4, [box, (sx - 30, sy + tail_dy - 30, sx + tail_dx + 20, sy + 30),
                               (W - W * 0.13 - H * 0.2, H - H * 0.62, W, H)]):
            out.append(snowflake(x, y, r))
            flakes += 1
    # Lichterkette oben
    out.append(fairy_lights(W, -2, 16, [RED, YELLOW, GREEN, WHITE], WHITE, n_swags=2 if not port else 1,
                            per=9 if not port else 10))
    out.append("</svg>")
    return "".join(out)


# ======================================================================
# Silvester / Neujahr
# ======================================================================
def burst(kind, cx, cy, r, color, rnd, color2=None):
    out = []
    if kind == "chrysantheme":
        n = 22
        for k in range(n):
            a = 2 * math.pi * k / n + rnd.uniform(-0.05, 0.05)
            r0, r1 = r * 0.22, r * rnd.uniform(0.85, 1.0)
            out.append(f'<line x1="{cx + r0 * math.cos(a):.1f}" y1="{cy + r0 * math.sin(a):.1f}" '
                       f'x2="{cx + r1 * math.cos(a):.1f}" y2="{cy + r1 * math.sin(a):.1f}" stroke="{color}" stroke-width="2.4" stroke-linecap="round"/>'
                       f'<circle cx="{cx + (r1 + 5) * math.cos(a):.1f}" cy="{cy + (r1 + 5) * math.sin(a):.1f}" r="2.4" fill="{color2 or color}"/>')
    elif kind == "weide":  # Trauerweide: Bögen, die nach unten fallen
        n = 12
        for k in range(n):
            a = math.pi + math.pi * k / (n - 1)  # obere Hälfte
            ex, ey = cx + r * math.cos(a), cy + r * math.sin(a) * 0.7
            drop = r * 0.9
            out.append(f'<path d="M{cx:.1f},{cy:.1f} Q{ex:.1f},{ey - r * 0.2:.1f} {ex + (ex - cx) * 0.15:.1f},{ey + drop:.1f}" '
                       f'fill="none" stroke="{color}" stroke-width="2.2" stroke-dasharray="7 4" stroke-linecap="round"/>')
    elif kind == "ring":
        n = 18
        for k in range(n):
            a = 2 * math.pi * k / n
            out.append(f'<circle cx="{cx + r * math.cos(a):.1f}" cy="{cy + r * math.sin(a):.1f}" r="3.6" fill="{color}"/>')
        out.append(f'<path d="{star_path(cx, cy, r * 0.45, r * 0.14, n=6)}" fill="{color2 or color}"/>')
    elif kind == "glitzer":
        for _ in range(26):
            a, d = rnd.uniform(0, 2 * math.pi), r * math.sqrt(rnd.random())
            x, y = cx + d * math.cos(a), cy + d * math.sin(a)
            q = rnd.uniform(3, 5.5)
            out.append(f'<path d="M{x - q:.1f},{y:.1f} L{x + q:.1f},{y:.1f} M{x:.1f},{y - q:.1f} L{x:.1f},{y + q:.1f}" '
                       f'stroke="{color}" stroke-width="2" stroke-linecap="round"/>')
    elif kind == "pfingstrose":  # zwei Ringe aus Strahlen in zwei Farben
        for ring, (rr, c) in enumerate(((r, color), (r * 0.58, color2 or WHITE))):
            n = 16 if ring == 0 else 10
            for k in range(n):
                a = 2 * math.pi * (k + 0.5 * ring) / n
                out.append(f'<line x1="{cx + rr * 0.55 * math.cos(a):.1f}" y1="{cy + rr * 0.55 * math.sin(a):.1f}" '
                           f'x2="{cx + rr * math.cos(a):.1f}" y2="{cy + rr * math.sin(a):.1f}" stroke="{c}" stroke-width="3.2" stroke-linecap="round"/>')
    return "".join(out)


def rocket_trail(x0, y0, x1, y1, color):
    out = []
    mx = (x0 + x1) / 2 + (x1 - x0) * 0.2
    for k in range(9):
        t = k / 9
        x = (1 - t) ** 2 * x0 + 2 * (1 - t) * t * mx + t * t * x1
        y = (1 - t) ** 2 * y0 + 2 * (1 - t) * t * ((y0 + y1) / 2) + t * t * y1
        out.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{0.9 + 1.6 * t:.1f}" fill="{color}"/>')
    return "".join(out)


def flap_year(x, y, h, year_from, year_to, flipping):
    """Fallblattanzeige mit vier Karten. flipping: Hinter der letzten Ziffer des alten Jahres
    lugt schon die neue hervor (rot, schräg) – gleich klappt sie um."""
    w, gap = h * 0.66, h * 0.1
    a, b = str(year_from), str(year_to)
    shown = a if flipping else b
    out = []

    def card(cx, cy, digit, color, rot=0):
        t = f' transform="rotate({rot} {cx + w / 2:.1f} {cy + h:.1f})"' if rot else ""
        return (f'<g{t}><rect x="{cx:.1f}" y="{cy:.1f}" width="{w:.1f}" height="{h:.1f}" rx="{h * 0.1:.1f}" fill="{WHITE}" '
                f'stroke="{BLACK}" stroke-width="3"/>'
                + text(cx + w / 2, cy + h * 0.8, digit, h * 0.86, color, anchor="middle")
                + f'<rect x="{cx:.1f}" y="{cy + h / 2 - 1.5:.1f}" width="{w:.1f}" height="3" fill="{BLACK}"/>'
                f'<rect x="{cx - 3:.1f}" y="{cy + h / 2 - 5:.1f}" width="5" height="10" rx="1.5" fill="{BLACK}"/>'
                f'<rect x="{cx + w - 2:.1f}" y="{cy + h / 2 - 5:.1f}" width="5" height="10" rx="1.5" fill="{BLACK}"/></g>')
    last_x = x + 3 * (w + gap)
    if flipping:
        out.append(card(last_x + w * 0.5, y - h * 0.2, b[3], RED, rot=14))
    for i in range(4):
        cx = x + i * (w + gap)
        out.append(card(cx, y, shown[i], RED if (i == 3 and not flipping) else BLACK))
    return "".join(out), 4 * w + 3 * gap + (w * 0.65 if flipping else 0)


def glasses(cx, cy, h):
    """Zwei Sektflöten, die anstoßen. (cx, cy): Mitte am Fuß der Kelche; h: Gesamthöhe."""
    out = []
    bh, bw = h * 0.52, h * 0.105  # Kelch: Höhe, halbe Breite oben
    for side in (-1, 1):
        g = [f'<g transform="translate({cx + side * h * 0.2:.1f},{cy:.1f}) rotate({-side * 12})">']
        g.append(f'<path d="M{-bw:.1f},{-bh:.1f} L{bw:.1f},{-bh:.1f} L{bw * 0.62:.1f},{-h * 0.03:.1f} Q0,{h * 0.03:.1f} '
                 f'{-bw * 0.62:.1f},{-h * 0.03:.1f} Z" fill="{WHITE}" stroke="{BLACK}" stroke-width="2.6" stroke-linejoin="round"/>')
        g.append(f'<path d="M{-bw * 0.93:.1f},{-bh * 0.8:.1f} L{bw * 0.93:.1f},{-bh * 0.8:.1f} L{bw * 0.62:.1f},{-h * 0.03:.1f} '
                 f'Q0,{h * 0.03:.1f} {-bw * 0.62:.1f},{-h * 0.03:.1f} Z" fill="{YELLOW}"/>')
        for k in range(5):
            g.append(f'<circle cx="{((k % 2) - 0.5) * bw * 0.6:.1f}" cy="{-bh * (0.12 + 0.13 * k):.1f}" r="{h * 0.016:.1f}" fill="{WHITE}"/>')
        g.append(f'<rect x="{-h * 0.016:.1f}" y="{-h * 0.01:.1f}" width="{h * 0.032:.1f}" height="{h * 0.36:.1f}" fill="{WHITE}" '
                 f'stroke="{BLACK}" stroke-width="1.6"/>'
                 f'<ellipse cx="0" cy="{h * 0.36:.1f}" rx="{bw * 1.1:.1f}" ry="{h * 0.03:.1f}" fill="{WHITE}" stroke="{BLACK}" stroke-width="2"/></g>')
        out.append("".join(g))
    top = cy - bh - h * 0.02
    for k in range(7):  # Funken über den Rändern
        a = math.radians(-90 + (k - 3) * 24)
        out.append(f'<line x1="{cx + 12 * math.cos(a):.1f}" y1="{top + 12 * math.sin(a):.1f}" '
                   f'x2="{cx + 28 * math.cos(a):.1f}" y2="{top + 28 * math.sin(a):.1f}" stroke="{YELLOW}" stroke-width="2.8" stroke-linecap="round"/>')
    return "".join(out)


def scene_silvester(W, H, year, after_midnight, seed=0):
    rnd = random.Random(seed + (7 if after_midnight else 0))
    port = W < H * 1.6
    out = [f'<svg viewBox="0 0 {W} {H}" class="fest-svg" xmlns="http://www.w3.org/2000/svg">',
           f'<rect width="{W}" height="{H}" fill="{BLACK}"/>']
    base = H - (46 if not port else 54)
    s = (W * (0.58 if not port else 0.95)) / 400
    head = "Frohes neues Jahr!" if after_midnight else "Guten Rutsch!"
    hs = 46 if not port else 38
    fh = 78 if not port else 64
    flap, fw = flap_year(0, 0, fh, year if after_midnight else year - 1, year, flipping=not after_midnight)
    if not port:
        hx, hy, anchor = 34, 72, "start"
        fx, fy = 34, 94
        tbox = (hx - 6, hy - hs * 0.85, hx + len(head) * hs * 0.5 + 6, hy + 10)
    else:
        hx, hy, anchor = W / 2, 62, "middle"
        fx, fy = (W - fw) / 2, 84
        tw = len(head) * hs * 0.5
        tbox = (hx - tw / 2 - 6, hy - hs * 0.85, hx + tw / 2 + 6, hy + 10)
    fbox = (fx - 8, fy - 8, fx + fw + 22, fy + fh + 8)
    gh = 150 if not port else 120
    gx = W - (100 if not port else 92)
    gbox = (gx - gh * 0.45, H - gh * 1.05, gx + gh * 0.45, H)
    keep = [tbox, fbox] + ([gbox] if after_midnight else [])

    # Feuerwerk: verschiedene Arten, nie über Schrift, Anzeige oder Gläsern
    kinds = ["chrysantheme", "weide", "ring", "pfingstrose", "glitzer", "chrysantheme", "ring"]
    colors = [(RED, YELLOW), (YELLOW, None), (GREEN, YELLOW), (RED, WHITE), (WHITE, None), (BLUE, WHITE), (YELLOW, RED)]
    n = (6 if after_midnight else 5) if not port else (6 if after_midnight else 5)
    spots = []
    for i in range(n):
        for _ in range(300):
            r = rnd.uniform(34, 58) * (1 if not port else 0.85)
            x, y = rnd.uniform(r + 8, W - r - 8), rnd.uniform(r + 6, base - 70 * s - r * 0.2)
            if _free(x, y, r * 1.05, keep) and all(math.hypot(x - a, y - b) > (r + rb) * 0.95 for a, b, rb in spots):
                spots.append((x, y, r))
                break
    for i, (x, y, r) in enumerate(spots):
        c1, c2 = colors[i % len(colors)]
        out.append(rocket_trail(x + rnd.uniform(-60, 60), base - 4, x, y + r * 0.25, YELLOW if c1 != YELLOW else WHITE))
        out.append(burst(kinds[i % len(kinds)], x, y, r, c1, rnd, c2))
    # Stadt in Blau vor schwarzem Himmel, gelbe Fenster
    hill_s = s * (0.95 if not port else 0.7)
    out.append(hills(W - 300 * hill_s, base, hill_s, BLUE, lights=YELLOW))
    out.append(city(0, base, s, BLUE, windows=[YELLOW, WHITE], rnd=rnd))
    # Rhein: Spiegelungen
    out.append(f'<rect y="{base}" width="{W}" height="{H - base}" fill="{BLACK}"/>')
    for (x, y, r), (c1, _) in zip(spots, colors):
        for k in range(4):
            out.append(f'<rect x="{x - 16 + k * 5 + rnd.uniform(-4, 4):.0f}" y="{base + 5 + k * 8}" width="{max(6, 30 - k * 8)}" height="2.6" fill="{c1}"/>')
    # Gruß und Jahreszahl als Fallblattanzeige; nach Mitternacht stoßen zwei Gläser an
    out.append(text(hx, hy, head, hs, WHITE, anchor=anchor))
    out.append(f'<g transform="translate({fx:.1f},{fy:.1f})">{flap}</g>')
    if after_midnight:
        out.append(glasses(gx, H - 12 - gh * 0.39, gh))
    out.append("</svg>")
    return "".join(out)


# ======================================================================
# Geburtstag
# ======================================================================
def gift(cx, base, w):
    """Geschenk mit Schleife; base = Unterkante."""
    h = w * 0.72
    x0, y0 = cx - w / 2, base - h
    return (f'<rect x="{x0:.1f}" y="{y0:.1f}" width="{w:.1f}" height="{h:.1f}" fill="{RED}" stroke="{BLACK}" stroke-width="2.6"/>'
            f'<rect x="{x0 - 6:.1f}" y="{y0 - 14:.1f}" width="{w + 12:.1f}" height="16" fill="{RED}" stroke="{BLACK}" stroke-width="2.6"/>'
            f'<rect x="{cx - 7:.1f}" y="{y0 - 14:.1f}" width="14" height="{h + 14:.1f}" fill="{YELLOW}" stroke="{BLACK}" stroke-width="2"/>'
            f'<path d="M{cx:.1f},{y0 - 14:.1f} C{cx - 34:.1f},{y0 - 46:.1f} {cx - 40:.1f},{y0 - 8:.1f} {cx:.1f},{y0 - 14:.1f} Z '
            f'M{cx:.1f},{y0 - 14:.1f} C{cx + 34:.1f},{y0 - 46:.1f} {cx + 40:.1f},{y0 - 8:.1f} {cx:.1f},{y0 - 14:.1f} Z" '
            f'fill="{YELLOW}" stroke="{BLACK}" stroke-width="2.2"/>')


def sparkle(x, y, r, color=YELLOW):
    return f'<path d="{star_path(x, y, r, r * 0.28, n=4)}" fill="{color}" stroke="{BLACK}" stroke-width="1.6" stroke-linejoin="round"/>'


NARROW, WIDE = set("iljI.,'!|ftr"), set("mwMW&")
SPACING = 0.06  # Luft zwischen den Ballonbuchstaben (in em), damit die dicken Konturen nicht verschmelzen


def _em(ch):
    """Geschätzte Zeichenbreite in em (Jost); reicht für Zentrierung und Schnüre."""
    if ch == " ":
        w = 0.28
    elif ch in NARROW:
        w = 0.3
    elif ch in WIDE:
        w = 0.86
    else:
        w = 0.66 if ch.isupper() or ch.isdigit() else 0.56
    return w + SPACING


def foil_word(cx, y, word, size, colors, bounce):
    """Ganzes Wort als Folienballons: ein Text, Farbe je Buchstabe, leichtes Auf und Ab.

    Drei Lagen: schwarze Kontur, weißer Glanz (versetzt nach oben links), Farbe."""
    o = size * 0.03
    def layer(dx, dy, fill, extra=""):
        spans, last = [], 0.0
        for i, ch in enumerate(word):
            off = (bounce if i % 2 else -bounce) if len(word) > 1 else 0
            c = fill or colors[i % len(colors)]
            spans.append(f'<tspan dy="{off - last:.1f}" fill="{c}">{escape(ch)}</tspan>')
            last = off
        return (f'<text x="{cx + dx:.1f}" y="{y + dy:.1f}" font-family="{FONT}" font-weight="600" font-size="{size:.0f}" '
                f'letter-spacing="{size * SPACING:.1f}" text-anchor="middle"{extra}>{"".join(spans)}</text>')
    return (layer(0, 0, BLACK, f' stroke="{BLACK}" stroke-width="{size * 0.1:.1f}" stroke-linejoin="round"')
            + layer(-o, -o, WHITE) + layer(o * 0.4, o * 0.4, None))


def scene_geburtstag(W, H, names, age=None, seed=0):
    """Folienballons: der Name in Ballonbuchstaben, das Alter als goldene Zahlen, Schnüre zum Geschenk.

    Bei mehreren Geburtstagen stehen die Initialen da („M & J“), der Gruß nennt alle Namen."""
    rnd = random.Random(seed)
    port = W < H * 1.6
    names = [n for n in names if n] or ["?"]
    show_age = bool(age) and len(names) == 1
    out = [f'<svg viewBox="0 0 {W} {H}" class="fest-svg" xmlns="http://www.w3.org/2000/svg">',
           f'<rect width="{W}" height="{H}" fill="{BLUE}"/>']
    word = names[0] if len(names) == 1 else " & ".join(n[:1].upper() for n in names)
    cx = W * 0.36 if (show_age and not port) else W / 2  # Mitte von Gruß, Buchstaben und Geschenk
    head = "Alles Gute!" if len(names) == 1 else f"Alles Gute, {names_text(names)}!"
    hsz = min(44 if not port else 36, (W - 40) / (len(head) * 0.5))
    hy = 50 if not port else 60
    out.append(text(W / 2 if len(names) > 1 else cx, hy, head, hsz, WHITE, anchor="middle"))
    # Größe: passend zur Breite und zum Platz unter dem Gruß
    ems = [_em(ch) for ch in word]
    ly = H * (0.6 if not port else 0.42)
    room = W * (0.62 if (show_age and not port) else 0.88)
    size = min(150 if not port else 120, room / max(sum(ems), 0.5), (ly - hy - 18) / 0.95)
    bounce = size * 0.06
    gw, gbase = 96, H - 12
    gtop = gbase - gw * 0.72 - 14
    # Schnüre von den geschätzten Buchstabenmitten zum Geschenk
    x = cx - sum(ems) * size / 2
    for i, (ch, em) in enumerate(zip(word, ems)):
        mid = x + em * size / 2
        x += em * size
        if ch.strip() and ch != "&":
            y = ly + ((bounce if i % 2 else -bounce) if len(word) > 1 else 0)
            out.append(f'<path d="M{mid:.1f},{y + 6:.1f} Q{(mid + cx) / 2 + rnd.uniform(-25, 25):.1f},{(y + gbase) / 2:.1f} {cx:.1f},{gtop:.1f}" '
                       f'fill="none" stroke="{WHITE}" stroke-width="2"/>')
    boxes = [(cx - sum(ems) * size / 2 - 10, ly - size * 0.9, cx + sum(ems) * size / 2 + 10, ly + bounce + 10)]
    if show_age:
        digits = str(age)
        ax, ay = (W * 0.83, ly) if not port else (W / 2, H * 0.75)
        asz = min(150 if not port else 110, (W * 0.3 if not port else W * 0.8) / (len(digits) * 0.66))
        for k in range(len(digits)):
            dx = ax + (k - (len(digits) - 1) / 2) * asz * 0.66
            out.append(f'<path d="M{dx:.1f},{ay + 8:.1f} Q{dx + 20:.1f},{(ay + gbase) / 2:.1f} {cx + gw * 0.4:.1f},{gtop + 10:.1f}" '
                       f'fill="none" stroke="{WHITE}" stroke-width="2"/>')
        out.append(foil_word(ax, ay, digits, asz, [YELLOW], asz * 0.04))
        boxes.append((ax - asz * 0.4 * len(digits) - 10, ay - asz * 0.9, ax + asz * 0.4 * len(digits) + 10, ay + 12))
    out.append(foil_word(cx, ly, word, size, [RED, YELLOW, GREEN, WHITE], bounce))
    out.append(gift(cx, gbase, gw))
    # Funkeln, nie über Buchstaben, Gruß und Geschenk
    boxes += [(0, 0, W, hy + 12), (cx - gw, gtop - 30, cx + gw, H)]
    for _ in range(70):
        px, py = rnd.uniform(10, W - 10), rnd.uniform(10, H - 10)
        if _free(px, py, 14, boxes):
            out.append(sparkle(px, py, rnd.choice((6, 8, 11))) if rnd.random() < 0.4 else f'<circle cx="{px:.0f}" cy="{py:.0f}" r="2" fill="{WHITE}"/>')
    out.append("</svg>")
    return "".join(out)


# ======================================================================
# Kleine Symbole für den Gruß im Kopf (32er-ViewBox)
# ======================================================================
def icon(kind, cls="fest-ic"):
    v = f'<svg class="{cls}" viewBox="0 0 32 32" aria-hidden="true">'
    if kind == "weihnachten":
        return (v + f'<path d="{star_path(16, 17, 14, 5.5, n=5)}" fill="{YELLOW}" stroke="{BLACK}" stroke-width="2" stroke-linejoin="round"/>'
                + "</svg>")
    if kind in ("silvester", "neujahr"):
        lines = []
        for k in range(10):
            a = 2 * math.pi * k / 10
            c = RED if k % 2 == 0 else BLUE
            lines.append(f'<line x1="{16 + 5 * math.cos(a):.1f}" y1="{14 + 5 * math.sin(a):.1f}" x2="{16 + 13 * math.cos(a):.1f}" '
                         f'y2="{14 + 13 * math.sin(a):.1f}" stroke="{c}" stroke-width="2.8" stroke-linecap="round"/>')
        return v + "".join(lines) + f'<circle cx="16" cy="14" r="3" fill="{YELLOW}" stroke="{BLACK}" stroke-width="1.2"/></svg>'
    if kind == "geburtstag":
        return (v + f'<rect x="5" y="17" width="22" height="11" rx="2" fill="{RED}" stroke="{BLACK}" stroke-width="2"/>'
                f'<path d="M5,19 q2.75,4 5.5,0 t5.5,0 t5.5,0 t5.5,0" fill="{WHITE}" stroke="{BLACK}" stroke-width="1.6"/>'
                f'<rect x="14.5" y="9" width="3" height="8" fill="{BLUE}" stroke="{BLACK}" stroke-width="1.2"/>'
                f'<path d="M16,2 C19,6 18,9 16,9 C14,9 13,6 16,2 Z" fill="{YELLOW}" stroke="{BLACK}" stroke-width="1.4"/></svg>')
    return ""


def scene(kind, W, H, seed=0, year=None, names=(), age=None):
    if kind == "weihnachten":
        return scene_weihnachten(W, H, seed)
    if kind in ("silvester", "neujahr"):
        return scene_silvester(W, H, year, after_midnight=(kind == "neujahr"), seed=seed)
    if kind == "geburtstag":
        return scene_geburtstag(W, H, list(names), age=age, seed=seed)
    return ""


# ======================================================================
# Logik: welcher Anlass ist heute, welches Zeitfenster gilt?
# ======================================================================
from datetime import date as _date, datetime as _dt, time as _time, timedelta as _td  # noqa: E402
import json as _json  # noqa: E402

# Festansicht (Variante C): Start und Ende; Silvester geht über Mitternacht
XMAS_VIEW = ((12, 24), _time(17), _time(23))
NYE_VIEW_START = ((12, 31), _time(22))
NYE_VIEW_END = ((1, 1), _time(2))
BDAY_VIEW = (_time(6), _time(10))
BDAY_VIEW_READY = True  # Geburtstagsbild (Folienballons) freigegeben
NAME_MAX = 24


def _leap(y):
    return y % 4 == 0 and (y % 100 != 0 or y % 400 == 0)


def parse_birthdays(text, today=None):
    """JSON aus den Einstellungen -> geprüfte Liste [{name, day, month, year}]. Ungültiges fällt weg."""
    today = today or _date.today()
    try:
        raw = _json.loads(text) if str(text or "").strip() else []
    except (ValueError, TypeError):
        return []
    out, seen = [], set()
    for b in raw if isinstance(raw, list) else []:
        if not isinstance(b, dict):
            continue
        name = " ".join(str(b.get("name") or "").split())[:NAME_MAX]
        try:
            day, month = int(b.get("day")), int(b.get("month"))
            year = int(b["year"]) if b.get("year") not in (None, "") else None
        except (TypeError, ValueError):
            continue
        if not name or not 1 <= month <= 12:
            continue
        days = [31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1]
        if not 1 <= day <= days:
            continue
        if year is not None and not (1900 <= year <= today.year):
            year = None
        if year is not None and month == 2 and day == 29 and not _leap(year):
            continue
        key = (name.lower(), day, month)
        if key in seen:
            continue
        seen.add(key)
        out.append({"name": name, "day": day, "month": month, "year": year})
    return out


def birthdays_on(d, birthdays):
    """Wer hat am Tag d Geburtstag? 29.2. wird in Nicht-Schaltjahren am 28.2. gefeiert."""
    hits = []
    for b in birthdays:
        day = 28 if (b["month"] == 2 and b["day"] == 29 and not _leap(d.year)) else b["day"]
        if (b["month"], day) == (d.month, d.day):
            age = d.year - b["year"] if b["year"] else None
            hits.append({"name": b["name"], "age": age if age and age > 0 else None})
    return hits


def read_config(opt, flag):
    return {
        "xmas": flag("festXmas"),
        "nye": flag("festNye"),
        "bday": flag("festBday"),
        "birthdays": parse_birthdays(opt("birthdays")),
    }


def names_text(names):
    return " und ".join(names) if len(names) <= 2 else ", ".join(names[:-1]) + " und " + names[-1]


def greetings(d, cfg):
    """Gruß im Kopf (Variante B) für den Tag d: [{kind, text}]."""
    out = []
    if not cfg:
        return out
    if cfg["bday"]:
        people = birthdays_on(d, cfg["birthdays"])
        if people:
            out.append({"kind": "geburtstag", "text": f"Alles Gute, {names_text([p['name'] for p in people])}!"})
    if cfg["xmas"] and d.month == 12 and d.day in (24, 25, 26):
        out.append({"kind": "weihnachten", "text": "Frohe Weihnachten"})
    if cfg["nye"] and (d.month, d.day) == (12, 31):
        out.append({"kind": "silvester", "text": "Guten Rutsch"})
    if cfg["nye"] and (d.month, d.day) == (1, 1):
        out.append({"kind": "neujahr", "text": "Frohes neues Jahr"})
    return out


def view(now, cfg):
    """Festansicht (Variante C), falls jetzt eine fällig ist: {kind, year, names, age}."""
    if not cfg:
        return None
    t, md = now.time().replace(second=0, microsecond=0), (now.month, now.day)
    if cfg["nye"]:
        if md == NYE_VIEW_START[0] and t >= NYE_VIEW_START[1]:
            return {"kind": "silvester", "year": now.year + 1}
        if md == NYE_VIEW_END[0] and t < NYE_VIEW_END[1]:
            return {"kind": "neujahr", "year": now.year}
    if cfg["xmas"] and md == XMAS_VIEW[0] and XMAS_VIEW[1] <= t < XMAS_VIEW[2]:
        return {"kind": "weihnachten"}
    if BDAY_VIEW_READY and cfg["bday"] and BDAY_VIEW[0] <= t < BDAY_VIEW[1]:
        people = birthdays_on(now.date(), cfg["birthdays"])
        if people:
            return {"kind": "geburtstag", "names": [p["name"] for p in people],
                    "age": people[0]["age"] if len(people) == 1 else None}
    return None


def boundaries(now, cfg, days=2):
    """Zeitpunkte, an denen sich Gruß oder Festansicht ändern (für den Bild-Cache).

    Mitternacht ist immer dabei: Dann wechselt der Gruß, an Silvester das Motiv (2026 -> 2027)."""
    if not cfg:
        return []
    out = []
    for k in range(days + 1):
        d = now.date() + _td(days=k)
        midnight = _dt.combine(d, _time(0), tzinfo=now.tzinfo)
        out.append(midnight)
        if cfg["xmas"] and (d.month, d.day) == XMAS_VIEW[0]:
            out += [_dt.combine(d, XMAS_VIEW[1], tzinfo=now.tzinfo), _dt.combine(d, XMAS_VIEW[2], tzinfo=now.tzinfo)]
        if cfg["nye"] and (d.month, d.day) == NYE_VIEW_START[0]:
            out.append(_dt.combine(d, NYE_VIEW_START[1], tzinfo=now.tzinfo))
        if cfg["nye"] and (d.month, d.day) == NYE_VIEW_END[0]:
            out.append(_dt.combine(d, NYE_VIEW_END[1], tzinfo=now.tzinfo))
        if BDAY_VIEW_READY and cfg["bday"] and birthdays_on(d, cfg["birthdays"]):
            out += [_dt.combine(d, BDAY_VIEW[0], tzinfo=now.tzinfo), _dt.combine(d, BDAY_VIEW[1], tzinfo=now.tzinfo)]
    return [e for e in out if e > now]


VIEW_LABEL = {"weihnachten": "Heiligabend", "silvester": "Silvester", "neujahr": "Neujahr"}
# Bildgröße der Festansicht in Entwurfs-Pixeln (quer 800 × 340, hochkant 480 × 590); das SVG skaliert mit
ART_H = {False: 340, True: 590}
