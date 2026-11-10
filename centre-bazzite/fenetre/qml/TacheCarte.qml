import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami
import "."

// Une tâche du panneau Activité : titre, statut en toutes lettres, détail, progression ; dépliable pour
// voir les étapes puis le journal. La carte ne décide de rien : tout vient de `tache` (voir taches.py).
Carte {
    id: carte

    property var tache: ({})
    // Dépliée d'office (un échec vient d'arriver) tant que l'utilisateur n'a pas choisi lui-même.
    property bool force: false
    property var choix: null

    readonly property string statut: tache.statut ?? "en_cours"
    readonly property var etapes: tache.etapes ?? []
    readonly property var journal: tache.journal ?? []
    readonly property bool depliable: etapes.length > 0 || journal.length > 0
    readonly property bool deplie: depliable && (choix !== null ? choix : force)
    readonly property var statuts: ({
        "en_cours": { "mot": "En cours", "badge": "en_cours" },
        "fini": { "mot": "Terminée", "badge": "ok" },
        "echec": { "mot": "Échec", "badge": "echec" },
        "interrompu": { "mot": "Interrompue", "badge": "attention" }
    })
    readonly property var etapeMots: ({
        "attente": "En attente", "en_cours": "En cours", "fini": "Terminée", "echec": "Échec", "saute": "Ignorée"
    })

    objectName: "tache-carte-" + (tache.id ?? "")
    teinte: statut === "echec" ? Style.echec : "transparent"

    RowLayout {
        Layout.fillWidth: true
        spacing: Style.espace(2)

        Controls.Label {
            Layout.fillWidth: true
            text: carte.tache.titre ?? ""
            font.weight: Font.DemiBold
            font.pointSize: Style.tailleCorps
            elide: Text.ElideRight
        }
        Badge {
            objectName: "tache-statut-" + (carte.tache.id ?? "")
            texte: carte.statuts[carte.statut]?.mot ?? carte.statut
            etat: carte.statuts[carte.statut]?.badge ?? "neutre"
        }
    }
    Controls.Label {
        visible: text !== ""
        Layout.fillWidth: true
        text: carte.tache.detail ?? ""
        wrapMode: Text.Wrap
        color: Style.texteAttenue
        font.pointSize: Style.tailleMeta
    }
    Progression {
        objectName: "tache-progression-" + (carte.tache.id ?? "")
        visible: carte.statut === "en_cours"
        Layout.fillWidth: true
        valeur: (carte.tache.progression ?? -1) < 0 ? -1 : carte.tache.progression / 100
    }
    // Seule une analyse de disque s'arrête d'ici (une mise à jour ou un ménage ne s'interrompent pas).
    Bouton {
        objectName: "tache-arreter-" + (carte.tache.id ?? "")
        visible: carte.statut === "en_cours" && String(carte.tache.id ?? "").startsWith("analyse:")
        flat: true
        icon.name: "media-playback-stop"
        text: "Arrêter l'analyse"
        onClicked: pont.arreterAnalyse()
    }
    Controls.ToolButton {
        objectName: "tache-bascule-" + (carte.tache.id ?? "")
        visible: carte.depliable
        icon.name: carte.deplie ? "arrow-up" : "arrow-down"
        text: carte.deplie ? "Masquer les détails" : "Afficher les détails"
        Accessible.name: text
        onClicked: carte.choix = !carte.deplie
    }

    ColumnLayout {
        objectName: "tache-details-" + (carte.tache.id ?? "")
        visible: carte.deplie
        Layout.fillWidth: true
        spacing: Style.espace(2)

        Repeater {
            model: carte.etapes
            delegate: RowLayout {
                required property var modelData

                Layout.fillWidth: true
                spacing: Style.espace(2)

                Controls.Label {
                    Layout.fillWidth: true
                    text: modelData.titre + (modelData.detail ? " : " + modelData.detail : "")
                    wrapMode: Text.Wrap
                    font.pointSize: Style.tailleMeta
                }
                Controls.Label {
                    text: carte.etapeMots[modelData.statut] ?? modelData.statut
                    color: modelData.statut === "echec" ? Style.echec
                         : modelData.statut === "fini" ? Style.ok
                         : Style.texteAttenue
                    font.pointSize: Style.tailleMeta
                }
            }
        }
        // Le journal dans un cadre sombre, en police à chasse fixe (comme les journaux de GitHub Hub).
        Rectangle {
            visible: carte.journal.length > 0
            Layout.fillWidth: true
            implicitHeight: texteJournal.implicitHeight + 2 * Style.espace(2.5)
            radius: Style.rayonEntree
            color: Style.fond
            border.width: 1
            border.color: Style.ligne

            Controls.Label {
                id: texteJournal

                anchors {
                    fill: parent
                    leftMargin: Style.espace(3)
                    rightMargin: Style.espace(3)
                    topMargin: Style.espace(2.5)
                    bottomMargin: Style.espace(2.5)
                }
                objectName: "tache-journal-" + (carte.tache.id ?? "")
                // Les 12 lignes les plus récentes ; « Copier le journal » copie tout.
                text: carte.journal.slice(-12).join("\n")
                wrapMode: Text.WrapAnywhere
                color: Style.texteAttenue
                font.family: Kirigami.Theme.fixedWidthFont.family
                font.pointSize: Style.tailleMono
                textFormat: Text.PlainText
            }
        }
        Bouton {
            objectName: "tache-copier-" + (carte.tache.id ?? "")
            visible: carte.journal.length > 0
            flat: true
            icon.name: "edit-copy"
            text: "Copier le journal"
            onClicked: pont.copier(carte.journal.join("\n"))
        }
    }
}
