import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as Controls
import "."

// Un chiffre clé de la santé (usure, température, VRAM…) : la valeur en grand, sa légende atténuée dessous.
ColumnLayout {
    id: mesure

    property string valeur
    property string legende

    spacing: 0

    Controls.Label {
        text: mesure.valeur
        font.pointSize: Style.tailleChiffre
        font.weight: Font.Bold
        font.features: ({ "tnum": 1 })
    }
    Controls.Label {
        text: mesure.legende
        color: Style.texteAttenue
        font.pointSize: Style.tailleMeta
    }
}
