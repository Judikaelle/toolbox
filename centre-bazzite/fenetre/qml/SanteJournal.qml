import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami
import "."

// Onglet Journal de la santé (Task 19), « pour information » : les erreurs du journal système et les plantages récents
// (les plus récents d'abord), côte à côte sur une fenêtre large ; puis les points de la santé mis en sourdine, avec
// « Signaler à nouveau ».
ColumnLayout {
    id: onglet

    required property var page      // la page Santé : ses données et ses formats

    readonly property var erreurs: page.sante.erreurs_journal ?? []
    readonly property var plantages: (page.sante.plantages ?? []).slice()
        .sort((a, b) => String(b.date ?? "").localeCompare(String(a.date ?? "")))
    // Côte à côte dès 40 unités de grille (720 px de contenu : fenêtre de 1100 px, menu déplié).
    readonly property bool deuxColonnes: width >= Kirigami.Units.gridUnit * 40

    objectName: "sante-onglet-journal"
    spacing: Style.gouttiere

    RowLayout {
        objectName: "journal-pour-information"
        Layout.fillWidth: true
        spacing: Style.espace(3)

        Intertitre {
            text: "Pour information"
        }
        Controls.Label {
            Layout.fillWidth: true
            text: "Rien d'urgent : ces lignes servent à comprendre un souci, pas à agir."
            color: Style.texteAttenue
            font.pointSize: Style.tailleMeta
            wrapMode: Text.WordWrap
        }
    }

    GridLayout {
        id: grille

        // Tirée de la largeur de l'onglet : un maximum tiré de la grille la bloquerait.
        readonly property real largeurColonne: onglet.deuxColonnes ? (onglet.width - columnSpacing) / 2 : onglet.width

        Layout.fillWidth: true
        columns: onglet.deuxColonnes ? 2 : 1
        columnSpacing: Style.gouttiere
        rowSpacing: Style.gouttiere

        Carte {
            objectName: "journal-erreurs"
            Layout.alignment: Qt.AlignTop
            Layout.fillWidth: true
            Layout.minimumWidth: 0
            Layout.preferredWidth: grille.largeurColonne
            Layout.maximumWidth: grille.largeurColonne
            titre: "Erreurs du journal système"

            Controls.Label {
                visible: onglet.erreurs.length === 0
                text: "Aucune erreur récente."
                color: Style.texteAttenue
            }
            ColumnLayout {
                Layout.fillWidth: true
                visible: onglet.erreurs.length > 0
                spacing: Style.espace(1.5)

                Repeater {
                    model: onglet.erreurs

                    delegate: ColumnLayout {
                        id: erreur

                        required property var modelData
                        required property int index

                        objectName: "journal-erreur-" + index
                        Layout.fillWidth: true
                        spacing: 0

                        RowLayout {
                            Layout.fillWidth: true
                            spacing: Style.espace(2)

                            TexteAbrege {
                                Layout.fillWidth: true
                                text: String(erreur.modelData.message ?? "").trim()
                            }
                            Controls.Label {
                                text: "× " + erreur.modelData.nombre
                                color: Style.texteAttenue
                                font.features: ({ "tnum": 1 })
                            }
                        }
                        TexteAbrege {
                            Layout.fillWidth: true
                            text: erreur.modelData.source ?? ""
                            color: Style.texteAttenue
                            font.pointSize: Style.tailleMeta
                        }
                    }
                }
            }
        }

        Carte {
            objectName: "journal-plantages"
            Layout.alignment: Qt.AlignTop
            Layout.fillWidth: true
            Layout.minimumWidth: 0
            Layout.preferredWidth: grille.largeurColonne
            Layout.maximumWidth: grille.largeurColonne
            titre: "Plantages récents"

            Controls.Label {
                visible: onglet.plantages.length === 0
                text: "Aucun plantage récent."
                color: Style.texteAttenue
            }
            ColumnLayout {
                Layout.fillWidth: true
                visible: onglet.plantages.length > 0
                spacing: Style.espace(0.5)

                Repeater {
                    model: onglet.plantages

                    delegate: RowLayout {
                        id: plantage

                        required property var modelData
                        required property int index

                        objectName: "journal-plantage-" + index
                        Layout.fillWidth: true
                        spacing: Style.espace(3)

                        TexteAbrege {
                            objectName: "journal-exe-" + plantage.index
                            Layout.fillWidth: true
                            text: plantage.modelData.exe ?? ""
                        }
                        Controls.Label {
                            text: "signal " + plantage.modelData.signal
                            color: Style.texteAttenue
                            font.pointSize: Style.tailleMeta
                        }
                        Controls.Label {
                            text: onglet.page.jourHeure(plantage.modelData.date)
                            color: Style.texteAttenue
                            font.pointSize: Style.tailleMeta
                            font.features: ({ "tnum": 1 })
                        }
                    }
                }
            }
        }
    }

    // Les points de la santé mis en sourdine : grisés, avec le moyen de les signaler à nouveau.
    ColumnLayout {
        Layout.fillWidth: true
        visible: onglet.page.sourdines.length > 0
        spacing: Style.espace(1)

        Intertitre {
            text: "En sourdine"
        }
        Repeater {
            model: onglet.page.sourdines

            delegate: RowLayout {
                id: ligne

                required property var modelData

                objectName: "sourdine-" + modelData.id
                Layout.fillWidth: true
                spacing: Kirigami.Units.largeSpacing

                Controls.Label {
                    Layout.fillWidth: true
                    text: ligne.modelData.titre + " (ne plus signalé)"
                    color: Style.texteAttenue
                    wrapMode: Text.WordWrap
                }
                Bouton {
                    flat: true
                    text: "Signaler à nouveau"
                    icon.name: "notifications"
                    onClicked: pont.sansSourdine(ligne.modelData.id)
                }
            }
        }
    }
}
