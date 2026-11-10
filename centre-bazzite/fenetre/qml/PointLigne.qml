import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami
import "."

// Un point signalé : son état écrit, son explication, l'action proposée et « Ne plus signaler ».
RowLayout {
    id: ligne

    required property var point
    property int lignesTitre: 0              // > 0 : le titre est abrégé (…) au-delà de ce nombre de lignes
    property bool actionPermise: true        // faux : l'action du point n'est pas proposée (ex. pendant une mise à jour)

    readonly property bool echec: point.gravite === "echec"
    // Seules les informations « mise à jour disponible » sont listées (même règle que points.compteurs).
    readonly property var etiquette: echec ? { "mot": "Échec", "etat": "echec" }
                                 : point.gravite === "info" ? { "mot": "Disponible", "etat": "info" }
                                 : { "mot": "Attention", "etat": "attention" }

    signal agir()
    signal nePlusSignaler()

    spacing: Kirigami.Units.largeSpacing

    Item {
        Layout.preferredWidth: Kirigami.Units.gridUnit * 5
        Layout.minimumWidth: Layout.preferredWidth
        Layout.maximumWidth: Layout.preferredWidth
        Layout.alignment: Qt.AlignTop
        implicitHeight: marque.implicitHeight

        Badge {
            id: marque

            objectName: "badge-point-" + ligne.point.id
            texte: ligne.etiquette.mot
            etat: ligne.etiquette.etat
        }
    }

    ColumnLayout {
        Layout.fillWidth: true
        spacing: Math.round(Kirigami.Units.smallSpacing / 2)

        Controls.Label {
            Layout.fillWidth: true
            text: ligne.point.titre ?? ""
            font.weight: Font.DemiBold
            wrapMode: Text.Wrap
            maximumLineCount: ligne.lignesTitre > 0 ? ligne.lignesTitre : 2147483647
            elide: ligne.lignesTitre > 0 ? Text.ElideRight : Text.ElideNone
        }
        Controls.Label {
            Layout.fillWidth: true
            visible: text !== ""
            text: ligne.point.detail ?? ""
            wrapMode: Text.Wrap
            color: Style.texteAttenue
        }
    }

    Bouton {
        objectName: "point-action-" + ligne.point.id
        Layout.alignment: Qt.AlignVCenter
        visible: !!ligne.point.action && ligne.actionPermise
        text: ligne.point.action?.libelle ?? ""
        onClicked: ligne.agir()
    }

    Bouton {
        objectName: "point-sourdine-" + ligne.point.id
        Layout.alignment: Qt.AlignVCenter
        flat: true
        text: "Ne plus signaler"
        icon.name: "notifications-disabled"
        Controls.ToolTip.visible: hovered
        Controls.ToolTip.delay: Kirigami.Units.toolTipDelay
        Controls.ToolTip.text: "Masque ce point jusqu'à ce qu'il empire."
        onClicked: ligne.nePlusSignaler()
    }
}
