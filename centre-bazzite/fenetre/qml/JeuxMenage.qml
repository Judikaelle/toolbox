import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami
import "."

// L'onglet Ménage des jeux : les caches de shaders sans jeu installé et les versions de Proton inutilisées, avec la même
// section que Stockage (liste complète dans le dialogue, empreinte, revérification par le moteur) ; puis les préfixes
// Proton orphelins, seulement listés : Health Hub ne les supprime jamais (un préfixe peut servir à un raccourci
// non-Steam ou contenir des sauvegardes), il propose seulement d'en copier le chemin.
ColumnLayout {
    id: onglet

    required property var page      // la page Jeux : ses données et ses formats

    readonly property var prefixes: page.prefixes.elements ?? []
    // W5 : la liste des jeux installés n'a pas pu être lue (cette phrase exacte de jeux.py, copie testée) ; le moteur ne
    // propose alors aucun cache de shaders. Une recommandation « shaders » présente (stockage.json relevé à un autre
    // moment) contredirait l'avertissement : il se tait (UI-m4).
    readonly property string phraseSteamIncertain: "Steam : illisible (bibliothèques non vérifiables)"
    readonly property bool steamIllisible: page.erreurs.includes(phraseSteamIncertain)
                                           && !page.recosJeux.some(r => r.id === "shaders")
    property int copie: -1              // la ligne dont le chemin vient d'être copié

    objectName: "jeux-menage"
    spacing: Style.gouttiere

    Kirigami.InlineMessage {
        objectName: "menage-steam-illisible"
        Layout.fillWidth: true
        visible: onglet.steamIllisible
        type: Kirigami.MessageType.Warning
        text: onglet.phraseSteamIncertain + ". Aucun cache de shaders n'est proposé tant que la liste des jeux "
              + "installés n'est pas lisible."
    }
    MenageSection {
        Layout.fillWidth: true
        ids: onglet.page.idsMenage
    }
    EtatVide {
        objectName: "menage-jeux-vide"
        Layout.fillWidth: true
        // Pas de « Rien à libérer » (et sa coche) à côté de l'avertissement W5 : on ne le sait pas.
        visible: onglet.page.recosJeux.length === 0 && onglet.prefixes.length === 0 && !onglet.steamIllisible
        icone: onglet.page.releve ? "checkmark" : "applications-games"
        texte: onglet.page.releve ? "Rien à libérer côté jeux." : onglet.page.texteVide
    }

    Carte {
        id: carte

        objectName: "prefixes-carte"
        Layout.fillWidth: true
        visible: onglet.prefixes.length > 0

        RowLayout {
            Layout.fillWidth: true
            spacing: Style.espace(3)

            Kirigami.Heading {
                Layout.fillWidth: true
                level: 2
                font.pointSize: Style.tailleTitreCarte
                font.weight: Font.Bold
                text: "Préfixes Proton orphelins"
                elide: Text.ElideRight
            }
            Controls.Label {
                objectName: "prefixes-total"
                text: onglet.page.pluriel(onglet.prefixes.length, "préfixe", "préfixes") + " · "
                      + (onglet.page.prefixes.taille ?? "")
                font.weight: Font.DemiBold
                font.features: ({ "tnum": 1 })
            }
        }
        Controls.Label {
            objectName: "prefixes-texte"
            Layout.fillWidth: true
            text: "Seulement listés : un préfixe peut servir à un raccourci non-Steam ou contenir des sauvegardes. "
                  + "Health Hub ne les supprime jamais."
            color: Style.texteAttenue
            wrapMode: Text.WordWrap
        }

        ListView {
            id: liste

            objectName: "liste-prefixes"
            Layout.fillWidth: true
            // Bornée au reste de l'écran (la page tient sur un écran) : la carte au-dessus, sa marge, puis sa marge du bas.
            Layout.preferredHeight: Math.min(contentHeight, Math.max(Kirigami.Units.gridUnit * 5,
                onglet.page.hauteurOnglet - carte.y - liste.y - 2 * Style.margeCarte))
            clip: true
            interactive: contentHeight > height
            boundsBehavior: Flickable.StopAtBounds
            model: onglet.prefixes
            Controls.ScrollBar.vertical: Controls.ScrollBar {
                policy: Controls.ScrollBar.AsNeeded
            }

            delegate: ColumnLayout {
                id: rang

                required property var modelData
                required property int index

                width: ListView.view.width - Style.espace(3)
                spacing: 0

                Kirigami.Separator {
                    Layout.fillWidth: true
                    visible: rang.index > 0
                    color: Style.ligne
                }
                RowLayout {
                    Layout.fillWidth: true
                    Layout.topMargin: Style.espace(1)
                    Layout.bottomMargin: Style.espace(1)
                    spacing: Style.espace(3)

                    TexteAbrege {
                        objectName: "prefixe-libelle-" + rang.index
                        Layout.fillWidth: true
                        text: rang.modelData.libelle ?? ""
                    }
                    Badge {
                        objectName: "prefixe-bibliotheque-" + rang.index
                        texte: rang.modelData.bibliotheque ?? ""
                        etat: "neutre"
                        point: false
                    }
                    Controls.Label {
                        objectName: "prefixe-taille-" + rang.index
                        Layout.preferredWidth: Kirigami.Units.gridUnit * 4
                        horizontalAlignment: Text.AlignRight
                        text: rang.modelData.taille ?? ""
                        font.features: ({ "tnum": 1 })
                    }
                    Controls.Label {
                        objectName: "prefixe-copie-" + rang.index
                        visible: onglet.copie === rang.index
                        text: "Chemin copié."
                        color: Style.ok
                        font.pointSize: Style.tailleMeta
                    }
                    Bouton {
                        objectName: "prefixe-copier-" + rang.index
                        flat: true
                        text: "Copier le chemin"
                        icon.name: "edit-copy"
                        onClicked: {
                            pont.copier(rang.modelData.cible ?? "");
                            onglet.copie = rang.index;
                        }
                    }
                }
            }
        }
    }
}
