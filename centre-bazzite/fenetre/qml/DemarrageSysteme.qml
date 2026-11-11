import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami
import "."

// L'onglet Système : les services et minuteurs du système activés, pour tous les comptes, en lecture seule (Health Hub ne
// lance jamais sudo). Un service essentiel porte le badge « Essentiel » et aucune commande ; les autres donnent la commande
// à copier dans un terminal. La liste défile dans sa propre zone, bornée au reste de l'écran.
ColumnLayout {
    id: onglet

    required property var page      // la page Démarrage : ses données

    objectName: "demarrage-systeme"
    spacing: Style.gouttiere

    Controls.Label {
        objectName: "systeme-phrase"
        Layout.fillWidth: true
        text: "Ces services démarrent avec le système, pour tous les comptes. Health Hub ne les change pas : chaque ligne "
              + "donne la commande à copier dans un terminal."
        color: Style.texteAttenue
        wrapMode: Text.WordWrap
    }

    Carte {
        id: carte

        objectName: "systeme-carte"
        Layout.fillWidth: true

        Controls.Label {
            objectName: "systeme-aucun"
            Layout.fillWidth: true
            visible: onglet.page.systeme.length === 0
            text: "Aucun service système relevé."
            color: Style.texteAttenue
        }
        Flickable {
            id: liste

            objectName: "systeme-liste"
            Layout.fillWidth: true
            visible: onglet.page.systeme.length > 0
            // Bornée au reste de l'écran (la page tient sur un écran) : la carte au-dessus, sa marge, puis sa marge du bas.
            Layout.preferredHeight: Math.min(contentHeight, Math.max(Kirigami.Units.gridUnit * 6,
                onglet.page.hauteurOnglet - carte.y - carte.decalageContenu - liste.y - Style.margeCarte))
            contentWidth: width
            contentHeight: lignes.implicitHeight
            clip: true
            interactive: contentHeight > height
            boundsBehavior: Flickable.StopAtBounds
            Controls.ScrollBar.vertical: Controls.ScrollBar {
                policy: Controls.ScrollBar.AsNeeded
            }

            ColumnLayout {
                id: lignes

                width: liste.width - (liste.contentHeight > liste.height ? Style.espace(4) : 0)
                spacing: 0

                Repeater {
                    model: onglet.page.systeme

                    delegate: ColumnLayout {
                        id: rang

                        required property var modelData
                        required property int index
                        readonly property string unite: modelData.unite ?? ""

                        objectName: "service-" + unite
                        Layout.fillWidth: true
                        spacing: Style.espace(1)

                        Kirigami.Separator {
                            Layout.fillWidth: true
                            Layout.bottomMargin: Style.espace(1.5)
                            visible: rang.index > 0
                            color: Style.ligne
                        }
                        RowLayout {
                            Layout.fillWidth: true
                            spacing: Style.espace(3)

                            TexteAbrege {
                                objectName: "systeme-unite-" + rang.unite
                                Layout.fillWidth: true
                                text: rang.unite
                                font.weight: Font.DemiBold
                            }
                            Controls.Label {
                                objectName: "systeme-duree-" + rang.unite
                                text: rang.modelData.duree ?? "—"
                                color: rang.modelData.duree ? Style.texte : Style.texteDim
                                font.features: ({ "tnum": 1 })
                            }
                            Loader {
                                active: !!rang.modelData.essentiel
                                visible: active
                                sourceComponent: Component {
                                    Badge {
                                        objectName: "systeme-essentiel-" + rang.unite
                                        texte: "Essentiel"
                                        etat: "neutre"
                                    }
                                }
                            }
                        }
                        Controls.Label {
                            objectName: "systeme-description-" + rang.unite
                            Layout.fillWidth: true
                            visible: text !== ""
                            text: rang.modelData.description ?? ""
                            wrapMode: Text.WordWrap
                        }
                        Controls.Label {
                            objectName: "systeme-explication-" + rang.unite
                            Layout.fillWidth: true
                            visible: text !== ""
                            text: rang.modelData.explication ?? ""
                            color: Style.texteAttenue
                            font.pointSize: Style.tailleMeta
                            wrapMode: Text.WordWrap
                        }
                        // Les autres : la commande, à copier (rien n'est lancé).
                        Loader {
                            Layout.fillWidth: true
                            Layout.bottomMargin: Style.espace(1.5)
                            active: !rang.modelData.essentiel && !!rang.modelData.commande
                            visible: active
                            sourceComponent: Component {
                                RowLayout {
                                    spacing: Style.espace(3)

                                    Controls.Label {
                                        objectName: "systeme-commande-" + rang.unite
                                        Layout.fillWidth: true
                                        text: rang.modelData.commande
                                        color: Style.texteAttenue
                                        font.family: Kirigami.Theme.fixedWidthFont.family
                                        font.pointSize: Style.tailleMono
                                        elide: Text.ElideRight
                                    }
                                    Bouton {
                                        objectName: "copier-" + rang.unite
                                        text: "Copier la commande"
                                        icon.name: "edit-copy"
                                        onClicked: pont.copier(rang.modelData.commande)
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}
