"""Apparence de GitHub Hub, accent émeraude, toujours sombre (Ruling V57). Main.qml chargé pour de vrai
(QT_QPA_PLATFORM=offscreen) : la palette de Style.qml, celle posée à la racine, celle des contrôles dessinés par le
style KDE (dialogues, infobulles) et quelques dimensions de GitHub Hub. Rien n'est lancé."""
import configparser
import re
import sys
import tempfile
import unittest
from pathlib import Path

ICI = Path(__file__).resolve().parent
FENETRE = ICI.parent / "fenetre"
sys.path.insert(0, str(FENETRE))

from PySide6.QtCore import QUrl  # noqa: E402
from PySide6.QtQml import QQmlApplicationEngine  # noqa: E402

from tests.appli_qt import APP  # noqa: E402
from tests.test_menu import Base, attendre  # noqa: E402

# Valeurs de la maquette validée (docs/maquettes/palette-verte.html, variante B — Émeraude).
PALETTE = {
    "fond": "#0b0e14", "fondMenu": "#10141c", "carte": "#151a23", "releve": "#1b2130",
    "ligne": "#262d3b", "ligne2": "#313a4c",
    "texte": "#e7ecf3", "texteAttenue": "#8a94a7", "texteDim": "#5d6779",
    "accent": "#34d399", "accent2": "#10b981", "texteSurAccent": "#062a1e",
    "ok": "#3fb950", "attention": "#e3a52f", "echec": "#f2555a",
}
PALETTE_KDE = FENETRE / "health-hub.colors"
UI_WIDGET = ICI.parent / "plasmoide" / "org.toolbox.centrebazzite" / "contents" / "ui"


class Palette(Base):
    def couleur(self, js):
        return self.evaluer("String(%s)" % js)

    def test_palette_exacte(self):
        for nom, valeur in PALETTE.items():
            self.assertEqual(self.couleur("Style." + nom), valeur, nom)

    def test_racine_toujours_sombre(self):
        page = "contenu.item.Kirigami.Theme."
        self.assertEqual(self.couleur(page + "backgroundColor"), "#0b0e14")
        self.assertEqual(self.couleur(page + "highlightColor"), "#34d399")
        self.assertEqual(self.couleur(page + "textColor"), "#e7ecf3")
        self.assertEqual(self.couleur(page + "highlightedTextColor"), "#062a1e")
        self.assertEqual(self.couleur(page + "positiveTextColor"), "#3fb950")
        self.assertEqual(self.couleur(page + "neutralTextColor"), "#e3a52f")
        self.assertEqual(self.couleur(page + "negativeTextColor"), "#f2555a")

    def test_menu_et_panneau_sur_le_fond_du_menu(self):
        self.assertEqual(self.f.objet("menu-lateral").property("color").name(), "#10141c")
        self.assertEqual(self.f.objet("activite-panneau").property("color").name(), "#10141c")

    def test_dialogue_sombre_meme_dessine_par_le_style(self):
        """Le contenu d'un Kirigami.PromptDialog n'hérite pas de la racine (colorSet View, inherit: false) : il
        prend la palette KDE de l'appli. Ouvrir la confirmation ne lance rien."""
        self.appeler("demanderMaj", True)
        self.assertTrue(self.ouvert("confirmation-extinction"))
        self.assertEqual(self.couleur("confirmationExtinction.contentItem.Kirigami.Theme.backgroundColor"), "#10141c")
        self.assertEqual(self.couleur("confirmationExtinction.contentItem.Kirigami.Theme.textColor"), "#e7ecf3")
        self.assertEqual(self.couleur("confirmationExtinction.background.color"), "#10141c")
        self.assertEqual(self.evaluer("confirmationExtinction.background.radius"), 18)
        self.assertEqual(self.maj(), [])

    def test_infobulles_sombres(self):
        bulle = "contenu.Controls.ToolTip.toolTip.Kirigami.Theme."
        self.assertEqual(self.couleur(bulle + "backgroundColor"), "#1b2130")
        self.assertEqual(self.couleur(bulle + "textColor"), "#e7ecf3")


class Dimensions(Base):
    def test_menu_250(self):
        self.assertTrue(self.f.objet("menu-lateral").property("deplie"))
        self.assertEqual(self.f.objet("menu-lateral").property("width"), 250)

    def test_activite_380(self):
        self.fenetre.setProperty("activiteOuverte", True)
        attendre(600)
        self.assertEqual(self.f.objet("activite-panneau").property("width"), 380)

    def test_barre_4px(self):
        barres = [o for o in self.f.tout() if o.metaObject().className().startswith("Progression")]
        self.assertTrue(barres)
        for barre in barres:
            self.assertEqual(barre.property("height"), 4)

    def test_bouton_principal_34(self):
        self.assertEqual(self.f.objet("bouton-principal").property("height"), 34)


