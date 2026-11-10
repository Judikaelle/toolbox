"""Point unique de création de l'application Qt des tests : toujours une QApplication (Kirigami plante sur une
QCoreApplication), quel que soit le module chargé en premier."""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "fenetre"))

from PySide6.QtQuickControls2 import QQuickStyle  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import apparence  # noqa: E402

QQuickStyle.setStyle("org.kde.desktop")
APP = QApplication.instance() or QApplication(sys.argv[:1])
apparence.appliquer(APP)        # comme le lanceur : la palette sombre de Health Hub
