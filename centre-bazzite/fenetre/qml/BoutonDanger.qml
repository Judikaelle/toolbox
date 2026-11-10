import QtQuick
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami
import "."

// Action destructrice : simple texte rouge, sans fond (la confirmation précède toujours le clic final).
Controls.Button {
    id: bouton

    readonly property color couleur: Style.echec

    flat: true
    implicitHeight: Style.hauteurBouton
    leftPadding: Style.espace(3.5)
    rightPadding: Style.espace(3.5)

    contentItem: Row {
        spacing: Style.espace(2)
        opacity: bouton.enabled ? 1 : 0.5

        Kirigami.Icon {
            visible: bouton.icon.name !== ""
            source: bouton.icon.name
            color: bouton.couleur
            width: Kirigami.Units.iconSizes.small
            height: width
            anchors.verticalCenter: parent.verticalCenter
        }
        Controls.Label {
            text: bouton.text
            color: bouton.couleur
            font.weight: Font.DemiBold
            font.pointSize: Style.tailleBouton
            anchors.verticalCenter: parent.verticalCenter
        }
    }
    background: Rectangle {
        y: bouton.down ? 1 : 0
        implicitHeight: Style.hauteurBouton
        height: parent.height
        width: parent.width
        radius: Style.rayonControle
        color: bouton.enabled && (bouton.hovered || bouton.down) ? Style.teinteFond(bouton.couleur) : "transparent"
        border.width: bouton.visualFocus ? 2 : 0
        border.color: Style.accent
        Behavior on color {
            ColorAnimation { duration: Style.dureeSurvol }
        }
    }
}
