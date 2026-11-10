import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami
import "."

// L'onglet Mode jeu : son état (la phrase et le mot du résumé de etat.json), ce qu'il a fait pendant la partie en cours,
// la dernière partie et ce qui a été remis, puis ses réglages. Un réglage passe par la CLI (`modejeu regler`) ; la
// fenêtre garde le choix affiché jusqu'à ce que etat.json, relu, fasse foi. « Remettre le bureau comme avant » passe
// par `modejeu restaurer`, qui ne fait rien si le service tourne (P5) ; le bouton attend sa fin, puis montre sa phrase.
ColumnLayout {
    id: onglet

    required property var page      // la page Jeux : ses données et ses formats

    readonly property var resume: page.modejeu ?? ({})
    readonly property string etat: page.etatModeJeu
    readonly property var mot: page.motsModeJeu[etat] ?? page.motsModeJeu["arrete"]
    readonly property var reglages: resume.reglages ?? ({ "actif": true, "ollama": true, "ne_pas_deranger": true,
                                                          "profil": true, "taches": true })
    readonly property var actions: resume.actions ?? null
    readonly property var derniere: resume.derniere ?? null
    property var demandes: ({})         // réglages cliqués, en attente de etat.json
    // UI-m8 : « remet tout de suite le bureau » n'est vrai que si le service tourne.
    readonly property string pied: {
        const base = "Les changements valent dès la prochaine partie.";
        switch (etat) {
        case "actif":
        case "pret": return base + " Couper le mode jeu remet tout de suite le bureau comme avant.";
        case "interrompu": return base + " Couper le mode jeu remettra le bureau comme avant à la reprise du service.";
        case "arrete": return base + " Le service du mode jeu ne tourne pas : rien ne change avant sa reprise.";
        default: return base;
        }
    }

    readonly property var nomsActions: [
        { "cle": "ollama", "nom": "Ollama" },
        { "cle": "ne_pas_deranger", "nom": "Ne pas déranger" },
        { "cle": "profil", "nom": "Profil d'énergie" },
        { "cle": "taches", "nom": "Relevés de Health Hub" }
    ]
    readonly property var statuts: ({
        "fait": { "mot": "Fait", "etat": "ok" },
        "rien": { "mot": "Rien à faire", "etat": "neutre" },
        "desactive": { "mot": "Désactivé", "etat": "neutre" },
        "echec": { "mot": "Échec", "etat": "echec" }
    })
    readonly property var lignesReglages: [
        { "cle": "actif", "libelle": "Mode jeu automatique", "detail": "" },
        { "cle": "ollama", "libelle": "Arrêter Ollama et rendre la mémoire vidéo",
          "detail": "Il est relancé à la fin seulement s'il tournait avant." },
        { "cle": "ne_pas_deranger", "libelle": "Activer Ne pas déranger", "detail": "" },
        { "cle": "profil", "libelle": "Passer en profil d'énergie « performance »", "detail": "" },
        { "cle": "taches", "libelle": "Mettre en pause les relevés de Health Hub",
          "detail": "L'analyse de disque s'arrête de toute façon pendant un jeu." }
    ]

    function valeur(cle) {
        return demandes[cle] ?? reglages[cle] ?? true;
    }
    function regler(cle, coche) {
        demandes = Object.assign({}, demandes, { [cle]: coche });
        pont.reglerModeJeu(cle, coche);
    }
    // etat.json relu : ses réglages font foi.
    onReglagesChanged: demandes = ({})

    objectName: "jeux-modejeu"
    spacing: Style.gouttiere

    Carte {
        objectName: "modejeu-carte"
        Layout.fillWidth: true

        RowLayout {
            Layout.fillWidth: true
            spacing: Style.espace(3)

            Kirigami.Heading {
                objectName: "modejeu-onglet-phrase"
                Layout.fillWidth: true
                level: 2
                font.pointSize: Style.tailleTitreCarte
                font.weight: Font.Bold
                text: onglet.page.phraseModeJeu
                wrapMode: Text.WordWrap
            }
            Badge {
                objectName: "modejeu-onglet-badge"
                Layout.alignment: Qt.AlignTop
                texte: onglet.mot.mot
                etat: onglet.mot.badge
            }
        }

        // Le service s'est arrêté pendant une partie : sa reprise remettra le bureau ; on peut le faire tout de suite. Ne
        // pas déranger et le profil sont tombés avec lui (le bus lève ses maintiens) : seul Ollama peut rester arrêté.
        Kirigami.InlineMessage {
            objectName: "modejeu-interrompu"
            Layout.fillWidth: true
            visible: onglet.etat === "interrompu"
            type: Kirigami.MessageType.Warning
            text: "Le service du mode jeu s'est arrêté pendant " + (onglet.resume.jeu ? "« " + onglet.resume.jeu + " »"
                  : "une partie") + " : Ollama n'a peut-être pas été relancé."
        }
        // Grisé pendant la remise (elle attend quelques secondes : pas de double clic), puis sa phrase en dessous.
        Bouton {
            objectName: "restaurer-modejeu"
            visible: onglet.etat === "interrompu"
            enabled: !pont.restaurationEnCours
            text: pont.restaurationEnCours ? "Remise du bureau en cours…" : "Remettre le bureau comme avant"
            icon.name: "edit-undo"
            onClicked: pont.restaurerModeJeu()
        }
        Controls.Label {
            objectName: "restaurer-retour"
            Layout.fillWidth: true
            visible: text !== ""
            text: pont.retourRestauration
            wrapMode: Text.WordWrap
        }

        // La partie en cours : une ligne par action, son statut écrit et son détail.
        GridLayout {
            objectName: "modejeu-actions"
            Layout.fillWidth: true
            visible: Object.keys(onglet.actions ?? {}).length > 0
            columns: 3
            columnSpacing: Style.espace(3)
            rowSpacing: Style.espace(1)

            Repeater {
                model: onglet.nomsActions

                delegate: Controls.Label {
                    required property var modelData
                    required property int index

                    objectName: "action-nom-" + modelData.cle
                    Layout.row: index
                    Layout.column: 0
                    text: modelData.nom
                    font.weight: Font.DemiBold
                }
            }
            Repeater {
                model: onglet.nomsActions

                delegate: Badge {
                    required property var modelData
                    required property int index
                    readonly property var action: (onglet.actions ?? {})[modelData.cle] ?? null

                    objectName: "action-statut-" + modelData.cle
                    Layout.row: index
                    Layout.column: 1
                    visible: action !== null
                    texte: onglet.statuts[action?.statut]?.mot ?? ""
                    etat: onglet.statuts[action?.statut]?.etat ?? "neutre"
                }
            }
            Repeater {
                model: onglet.nomsActions

                delegate: TexteAbrege {
                    required property var modelData
                    required property int index

                    objectName: "action-detail-" + modelData.cle
                    Layout.row: index
                    Layout.column: 2
                    Layout.fillWidth: true
                    text: (onglet.actions ?? {})[modelData.cle]?.detail ?? ""
                    color: Style.texteAttenue
                }
            }
        }
        Kirigami.InlineMessage {
            objectName: "modejeu-avertissement"
            Layout.fillWidth: true
            visible: (onglet.resume.avertissement ?? "") !== ""
            type: Kirigami.MessageType.Warning
            text: onglet.resume.avertissement ?? ""
        }

        // La dernière partie (P13 : la phrase du moteur, telle quelle) et ce qui a été remis.
        ColumnLayout {
            Layout.fillWidth: true
            visible: onglet.derniere !== null
            spacing: 0

            TexteAbrege {
                objectName: "modejeu-onglet-derniere"
                Layout.fillWidth: true
                text: onglet.derniere?.phrase ?? ""
            }
            TexteAbrege {
                objectName: "modejeu-retours"
                Layout.fillWidth: true
                visible: text !== ""
                text: ["profil", "ne_pas_deranger", "ollama"]
                      .map(cle => onglet.derniere?.retour?.[cle]?.detail ?? "").filter(t => t !== "").join(" ")
                color: Style.texteAttenue
                font.pointSize: Style.tailleMeta
            }
        }
    }

    Carte {
        objectName: "reglages-carte"
        Layout.fillWidth: true
        titre: "Réglages"

        ColumnLayout {
            Layout.fillWidth: true
            spacing: Style.espace(1)

            Repeater {
                model: onglet.lignesReglages

                delegate: ColumnLayout {
                    id: reglage

                    required property var modelData

                    Layout.fillWidth: true
                    Layout.leftMargin: modelData.cle === "actif" ? 0 : Style.espace(4)
                    spacing: 0

                    Controls.Switch {
                        id: interrupteur

                        objectName: "reglage-" + reglage.modelData.cle
                        text: reglage.modelData.libelle
                        checked: onglet.valeur(reglage.modelData.cle)
                        // Les quatre actions attendent l'interrupteur général.
                        enabled: reglage.modelData.cle === "actif" || onglet.valeur("actif")
                        font.weight: reglage.modelData.cle === "actif" ? Font.DemiBold : Font.Normal
                        onToggled: {
                            onglet.regler(reglage.modelData.cle, checked);
                            checked = Qt.binding(() => onglet.valeur(reglage.modelData.cle));
                        }
                    }
                    Controls.Label {
                        objectName: "reglage-detail-" + reglage.modelData.cle
                        Layout.fillWidth: true
                        Layout.leftMargin: interrupteur.indicator ? interrupteur.indicator.width + interrupteur.spacing : 0
                        visible: text !== ""
                        text: reglage.modelData.detail
                        color: Style.texteAttenue
                        font.pointSize: Style.tailleMeta
                        wrapMode: Text.WordWrap
                        opacity: interrupteur.enabled ? 1 : 0.6
                    }
                }
            }
            Kirigami.Separator {
                Layout.fillWidth: true
                Layout.topMargin: Style.espace(1)
                color: Style.ligne
            }
            Controls.Label {
                objectName: "modejeu-pied"
                Layout.fillWidth: true
                text: onglet.pied
                color: Style.texteAttenue
                font.pointSize: Style.tailleMeta
                wrapMode: Text.WordWrap
            }
            Controls.Label {
                objectName: "modejeu-detecte"
                Layout.fillWidth: true
                text: "Détecté : les jeux lancés par Steam, Heroic, Lutris ou umu."
                color: Style.texteAttenue
                font.pointSize: Style.tailleMeta
                wrapMode: Text.WordWrap
            }
        }
    }
}
