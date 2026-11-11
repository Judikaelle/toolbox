import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami
import "."

// Démarrage, en onglets (v2c) : « Durée » (le démarrage découpé, ce qui ralentit), « Au lancement » (ce qui démarre avec ta
// session, avec ses bascules confirmées) et « Système » (les services du système, en lecture seule). Seul l'onglet ouvert existe ; la fenêtre le garde (ongletDemarrage) : revenir sur la page le rouvre.
// Tout vient de demarrage.json et du résumé de etat.json, écrits par le moteur ; le relevé se refait à l'ouverture.
// Pas de bouton principal : « Tout mettre à jour » reste en pied de menu. Les données communes aux onglets vivent ici ;
// chaque onglet les lit par sa propriété « page ».
Controls.ScrollView {
    id: pageDemarrage

    objectName: "page-demarrage"
    readonly property var demarrage: pont.demarrage
    // demarrage.json lu au moins une fois : sinon, la page dit que le relevé arrive.
    readonly property bool releve: (demarrage.genere ?? null) !== null
    // Une durée vaut null tant que le démarrage n'est pas fini.
    readonly property var duree: demarrage.duree ?? null
    readonly property var habituel: demarrage.habituel ?? null
    readonly property var precedents: demarrage.precedents ?? []
    readonly property var ralentisseurs: demarrage.ralentisseurs ?? []
    readonly property var arrierePlan: demarrage.arriere_plan ?? []
    readonly property var systeme: demarrage.systeme ?? []
    readonly property var erreurs: demarrage.erreurs ?? []
    readonly property string phrase: pont.etat.demarrage?.phrase ?? ""
    readonly property string texteVide: "Pas encore de relevé du démarrage : il se fait à l'ouverture de la page."
    // Le retour de la CLI (onglet Au lancement) que la croix a fermé : il ne revient pas en changeant d'onglet.
    property string retourFerme: ""

    // --- Onglets ---
    readonly property var cles: ["duree", "lancement", "systeme"]
    readonly property var libelles: ({ "duree": "Durée", "lancement": "Au lancement", "systeme": "Système" })
    readonly property string demande: applicationWindow().ongletDemarrage
    // L'onglet montré : celui que la fenêtre garde, s'il existe ; sinon la durée.
    readonly property string onglet: cles.includes(demande) ? demande : "duree"
    readonly property real marge: Style.margePage
    // La hauteur qu'un onglet peut prendre sans faire défiler la page : ses longues listes s'y bornent et défilent seules.
    readonly property real hauteurOnglet: height - chargeur.y - 1.75 * marge

    function choisir(cle) {
        applicationWindow().ongletDemarrage = cle;
    }
    function pluriel(n, mot, mots) {
        return n + " " + (n > 1 ? mots : mot);
    }

    // Le relevé se refait à l'ouverture : la page se met à jour d'elle-même quand demarrage.json ou etat.json changent.
    // Chaque onglet s'ouvre en haut.
    Component.onCompleted: pont.rafraichirDemarrage()
    onOngletChanged: contentItem.contentY = 0

    contentWidth: availableWidth
    contentHeight: colonne.implicitHeight + 1.75 * marge
    Controls.ScrollBar.horizontal.policy: Controls.ScrollBar.AlwaysOff

    ColumnLayout {
        id: colonne

        x: pageDemarrage.marge
        y: pageDemarrage.marge * 0.75
        width: pageDemarrage.availableWidth - 2 * pageDemarrage.marge
        spacing: Style.espace(3)

        RowLayout {
            Layout.fillWidth: true
            spacing: Style.espace(3)

            Kirigami.Heading {
                level: 1
                type: Kirigami.Heading.Type.Primary
                font.pointSize: Style.tailleTitrePage
                font.weight: Font.Bold
                text: "Démarrage"
            }
            TexteAbrege {
                objectName: "demarrage-phrase"
                Layout.fillWidth: true
                horizontalAlignment: Text.AlignRight
                text: pageDemarrage.phrase
                color: Style.texteAttenue
            }
        }
        // Sans relevé, la page ne montre que cette phrase : pas d'onglets à ouvrir.
        EtatVide {
            objectName: "demarrage-vide"
            Layout.fillWidth: true
            visible: !pageDemarrage.releve
            icone: "chronometer"
            texte: pageDemarrage.texteVide
        }
        Onglets {
            objectName: "demarrage-onglets"
            Layout.fillWidth: true
            visible: pageDemarrage.releve
            modele: pageDemarrage.cles.map(cle => ({ "cle": cle, "libelle": pageDemarrage.libelles[cle], "etat": "" }))
            courant: pageDemarrage.onglet
            onChoisir: cle => pageDemarrage.choisir(cle)
        }
        Loader {
            id: chargeur

            Layout.fillWidth: true
            Layout.topMargin: Style.espace(1)
            active: pageDemarrage.releve
            sourceComponent: ({ "duree": ongletDuree, "lancement": ongletLancement, "systeme": ongletSysteme })[pageDemarrage.onglet]
        }

        // Le Loader d'une mise en page ne redimensionne pas ce qu'il charge : chaque onglet prend la largeur de la page.
        Component {
            id: ongletDuree

            DemarrageDuree {
                width: colonne.width
                page: pageDemarrage
            }
        }
        Component {
            id: ongletLancement

            DemarrageLancement {
                width: colonne.width
                page: pageDemarrage
            }
        }
        Component {
            id: ongletSysteme

            DemarrageSysteme {
                width: colonne.width
                page: pageDemarrage
            }
        }
    }
}
