import QtQuick
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami
import "."

// Le bouton principal d'un écran (un seul par écran) : dégradé émeraude, texte foncé, halo léger de l'accent
// (le seul effet d'ombre de la fenêtre). Désactivé : à moitié transparent, sans halo.
Controls.Button {
    id: bouton

    property string raccourci: ""
    property bool occupe: false
    property string libelle: text      // nom lu dans l'infobulle quand le bouton n'a que son icône
    readonly property string infobulle: text !== "" ? raccourci : libelle + " (" + raccourci + ")"

    implicitHeight: Style.hauteurBouton
    leftPadding: Style.espace(4)
    rightPadding: Style.espace(4)
    Controls.ToolTip.visible: raccourci !== "" && hovered
    Controls.ToolTip.delay: Kirigami.Units.toolTipDelay
    Controls.ToolTip.text: infobulle
    Shortcut {
        enabled: bouton.raccourci !== "" && bouton.enabled && bouton.visible
        sequence: bouton.raccourci
        onActivated: bouton.clicked()
    }

    contentItem: Row {
        spacing: Style.espace(2)
        opacity: bouton.enabled || bouton.occupe ? 1 : 0.5     // l'indicateur d'occupation reste net

        Controls.BusyIndicator {
            visible: bouton.occupe
            running: visible
            width: 14
            height: 14
            anchors.verticalCenter: parent.verticalCenter
            Kirigami.Theme.textColor: Style.texteSurAccent
        }
        Kirigami.Icon {
            visible: bouton.icon.name !== "" && !bouton.occupe
            source: bouton.icon.name
            color: Style.texteSurAccent
            width: Kirigami.Units.iconSizes.small
            height: width
            anchors.verticalCenter: parent.verticalCenter
        }
        Controls.Label {
            visible: bouton.text !== ""
            text: bouton.text
            color: Style.texteSurAccent
            font.weight: Font.DemiBold
            font.pointSize: Style.tailleBouton
            anchors.verticalCenter: parent.verticalCenter
        }
    }
    background: Item {
        implicitHeight: Style.hauteurBouton

        // Le halo : 0 4px 14px de l'accent à 30 %, comme le bouton principal de GitHub Hub.
        Kirigami.ShadowedRectangle {
            visible: bouton.enabled
            anchors.fill: fondBouton
            radius: Style.rayonControle
            color: Style.accent2
            shadow.size: 14
            shadow.yOffset: 4
            shadow.color: Qt.alpha(Style.accent, 0.3)
        }
        Rectangle {
            id: fondBouton

            width: parent.width
            height: parent.height
            y: bouton.down ? 1 : 0
            radius: Style.rayonControle
            opacity: bouton.enabled ? 1 : 0.5
            border.width: bouton.visualFocus ? 2 : 0
            border.color: Style.texte
            gradient: Gradient {
                orientation: Gradient.Horizontal
                GradientStop { position: 0; color: bouton.hovered ? Qt.lighter(Style.accent2, 1.1) : Style.accent2 }
                GradientStop { position: 1; color: bouton.hovered ? Qt.lighter(Style.accent, 1.1) : Style.accent }
            }
        }
    }
}
