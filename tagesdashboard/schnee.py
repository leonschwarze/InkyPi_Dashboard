"""
Schnee-Radar (seit 1.42): Schnee-Karte, Schnee-Stimmung und „Wo liegt Schnee?“.

Leons Wahl aus den Vorschlägen vom 23.11.: A Schnee-Karte (Alltag), D Schnee-Stimmung (Flocken in der
Tageskurve, Schneekappen im Nachtbild, „Schnee Do, Fr“ im Kopf der Wochenvorschau, weiße Weihnachten) und
C „Wo liegt Schnee?“ als Zeile in der Wochenvorschau.

Woher die Daten kommen
----------------------
* OB und WANN es in Bonn schneit, kommt wie immer aus Bright Sky (DWD MOSMIX: Modell, statistisch an
  Stationsmessungen korrigiert). Eine Stunde zählt als Schnee, wenn Niederschlag fällt (≥ RAIN_MM) und
  Bright Sky „snow“ oder „sleet“ meldet (`condition` oder `icon`). Nur dann gibt es eine Schnee-Karte.
* WIE VIEL (Zentimeter), die Schneefallgrenze und die Schneehöhe kommen von Open-Meteo, und zwar über die
  DWD-Schnittstelle (ICON-D2 mit ~2 km für zwei Tage, dahinter ICON-EU und ICON global):
    https://api.open-meteo.com/v1/dwd-icon?latitude=50.73,51.18,…&longitude=7.10,8.49,…
        &hourly=snowfall,snow_depth,snowfall_height,temperature_2m,precipitation
        &timeformat=unixtime&timezone=GMT&past_days=1&forecast_days=7
  Mehrere Orte in EINER Anfrage (Komma-Listen) → Antwort ist eine Liste, je Ort ein Eintrag
  {"elevation", "hourly": {"time": [...], "snowfall": [...] (cm, Summe der Stunde davor),
  "snow_depth": [...] (m), "snowfall_height": [...] (m über NN), ...}}. Ohne Schlüssel.
* Die Zentimeter sind umgerechnet, nicht gemessen: Open-Meteo rechnet 0,7 cm je mm Schmelzwasser. Nasser
  Schnee um 0 °C (in Bonn der Normalfall) ergibt eher 1 cm je mm. Deshalb zeigt die Karte eine Spanne
  von `cm` bis `cm / 0,7` („2–3 cm“), nie eine genaue Zahl. Die Schneehöhe ist ein Modellwert, keine Messung
  („bleibt liegen“ deshalb erst ab LIE_CM).

Orte der Umland-Zeile (von hoch nach tief, Bonn = Wetter-Ort kommt als letzter dazu):
  Winterberg = Kahler Asten (842 m), Hohe Acht (747 m, höchster Berg der Eifel), Großer Ölberg (460 m,
  höchster Berg des Siebengebirges).

Abgefragt wird nur, wenn es etwas zu sagen geben kann: normale Ansicht nur, wenn Bright Sky in den nächsten
48 Stunden oder am Fokustag Schnee meldet; Nachtbild nur in der Schneesaison (Oktober bis April) und wenn es
kalt genug war; Wochenvorschau in der Schneesaison. Zwischenspeicher 30 Minuten (auch für Fehlschläge).
Statusname „Schnee“. Aus der Claude-Umgebung nicht erreichbar – getestet gegen dev/mock_schnee.py.
"""

import logging
import math
import time as _time
from datetime import date, datetime, timedelta, timezone

import requests

try:
    from . import status
except ImportError:  # Tests importieren die Module ohne Paket
    import status

logger = logging.getLogger(__name__)

URL = "https://api.open-meteo.com/v1/dwd-icon"
HOURLY = "snowfall,snow_depth,snowfall_height,temperature_2m,precipitation"
HEADERS = {"User-Agent": "InkyPi-Tagesdashboard/1.42 (privates E-Ink-Display; github.com/leonschwarze/InkyPi_Dashboard)"}
STATUS_NAME = "Schnee"
TIMEOUT = 20
CACHE_MIN = 30

