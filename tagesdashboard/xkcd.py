"""
Sonntagscomic (seit 1.40, Leons Wahl „Variante C“): Sonntags ohne weitere Termine steht in der
Terminspalte der neueste xkcd-Comic, links bleibt das Wetter.

Quelle
------
xkcd von Randall Munroe, Lizenz CC BY-NC 2.5 (Nennung von Autor und Quelle, nicht kommerziell).
Offizielle JSON-Schnittstelle ohne Schlüssel:
  https://xkcd.com/info.0.json           neuester Comic
  https://xkcd.com/<num>/info.0.json     ein bestimmter Comic
Felder: num, title, safe_title, alt (der „Mouseover“-Text), img (PNG/JPG unter imgs.xkcd.com),
year/month/day, link, extra_parts (nur bei interaktiven Comics). Neue Comics erscheinen montags,
mittwochs und freitags – sonntags ist der neueste also meist der vom Freitag. Viele neuere Comics gibt
es zusätzlich doppelt so groß („…_2x.png“); dann wird daraus verkleinert (schärfer).

Auswahl
-------
Viele xkcd sind sehr breit (vier Felder nebeneinander) oder sehr hoch. In der Terminspalte (quer etwa
330 × 330 px) wären sie nicht lesbar. Deshalb gilt: Der Comic muss mit mindestens MIN_SCALE seiner
normalen Größe (1x) in den Kasten passen; sonst kommt der vorherige, höchstens LOOKBACK Comics zurück.
Passt keiner, gibt es keinen Comic, und die Terminspalte bleibt wie immer.

Bild
----
Wird hier mit Pillow auf die geplante Breite verkleinert (das Template zeigt es dann 1:1, ohne dass
Chromium noch einmal glättet). Schwarz-weiße Comics werden hart auf Schwarz und Weiß gesetzt (Schwelle
GRAY_CUT); farbige bleiben, wie sie sind (eink.py rastet sie später ein).

Zwischenspeicher: neuester Comic 60 Minuten (Fehlschlag 30), Angaben und Bildgröße je Nummer dauerhaft,
die fertigen Bilder der letzten Runde (höchstens CANDIDATES) im Speicher.
"""

import base64
import io
import logging
import time as _time

import requests

try:
    from . import status
except ImportError:  # Tests importieren die Module ohne Paket
    import status

logger = logging.getLogger(__name__)

LATEST_URL = "https://xkcd.com/info.0.json"
NUM_URL = "https://xkcd.com/{num}/info.0.json"
HEADERS = {"User-Agent": "InkyPi-Tagesdashboard/1.40 (privates E-Ink-Display; github.com/leonschwarze/InkyPi_Dashboard)"}
STATUS_NAME = "xkcd"
CREDIT = "Randall Munroe"  # Nennung des Autors (Lizenz CC BY-NC 2.5); dev/render.py setzt hier „Beispiel“
TIMEOUT = 15
LATEST_MIN, FAIL_MIN = 60, 30
LOOKBACK = 8          # so viele Comics zurück wird gesucht, bis einer passt
CANDIDATES = 3        # so viele passende gehen ans Template (das wählt den ersten, der wirklich passt)
MIN_SCALE = 0.7       # kleiner als 70 % der normalen Größe wird die Handschrift auf E-Ink unleserlich
MAX_SCALE = 1.4       # größer nur, wenn es das Bild in doppelter Größe gibt
WEEKDAY = 6           # sonntags
GRAY_CUT = 160        # Schwelle Schwarz/Weiß nach dem Verkleinern

_latest = {}   # {"t": monotonic, "num": int | None}
_meta = {}     # num -> dict | None (None = gibt es nicht / nicht geeignet)
_sizes = {}    # img-URL -> (w1x, h1x, url des genutzten Bildes)
_picture = {}  # (url, breite) -> {src, w, h} – nur die Bilder der letzten Runde


def _get(session, url):
    return session.get(url, headers=HEADERS, timeout=TIMEOUT)


