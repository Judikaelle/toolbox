import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami
import "."

// Onglet Disques de la santé (Task 19) : chaque SSD (usure, réserve, température, heures, écritures, erreurs) et
// « Stockage sain » (erreurs d'entrée-sortie du noyau, volumes attendus montés), contrôles repris de bazzite-health.
ColumnLayout {
    id: onglet

    required property var page      // la page Santé : ses données et ses formats

    objectName: "sante-onglet-disques"
    spacing: Style.gouttiere

    EtatVide {
        Layout.fillWidth: true
        visible: (onglet.page.sante.ssd ?? []).length === 0
        icone: "drive-harddisk"
        texte: "Disques pas encore mesurés."
        explication: "La mesure se fait une fois par heure."
    }
    Repeater {
        model: onglet.page.sante.ssd ?? []

        delegate: Carte {
            id: disque

            required property var modelData
            readonly property var s: modelData.sante ?? null

            Layout.fillWidth: true
            teinte: onglet.page.teinteDisque(modelData.modele)

            RowLayout {
                Layout.fillWidth: true
                spacing: Style.espace(3)

                Controls.Label {
                    text: disque.modelData.modele
                    font.weight: Font.Bold
                    font.pointSize: Style.tailleTitreCarte
                }
                Badge {
                    texte: disque.modelData.bus === "usb" ? "USB" : disque.modelData.bus === "nvme" ? "NVMe" : String(disque.modelData.bus ?? "").toUpperCase()
                    visible: texte !== ""
                    etat: "neutre"
                    point: false
                }
                Badge {
                    visible: !disque.s
                    texte: "Santé non disponible par l'USB"
                    etat: "neutre"
                    point: false
                }
                Item {
                    Layout.fillWidth: true
                }
            }
            Flow {
                Layout.fillWidth: true
                visible: !!disque.s
                spacing: Style.margePage

                Mesure {
                    valeur: onglet.page.pourcent(disque.s?.usure)
                    legende: "Usure"
                }
                Mesure {
                    valeur: onglet.page.pourcent(disque.s?.reserve)
                    legende: "Réserve restante"
                }
                Mesure {
                    valeur: onglet.page.degres(disque.s?.temperature)
                    legende: "Température"
                }
                Mesure {
                    valeur: disque.s?.heures !== undefined ? onglet.page.nombre(disque.s.heures, 0) + " h" : "—"
                    legende: "Allumé"
                }
                Mesure {
                    valeur: disque.s?.ecrit_to !== undefined ? onglet.page.nombre(disque.s.ecrit_to, 1) + " To" : "—"
                    legende: "Écrits"
                }
                Mesure {
                    valeur: disque.s?.erreurs_media !== undefined ? String(disque.s.erreurs_media) : "—"
                    legende: "Erreurs"
                }
                Mesure {
                    valeur: disque.s?.arrets_brutaux !== undefined ? String(disque.s.arrets_brutaux) : "—"
                    legende: "Arrêts brutaux"
                }
            }
            Controls.Label {
                Layout.fillWidth: true
                visible: (disque.s?.avertissements ?? []).length > 0
                text: "Avertissements : " + (disque.s?.avertissements ?? []).join(", ")
                color: Style.attention
                wrapMode: Text.WordWrap
            }
        }
    }
    // Contrôles de bazzite-health : erreurs d'E/S du noyau et volumes attendus montés.
    Carte {
        id: stockage

        readonly property var erreurs: onglet.page.sante.erreurs_disque ?? null
        readonly property var nonMontes: onglet.page.sante.non_montes ?? null
        readonly property var attendus: onglet.page.sante.attendus ?? null
        // Aucun volume attendu dans la configuration : pas de ligne (rien à vérifier).
        readonly property bool avecAttendus: attendus === null || attendus.length > 0 || (nonMontes ?? []).length > 0
        readonly property var lignes: [onglet.page.ligneErreurs(erreurs)].concat(
            avecAttendus ? [onglet.page.ligneAttendus(nonMontes, attendus)] : [])

        objectName: "carte-stockage"
        Layout.fillWidth: true
        visible: erreurs !== null || nonMontes !== null
        titre: lignes.every(l => l.etat === "ok") ? "Stockage sain" : "Stockage"
        teinte: onglet.page.teinteDe(lignes)

        LigneControle {
            nom: "stockage-erreurs"
            libelle: "Erreurs d'entrée-sortie"
            ligne: stockage.lignes[0]
        }
        LigneControle {
            nom: "stockage-attendus"
            visible: stockage.avecAttendus
            libelle: onglet.page.libelleAttendus(stockage.attendus)
            ligne: stockage.lignes[1] ?? ({})
        }
    }
}
