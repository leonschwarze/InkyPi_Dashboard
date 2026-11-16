"""
Statusanzeige im Kopf des Dashboards: Welche Datenquelle fällt gerade aus, und seit wann? (seit 1.21)

Ablauf in einer Aktualisierung:
  1. generate_image ruft begin() auf (vergisst Reste einer abgebrochenen Runde).
  2. Die Module melden, was passiert: use(quelle) = die Quelle wird in dieser Runde gebraucht
     (auch, wenn ein Zwischenspeicher antwortet); ok(quelle) bzw. fail(quelle, grund) = ein echter
     Abruf hat geklappt bzw. ist gescheitert. ok/fail zählen zugleich als use.
  3. generate_image ruft commit(now) auf: Erst hier bekommen die Meldungen eine Uhrzeit. So bleibt
     die Uhr in einer Hand (current_time() des Plugins, in Tests eingefroren), und die Module
     brauchen kein „jetzt“.
  4. report(now) liefert die Einträge für den Kopf – nur Quellen, die in dieser Runde gebraucht
     wurden und gerade ausfallen. Die Zugdaten von Dienstagmorgen erscheinen also nicht die ganze
     Woche im Kopf.

Zwei Stufen:
  * sofort beim ersten Fehler: roter Punkt mit dem Namen der Quelle („● Radar“)
  * ab LONG_AFTER (etwa 2 Stunden): „● Kalender seit 9:10 nicht erreichbar“

Eine Runde gilt für eine Quelle als gescheitert, wenn irgendein Abruf dieser Quelle scheiterte
(z. B. ein Kalender von dreien oder ein Ort bei der Anfahrt): Dann fehlt etwas auf dem Bild.
Ein erfolgreicher Abruf beendet den Ausfall. Wird eine Quelle länger als STALE nicht gebraucht
(Zug nur dienstags, Radar nicht im Nachtbild), beginnt ein neuer Fehler auch einen neuen Ausfall –
sonst stünde „Zug seit Dienstag letzter Woche …“ da.

Der Zustand liegt nur im Speicher: Nach einem Neustart von InkyPi beginnt die Zählung neu.
"""

import logging
from datetime import timedelta

logger = logging.getLogger(__name__)

LONG_AFTER = timedelta(hours=2)     # ab hier der volle Hinweis „seit … nicht erreichbar“
TOLERANCE = timedelta(minutes=1)    # InkyPi kommt nie auf die Sekunde genau im Takt
STALE = timedelta(hours=6)          # so lange nicht gebraucht -> alter Ausfall zählt nicht mehr
MAX_SHOWN = 3                       # mehr passt nicht in den Kopf

_events = []   # (quelle, art, grund) aus der laufenden Runde; art = "use" | "ok" | "fail"
_state = {}    # quelle -> {"since": datetime, "last": datetime, "detail": str}
_used = []     # Quellen der letzten Runde, in der Reihenfolge der ersten Meldung


def begin():
    _events.clear()


def use(source):
    _events.append((source, "use", ""))


def ok(source):
    _events.append((source, "ok", ""))


def fail(source, detail=""):
    _events.append((source, "fail", str(detail)[:200]))


def commit(now):
    """Meldungen der Runde mit der Uhrzeit `now` übernehmen."""
    result = {}  # quelle -> (gescheitert?, grund) für Quellen mit echtem Abruf
    used = []
    for source, kind, detail in _events:
        if source not in used:
            used.append(source)
        if kind == "ok":
            result.setdefault(source, (False, ""))
        elif kind == "fail":
            result[source] = (True, detail)
    _events.clear()
    _used[:] = used

    for source, (failed, detail) in result.items():
        st = _state.get(source)
        if not failed:
            if st:
                logger.info("Status: %s wieder erreichbar (Ausfall seit %s)", source, _hm(st["since"]))
                del _state[source]
            continue
        if st is None or now - st["last"] > STALE:
            st = {"since": now}
            logger.warning("Status: %s nicht erreichbar (%s)", source, detail or "ohne Angabe")
        st.update(last=now, detail=detail)
        _state[source] = st


def report(now):
    """Einträge für den Kopf: [{"name", "since", "long"}], längste Ausfälle zuerst."""
    out = []
    for source in _used:
        st = _state.get(source)
        if not st:
            continue
        out.append({"name": source, "since": since_text(st["since"], now),
                    "long": now - st["since"] >= LONG_AFTER - TOLERANCE, "_t": st["since"]})
    out.sort(key=lambda e: e["_t"])
    for e in out:
        del e["_t"]
    return out[:MAX_SHOWN]


def boundaries(now):
    """Zeitpunkte, an denen ein kurzer Hinweis zum langen wird (für den Bild-Cache mit Zug)."""
    return [st["since"] + LONG_AFTER for src, st in _state.items()
            if src in _used and st["since"] + LONG_AFTER > now]


def snapshot():
    """Laufende Ausfälle als {quelle: (seit, zuletzt gescheitert)} – für die Wochenbilanz in pizustand.py (seit 1.28)."""
    return {src: (st["since"], st["last"]) for src, st in _state.items()}


def reset():
    """Alles vergessen (Tests)."""
    _events.clear()
    _state.clear()
    _used.clear()


def _hm(dt):
    return f"{dt.hour}:{dt.minute:02d}"


WOCHENTAGE_KURZ = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]


def since_text(since, now):
    """„9:10“ heute, „gestern 22:40“, innerhalb einer Woche „Mo 22:40“, sonst „12.11.“."""
    days = (now.date() - since.date()).days
    if days <= 0:
        return _hm(since)
    if days == 1:
        return f"gestern {_hm(since)}"
    if days < 7:
        return f"{WOCHENTAGE_KURZ[since.weekday()]} {_hm(since)}"
    return f"{since.day}.{since.month}."
