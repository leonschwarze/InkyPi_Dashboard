"""
Eigenes SVG-Iconset für das DWD-Wetter-Plugin.

Alle Icons werden als Inline-SVG erzeugt (kein Download, keine Lizenzfragen)
und sind für E-Ink optimiert: kräftige Konturen, wenige, satte Flächenfarben.
Die Konturen verwenden ``currentColor`` und folgen damit automatisch der
Textfarbe aus den InkyPi-Stileinstellungen.

Wetter-Icons nutzen eine 64x64-ViewBox, Messwert-Icons eine 32x32-ViewBox.
"""

import math

# Farbpalette – bewusst nah an den Farben von Farb-E-Ink-Displays
# (Inky Impression / Spectra 6), damit beim Dithering wenig "Rauschen" entsteht.
SUN = "#FFC400"
SUN_DARK = "#FF8A00"
MOON = "#FFE27A"
CLOUD_LIGHT = "#FFFFFF"
CLOUD_GREY = "#C9D1D9"
CLOUD_DARK = "#8C98A4"
RAIN = "#1E6FD9"
ICE = "#5FB4FF"
BOLT = "#FFD400"
INK = "currentColor"

STROKE = 3.2  # Konturstärke in der 64er-ViewBox


def _svg(body, size=64, cls="wx-icon"):
    return (
        f'<svg class="{cls}" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size} {size}" '
        f'fill="none" stroke-linecap="round" stroke-linejoin="round">{body}</svg>'
    )


# --------------------------------------------------------------------------
# Grundformen
# --------------------------------------------------------------------------

def _sun(cx, cy, r, rays=True, ray_len=None, ray_gap=None):
    parts = []
    if rays:
        ray_len = ray_len if ray_len is not None else r * 0.55
        ray_gap = ray_gap if ray_gap is not None else r * 0.45
        for i in range(8):
            a = math.radians(i * 45)
            x1 = cx + math.cos(a) * (r + ray_gap)
            y1 = cy + math.sin(a) * (r + ray_gap)
            x2 = cx + math.cos(a) * (r + ray_gap + ray_len)
            y2 = cy + math.sin(a) * (r + ray_gap + ray_len)
            parts.append(
                f'<line x1="{x1:.2f}" y1="{y1:.2f}" x2="{x2:.2f}" y2="{y2:.2f}" '
                f'stroke="{SUN_DARK}" stroke-width="{STROKE}"/>'
            )
    parts.append(
        f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="{SUN}" stroke="{INK}" stroke-width="{STROKE}"/>'
    )
    return "".join(parts)


def _moon(cx, cy, r):
    """Sichelmond: Kreis, aus dem ein versetzter Kreis gleichen Radius 'ausgeschnitten' ist."""
    # Versatz des schneidenden Kreises
    dx, dy = r * 0.62, -r * 0.48
    d = math.hypot(dx, dy)
    # Schnittpunkte zweier Kreise mit gleichem Radius
    mx, my = cx + dx / 2, cy + dy / 2
    h = math.sqrt(max(r * r - (d / 2) ** 2, 0))
    ux, uy = -dy / d, dx / d
    p1 = (mx + ux * h, my + uy * h)
    p2 = (mx - ux * h, my - uy * h)
    path = (
        f"M{p1[0]:.2f},{p1[1]:.2f} "
        f"A{r},{r} 0 1 1 {p2[0]:.2f},{p2[1]:.2f} "
        f"A{r},{r} 0 0 0 {p1[0]:.2f},{p1[1]:.2f} Z"
    )
    return f'<path d="{path}" fill="{MOON}" stroke="{INK}" stroke-width="{STROKE}"/>'


def _cloud(x, y, s=1.0, fill=CLOUD_LIGHT):
    """Wolke; (x, y) = linke obere Ecke der 40x24-Grundform, s = Skalierung."""
    def p(px, py):
        return f"{x + px * s:.2f},{y + py * s:.2f}"

    r1, r2, r3 = 8 * s, 12 * s, 9.5 * s
    path = (
        f"M{p(9, 24)} "
        f"A{r1:.2f},{r1:.2f} 0 0 1 {p(8, 8)} "
        f"A{r2:.2f},{r2:.2f} 0 0 1 {p(30, 5.5)} "
        f"A{r3:.2f},{r3:.2f} 0 0 1 {p(32, 24)} Z"
    )
    return f'<path d="{path}" fill="{fill}" stroke="{INK}" stroke-width="{STROKE}"/>'