# (Anzeigename, Breite, Länge) – von hoch nach tief; der Wetter-Ort kommt als letzter dazu
PLACES = [
    ("Winterberg", 51.1794, 8.4889),   # Kahler Asten, 842 m
    ("Hohe Acht", 50.3858, 7.0111),    # 747 m
    ("Ölberg", 50.6822, 7.2483),       # Großer Ölberg, 460 m
]
SEASON = (10, 11, 12, 1, 2, 3, 4)
RAIN_MM = 0.1          # ab so viel Niederschlag in der Stunde zählt eine Schneestunde (wie Glätte/Regen)
SNOW = {"snow", "sleet"}
HORIZON = timedelta(hours=48)
MERGE_GAP = timedelta(hours=3)   # Pausen bis 3 h gehören zum selben Schneefall
CM_PER_MM = 0.7        # Umrechnung von Open-Meteo; nasser Schnee eher 1,0 → obere Grenze cm / 0,7
LIE_CM = 1.0           # ab so viel Schneehöhe (Modell) „bleibt liegen“, Schneekappen, Umland-Zeile
VALLEY_M = 100         # Schneefallgrenze höchstens so weit über dem Wetter-Ort: „bis ins Rheintal“
FRESH_CM = 2.0         # erwarteter Neuschnee in der Woche, ab dem die Umland-Zeile ihn nennt / erscheint
STRIP_FULL_CM = 2.0    # cm je Stunde = voller Balken im Flockenband
STRIP_MAX = 24         # höchstens so viele Stunden im Band
COLD_C = 3.0           # Nachtbild: nur fragen, wenn es in den letzten 2 Tagen so kalt war
KURZ = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]

_cache = {}  # Schlüssel → (monotonic, daten | None)


# ----------------------------------------------------------------------
# Bright Sky: Schneestunden
# ----------------------------------------------------------------------
def is_snow(r, min_mm=RAIN_MM):
    """Schneestunde nach Bright Sky (Niederschlag und „snow“/„sleet“)."""
    return (r.get("precipitation") or 0) >= min_mm and (r.get("condition") in SNOW or r.get("icon") in SNOW)


def snow_soon(records, now, focus=None):
    """Lohnt sich die Abfrage für die normale Ansicht? Schnee in den nächsten 48 h oder am Fokustag."""
    return any(is_snow(r) for r in records
               if (now - timedelta(hours=1) < r["dt"] <= now + HORIZON)
               or (focus is not None and r["dt"].date() == focus))


def in_season(d):
    return d.month in SEASON


def was_cold(records, now):
    """Nachtbild: Kann überhaupt Schnee liegen? (letzte 48 h bis Nachtende einmal ≤ COLD_C)"""
    return any((r.get("temperature") if r.get("temperature") is not None else 99) <= COLD_C
               for r in records if now - timedelta(hours=48) <= r["dt"] <= now + timedelta(hours=12))


# ----------------------------------------------------------------------
# Open-Meteo (DWD ICON)
# ----------------------------------------------------------------------
def _num(v, scale=1.0):
    try:
        return None if v is None else float(v) * scale
    except (TypeError, ValueError):
        return None


