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
    readonly property var plantages: page.sante.plantages ?? []
    // Une ligne par programme (comme le point « plantages ») : le plus fréquent d'abord, puis le plus récent, pour voir
    // d'un coup d'œil ce qui se répète.
    readonly property var parProgramme: {
        const groupes = {};
        for (const p of plantages) {
            if (!p || typeof p !== "object")
                continue;
            const exe = String(p.exe || "?"), date = String(p.date ?? "");
            const g = groupes[exe] ?? (groupes[exe] = { exe: exe, nombre: 0, dernier: "", signal: p.signal });
            g.nombre += 1;
            if (date > g.dernier) {
                g.dernier = date;
                g.signal = p.signal;
            }
        }
        return Object.values(groupes).sort((a, b) => b.nombre - a.nombre || b.dernier.localeCompare(a.dernier)
                                                   || a.exe.localeCompare(b.exe));
    }
    readonly property var nomsSignaux: ({ 3: "SIGQUIT", 4: "SIGILL", 5: "SIGTRAP", 6: "SIGABRT", 7: "SIGBUS", 8: "SIGFPE",
                                          9: "SIGKILL", 11: "SIGSEGV", 15: "SIGTERM", 31: "SIGSYS" })
    // Les plantages vus par le noyau (journal du noyau de cette session), en plus de ceux de coredumpctl.
    readonly property int plantagesNoyau: page.noyau?.plantages?.nombre ?? 0
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
                objectName: "journal-plantages-noyau"
                Layout.fillWidth: true
                visible: onglet.plantagesNoyau > 0
                text: onglet.plantagesNoyau + (onglet.plantagesNoyau > 1 ? " plantages" : " plantage") + " vus par le noyau"
                color: Style.texteAttenue
                font.pointSize: Style.tailleMeta
                wrapMode: Text.WordWrap
            }

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
                    model: onglet.parProgramme

                    // Comme une erreur du journal : le programme et « N fois » sur la première ligne, le signal et la
                    // date du dernier plantage dessous, pour que le nom du programme reste lisible en deux colonnes.
                    delegate: ColumnLayout {
                        id: plantage

                        required property var modelData
                        required property int index

                        objectName: "journal-plantage-" + index
                        Layout.fillWidth: true
                        spacing: 0

                        RowLayout {
                            Layout.fillWidth: true
                            spacing: Style.espace(2)

                            TexteAbrege {
                                objectName: "journal-exe-" + plantage.index
                                Layout.fillWidth: true
                                text: plantage.modelData.exe
                            }
                            Controls.Label {
                                objectName: "journal-fois-" + plantage.index
                                visible: plantage.modelData.nombre > 1
                                text: plantage.modelData.nombre + " fois"
                                font.weight: Font.DemiBold
                                font.features: ({ "tnum": 1 })
                            }
                        }
                        RowLayout {
                            Layout.fillWidth: true
                            spacing: Style.espace(2)

                            Controls.Label {
                                objectName: "journal-signal-" + plantage.index
                                text: onglet.nomsSignaux[plantage.modelData.signal] ?? ("signal " + plantage.modelData.signal)
                                color: Style.texteAttenue
                                font.pointSize: Style.tailleMeta
                            }
                            TexteAbrege {
                                objectName: "journal-date-" + plantage.index
                                Layout.fillWidth: true
                                text: (plantage.modelData.nombre > 1 ? "dernier le " : "le ")
                                      + onglet.page.jourHeure(plantage.modelData.dernier)
                                color: Style.texteAttenue
                                font.pointSize: Style.tailleMeta
                                font.features: ({ "tnum": 1 })
                            }
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
