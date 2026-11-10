import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami
import "."

// Ménage : une ligne par recommandation du moteur (stockage.recommandations), avec ce qui part et combien ça libère
// (vue d'ensemble de Stockage, Task 19). Rien ne part sans confirmation : le dialogue liste TOUS les éléments (liste
// défilante) et leur total, puis un bouton destructeur ; la commande porte l'empreinte de la liste montrée, et le
// moteur revérifie chaque élément au moment d'agir. Le journal se réduit à la main (commande à copier).
Carte {
    id: section

    readonly property var recommandations: pont.stockage.recommandations ?? []
    property var ouverte: null          // la recommandation du dialogue, telle qu'elle était à l'ouverture
    property string copiee: ""          // id de la recommandation dont la commande vient d'être copiée
    property string changement: ""      // la liste a changé pendant la confirmation : on le dit

    function reco(id) {
        return recommandations.find(r => r.id === id) ?? null;
    }
    // Ce que montre la liste : cible, libellé et taille de chaque élément (comme l'empreinte du moteur).
    function signature(r) {
        return JSON.stringify((r?.elements ?? []).map(e => [e.cible, e.libelle, e.octets]));
    }
    function libelleConfirmer(r) {
        switch (r?.mode) {
        case "supprimer": return "Supprimer définitivement";
        case "corbeille": return r.id === "corbeille" ? "Vider la corbeille définitivement" : "Envoyer à la corbeille";
        case "commande": return "Désinstaller";
        default: return "";
        }
    }
    function enCours(id) {
        return pont.taches.some(t => t.id === "menage:" + id && t.statut === "en_cours");
    }
    // Ce que montre le dialogue est toujours ce que stockage.json propose encore, élément pour élément.
    function inchangee() {
        return ouverte !== null && signature(reco(ouverte.id)) === signature(ouverte);
    }
    function ouvrir(id) {
        const r = reco(id);
        if (!r || r.mode === "copier")
            return;
        changement = "";
        ouverte = r;
        dialogue.open();
    }
    function confirmer() {
        dialogue.close();
        if (inchangee())
            pont.menage(ouverte.id, ouverte.elements);
        else
            changement = "La liste a changé pendant que tu la regardais : rien n'est parti. Vérifie-la avant de confirmer.";
    }

    // stockage.json est réécrit (relevé horaire, autre ménage) : si la liste ouverte a changé, on ferme sans rien lancer.
    onRecommandationsChanged: {
        if (dialogue.visible && !inchangee()) {
            dialogue.close();
            changement = "La liste a changé pendant que tu la regardais : rien n'est parti. Vérifie-la avant de confirmer.";
        }
    }

    objectName: "menage-section"
    visible: recommandations.length > 0

    RowLayout {
        Layout.fillWidth: true
        spacing: Style.espace(3)

        Kirigami.Heading {
            objectName: "menage-entete"
            level: 2
            font.pointSize: Style.tailleTitreCarte
            font.weight: Font.Bold
            text: "Ménage"
        }
        TexteAbrege {
            Layout.fillWidth: true
            horizontalAlignment: Text.AlignRight
            text: "Rien ne part sans ta confirmation."
            color: Style.texteAttenue
            font.pointSize: Style.tailleMeta
        }
    }
    Kirigami.InlineMessage {
        id: avertissement

        objectName: "menage-avertissement"
        Layout.fillWidth: true
        visible: section.changement !== ""
        type: Kirigami.MessageType.Warning
        text: section.changement
    }

    ColumnLayout {
        Layout.fillWidth: true
        spacing: Style.espace(2)

        Repeater {
            model: section.recommandations

            delegate: ColumnLayout {
                id: ligne

                required property var modelData
                required property int index
                readonly property string rid: modelData.id ?? ""
                readonly property bool aCopier: (modelData.a_copier ?? "") !== ""
                readonly property bool copier: modelData.mode === "copier"
                readonly property bool occupe: section.enCours(rid)

                objectName: "menage-ligne-" + rid
                Layout.fillWidth: true
                spacing: Style.espace(2)

                Kirigami.Separator {
                    Layout.fillWidth: true
                    visible: ligne.index > 0
                    color: Style.ligne
                }
                RowLayout {
                    Layout.fillWidth: true
                    spacing: Style.espace(3)

                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 0

                        RowLayout {
                            Layout.fillWidth: true
                            spacing: Style.espace(2)

                            TexteAbrege {
                                objectName: "menage-titre-" + ligne.rid
                                Layout.fillWidth: true
                                text: ligne.modelData.titre ?? ""
                                font.weight: Font.DemiBold
                            }
                            Badge {
                                objectName: "menage-en-cours-" + ligne.rid
                                visible: ligne.occupe
                                texte: "En cours"
                                etat: "en_cours"
                            }
                            // La taille : dans « Libérer … » quand il y est, sinon ici (le journal).
                            Controls.Label {
                                objectName: "menage-taille-" + ligne.rid
                                visible: ligne.copier
                                text: ligne.modelData.taille ?? ""
                                font.weight: Font.DemiBold
                                font.features: ({ "tnum": 1 })
                            }
                        }
                        // Ce qui arrive à ce qui part (définitivement, à la corbeille…) ; le dialogue le redit en entier.
                        TexteAbrege {
                            objectName: "menage-explication-" + ligne.rid
                            Layout.fillWidth: true
                            text: ligne.modelData.explication ?? ""
                            color: Style.texteAttenue
                            font.pointSize: Style.tailleMeta
                        }
                        // Ce qui est volontairement laissé hors de la liste (sauvegardes de jeux probables, V54).
                        Controls.Label {
                            objectName: "menage-remarque-" + ligne.rid
                            Layout.fillWidth: true
                            visible: text !== ""
                            text: ligne.modelData.remarque ?? ""
                            color: Style.attention
                            font.pointSize: Style.tailleMeta
                            wrapMode: Text.WordWrap
                        }
                    }
                    Bouton {
                        objectName: "menage-liberer-" + ligne.rid
                        Layout.alignment: Qt.AlignVCenter
                        visible: !ligne.copier
                        enabled: !ligne.occupe
                        text: "Libérer " + (ligne.modelData.taille ?? "") + "…"
                        icon.name: "edit-clear-all"
                        onClicked: section.ouvrir(ligne.rid)
                    }
                }
                // La commande à lancer soi-même : le journal (sa seule action), ou les anciens pilotes GL NVIDIA épinglés,
                // que Health Hub ne retire pas (à côté de « Libérer… » des runtimes, le bouton n'a que son icône).
                RowLayout {
                    Layout.fillWidth: true
                    visible: ligne.aCopier
                    spacing: Style.espace(2)

                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 0

                        Controls.Label {
                            Layout.fillWidth: true
                            visible: !ligne.copier
                            text: "Anciens pilotes GL NVIDIA, épinglés : à retirer toi-même dans un terminal."
                            color: Style.texteAttenue
                            font.pointSize: Style.tailleMeta
                            wrapMode: Text.WordWrap
                        }
                        Controls.Label {
                            objectName: "menage-a-copier-" + ligne.rid
                            Layout.fillWidth: true
                            text: ligne.modelData.a_copier ?? ""
                            textFormat: Text.PlainText
                            font.family: "monospace"
                            font.pointSize: Style.tailleMono
                            wrapMode: Text.WrapAnywhere
                            maximumLineCount: 2
                            elide: Text.ElideRight
                        }
                        Controls.Label {
                            objectName: "menage-copie-" + ligne.rid
                            visible: section.copiee === ligne.rid
                            text: "Commande copiée."
                            color: Style.ok
                            font.pointSize: Style.tailleMeta
                        }
                    }
                    Bouton {
                        objectName: "menage-copier-" + ligne.rid
                        Layout.alignment: Qt.AlignVCenter
                        text: "Copier la commande"
                        icon.name: "edit-copy"
                        display: ligne.copier ? Controls.AbstractButton.TextBesideIcon : Controls.AbstractButton.IconOnly
                        onClicked: {
                            pont.copier(ligne.modelData.a_copier);
                            section.copiee = ligne.rid;
                        }
                    }
                }
            }
        }
    }

    // La confirmation : ce qui part, combien ça libère, puis un clic sur le bouton destructeur.
    Dialogue {
        id: dialogue

        objectName: "menage-dialogue"
        title: section.ouverte?.titre ?? ""
        subtitle: section.ouverte?.explication ?? ""
        standardButtons: Kirigami.Dialog.NoButton
        preferredWidth: Kirigami.Units.gridUnit * 28

        ColumnLayout {
            Layout.fillWidth: true
            Layout.topMargin: Style.espace(2)
            spacing: Style.espace(1)

            // Tout ce qui part, sans exception : une liste défilante de hauteur bornée.
            ListView {
                id: liste

                Layout.fillWidth: true
                Layout.preferredHeight: Math.min(contentHeight, Kirigami.Units.gridUnit * 15)
                clip: true
                boundsBehavior: Flickable.StopAtBounds
                model: section.ouverte?.elements ?? []
                Controls.ScrollBar.vertical: Controls.ScrollBar {
                    policy: Controls.ScrollBar.AsNeeded
                }

                delegate: RowLayout {
                    id: ligne

                    required property var modelData
                    property alias libelle: etiquette

                    width: ListView.view.width - Style.espace(4)
                    spacing: Style.espace(3)

                    Controls.Label {
                        id: etiquette

                        Layout.fillWidth: true
                        Layout.topMargin: Style.espace(0.5)
                        Layout.bottomMargin: Style.espace(0.5)
                        text: ligne.modelData.libelle ?? ""
                        textFormat: Text.PlainText
                        elide: Text.ElideMiddle
                    }
                    Controls.Label {
                        text: ligne.modelData.taille ?? ""
                        color: Style.texteAttenue
                    }
                }
            }
            Kirigami.Separator {
                Layout.fillWidth: true
                Layout.topMargin: Style.espace(1)
                color: Style.ligne
            }
            Controls.Label {
                id: total

                readonly property int nombre: (section.ouverte?.elements ?? []).length

                text: nombre + (nombre > 1 ? " éléments" : " élément") + " · Total : " + (section.ouverte?.taille ?? "")
                font.weight: Font.DemiBold
            }
            RowLayout {
                Layout.fillWidth: true
                Layout.topMargin: Style.espace(2)
                spacing: Style.espace(2)

                Item {
                    Layout.fillWidth: true
                }
                Bouton {
                    id: annuler

                    text: "Annuler"
                    icon.name: "dialog-cancel"
                    onClicked: dialogue.close()
                }
                BoutonDanger {
                    id: confirmer

                    text: section.libelleConfirmer(section.ouverte)
                    icon.name: section.ouverte?.mode === "corbeille" ? "user-trash" : "edit-delete"
                    onClicked: section.confirmer()
                }
            }
        }
    }
}
