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


def bunting(W, y, sag, colors, n_swags=2, per=8, size=22):
    out = []
    step = W / n_swags
    k = 0
    for i in range(n_swags):
        path, at = swag(i * step - 6, (i + 1) * step + 6, y, sag)
        for j in range(per):
            t0, t1 = (j + 0.12) / per, (j + 0.88) / per
            (xa, ya), (xb, yb) = at(t0), at(t1)
            xm, ym = (xa + xb) / 2, (ya + yb) / 2 + size * 1.25
            c = colors[k % len(colors)]
            k += 1
            out.append(f'<path d="M{xa:.1f},{ya:.1f} L{xb:.1f},{yb:.1f} L{xm:.1f},{ym:.1f} Z" fill="{c}" '
                       f'stroke="{BLACK}" stroke-width="2" stroke-linejoin="round"/>')
        out.append(f'<path d="{path}" fill="none" stroke="{BLACK}" stroke-width="2.4"/>')
    return "".join(out)


def text(x, y, s, size, fill, anchor="start", stroke=None, sw=0):
    st = f' stroke="{stroke}" stroke-width="{sw}" paint-order="stroke" stroke-linejoin="round"' if stroke else ""
    return (f'<text x="{_r(x)}" y="{_r(y)}" font-family="{FONT}" font-weight="600" font-size="{size:.0f}" '
            f'fill="{fill}" text-anchor="{anchor}"{st}>{s}</text>')


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
def balloon(cx, cy, rx, color, knot_to, letter=None):
    ry = rx * 1.22
    out = [f'<path d="M{cx:.1f},{cy + ry:.1f} C{cx - 8:.1f},{cy + ry + 30:.1f} {cx + 12:.1f},{cy + ry + 50:.1f} '
           f'{knot_to[0]:.1f},{knot_to[1]:.1f}" fill="none" stroke="{BLACK}" stroke-width="2"/>',
           f'<ellipse cx="{cx:.1f}" cy="{cy:.1f}" rx="{rx:.1f}" ry="{ry:.1f}" fill="{color}" stroke="{BLACK}" stroke-width="2.6"/>',
           f'<path d="M{cx - 6:.1f},{cy + ry + 8:.1f} L{cx + 6:.1f},{cy + ry + 8:.1f} L{cx:.1f},{cy + ry - 1:.1f} Z" fill="{color}" stroke="{BLACK}" stroke-width="2"/>',
           f'<ellipse cx="{cx - rx * 0.42:.1f}" cy="{cy - ry * 0.42:.1f}" rx="{rx * 0.16:.1f}" ry="{ry * 0.24:.1f}" fill="{WHITE}" transform="rotate(25 {cx - rx * 0.42:.1f} {cy - ry * 0.42:.1f})"/>']
    if letter:
        out.append(text(cx, cy + rx * 0.42, letter, rx * 1.15, WHITE, anchor="middle", stroke=BLACK, sw=3))
    return "".join(out)


