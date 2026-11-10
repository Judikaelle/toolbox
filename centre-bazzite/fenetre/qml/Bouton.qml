import QtQuick
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami
import "."

// Bouton secondaire de GitHub Hub : surface relevée, bordure fine, rayon 10, 34 px, texte 13 demi-gras.
// « flat » : transparent, la surface n'apparaît qu'au survol. Désactivé : à moitié transparent.
// display: IconOnly : l'icône seule, le texte en infobulle (et toujours dans le nom accessible).
Controls.Button {
    id: bouton

    readonly property bool iconeSeule: display === Controls.AbstractButton.IconOnly

    implicitHeight: Style.hauteurBouton
    leftPadding: iconeSeule ? Style.espace(2.5) : Style.espace(3.5)
    rightPadding: leftPadding
    Controls.ToolTip.visible: iconeSeule && hovered && text !== ""
    Controls.ToolTip.delay: Kirigami.Units.toolTipDelay
    Controls.ToolTip.text: text

    contentItem: Row {
        spacing: Style.espace(2)
        opacity: bouton.enabled ? 1 : 0.5

        Kirigami.Icon {
            visible: bouton.icon.name !== ""
            source: bouton.icon.name
            color: Style.texte
            width: Kirigami.Units.iconSizes.small
            height: width
            anchors.verticalCenter: parent.verticalCenter
        }
        Controls.Label {
            visible: bouton.text !== "" && !bouton.iconeSeule
            text: bouton.text
            color: Style.texte
            font.weight: Font.DemiBold
            font.pointSize: Style.tailleBouton
            anchors.verticalCenter: parent.verticalCenter
        }
    }
    background: Rectangle {
        y: bouton.down ? 1 : 0
        implicitHeight: Style.hauteurBouton
        width: parent.width
        height: parent.height
        radius: Style.rayonControle
        opacity: bouton.enabled ? 1 : 0.5
        color: bouton.flat ? (bouton.enabled && (bouton.hovered || bouton.down) ? Style.releve : "transparent")
             : bouton.enabled && bouton.hovered ? Qt.lighter(Style.releve, 1.25) : Style.releve
        border.width: bouton.visualFocus ? 2 : bouton.flat ? 0 : 1
        border.color: bouton.visualFocus ? Style.accent
                    : bouton.enabled && bouton.hovered ? Qt.lighter(Style.ligne2, 1.35) : Style.ligne2
        Behavior on color {
            ColorAnimation { duration: Style.dureeSurvol }
        }
    }
}