def latest_num(session):
    """Nummer des neuesten Comics (Zwischenspeicher 60 min, Fehlschlag 30 min)."""
    now = _time.monotonic()
    if _latest and now - _latest["t"] < 60 * (LATEST_MIN if _latest["num"] else FAIL_MIN):
        return _latest["num"]
    num = None
    try:
        r = _get(session, LATEST_URL)
        if r.status_code != 200:
            raise RuntimeError(f"HTTP {r.status_code}")
        data = r.json()
        num = int(data["num"])
        _meta[num] = clean_meta(data)
        status.ok(STATUS_NAME)
    except Exception as exc:
        logger.warning("xkcd: neuester Comic nicht abrufbar: %s", exc)
        status.fail(STATUS_NAME, exc)
    _latest.clear()
    _latest.update(t=now, num=num)
    return num


def clean_meta(data):
    """Nur die Felder, die wir brauchen; None für Comics, die sich nicht als Bild zeigen lassen."""
    img = str(data.get("img") or "")
    if "extra_parts" in data or not img.lower().endswith((".png", ".jpg", ".jpeg")):
        return None  # interaktiv, animiert oder ohne Bild
    return {"num": int(data["num"]), "title": str(data.get("safe_title") or data.get("title") or "").strip(),
            "alt": " ".join(str(data.get("alt") or "").split()), "img": img,
            "date": f"{data.get('day', '')}.{data.get('month', '')}.{data.get('year', '')}"}


def meta(num, session):
    if num not in _meta:
        r = _get(session, NUM_URL.format(num=num))
        if r.status_code == 404:  # gibt es nicht (z. B. Nummer 404)
            _meta[num] = None
        elif r.status_code != 200:
            raise RuntimeError(f"Comic {num}: HTTP {r.status_code}")
        else:
            _meta[num] = clean_meta(r.json())
    return _meta[num]


def double_url(url):
    """Adresse der doppelt großen Fassung: …/plate_maintenance.png → …/plate_maintenance_2x.png"""
    stem, dot, ext = url.rpartition(".")
    return f"{stem}_2x.{ext}" if dot and not stem.endswith("_2x") else None


def fetch_image(url, session):
    """Bild laden, wenn möglich in doppelter Größe. Gibt (PIL-Bild, Faktor 1 oder 2) zurück."""
    from PIL import Image
    for cand, factor in ((double_url(url), 2), (url, 1)):
        if not cand:
            continue
        r = _get(session, cand)
        if r.status_code == 200 and r.content:
            img = Image.open(io.BytesIO(r.content))
            img.load()
            return img, factor
        if factor == 1:
            raise RuntimeError(f"Bild {url}: HTTP {r.status_code}")
    raise RuntimeError(f"Bild {url} nicht ladbar")


def fit_scale(w1, h1, box_w, box_h, factor):
    """Maßstab (bezogen auf die normale Größe 1x), mit dem der Comic in den Kasten passt."""
    return min(box_w / w1, box_h / h1, MAX_SCALE if factor == 2 else 1.0)


def to_rgb(img):
    from PIL import Image
    if img.mode in ("RGBA", "LA", "P", "PA") or "transparency" in img.info:
        rgba = img.convert("RGBA")
        bg = Image.new("RGB", rgba.size, "white")
        bg.paste(rgba, mask=rgba.split()[3])
        return bg
    return img.convert("RGB")


def is_gray(rgb):
    """Schwarz-weißer Comic? (fast alle Pixel ohne Farbe – Kantenpixel von JPEGs dürfen leicht abweichen)"""
    small = rgb.copy()
    small.thumbnail((200, 200))
    raw = small.tobytes()  # R, G, B hintereinander (getdata ist ab Pillow 14 weg)
    px = zip(raw[0::3], raw[1::3], raw[2::3])
    colored = sum(1 for r, g, b in px if max(r, g, b) - min(r, g, b) > 40)
    return colored <= len(raw) // 3 * 0.002


def prepare(img, target_w):
    """Auf target_w Pixel Breite bringen, schwarz-weiße Comics hart auf Schwarz und Weiß setzen.

    Erprobt an Handschrift in 60–90 % Größe: Lanczos und Schwelle 160 lassen die Buchstaben offen.
    Linien vorher dicker zu machen (MinFilter) oder eine höhere Schwelle füllen die Buchstaben zu."""
    from PIL import Image
    rgb = to_rgb(img)
    ratio = target_w / rgb.width
    target_h = max(1, round(rgb.height * ratio))
    out = rgb.resize((target_w, target_h), Image.LANCZOS)
    if is_gray(out):
        out = out.convert("L").point(lambda v: 255 if v > GRAY_CUT else 0).convert("RGB")
    return out


