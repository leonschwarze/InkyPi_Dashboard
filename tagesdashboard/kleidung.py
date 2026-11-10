"""
Wetterbedingte Kleidungsempfehlung für das Tagesdashboard.

Idee: Entscheidend ist nicht die Temperatur jetzt, sondern die kälteste
*gefühlte* Temperatur in der Zeit, in der man voraussichtlich unterwegs ist –
von jetzt bis zum Ende des letzten Termins heute (mindestens 4 Stunden).
Kälteempfindliche Personen bekommen einen Aufschlag: Die Schwellen werden so
verschoben, als wäre es einige Grad kälter.
"""

from dataclasses import dataclass, field

# Aufschlag in °C je Empfindlichkeit
EMPFINDLICHKEIT = {"normal": 0, "empfindlich": 3, "sehr": 5}

# Böen ab ca. 40 km/h machen einen Schirm unpraktisch (DWD warnt ab 50 km/h vor Windböen)
SCHIRM_MAX_BOEEN = 40


@dataclass
class Stunde:
    gefuehlt: float          # gefühlte Temperatur °C
    temp: float              # Lufttemperatur °C
    regen_prob: float = 0    # Regenwahrscheinlichkeit %
    regen_mm: float = 0      # Niederschlag mm/h
    boeen: float = 0         # Böen km/h
    sonne_min: float = 0     # Sonnenschein in der Stunde (min)
    schnee: bool = False


@dataclass
class Empfehlung:
    titel: str
    teile: list = field(default_factory=list)   # (icon, text)
    grund: str = ""


def empfehlen(stunden, empfindlichkeit="empfindlich", monat=11):
    if not stunden:
        return None
    off = EMPFINDLICHKEIT.get(empfindlichkeit, 3)
    kaeltest = min(h.gefuehlt for h in stunden)
    waermst = max(h.gefuehlt for h in stunden)
    t = kaeltest - off  # "wie kalt es sich für diese Person anfühlt"

    teile, gruende = [], []  # (Priorität, Icon, Text) – kleinere Zahl = wichtiger

    # 1) Grundausstattung nach gefühlter Temperatur
    if t < -5:
        titel = "Sehr warm anziehen"
        teile += [(1, "coat", "Daunenjacke"), (3, "beanie", "Mütze"), (3, "gloves", "Handschuhe"),
                  (4, "scarf", "Schal"), (5, "layers", "Thermo-Unterwäsche")]
    elif t < 2:
        titel = "Warm anziehen"
        teile += [(1, "coat", "Winterjacke"), (3, "beanie", "Mütze"), (3, "gloves", "Handschuhe"), (4, "scarf", "Schal")]
    elif t < 7:
        titel = "Warm anziehen"
        teile += [(1, "coat", "Winterjacke"), (3, "scarf", "Schal"), (4, "beanie", "Mütze")]
    elif t < 12:
        titel = "Jacke und Pullover"
        teile += [(1, "jacket", "Übergangsjacke"), (3, "sweater", "Pullover")]
        if off:
            teile.append((4, "scarf", "dünner Schal"))
    elif t < 17:
        titel = "Leichte Jacke"
        teile += [(1, "jacket", "leichte Jacke"), (3, "sweater", "Langarm")]
    elif t < 23:
        titel = "Leicht anziehen"
        teile += [(1, "tshirt", "T-Shirt"), (3, "sweater", "Strickjacke für später")]
    else:
        titel = "Luftig anziehen"
        teile += [(1, "tshirt", "luftige Kleidung")]
    gruende.append(f"gefühlt bis {round(kaeltest)}°")

    # 2) Großer Temperatursprung (z. B. kalter Morgen, warmer Mittag) -> Zwiebellook
    #    statt dicker Winterjacke, die man mittags herumträgt
    if waermst - kaeltest >= 8 and waermst - off >= 12:
        titel = "Zwiebellook"
        teile = [(p, "jacket" if i == "coat" else i, "warme Jacke zum Ausziehen" if i == "coat" else x)
                 for p, i, x in teile if i not in ("gloves",)]
        teile.append((2, "layers", "mehrere Schichten"))
        gruende.append(f"{round(kaeltest)}° bis {round(waermst)}°")

    # 3) Nässe: Schirm nur, wenn der Wind es zulässt
    nass = [h for h in stunden if h.regen_prob >= 50 or h.regen_mm >= 0.3]
    max_boeen = max(h.boeen for h in stunden)
    schnee = any(h.schnee for h in nass)
    if nass:
        if schnee:
            teile.append((2, "boots", "rutschfeste Schuhe"))
            gruende.append("Schnee")
        elif max_boeen >= SCHIRM_MAX_BOEEN:
            teile.append((2, "rainjacket", "Kapuze statt Schirm"))
            gruende.append("Regen, zu windig für Schirm")
        else:
            teile.append((2, "umbrella", "Schirm"))
            gruende.append("Regen")
        if t < 7 and not schnee:
            teile.append((5, "boots", "wasserfeste Schuhe"))
    elif max_boeen >= 50 and t < 12:
        teile.append((2, "rainjacket", "winddichte Jacke"))
        gruende.append(f"Böen bis {round(max_boeen)} km/h")

    # 4) Glätte: um 0 °C und nass oder Schnee
    if any(h.temp <= 1 and (h.regen_mm > 0 or h.schnee) for h in stunden) and not schnee:
        teile.append((2, "boots", "rutschfeste Schuhe"))
        gruende.append("Glättegefahr")

    # 5) Sonne im Sommerhalbjahr
    if 4 <= monat <= 9 and sum(h.sonne_min for h in stunden) >= 120:
        teile.append((3, "sunglasses", "Sonnenschutz"))

    if nass and not schnee and titel.endswith(" anziehen"):
        titel = titel[: -len(" anziehen")] + " und regenfest anziehen"

    # Je Symbol nur das wichtigste Teil; maximal 5, Reihenfolge wie oben
    best = {}
    for idx, (prio, icon, text) in enumerate(teile):
        if icon not in best or prio < best[icon][0]:
            best[icon] = (prio, idx, text)
    auswahl = sorted(best.items(), key=lambda kv: (kv[1][0], kv[1][1]))[:5]
    auswahl.sort(key=lambda kv: kv[1][1])
    uniq = [(icon, text) for icon, (_, _, text) in auswahl]
    return Empfehlung(titel=titel, teile=uniq[:5], grund=" · ".join(gruende))


