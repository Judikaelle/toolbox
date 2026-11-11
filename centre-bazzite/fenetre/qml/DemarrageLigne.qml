import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami
import "."

// Une ligne de « Au lancement » : le nom, ce que c'est (ou quand ça se lance), l'état, puis les boutons. Les boutons ne
// dépendent que de « modifiable » : sans lui, la raison en texte secondaire et aucun bouton. La ligne ne fait rien
// elle-même : elle signale (basculer, remettre) et l'onglet décide. « occupee » : sa commande tourne (« En cours… »,
// boutons grisés).
ColumnLayout {
    id: ligne

    required property var entree
    property string section: ""
    property bool occupee: false
    readonly property string cle: entree.id.replace(/[^A-Za-z0-9]/g, "_")
    readonly property bool modifiable: !!entree.modifiable

    signal basculer(var entree)
    signal remettre(string id)

    objectName: "entree-" + cle
    Layout.fillWidth: true
    spacing: Style.espace(1)

    // Large : le texte à gauche, l'état et les boutons à droite. Étroit : les boutons passent sous le texte.
    GridLayout {
        Layout.fillWidth: true
        columns: width < Kirigami.Units.gridUnit * 36 ? 1 : 2
        columnSpacing: Style.espace(3)
        rowSpacing: Style.espace(1.5)

        ColumnLayout {
            Layout.fillWidth: true
            spacing: Style.espace(0.5)

            RowLayout {
                Layout.fillWidth: true
                spacing: Style.espace(2)

                TexteAbrege {
                    objectName: "nom-" + ligne.cle
                    Layout.fillWidth: true
                    text: ligne.entree.nom ?? ""
                    font.weight: Font.DemiBold
                }
                Loader {
                    active: !!ligne.entree.avertissement
                    visible: active
                    sourceComponent: Component {
                        Kirigami.Icon {
                            objectName: "avertissement-" + ligne.cle
                            source: "dialog-warning"
                            color: Style.couleurEtat("attention")
                            implicitWidth: Kirigami.Units.iconSizes.small
                            implicitHeight: implicitWidth
                            Accessible.role: Accessible.StaticText
                            Accessible.name: ligne.entree.avertissement
                            HoverHandler {
                                id: survol
                            }
                            Controls.ToolTip.visible: survol.hovered
                            Controls.ToolTip.delay: Kirigami.Units.toolTipDelay
                            Controls.ToolTip.text: ligne.entree.avertissement
                        }
                    }
                }
            }
            Controls.Label {
                objectName: "description-" + ligne.cle
                Layout.fillWidth: true
                visible: text !== ""
                text: ligne.entree.description || ligne.entree.quand || ""
                color: Style.texteAttenue
                wrapMode: Text.WordWrap
            }
            // Quand ça se lance, si la description a pris la première ligne ; en lecture seule, pourquoi.
            Controls.Label {
                objectName: "quand-" + ligne.cle
                Layout.fillWidth: true
                visible: text !== ""
                text: ligne.entree.description ? (ligne.entree.quand ?? "") : ""
                color: Style.texteDim
                font.pointSize: Style.tailleMeta
                wrapMode: Text.WordWrap
            }
            Controls.Label {
                objectName: "raison-" + ligne.cle
                Layout.fillWidth: true
                visible: !ligne.modifiable && text !== ""
                text: ligne.entree.raison ?? ""
                color: Style.texteAttenue
                font.pointSize: Style.tailleMeta
                wrapMode: Text.WordWrap
            }
        }
        RowLayout {
            Layout.alignment: Qt.AlignRight | Qt.AlignVCenter
            spacing: Style.espace(3)

            Controls.Label {
                objectName: "en-cours-" + ligne.cle
                visible: ligne.occupee
                text: "En cours…"
                color: Style.texteAttenue
            }
            Badge {
                objectName: "etat-" + ligne.cle
                texte: ligne.entree.actif ? "Activé" : "Désactivé"
                etat: ligne.entree.actif ? "ok" : "neutre"
            }
            Loader {
                active: !!ligne.entree.modifie
                visible: active
                sourceComponent: Component {
                    Badge {
                        objectName: "modifie-" + ligne.cle
                        texte: "Modifié par Health Hub"
                        etat: "info"
                    }
                }
            }
            Loader {
                active: !!ligne.entree.modifie
                visible: active
                sourceComponent: Component {
                    Bouton {
                        objectName: "remettre-" + ligne.cle
                        enabled: !ligne.occupee
                        text: "Remettre comme avant"
                        icon.name: "edit-undo"
                        onClicked: ligne.remettre(ligne.entree.id)
                    }
                }
            }
            Loader {
                active: ligne.modifiable
                visible: active
                sourceComponent: Component {
                    Bouton {
                        objectName: "basculer-" + ligne.cle
                        enabled: !ligne.occupee
                        text: ligne.entree.actif ? "Désactiver" : "Activer"
                        onClicked: ligne.basculer(ligne.entree)
                    }
                }
            }
        }
    }
}