class Sources(unittest.TestCase):
    def test_aucun_hex_hors_style(self):
        hex_ = re.compile(r"#[0-9a-fA-F]{3,8}\b")
        for fichier in sorted((FENETRE / "qml").glob("*.qml")):
            if fichier.name == "Style.qml":
                continue
            trouves = hex_.findall(fichier.read_text(encoding="utf-8"))
            self.assertEqual(trouves, [], fichier.name)

    def lire_palette_kde(self):
        config = configparser.ConfigParser(interpolation=None)
        config.optionxform = str
        config.read(PALETTE_KDE, encoding="utf-8")
        return config

    @staticmethod
    def hexa(rgb):
        return "#" + "".join("%02x" % int(x) for x in rgb.split(","))

    def test_palette_kde_suit_style(self):
        """health-hub.colors traduit la palette de Style.qml pour le style KDE : les mêmes couleurs, rien d'autre."""
        config = self.lire_palette_kde()
        roles = {
            ("Colors:Window", "BackgroundNormal"): "fond",
            ("Colors:Window", "BackgroundAlternate"): "fondMenu",
            ("Colors:View", "BackgroundNormal"): "fondMenu",
            ("Colors:View", "BackgroundAlternate"): "carte",
            ("Colors:Button", "BackgroundNormal"): "releve",
            ("Colors:Tooltip", "BackgroundNormal"): "releve",
            ("Colors:Complementary", "BackgroundNormal"): "releve",
            ("Colors:Header", "BackgroundNormal"): "fondMenu",
            ("Colors:Selection", "BackgroundNormal"): "accent",
            ("Colors:Selection", "ForegroundNormal"): "texteSurAccent",
        }
        for (section, cle), nom in roles.items():
            self.assertEqual(self.hexa(config[section][cle]), PALETTE[nom], section + " " + cle)
        for section in ("Colors:Window", "Colors:View", "Colors:Button", "Colors:Tooltip", "Colors:Complementary",
                        "Colors:Header"):
            s = config[section]
            self.assertEqual(self.hexa(s["ForegroundNormal"]), PALETTE["texte"], section)
            self.assertEqual(self.hexa(s["ForegroundInactive"]), PALETTE["texteAttenue"], section)
            self.assertEqual(self.hexa(s["ForegroundPositive"]), PALETTE["ok"], section)
            self.assertEqual(self.hexa(s["ForegroundNeutral"]), PALETTE["attention"], section)
            self.assertEqual(self.hexa(s["ForegroundNegative"]), PALETTE["echec"], section)
            for cle in ("ForegroundActive", "ForegroundLink", "DecorationFocus", "DecorationHover"):
                self.assertEqual(self.hexa(s[cle]), PALETTE["accent"], section + " " + cle)
        couleurs = {self.hexa(v) for s in config.sections() if s.startswith("Colors:")
                    for v in config[s].values()}
        self.assertLessEqual(couleurs, set(PALETTE.values()))

    def test_widget_garde_plasma_avec_l_accent_emeraude(self):
        """Le widget ne peut pas lire Style.qml : ses éléments d'accent (badges info/en cours, barre de progression)
        portent les deux émeraudes de la palette, choisies selon le fond du thème Plasma ; le reste suit Plasma."""
        for nom in ("Badge.qml", "Progression.qml"):
            texte = (UI_WIDGET / nom).read_text(encoding="utf-8")
            self.assertIn("readonly property color accent: Kirigami.Theme.backgroundColor.hslLightness > 0.5", texte, nom)
            self.assertEqual(sorted(re.findall(r"#[0-9a-fA-F]{3,8}\b", texte)),
                             sorted([PALETTE["accent"], PALETTE["accent2"]]), nom)
            self.assertNotIn("highlightColor", texte, nom)

    def test_palette_kde_posee_sur_l_appli(self):
        self.assertTrue(PALETTE_KDE.is_file())
        self.assertEqual(APP.property("KDE_COLOR_SCHEME_PATH"), str(PALETTE_KDE))


class AccentDuWidget(unittest.TestCase):
    """Revue finale M7 : le widget suit Plasma, clair ou sombre ; son accent émeraude reste lisible sur les deux. La
    barre du widget est chargée (depuis un fichier, dans une fenêtre : hors scène, le thème Kirigami ne se propage
    pas) sous un fond de thème Plasma clair, puis sombre."""

    def accent(self, fond):
        with tempfile.TemporaryDirectory() as d:
            essai = Path(d) / "Essai.qml"
            essai.write_text(f'''import QtQuick
import org.kde.kirigami as Kirigami
import "{UI_WIDGET.as_uri()}" as Widget

Window {{
    readonly property color accent: barre.accent

    Item {{
        Kirigami.Theme.inherit: false
        Kirigami.Theme.backgroundColor: "{fond}"

        Widget.Progression {{
            id: barre
        }}
    }}
}}
''', encoding="utf-8")
            moteur = QQmlApplicationEngine()
            moteur.load(QUrl.fromLocalFile(str(essai)))
            self.assertTrue(moteur.rootObjects(), "Essai.qml ne s'est pas chargé")
            valeur = moteur.rootObjects()[0].property("accent").name()
            del moteur
            return valeur

    def test_emeraude_foncee_sur_un_theme_clair(self):
        self.assertEqual(self.accent("#eff0f1"), PALETTE["accent2"])      # fond de Breeze clair

    def test_emeraude_claire_sur_un_theme_sombre(self):
        self.assertEqual(self.accent("#202326"), PALETTE["accent"])       # fond de Breeze sombre


if __name__ == "__main__":
    unittest.main()
