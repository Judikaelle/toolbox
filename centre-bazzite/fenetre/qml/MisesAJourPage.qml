import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami
import "."

// Mises à jour : à gauche « Depuis ta dernière visite » et les sessions lancées depuis Health Hub,
// à droite soit les changements groupés (avec le détail du changement choisi), soit les étapes d'une session.
Item {
    id: page
    objectName: "page-majs"

    readonly property var etat: pont.etat
    readonly property var enCours: etat.en_cours ?? null
    readonly property var sessions: pont.sessions
    readonly property var chronologie: etat.depuis_visite?.chronologie ?? []
    readonly property var resumes: etat.resumes ?? {}
    readonly property var notes: etat.notes ?? {}
    readonly property real marge: Style.margePage

    // Choix de l'utilisateur : "visite", "cours" ou "s:<début>" ; vide = ce qui est le plus utile à voir.
    property string choix: ""
    readonly property string vue: choix !== "" ? choix : enCours ? "cours" : "visite"
    property string changementOuvert: ""
    property date maintenant: new Date()

    readonly property var groupes: [
        { "cle": "systeme", "titre": "Système" },
        { "cle": "applications", "titre": "Applications" },
        { "cle": "outils", "titre": "Outils" },
        { "cle": "conteneurs", "titre": "Conteneurs" }
    ]
    readonly property var nomsEtapes: ({
        "uupd": "Mise à jour du système",
        "maj-apps": "Mise à jour des outils",
        "notes": "Notes de version",
        "resume": "Résumé des nouveautés",
        "etat": "Bilan de santé",
        "extinction": "Extinction"
    })
    readonly property var statuts: ({
        "attente": { "mot": "En attente", "etat": "neutre" },
        "en_cours": { "mot": "En cours", "etat": "en_cours" },
        "fini": { "mot": "Terminée", "etat": "ok" },
        "reporte": { "mot": "Reportée", "etat": "attention" },
        "saute": { "mot": "Sautée", "etat": "neutre" },
        "echec": { "mot": "Échec", "etat": "echec" }
    })

    // Tous les changements de la chronologie, regroupés par catégorie.
    readonly property var changements: chronologie.reduce((tous, e) => tous.concat(e.changements ?? []), [])
    function date(iso) {
        const d = iso ? new Date(iso) : null;
        return d && !isNaN(d.getTime()) ? d : null;
    }
    function quand(iso) {
        const d = date(iso);
        if (!d)
            return "Date inconnue";
        const hier = new Date(maintenant);
        hier.setDate(hier.getDate() - 1);
        const heure = d.getHours() + " h " + String(d.getMinutes()).padStart(2, "0");
        const jour = d.toDateString() === maintenant.toDateString() ? "Aujourd'hui"
                   : d.toDateString() === hier.toDateString() ? "Hier"
                   : d.toLocaleDateString(Qt.locale("fr_FR"), "d MMM");
        return jour + " à " + heure;
    }
    // Une session coupée (reboot, arrêt de l'unité) est archivée en échec avec une étape « interrompue ».
    function interrompue(s) {
        return Object.values(s.etapes ?? {}).some(e => e.statut === "echec" && e.detail === "interrompue");
    }
    function issue(s) {
        return s.fin === null || s.fin === undefined ? { "mot": "En cours", "etat": "en_cours" }
             : s.succes ? { "mot": "Réussie", "etat": "ok" }
             : interrompue(s) ? { "mot": "Interrompue", "etat": "attention" }
             : { "mot": "Échec", "etat": "echec" };
    }
    function couleurDe(etat) {
        return etat === "ok" ? Style.ok
             : etat === "echec" ? Style.echec
             : etat === "attention" ? Style.attention
             : etat === "en_cours" ? Style.accent : "transparent";
    }
    function versions(c) {
        return c.de && c.vers ? c.de + " → " + c.vers
             : c.vers ? "nouveau, " + c.vers
             : c.de ? "retiré (" + c.de + ")" : "";
    }
    function etapesDe(session) {
        const etapes = session?.etapes ?? {};
        const ordre = Object.keys(nomsEtapes);
        return Object.keys(etapes).sort((a, b) => ordre.indexOf(a) - ordre.indexOf(b))
                     .map(nom => Object.assign({ "nom": nom }, etapes[nom]));
    }
    function sessionChoisie() {
        return vue === "cours" ? enCours : sessions.find(s => "s:" + s.debut === vue) ?? null;
    }
    function ouvrir(id) {
        changementOuvert = changementOuvert === id ? "" : id;
    }

    Timer {
        interval: 60000
        running: true
        repeat: true
        onTriggered: page.maintenant = new Date()
    }

    RowLayout {
        anchors.fill: parent
        spacing: 0

        // --- Colonne de gauche : visite et sessions ---
        Controls.ScrollView {
            Layout.preferredWidth: Kirigami.Units.gridUnit * 15
            Layout.fillHeight: true
            Controls.ScrollBar.horizontal.policy: Controls.ScrollBar.AlwaysOff
            contentWidth: availableWidth

            ColumnLayout {
                x: Kirigami.Units.largeSpacing
                y: page.marge * 0.75
                width: parent.width - 2 * Kirigami.Units.largeSpacing
                spacing: Kirigami.Units.smallSpacing

                Kirigami.Heading {
                    Layout.leftMargin: Kirigami.Units.largeSpacing
                    Layout.bottomMargin: Kirigami.Units.smallSpacing
                    level: 3
                    type: Kirigami.Heading.Type.Primary
                    font.pointSize: Style.tailleTitrePage
                    font.weight: Font.Bold
                    text: "Mises à jour"
                }

                Entree {
                    visible: !!page.enCours
                    cle: "cours"
                    titre: "En ce moment"
                    mot: page.enCours?.global !== undefined ? "En cours, " + page.enCours.global + " %" : "En cours"
                    etat: "en_cours"
                }
                Entree {
                    cle: "visite"
                    titre: "Depuis ta dernière visite"
                    mot: page.changements.length === 0 ? "Rien de nouveau"
                       : page.changements.length + (page.changements.length > 1 ? " changements" : " changement")
                    etat: "neutre"
                }

                Intertitre {
                    Layout.leftMargin: Kirigami.Units.largeSpacing
                    Layout.topMargin: Kirigami.Units.largeSpacing
                    text: "Lancées depuis Health Hub"
                }
                EtatVide {
                    objectName: "vide-sessions"
                    Layout.fillWidth: true
                    visible: page.sessions.length === 0
                    icone: "view-history"
                    texte: "Aucune mise à jour lancée depuis Health Hub pour l'instant."
                }
                Repeater {
                    model: page.sessions

                    delegate: Entree {
                        required property var modelData

                        cle: "s:" + modelData.debut
                        titre: page.quand(modelData.debut)
                        mot: page.issue(modelData).mot
                        etat: page.issue(modelData).etat
                    }
                }
            }
        }

        Kirigami.Separator {
            Layout.fillHeight: true
            color: Style.ligne
        }

        // --- Colonne de droite ---
        Controls.ScrollView {
            id: droite

            Layout.fillWidth: true
            Layout.fillHeight: true
            Controls.ScrollBar.horizontal.policy: Controls.ScrollBar.AlwaysOff
            contentWidth: availableWidth

            ColumnLayout {
                x: page.marge
                y: page.marge * 0.75
                width: droite.availableWidth - 2 * page.marge
                spacing: Kirigami.Units.gridUnit

                // Ce que le compteur du menu compte : mises à jour disponibles, redémarrage en attente, échecs.
                ARegarder {
                    Layout.fillWidth: true
                    rubrique: "majs"
                    lignesTitre: 2         // colonne étroite : un titre de redémarrage long ne prend pas la hauteur
                }

                // Session choisie : issue, puis une ligne par étape.
                ColumnLayout {
                    id: vueSession

                    readonly property var session: page.sessionChoisie()
                    readonly property bool enDirect: page.vue === "cours"
                    readonly property var resultat: session ? page.issue(session) : null

                    Layout.fillWidth: true
                    visible: page.vue !== "visite"
                    spacing: Kirigami.Units.largeSpacing

                    Kirigami.Heading {
                        Layout.fillWidth: true
                        level: 2
                        type: Kirigami.Heading.Type.Primary
                        font.pointSize: Style.tailleSection
                        font.weight: Font.Bold
                        text: vueSession.enDirect ? "Mise à jour en cours" : page.quand(vueSession.session?.debut)
                        wrapMode: Text.WordWrap
                    }
                    Controls.Label {
                        Layout.fillWidth: true
                        visible: vueSession.enDirect && !!vueSession.session?.unite
                        text: "Une mise à jour système tourne déjà en arrière-plan (" + vueSession.session?.unite
                              + "). Health Hub n'en suit pas les étapes."
                        color: Style.texteAttenue
                        wrapMode: Text.WordWrap
                    }
                    EtatVide {
                        objectName: "vide-session"
                        Layout.fillWidth: true
                        visible: !vueSession.session
                        icone: "view-history"
                        texte: "Cette session n'est plus disponible."
                    }

                    Carte {
                        Layout.fillWidth: true
                        visible: !!vueSession.session && !vueSession.session.unite
                        teinte: vueSession.resultat ? page.couleurDe(vueSession.resultat.etat) : "transparent"

                        RowLayout {
                            Layout.fillWidth: true
                            spacing: Style.espace(3)

                            Controls.Label {
                                text: "Résultat"
                                color: Style.texteAttenue
                            }
                            Badge {
                                objectName: "badge-resultat"
                                texte: vueSession.resultat?.mot ?? ""
                                etat: vueSession.resultat?.etat ?? "neutre"
                            }
                            Item {
                                Layout.fillWidth: true
                            }
                        }
                        Controls.Label {
                            Layout.fillWidth: true
                            visible: !vueSession.enDirect
                            text: vueSession.session?.bilan ?? "Détails non enregistrés pour cette session."
                            wrapMode: Text.WordWrap
                        }

                        Repeater {
                            model: page.etapesDe(vueSession.session)

                            delegate: ColumnLayout {
                                id: ligneEtape

                                required property var modelData
                                readonly property var statut: page.statuts[modelData.statut] ?? { "mot": String(modelData.statut), "etat": "neutre" }

                                Layout.fillWidth: true
                                spacing: Style.espace(1)

                                Kirigami.Separator {
                                    Layout.fillWidth: true
                                    Layout.bottomMargin: Style.espace(1)
                                    color: Style.ligne
                                }
                                RowLayout {
                                    Layout.fillWidth: true
                                    spacing: Style.espace(3)

                                    Controls.Label {
                                        Layout.fillWidth: true
                                        text: page.nomsEtapes[ligneEtape.modelData.nom] ?? ligneEtape.modelData.nom
                                        font.weight: Font.Medium
                                        elide: Text.ElideRight
                                    }
                                    Badge {
                                        objectName: "badge-etape-" + ligneEtape.modelData.nom
                                        texte: ligneEtape.statut.mot
                                        etat: ligneEtape.statut.etat
                                    }
                                }
                                Progression {
                                    objectName: "progression-etape-" + ligneEtape.modelData.nom
                                    Layout.fillWidth: true
                                    visible: ligneEtape.modelData.statut === "en_cours"
                                    valeur: (ligneEtape.modelData.progression ?? 0) / 100
                                }
                                Controls.Label {
                                    Layout.fillWidth: true
                                    visible: text !== ""
                                    text: ligneEtape.modelData.detail ?? ""
                                    color: Style.texteAttenue
                                    wrapMode: Text.WordWrap
                                }
                            }
                        }
                    }
                }

                // Changements propres à la session choisie.
                ColumnLayout {
                    Layout.fillWidth: true
                    visible: page.vue !== "visite" && !!vueSession.session?.changements
                    spacing: Kirigami.Units.largeSpacing

                    Kirigami.Heading {
                        Layout.fillWidth: true
                        level: 3
                        type: Kirigami.Heading.Type.Primary
                        font.pointSize: Style.tailleSection
                        font.weight: Font.Bold
                        text: "Changements de cette session"
                    }
                    Controls.Label {
                        Layout.fillWidth: true
                        visible: (vueSession.session?.changements ?? []).length === 0
                        text: "Aucun changement : tout était déjà à jour."
                        color: Style.texteAttenue
                        wrapMode: Text.WordWrap
                    }
                    Groupes {
                        Layout.fillWidth: true
                        source: vueSession.session?.changements ?? []
                    }
                }

                // Changements depuis la dernière visite.
                ColumnLayout {
                    Layout.fillWidth: true
                    visible: page.vue === "visite"
                    spacing: Kirigami.Units.largeSpacing

                    Kirigami.Heading {
                        Layout.fillWidth: true
                        level: 2
                        type: Kirigami.Heading.Type.Primary
                        font.pointSize: Style.tailleSection
                        font.weight: Font.Bold
                        text: "Depuis ta dernière visite"
                    }
                    EtatVide {
                        objectName: "vide-visite"
                        Layout.fillWidth: true
                        visible: page.changements.length === 0
                        icone: "checkmark"
                        texte: "Rien de nouveau depuis ta dernière visite."
                    }

                    Groupes {
                        Layout.fillWidth: true
                        source: page.changements
                    }
                }
            }
        }
    }

    // Changements groupés par catégorie, chacun dépliable (résumé, source, notes d'origine, avant → après).
    component Groupes: ColumnLayout {
        id: groupes

        property var source: []

        function duGroupe(cle) {
            return source.filter(c => c.categorie === cle);
        }

        spacing: Kirigami.Units.largeSpacing

        Repeater {
            model: page.groupes

            delegate: ColumnLayout {
                id: groupe

                required property var modelData
                readonly property var liste: groupes.duGroupe(modelData.cle)

                Layout.fillWidth: true
                visible: liste.length > 0
                spacing: 0

                Intertitre {
                    Layout.bottomMargin: Kirigami.Units.smallSpacing
                    text: groupe.modelData.titre
                }
                Repeater {
                    model: groupe.liste

                    delegate: ColumnLayout {
                        id: rang

                        required property var modelData
                        readonly property bool ouvert: page.changementOuvert === modelData.id
                        readonly property var note: page.notes[modelData.id] ?? null

                        Layout.fillWidth: true
                        spacing: 0

                        Controls.ItemDelegate {
                            Layout.fillWidth: true
                            id: ligneChangement

                            Accessible.name: (rang.modelData.nom || rang.modelData.id) + ", " + page.versions(rang.modelData)
                                             + (rang.ouvert ? ", détail affiché" : "")
                            onClicked: page.ouvrir(rang.modelData.id)

                            background: Rectangle {
                                radius: Style.rayonEntree
                                color: rang.ouvert ? Style.teinteFond(Style.accent)
                                     : ligneChangement.hovered ? Style.carte : "transparent"
                                border.width: ligneChangement.visualFocus ? 1 : 0
                                border.color: Style.accent
                            }

                            contentItem: RowLayout {
                                spacing: Kirigami.Units.largeSpacing

                                Kirigami.Icon {
                                    implicitWidth: Kirigami.Units.iconSizes.small
                                    implicitHeight: implicitWidth
                                    source: rang.ouvert ? "arrow-down" : "arrow-right"
                                    color: Style.texteAttenue
                                }
                                Controls.Label {
                                    Layout.fillWidth: true
                                    text: rang.modelData.nom || rang.modelData.id
                                    elide: Text.ElideRight
                                }
                                Controls.Label {
                                    text: page.versions(rang.modelData)
                                    color: Style.texteAttenue
                                    font.features: ({ "tnum": 1 })
                                }
                            }
                        }

                        // Détail du changement choisi.
                        ColumnLayout {
                            Layout.fillWidth: true
                            Layout.leftMargin: Kirigami.Units.gridUnit * 2
                            Layout.topMargin: Kirigami.Units.smallSpacing
                            Layout.bottomMargin: Kirigami.Units.largeSpacing
                            visible: rang.ouvert
                            spacing: Kirigami.Units.smallSpacing

                            Controls.Label {
                                Layout.fillWidth: true
                                objectName: "resume-" + rang.modelData.id
                                // Sans résumé : si la source officielle a échoué (lien sans texte), on le dit.
                                text: page.resumes[rang.modelData.id]
                                      ?? (rang.note?.lien && !rang.note?.texte
                                          ? "Notes officielles non récupérées pour l'instant : ouvre-les sur le site."
                                          : "Pas de résumé : pas de notes de version trouvées.")
                                wrapMode: Text.WordWrap
                            }
                            Controls.Label {
                                Layout.fillWidth: true
                                objectName: "source-" + rang.modelData.id
                                visible: !!rang.note?.source
                                text: "Source : " + (rang.note?.source ?? "")
                                color: Style.texteAttenue
                                font.pointSize: Style.tailleMeta
                            }
                            Controls.Label {
                                Layout.fillWidth: true
                                text: "Avant : " + (rang.modelData.de ?? "absent") + "   Après : " + (rang.modelData.vers ?? "retiré")
                                color: Style.texteAttenue
                                font.pointSize: Style.tailleMeta
                            }
                            ColumnLayout {
                                Layout.fillWidth: true
                                visible: !!rang.note?.texte
                                spacing: Kirigami.Units.smallSpacing

                                Bouton {
                                    objectName: "notes-origine-" + rang.modelData.id
                                    flat: true
                                    text: "Notes de version d'origine"
                                    icon.name: notesOuvertes.visible ? "arrow-down" : "arrow-right"
                                    onClicked: notesOuvertes.visible = !notesOuvertes.visible
                                }
                                Controls.ScrollView {
                                    id: notesOuvertes

                                    Layout.fillWidth: true
                                    Layout.preferredHeight: Math.min(Kirigami.Units.gridUnit * 14, texteNotes.implicitHeight + 2 * Kirigami.Units.smallSpacing)
                                    visible: false
                                    Controls.ScrollBar.horizontal.policy: Controls.ScrollBar.AlwaysOff

                                    Controls.TextArea {
                                        id: texteNotes

                                        readOnly: true
                                        selectByMouse: true
                                        wrapMode: TextEdit.Wrap
                                        text: rang.note?.texte ?? ""
                                        textFormat: TextEdit.PlainText
                                        background: Rectangle {
                                            radius: Style.rayonControle
                                            color: Style.fond
                                            border.width: 1
                                            border.color: Style.ligne
                                        }
                                    }
                                }
                            }
                            Bouton {
                                objectName: "ouvrir-notes-" + rang.modelData.id
                                visible: !!rang.note?.lien
                                text: "Ouvrir les notes"
                                icon.name: "internet-services"
                                onClicked: Qt.openUrlExternally(rang.note.lien)
                            }
                        }
                        Kirigami.Separator {
                            Layout.fillWidth: true
                            color: Style.ligne
                        }
                    }
                }
            }
        }
    }

    // Une entrée de la colonne de gauche : titre et état écrit dans un badge.
    component Entree: Controls.ItemDelegate {
        id: entree

        property string cle
        property string titre
        property string mot
        property string etat: "neutre"

        objectName: "entree-" + cle
        Layout.fillWidth: true
        Accessible.name: titre + ", " + mot
        onClicked: page.choix = cle

        background: Rectangle {
            radius: Style.rayonEntree
            color: page.vue === entree.cle ? Style.teinteFond(Style.accent)
                 : entree.hovered ? Style.carte : "transparent"
            border.width: entree.visualFocus ? 1 : 0
            border.color: Style.accent
        }

        contentItem: ColumnLayout {
            spacing: Style.espace(1)

            Controls.Label {
                Layout.fillWidth: true
                text: entree.titre
                font.weight: Font.DemiBold
                elide: Text.ElideRight
            }
            Badge {
                objectName: "badge-entree-" + entree.cle
                texte: entree.mot
                etat: entree.etat
            }
        }
    }
}