def _drop(x, y, s=1.0, fill=RAIN):
    """Regentropfen, Spitze bei (x, y)."""
    path = (
        f"M{x:.2f},{y:.2f} "
        f"C{x + 1.2 * s:.2f},{y + 2.6 * s:.2f} {x + 4 * s:.2f},{y + 4.6 * s:.2f} {x + 4 * s:.2f},{y + 7.2 * s:.2f} "
        f"A{4 * s:.2f},{4 * s:.2f} 0 0 1 {x - 4 * s:.2f},{y + 7.2 * s:.2f} "
        f"C{x - 4 * s:.2f},{y + 4.6 * s:.2f} {x - 1.2 * s:.2f},{y + 2.6 * s:.2f} {x:.2f},{y:.2f} Z"
    )
    return f'<path d="{path}" fill="{fill}" stroke="{INK}" stroke-width="{STROKE * 0.7:.2f}"/>'


def _streak(x, y, length=8):
    return (
        f'<line x1="{x}" y1="{y}" x2="{x - length * 0.35:.2f}" y2="{y + length}" '
        f'stroke="{RAIN}" stroke-width="{STROKE * 1.1:.2f}"/>'
    )


def _flake(cx, cy, r=4.5, color=RAIN):
    parts = []
    for i in range(3):
        a = math.radians(90 + i * 60)
        dx, dy = math.cos(a) * r, math.sin(a) * r
        parts.append(
            f'<line x1="{cx - dx:.2f}" y1="{cy - dy:.2f}" x2="{cx + dx:.2f}" y2="{cy + dy:.2f}" '
            f'stroke="{color}" stroke-width="{STROKE * 0.95:.2f}"/>'
        )
    return "".join(parts)


def _hailstone(cx, cy, r=3):
    return f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="{CLOUD_LIGHT}" stroke="{RAIN}" stroke-width="{STROKE * 0.8:.2f}"/>'


def _bolt(x, y, s=1.0):
    pts = [(6, 0), (0, 12), (5, 12), (2, 22), (12, 8), (7, 8), (10, 0)]
    d = " ".join(f"{x + px * s:.2f},{y + py * s:.2f}" for px, py in pts)
    return f'<polygon points="{d}" fill="{BOLT}" stroke="{INK}" stroke-width="{STROKE * 0.8:.2f}"/>'


def _fog_lines(y0, rows=3, x0=8, x1=56, gap=7):
    parts = []
    for i in range(rows):
        y = y0 + i * gap
        off = 6 if i % 2 else 0
        parts.append(
            f'<line x1="{x0 + off}" y1="{y}" x2="{x1 - 14 + off}" y2="{y}" stroke="{INK}" stroke-width="{STROKE}"/>'
            f'<line x1="{x1 - 8 + off}" y1="{y}" x2="{x1 + off - 2}" y2="{y}" stroke="{INK}" stroke-width="{STROKE}"/>'
        )
    return "".join(parts)


def _wind_lines(x=6, y=18, s=1.0, color=INK, sw=STROKE):
    def p(px, py):
        return f"{x + px * s:.2f},{y + py * s:.2f}"
    return (
        f'<path d="M{p(0, 10)} H{x + 34 * s:.2f} A{6 * s:.2f},{6 * s:.2f} 0 1 0 {p(28, 4)}" stroke="{color}" stroke-width="{sw}"/>'
        f'<path d="M{p(0, 19)} H{x + 44 * s:.2f} A{5 * s:.2f},{5 * s:.2f} 0 1 1 {p(40, 29)}" stroke="{color}" stroke-width="{sw}"/>'
        f'<path d="M{p(6, 28)} H{x + 24 * s:.2f}" stroke="{color}" stroke-width="{sw}"/>'
    )


# --------------------------------------------------------------------------
# Wetter-Icons (64x64)
# --------------------------------------------------------------------------

