pragma Singleton
import QtQuick
import org.kde.kirigami as Kirigami

// Apparence de Health Hub : celle de GitHub Hub (fonds, cartes, bordures, rayons, échelle de texte), toujours sombre,
// avec un accent émeraude (Ruling V57, maquette docs/maquettes/palette-verte.html, variante B). C'est le seul
// fichier QML qui écrit des couleurs : Main.qml pose cette palette à la racine (Kirigami.Theme), les composants
// lisent Style ou Kirigami.Theme. ../health-hub.colors en est la traduction pour le style KDE (dialogues, infobulles).
QtObject {
    // --- Palette ---
    readonly property color fond: "#0b0e14"            // fenêtre
    readonly property color fondMenu: "#10141c"        // menu, panneau Activité, dialogues
    readonly property color carte: "#151a23"
    readonly property color releve: "#1b2130"          // boutons secondaires, pistes des barres, infobulles
    readonly property color ligne: "#262d3b"           // bordure des cartes, séparateurs
    readonly property color ligne2: "#313a4c"          // bordure des boutons, cadres en pointillés
    readonly property color texte: "#e7ecf3"
    readonly property color texteAttenue: "#8a94a7"    // libellés, méta
    readonly property color texteDim: "#5d6779"        // intertitres, désactivé
    readonly property color accent: "#34d399"          // accent, liens, entrée active, info, en cours
    readonly property color accent2: "#10b981"         // départ des dégradés de l'accent
    readonly property color texteSurAccent: "#062a1e"  // texte du bouton principal
    readonly property color ok: "#3fb950"
    readonly property color attention: "#e3a52f"
    readonly property color echec: "#f2555a"

    // --- Rayons ---
    readonly property real rayonCarte: 14
    readonly property real rayonBandeau: 18            // bandeau d'accueil, dialogues
    readonly property real rayonControle: 10           // boutons, champs
    readonly property real rayonEntree: 9              // entrée de menu
    readonly property real rayonBarre: 4               // barre de progression (les pilules : hauteur / 2)

    // --- Espaces (pas de 4 px) ---
    function espace(n) {
        return 4 * n;
    }
    readonly property real margePage: 24
    readonly property real gouttiere: 16
    readonly property real margeCarte: 18
    readonly property real lisere: 3
    readonly property real epaisseurBarre: 4
    readonly property real hauteurBouton: 34

    readonly property real largeurMenu: 250
    readonly property real largeurRail: Kirigami.Units.gridUnit * 3.5
    readonly property real largeurActivite: 380

    // --- Texte : l'échelle de GitHub Hub en pixels, sur la police du système (Noto Sans, comme GitHub Hub ici) ---
    // Qt compte en points : 1 px = 0,75 pt à 96 ppp logiques.
    function points(px) {
        return px * 0.75;
    }
    readonly property real tailleTitrePage: points(20)
    readonly property real tailleBandeau: points(23)
    readonly property real tailleChiffre: points(22)     // chiffres clés (libellé en tailleMeta, atténué)
    readonly property real tailleSection: points(16)
    readonly property real tailleTitreCarte: points(15)
    readonly property real tailleCorps: points(13.5)
    readonly property real tailleBouton: points(13)
    readonly property real tailleMeta: points(12)
    readonly property real tailleBadge: points(11.5)
    readonly property real tailleMono: points(11.5)      // journaux
    readonly property real tailleIntertitre: points(11)  // en capitales, interlettrage de 0,08 em
    readonly property real interlettrage: 11 * 0.08

    readonly property real alphaFond: 0.14
    readonly property real alphaBordure: 0.35

    readonly property int dureeSurvol: Kirigami.Units.shortDuration
    // 0 quand les animations sont coupées.
    readonly property int dureePanneau: Kirigami.Units.longDuration

    // Teintes d'état : fond à 14 %, bordure à 35 %.
    function teinteFond(c) {
        return Qt.alpha(c, alphaFond);
    }
    function teinteBordure(c) {
        return Qt.alpha(c, alphaBordure);
    }
    // Couleur d'un état écrit dans un badge ; « info » et « en cours » prennent l'accent.
    function couleurEtat(etat) {
        switch (etat) {
        case "ok": return ok;
        case "attention": return attention;
        case "echec": return echec;
        case "info":
        case "en_cours": return accent;
        default: return texteAttenue;
        }
    }

    // --- Temps et état global, communs à l'accueil et au menu ---
    readonly property var etatsGlobaux: ({
        "vert": { "mot": "Tout va bien", "badge": "ok" },
        "orange": { "mot": "À regarder", "badge": "attention" },
        "rouge": { "mot": "Échec", "badge": "echec" },
        "en_cours": { "mot": "Mise à jour en cours", "badge": "en_cours" }
    })

    function dateDe(iso) {
        const d = iso ? new Date(iso) : null;
        return d && !isNaN(d.getTime()) ? d : null;
    }
    function heure(d) {
        return d.getHours() + " h " + String(d.getMinutes()).padStart(2, "0");
    }
    // "" aujourd'hui, « hier », sinon « 8 nov. ».
    function jour(d, maintenant) {
        const hier = new Date(maintenant);
        hier.setDate(hier.getDate() - 1);
        if (d.toDateString() === maintenant.toDateString())
            return "";
        if (d.toDateString() === hier.toDateString())
            return "hier";
        return d.toLocaleDateString(Qt.locale("fr_FR"), "d MMM");
    }
    function derniereVerification(iso, maintenant) {
        const d = dateDe(iso);
        if (!d)
            return "Pas encore de vérification";
        const j = jour(d, maintenant);
        return "Dernière vérification " + (j === "" ? "" : j === "hier" ? "hier " : "le " + j + " ") + "à " + heure(d);
    }
}