def data_uri(img):
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def plan_box(dims):
    """Geschätzter Platz für das Bild in der Terminspalte (px), ohne Karten darüber. Das Template misst
    später genau nach; die Schätzung legt nur fest, in welcher Größe die Bilder vorbereitet werden."""
    w, h = dims
    if h > w:  # hochkant: Spalte über die volle Breite, unter dem Wetter; eher großzügig, fitComic verkleinert notfalls
        u = min(w * 0.0145, h * 0.0098)
        return w - 6 * u, h * 0.40
    u = min(w * 0.01, h * 0.01667)
    return w * 0.46 - 6 * u, h - 22 * u


def load(dims, session=None):
    """Bis zu CANDIDATES passende Comics, neuester zuerst, als Dicts fürs Template ([] = keiner).

    Das Template nimmt den ersten, der tatsächlich hineinpasst (über der Liste können Karten stehen,
    die Python nicht vermessen kann); passt keiner, bleibt die Terminliste."""
    session = session or requests.Session()
    status.use(STATUS_NAME)
    newest = latest_num(session)
    if not newest:
        return []
    box_w, box_h = plan_box(dims)
    out, keep = [], {}
    try:
        for num in range(newest, max(0, newest - LOOKBACK), -1):
            m = meta(num, session)
            if not m:
                continue
            raw = None
            if m["img"] not in _sizes:  # Größe einmal ermitteln, danach gemerkt
                raw, factor = fetch_image(m["img"], session)
                _sizes[m["img"]] = (raw.width / factor, raw.height / factor, factor)
            w1, h1, factor = _sizes[m["img"]]
            scale = fit_scale(w1, h1, box_w, box_h, factor)
            if scale < MIN_SCALE:
                logger.info("xkcd %d „%s“ (%d × %d) passt nicht (%.0f %%) – nehme den vorherigen",
                            num, m["title"], w1, h1, scale * 100)
                continue
            key = (m["img"], max(1, int(w1 * scale)))
            pic = _picture.get(key)
            if pic is None:
                pic = prepare(raw or fetch_image(m["img"], session)[0], key[1])
                pic = {"src": data_uri(pic), "w": pic.width, "h": pic.height}
            keep[key] = pic
            logger.info("xkcd %d „%s“: %d × %d px (%.0f %% der normalen Größe)", num, m["title"],
                        pic["w"], pic["h"], scale * 100)
            # kleiner als min_w darf das Template nicht verkleinern (sonst unlesbar)
            out.append(dict(pic, num=num, title=m["title"], alt=m["alt"], date=m["date"], credit=CREDIT,
                            min_w=round(w1 * MIN_SCALE)))
            if len(out) >= CANDIDATES:
                break
        status.ok(STATUS_NAME)
    except Exception as exc:
        logger.warning("xkcd: Comic nicht ladbar: %s", exc)
        status.fail(STATUS_NAME, exc)
    _picture.clear()
    _picture.update(keep)  # nur die Bilder dieser Runde behalten (Speicher auf dem Pi Zero)
    if not out:
        logger.info("xkcd: keiner der letzten %d Comics passt in die Terminspalte", LOOKBACK)
    return out


def free_today(day, now):
    """Sind heute keine Termine mehr (auch keine ganztägigen)? day = erster Eintrag aus calendar_days."""
    if not day or not day.get("is_today"):
        return False
    return not any(ev["source"]["end"] > now for ev in day.get("events") or [])


def next_event(calendar):
    """„Morgen 10:00 Jour fixe Team“ – nächster Termin nach heute (mit Uhrzeit bevorzugt)."""
    for day in calendar or []:
        if day.get("is_today"):
            continue
        evs = day.get("events") or []
        ev = next((e for e in evs if not e["all_day"]), None) or (evs[0] if evs else None)
        if ev:
            when = ev["short"] if not ev["all_day"] else ""
            return f"{day['label']} {when} {ev['title']}".replace("  ", " ").strip()
    return None


def boundaries(now, today_events):
    """Sonntags: Ende der heutigen Termine – danach kann der Comic erscheinen."""
    if now.weekday() != WEEKDAY:
        return []
    return [ev["source"]["end"] for ev in today_events or [] if ev["source"]["end"] > now]