# --------------------------------------------------------------------------
# Symbole (32er-ViewBox, Konturen in Textfarbe, Flächen in E-Ink-Farben)
# --------------------------------------------------------------------------
_BLUE, _RED, _GREEN, _ORANGE, _YELLOW = "#0082C9", "#E3001B", "#2E9E3F", "#FF8C00", "#FFC400"


def _svg(body):
    return ('<svg class="cl-icon" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" fill="none" '
            'stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round">'
            f"{body}</svg>")


ICONS = {
    "coat": _svg(f'<path d="M11 4 L16 8 L21 4 L27 8 L29 19 L25 20 L25 29 H7 L7 20 L3 19 L5 8 Z" fill="{_BLUE}"/>'
                 '<path d="M16 8 V29" stroke="#fff"/><path d="M11 4 L16 8 L21 4"/>'),
    "jacket": _svg(f'<path d="M11 5 L16 9 L21 5 L27 9 L28 17 L25 18 L25 27 H7 L7 18 L4 17 L5 9 Z" fill="{_GREEN}"/>'
                   '<path d="M16 9 V27" stroke="#fff"/><path d="M11 5 L16 9 L21 5"/>'),
    "sweater": _svg(f'<path d="M12 5 Q16 9 20 5 L27 9 L29 20 L25 21 L24 13 L24 28 H8 L8 13 L7 21 L3 20 L5 9 Z" fill="{_RED}"/>'
                    '<path d="M8 24 H24" stroke="#fff"/>'),
    "tshirt": _svg(f'<path d="M12 5 Q16 9 20 5 L28 9 L26 15 L23 14 L23 28 H9 L9 14 L6 15 L4 9 Z" fill="{_YELLOW}"/>'),
    "layers": _svg(f'<path d="M16 4 L29 11 L16 18 L3 11 Z" fill="{_YELLOW}"/><path d="M3 16 L16 23 L29 16"/>'
                   '<path d="M3 21 L16 28 L29 21"/>'),
    "beanie": _svg(f'<path d="M5 22 A11 11 0 0 1 27 22 Z" fill="{_RED}"/>'
                   f'<rect x="4" y="21" width="24" height="6" rx="2" fill="#fff"/><circle cx="16" cy="7" r="3" fill="{_RED}"/>'),
    "gloves": _svg(f'<path d="M9 29 V16 C9 10 10 6 13 6 C15 6 15 9 15 11 V6 C15 4 19 4 19 6 V12 L22 9 C24 7 27 10 25 12 '
                   f'L20 19 V29 Z" fill="{_ORANGE}"/><path d="M9 25 H20" stroke="#fff"/>'),
    "scarf": _svg('<path d="M6 7 Q16 17 26 7" stroke="currentColor" stroke-width="8"/>'
                  f'<path d="M6 7 Q16 17 26 7" stroke="{_GREEN}" stroke-width="4.6"/>'
                  f'<rect x="12" y="13" width="6" height="15" rx="1" fill="{_GREEN}"/>'
                  f'<rect x="18.5" y="13" width="6" height="12" rx="1" fill="{_GREEN}" transform="rotate(12 21 13)"/>'),
    "rainjacket": _svg(f'<path d="M10 9 C10 2 22 2 22 9 L27 11 L29 21 L25 22 L25 30 H7 L7 22 L3 21 L5 11 Z" fill="{_YELLOW}"/>'
                       '<path d="M12 9 C12 5 20 5 20 9"/><path d="M16 11 V30"/>'),
    "umbrella": _svg(f'<path d="M3 16 A13 13 0 0 1 29 16 Q25.75 13 22.5 16 Q19.25 13 16 16 Q12.75 13 9.5 16 Q6.25 13 3 16 Z" '
                     f'fill="{_BLUE}"/><path d="M16 16 V26 A3 3 0 0 1 10 26"/>'),
    "boots": _svg(f'<path d="M8 4 H17 V18 L27 22 C29 23 29 28 27 28 H8 Z" fill="{_ORANGE}"/>'
                  '<path d="M8 28 V30 H28" /><path d="M11 30 V28 M15 30 V28 M19 30 V28 M23 30 V28" stroke-width="1.6"/>'),
    "sunglasses": _svg(f'<path d="M3 11 H29"/><path d="M4 11 L5 17 A4 4 0 0 0 13 17 L14 11" fill="{_BLUE}"/>'
                       f'<path d="M18 11 L19 17 A4 4 0 0 0 27 17 L28 11" fill="{_BLUE}"/><path d="M14 13 Q16 11.5 18 13"/>'),
}
