import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami
import "."

// Santé, en onglets (Task 19) : « Résumé » (ce qui est à regarder, une ligne par domaine avec sa mesure clé, le bilan de
// la semaine), puis Disques, GPU et jeux, Système, Sécurité, Contrôles et Journal. Seul l'onglet ouvert existe ; la fenêtre le
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
    // Le noyau (messages de cette session, par catégorie) et la mémoire, relevés par sante.py ; null : illisible.
    readonly property var noyau: sante.noyau ?? null
    readonly property var memoire: sante.memoire ?? null
    // La sécurité (ports, pare-feu, démarrage, dossiers temporaires), relevée par securite.py ; null : jamais relevée.
    readonly property var securite: sante.securite ?? null
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
                         liste(t.map(x => x.nom + " (" + Style.taille(x.octets) + ", " + x.present + " % présent)")));
        return ligne("OK", "ok", "Aucun téléchargement interrompu.");
    }
    function ligneCaches(c) {
        const k = c?.caches ?? null;
        const tailles = k ? "Miniatures " + Style.taille(k.miniatures) + " · corbeille " + Style.taille(k.corbeille)
                            + (k.journal != null ? " · journal système " + Style.taille(k.journal) : "") : "";
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
        const detail = Style.taille(b.libre_go * 1073741824) + " libres sur " + Style.taille(b.total_go * 1073741824);
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
    // --- Sécurité : l'état d'une ligne est la gravité de son point (securite:*), sinon « ok » ; une mesure illisible
    // (null) vaut « Vérification impossible ». Aucun seuil n'est recalculé ici.
    // Le premier point de ce préfixe (ou, avec `exact`, de cet id) : `actif` true ne retient que ceux hors sourdine.
    function trouverPoint(prefixe, exact, actif) {
        return points.find(p => (!actif || !p.en_sourdine) && (exact ? String(p.id) === prefixe : String(p.id).startsWith(prefixe))) ?? null;
    }
    function pointActif(prefixe, exact) {
        return trouverPoint(prefixe, exact === true, true);
    }
    function etatDuPoint(prefixe, exact) {
        return pointActif(prefixe, exact)?.gravite ?? "ok";
    }
    // `texte` : le mot du badge ; null, le mot de l'état (« Attention », « Échec »). Un point en sourdine n'est plus signalé :
    // la ligne dit « En sourdine » (neutre) et garde son détail, le problème reste décrit. `exact` : l'id entier, pas un préfixe.
    function ligneDuPoint(prefixe, texte, detail, exact) {
        if (!pointActif(prefixe, exact) && trouverPoint(prefixe, exact === true, false))
            return ligne("En sourdine", "neutre", detail);
        const etat = etatDuPoint(prefixe, exact);
        return ligne(texte ?? motsEtat[etat] ?? "", etat, detail);
    }
    function ligneParefeu(s) {
        const p = s?.pare_feu ?? null;
        if (p === null)
            return impossible("L'état du pare-feu (firewalld) n'a pas pu être lu.");
        if (!p.actif)
            return ligneDuPoint("securite:pare-feu", "Arrêté", pointDe("securite:pare-feu")?.detail
                                ?? "Rien ne filtre les connexions venant du réseau.");
        const parts = [p.zone ? "Zone " + p.zone : "Pare-feu actif"];
        if (p.ouvre_hauts)
            parts.push("laisse entrer les ports au-dessus de 1024");
        else if ((p.ports ?? []).length > 0)
            parts.push("ports ouverts : " + liste(p.ports));
        return ligne("Actif", "ok", parts.join(" : ") + ((p.services ?? []).length > 0 ? ". Services : " + liste(p.services) : ""));
    }
    function nomsDePorts(e) {
        return e.prog + " (" + (e.ports ?? []).join(", ") + ")";
    }
    // Une ligne par programme inconnu, ou null si la mesure est illisible.
    function lignesPorts(s) {
        const p = s?.ports ?? null;
        if (p === null)
            return null;
        return (p.inconnus ?? []).map(i => ligneDuPoint("securite:port:" + i.prog, null,
            "Ports " + (i.ports ?? []).join(", ") + ", joignables par le réseau local.", true));
    }
    // La ligne d'information qui groupe le reste (programmes connus, ports sans programme visible), ou null.
    function ligneAutresPorts(s) {
        const p = s?.ports ?? null;
        const connus = p?.connus ?? [], systeme = p?.systeme ?? [];
        if (p === null || connus.length + systeme.length === 0)
            return null;
        const parts = [];
        if (connus.length > 0)
            parts.push(liste(connus.map(nomsDePorts)));
        if (systeme.length > 0)
            parts.push("sans programme visible : " + liste(systeme));
        // des programmes, ou des ports : jamais les deux additionnés
        const titre = connus.length > 0 ? pluriel(connus.length, "programme", "programmes") : pluriel(systeme.length, "port", "ports");
        return ligne(titre, "info", parts.join(" ; "));
    }
    function nomDuFichier(chemin) {
        return String(chemin).split("/").pop();
    }
    // Une ligne par fichier de démarrage signalé, sinon « Rien de suspect » ; null : mesure illisible.
    function lignesDemarrage(s) {
        const d = s?.demarrage ?? null;
        if (d === null)
            return null;
        return (d.trouves ?? []).map(f => ligneDuPoint("securite:demarrage:" + f.chemin, null,
            (f.role ?? "Fichier de démarrage") + " : " + f.chemin + ", ligne " + f.numero + " : " + f.ligne, true));
    }
    function ligneDemarrageOk(s) {
        const d = s?.demarrage ?? null;
        const lus = (d?.lus ?? 0) + (d?.lus === 1 ? " fichier lu" : " fichiers lus");
        if (d?.incomplet)
            return ligne("Incomplet", "neutre", lus + " ; la liste des services systemd n'a pas pu être lue.");
        return ligne("Rien de suspect", "ok", lus + ".");
    }
    // /etc/ld.so.preload non vide : une ligne en plus dans la carte du démarrage ; null sinon.
    function ligneLdPreload(s) {
        const l = s?.ld_preload ?? null;
        if (l === null || l.length === 0)
            return null;
        return ligneDuPoint("securite:ld-preload", null, "/etc/ld.so.preload contient : " + liste(l));
    }
    function ligneTemporaires(s) {
        const t = s?.temporaires ?? null;
        if (t === null)
            return impossible("Les dossiers temporaires n'ont pas pu être parcourus.");
        const n = t.nombre ?? 0;
        if (n === 0)
            return ligne("Aucun programme", "ok", (t.examines ?? 0) + " éléments examinés dans /tmp, /var/tmp et /dev/shm"
                         + (t.plafond_atteint ? " (parcours limité)." : "."));
        const plus = t.plafond_atteint ? "Au moins " : "";
        return ligneDuPoint("securite:temporaires", plus + n + (n > 1 ? " programmes" : " programme"),
                            liste(t.exemples ?? []));
    }
    function ligneCache(s) {
        const c = s?.cache ?? null;
        if (c === null)
            return impossible("Le dossier ~/.cache n'a pas pu être parcouru.");
        if (c.length === 0)
            return ligne("Aucun", "ok", "Aucun programme exécutable dans ~/.cache.");
        return ligne(c.length + (c.length > 1 ? " dossiers" : " dossier"), "info",
                     "Programmes dans ~/.cache (normal pour des outils comme uv) : "
                     + liste(c.map(x => x.dossier + " (" + x.nombre + ")")));
    }
    // --- Noyau et mémoire : l'état d'une ligne est la gravité de son point (noyau:*, memoire:*), sinon « ok » ; une source
    // illisible (null) vaut « Vérification impossible ». Aucun seuil n'est recalculé ici.
    function pluriel(n, mot, mots) {
        return n + " " + (n > 1 ? mots : mot);
    }
    function ligneNoyauGpu(n) {
        const g = n?.gpu ?? null;
        if (g === null)
            return impossible("Le journal du noyau n'a pas pu être lu.");
        const nb = g.nombre ?? 0;
        if (nb === 0 && !g.chute)
            return ligne("Aucune", "ok", "Aucune erreur du pilote depuis le démarrage.");
        const exemples = (g.exemples ?? []).join("\n");
        const graves = (g.graves ?? 0) > 0 || g.chute;
        const detail = graves ? exemples : "Erreurs causées par une application, sans gravité pour le système."
                                             + (exemples !== "" ? "\n" + exemples : "");
        return ligneDuPoint("noyau:gpu", g.chute ? "Carte perdue" : pluriel(nb, "erreur", "erreurs"),
                            detail + "\nLe détail : journalctl -k -b", true);
    }
    // Une catégorie du noyau (matériel, USB) : le nombre de lignes, et leurs exemples.
    function ligneNoyauCategorie(n, cle) {
        const c = n?.[cle] ?? null;
        if (c === null)
            return impossible("Le journal du noyau n'a pas pu être lu.");
        const nb = c.nombre ?? 0;
        if (nb === 0)
            return ligne("Aucune", "ok", "Aucune erreur depuis le démarrage.");
        return ligneDuPoint("noyau:" + cle, pluriel(nb, "erreur", "erreurs"),
                            (c.exemples ?? []).join("\n") + "\nLe détail : journalctl -k -b", true);
    }
    function ligneMateriel(n) {
        return ligneNoyauCategorie(n, "materiel");
    }
    function ligneUsb(n) {
        return ligneNoyauCategorie(n, "usb");
    }
    // « 24 Go disponibles sur 32 Go · attente 0,4 % · swap 0 Mo sur 8,0 Go · zram 2,0 Go → 512 Mo (zstd) »
    function ligneMemoire(m) {
        if (m === null)
            return impossible("La mémoire n'a pas pu être lue.");
        const parts = [Style.taille(m.disponible) + " disponibles sur " + Style.taille(m.total)];
        if (m.attente != null)
            parts.push("attente " + nombre(m.attente, 1) + " %");
        const zram = m.zram ?? [];
        if ((m.swap_total ?? 0) > 0)
            parts.push("swap " + Style.taille(m.swap_utilise) + " sur " + Style.taille(m.swap_total));
        if (zram.length > 0)
            parts.push("zram " + zram.map(z => Style.taille(z.donnees) + " → " + Style.taille(z.compresse)
                                              + (z.algo ? " (" + z.algo + ")" : "")).join(", "));
        let detail = parts.join(" · ");
        if (zram.length > 0 && (m.swap_total ?? 0) > 0 && (m.swap_utilise ?? 0) > 0.5 * m.swap_total)
            detail += ". Un swap bien rempli est normal avec zram.";
        // Le pire des deux points actifs : la pression (« Saturée », « Juste ») l'emporte à gravité égale.
        const rang = { "echec": 3, "attention": 2, "info": 1 };
        const pression = pointActif("memoire:pression", true), sansSwap = pointActif("memoire:sans-swap", true);
        if (!pression && !sansSwap && (trouverPoint("memoire:", false, false)))
            return ligne("En sourdine", "neutre", detail);
        if (sansSwap)
            detail += ". Ni swap ni zram n'est actif.";
        const pire = sansSwap && (!pression || (rang[sansSwap.gravite] ?? 0) > (rang[pression.gravite] ?? 0)) ? sansSwap : pression;
        if (!pire)
            return ligne("OK", "ok", detail);
        const mot = pire === sansSwap ? "Sans swap" : pire.gravite === "echec" ? "Saturée" : "Juste";
        return ligne(mot, pire.gravite, detail);
    }
    // Détails de bazzite-health : colonnes alignées par des espaces, lignes suivantes indentées.
    function detailsBilan(texte) {
        return String(texte ?? "").split("\n").map(l => l.replace(/^\s+/, "")).join("\n").trim();
    }

    // --- Onglets ---
    readonly property var domaines: ["disques", "gpu", "systeme", "securite", "controles", "journal"]
    readonly property var libelles: ({ "resume": "Résumé", "disques": "Disques", "gpu": "GPU et jeux",
                                       "systeme": "Système", "securite": "Sécurité", "controles": "Contrôles", "journal": "Journal" })
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
                                "systeme": ongletSysteme, "securite": ongletSecurite, "controles": ongletControles,
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
            id: ongletSecurite

            SanteSecurite {
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
