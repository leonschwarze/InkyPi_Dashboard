"""
Zeichensatz für InkyPis Bildvorlagen: immer UTF-8.

InkyPis Basis-Template (base_plugin/render/plugin.html) nennt keinen Zeichensatz. Chromium rät
ihn dann aus dem Inhalt. Bei vielen Akzenten (z. B. französische Schlagzeilen, Terminnamen) hält
er die Seite für Latin-1, und aus „é“ wird „Ã©“, aus „ü“ „Ã¼“ – auf der ganzen Seite.

utf8_templates(plugin) hängt sich vor den Template-Lader des Plugins: plugin.html kommt weiter
unverändert aus InkyPi (so bleiben Updates des Basis-Templates wirksam), bekommt aber direkt nach
<head> die Zeile <meta charset="utf-8">. Steht dort schon ein Zeichensatz, ändert sich nichts.

Quelle: shared/zeichensatz.py. Kopien in dwd_wetter/, nextcloud_kalender/ und tagesdashboard/lib/;
nach Änderungen `python dev/sync_lib.py`.
"""

from jinja2 import BaseLoader

META = '<meta charset="utf-8">'


class Utf8Loader(BaseLoader):
    def __init__(self, inner):
        self.inner = inner

    def get_source(self, environment, template):
        source, filename, uptodate = self.inner.get_source(environment, template)
        if template == "plugin.html" and "charset" not in source[:1024].lower():
            source = source.replace("<head>", f"<head>\n    {META}", 1)
        return source, filename, uptodate

    def list_templates(self):
        return self.inner.list_templates()


def utf8_templates(plugin):
    """Einmal pro Plugin-Objekt aufrufen (mehrfach schadet nicht)."""
    env = getattr(plugin, "env", None)
    if env is not None and not isinstance(env.loader, Utf8Loader):
        env.loader = Utf8Loader(env.loader)
