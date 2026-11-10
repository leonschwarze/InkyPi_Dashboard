"""
Schärfere Darstellung auf Pimoroni Inky (Spectra 6, z. B. Inky Impression 7,3").

Warum das nötig ist
-------------------
Der Pimoroni-Treiber (``inky_e673.set_image``) rechnet jedes RGB-Bild mit
Floyd-Steinberg-Dithering auf die 6 Displayfarben um. Jede Farbe, die keine
Displayfarbe ist – Kantenglättung von Schrift und Icons, Orange, Grautöne –,
wird dabei in ein unruhiges Punktmuster zerlegt. Text franst aus, Flächen rauschen.

Was dieses Modul macht
----------------------
Es ordnet jedes Pixel *vor* dem Treiber selbst einer Displayfarbe zu:

* Kanten (1 Pixel breite Übergänge, z. B. Kantenglättung) werden hart
  schwarz/weiß bzw. auf die nächste Farbe gesetzt.
* Flächen in Zwischentönen (Grau der Nachtstunden, graue Wolken, helle Tönungen)
  werden mit einem gleichmäßigen 4×4-Raster (Bayer-Matrix) dargestellt. Das sieht
  ruhig aus und ist reproduzierbar, anders als das Zufallsrauschen des Treibers.
* Orange – das Spectra 6 nicht hat – wird zu einem Schachbrett aus Rot und Gelb.

Danach liegt jedes Pixel exakt auf einer Farbe der Treiberpalette; das Dithering
des Treibers hat keinen Fehler mehr zu verteilen und lässt das Bild unverändert.

Dieses Modul existiert in mehreren Plugins als Kopie. Original: shared/eink.py,
verteilen mit ``python dev/sync_lib.py``.
"""

import logging

import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)

# Displayfarben in Treiber-Reihenfolge (inky_e673: DESATURATED_PALETTE bzw. SATURATED_PALETTE)
PURE = np.array([[0, 0, 0], [255, 255, 255], [255, 255, 0], [255, 0, 0], [0, 0, 255], [0, 255, 0]])
SATURATED = np.array([[0, 0, 0], [161, 164, 165], [208, 190, 71], [156, 72, 75], [61, 59, 94], [58, 91, 70]])
BLACK, WHITE, YELLOW, RED, BLUE, GREEN, ORANGE = range(7)

# Gestaltungsfarben der Plugins -> Displayfarbe. Mehrere Vertreter je Farbe, damit
# z. B. das helle Eisblau der Schneeflocken als Blau und nicht als Weiß erkannt wird.
REFERENCES = [
    (YELLOW, (255, 196, 0)), (YELLOW, (255, 212, 0)), (YELLOW, (255, 229, 0)), (YELLOW, (255, 226, 122)),
    (YELLOW, (255, 255, 0)),
    (RED, (227, 0, 27)), (RED, (224, 80, 11)), (RED, (139, 10, 80)), (RED, (255, 0, 0)),
    (BLUE, (0, 130, 201)), (BLUE, (30, 111, 217)), (BLUE, (11, 61, 145)), (BLUE, (95, 180, 255)),
    (BLUE, (0, 0, 255)),
    (GREEN, (46, 158, 63)), (GREEN, (0, 255, 0)),
    (ORANGE, (255, 140, 0)), (ORANGE, (255, 138, 0)),
]
# Schwarz und Weiß gehören immer dazu
CANDIDATES = [(BLACK, (0, 0, 0)), (WHITE, (255, 255, 255))] + REFERENCES
CAND_RGB = np.array([c for _, c in CANDIDATES], dtype=np.float32)
CAND_ID = np.array([i for i, _ in CANDIDATES])
# Alle Paare von Kandidatenfarben: Übergangspixel sind fast immer eine Mischung aus zweien
PAIRS = np.array([(i, j) for i in range(len(CANDIDATES)) for j in range(i + 1, len(CANDIDATES))
                  if CAND_ID[i] != CAND_ID[j]])

# 4×4-Bayer-Matrix: Schwellen zwischen 0 und 1 für ein gleichmäßiges Raster
BAYER = (np.array([[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]]) + 0.5) / 16

PURE_DISTANCE = 30   # so nah an einer Gestaltungsfarbe gilt ein Pixel als "rein"
MIN_TONE = 0.06      # schwächere Beimischungen fallen weg (keine einzelnen Punkte im Weiß)
CHUNK = 20000        # Pixel pro Rechenschritt (begrenzt den Speicher auf dem Pi Zero)


def _erode(mask):
    """True nur, wo das Pixel und alle 8 Nachbarn True sind (Fläche statt Kante)."""
    p = np.pad(mask, 1, constant_values=False)
    out = np.ones_like(mask)
    h, w = mask.shape
    for dy in (0, 1, 2):
        for dx in (0, 1, 2):
            out &= p[dy:dy + h, dx:dx + w]
    return out


def _unmix(px):
    """Erklärt jedes Pixel als Mischung zweier Kandidatenfarben a, b mit Anteil t von b.

    Beispiel: dunkles Gelb (128, 110, 0) ist knapp halb Schwarz, halb Gelb – nicht Rot,
    obwohl Rot im RGB-Abstand näher läge. So entstehen keine farbigen Säume an Kanten.
    """
    A = CAND_RGB[PAIRS[:, 0]]
    V = CAND_RGB[PAIRS[:, 1]] - A
    vv = (V * V).sum(-1)
    res_a, res_b, res_t = [], [], []
    for start in range(0, len(px), CHUNK):
        p = px[start:start + CHUNK].astype(np.float32)
        d = p[:, None, :] - A[None, :, :]
        t = np.clip((d * V[None]).sum(-1) / vv[None], 0.0, 1.0)
        resid = ((d - t[..., None] * V[None]) ** 2).sum(-1)
        best = resid.argmin(1)
        res_a.append(CAND_ID[PAIRS[best, 0]])
        res_b.append(CAND_ID[PAIRS[best, 1]])
        res_t.append(t[np.arange(len(p)), best])
    return np.concatenate(res_a), np.concatenate(res_b), np.concatenate(res_t)