def _icon_clear_day():
    return _sun(32, 32, 13, ray_len=7, ray_gap=5)


def _icon_clear_night():
    return _moon(31, 33, 19) + (
        f'<path d="M50 10 l1.6 3.4 3.4 1.6 -3.4 1.6 -1.6 3.4 -1.6 -3.4 -3.4 -1.6 3.4 -1.6 Z" '
        f'fill="{MOON}" stroke="{INK}" stroke-width="1.6"/>'
    )


def _icon_partly_cloudy_day():
    return _sun(40, 22, 10, ray_len=5, ray_gap=4) + _cloud(6, 24, 1.15)


def _icon_partly_cloudy_night():
    return _moon(41, 21, 12) + _cloud(6, 25, 1.15)


def _icon_cloudy():
    return _cloud(16, 10, 1.0, CLOUD_GREY) + _cloud(4, 24, 1.15, CLOUD_LIGHT)


def _icon_fog():
    return _cloud(10, 6, 1.1, CLOUD_GREY) + _fog_lines(40, rows=3, gap=8)


def _icon_wind():
    return _wind_lines(6, 12, 1.15)


def _icon_rain():
    return (
        _cloud(6, 6, 1.3, CLOUD_GREY)
        + _drop(19, 41, 1.05) + _drop(32, 46, 1.05) + _drop(45, 41, 1.05)
    )


def _icon_drizzle():
    return (
        _cloud(6, 6, 1.3, CLOUD_GREY)
        + _drop(22, 43, 0.75) + _drop(42, 43, 0.75)
    )


def _icon_heavy_rain():
    return (
        _cloud(6, 4, 1.3, CLOUD_DARK)
        + _streak(17, 40, 12) + _streak(27, 42, 14) + _streak(37, 40, 12) + _streak(47, 42, 14)
    )


def _icon_showers_day():
    return (
        _sun(42, 18, 9, ray_len=4.5, ray_gap=3.5)
        + _cloud(5, 18, 1.15, CLOUD_LIGHT)
        + _drop(18, 48, 0.85) + _drop(30, 50, 0.85)
    )


def _icon_showers_night():
    return (
        _moon(43, 17, 10)
        + _cloud(5, 18, 1.15, CLOUD_LIGHT)
        + _drop(18, 48, 0.85) + _drop(30, 50, 0.85)
    )


def _icon_sleet():
    return (
        _cloud(6, 6, 1.3, CLOUD_GREY)
        + _drop(20, 41, 0.95) + _flake(33, 50, 5.5) + _drop(45, 41, 0.95)
    )


def _icon_snow():
    return (
        _cloud(6, 6, 1.3, CLOUD_GREY)
        + _flake(19, 46, 5.5) + _flake(32, 54, 5.5) + _flake(45, 46, 5.5)
    )


def _icon_hail():
    return (
        _cloud(6, 6, 1.3, CLOUD_GREY)
        + _hailstone(19, 44) + _hailstone(32, 51) + _hailstone(45, 44)
        + _hailstone(26, 57, 2.4) + _hailstone(39, 57, 2.4)
    )


def _icon_thunderstorm():
    return (
        _cloud(6, 4, 1.3, CLOUD_DARK)
        + _bolt(26, 33, 1.3)
        + _drop(15, 42, 0.8) + _drop(49, 42, 0.8)
    )


WEATHER_ICONS = {
    "clear-day": _icon_clear_day,
    "clear-night": _icon_clear_night,
    "partly-cloudy-day": _icon_partly_cloudy_day,
    "partly-cloudy-night": _icon_partly_cloudy_night,
    "cloudy": _icon_cloudy,
    "fog": _icon_fog,
    "wind": _icon_wind,
    "drizzle": _icon_drizzle,
    "rain": _icon_rain,
    "heavy-rain": _icon_heavy_rain,
    "showers-day": _icon_showers_day,
    "showers-night": _icon_showers_night,
    "sleet": _icon_sleet,
    "snow": _icon_snow,
    "hail": _icon_hail,
    "thunderstorm": _icon_thunderstorm,
}