def parse(data, names, tz):
    """Antwort → {Name: {"elev": m, "hours": [{"dt", "snow" cm, "depth" cm, "line" m, "temp", "precip"}]}}."""
    items = data if isinstance(data, list) else [data]
    if len(items) != len(names):
        raise RuntimeError(f"Open-Meteo: {len(items)} Orte statt {len(names)}")
    out = {}
    for name, it in zip(names, items):
        h = (it or {}).get("hourly") or {}
        times = h.get("time") or []
        col = lambda k: h.get(k) or [None] * len(times)  # noqa: E731
        hours = []
        for t, sf, sd, sl, tt, pr in zip(times, col("snowfall"), col("snow_depth"), col("snowfall_height"),
                                         col("temperature_2m"), col("precipitation")):
            try:
                dt = datetime.fromtimestamp(int(t), timezone.utc).astimezone(tz)
            except (TypeError, ValueError, OverflowError):
                continue
            hours.append({"dt": dt, "snow": _num(sf), "depth": _num(sd, 100.0), "line": _num(sl),
                          "temp": _num(tt), "precip": _num(pr)})
        out[name] = {"elev": _num((it or {}).get("elevation")), "hours": hours}
    return out


def fetch(places, tz, session=None):
    """places: [(Name, Breite, Länge)] → parse(...)"""
    session = session or requests.Session()
    params = {
        "latitude": ",".join(f"{p[1]:.4f}" for p in places),
        "longitude": ",".join(f"{p[2]:.4f}" for p in places),
        "hourly": HOURLY, "timeformat": "unixtime", "timezone": "GMT", "past_days": 1, "forecast_days": 7,
    }
    r = session.get(URL, params=params, headers=HEADERS, timeout=TIMEOUT)
    if r.status_code != 200:
        raise RuntimeError(f"Open-Meteo: HTTP {r.status_code}")
    return parse(r.json(), [p[0] for p in places], tz)


def load(lat, lon, tz, home_name="Bonn", session=None):
    """Schneedaten für den Wetter-Ort und die Umlandorte oder None (Zusatz: nie das Bild verlieren)."""
    places = PLACES + [(home_name or "Bonn", lat, lon)]
    key = (round(lat, 3), round(lon, 3), home_name)
    status.use(STATUS_NAME)
    hit = _cache.get(key)
    if hit and _time.monotonic() - hit[0] < CACHE_MIN * 60:
        return hit[1]
    try:
        data = fetch(places, tz, session)
        data = {"places": data, "home": places[-1][0]}
        status.ok(STATUS_NAME)
        logger.info("Schnee: Open-Meteo %s", ", ".join(
            f"{n} {depth_now(data, n, datetime.now(tz)):.0f} cm" for n, *_ in places))
    except Exception as exc:  # Zusatz: nie das ganze Bild verlieren
        logger.warning("Schnee: Open-Meteo nicht verfügbar: %s", exc)
        status.fail(STATUS_NAME, exc)
        data = None
    _cache[key] = (_time.monotonic(), data)
    return data


def reset():
    """Zwischenspeicher leeren (Tests)."""
    _cache.clear()


def _hours(data, name):
    return ((data or {}).get("places", {}).get(name) or {}).get("hours") or []


def home_hours(data):
    return _hours(data, (data or {}).get("home"))


def depth_now(data, name, now):
    """Schneehöhe (cm, Modell) zur Stunde von now – 0 ohne Daten."""
    hours = [h for h in _hours(data, name) if h["depth"] is not None and h["dt"] <= now + timedelta(minutes=59)]
    return hours[-1]["depth"] if hours else 0.0


def snowfall(hours, a, b):
    """Summe des Schneefalls (cm) der Stunden mit a < dt ≤ b, None ohne Werte."""
    vals = [h["snow"] for h in hours if a < h["dt"] <= b and h["snow"] is not None]
    return sum(vals) if vals else None


# ----------------------------------------------------------------------
# Texte
# ----------------------------------------------------------------------
def range_text(cm):
    """„2–3 cm“ (Open-Meteo-Wert bis Wert / 0,7), „< 1 cm“, None bei (fast) nichts."""
    if cm is None or cm < 0.3:
        return None
    hi = cm / CM_PER_MM
    if hi < 1:
        return "< 1 cm"
    a = max(1, round(cm))
    b = max(a, round(hi))
    return f"{a} cm" if a == b else f"{a}–{b} cm"


def _de(x):
    return f"{x:.0f}".replace("-", "−")


