import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami
import "."

// Stockage, en onglets (Task 19) : « Vue d'ensemble » (ce qui est à regarder, les disques en lignes, le ménage,
// l'optimisation, les sourdines), puis un onglet par volume, dans l'ordre des disques puis de leur place sur le disque :
// son espace libre et son analyse. Seul l'onglet ouvert existe ; la fenêtre le garde (ongletStockage) : revenir sur la
// page le rouvre. Tout vient de stockage.json, écrit par le moteur.
Controls.ScrollView {
    id: page

    objectName: "page-stockage"
    readonly property var disques: pont.stockage.disques ?? []
    // Chaque volume affiché, avec son disque.
    readonly property var volumes: disques.reduce((liste, d) => liste.concat((d.volumes ?? []).map(v => ({ "volume": v, "disque": d }))), [])
    readonly property var linstat: pont.stockage.linstat ?? ({})
    // Sans moteur, pourquoi : LinStat absent, ou installé mais changé (sa carte reste ouvrable). "" quand LinStat répond.
    readonly property string sansLinstat: disques.length === 0 || linstat.moteur ? ""
        : (linstat.commande ?? null) !== null
          ? "LinStat ne répond plus comme prévu : l'analyse est en pause, la carte détaillée reste disponible."
          : "LinStat n'est pas installé : seul l'espace libre est affiché."
    readonly property string demande: applicationWindow().ongletStockage
    readonly property var entree: volumes.find(e => e.volume.chemin === demande) ?? null
    // L'onglet montré : celui que la fenêtre garde, s'il existe encore ; sinon la vue d'ensemble.
    readonly property string onglet: entree !== null ? demande : "ensemble"
    readonly property real marge: Style.margePage

    function choisir(cle) {
        applicationWindow().ongletStockage = cle;
    }
    // L'état écrit sur l'onglet d'un volume : celui de sa jauge s'il est en alerte, sinon « en cours » pendant son analyse.
    function etatOnglet(v) {
        if (v.etat === "echec" || v.etat === "attention")
            return v.etat;
        return pont.taches.some(t => t.id === "analyse:" + v.chemin && t.statut === "en_cours") ? "en_cours" : "";
    }

    // Le relevé se refait à l'ouverture : la page se met à jour d'elle-même quand stockage.json change.
    Component.onCompleted: pont.rafraichirStockage()
    // Un onglet qui disparaît (disque externe débranché) ramène à la vue d'ensemble pour de bon : il ne se rouvre pas tout seul
    // au retour du disque. Sans relevé (aucun disque encore), l'onglet gardé reste. Chaque onglet s'ouvre en haut.
    onOngletChanged: {
        if (disques.length > 0 && onglet !== demande)
            choisir("ensemble");
        contentItem.contentY = 0;
    }

    contentWidth: availableWidth
    contentHeight: colonne.implicitHeight + 1.75 * marge
    Controls.ScrollBar.horizontal.policy: Controls.ScrollBar.AlwaysOff

    ColumnLayout {
        id: colonne

        x: page.marge
        y: page.marge * 0.75
        width: page.availableWidth - 2 * page.marge
        spacing: Style.espace(3)

        Kirigami.Heading {
            level: 1
            type: Kirigami.Heading.Type.Primary
            font.pointSize: Style.tailleTitrePage
            font.weight: Font.Bold
            text: "Stockage"
        }
        Onglets {
            objectName: "stockage-onglets"
            Layout.fillWidth: true
            modele: [{ "cle": "ensemble", "libelle": "Vue d'ensemble", "etat": "" }].concat(page.volumes.map(e => ({
                "cle": e.volume.chemin,
                "libelle": e.volume.nom ?? e.volume.chemin,
                "etat": page.etatOnglet(e.volume)
            })))
            courant: page.onglet
            onChoisir: cle => page.choisir(cle)
        }
        Loader {
            Layout.fillWidth: true
            Layout.topMargin: Style.espace(1)
            sourceComponent: page.onglet === "ensemble" ? ongletEnsemble : ongletVolume
        }

        Component {
            id: ongletEnsemble

            StockageEnsemble {
                width: colonne.width          // le Loader d'une mise en page ne redimensionne pas ce qu'il charge
                disques: page.disques
                sansLinstat: page.sansLinstat
                onOuvrir: chemin => page.choisir(chemin)
            }
        }
        Component {
            id: ongletVolume

            StockageVolume {
                width: colonne.width
                volume: page.entree?.volume ?? ({})
                disque: page.entree?.disque ?? ({})
                sansLinstat: page.sansLinstat
            }
        }
    }
}