def weather_icon(name, cls="wx-icon"):
    builder = WEATHER_ICONS.get(name) or WEATHER_ICONS["cloudy"]
    return _svg(builder(), 64, cls)


# --------------------------------------------------------------------------
# Messwert-Icons (32x32) – schlicht, einfarbig mit Akzent
# --------------------------------------------------------------------------

S = 2.4  # Konturstärke in der 32er-ViewBox


def _mi_wind():
    return _wind_lines(3, 4, 0.58, INK, S)


def _mi_gust():
    return (
        _wind_lines(2, 5, 0.5, INK, S)
        + f'<polygon points="22,14 30,14 25,21 29,21 19,31 22,23 18,23" fill="{BOLT}" stroke="{INK}" stroke-width="1.4"/>'
    )


def _mi_humidity():
    return (
        f'<path d="M16 3 C18 8 25 13 25 20 A9 9 0 0 1 7 20 C7 13 14 8 16 3 Z" fill="{ICE}" stroke="{INK}" stroke-width="{S}"/>'
        f'<path d="M11.5 20.5 A4.5 4.5 0 0 0 16 25" stroke="#FFFFFF" stroke-width="{S}"/>'
    )


def _mi_pressure():
    return (
        f'<circle cx="16" cy="17" r="12" fill="#FFFFFF" stroke="{INK}" stroke-width="{S}"/>'
        f'<line x1="16" y1="17" x2="22.5" y2="11" stroke="{SUN_DARK}" stroke-width="{S * 1.1:.2f}"/>'
        f'<circle cx="16" cy="17" r="2" fill="{INK}" stroke="none"/>'
        f'<line x1="8" y1="17" x2="10" y2="17" stroke="{INK}" stroke-width="{S}"/>'
        f'<line x1="16" y1="9" x2="16" y2="11" stroke="{INK}" stroke-width="{S}"/>'
        f'<line x1="24" y1="17" x2="22" y2="17" stroke="{INK}" stroke-width="{S}"/>'
    )


def _mi_precip():
    return (
        f'<path d="M3 16 A13 13 0 0 1 29 16 Q25.75 13 22.5 16 Q19.25 13 16 16 Q12.75 13 9.5 16 Q6.25 13 3 16 Z" '
        f'fill="{RAIN}" stroke="{INK}" stroke-width="{S}"/>'
        f'<path d="M16 16 V26 A3 3 0 0 1 10 26" stroke="{INK}" stroke-width="{S}"/>'
        f'<line x1="16" y1="3" x2="16" y2="1.5" stroke="{INK}" stroke-width="{S}"/>'
    )


def _mi_sunshine():
    return _sun(16, 16, 6.5, ray_len=4, ray_gap=3).replace(f'stroke-width="{STROKE}"', f'stroke-width="{S}"')


def _sun_horizon(arrow_up=True):
    arrow = "M16 2 L12 6 M16 2 L20 6 M16 2 V9" if arrow_up else "M16 9 L12 5 M16 9 L20 5 M16 9 V2"
    return (
        f'<path d="M7 24 A9 9 0 0 1 25 24 Z" fill="{SUN}" stroke="{INK}" stroke-width="{S}"/>'
        f'<line x1="2" y1="24" x2="30" y2="24" stroke="{INK}" stroke-width="{S}"/>'
        f'<line x1="8" y1="29" x2="24" y2="29" stroke="{INK}" stroke-width="{S}"/>'
        f'<path d="{arrow}" stroke="{SUN_DARK}" stroke-width="{S}"/>'
    )


def _mi_sunrise():
    return _sun_horizon(True)


def _mi_sunset():
    return _sun_horizon(False)


def _mi_sun_times():
    return (
        f'<path d="M5 22 A11 11 0 0 1 27 22 Z" fill="{SUN}" stroke="{INK}" stroke-width="{S}"/>'
        f'<line x1="1.5" y1="22" x2="30.5" y2="22" stroke="{INK}" stroke-width="{S}"/>'
        f'<path d="M6 28 H12 M20 28 H26" stroke="{INK}" stroke-width="{S}"/>'
        f'<path d="M16 2 V6 M7 5.5 L9.2 8.5 M25 5.5 L22.8 8.5" stroke="{SUN_DARK}" stroke-width="{S}"/>'
    )


