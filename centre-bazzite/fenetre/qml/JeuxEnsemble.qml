import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami
import "."

// La vue d'ensemble de Jeux, d'un coup d'œil : ce qui n'a pas pu être lu (s'il y a lieu), puis une ligne par sujet,
// le mode jeu, les bibliothèques, les doublons, le ménage et les gels ; un clic sur une ligne ouvre son onglet.
ColumnLayout {
    id: ensemble

    required property var page      // la page Jeux : ses données et ses formats

    readonly property real enTrop: page.doublons.reduce((total, d) => total + (d.en_trop ?? 0), 0)
    readonly property real aLiberer: page.recosJeux.reduce((total, r) => total + (r.octets ?? 0), 0)
    readonly property int nombrePrefixes: (page.prefixes.elements ?? []).length
    readonly property int nombreGels: page.gels.nombre ?? 0
    readonly property var modeJeu: page.motsModeJeu[page.etatModeJeu] ?? page.motsModeJeu["arrete"]

    objectName: "jeux-ensemble"
    spacing: Style.gouttiere

    // Une source illisible (Heroic, Lutris, Steam…) : ses phrases, telles que le moteur les écrit.
    Kirigami.InlineMessage {
        objectName: "jeux-erreurs"
        Layout.fillWidth: true
        visible: ensemble.page.erreurs.length > 0
        type: Kirigami.MessageType.Warning
        text: ensemble.page.erreurs.join("\n")
    }

    Carte {
        objectName: "jeux-lignes"
        Layout.fillWidth: true

        ColumnLayout {
            Layout.fillWidth: true
            spacing: Style.espace(1)

            Ligne {
                cle: "modejeu"
                nom: "Mode jeu"
                mot: ensemble.modeJeu.mot
                etat: ensemble.modeJeu.badge
                onClicked: ensemble.page.choisir("modejeu")

                TexteAbrege {
                    objectName: "modejeu-phrase"
                    Layout.fillWidth: true
                    text: ensemble.page.phraseModeJeu
                }
                TexteAbrege {
                    objectName: "modejeu-derniere"
                    Layout.fillWidth: true
                    visible: text !== ""
                    text: ensemble.page.modejeu?.derniere?.phrase ?? ""
                    color: Style.texteAttenue
                    font.pointSize: Style.tailleMeta
                }
            }

            // Sans relevé de jeux.json, le reste attend : on le dit, une fois.
            EtatVide {
                objectName: "jeux-vide"
                Layout.fillWidth: true
                Layout.topMargin: Style.espace(1)
                visible: !ensemble.page.releve
                icone: "applications-games"
                texte: ensemble.page.texteVide
            }

            Separateur {}
            Ligne {
                cle: "bibliotheques"
                nom: "Bibliothèques"
                visible: ensemble.page.releve
                onClicked: ensemble.page.ouvrirBibliotheques("")

                // Une ligne par bibliothèque : un clic ouvre l'onglet Bibliothèques filtré sur elle.
                Repeater {
                    model: ensemble.page.bibliotheques

                    delegate: Controls.AbstractButton {
                        id: bib

                        required property var modelData
                        readonly property string bid: modelData.id ?? ""

                        objectName: "ligne-bibliotheque-" + bid
                        Layout.fillWidth: true
                        hoverEnabled: true
                        Accessible.role: Accessible.Button
                        Accessible.name: (modelData.nom ?? "") + ". Montre ses jeux."
                        onClicked: ensemble.page.ouvrirBibliotheques(bid)

                        contentItem: RowLayout {
                            spacing: Style.espace(3)

                            TexteAbrege {
                                objectName: "bibliotheque-nom-" + bib.bid
                                Layout.fillWidth: true
                                text: bib.modelData.nom ?? ""
                            }
                            Badge {
                                objectName: "bibliotheque-absente-" + bib.bid
                                visible: !!bib.modelData.absente
                                texte: "Absente"
                                etat: "neutre"
                            }
                            Controls.Label {
                                objectName: "bibliotheque-nombre-" + bib.bid
                                visible: !bib.modelData.absente
                                text: ensemble.page.pluriel(bib.modelData.nombre ?? 0, "jeu", "jeux")
                                color: Style.texteAttenue
                                font.features: ({ "tnum": 1 })
                            }
                            Controls.Label {
                                objectName: "bibliotheque-taille-" + bib.bid
                                visible: !bib.modelData.absente
                                Layout.preferredWidth: Kirigami.Units.gridUnit * 3.5
                                horizontalAlignment: Text.AlignRight
                                text: bib.modelData.taille ?? ""
                                font.weight: Font.DemiBold
                                font.features: ({ "tnum": 1 })
                            }
                        }
                        background: Rectangle {
                            radius: Style.rayonControle / 2
                            color: "transparent"
                            border.width: bib.visualFocus ? 2 : 0
                            border.color: Style.accent
                        }
                    }
                }
            }

            Separateur {}
            Ligne {
                cle: "doublons"
                nom: "Doublons"
                visible: ensemble.page.releve
                mot: ensemble.page.doublons.length > 0 ? "En double" : ""
                etat: ensemble.page.doublons.length > 0 ? "attention" : ""
                badgeNom: "doublons-badge"
                onClicked: ensemble.page.ouvrirBibliotheques("doublons")

                TexteAbrege {
                    objectName: "doublons-phrase"
                    Layout.fillWidth: true
                    text: ensemble.page.doublons.length === 0 ? "Aucun jeu en double."
                          : ensemble.page.pluriel(ensemble.page.doublons.length, "jeu", "jeux") + " en double : "
                            + Style.taille(ensemble.enTrop) + " en trop"
                }
            }

            Separateur {}
            Ligne {
                cle: "menage"
                nom: "Ménage"
                visible: ensemble.page.releve
                onClicked: ensemble.page.choisir("menage")

                TexteAbrege {
                    objectName: "menage-phrase"
                    Layout.fillWidth: true
                    text: ensemble.aLiberer > 0 ? Style.taille(ensemble.aLiberer) + " à libérer"
                                                : "Rien à libérer côté jeux."
                }
                TexteAbrege {
                    objectName: "prefixes-phrase"
                    Layout.fillWidth: true
                    visible: ensemble.nombrePrefixes > 0
                    text: ensemble.page.pluriel(ensemble.nombrePrefixes, "préfixe orphelin", "préfixes orphelins")
                          + " (" + (ensemble.page.prefixes.taille ?? "") + "), seulement listés"
                    color: Style.texteAttenue
                    font.pointSize: Style.tailleMeta
                }
            }

            Separateur {}
            Ligne {
                cle: "gels"
                nom: "Gels"
                visible: ensemble.page.releve
                onClicked: ensemble.page.choisir("gels")

                TexteAbrege {
                    objectName: "gels-phrase"
                    Layout.fillWidth: true
                    text: ensemble.nombreGels === 0 ? "Aucun gel capturé."
                          : ensemble.page.pluriel(ensemble.nombreGels, "capture", "captures")
                            + (ensemble.page.jourCourt(ensemble.page.gels.dernier) !== ""
                               ? ", la dernière le " + ensemble.page.jourCourt(ensemble.page.gels.dernier) : "")
                }
            }
        }
    }

    component Separateur: Kirigami.Separator {
        Layout.fillWidth: true
        visible: ensemble.page.releve
        color: Style.ligne
    }

    // Une ligne de la vue d'ensemble : le nom du sujet, son contenu (une ou plusieurs lignes), son état écrit s'il en a
    // un ; un clic ouvre son onglet.
    component Ligne: Controls.AbstractButton {
        id: ligne

        property string cle
        property string nom
        property string mot: ""
        property string etat: ""
        property string badgeNom: cle + "-badge"
        default property alias contenu: colonneLigne.data

        objectName: "ligne-" + cle
        Layout.fillWidth: true
        hoverEnabled: true
        topPadding: Style.espace(2)
        bottomPadding: Style.espace(2)
        leftPadding: Style.espace(2)
        rightPadding: Style.espace(2)
        Accessible.role: Accessible.Button
        Accessible.name: nom + (mot !== "" ? ", " + mot : "") + ". Ouvre son onglet."

        contentItem: RowLayout {
            spacing: Style.espace(3)

            Controls.Label {
                Layout.alignment: Qt.AlignTop
                Layout.preferredWidth: Kirigami.Units.gridUnit * 7
                text: ligne.nom
                font.weight: Font.DemiBold
                elide: Text.ElideRight
            }
            ColumnLayout {
                id: colonneLigne

                Layout.fillWidth: true
                spacing: Style.espace(1)
            }
            Badge {
                objectName: ligne.badgeNom
                Layout.alignment: Qt.AlignTop
                visible: ligne.mot !== ""
                texte: ligne.mot
                etat: ligne.etat || "neutre"
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
