import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami
import "."

// Un disque physique dans la vue d'ensemble de Stockage (titre et modèle en badges neutres) et une ligne par volume :
// nom, barre de l'espace libre, Go libres (jamais l'espace utilisé), état écrit. L'état vient du moteur (stockage.py).
// Un clic sur une ligne ouvre l'onglet du volume (Task 19), où vivent son système de fichiers et son analyse.
ColumnLayout {
    id: bloc

    property var disque: ({})

    signal ouvrir(string chemin)

    readonly property var volumes: disque.volumes ?? []

    objectName: "stockage-disque-" + (disque.id ?? "")
    spacing: Style.espace(1)

    RowLayout {
        Layout.fillWidth: true
        Layout.bottomMargin: Style.espace(1)
        spacing: Style.espace(2)

        Badge {
            objectName: "stockage-disque-titre-" + (bloc.disque.id ?? "")
            texte: bloc.disque.titre ?? ""
            point: false
        }
        Badge {
            objectName: "stockage-disque-modele-" + (bloc.disque.id ?? "")
            visible: texte !== ""
            texte: bloc.disque.modele ?? ""
            point: false
        }
        Item {
            Layout.fillWidth: true
        }
    }

    // Le badge le plus long réserve sa place : les barres restent alignées d'une ligne à l'autre.
    Badge {
        id: plusLong

        visible: false
        texte: "Peu d'espace libre"
    }

    Repeater {
        model: bloc.volumes

        delegate: Controls.AbstractButton {
            id: ligne

            required property var modelData
            readonly property string chemin: modelData.chemin ?? ""
            readonly property string nom: modelData.nom ?? chemin
            readonly property string etat: modelData.etat ?? "ok"

            objectName: "stockage-ligne-" + chemin
            Layout.fillWidth: true
            hoverEnabled: true
            topPadding: Style.espace(1)
            bottomPadding: Style.espace(1)
            leftPadding: Style.espace(2)
            rightPadding: Style.espace(2)
            Accessible.role: Accessible.Button
            Accessible.name: nom + " : " + jauge.libre + ", " + etiquette.texte + ". Ouvre l'onglet du volume."
            onClicked: bloc.ouvrir(chemin)

            contentItem: RowLayout {
                spacing: Style.espace(3)

                Jauge {
                    id: jauge

                    objectName: "jauge-" + ligne.chemin
                    Layout.fillWidth: true
                    Layout.alignment: Qt.AlignVCenter
                    nom: ligne.nom
                    libreGo: ligne.modelData.libre_go ?? 0
                    totalGo: ligne.modelData.total_go ?? 0
                    etat: ligne.etat
                    badgeAlerte: false
                }
                Item {
                    Layout.preferredWidth: plusLong.implicitWidth
                    Layout.alignment: Qt.AlignVCenter
                    implicitHeight: etiquette.implicitHeight

                    Badge {
                        id: etiquette

                        objectName: "stockage-etat-" + ligne.chemin
                        texte: ligne.etat === "ok" ? "OK" : "Peu d'espace libre"
                        etat: ligne.etat
                    }
                }
                Kirigami.Icon {
                    Layout.alignment: Qt.AlignVCenter
                    implicitWidth: Kirigami.Units.iconSizes.small
                    implicitHeight: implicitWidth
                    source: "go-next-symbolic"
                    color: ligne.hovered ? Style.texte : Style.texteDim
                }
            }
            background: Rectangle {
                radius: Style.rayonControle
                color: ligne.hovered || ligne.down ? Style.releve : "transparent"
                border.width: ligne.visualFocus ? 2 : 0
                border.color: Style.accent

                Behavior on color {
                    ColorAnimation { duration: Style.dureeSurvol }
                }
            }
        }
    }
}