def _mi_visibility():
    return (
        f'<path d="M2 16 Q16 3 30 16 Q16 29 2 16 Z" fill="#FFFFFF" stroke="{INK}" stroke-width="{S}"/>'
        f'<circle cx="16" cy="16" r="5.5" fill="{RAIN}" stroke="{INK}" stroke-width="{S}"/>'
        f'<circle cx="16" cy="16" r="1.8" fill="{INK}" stroke="none"/>'
    )


def _mi_dewpoint():
    return (
        f'<path d="M10 4 A3 3 0 0 1 16 4 V19 A6 6 0 1 1 10 19 Z" fill="#FFFFFF" stroke="{INK}" stroke-width="{S}"/>'
        f'<circle cx="13" cy="24" r="3" fill="{RAIN}" stroke="none"/>'
        f'<line x1="13" y1="21" x2="13" y2="10" stroke="{RAIN}" stroke-width="2.4"/>'
        f'<path d="M25 9 C26 11.5 29 13.5 29 16.5 A4 4 0 0 1 21 16.5 C21 13.5 24 11.5 25 9 Z" fill="{ICE}" stroke="{INK}" stroke-width="1.8"/>'
    )


def _mi_cloudcover():
    return _cloud(1, 5, 0.75, CLOUD_GREY).replace(f'stroke-width="{STROKE}"', f'stroke-width="{S}"')


def _mi_thermometer():
    return (
        f'<path d="M13 4 A3 3 0 0 1 19 4 V19 A6 6 0 1 1 13 19 Z" fill="#FFFFFF" stroke="{INK}" stroke-width="{S}"/>'
        f'<circle cx="16" cy="24" r="3" fill="{SUN_DARK}" stroke="none"/>'
        f'<line x1="16" y1="21" x2="16" y2="9" stroke="{SUN_DARK}" stroke-width="2.4"/>'
    )


def _mi_station():
    return (
        f'<path d="M16 30 C16 30 6 19 6 12 A10 10 0 0 1 26 12 C26 19 16 30 16 30 Z" fill="#FFFFFF" stroke="{INK}" stroke-width="{S}"/>'
        f'<circle cx="16" cy="12" r="3.5" fill="{RAIN}" stroke="{INK}" stroke-width="1.6"/>'
    )


METRIC_ICONS = {
    "wind": _mi_wind,
    "gust": _mi_gust,
    "humidity": _mi_humidity,
    "pressure": _mi_pressure,
    "precip": _mi_precip,
    "sunshine": _mi_sunshine,
    "sunrise": _mi_sunrise,
    "sunset": _mi_sunset,
    "sun_times": _mi_sun_times,
    "visibility": _mi_visibility,
    "dewpoint": _mi_dewpoint,
    "cloudcover": _mi_cloudcover,
    "thermometer": _mi_thermometer,
    "station": _mi_station,
}


def metric_icon(name, cls="mx-icon"):
    builder = METRIC_ICONS.get(name)
    if not builder:
        return ""
    return _svg(builder(), 32, cls)


def wind_arrow(direction_deg, cls="wind-arrow"):
    """Pfeil, der in die Richtung zeigt, in die der Wind weht (Meteorologie: Herkunft + 180°)."""
    if direction_deg is None:
        return ""
    rot = (float(direction_deg) + 180) % 360
    return (
        f'<svg class="{cls}" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">'
        f'<g transform="rotate({rot:.0f} 16 16)">'
        f'<path d="M16 3 L25 26 L16 20 L7 26 Z" fill="currentColor"/>'
        f"</g></svg>"
    )


def warning_icon(fill, mark="#000000", cls="warn-icon"):
    return (
        f'<svg class="{cls}" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" stroke-linejoin="round">'
        f'<path d="M16 2.5 L30 28.5 H2 Z" fill="{fill}" stroke="{mark}" stroke-width="2.6"/>'
        f'<line x1="16" y1="11" x2="16" y2="19.5" stroke="{mark}" stroke-width="3.4" stroke-linecap="round"/>'
        f'<circle cx="16" cy="24.2" r="2" fill="{mark}"/>'
        f"</svg>"
    )
