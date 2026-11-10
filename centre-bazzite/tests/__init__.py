"""Les tests ne lisent jamais la configuration locale (~/.config/health-hub/config.toml) : la leur est
echantillons/config.toml, ou celle que `configuration()` écrit le temps d'un bloc."""
import contextlib
import os
import tempfile
from pathlib import Path

# Filet D-Bus (mode jeu), posé avant tout import de Qt ou de dbus : aucun test ne joint le vrai bus de session ni le
# bus système (Ne pas déranger, profil d'énergie) ; une connexion oubliée échoue au lieu d'agir sur le bureau.
os.environ["DBUS_SESSION_BUS_ADDRESS"] = os.environ["DBUS_SYSTEM_BUS_ADDRESS"] = "unix:path=/nonexistent/health-hub-tests"

from centre_bazzite import config  # noqa: E402

config.CHEMIN = Path(__file__).resolve().parent / "echantillons" / "config.toml"


@contextlib.contextmanager
def configuration(texte):
    """Le temps du bloc, la configuration lue est un fichier temporaire qui contient `texte` (TOML)."""
    with tempfile.TemporaryDirectory() as dossier:
        chemin = Path(dossier) / "config.toml"
        chemin.write_text(texte, encoding="utf-8")
        ancien, config.CHEMIN = config.CHEMIN, chemin
        try:
            yield chemin
        finally:
            config.CHEMIN = ancien
