"""Livestream-Karte (seit 1.25, Variante A): Während eines Termins „Ratssitzung“ steht oben in der
Terminspalte eine rot gerahmte Karte mit QR-Code, der zum Livestream der Sitzung führt – so kann
im Haushalt jemand mit dem Handy mitschauen. Stichwörter und Adresse sind einstellbar (z. B. auch
Bezirksvertretung). Nur in der normalen Ansicht; ohne laufende Sitzung bleibt das Bild pixelgleich.

Adresse: Die Stadt Bonn überträgt Rat und Bezirksvertretungen auf YouTube und auf
www.bonn.de/livestream; der YouTube-Link wechselt mit jeder Sitzung, die Seite der Stadt bleibt
und verlinkt am Sitzungstag den Stream. Deshalb führt der QR-Code standardmäßig dorthin.

QR-Code: `lib/segno` (reine Python-Kopie von segno 1.6.6, BSD-Lizenz, keine Installation auf dem
Pi). Das SVG hat ein Modul = eine Einheit der viewBox; die Größe in Pixeln setzt `fitQr()` im
Template auf ein ganzzahliges Vielfaches, damit jedes Modul auf E-Ink gleich breit ist
(ungleich breite Module erschweren das Scannen).
"""
from html import escape

try:  # als Paket im InkyPi-Plugin-Ordner
    from .lib import segno
except ImportError:  # direkt aus dem Ordner (Tests)
    from lib import segno

DEFAULT_WORDS = "Ratssitzung"
DEFAULT_URL = "https://www.bonn.de/livestream"
QUIET = 2  # Ruhezone in Modulen (Norm: 4; die weiße Karte drumherum gibt noch mehr Rand)


def normalize_url(text):
    """Adresse aus der Einstellung: leer → Standard, ohne Schema → https:// davor."""
    u = (text or "").strip()
    if not u:
        return DEFAULT_URL
    if "://" not in u:
        u = "https://" + u
    return u


def _hm(dt):
    return f"{dt.hour}:{dt.minute:02d}"


def matches(title, words):
    """Passt der Termintitel zu einem der Stichwörter (Komma-Liste, ohne Groß/Klein)?"""
    t = (title or "").lower()
    return any(w.strip().lower() in t for w in (words or "").split(",") if w.strip())


def running(events, words, now):
    """Der laufende Termin mit Stichwort (nicht ganztägig), sonst None. Bei mehreren der früheste."""
    hits = [ev for ev in events or []
            if not ev.get("all_day") and matches(ev.get("title"), words)
            and ev["source"]["start"] <= now < ev["source"]["end"]]
    return min(hits, key=lambda ev: ev["source"]["start"]) if hits else None


def short_url(url):
    """Zum Abtippen: ohne https:// und www., ohne Schrägstrich am Ende."""
    u = (url or "").strip()
    for p in ("https://", "http://"):
        if u.lower().startswith(p):
            u = u[len(p):]
    if u.lower().startswith("www."):
        u = u[4:]
    return u.rstrip("/")


def qr_svg(url, cls="qr"):
    """QR-Code als Inline-SVG (schwarze Module auf weißem Grund, auch bei dunklem Hintergrund) und
    Kantenlänge in Modulen samt Ruhezone. Fehlerkorrektur mindestens M; segno erhöht sie, solange
    die Version gleich bleibt."""
    qr = segno.make(url, error="m", micro=False)
    rows = list(qr.matrix)
    n = len(rows)
    size = n + 2 * QUIET
    parts = []
    for y, row in enumerate(rows):  # waagerechte Läufe dunkler Module → kurzer Pfad
        x = 0
        while x < n:
            if row[x]:
                start = x
                while x < n and row[x]:
                    x += 1
                parts.append(f"M{start + QUIET} {y + QUIET}h{x - start}v1h{start - x}z")
            else:
                x += 1
    svg = (f'<svg class="{escape(cls)}" data-n="{size}" viewBox="0 0 {size} {size}" '
           f'shape-rendering="crispEdges" aria-label="QR-Code: {escape(url)}">'
           f'<rect width="{size}" height="{size}" fill="#fff"/>'
           f'<path d="{"".join(parts)}" fill="#000"/></svg>')
    return svg, size


def card(events, words, url, now):
    """Daten der Karte für den laufenden Termin, sonst None."""
    ev = running(events, words, now)
    if not ev:
        return None
    href = normalize_url(url)
    svg, n = qr_svg(href)
    end = ev["source"]["end"]
    # Endet die Sitzung erst morgen (ungewöhnlich), steht das Datum dabei
    until = f"bis {_hm(end)}" if end.date() == now.date() else f"bis {end.day}.{end.month}. {_hm(end)}"
    return {"title": ev["title"], "until": until, "href": href, "url": short_url(href), "svg": svg, "n": n}


def boundaries(events, words, now):
    """Beginn und Ende der heutigen Termine mit Stichwort (für den Bild-Cache, nur mit Zug aktiv)."""
    out = []
    for ev in events or []:
        if ev.get("all_day") or not matches(ev.get("title"), words):
            continue
        out += [t for t in (ev["source"]["start"], ev["source"]["end"]) if t > now]
    return out