def cake(cx, base, w, age=None):
    """Zweistöckige Torte mit Zuckerguss; Zahlenkerzen mit dem Alter, sonst bunte Kerzen."""
    out = []
    h1, h2 = w * 0.36, w * 0.28
    w1, w2 = w, w * 0.72
    y1, y2 = base - h1, base - h1 - h2
    out.append(f'<ellipse cx="{cx:.1f}" cy="{base + 4:.1f}" rx="{w * 0.62:.1f}" ry="{w * 0.06:.1f}" fill="{WHITE}" stroke="{BLACK}" stroke-width="2.6"/>')
    for (yy, ww, hh, body, dots) in ((y1, w1, h1, RED, YELLOW), (y2, w2, h2, YELLOW, BLUE)):
        x0 = cx - ww / 2
        out.append(f'<rect x="{x0:.1f}" y="{yy:.1f}" width="{ww:.1f}" height="{hh:.1f}" rx="5" fill="{body}" stroke="{BLACK}" stroke-width="2.6"/>')
        # Zuckerguss mit Tropfen
        n = 7
        d = [f"M{x0:.1f},{yy + 2:.1f}"]
        for k in range(n):
            xa, xb = x0 + ww * k / n, x0 + ww * (k + 1) / n
            drop = hh * (0.42 if k % 2 == 0 else 0.26)
            d.append(f"L{xa + (xb - xa) * 0.15:.1f},{yy + 6:.1f} Q{(xa + xb) / 2:.1f},{yy + drop * 1.6:.1f} {xb - (xb - xa) * 0.15:.1f},{yy + 6:.1f}")
        d.append(f"L{x0 + ww:.1f},{yy + 2:.1f} L{x0 + ww:.1f},{yy - 1:.1f} L{x0:.1f},{yy - 1:.1f} Z")
        out.append(f'<path d="{" ".join(d)}" fill="{WHITE}" stroke="{BLACK}" stroke-width="2.2" stroke-linejoin="round"/>')
        for k in range(5):
            out.append(f'<circle cx="{x0 + ww * (k + 0.5) / 5:.1f}" cy="{yy + hh * 0.74:.1f}" r="{w * 0.022:.1f}" fill="{dots}"/>')

    def flame(x, y, s):
        return (f'<path d="M{x:.1f},{y - s * 1.9:.1f} C{x + s:.1f},{y - s:.1f} {x + s * 0.8:.1f},{y:.1f} {x:.1f},{y:.1f} '
                f'C{x - s * 0.8:.1f},{y:.1f} {x - s:.1f},{y - s:.1f} {x:.1f},{y - s * 1.9:.1f} Z" fill="{YELLOW}" stroke="{BLACK}" stroke-width="1.8"/>'
                f'<path d="M{x:.1f},{y - s * 0.95:.1f} C{x + s * 0.4:.1f},{y - s * 0.5:.1f} {x + s * 0.35:.1f},{y - s * 0.05:.1f} {x:.1f},{y - s * 0.05:.1f} '
                f'C{x - s * 0.35:.1f},{y - s * 0.05:.1f} {x - s * 0.4:.1f},{y - s * 0.5:.1f} {x:.1f},{y - s * 0.95:.1f} Z" fill="{RED}"/>')
    if age is not None and 0 < age < 130:
        digits = str(age)
        size = w * (0.5 if len(digits) < 3 else 0.38)
        step = size * 0.62
        x0 = cx - step * (len(digits) - 1) / 2
        for i, dg in enumerate(digits):
            x = x0 + i * step
            out.append(f'<rect x="{x - 1.5:.1f}" y="{y2 - size * 0.95:.1f}" width="3" height="{size * 0.16:.1f}" fill="{BLACK}"/>')
            out.append(text(x, y2 - 2, dg, size, BLUE, anchor="middle", stroke=BLACK, sw=3.2))
            out.append(flame(x, y2 - size * 0.92, w * 0.045))
    else:
        for k in range(5):
            x = cx - w2 * 0.36 + w2 * 0.72 * k / 4
            ch = w * 0.2
            c = (RED, BLUE, GREEN, BLUE, RED)[k]
            out.append(f'<rect x="{x - w * 0.022:.1f}" y="{y2 - ch:.1f}" width="{w * 0.044:.1f}" height="{ch:.1f}" fill="{c}" stroke="{BLACK}" stroke-width="1.8"/>')
            for j in range(3):
                out.append(f'<line x1="{x - w * 0.022:.1f}" y1="{y2 - ch * (0.25 + 0.25 * j):.1f}" x2="{x + w * 0.022:.1f}" '
                           f'y2="{y2 - ch * (0.15 + 0.25 * j):.1f}" stroke="{WHITE}" stroke-width="2"/>')
            out.append(flame(x, y2 - ch - 2, w * 0.04))
    return "".join(out)


