import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami
import "."

// Colonne « Activité » à droite de la fenêtre : les tâches en cours et récentes (pont.taches).
Rectangle {
    id: panneau

    // Tâche dépliée d'office (un échec vient d'arriver).
    property string depliee: ""
    signal fermer()

    readonly property var taches: pont.taches
    readonly property bool aEffacer: taches.some(t => t.statut !== "en_cours")

    objectName: "activite-panneau"
    color: Style.fondMenu
    clip: true

    ColumnLayout {
        // Largeur fixe : le contenu ne se reflue pas pendant que le panneau glisse.
        width: Style.largeurActivite
        height: parent.height
        spacing: Style.espace(3)

        RowLayout {
            Layout.fillWidth: true
            Layout.margins: Style.espace(3)
            Layout.bottomMargin: 0
            spacing: Style.espace(1)

            Kirigami.Heading {
                Layout.fillWidth: true
                level: 3
                text: "Activité"
                font.pointSize: Style.tailleTitreCarte
                font.weight: Font.Bold
            }
            Bouton {
                objectName: "activite-effacer"
                flat: true
                enabled: panneau.aEffacer
                text: "Effacer terminées"
                onClicked: pont.effacerTerminees()
            }
            Controls.ToolButton {
                objectName: "activite-fermer"
                icon.name: "window-close"
                display: Controls.AbstractButton.IconOnly
                text: "Fermer l'activité"
                Accessible.name: text
                Controls.ToolTip.visible: hovered
                Controls.ToolTip.delay: Kirigami.Units.toolTipDelay
                Controls.ToolTip.text: text
                onClicked: panneau.fermer()
            }
        }

        Rectangle {
            Layout.fillWidth: true
            implicitHeight: 1
            color: Style.ligne
        }

        EtatVide {
            objectName: "activite-vide"
            visible: panneau.taches.length === 0
            Layout.fillWidth: true
            Layout.leftMargin: Style.espace(3)
            Layout.rightMargin: Style.espace(3)
            icone: "view-list-details"
            texte: "Aucune tâche en cours."
        }
        ListView {
            id: liste

            visible: panneau.taches.length > 0
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.minimumHeight: 0
            clip: true
            spacing: Style.espace(3)
            leftMargin: Style.espace(3)
            rightMargin: Style.espace(3)
            bottomMargin: Style.espace(3)
            model: panneau.taches
            boundsBehavior: Flickable.StopAtBounds
            Controls.ScrollBar.vertical: Controls.ScrollBar {
                policy: Controls.ScrollBar.AsNeeded
            }

            delegate: TacheCarte {
                required property var modelData

                width: liste.width - liste.leftMargin - liste.rightMargin
                tache: modelData
                force: modelData.id === panneau.depliee
            }
        }
        Item {
            visible: panneau.taches.length === 0
            Layout.fillHeight: true
        }
    }
}
