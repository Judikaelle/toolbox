import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami
import "."

// Jeux, en onglets (v2b) : « Vue d'ensemble » (une ligne par sujet, un clic ouvre son onglet), puis les onglets que
// chaque tâche ajoute. Seul l'onglet ouvert existe ; la fenêtre le garde (ongletJeux) : revenir sur la page le rouvre.
// Tout vient de jeux.json (bibliothèques, doublons, préfixes, gels), de stockage.json (le ménage des jeux) et de
// etat.json (le résumé du mode jeu), écrits par le moteur ; le relevé se refait à l'ouverture. Pas de bouton principal :
// « Tout mettre à jour » reste en pied de menu. Les données et les formats communs aux onglets vivent ici ; chaque
// onglet les lit par sa propriété « page ».
Controls.ScrollView {
    id: pageJeux

    objectName: "page-jeux"
    readonly property var jeux: pont.jeux
    // jeux.json lu au moins une fois : sinon, chaque onglet qui en dépend dit que le relevé arrive (une liste venue du
    // pont n'est pas un Array JavaScript : on teste sa présence).
    readonly property bool releve: (jeux.bibliotheques ?? null) !== null
    readonly property var bibliotheques: jeux.bibliotheques ?? []
    readonly property var erreurs: jeux.erreurs ?? []
    readonly property var doublons: jeux.doublons ?? []
    readonly property var prefixes: jeux.prefixes ?? ({ "elements": [], "octets": 0, "taille": "0 Mo" })
    readonly property var gels: jeux.gels ?? ({ "nombre": 0, "automatiques": 0, "dernier": null, "liste": [] })
    readonly property string texteVide: "Pas encore de relevé des jeux : il se fait à l'ouverture de la page."
    // Le ménage des jeux : les recommandations de stockage.json que la page Jeux montre (copie de menage.IDS_JEUX).
    readonly property var idsMenage: ["shaders", "proton"]
    readonly property var recosJeux: (pont.stockage.recommandations ?? []).filter(r => idsMenage.includes(r.id))

    // Le résumé du mode jeu (etat.json) ; absent (etat.json d'avant le mode jeu) : le service ne tourne pas.
    readonly property var modejeu: pont.etat.modejeu ?? null
    readonly property string etatModeJeu: modejeu?.etat ?? "arrete"
    readonly property string phraseModeJeu: modejeu?.phrase ?? "Le service du mode jeu ne tourne pas."
    readonly property var motsModeJeu: ({
        "actif": { "mot": "Actif", "badge": "info" },
        "pret": { "mot": "Prêt", "badge": "ok" },
        "desactive": { "mot": "Désactivé", "badge": "neutre" },
        "arrete": { "mot": "Service arrêté", "badge": "attention" },
        "interrompu": { "mot": "Interrompu", "badge": "attention" }
    })

    // --- Onglets ---
    readonly property var cles: ["ensemble", "bibliotheques", "menage", "modejeu", "gels"]
    readonly property var libelles: ({ "ensemble": "Vue d'ensemble", "bibliotheques": "Bibliothèques", "menage": "Ménage",
                                       "modejeu": "Mode jeu", "gels": "Gels" })
    readonly property string demande: applicationWindow().ongletJeux
    // L'onglet montré : celui que la fenêtre garde, s'il existe ; sinon la vue d'ensemble.
    readonly property string onglet: cles.includes(demande) ? demande : "ensemble"
    readonly property real marge: Style.margePage
    // La hauteur qu'un onglet peut prendre sans faire défiler la page : ses longues listes s'y bornent et défilent seules.
    readonly property real hauteurOnglet: height - chargeur.y - 1.75 * marge

    function choisir(cle) {
        applicationWindow().ongletJeux = cle;
    }
    // L'onglet Bibliothèques, avec un filtre : "" (toutes), "doublons", ou l'id d'une bibliothèque.
    function ouvrirBibliotheques(filtre) {
        applicationWindow().filtreJeux = filtre;
        choisir("bibliotheques");
    }
    // L'état écrit sur un onglet (un point de sa couleur ; son contenu l'écrit aussi).
    function etatOnglet(cle) {
        if (cle === "bibliotheques")
            return erreurs.length > 0 || bibliotheques.some(b => b.absente) ? "attention" : "";
        if (cle === "modejeu") {
            if (etatModeJeu === "actif")
                return "en_cours";
            const coche = (modejeu?.reglages ?? {}).actif ?? true;
            return etatModeJeu === "interrompu" || (etatModeJeu === "arrete" && coche) ? "attention" : "";
        }
        return "";
    }
    function pluriel(n, mot, mots) {
        return n + " " + (n > 1 ? mots : mot);
    }
    // « 21 sept. » (Style.jour, sans « hier » : une capture se date).
    function jourCourt(iso) {
        const d = Style.dateDe(iso);
        return d ? d.toLocaleDateString(Qt.locale("fr_FR"), "d MMM") : "";
    }

    // Le relevé se refait à l'ouverture : la page se met à jour d'elle-même quand jeux.json, stockage.json ou etat.json
    // changent. Chaque onglet s'ouvre en haut.
    Component.onCompleted: pont.rafraichirJeux()
    onOngletChanged: contentItem.contentY = 0

    contentWidth: availableWidth
    contentHeight: colonne.implicitHeight + 1.75 * marge
    Controls.ScrollBar.horizontal.policy: Controls.ScrollBar.AlwaysOff

    ColumnLayout {
        id: colonne

        x: pageJeux.marge
        y: pageJeux.marge * 0.75
        width: pageJeux.availableWidth - 2 * pageJeux.marge
        spacing: Style.espace(3)

        Kirigami.Heading {
            level: 1
            type: Kirigami.Heading.Type.Primary
            font.pointSize: Style.tailleTitrePage
            font.weight: Font.Bold
            text: "Jeux"
        }
        Onglets {
            objectName: "jeux-onglets"
            Layout.fillWidth: true
            modele: pageJeux.cles.map(cle => ({ "cle": cle, "libelle": pageJeux.libelles[cle], "etat": pageJeux.etatOnglet(cle) }))
            courant: pageJeux.onglet
            onChoisir: cle => pageJeux.choisir(cle)
        }
        Loader {
            id: chargeur

            Layout.fillWidth: true
            Layout.topMargin: Style.espace(1)
            sourceComponent: ({ "ensemble": ongletEnsemble, "bibliotheques": ongletBibliotheques, "menage": ongletMenage,
                                "modejeu": ongletModeJeu, "gels": ongletGels })[pageJeux.onglet]
        }

        // Le Loader d'une mise en page ne redimensionne pas ce qu'il charge : chaque onglet prend la largeur de la page.
        Component {
            id: ongletEnsemble

            JeuxEnsemble {
                width: colonne.width
                page: pageJeux
            }
        }
        Component {
            id: ongletBibliotheques

            JeuxBibliotheques {
                width: colonne.width
                page: pageJeux
            }
        }
        Component {
            id: ongletMenage

            JeuxMenage {
                width: colonne.width
                page: pageJeux
            }
        }
        Component {
            id: ongletModeJeu

            JeuxModeJeu {
                width: colonne.width
                page: pageJeux
            }
        }
        Component {
            id: ongletGels

            JeuxGels {
                width: colonne.width
                page: pageJeux
            }
        }
    }
}
