import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami
import "."

// Onglet GPU et jeux de la santé (Task 19) : la carte graphique (température, consommation, VRAM), Ollama (avec
// « Arrêter Ollama ») et les gels de jeu enregistrés.
ColumnLayout {
    id: onglet

    required property var page      // la page Santé : ses données et ses formats

    objectName: "sante-onglet-gpu"
    spacing: Style.gouttiere

    Carte {
        objectName: "gpu-carte"
        Layout.fillWidth: true

        Flow {
            readonly property var gpu: onglet.page.sante.gpu ?? null

            Layout.fillWidth: true
            spacing: Style.margePage

            Mesure {
                valeur: parent.gpu?.nom ?? "—"
                legende: "Carte graphique"
            }
            Mesure {
                valeur: onglet.page.degres(parent.gpu?.temperature)
                legende: "Température"
            }
            Mesure {
                valeur: parent.gpu?.watts !== undefined ? onglet.page.nombre(parent.gpu.watts, 0) + " W" : "—"
                legende: "Consommation"
            }
            Mesure {
                valeur: parent.gpu?.vram_utilisee_go !== undefined
                        ? onglet.page.nombre(parent.gpu.vram_utilisee_go, 1) + " / " + onglet.page.nombre(parent.gpu.vram_totale_go, 1) + " Go" : "—"
                legende: "VRAM"
            }
        }
        Kirigami.Separator {
            Layout.fillWidth: true
            color: Style.ligne
        }
        RowLayout {
            id: ollama

            readonly property bool actif: !!onglet.page.sante.ollama?.actif

            Layout.fillWidth: true
            spacing: Style.espace(3)

            Badge {
                texte: ollama.actif ? "Actif" : "Arrêté"
                etat: ollama.actif ? "en_cours" : "neutre"
            }
            Controls.Label {
                Layout.fillWidth: true
                text: ollama.actif ? "Ollama tourne" + (onglet.page.sante.ollama.modeles_charges?.length > 0 ? " (modèle chargé : " + onglet.page.sante.ollama.modeles_charges.join(", ") + ")." : ".")
                            : "Ollama est arrêté."
                wrapMode: Text.WordWrap
            }
            BoutonDanger {
                enabled: ollama.actif
                text: "Arrêter Ollama"
                icon.name: "media-playback-stop"
                onClicked: pont.arreterOllama()
            }
        }
        RowLayout {
            readonly property var gels: onglet.page.sante.gels ?? null
            readonly property int nombreGels: gels ? gels.nombre : 0

            Layout.fillWidth: true
            spacing: Style.espace(3)

            Badge {
                texte: parent.nombreGels === 0 ? "Aucun gel" : parent.nombreGels + (parent.nombreGels > 1 ? " gels" : " gel")
                etat: parent.nombreGels === 0 ? "ok" : "attention"
            }
            Controls.Label {
                Layout.fillWidth: true
                text: parent.nombreGels === 0 ? "Aucun gel de jeu enregistré."
                      : parent.nombreGels + (parent.nombreGels > 1 ? " gels de jeu enregistrés" : " gel de jeu enregistré")
                        + (onglet.page.dateDuGel(parent.gels.dernier) !== "" ? ", le dernier le " + onglet.page.dateDuGel(parent.gels.dernier) + "." : ".")
                wrapMode: Text.WordWrap
            }
        }
    }
}
