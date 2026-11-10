"""Point unique de création de l'application Qt des tests : toujours une QApplication (Kirigami plante sur une
QCoreApplication), quel que soit le module chargé en premier. Ici aussi, le filet des commandes de la fenêtre
(sans_commande) et l'arrêt d'un pont dont le test est fini (arreter_pont)."""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "fenetre"))

from PySide6.QtCore import QProcess, QTimer  # noqa: E402
from PySide6.QtQuickControls2 import QQuickStyle  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import apparence  # noqa: E402

QQuickStyle.setStyle("org.kde.desktop")
APP = QApplication.instance() or QApplication(sys.argv[:1])
apparence.appliquer(APP)        # comme le lanceur : la palette sombre de Health Hub


def sans_commande(programme, arguments=(), *_autres):
    """Filet (UI-m1) : le QProcess.startDetached des tests. Aucune vraie commande ne part d'un pont pendant les tests ;
    un test qui veut voir les commandes le remplace par son faux le temps du test (mock.patch.object), puis le filet
    revient. Un appel ici est une fuite : il est dit sur stderr et rien n'est lancé."""
    print(f"filet des tests : commande non lancée : {programme} {' '.join(map(str, arguments))}", file=sys.stderr)
    return False, 0


QProcess.startDetached = sans_commande


def arreter_pont(pont):
    """Un pont dont le test est fini ne fait plus rien (UI-m1) : la garde d'état forcé (V46) l'empêche de lancer quoi
    que ce soit, ses minuteurs s'arrêtent et son veilleur de fichiers ne le réveille plus. Sans cela, il survit au test
    (deleteLater n'agit qu'au retour dans une boucle d'événements, que les tests ne lancent pas) : la suppression de son
    dossier temporaire réveille son veilleur, qui relance son suivi de 5 s, et ses `rafraichir` tombent dans le faux
    startDetached d'un test suivant (ou dans le filet)."""
    if getattr(pont, "_arrete_par_le_test", False):
        return
    pont._arrete_par_le_test = True
    pont._etat_force = True
    pont._minuteur.timeout.disconnect()
    for minuteur in pont.findChildren(QTimer):
        minuteur.stop()
    veilleur = pont._veilleur
    veilleur.fileChanged.disconnect()
    veilleur.directoryChanged.disconnect()
    chemins = veilleur.files() + veilleur.directories()
    if chemins:
        veilleur.removePaths(chemins)