def _day_word(start, now):
    if start.date() == now.date():
        return ""
    if start.date() == now.date() + timedelta(days=1):
        return "heute Nacht" if start.hour < 6 and now.hour >= 18 else "morgen"
    return KURZ[start.weekday()]


def episode(records, now):
    """Erster Schneefall in den nächsten 48 h nach Bright Sky: (Beginn, Ende, Datensätze, offen) oder None.
    Bright-Sky-Stunden gelten für die Stunde VOR dem Zeitstempel (Datensatz 4:00 = Schnee 3–4 Uhr)."""
    snowy = [r for r in records if now < r["dt"] <= now + HORIZON and is_snow(r)]
    if not snowy:
        return None
    group = [snowy[0]]
    for r in snowy[1:]:
        if r["dt"] - group[-1]["dt"] > MERGE_GAP:
            break
        group.append(r)
    # Uhrzeiten wie überall im Dashboard nach dem Zeitstempel (Tageskurve „Schnee 17–23 Uhr“): start = erster,
    # end = letzter Schnee-Datensatz. Es schneit also schon ab start − 1 h (dafür `begun` in card()).
    start, end = group[0]["dt"], group[-1]["dt"]
    open_end = end >= now + HORIZON - timedelta(hours=1)
    return start, end, group, open_end


def card(records, data, now):
    """Schnee-Karte (Variante A) oder None.

    {"top": "Schnee morgen 3–9 Uhr", "sub": "bleibt liegen · bis ins Rheintal", "badge": "2–3 cm" | "ab 350 m" | None,
     "start", "end", "strip": {"svg", "ticks"} | None, "cm": float | None, "line": m | None, "lies": bool}
    """
    ep = episode(records, now)
    if not ep:
        return None
    start, end, group, open_end = ep
    # Kopfzeile
    if start - timedelta(hours=1) <= now:  # der erste Datensatz gilt für die Stunde davor: es schneit schon
        if open_end:
            top = "Schnee hält an"
        else:
            dw = _day_word(end - timedelta(minutes=1), now)
            top = f"Schnee bis etwa {(dw + ' ') if dw else ''}{end.hour or 24} Uhr"
    else:
        dw = _day_word(start, now)
        short = not open_end and end - start <= timedelta(hours=12)
        when = f"{start.hour}–{end.hour or 24} Uhr" if short else f"ab {start.hour} Uhr"
        top = "Schnee " + (dw + " " if dw else "") + when
    # Menge, Schneefallgrenze, liegen bleiben (Open-Meteo)
    hours = home_hours(data)
    elev = ((data or {}).get("places", {}).get((data or {}).get("home")) or {}).get("elev")
    # ab jetzt (wenn es schon schneit) bzw. eine Stunde Spielraum vor dem Beginn – die Modelle liegen oft eine Stunde auseinander
    begun = start - timedelta(hours=1) <= now
    cm = snowfall(hours, now if begun else start - timedelta(hours=2), end + timedelta(hours=1)) if hours else None
    lines = [h["line"] for h in hours if start <= h["dt"] <= end and h["line"] is not None]
    line = min(lines) if lines else None
    depths = [h["depth"] for h in hours if end <= h["dt"] <= end + timedelta(hours=6) and h["depth"] is not None]
    lies = bool(depths) and max(depths) >= LIE_CM
    sub = []
    if line is not None and elev is not None and line > elev + VALLEY_M:
        sub = ["in Bonn eher Schneeregen"]  # das Abzeichen nennt dann die Höhe, ab der es schneit
    else:
        if lies:
            sub.append("bleibt liegen")
        elif cm is not None and cm >= 0.3:
            sub.append("taut wohl gleich weg")
        if line is not None:
            sub.append("bis ins Rheintal")
    if not hours:  # ohne Open-Meteo: wenigstens die Temperatur aus Bright Sky
        temps = [r["temperature"] for r in group if r.get("temperature") is not None]
        if temps:
            lo, hi = min(temps), max(temps)
            sub.append(f"bei {_de(lo)}°" if round(lo) == round(hi) else f"bei {_de(lo)} bis {_de(hi)}°")
    sleety = bool(sub) and sub[0].startswith("in Bonn eher")
    badge = f"ab {round(line / 50) * 50:.0f} m" if sleety else range_text(cm)
    if cm is not None and badge is None:
        sub.insert(0, "kaum Neuschnee")
    return {"top": top, "sub": " · ".join(sub), "badge": badge, "start": start, "end": end, "cm": cm,
            "line": line, "lies": lies, "strip": strip(records, hours, start - timedelta(hours=1), end)}


