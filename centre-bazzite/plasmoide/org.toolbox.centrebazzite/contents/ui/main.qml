import QtQuick
import QtQuick.Layouts
import QtQuick.Shapes
import org.kde.kirigami as Kirigami
import org.kde.plasma.components as PlasmaComponents3
import org.kde.plasma.core as PlasmaCore
import org.kde.plasma.plasma5support as P5Support
import org.kde.plasma.plasmoid

// Le Health Hub dans la zone de notification : une icône avec une pastille d'état, et le panneau
// rapide de la maquette. Le plasmoïde ne calcule rien : il lit etat.json (écrit par le moteur) et
// confie chaque action à la CLI centre-bazzite.
PlasmoidItem {
    id: root

    // CENTRE_BAZZITE_ETAT remplace etat.json par un fichier d'essai (vérification avec plasmawindowed).
    readonly property string fichierEtat: "\"${CENTRE_BAZZITE_ETAT:-$HOME/.local/state/centre-bazzite/etat.json}\""
    readonly property string commandeLecture: "cat " + fichierEtat
    // Pendant une mise à jour, l'état est d'abord recalculé (sans les mesures de santé), puis relu.
    readonly property string commandeSuivi: "timeout 60 centre-bazzite rafraichir --leger >/dev/null 2>&1; cat " + fichierEtat
    readonly property int toursApresAction: 10       // 10 lectures rapides (30 s) après une action

    property var etat: null                    // dernier état lu correctement ; null tant qu'il n'y en a aucun
    property string dernierTexte: ""
    property bool lectureEnAttente: false
    property int toursRapides: 0
    property bool lancement: false             // une mise à jour vient d'être demandée
    property bool confirmationExtinction: false
    property string confirmationJeu: ""        // "maj" ou "eteindre" : action en attente, un jeu tourne
    property string jeuSignale: ""             // nom du jeu donné par la CLI quand elle refuse
    property string extinctionAnnulee: ""      // session (début) dont l'annulation de l'extinction est demandée
    property string erreur: ""
    property date maintenant: new Date()

    readonly property var enCours: etat?.en_cours ?? null
    readonly property var extinction: etat?.extinction ?? null
    readonly property bool majEnCours: !!enCours || lancement
    // Les boutons attendent la fin d'une session de Health Hub ; pendant un rattrapage de uupd seul, ils
    // restent actifs (la session suit la mise à jour en cours, puis fait le reste).
    readonly property bool boutonsBloques: !!enCours?.debut || lancement
    readonly property string jeu: etat?.jeu ?? ""
    readonly property string nomJeu: jeuSignale || jeu || "inconnu"
    // « Mettre à jour et éteindre » : extinction prévue pendant toute la session, annulable à tout moment.
    readonly property bool extinctionPrevue: !!enCours?.eteindre || !!extinction?.a
    readonly property bool suiviRapide: !!enCours || !!extinction || toursRapides > 0
    readonly property var etatGlobal: etats[etat?.couleur] ?? null
    // Les points actifs, échecs d'abord (même règle que la couleur du moteur : ni sourdine, ni info).
    readonly property var aRegarder: {
        const actifs = (etat?.points ?? []).filter(p => !p.en_sourdine && p.gravite !== "info");
        return actifs.filter(p => p.gravite === "echec").concat(actifs.filter(p => p.gravite !== "echec"));
    }
    readonly property bool extinctionAnnuleeIci: !!etat?.extinction_annulee
        || (extinctionAnnulee !== "" && extinctionAnnulee === (enCours?.debut ?? extinction?.a ?? ""))
    readonly property string raisonAnnulation: enCours?.etapes?.extinction?.detail ?? ""
    readonly property int secondesExtinction: {
        const a = extinction?.a ? new Date(extinction.a) : null;
        return a && !isNaN(a.getTime()) ? Math.max(0, Math.round((a - maintenant) / 1000)) : 0;
    }
    readonly property string texteExtinction: extinctionAnnuleeIci ? "Extinction annulée."
                                            : !extinction?.a ? "Ton PC s'éteindra à la fin de la mise à jour."
                                            : secondesExtinction > 0 ? "Ton PC s'éteint dans " + secondesExtinction + " s."
                                            : "Ton PC s'éteint…"
    readonly property string detailExtinction: extinctionAnnuleeIci
        ? (raisonAnnulation.startsWith("un jeu") ? "Ton PC reste allumé : " + raisonAnnulation + "." : "Ton PC restera allumé.")
        : extinction?.a ? "La mise à jour est terminée. Tu peux encore annuler l'extinction."
        : "Tu peux annuler l'extinction à tout moment ; un compte à rebours de 60 s la précédera."

    readonly property var etats: ({
        "vert": { "mot": "Tout va bien", "badge": "ok", "couleur": Kirigami.Theme.positiveTextColor },
        "orange": { "mot": "À regarder", "badge": "attention", "couleur": Kirigami.Theme.neutralTextColor },
        "rouge": { "mot": "Échec", "badge": "echec", "couleur": Kirigami.Theme.negativeTextColor },
        "en_cours": { "mot": "Mise à jour en cours", "badge": "en_cours", "couleur": Kirigami.Theme.highlightColor }
    })
    readonly property var nomsEtapes: ({
        "uupd": "Mise à jour du système",
        "maj-apps": "Mise à jour des outils",
        "notes": "Notes de version",
        "resume": "Résumé des nouveautés",
        "etat": "Bilan de santé",
        "extinction": "Extinction"
    })

    function lire() {
        if (lectureEnAttente)
            return;     // la lecture précédente n'est pas finie : ce tour est sauté
        lectureEnAttente = true;
        lecteur.connectSource(suiviRapide ? commandeSuivi : commandeLecture);
    }
    // Un fichier absent, vide ou illisible garde le dernier état valide.
    function recevoir(texte) {
        if (texte === dernierTexte)
            return;
        let donnees = null;
        try {
            donnees = JSON.parse(texte);
        } catch (e) {
            return;
        }
        if (donnees && typeof donnees === "object" && !Array.isArray(donnees)) {
            dernierTexte = texte;
            etat = donnees;
        }
    }
    function executer(commande) {
        erreur = "";
        commandes.connectSource(commande);
        toursRapides = toursApresAction;
    }
    // Spec 7.3 : si un jeu tourne, proposer d'attendre la fin de la partie (la CLI refuse sans --meme-si-jeu).
    function lancerMaj(eteindre, memeSiJeu) {
        confirmationExtinction = false;
        if (boutonsBloques)
            return;
        if (!memeSiJeu && jeu !== "") {
            jeuSignale = "";
            confirmationJeu = eteindre ? "eteindre" : "maj";
            return;
        }
        confirmationJeu = "";
        lancement = true;
        executer("centre-bazzite maj" + (eteindre ? " --eteindre" : "") + (memeSiJeu ? " --meme-si-jeu" : ""));
    }
    function annulerExtinction() {
        extinctionAnnulee = enCours?.debut ?? extinction?.a ?? "";
        executer("centre-bazzite annuler-extinction");
    }
    function ouvrirCentre() {
        commandes.connectSource("setsid -f centre-bazzite-fenetre >/dev/null 2>&1");
        root.expanded = false;
    }
    // « Dernière mise à jour : 14 h 52, Tout était déjà à jour. » (une session a eu lieu depuis la visite)
    function texteDerniereMaj(maj) {
        const d = maj?.heure ? new Date(maj.heure) : null;
        if (!d || isNaN(d.getTime()))
            return "";
        return "Dernière mise à jour : " + d.getHours() + " h " + String(d.getMinutes()).padStart(2, "0")
             + ", " + (maj.bilan ?? "");
    }
    function texteNombre(n) {
        n = Number(n) || 0;
        return n === 0 ? "Aucune mise à jour depuis ta dernière visite"
             : n === 1 ? "1 mise à jour depuis ta dernière visite"
             : n + " mises à jour depuis ta dernière visite";
    }
    function etapeActuelle() {
        const etapes = enCours?.etapes ?? {};
        for (const nom in etapes) {
            if (etapes[nom].statut === "en_cours")
                return (nomsEtapes[nom] ?? nom) + (etapes[nom].detail ? " : " + etapes[nom].detail : "");
        }
        return "";
    }

    Plasmoid.status: PlasmaCore.Types.ActiveStatus
    toolTipMainText: extinction?.a ? (extinctionAnnuleeIci ? "Extinction annulée" : "Extinction programmée")
                   : !etat ? "Health Hub"
                   : enCours?.global !== undefined ? "Mise à jour en cours : " + enCours.global + " %"
                   : (etat.phrase ?? "")
    toolTipSubText: extinctionPrevue ? texteExtinction
                  : !etat ? "État indisponible"
                  : (etat.phrase2 ?? "")

    onExpandedChanged: {
        if (root.expanded) {
            maintenant = new Date();
            lire();
        } else {
            confirmationExtinction = false;
            confirmationJeu = "";
        }
    }
    onEnCoursChanged: if (enCours?.debut) lancement = false
    onToursRapidesChanged: if (toursRapides === 0) lancement = false

    P5Support.DataSource {
        id: lecteur

        engine: "executable"
        onNewData: (source, donnees) => {
            disconnectSource(source);
            root.lectureEnAttente = false;
            if (donnees["exit code"] === 0)
                root.recevoir(donnees["stdout"] ?? "");
        }
    }
    P5Support.DataSource {
        id: commandes

        engine: "executable"
        onNewData: (source, donnees) => {
            disconnectSource(source);
            const code = donnees["exit code"];
            // 75 : la CLI refuse la mise à jour parce qu'un jeu a démarré depuis le dernier état.
            if (code === 75 && source.startsWith("centre-bazzite maj")) {
                const m = /Un jeu tourne \((.*)\)/.exec(String(donnees["stderr"] ?? ""));
                root.lancement = false;
                root.jeuSignale = m ? m[1] : "";
                root.confirmationJeu = source.includes("--eteindre") ? "eteindre" : "maj";
                return;
            }
            if (code !== undefined && code !== 0) {
                const lignes = String(donnees["stderr"] ?? "").trim().split("\n");
                root.erreur = "Échec de la commande : " + (lignes[lignes.length - 1] || "code de sortie " + code);
                // Rien n'a été lancé ni annulé : le panneau ne doit pas faire croire le contraire.
                root.lancement = false;
                if (source.includes("annuler-extinction"))
                    root.extinctionAnnulee = "";
            }
        }
    }
    Timer {
        // 30 s au repos ; 3 s pendant une mise à jour, un compte à rebours ou juste après une action.
        interval: root.suiviRapide ? 3000 : 30000
        running: true
        repeat: true
        triggeredOnStart: true
        onTriggered: {
            if (root.toursRapides > 0)
                root.toursRapides -= 1;
            root.lire();
        }
    }
    Timer {
        // Horloge du compte à rebours de l'extinction.
        interval: 1000
        running: !!root.extinction
        repeat: true
        onTriggered: root.maintenant = new Date()
    }

    compactRepresentation: MouseArea {
        id: compact

        readonly property real taillePastille: Math.max(6, Math.round(Math.min(width, height) * 0.4))

        hoverEnabled: true
        onClicked: root.expanded = !root.expanded
        Accessible.name: "Health Hub"
        Accessible.description: root.etatGlobal?.mot ?? "État indisponible"

        Kirigami.Icon {
            anchors.fill: parent
            // l'icône est livrée avec le paquet : elle ne dépend pas du thème d'icônes de plasmashell
            source: Qt.resolvedUrl("../icons/centre-bazzite-symbolic.svg")
            isMask: true
            color: Kirigami.Theme.textColor
            active: compact.containsMouse
        }
        // Pastille d'état dans le coin : vert, orange ou rouge ; un arc qui tourne pendant une mise à jour.
        Rectangle {
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            width: compact.taillePastille
            height: width
            radius: width / 2
            visible: !root.majEnCours && root.etatGlobal !== null
            color: root.etatGlobal?.couleur ?? "transparent"
            border.width: 1
            border.color: Kirigami.Theme.backgroundColor
        }
        Rectangle {
            // fond de l'arc, pour le détacher du dessin de l'icône
            anchors.fill: rouet
            radius: width / 2
            visible: rouet.visible
            color: Kirigami.Theme.backgroundColor
        }
        Shape {
            id: rouet

            anchors.right: parent.right
            anchors.bottom: parent.bottom
            width: compact.taillePastille + 2
            height: width
            visible: root.majEnCours
            preferredRendererType: Shape.CurveRenderer

            ShapePath {
                strokeColor: Kirigami.Theme.highlightColor
                strokeWidth: 2
                fillColor: "transparent"
                capStyle: ShapePath.RoundCap

                PathAngleArc {
                    centerX: rouet.width / 2
                    centerY: rouet.height / 2
                    radiusX: rouet.width / 2 - 1
                    radiusY: rouet.height / 2 - 1
                    startAngle: 0
                    sweepAngle: 270
                }
            }
            RotationAnimator on rotation {
                from: 0
                to: 360
                duration: 1000
                loops: Animation.Infinite
                running: rouet.visible
            }
        }
    }

    fullRepresentation: Item {
        id: panneau

        readonly property real marge: Kirigami.Units.largeSpacing

        Layout.preferredWidth: Kirigami.Units.gridUnit * 19      // ≈ 340 px, la largeur de la maquette
        Layout.minimumWidth: Layout.preferredWidth
        Layout.maximumWidth: Layout.preferredWidth
        Layout.preferredHeight: contenu.implicitHeight + 2 * marge
        Layout.minimumHeight: Layout.preferredHeight

        ColumnLayout {
            id: contenu

            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.margins: panneau.marge
            spacing: Kirigami.Units.smallSpacing

            // --- La phrase d'état et le nombre de mises à jour ---
            RowLayout {
                Layout.fillWidth: true
                spacing: Kirigami.Units.largeSpacing

                Kirigami.Heading {
                    Layout.fillWidth: true
                    Layout.alignment: Qt.AlignTop
                    level: 2
                    type: Kirigami.Heading.Type.Primary
                    text: root.etat ? (root.etat.phrase ?? "") : "État indisponible"
                    wrapMode: Text.WordWrap
                }
                Badge {
                    Layout.alignment: Qt.AlignTop
                    visible: root.etatGlobal !== null
                    texte: (root.majEnCours ? root.etats["en_cours"] : root.etatGlobal)?.mot ?? ""
                    etat: (root.majEnCours ? root.etats["en_cours"] : root.etatGlobal)?.badge ?? "neutre"
                }
            }
            PlasmaComponents3.Label {
                Layout.fillWidth: true
                text: root.etat ? root.texteNombre(root.etat.depuis_visite?.nombre)
                                : "Le fichier d'état est absent ou illisible. Il sera recréé au prochain relevé."
                color: Kirigami.Theme.disabledTextColor
                wrapMode: Text.WordWrap
            }
            PlasmaComponents3.Label {
                Layout.fillWidth: true
                visible: text !== ""
                text: root.etat ? root.texteDerniereMaj(root.etat.derniere_maj) : ""
                color: Kirigami.Theme.disabledTextColor
                wrapMode: Text.WordWrap
            }

            // --- Mise à jour en cours, extinction programmée ---
            Bandeau {
                Layout.topMargin: Kirigami.Units.smallSpacing
                visible: root.majEnCours && !root.extinction
                icone: "system-software-update"
                titre: root.enCours?.global !== undefined ? "Mise à jour en cours : " + root.enCours.global + " %"
                     : root.enCours?.unite ? "Une mise à jour système tourne déjà"
                     : "Lancement de la mise à jour…"
                texte: root.enCours?.unite ? "Bazzite se met à jour en arrière-plan." : root.etapeActuelle()
                progression: (root.enCours?.global ?? -100) / 100
                indetermine: root.enCours?.global === undefined
            }
            Bandeau {
                Layout.topMargin: Kirigami.Units.smallSpacing
                visible: root.extinctionPrevue
                icone: "system-shutdown"
                teinte: Kirigami.Theme.neutralTextColor
                titre: root.texteExtinction
                texte: root.detailExtinction

                PlasmaComponents3.Button {
                    visible: !root.extinctionAnnuleeIci
                    text: "Annuler l'extinction"
                    icon.name: "dialog-cancel"
                    onClicked: root.annulerExtinction()
                }
            }

            // --- Au plus trois points, chacun avec son état écrit ---
            ColumnLayout {
                Layout.fillWidth: true
                Layout.topMargin: Kirigami.Units.largeSpacing
                visible: root.etat !== null
                spacing: Kirigami.Units.smallSpacing

                RowLayout {
                    Layout.fillWidth: true
                    visible: root.aRegarder.length === 0
                    spacing: Kirigami.Units.smallSpacing

                    Kirigami.Icon {
                        implicitWidth: Kirigami.Units.iconSizes.smallMedium
                        implicitHeight: Kirigami.Units.iconSizes.smallMedium
                        source: "checkmark"
                        color: Kirigami.Theme.positiveTextColor
                    }
                    PlasmaComponents3.Label {
                        Layout.fillWidth: true
                        text: "Rien à regarder."
                    }
                }
                Repeater {
                    model: root.aRegarder.slice(0, 3)

                    delegate: Ligne {
                        required property var modelData

                        mot: modelData.gravite === "echec" ? "Échec" : "Attention"
                        etat: modelData.gravite === "echec" ? "echec" : "attention"
                        texte: modelData.titre ?? ""
                    }
                }
                PlasmaComponents3.Label {
                    readonly property int reste: root.aRegarder.length - 3

                    Layout.fillWidth: true
                    visible: reste > 0
                    text: "Et " + reste + (reste > 1 ? " autres points" : " autre point") + " dans Health Hub."
                    color: Kirigami.Theme.disabledTextColor
                    wrapMode: Text.WordWrap
                }
            }

            PlasmaComponents3.Label {
                Layout.fillWidth: true
                visible: root.erreur !== ""
                text: root.erreur
                color: Kirigami.Theme.negativeTextColor
                wrapMode: Text.WordWrap
            }

            // --- Les boutons ---
            RowLayout {
                Layout.fillWidth: true
                Layout.topMargin: Kirigami.Units.largeSpacing
                visible: !root.confirmationExtinction && root.confirmationJeu === ""
                spacing: Kirigami.Units.smallSpacing

                PlasmaComponents3.Button {
                    enabled: !root.boutonsBloques
                    highlighted: true
                    text: "Tout mettre à jour"
                    icon.name: "system-software-update"
                    onClicked: root.lancerMaj(false, false)
                }
                PlasmaComponents3.Button {
                    text: "Ouvrir Health Hub"
                    icon.name: "centre-bazzite"
                    onClicked: root.ouvrirCentre()
                }
            }
            PlasmaComponents3.Button {
                visible: !root.confirmationExtinction && root.confirmationJeu === ""
                enabled: !root.boutonsBloques
                flat: true
                text: "Mettre à jour et éteindre"
                icon.name: "system-shutdown"
                onClicked: root.confirmationExtinction = true
            }
            Bandeau {
                Layout.topMargin: Kirigami.Units.largeSpacing
                visible: root.confirmationExtinction
                icone: "system-shutdown"
                teinte: Kirigami.Theme.neutralTextColor
                titre: "Mettre à jour, puis éteindre ?"
                texte: "Ton PC s'éteindra à la fin de la mise à jour, après un compte à rebours de 60 s que tu pourras annuler."

                PlasmaComponents3.Button {
                    enabled: !root.boutonsBloques
                    text: "Mettre à jour et éteindre"
                    icon.name: "system-shutdown"
                    onClicked: root.lancerMaj(true, false)
                }
                PlasmaComponents3.Button {
                    flat: true
                    text: "Annuler"
                    onClicked: root.confirmationExtinction = false
                }
            }
            Bandeau {
                Layout.topMargin: Kirigami.Units.largeSpacing
                visible: root.confirmationJeu !== ""
                icone: "input-gaming"
                teinte: Kirigami.Theme.neutralTextColor
                titre: "Un jeu tourne (" + root.nomJeu + ") : lancer quand même ?"
                texte: "La mise à jour peut ralentir ta partie. Tu peux aussi attendre la fin de la partie, puis relancer."
                       + (root.confirmationJeu === "eteindre" ? " Ton PC ne s'éteindra pas tant qu'un jeu tourne." : "")

                PlasmaComponents3.Button {
                    text: "Lancer quand même"
                    icon.name: "system-software-update"
                    onClicked: root.lancerMaj(root.confirmationJeu === "eteindre", true)
                }
                PlasmaComponents3.Button {
                    flat: true
                    text: "Attendre"
                    onClicked: root.confirmationJeu = ""
                }
            }
        }
    }

    // Une ligne du panneau : le badge d'état écrit, puis le titre du point.
    component Ligne: RowLayout {
        id: ligne

        property string mot
        property string texte
        property string etat: "neutre"

        Layout.fillWidth: true
        spacing: Kirigami.Units.smallSpacing

        Badge {
            Layout.alignment: Qt.AlignTop
            Layout.preferredWidth: Kirigami.Units.gridUnit * 5
            texte: ligne.mot
            etat: ligne.etat
        }
        PlasmaComponents3.Label {
            Layout.fillWidth: true
            Layout.alignment: Qt.AlignTop
            text: ligne.texte
            wrapMode: Text.Wrap
            maximumLineCount: 2
            elide: Text.ElideRight
        }
    }

    // Encadré teinté (mise à jour en cours, extinction, confirmation) ; les boutons vont dessous, à droite.
    component Bandeau: Rectangle {
        id: bandeau

        property string icone
        property string titre
        property string texte
        property color teinte: Kirigami.Theme.highlightColor
        property real progression: -1           // de 0 à 1 ; négatif : pas de barre
        property bool indetermine: false
        default property alias boutons: zoneBoutons.data

        Layout.fillWidth: true
        implicitHeight: colonne.implicitHeight + 2 * Kirigami.Units.largeSpacing
        radius: Kirigami.Units.cornerRadius
        color: Qt.alpha(teinte, 0.1)
        border.width: 1
        border.color: Qt.alpha(teinte, 0.35)

        ColumnLayout {
            id: colonne

            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.margins: Kirigami.Units.largeSpacing
            spacing: Kirigami.Units.smallSpacing

            RowLayout {
                Layout.fillWidth: true
                spacing: Kirigami.Units.largeSpacing

                Kirigami.Icon {
                    Layout.alignment: Qt.AlignTop
                    implicitWidth: Kirigami.Units.iconSizes.smallMedium
                    implicitHeight: Kirigami.Units.iconSizes.smallMedium
                    source: bandeau.icone
                    color: bandeau.teinte
                }
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: Math.round(Kirigami.Units.smallSpacing / 2)

                    PlasmaComponents3.Label {
                        Layout.fillWidth: true
                        text: bandeau.titre
                        font.weight: Font.DemiBold
                        wrapMode: Text.WordWrap
                    }
                    PlasmaComponents3.Label {
                        Layout.fillWidth: true
                        visible: text !== ""
                        text: bandeau.texte
                        color: Kirigami.Theme.disabledTextColor
                        wrapMode: Text.WordWrap
                    }
                }
            }
            Progression {
                Layout.fillWidth: true
                visible: bandeau.indetermine || bandeau.progression >= 0
                valeur: bandeau.indetermine ? -1 : Math.max(0, bandeau.progression)
            }
            RowLayout {
                id: zoneBoutons

                Layout.alignment: Qt.AlignRight
                visible: children.length > 0
                spacing: Kirigami.Units.smallSpacing
            }
        }
    }
}
