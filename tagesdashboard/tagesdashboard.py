"""
Tagesdashboard – Wetter (DWD) und Nextcloud-Kalender auf einem Bild.

Das Plugin ist eigenständig. Im Unterordner lib/ liegen die Bausteine der
beiden Einzel-Plugins:
  lib/dwd_wetter.py, lib/dwd_icons.py   Wetterdaten, Symbole, Warnungen
  lib/nextcloud_kalender.py             CalDAV-Abruf, Serientermine
Die Einzel-Plugins müssen dafür nicht installiert sein.

Was das Dashboard selbst hinzufügt:
  * Fokus-Tag: tagsüber das Wetter von heute, abends (einstellbar) das von morgen
  * Tageskurve 6–24 Uhr mit "jetzt"-Linie
  * Kleidungsempfehlung für die Zeit, in der man unterwegs ist (aus den Terminen)
  * Regenwahrscheinlichkeit direkt an den Terminen
"""

import logging
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

import requests

from plugins.base_plugin.base_plugin import BasePlugin

logger = logging.getLogger(__name__)

try:
    from .lib import dwd_wetter as dwd
    from .lib import dwd_icons as icons
    from .lib import nextcloud_kalender as nc
    from .lib import eink
    IMPORT_ERROR = None
except Exception as exc:  # Plugin soll InkyPi beim Start nicht blockieren
    logger.exception("Bausteine des Tagesdashboards konnten nicht geladen werden")
    dwd = icons = nc = eink = None
    IMPORT_ERROR = exc

try:
    from . import kleidung
except ImportError:  # pragma: no cover
    from plugins.tagesdashboard import kleidung

WOCHENTAGE = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]
WOCHENTAGE_KURZ = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]
MONATE = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli",
          "August", "September", "Oktober", "November", "Dezember"]

DEFAULTS = {
    "sensitivity": "empfindlich",
    "switchHour": "20",
    "calendarDays": "7",
    "showAlerts": "true",
    "showWear": "true",
    "showGraph": "true",
    "rainOnEvents": "true",
    "useColors": "true",
    "showLocation": "true",
    "showPast": "false",
    "verifySSL": "true",
    "einkSnap": "true",
}
SENSITIVITY_LABEL = {"normal": "normal", "empfindlich": "kälteempfindlich", "sehr": "sehr kälteempfindlich"}
GRAPH_START, GRAPH_END = 6, 24  # Tageskurve von 6 bis 24 Uhr
# Regenstärke in mm pro Stunde. Bewusst alltagsnah gewählt; die offizielle DWD-Einteilung
# (leicht < 2,5, mäßig bis 10, stark > 10 mm/Std.) würde fast jeden Regen "leicht" nennen.
RAIN_LEVELS = [(1.0, "leicht"), (4.0, "maessig"), (float("inf"), "stark")]
RAIN_SCALE = 4.0  # mm/Std.: ab hier ist der Balken voll hoch (feste Skala, Tage bleiben vergleichbar)

# UV-Gefahrenindex des DWD: tägliche Höchstwerte für ausgewählte Orte (heute, morgen, übermorgen)
UVI_URL = "https://opendata.dwd.de/climate_environment/health/alerts/uvi.json"
# Stufen nach WHO/Bundesamt für Strahlenschutz: (bis einschließlich, Bezeichnung, Farbe, Schrift)
UV_STUFEN = [
    (2, "niedrig", "#2E9E3F", "#FFFFFF"),
    (5, "mittel", "#FFC400", "#000000"),
    (7, "hoch", "#FF8C00", "#000000"),
    (10, "sehr hoch", "#E3001B", "#FFFFFF"),
    (99, "extrem", "#8B0A50", "#FFFFFF"),
]
MIN_WEAR_HOURS = 4


def hm(dt):
    return f"{dt.hour}:{dt.minute:02d}"