def strip(records, hours, start, end, width=240, height=40):
    """Flockenband: ein Balken je Stunde, von Beginn (start = Anfang der ersten Schneestunde) bis eine Stunde danach.
    Höhe = Schneefall in cm/Std. (Open-Meteo, STRIP_FULL_CM = voll); ohne Open-Meteo der Niederschlag."""
    a = start
    b = min(end + timedelta(hours=1), a + timedelta(hours=STRIP_MAX))
    slots = []
    t = a
    while t < b:
        t1 = t + timedelta(hours=1)
        bs = next((r for r in records if r["dt"] == t1), None)
        om = next((h for h in hours if h["dt"] == t1), None)
        snowy = bool(bs and is_snow(bs))
        v = om["snow"] if om and om["snow"] is not None else ((bs.get("precipitation") or 0) if snowy else 0)
        slots.append((t, v, snowy or v >= 0.1))
        t = t1
    if len(slots) < 3:
        return None
    n = len(slots)
    slot = width / n
    bars = []
    for i, (_, v, on) in enumerate(slots):
        if not on:
            continue
        h = height * max(min(v / STRIP_FULL_CM, 1.0), 0.28)
        bars.append(f'<rect class="sn-bar" x="{i * slot + slot * 0.12:.1f}" y="{height - h:.1f}" '
                    f'width="{slot * 0.76:.1f}" height="{h:.1f}"/>')
    step = 3 if n <= 12 else 6
    ticks = [{"x": i / n * 100, "text": f"{t.hour}"} for i, (t, _, _) in enumerate(slots)
             if t.hour % step == 0 and 6 < i / n * 100 < 90]
    svg = (f'<svg class="sn-strip" viewBox="0 0 {width} {height}" preserveAspectRatio="none">' + "".join(bars)
           + f'<line class="rd-axis" x1="0" y1="{height}" x2="{width}" y2="{height}" vector-effect="non-scaling-stroke"/>'
           + "</svg>")
    return {"svg": svg, "ticks": ticks}


def boundaries(c, now):
    """Fenstergrenzen für den Bild-Cache: Beginn („ab“ → „bis etwa“) und Ende des Schneefalls."""
    return [t for t in (c["start"] - timedelta(hours=1), c["end"]) if t and t > now] if c else []


# ----------------------------------------------------------------------
# Schnee-Stimmung (D)
# ----------------------------------------------------------------------
def graph_cm(data, d):
    """Schneefall je Stunde am Tag d (für die Kopfzeile der Tageskurve): {dt: cm}."""
    return {h["dt"]: h["snow"] for h in home_hours(data) if h["dt"].date() == d or
            h["dt"] == datetime.combine(d + timedelta(days=1), datetime.min.time(), h["dt"].tzinfo)}


def caps(data, now, end):
    """Nachtbild: Liegt in Bonn bis zum Ende der Nacht Schnee (Modell ≥ LIE_CM)? → Schneekappen."""
    vals = [h["depth"] for h in home_hours(data) if now - timedelta(minutes=59) <= h["dt"] <= end
            and h["depth"] is not None]
    return bool(vals) and max(vals) >= LIE_CM


