import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami
import "."

// L'onglet d'un volume (Task 19) : en tête, son nom, son disque, son système de fichiers, sa place sur le disque, la barre
// de son espace libre (jamais l'espace utilisé) et son état écrit ; puis ce que LinStat y a trouvé. Sans moteur, l'espace
// libre seul, la raison, et « Carte détaillée » si la commande de LinStat est connue (spec §6.2).
Carte {
    id: carte

    property var volume: ({})
    property var disque: ({})
    property string sansLinstat: ""     // pourquoi il n'y a pas d'analyse ("" : LinStat répond)

    readonly property string chemin: volume.chemin ?? ""
    readonly property string etat: volume.etat ?? "ok"
    readonly property real libreGo: volume.libre_go ?? 0
    readonly property real totalGo: volume.total_go ?? 0
    readonly property var linstat: pont.stockage.linstat ?? ({})
    readonly property bool moteur: linstat.moteur ?? false
    readonly property bool commandeConnue: (linstat.commande ?? null) !== null
    readonly property var places: ({ "debut": "début du disque", "milieu": "milieu du disque", "fin": "fin du disque" })
    readonly property color teinteEtat: etat === "echec" ? Style.echec : etat === "attention" ? Style.attention : Style.accent

    // Comme la jauge : une décimale sous 100 Go pour l'espace libre ; le total en Go entiers dès 10 Go.
    function go(x, decimalesSous) {
        return Number(x).toLocaleString(Qt.locale("fr_FR"), "f", x >= decimalesSous ? 0 : 1) + " Go";
    }

    objectName: "stockage-volume-" + chemin

    RowLayout {
        Layout.fillWidth: true
        spacing: Style.espace(3)

        Controls.Label {
            objectName: "volume-nom-" + carte.chemin
            text: carte.volume.nom ?? carte.chemin
            font.weight: Font.Bold
            font.pointSize: Style.tailleTitreCarte
        }
        Badge {
            objectName: "volume-disque-" + carte.chemin
            visible: texte !== ""
            texte: carte.disque.titre ?? ""
            point: false
        }
        Controls.Label {
            objectName: "stockage-detail-" + carte.chemin
            Layout.fillWidth: true
            text: [carte.volume.fs, carte.places[carte.volume.position]].filter(x => x).join(" · ")
            color: Style.texteAttenue
            font.pointSize: Style.tailleMeta
            elide: Text.ElideRight
        }
        Badge {
            objectName: "volume-etat-" + carte.chemin
            texte: carte.etat === "ok" ? "OK" : "Peu d'espace libre"
            etat: carte.etat
        }
    }
    RowLayout {
        Layout.fillWidth: true
        spacing: Style.espace(3)

        Progression {
            objectName: "volume-barre-" + carte.chemin
            Layout.fillWidth: true
            Layout.alignment: Qt.AlignVCenter
            valeur: carte.totalGo > 0 ? Math.max(0, Math.min(carte.libreGo / carte.totalGo, 1)) : 0
            teinte: carte.teinteEtat
            Accessible.name: carte.chemin + " : " + libre.text
        }
        Controls.Label {
            id: libre

            objectName: "volume-libre-" + carte.chemin
            text: carte.go(carte.libreGo, 100) + " libres sur " + carte.go(carte.totalGo, 10)
            color: carte.etat !== "ok" ? carte.teinteEtat : Style.texteAttenue
            font.features: ({ "tnum": 1 })
        }
    }
    Controls.Label {
        objectName: "volume-sans-linstat-" + carte.chemin
        Layout.fillWidth: true
        visible: carte.sansLinstat !== ""
        text: carte.sansLinstat
        color: Style.texteAttenue
        font.pointSize: Style.tailleMeta
        wrapMode: Text.WordWrap
    }

    Kirigami.Separator {
        Layout.fillWidth: true
        visible: resultats.visible
        color: Style.ligne
    }
    StockageAnalyse {
        id: resultats

        visible: carte.moteur || carte.commandeConnue
        moteur: carte.moteur
        volume: carte.volume
        analyse_: (pont.stockage.analyses ?? ({}))[carte.chemin] ?? null
        tache: pont.taches.find(t => t.id === "analyse:" + carte.chemin) ?? null
        carteDisponible: carte.commandeConnue
    }
}
