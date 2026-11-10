import QtQuick
import QtQuick.Layouts
import org.kde.kirigami as Kirigami
import org.kde.plasma.components as PlasmaComponents3

// Pilule d'état du widget : toujours un mot, la couleur ne porte jamais seule l'information.
// Copie adaptée de fenetre/qml/Badge.qml (le widget ne peut pas importer les QML de la fenêtre) :
// teintes à 14 % (fond) et 35 % (bordure). Le widget garde les couleurs de Plasma, sauf l'accent : l'émeraude de
// la fenêtre (Ruling V57) pour « info » et « en cours », la claire (Style.accent) sur un thème Plasma sombre, la plus
// foncée (Style.accent2) sur un thème clair, où la claire se lirait mal.
Rectangle {
    id: badge

    property string texte
    property string etat: "neutre"   // ok | attention | echec | info | en_cours | neutre
    property bool point: true
    readonly property color accent: Kirigami.Theme.backgroundColor.hslLightness > 0.5 ? "#10b981" : "#34d399"

    readonly property color couleur: {
        switch (etat) {
        case "ok": return Kirigami.Theme.positiveTextColor;
        case "attention": return Kirigami.Theme.neutralTextColor;
        case "echec": return Kirigami.Theme.negativeTextColor;
        case "info":
        case "en_cours": return accent;
        default: return Kirigami.Theme.disabledTextColor;
        }
    }

    implicitWidth: ligne.implicitWidth + Kirigami.Units.smallSpacing * 4
    implicitHeight: ligne.implicitHeight + Kirigami.Units.smallSpacing * 1.5
    radius: height / 2
    color: Qt.alpha(couleur, 0.14)
    border.width: 1
    border.color: Qt.alpha(couleur, 0.35)
    Accessible.role: Accessible.StaticText
    Accessible.name: texte

    RowLayout {
        id: ligne

        anchors.centerIn: parent
        spacing: Kirigami.Units.smallSpacing * 1.5

        Rectangle {
            visible: badge.point
            implicitWidth: Kirigami.Units.smallSpacing * 1.5
            implicitHeight: implicitWidth
            radius: width / 2
            color: badge.couleur
        }
        PlasmaComponents3.Label {
            text: badge.texte
            color: badge.couleur
            font.weight: Font.DemiBold
            font.pointSize: Kirigami.Theme.smallFont.pointSize
        }
    }
}