PEAK = "Ölberg"  # höchster Gipfel im Nachtbild (460 m), einer der Orte in PLACES


def peaks(data, now, end):
    """Nachtbild (seit 1.43, „weiße Gipfel“): Liegt auf dem Ölberg zwischen jetzt und end Schnee (Modell ≥ LIE_CM)?
    Dann werden Drachenfels und Ölberg weiß – auch wenn in Bonn keiner liegt (caps). Tagsüber (end = now) auch
    Anlass für die Schlitten-Katze."""
    vals = [h["depth"] for h in _hours(data, PEAK) if now - timedelta(minutes=59) <= h["dt"] <= end
            and h["depth"] is not None]
    return bool(vals) and max(vals) >= LIE_CM


def snow_days(records, days):
    """Wochenvorschau: {Datum: "snow" | "mixed"} für Tage mit Schnee nach Bright Sky.
    "snow": mindestens die Hälfte der nassen Stunden ist Schnee (dann zählt der Tag nicht als Regen)."""
    out = {}
    for d in days:
        day = [r for r in records if r["dt"].date() == d]
        wet = [r for r in day if (r.get("precipitation") or 0) >= RAIN_MM]
        snowy = [r for r in wet if is_snow(r)]
        if snowy:
            out[d] = "snow" if len(snowy) * 2 >= len(wet) else "mixed"
    return out


def umland(data, now):
    """Zeile „Wo liegt Schnee?“ (Variante C) oder None.

    Je Ort die Schneehöhe jetzt (Modell) und, ab FRESH_CM, der erwartete Neuschnee bis zum Ende der Vorhersage
    in Klammern: „Winterberg 18 cm (+10) · Hohe Acht 4 cm · Ölberg – · Bonn –“. Nur, wenn irgendwo Schnee
    liegt oder welcher erwartet wird."""
    if not data:
        return None
    parts, any_snow = [], False
    names = [p[0] for p in PLACES] + [data.get("home")]
    for name in names:
        hours = _hours(data, name)
        if not hours:
            continue
        d = depth_now(data, name, now)
        fresh = snowfall(hours, now, now + timedelta(days=8)) or 0
        lies = d >= LIE_CM
        new = fresh >= FRESH_CM
        any_snow = any_snow or lies or new
        text = f"{name} {round(d)} cm" if lies else (f"{name} 0 cm" if new else f"{name} –")
        if new:
            text += f" (+{round(fresh)})"
        parts.append({"name": name, "depth": round(d) if lies else 0, "fresh": round(fresh) if new else 0,
                      "text": text})
    return {"parts": parts, "text": " · ".join(p["text"] for p in parts)} if any_snow and parts else None


XMAS_FROM = (12, 15)


def christmas(data, today, now):
    """Weiße Weihnachten in Bonn? (15.–24.12.) Text oder None.
    Meteorologisch: Schneedecke ≥ 1 cm am Morgen (7 Uhr) eines der drei Festtage. Modellwert."""
    if not (today.month == 12 and XMAS_FROM[1] <= today.day <= 24):
        return None
    hours = home_hours(data)
    if not hours:
        return None
    days = [date(today.year, 12, d) for d in (24, 25, 26)]
    mornings = [h for h in hours if h["dt"].date() in days and h["dt"].hour == 7 and h["depth"] is not None]
    if not mornings:
        return "Weiße Weihnachten? Noch zu weit für die Vorhersage"
    best = max(mornings, key=lambda h: h["depth"])
    if best["depth"] >= LIE_CM:
        return f"Weiße Weihnachten in Bonn: möglich · Modell {round(best['depth'])} cm am {best['dt'].day}.12."
    tz = hours[0]["dt"].tzinfo
    a = datetime.combine(date(today.year, 12, 23), datetime.min.time(), tz)
    fall = snowfall(hours, a, a + timedelta(days=4)) or 0
    if fall >= 0.5:
        return "Weiße Weihnachten in Bonn: eher Flocken als Schneedecke"
    return "Weiße Weihnachten in Bonn: eher nicht"