class Tagesdashboard(BasePlugin):

    def generate_settings_template(self):
        params = super().generate_settings_template()
        params["style_settings"] = True
        params["api_key"] = {
            "required": True,
            "service": "Nextcloud (App-Passwort)",
            "expected_key": "NEXTCLOUD_APP_PASSWORD",
        }
        return params

    def current_time(self, tz):
        """Eigene Methode, damit Tests eine feste Uhrzeit einsetzen können."""
        return datetime.now(tz)

    def _opt(self, settings, key):
        if "cfgVersion" in settings and DEFAULTS.get(key) in ("true", "false"):
            return settings.get(key, "false")
        return settings.get(key) or DEFAULTS[key]

    # ==================================================================
    def generate_image(self, settings, device_config):
        if IMPORT_ERROR is not None:
            raise RuntimeError(f"Plugin unvollständig – Ordner lib/ fehlt oder ist beschädigt ({IMPORT_ERROR}).")
        flag = lambda k: self._opt(settings, k) == "true"  # noqa: E731

        tz_name = device_config.get_config("timezone", default="Europe/Berlin") or "Europe/Berlin"
        try:
            tz = ZoneInfo(tz_name)
        except Exception:
            tz = ZoneInfo("Europe/Berlin")
        now = self.current_time(tz)
        today = now.date()

        switch = self._opt(settings, "switchHour")
        focus = today + timedelta(days=1) if switch.isdigit() and now.hour >= int(switch) else today

        # ---- Kalender (darf ausfallen, dann nur Wetter) -------------------
        events, calendars, cal_error = [], [], None
        try:
            events, calendars = self.load_calendar(settings, device_config, tz, today, flag)
        except RuntimeError as exc:
            cal_error = str(exc)
            logger.warning("Kalender nicht verfügbar: %s", exc)

        # ---- Wetter (darf ausfallen, dann nur Kalender) ------------------
        weather, wx_error = None, None
        try:
            weather = self.load_weather(settings, tz, now, focus, flag)
        except RuntimeError as exc:
            wx_error = str(exc)
            logger.warning("Wetter nicht verfügbar: %s", exc)

        if weather is None and cal_error:
            raise RuntimeError(f"Weder Wetter noch Kalender verfügbar. Wetter: {wx_error} Kalender: {cal_error}")

        use_colors = flag("useColors")
        for ev in events:
            ev["color"] = ev["cal_color"] if use_colors else "#000000"
            ev["fg"] = nc.contrast_color(ev["color"])

        records = weather["records"] if weather else []
        params = {
            "date_str": f"{WOCHENTAGE[today.weekday()]}, {today.day}. {MONATE[today.month - 1]}",
            "kw": today.isocalendar()[1],
            "updated": now.strftime("%H:%M"),
            "place": (settings.get("customTitle") or "").strip() or (weather or {}).get("place", ""),
            "weather": weather,
            "wx_error": wx_error,
            "cal_error": cal_error,
            "wear": None,
            "graph": None,
            "calendar": self.calendar_days(events, tz, now, today, settings, flag, records),
            "show_location": flag("showLocation"),
            "use_colors": use_colors,
            "plugin_settings": settings,
        }
        if weather:
            if flag("showGraph"):
                params["graph"] = self.day_graph(records, focus, now, tz, weather["sun_cache"])
            if flag("showWear"):
                params["wear"] = self.wear(records, events, focus, now, tz, self._opt(settings, "sensitivity"),
                                           uv=weather.get("uv"))

        dimensions = device_config.get_resolution()
        if device_config.get_config("orientation") == "vertical":
            dimensions = dimensions[::-1]
        params["orientation"] = "portrait" if dimensions[1] > dimensions[0] else "landscape"

        image = self.render_image(dimensions, "tagesdashboard.html", "tagesdashboard.css", params)
        if not image:
            raise RuntimeError("Bild konnte nicht erzeugt werden – siehe Logs.")
        if eink is not None:
            image = eink.prepare(image, device_config, enabled=flag("einkSnap"))
        return image

    # ==================================================================
    # Kalender
    # ==================================================================
    def load_calendar(self, settings, device_config, tz, today, flag):
        user = (settings.get("username") or "").strip()
        url = (settings.get("nextcloudUrl") or "").strip()
        if not user or not url:
            raise RuntimeError("Nextcloud-Adresse oder Benutzername fehlt.")
        key = (settings.get("passwordKey") or "NEXTCLOUD_APP_PASSWORD").strip()
        password = device_config.load_env_key(key)
        if not password:
            raise RuntimeError(f"App-Passwort fehlt (API Keys → {key}).")

        days = int(self._opt(settings, "calendarDays")) if self._opt(settings, "calendarDays").isdigit() else 7
        start = datetime.combine(today, time.min, tz)
        end = start + timedelta(days=max(days, 2) + 1)

        client = nc.CalDavClient(nc.dav_root(url), user, password, verify=flag("verifySSL"))
        helper = nc.NextcloudKalender({"id": "nextcloud_kalender"})
        calendars = helper.select_calendars(client.calendars(), settings.get("calendars", ""))
        events = []
        for cal in calendars:
            try:
                for ics in client.events(cal["url"], start, end):
                    events.extend(helper.parse_events(ics, cal, tz, start, end))
            except RuntimeError as exc:
                logger.warning("Kalender %s nicht lesbar: %s", cal["name"], exc)
        return events, calendars

    def calendar_days(self, events, tz, now, today, settings, flag, records):
        helper = nc.NextcloudKalender({"id": "nextcloud_kalender"}) if nc else None
        if helper is None:
            return []
        n = int(self._opt(settings, "calendarDays")) if self._opt(settings, "calendarDays").isdigit() else 7
        out = []
        for i in range(n):
            d = today + timedelta(days=i)
            items = helper.events_on_day(events, d, tz, now, flag("showPast"))
            if flag("rainOnEvents"):
                for it in items:
                    it["rain"] = self.rain_during(records, it["source"]) if not it["all_day"] else None
            if items or i == 0:
                label = "Heute" if i == 0 else ("Morgen" if i == 1 else WOCHENTAGE_KURZ[d.weekday()])
                out.append({
                    "label": label,
                    "date": "" if i == 0 else f"{d.day}. {MONATE[d.month - 1]}" if i == 1 else f"{d.day}.{d.month}.",
                    "is_today": i == 0,
                    "events": items,
                })
        return out

    @staticmethod
    def rain_during(records, ev):
        """Höchste Regenwahrscheinlichkeit während eines Termins (nur wenn ≥ 50 %)."""
        s, e = ev["start"], max(ev["end"], ev["start"] + timedelta(hours=1))
        probs = [r.get("precipitation_probability") for r in records
                 if s - timedelta(minutes=59) <= r["dt"] <= e and r.get("precipitation_probability") is not None]
        if probs and max(probs) >= 50:
            return f"{round(max(probs))} % Regen"
        return None

    # ==================================================================
    # Wetter
    # ==================================================================
    def load_weather(self, settings, tz, now, focus, flag):
        raw_lat = str(settings.get("latitude", "")).strip().replace(",", ".")
        raw_lon = str(settings.get("longitude", "")).strip().replace(",", ".")
        try:
            lat, lon = float(raw_lat), float(raw_lon)
        except ValueError:
            raise RuntimeError("Bitte einen Ort für das Wetter wählen.")

        w = dwd.DwdWetter({"id": "dwd_wetter"})
        opts = {
            "show_alerts": flag("showAlerts"), "show_graph": False, "night_shading": True,
            "graph_icons": True, "hours": 24, "days": 2,
            # Platz 5 wird durch den UV-Index ersetzt; Bewölkung ist der Ersatz ohne UV-Daten
            "tiles": ["wind", "gust", "precip", "humidity", "cloudcover", "sun"],
        }
        data = w.fetch_data(lat, lon, tz, now, opts)
        base = w.build_template_params(data, lat, lon, tz, now, opts, settings)

        cache = {}

        def sun_cache(d):
            if d not in cache:
                cache[d] = w.sun_times(lat, lon, d, tz)
            return cache[d]

        records = []
        for rec in (data["hourly"] or {}).get("weather", []):
            try:
                rec = dict(rec)
                rec["dt"] = dwd.parse_ts(rec["timestamp"], tz)
                records.append(rec)
            except (KeyError, ValueError):
                continue
        records.sort(key=lambda r: r["dt"])

        offset = (focus - now.date()).days  # 0 = heute, 1 = morgen
        uv = self.load_uv(settings.get("uvCity", ""), base["title"])
        uv_value = None
        if uv:
            uv_value = uv.get(["today", "tomorrow", "dayafter_to"][min(offset, 2)])

        result = {
            "uv": uv_value,
            "place": base["title"],
            "station": base["station"],
            "alert": base["alerts"][0] if base["alerts"] else None,
            "alerts_more": base["alerts_more"],
            "records": records,
            "sun_cache": sun_cache,
        }
        if focus == now.date():
            cur = base["current"]
            result.update({
                "is_today": True,
                "label": None,
                "icon": cur["icon"],
                "temp": cur["temp"],
                "text": cur["text"],
                "sub": f"↑{cur['tmax']}° ↓{cur['tmin']}°" + (f" · gefühlt {cur['feels']}°" if cur["show_feels"] else ""),
                "tiles": self.today_tiles(base["tiles"], records, now.date()),
            })
        else:
            result.update(self.focus_day(w, records, focus, tz, sun_cache))
        if uv_value is not None:
            result["tiles"] = [self.uv_tile(uv_value, offset) if t.get("key") == "cloudcover" else t
                               for t in result["tiles"]]
        return result

    # ------------------------------------------------------------------
    def load_uv(self, wanted, place):
        """UV-Index vom DWD; der Ort wird über den Namen zugeordnet (z. B. „Bonn“)."""
        names = [n.strip() for n in (wanted, place) if n and n.strip()]
        if not names:
            return None
        try:
            session = requests.Session()
            session.headers.update({"User-Agent": dwd.USER_AGENT})
            resp = session.get(UVI_URL, timeout=15)
            if resp.status_code != 200:
                raise RuntimeError(f"HTTP {resp.status_code}")
            entries = resp.json().get("content") or []
        except Exception as exc:
            logger.warning("UV-Index nicht verfügbar: %s", exc)
            return None
        by_city = {(e.get("city") or "").casefold(): e.get("forecast") or {} for e in entries}
        for name in names:
            key = name.casefold()
            if key in by_city:
                return by_city[key]
            # z. B. "Frankfurt" passt auf "Frankfurt/Main"
            for city, fc in by_city.items():
                if city.startswith(key) or key.startswith(city):
                    return fc
        logger.info("Kein UV-Index für %s. Verfügbare Orte: %s", names,
                    ", ".join(sorted(e.get("city", "") for e in entries)))
        return None

    @staticmethod
    def uv_stufe(value):
        for limit, name, bg, fg in UV_STUFEN:
            if value <= limit:
                return name, bg, fg
        return UV_STUFEN[-1][1:]

    def uv_tile(self, value, offset):
        name, bg, fg = self.uv_stufe(value)
        badge = (f'<svg class="mx-icon" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">'
                 f'<rect x="2" y="5" width="28" height="22" rx="5" fill="{bg}" stroke="currentColor" stroke-width="2.4"/>'
                 f'<text x="16" y="21" text-anchor="middle" font-family="Jost, sans-serif" font-weight="700" '
                 f'font-size="13" fill="{fg}">UV</text></svg>')
        return {"icon": badge, "label": "UV " + ("heute" if offset == 0 else "morgen"),
                "value": str(int(round(value))), "unit": name, "key": "uv"}

    @staticmethod
    def today_tiles(tiles, records, d):
        """Kacheln aus dem DWD-Plugin, mit kürzeren Beschriftungen fürs Dashboard."""
        snowy = any(r.get("icon") in ("snow", "sleet") for r in records if r["dt"].date() == d)
        out = []
        for t in tiles:
            if t["label"] == "Bewölkung":
                t = dict(t, key="cloudcover")
            if t["label"] == "Regen heute" and snowy:
                t = dict(t, label="Schnee heute")
            out.append(t)
        return out

    def focus_day(self, w, records, d, tz, sun_cache):
        """Kopfbereich und Kacheln für den nächsten Tag (abends)."""
        day = [r for r in records if r["dt"].date() == d]
        if not day:
            raise RuntimeError("Keine Vorhersage für morgen verfügbar.")
        daytime = [r for r in day if 7 <= r["dt"].hour <= 20] or day
        val = lambda key, recs=day: [r[key] for r in recs if r.get(key) is not None]  # noqa: E731
        temps = val("temperature")
        icon = w.day_icon(day)
        precip = sum(r.get("precipitation") or 0 for r in day)
        probs = val("precipitation_probability")
        winds = val("wind_speed", daytime)
        dirs = val("wind_direction", daytime)
        gusts = val("wind_gust_speed")
        hums = val("relative_humidity", daytime)
        clouds = val("cloud_cover", daytime)
        sr, ss = sun_cache(d)
        mi = icons.metric_icon
        wind = sum(winds) / len(winds) if winds else None
        wdir = dirs[len(dirs) // 2] if dirs else None
        wind_extra = ""
        if wdir is not None and (wind or 0) >= 1:
            wind_extra = icons.wind_arrow(wdir, "tile-arrow") + f"<span>{dwd.compass(wdir)}</span>"
        tiles = [
            {"icon": mi("wind"), "label": "Wind tagsüber", "value": dwd.de_num(wind), "unit": "km/h", "extra": wind_extra},
            {"icon": mi("gust"), "label": "Böen bis", "value": dwd.de_num(max(gusts) if gusts else None), "unit": "km/h"},
            {"icon": mi("precip"), "label": "Regen morgen", "value": dwd.de_num(precip, 1), "unit": "mm",
             "extra": f"<span>{dwd.de_num(max(probs))} %</span>" if probs else ""},
            {"icon": mi("humidity"), "label": "Luftfeuchte", "value": dwd.de_num(sum(hums) / len(hums) if hums else None), "unit": "%"},
            {"icon": mi("cloudcover"), "label": "Bewölkung", "key": "cloudcover",
             "value": dwd.de_num(sum(clouds) / len(clouds) if clouds else None), "unit": "%"},
        ]
        if sr and ss:
            tiles.append({"icon": mi("sun_times"), "label": "Sonne",
                          "value": f'{hm(sr)}<span class="sep">–</span>{hm(ss)}', "unit": "", "raw": True})
        mean_cloud = sum(clouds) / len(clouds) if clouds else None
        return {
            "is_today": False,
            "label": f"Morgen · {WOCHENTAGE[d.weekday()]}",
            "icon": icons.weather_icon(icon, "cur-icon"),
            "temp": dwd.de_num(max(temps)) if temps else "–",
            "text": dwd.condition_text(icon, precip / max(len(day), 1), mean_cloud, True),
            "sub": f"Höchstwert · tiefst {dwd.de_num(min(temps))}°" if temps else "",
            "tiles": tiles,
        }

    # ------------------------------------------------------------------
    def day_graph(self, records, d, now, tz, sun_cache):
        start = datetime.combine(d, time(GRAPH_START), tz)
        end = datetime.combine(d, time.min, tz) + timedelta(hours=GRAPH_END)
        pts = [r for r in records if start <= r["dt"] <= end and r.get("temperature") is not None]
        if len(pts) < 4:
            return None
        n = len(pts)
        W, H = 1000.0, 300.0
        slot = W / n
        temps = [r["temperature"] for r in pts]
        tmax, tmin = max(temps), min(temps)
        span = max(tmax - tmin, 4.0)
        mid = (tmax + tmin) / 2
        lo, hi = mid - span / 2, mid + span / 2
        top, bottom = 0.30, 0.72
        x = lambda i: (i + 0.5) * slot  # noqa: E731
        y = lambda t: H * (top + (hi - t) / (hi - lo) * (bottom - top))  # noqa: E731
        left = lambda i: f"{(i + 0.5) / n * 100:.2f}"  # noqa: E731

        P = [(x(i), y(t)) for i, t in enumerate(temps)]
        line = f"M{P[0][0]:.1f},{P[0][1]:.1f}"
        for i in range(len(P) - 1):
            p0 = P[i - 1] if i > 0 else P[i]
            p1, p2 = P[i], P[i + 1]
            p3 = P[i + 2] if i + 2 < len(P) else p2
            c1 = (p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6)
            c2 = (p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6)
            line += f" C{c1[0]:.1f},{c1[1]:.1f} {c2[0]:.1f},{c2[1]:.1f} {p2[0]:.1f},{p2[1]:.1f}"

        # Regen bekommt eine eigene Zeile unter der Kurve: Höhe = Menge, Füllung = Stärke.
        rain, nights = [], []
        for i, r in enumerate(pts):
            amount = r.get("precipitation") or 0
            if amount >= 0.05:
                level = next(name for limit, name in RAIN_LEVELS if amount < limit)
                h = 100 * max(min(amount / RAIN_SCALE, 1.0), 0.28)  # auch Niesel bleibt sichtbar
                rain.append({"x": f"{i * slot + slot * 0.08:.1f}", "w": f"{slot * 0.84:.1f}",
                             "y": f"{100 - h:.1f}", "h": f"{h:.1f}", "cls": level})
            sr, ss = sun_cache(r["dt"].date())
            if sr and ss and not (sr <= r["dt"] < ss):
                nights.append({"x": f"{i * slot:.1f}", "w": f"{slot + 0.6:.1f}"})
        used_levels = {c["cls"] for c in rain}

        icon_hours = {9, 12, 15, 18, 21}
        gicons, xlabels = [], []
        for i, r in enumerate(pts):
            h = r["dt"].hour
            if h in icon_hours:
                day = sun_cache(r["dt"].date())
                is_day = day[0] <= r["dt"] < day[1] if day[0] and day[1] else 7 <= h < 18
                ic = dwd.refine_icon(r.get("icon"), r.get("precipitation"), r.get("cloud_cover"), is_day)
                gicons.append({"left": left(i), "svg": icons.weather_icon(ic, "g-icon")})
                xlabels.append({"left": left(i), "text": str(h)})

        imax, imin = temps.index(tmax), temps.index(tmin)
        tlabels = [{"left": left(imax), "top": f"{y(tmax) / H * 100:.2f}", "text": f"{dwd.de_num(tmax)}°", "cls": "t-max"}]
        if imin != imax:
            tlabels.append({"left": left(imin), "top": f"{y(tmin) / H * 100:.2f}", "text": f"{dwd.de_num(tmin)}°", "cls": "t-min"})
        for t in tlabels:
            v = float(t["left"])
            t["edge"] = " edge-l" if v < 6 else (" edge-r" if v > 94 else "")

        now_left = None
        if start <= now <= end:
            now_left = f"{((now - start).total_seconds() / 3600 + 0.5) / n * 100:.2f}"
        return {"line": line, "nights": nights, "icons": gicons, "xlabels": xlabels,
                "tlabels": tlabels, "now_left": now_left, "rain": rain,
                "rain_levels": [lv for _, lv in RAIN_LEVELS if lv in used_levels],
                "rain_summary": self.rain_summary(pts, now, d)}

    @staticmethod
    def rain_summary(pts, now, d):
        """Kopfzeile der Tageskurve, z. B. „Regen 17–23 Uhr · 6,8 mm · bis 85 %“."""
        relevant = [r for r in pts if d != now.date() or r["dt"] >= now - timedelta(minutes=59)]
        if not relevant:
            return "Kein Regen mehr erwartet"
        wet = [r for r in relevant if (r.get("precipitation") or 0) >= 0.1
               or (r.get("precipitation_probability") or 0) >= 50]
        probs = [r["precipitation_probability"] for r in relevant if r.get("precipitation_probability") is not None]
        if not wet:
            if probs and max(probs) >= 30:
                return f"Kaum Regen · Risiko bis {round(max(probs))} %"
            return "Kein Regen erwartet" if d != now.date() else "Kein Regen mehr erwartet"
        total = sum(r.get("precipitation") or 0 for r in relevant)
        first, last = wet[0]["dt"], wet[-1]["dt"]
        snowy = sum(1 for r in wet if r.get("icon") in ("snow", "sleet") or r.get("condition") in ("snow", "sleet"))
        word = "Schnee" if snowy > len(wet) / 2 else ("Niederschlag" if snowy else "Regen")
        if d == now.date() and first <= now:
            when = f"{word} bis {last.hour} Uhr"
        elif first == last:
            when = f"{word} um {first.hour} Uhr"
        else:
            when = f"{word} {first.hour}–{last.hour if last.hour else 24} Uhr"
        return f"{when} · {dwd.de_num(total, 1)} mm"

    # ------------------------------------------------------------------
    def wear(self, records, events, d, now, tz, sensitivity, uv=None):
        """Kleidungsempfehlung für die Zeit, in der man voraussichtlich unterwegs ist."""
        day_start = datetime.combine(d, time.min, tz)
        day_end = day_start + timedelta(days=1)
        timed = [e for e in events if not e["all_day"] and e["start"] < day_end and e["end"] > day_start]
        reason = None
        if d == now.date():
            start = now.replace(minute=0, second=0, microsecond=0)
            end = start + timedelta(hours=MIN_WEAR_HOURS)
            later = [e for e in timed if e["end"] > now]
            if later:
                last = max(later, key=lambda e: e["end"])
                if last["end"] > end:
                    end, reason = last["end"], last["title"]
        else:
            start = datetime.combine(d, time(7), tz)
            end = datetime.combine(d, time(19), tz)
            if timed:
                start = min(start, min(e["start"] for e in timed))
                last = max(timed, key=lambda e: e["end"])
                if last["end"] > end:
                    end, reason = last["end"], last["title"]
        end = min(end, day_end)

        hours = []
        for r in records:
            if not (start <= r["dt"] <= end + timedelta(minutes=59)) or r.get("temperature") is None:
                continue
            gef = dwd.feels_like(r["temperature"], r.get("wind_speed"), r.get("relative_humidity"))
            hours.append(kleidung.Stunde(
                gefuehlt=gef, temp=r["temperature"],
                regen_prob=r.get("precipitation_probability") or (100 if (r.get("precipitation") or 0) >= 0.3 else 0),
                regen_mm=r.get("precipitation") or 0,
                boeen=r.get("wind_gust_speed") or 0,
                sonne_min=r.get("sunshine") or 0,
                schnee=(r.get("icon") in ("snow", "sleet")) or (r.get("condition") in ("snow", "sleet")),
            ))
        rec = kleidung.empfehlen(hours, sensitivity, monat=d.month, uv=uv)
        if rec is None:
            return None
        grund = rec.grund  # wann es regnet, steht in der Kopfzeile der Tageskurve
        until = f"Bis {hm(end)}" if end < day_end else "Bis Mitternacht"
        if d != now.date():
            until = f"Morgen {hm(start)}–{hm(end)}"
        # "Warm und regenfest anziehen" -> "Anziehen: warm und regenfest"
        title = rec.titel
        if title.endswith(" anziehen"):
            title = title[: -len(" anziehen")]
            title = title[:1].lower() + title[1:]
        return {
            "title": title,
            "pieces": [{"svg": kleidung.ICONS.get(icon, ""), "text": text} for icon, text in rec.teile],
            "why": f"{until}: {grund}",
            "reason_event": reason,
            "sensitivity": SENSITIVITY_LABEL.get(sensitivity, ""),
        }