def confetti(W, H, n, rnd, keep_out=()):
    out = []
    cols = (RED, YELLOW, BLUE, GREEN)
    placed = 0
    for _ in range(n * 4):
        if placed >= n:
            break
        x, y = rnd.uniform(6, W - 6), rnd.uniform(6, H - 6)
        if any(x0 <= x <= x1 and y0 <= y <= y1 for x0, y0, x1, y1 in keep_out):
            continue
        placed += 1
        c, kind = rnd.choice(cols), rnd.random()
        rot = rnd.uniform(0, 180)
        if kind < 0.45:
            out.append(f'<rect x="{x - 5:.0f}" y="{y - 2.5:.0f}" width="10" height="5" fill="{c}" transform="rotate({rot:.0f} {x:.0f} {y:.0f})"/>')
        elif kind < 0.75:
            out.append(f'<circle cx="{x:.0f}" cy="{y:.0f}" r="3.6" fill="{c}"/>')
        else:  # Luftschlangen-Schnipsel
            out.append(f'<path d="M{x - 8:.0f},{y:.0f} q4,-7 8,0 t8,0" fill="none" stroke="{c}" stroke-width="2.6" '
                       f'stroke-linecap="round" transform="rotate({rot:.0f} {x:.0f} {y:.0f})"/>')
    return "".join(out)


def scene_geburtstag(W, H, names, age=None, seed=0):
    rnd = random.Random(seed)
    port = W < H * 1.6
    out = [f'<svg viewBox="0 0 {W} {H}" class="fest-svg" xmlns="http://www.w3.org/2000/svg">',
           f'<rect width="{W}" height="{H}" fill="{WHITE}"/>']
    if not port:
        cake_c, cake_b, cake_w = W * 0.8, H - 22, W * 0.25
        bal_x, bal_y = W * 0.14, H * 0.38
        text_box = (W * 0.25, H * 0.3, W * 0.64, H * 0.82)
    else:
        cake_c, cake_b, cake_w = W * 0.68, H - 18, W * 0.42
        bal_x, bal_y = W * 0.2, H * 0.62
        text_box = (W * 0.04, H * 0.16, W * 0.96, H * 0.44)
    keep = [text_box, (cake_c - cake_w * 0.65, cake_b - cake_w * 1.3, cake_c + cake_w * 0.65, H),
            (bal_x - 60, bal_y - 60, bal_x + 70, H)]
    out.append(confetti(W, H, int(70 * W / 800) + 10, rnd, keep_out=keep))
    out.append(bunting(W, -4, 22 if not port else 26, [RED, YELLOW, BLUE, GREEN], n_swags=2 if not port else 1,
                       per=8 if not port else 9))
    # Luftballons (gebündelt), auf dem größten die Initiale
    knot = (bal_x + 6, H - 14)
    first = names[0] if names else ""
    for (dx, dy, r, c, letter) in ((-6, 8, 30, BLUE, None), (44, -26, 32, GREEN, None), (-30, -52, 38, RED, first[:1] or None)):
        out.append(balloon(bal_x + dx, bal_y + dy, r if not port else r * 0.9, c, knot, letter))
    out.append(f'<path d="M{knot[0] - 9:.0f},{knot[1] - 6:.0f} L{knot[0]:.0f},{knot[1]:.0f} L{knot[0] - 9:.0f},{knot[1] + 6:.0f} Z '
               f'M{knot[0] + 9:.0f},{knot[1] - 6:.0f} L{knot[0]:.0f},{knot[1]:.0f} L{knot[0] + 9:.0f},{knot[1] + 6:.0f} Z" '
               f'fill="{RED}" stroke="{BLACK}" stroke-width="1.8"/>')
    out.append(cake(cake_c, cake_b, cake_w, age if len(names) == 1 else None))
    # Gruß
    who = " und ".join(names) if len(names) <= 2 else ", ".join(names[:-1]) + " und " + names[-1]
    x0, y0, x1, y1 = text_box
    big = 58 if not port else 46
    if len(who) > 9:
        big = max(34, big - (len(who) - 9) * 2.2)
    cx = (x0 + x1) / 2
    out.append(text(cx, y0 + 50 if not port else y0 + 40, "Alles Gute,", 40 if not port else 34, BLACK, anchor="middle"))
    out.append(text(cx, y0 + 50 + big + 4 if not port else y0 + 40 + big + 4, f"{who}!", big, RED, anchor="middle"))
    if age is not None and len(names) == 1:
        out.append(text(cx, y0 + 50 + big + 46 if not port else y0 + 40 + big + 40, f"{age} Jahre", 28 if not port else 24, BLACK, anchor="middle"))
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
BDAY_VIEW_READY = False  # Geburtstagsbild: Gestaltung noch nicht freigegeben – bis dahin nur der Gruß im Kopf
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