def classify(rgb):
    """Liefert für jedes Pixel einen Farbindex 0–5 (Displayfarben) bzw. 6 (Orange)."""
    h, w, _ = rgb.shape
    flat = rgb.reshape(-1, 3).astype(np.float32)
    out = np.empty(h * w, dtype=np.int32)

    # 1) Reine Pixel: nahe an einer Gestaltungsfarbe (der allergrößte Teil des Bildes)
    dist = np.empty(h * w, dtype=np.float32)
    nearest = np.empty(h * w, dtype=np.int32)
    for start in range(0, h * w, CHUNK * 5):
        p = flat[start:start + CHUNK * 5]
        d = ((p[:, None, :] - CAND_RGB[None]) ** 2).sum(-1)
        nearest[start:start + len(p)] = d.argmin(1)
        dist[start:start + len(p)] = np.sqrt(d.min(1))
    pure = dist < PURE_DISTANCE
    out[pure] = CAND_ID[nearest[pure]]

    # 2) Übergänge und Zwischentöne: als Mischung zweier Farben erklären
    mixed = ~pure
    if mixed.any():
        a, b, t = _unmix(flat[mixed])
        # sehr schwache Beimischungen ignorieren
        t = np.where(t < MIN_TONE, 0.0, np.where(t > 1 - MIN_TONE, 1.0, t))
        hard = np.where(t < 0.5, a, b)
        out[mixed] = hard

        # Flächen (nicht nur 1-Pixel-Kanten) gleichmäßig rastern statt hart setzen –
        # aber nur Grautöne, helle Tönungen und ausgewogene Mischungen zweier Farben.
        # Kräftige Farben (≥ 60 % Farbe) und dunkle Farbtöne werden einfarbig gefüllt,
        # sonst würde z. B. ein Kalenderrot aus Nextcloud gepunktet.
        mixed2d = mixed.reshape(h, w)
        area = _erode(mixed2d).reshape(-1)
        gray_pair = ((a == BLACK) & (b == WHITE)) | ((a == WHITE) & (b == BLACK))
        strong_tint = (a == WHITE) & (b != BLACK) & (t >= 0.6)
        dark_tone = ((a == BLACK) | (b == BLACK)) & ~gray_pair
        # Zwei Farben: nur echte Mischungen (z. B. Rot+Gelb ≈ 50/50) rastern; überwiegt
        # eine Farbe deutlich (Nextcloud-Rot #E9322D ≈ 78 % Rot, 22 % Gelb), einfarbig.
        colour_pair = (a > WHITE) & (b > WHITE)
        dominant = colour_pair & (np.abs(t - 0.5) > 0.15)
        in_area = area[mixed] & ~strong_tint & ~dark_tone & ~dominant
        threshold = np.tile(BAYER, (h // 4 + 1, w // 4 + 1))[:h, :w].reshape(-1)[mixed]
        rastered = np.where(t > threshold, b, a)
        out_mixed = out[mixed]
        out_mixed[in_area] = rastered[in_area]
        out[mixed] = out_mixed

    out = out.reshape(h, w)
    # 3) Orange gibt es auf Spectra 6 nicht: Schachbrett aus Rot und Gelb
    orange = out == ORANGE
    if orange.any():
        yy, xx = np.indices((h, w))
        checker = (xx + yy) % 2 == 0
        out[orange & checker] = RED
        out[orange & ~checker] = YELLOW
    return out


def palette_for(saturation):
    """Palette, mit der das Bild garantiert unverändert durch den Treiber geht.

    Bei Treiber-Sättigung bis 0,5 bleiben reine Farben stabil (gut für die Vorschau
    in der Web-Oberfläche). Darüber nutzen wir exakt die Mischpalette des Treibers.
    """
    if saturation <= 0.5:
        return PURE
    return (SATURATED * saturation + PURE * (1 - saturation)).astype(int)


def snap(image, saturation=0.5):
    rgb = np.asarray(image.convert("RGB"))
    idx = classify(rgb)
    return Image.fromarray(palette_for(saturation)[idx].astype(np.uint8), "RGB")


def prepare(image, device_config, enabled=True):
    """Bild für das Display vorbereiten. Ändert nur etwas bei Inky-Displays."""
    if not enabled or image is None:
        return image
    display_type = device_config.get_config("display_type", default="inky")
    if display_type != "inky":
        return image
    settings = device_config.get_config("image_settings", default={}) or {}
    try:
        saturation = float(settings.get("inky_saturation", 0.5))
    except (TypeError, ValueError):
        saturation = 0.5
    changed = [k for k in ("brightness", "contrast", "saturation", "sharpness")
               if abs(float(settings.get(k, 1.0) or 1.0) - 1.0) > 1e-6]
    if changed:
        logger.info("Bildeinstellungen %s ungleich 1,0 – sie verändern die Farben nach dem Einrasten "
                    "und bringen das Rastern des Treibers zurück.", ", ".join(changed))
    try:
        return snap(image, saturation)
    except Exception:  # lieber unscharf als gar kein Bild
        logger.exception("Einrasten der Farben fehlgeschlagen – Bild wird unverändert verwendet")
        return image
