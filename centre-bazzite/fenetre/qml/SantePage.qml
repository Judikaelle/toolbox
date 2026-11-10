import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami
import "."

// Santé, en onglets (Task 19) : « Résumé » (ce qui est à regarder, une ligne par domaine avec sa mesure clé, le bilan de
// la semaine), puis Disques, GPU et jeux, Système, Contrôles et Journal. Seul l'onglet ouvert existe ; la fenêtre le
// garde (ongletSante) : revenir sur la page le rouvre. Tout vient de pont.etat ; l'onglet d'un domaine porte la pire
// gravité des points actifs de la santé (rubrique « sante ») rangés dans ce domaine (champ « domaine », calculé par
// points.domaine). Les données et les formats communs aux onglets vivent ici ; chaque onglet les lit par sa propriété
// « page ».
Controls.ScrollView {
    id: pageSante

    objectName: "page-sante"
    readonly property var etat: pont.etat
    readonly property var sante: etat.sante ?? {}
    readonly property var points: etat.points ?? []
    // Les points mis en sourdine que la santé montre (onglet Journal, ligne du résumé) : pas ceux de volume, de ménage ni
    // de stockage, que la page Stockage montre ; ceux des mises à jour restent ici, leur page n'a pas de liste.
    readonly property var sourdines: points.filter(p => p.en_sourdine && !/^(volume|menage|stockage):/.test(String(p.id)))
    // Contrôles repris de bazzite-health, lus dans leur cache (null : jamais faits).
    readonly property var controles: sante.controles ?? null
    readonly property real marge: Style.margePage
    // Niveaux de bazzite-health (ok, attention, alerte), écrits en toutes lettres dans un badge.
    readonly property var niveaux: ({
        "ok": { "mot": "OK", "etat": "ok" },
        "attention": { "mot": "Attention", "etat": "attention" },
        "alerte": { "mot": "Alerte", "etat": "echec" }
    })
    // Liseré d'un disque : rouge si un point critique est actif, orange pour usure, réserve ou chaleur.
    function teinteDisque(modele) {
        const prefixe = "ssd:" + modele + ":";
        const actifs = points.filter(p => !p.en_sourdine && String(p.id).startsWith(prefixe)).map(p => String(p.id).slice(prefixe.length));
        if (actifs.some(i => i.startsWith("critique")))
            return Style.echec;
        if (actifs.some(i => i === "usure" || i === "reserve" || i === "chaleur"))
            return Style.attention;
        return "transparent";
    }

    function nombre(x, decimales) {
        return Number(x).toLocaleString(Qt.locale("fr_FR"), "f", decimales);
    }
    function pourcent(x) {
        return x === undefined || x === null ? "—" : Math.round(x) + " %";
    }
    function degres(x) {
        return x === undefined || x === null ? "—" : Math.round(x) + " °C";
    }
    function date(iso) {
        const d = iso ? new Date(iso) : null;
        return d && !isNaN(d.getTime()) ? d : null;
    }
    function jourHeure(iso) {
        const d = date(iso);
        return d ? d.toLocaleDateString(Qt.locale("fr_FR"), "d MMM") + " à " + d.getHours() + " h " + String(d.getMinutes()).padStart(2, "0") : "date inconnue";
    }
    // « 4 mises à jour, 2 sessions (1 en échec). »
    function syntheseSemaine(sem) {
        if (!sem)
            return "";
        const n = sem.changements ?? 0, m = sem.sessions ?? 0, e = sem.echecs ?? 0;
        return n + (n > 1 ? " mises à jour, " : " mise à jour, ") + m + (m > 1 ? " sessions" : " session")
               + " (" + e + " en échec).";
    }
    function jourCourt(iso) {
        const d = date(iso);
        return d ? d.toLocaleDateString(Qt.locale("fr_FR"), "d MMM") : "date inconnue";
    }
    function jour(iso) {
        const d = date(iso);
        return d ? d.toLocaleDateString(Qt.locale("fr_FR"), "d MMMM yyyy") : "";
    }
    // « 20260921-194442-GEL-JeuDeCourse.ex.txt » → « 21 septembre 2026 ».
    function dateDuGel(fichier) {
        const m = /^(\d{4})(\d{2})(\d{2})/.exec(String(fichier ?? ""));
        return m ? jour(m[1] + "-" + m[2] + "-" + m[3] + "T12:00:00") : "";
    }
    // Copie de commun.taille (mêmes opérations, mêmes bornes) : base 1024, virgule, une décimale sous
    // 10 Go et pour les To ; l'arrondi, moitié vers le haut, décide de l'unité et des décimales.
    function arrondi(x, decimales) {
        const f = Math.pow(10, decimales);
        return Math.floor(x * f + 0.5) / f;
    }
    function taille(octets) {
        const o = Math.max(0, Number(octets) || 0);
        const mo = arrondi(o / 1048576, 0);
        if (mo < 1024)
            return mo.toFixed(0) + " Mo";
        let go = arrondi(o / 1073741824, 1);
        if (go < 10)
            return go.toFixed(1).replace(".", ",") + " Go";
        go = arrondi(o / 1073741824, 0);
        if (go < 1024)
            return go.toFixed(0) + " Go";
        return arrondi(o / 1099511627776, 1).toFixed(1).replace(".", ",") + " To";
    }
    function pointDe(prefixe) {
        return points.find(p => String(p.id).startsWith(prefixe)) ?? null;
    }
    function liste(elements) {
        return elements.slice(0, 5).join(", ") + (elements.length > 5 ? " …" : "");
    }
    // Une ligne de contrôle : le mot et l'état de son badge, et une phrase de détail.
    function ligne(texte, etat, detail) {
        return { "texte": texte, "etat": etat, "detail": detail };
    }
    function impossible(detail) {
        return ligne("Vérification impossible", "neutre", detail);
    }
    function ligneImage(c) {
        if (c?.image == null)
            return impossible("Le dépôt de Bazzite n'a pas répondu ; nouvel essai au prochain relevé, dans l'heure.");
        const v = c.image.disponible ?? null;
        if (pointDe("maj:dispo:image:"))
            return ligne("1 à mettre à jour", "info", "Bazzite " + v + " est disponible.");
        return ligne("À jour", "ok", v ? "Bazzite " + v + " est déjà installée." : "Aucune nouvelle version de Bazzite.");
    }
    function ligneFlatpak(c) {
        if (c?.flatpak == null)
            return impossible("Flathub n'a pas répondu ; nouvel essai au prochain relevé, dans l'heure.");
        const apps = c.flatpak.a_mettre_a_jour ?? [];
        const p = pointDe("maj:dispo:flatpak");
        if (p)
            return ligne(Math.round(p.mesure) + " à mettre à jour", "info", liste(apps));
        return ligne("À jour", "ok", apps.length > 0 ? "Mises à jour depuis la vérification." : "Toutes les applications Flatpak sont à jour.");
    }
    function ligneRuntimes(c) {
        if (c?.runtimes == null)
            return impossible("La liste des runtimes Flatpak n'a pas pu être lue ; nouvel essai au prochain relevé, dans l'heure.");
        const tous = (c.runtimes.inutilises ?? []).concat((c.runtimes.gl_obsoletes ?? []).map(r => String(r).split("/")[1] ?? r));
        if (tous.length > 0)
            return ligne(tous.length + (tous.length > 1 ? " inutilisés" : " inutilisé"), "attention", liste(tous));
        return ligne("OK", "ok", "Aucun runtime Flatpak inutilisé.");
    }
    function ligneTelechargements(c) {
        if (c?.telechargements == null)
            return impossible("Les dossiers de téléchargement n'ont pas pu être lus.");
        const t = c.telechargements;
        if (t.length > 0)
            return ligne(t.length + (t.length > 1 ? " incomplets" : " incomplet"), "attention",
                         liste(t.map(x => x.nom + " (" + taille(x.octets) + ", " + x.present + " % présent)")));
        return ligne("OK", "ok", "Aucun téléchargement interrompu.");
    }
    function ligneCaches(c) {
        const k = c?.caches ?? null;
        const tailles = k ? "Miniatures " + taille(k.miniatures) + " · corbeille " + taille(k.corbeille)
                            + (k.journal != null ? " · journal système " + taille(k.journal) : "") : "";
        if (k === null || k.journal == null)
            return impossible(tailles !== "" ? tailles : "Les caches n'ont pas pu être mesurés.");
        if (pointDe("menage:journal"))
            return ligne("Journal à réduire", "attention", tailles + ". Pour le réduire : sudo journalctl --vacuum-size=500M");
        return ligne("OK", "ok", tailles);
    }
    function ligneBoot(c) {
        const b = c?.boot ?? null;
        if (b === null)
            return impossible("La partition /boot n'a pas pu être mesurée.");
        const detail = taille(b.libre_go * 1073741824) + " libres sur " + taille(b.total_go * 1073741824);
        return pointDe("volume:/boot") ? ligne("Presque plein", "attention", detail) : ligne("OK", "ok", detail);
    }
    function ligneErreurs(e) {
        if (e === null)
            return impossible("Le journal du noyau n'a pas pu être lu.");
        const n = e.nombre ?? 0;
        if (n === 0)
            return ligne("Aucune", "ok", "Aucune erreur de disque depuis le démarrage.");
        return ligne(n + (n > 1 ? " erreurs" : " erreur"), n > 5 ? "echec" : "attention",
                     (e.exemples ?? []).join("\n") + "\nLe détail : journalctl -k -b");
    }
    // Les volumes qui doivent être montés (sante.attendus, d'après la configuration locale) ; null : etat.json
    // d'avant leur relevé, la ligne reste, sans chemin.
    function ligneAttendus(nonMontes, attendus) {
        if (nonMontes === null)
            return impossible("Les montages n'ont pas pu être vérifiés.");
        if (nonMontes.length > 0)
            return ligne("Non monté", "echec", nonMontes.join(", ") + " est absent : ce qui y est installé ne se lancera pas.");
        return ligne("Monté", "ok", (attendus ?? []).map(v => v.chemin).join(", "));
    }
    function libelleAttendus(attendus) {
        return (attendus ?? []).length === 1 ? "Disque " + (attendus[0].nom ?? attendus[0].chemin) : "Volumes attendus";
    }
    function teinteDe(lignes) {
        return lignes.some(l => l.etat === "echec") ? Style.echec
             : lignes.some(l => l.etat === "attention") ? Style.attention : "transparent";
    }
    // Détails de bazzite-health : colonnes alignées par des espaces, lignes suivantes indentées.
    function detailsBilan(texte) {
        return String(texte ?? "").split("\n").map(l => l.replace(/^\s+/, "")).join("\n").trim();
    }

    // --- Onglets ---
    readonly property var domaines: ["disques", "gpu", "systeme", "controles", "journal"]
    readonly property var libelles: ({ "resume": "Résumé", "disques": "Disques", "gpu": "GPU et jeux",
                                       "systeme": "Système", "controles": "Contrôles", "journal": "Journal" })
    readonly property string demande: applicationWindow().ongletSante
    // L'onglet montré : celui que la fenêtre garde, s'il existe ; sinon le résumé.
    readonly property string onglet: demande === "resume" || domaines.includes(demande) ? demande : "resume"
    readonly property var motsEtat: ({ "ok": "OK", "attention": "Attention", "echec": "Échec", "info": "Info" })

    function choisir(cle) {
        applicationWindow().ongletSante = cle;
    }
    // La pire gravité des points actifs (hors sourdine) de la santé rangés dans un domaine : echec, attention, info,
    // sinon ok. Seule la rubrique « sante » compte (Ruling V68) : un échec de mise à jour ou un disque plein reste à sa
    // page (Mises à jour, Stockage) et ne colore pas la santé.
    function etatDomaine(domaine) {
        const actifs = points.filter(p => !p.en_sourdine && p.rubrique === "sante" && p.domaine === domaine);
        return actifs.some(p => p.gravite === "echec") ? "echec"
             : actifs.some(p => p.gravite === "attention") ? "attention"
             : actifs.length > 0 ? "info" : "ok";
    }

    onOngletChanged: contentItem.contentY = 0     // chaque onglet s'ouvre en haut

    contentWidth: availableWidth
    contentHeight: colonne.implicitHeight + 1.75 * marge
    Controls.ScrollBar.horizontal.policy: Controls.ScrollBar.AlwaysOff

    ColumnLayout {
        id: colonne

        x: pageSante.marge
        y: pageSante.marge * 0.75
        width: pageSante.availableWidth - 2 * pageSante.marge
        spacing: Style.espace(3)

        Kirigami.Heading {
            level: 1
            type: Kirigami.Heading.Type.Primary
            font.pointSize: Style.tailleTitrePage
            font.weight: Font.Bold
            text: "Santé"
        }
        Onglets {
            objectName: "sante-onglets"
            Layout.fillWidth: true
            modele: ["resume"].concat(pageSante.domaines).map(cle => {
                const etat = cle === "resume" ? "ok" : pageSante.etatDomaine(cle);
                return { "cle": cle, "libelle": pageSante.libelles[cle], "etat": etat === "ok" ? "" : etat };
            })
            courant: pageSante.onglet
            onChoisir: cle => pageSante.choisir(cle)
        }
        Loader {
            Layout.fillWidth: true
            Layout.topMargin: Style.espace(1)
            sourceComponent: ({ "resume": ongletResume, "disques": ongletDisques, "gpu": ongletGpu,
                                "systeme": ongletSysteme, "controles": ongletControles,
                                "journal": ongletJournal })[pageSante.onglet]
        }

        // Le Loader d'une mise en page ne redimensionne pas ce qu'il charge : chaque onglet prend la largeur de la page.
        Component {
            id: ongletResume

            SanteResume {
                width: colonne.width
                page: pageSante
            }
        }
        Component {
            id: ongletDisques

            SanteDisques {
                width: colonne.width
                page: pageSante
            }
        }
        Component {
            id: ongletGpu

            SanteGpu {
                width: colonne.width
                page: pageSante
            }
        }
        Component {
            id: ongletSysteme

            SanteSysteme {
                width: colonne.width
                page: pageSante
            }
        }
        Component {
            id: ongletControles

            SanteControles {
                width: colonne.width
                page: pageSante
            }
        }
        Component {
            id: ongletJournal

            SanteJournal {
                width: colonne.width
                page: pageSante
            }
        }
    }
}
