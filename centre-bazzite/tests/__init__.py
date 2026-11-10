"""Les tests ne lisent jamais la configuration locale (~/.config/health-hub/config.toml) : la leur est
echantillons/config.toml, ou celle que `configuration()` écrit le temps d'un bloc."""
import contextlib
import tempfile
from pathlib import Path

from centre_bazzite import config

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