# ----------------------------------------------------------------------
# Schneekappen im Nachtbild (Geometrie, nachtgrafik.svg ruft das auf)
# ----------------------------------------------------------------------
def _points(path):
    """„M0,104 L0,86 …Z“ → [(x, y)] (nur M/L, wie die Stadt-Umrisse in nachtgrafik.CITY)."""
    pts = []
    for tok in path.replace("M", " ").replace("L", " ").replace("Z", " ").split():
        x, y = tok.split(",")
        pts.append((float(x), float(y)))
    return pts


def _inside(pts, x, y):
    c = False
    for (x0, y0), (x1, y1) in zip(pts, pts[1:] + pts[:1]):
        if (y0 > y) != (y1 > y) and x < (x1 - x0) * (y - y0) / (y1 - y0) + x0:
            c = not c
    return c


def roof_caps(path, base=104.0, thick=2.6, inset=0.9, max_slope=0.6):
    """Weiße Streifen auf den flachen Dächern eines Umrisses: je Kante, die oben liegt (darüber frei, darunter
    Gebäude) und höchstens max_slope steil ist. Der Streifen beginnt inset unter der Kante, damit oben eine
    schwarze Linie bleibt: Kantenpixel dann nur Schwarz/Weiß bzw. Schwarz/Blau, nie drei Farben (eink.py)."""
    pts = _points(path)
    out = []
    for (x0, y0), (x1, y1) in zip(pts, pts[1:] + pts[:1]):
        dx, dy = x1 - x0, y1 - y0
        if abs(dx) < 3 or abs(dy) > abs(dx) * max_slope or max(y0, y1) >= base - 1:
            continue
        mx, my = (x0 + x1) / 2, (y0 + y1) / 2
        if not (_inside(pts, mx, my + 1.5) and not _inside(pts, mx, my - 1.5)):
            continue
        a, b = (x0, y0), (x1, y1)
        if a[0] > b[0]:
            a, b = b, a
        # an den Enden etwas einrücken, damit der Streifen nicht über die Hauskante hinaussteht
        ax, bx = a[0] + 0.8, b[0] - 0.8
        ya = a[1] + (b[1] - a[1]) * (ax - a[0]) / (b[0] - a[0])
        yb = a[1] + (b[1] - a[1]) * (bx - a[0]) / (b[0] - a[0])
        out.append(f"M{ax:.1f},{ya + inset:.1f} L{bx:.1f},{yb + inset:.1f} L{bx:.1f},{yb + inset + thick:.1f} "
                   f"L{ax:.1f},{ya + inset + thick:.1f} Z")
    return out


def hill_cap(path, clip_id, thick=5.4, inset=1.0, foot=92):
    """Schnee auf dem Siebengebirge: der obere Umriss (ohne die senkrechte rechte Kante und die Grundlinie)
    weiß nachgezogen und auf die Berge beschnitten → weißer Saum innen an der Kammlinie."""
    top = path.split(" L300,104")[0]   # HILLS endet mit „… L300,104 Z“
    # clip-path an der Gruppe, die Verschiebung nur am Strich (sonst verschöbe sich der Zuschnitt mit)
    # zweiter Zuschnitt: nur oberhalb von `foot`, sonst liefe der Saum am Fuß der Berge bis ans Wasser
    return (f'<clipPath id="{clip_id}"><path d="{path}"/></clipPath>'
            f'<clipPath id="{clip_id}-f"><rect x="0" y="0" width="300" height="{foot}"/></clipPath>'
            f'<g clip-path="url(#{clip_id}-f)"><g clip-path="url(#{clip_id})"><path d="{top}" '
            f'transform="translate(0,{inset + thick / 2:.1f})" fill="none" stroke="#FFFFFF" stroke-width="{thick:.1f}"/>'
            f'</g></g>')
