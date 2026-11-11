import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami
import "."

// Onglet GPU et jeux de la santé (Task 19) : la carte graphique (température, consommation, VRAM), Ollama (avec
// « Arrêter Ollama »), les erreurs du pilote vues par le noyau et le compte des gels de jeu capturés, dont le détail vit dans la page Jeux (v2b, D16).
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
        // Les erreurs du pilote vues par le noyau (Xid) : l'état vient du point noyau:gpu.
        LigneControle {
            nom: "gpu-noyau"
            libelle: "Erreurs du pilote (noyau)"
            ligne: onglet.page.ligneNoyauGpu(onglet.page.noyau)
        }
        // Les gels : leur compte et le même badge qu'avant ; la liste, ouvrable, est dans Jeux (onglet Gels).
        RowLayout {
            id: gels

            readonly property int nombre: onglet.page.sante.gels?.nombre ?? 0

            Layout.fillWidth: true
            spacing: Style.espace(3)

            Badge {
                objectName: "gels-sante-badge"
                texte: gels.nombre === 0 ? "Aucun gel" : gels.nombre + (gels.nombre > 1 ? " gels" : " gel")
                etat: gels.nombre === 0 ? "ok" : "attention"
            }
            Controls.Label {
                objectName: "gels-sante"
                Layout.fillWidth: true
                text: gels.nombre === 0 ? "Aucune capture de gel"
                      : gels.nombre + (gels.nombre > 1 ? " captures de gel" : " capture de gel")
                wrapMode: Text.WordWrap
            }
            Bouton {
                objectName: "voir-gels"
                text: "Voir dans Jeux"
                icon.name: "go-next-symbolic"
                onClicked: {
                    applicationWindow().ongletJeux = "gels";
                    applicationWindow().page = "jeux";
                }
            }
        }
    }
}
