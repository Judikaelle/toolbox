"""Palette KDE de la fenêtre : toujours sombre, accent émeraude (Ruling V57), quel que soit le thème de Plasma.

Main.qml pose la palette de Style.qml à la racine, mais les contrôles dessinés par le style KDE (dialogues, infobulles,
champs, notifications) prennent les couleurs du schéma de l'application, sans hériter de la racine. On leur donne
health-hub.colors, la même palette au format KColorScheme, avant de charger le QML."""
from pathlib import Path

PALETTE = Path(__file__).resolve().parent / "health-hub.colors"


def appliquer(app):
    """À appeler juste après la création de la QApplication, avant de charger Main.qml."""
    app.setProperty("KDE_COLOR_SCHEME_PATH", str(PALETTE))
