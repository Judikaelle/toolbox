import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami
import "."

// Accueil, « le brief du matin » : l'essentiel en une phrase, ce qui a changé, la santé, puis ce qui
// mérite un coup d'œil. Tout vient de pont.etat (etat.json) ; chaque action passe par la CLI.
Controls.ScrollView {
    id: accueil

    signal ouvrirPage(string nom)

    readonly property var etat: pont.etat
    readonly property var sante: etat.sante ?? {}
    readonly property var enCours: etat.en_cours ?? null
    // Le lancement des mises à jour vit dans Main.qml (menu et accueil passent par le même chemin).
    readonly property bool lancement: applicationWindow().lancement
    readonly property bool majEnCours: !!enCours || lancement
    readonly property bool boutonsBloques: applicationWindow().boutonsBloques
    // L'extinction prévue et son annulation vivent dans Main.qml (le menu la propose aussi).
    readonly property var extinction: applicationWindow().extinction
    readonly property bool extinctionPrevue: applicationWindow().extinctionPrevue
    readonly property bool extinctionAnnuleeIci: applicationWindow().extinctionAnnuleeIci
    readonly property var chronologie: etat.depuis_visite?.chronologie ?? []
    readonly property var points: etat.points ?? []
    // Le redémarrage a son bandeau : il n'est pas répété dans « À regarder ».
    readonly property var pointRedemarrage: points.find(p => estRedemarrage(p)) ?? null
    readonly property var aRegarder: points.filter(p => !p.en_sourdine && p.gravite !== "info"
                                                   && !estRedemarrage(p) && !masques.includes(p.id))
    // Mises à jour disponibles (contrôles en cache) : une pour l'image de Bazzite, une par Flatpak.
    readonly property int disponibles: points.filter(p => String(p.id).startsWith("maj:dispo:") && !p.en_sourdine)
        .reduce((n, p) => n + (String(p.id).startsWith("maj:dispo:image:") ? 1 : Math.max(1, Math.round(p.mesure ?? 1))), 0)

    // État local de la fenêtre : rien de tout ça n'est écrit sur le disque.
    property bool redemarrageReporte: false
    property var masques: []                  // points mis en sourdine depuis l'ouverture
    property date maintenant: new Date()

    readonly property real marge: Style.margePage
    readonly property var etatGlobal: Style.etatsGlobaux[etat.couleur] ?? null
    readonly property string modeJeu: etat.modejeu?.etat ?? ""
    // Le volume le plus serré (plus faible part d'espace libre) : c'est lui que la tuile « Espace libre » montre.
    readonly property var volumeSerre: (sante.volumes ?? []).reduce(
        (pire, v) => v.total_go > 0 && (pire === null || v.libre_go / v.total_go < pire.libre_go / pire.total_go) ? v : pire, null)
    readonly property real temperatureMax: Math.max(sante.temperatures?.cpu ?? -Infinity, sante.gpu?.temperature ?? -Infinity)
    readonly property var nomsEtapes: ({
        "uupd": "Mise à jour du système",
        "maj-apps": "Mise à jour des outils",
        "notes": "Notes de version",
        "resume": "Résumé des nouveautés",
        "etat": "Bilan de santé",
        "extinction": "Extinction"
    })

    function estRedemarrage(point) {
        return String(point.id).startsWith("redemarrage:");
    }
    function date(iso) {
        return Style.dateDe(iso);
    }
    function heure(d) {
        return Style.heure(d);
    }
    function jour(d) {
        return Style.jour(d, maintenant);
    }
    function nombre(x, decimales) {
        return Number(x).toLocaleString(Qt.locale("fr_FR"), "f", decimales);
    }
    function degres(x) {
        return x === undefined || x === null ? "—" : Math.round(x) + " °C";
    }
    // Ligne de résumé d'une étape de la frise : les résumés en français, sinon « avant → après ».
    function resumeEtape(entree) {
        if (entree.ligne)
            return entree.ligne;
        const resumes = etat.resumes ?? {};
        const changements = entree.changements ?? [];
        const textes = changements.filter(c => resumes[c.id]).map(c => resumes[c.id]);
        if (textes.length > 0)
            return textes.join(" ");
        return changements.map(c => versions(c, changements.length > 1)).filter(t => t !== "").join(" · ");
    }
    function versions(c, avecNom) {
        const t = c.de && c.vers ? c.de + " → " + c.vers
                : c.vers ? "nouveau, " + c.vers
                : c.de ? "retiré (" + c.de + ")" : "";
        return avecNom && t !== "" ? (c.nom || c.id) + " " + t : t;
    }
    function etapeActuelle() {
        const etapes = enCours?.etapes ?? {};
        for (const nom in etapes) {
            if (etapes[nom].statut === "en_cours")
                return (nomsEtapes[nom] ?? nom) + (etapes[nom].detail ? " : " + etapes[nom].detail : "");
        }
        return "";
    }
    // « Marque SSD X9 PRO 2TB » → « Marque X9 PRO » (et sans un éventuel « with heatsink … »).
    function nomCourt(modele) {
        return String(modele ?? "").replace(/\s+with heatsink.*$/i, "").replace(/\bSSD\b/g, "")
                                   .replace(/\s+\d+\s*[TG]B$/i, "").replace(/\s+/g, " ").trim();
    }
    function syntheseSante() {
        const morceaux = [];
        for (const d of sante.ssd ?? []) {
            if (d.sante && d.sante.usure !== undefined && d.sante.usure !== null)
                morceaux.push("SSD " + nomCourt(d.modele) + " usé à " + d.sante.usure + " %");
        }
        const services = sante.services_en_echec;
        if (services)
            morceaux.push(services.length === 0 ? "Aucun service en échec"
                          : services.length + (services.length > 1 ? " services en échec" : " service en échec"));
        return morceaux.length > 0 ? morceaux.join(". ") + "." : "";
    }
    function volumeEnAlerte(chemin) {
        return points.some(p => p.id === "volume:" + chemin && !p.en_sourdine && !masques.includes(p.id));
    }
    // État d'un volume pour la jauge et la tuile. Même règle que centre_bazzite/stockage.py (_etat), qui fait référence : à changer des deux côtés :
    // « echec » sous 5 % d'espace libre, sinon « attention » si le point volume:<chemin> est actif, sinon « ok ».
    function etatVolume(v) {
        if (v.total_go > 0 && v.libre_go / v.total_go < 0.05)
            return "echec";
        return volumeEnAlerte(v.chemin) ? "attention" : "ok";
    }
    function libreCourt(go) {
        return Number(Math.round(go)).toLocaleString(Qt.locale("fr_FR"), "f", 0) + " Go";
    }
    function nePlusSignaler(point) {
        masques = masques.concat([point.id]);
        pont.sourdine(point.id);
        applicationWindow().showPassiveNotification("« " + point.titre + " » ne sera plus signalé, sauf s'il empire.",
                                                     "long", "Annuler", () => {
            masques = masques.filter(id => id !== point.id);
            pont.sansSourdine(point.id);
        });
    }
    contentWidth: availableWidth
    contentHeight: colonne.implicitHeight + 2 * marge
    Controls.ScrollBar.horizontal.policy: Controls.ScrollBar.AlwaysOff

    Timer {
        // Horloge des libellés (« hier », compte à rebours de l'extinction).
        interval: accueil.extinction ? 1000 : 60000
        running: true
        repeat: true
        onTriggered: accueil.maintenant = new Date()
    }
    Dialogue {
        id: confirmationRedemarrage

        title: "Redémarrer maintenant ?"
        subtitle: "Les applications ouvertes vont se fermer : enregistre ton travail avant."
        standardButtons: Kirigami.Dialog.NoButton
        customFooterActions: [
            Kirigami.Action {
                text: "Redémarrer"
                icon.name: "system-reboot"
                onTriggered: {
                    confirmationRedemarrage.close();
                    if (!accueil.enCours)       // jamais pendant une mise à jour (elle serait coupée)
                        pont.redemarrer();
                }
            },
            Kirigami.Action {
                text: "Annuler"
                icon.name: "dialog-cancel"
                onTriggered: confirmationRedemarrage.close()
            }
        ]
    }

    ColumnLayout {
        id: colonne

        x: accueil.marge
        y: accueil.marge * 0.75
        width: accueil.availableWidth - 2 * accueil.marge
        spacing: Style.gouttiere

        // --- Le bandeau d'accueil : l'état (dans son badge), la phrase, les boutons ---
        Carte {
            id: bandeauEtat

            objectName: "bandeau-accueil"
            Layout.fillWidth: true
            halo: true

            Flow {
                Layout.fillWidth: true
                spacing: Style.espace(2)

                Badge {
                    objectName: "badge-etat"
                    visible: accueil.etatGlobal !== null
                    texte: accueil.etatGlobal?.mot ?? ""
                    etat: accueil.etatGlobal?.badge ?? "neutre"
                }
                // Le mode jeu, seulement quand il agit ou qu'il attend de remettre le bureau comme avant (Task 6).
                Badge {
                    objectName: "badge-modejeu"
                    // UI-m7 : la phrase entière, à la ligne plutôt que hors du bandeau.
                    largeurMax: parent.width
                    visible: accueil.modeJeu === "actif" || accueil.modeJeu === "interrompu"
                    texte: accueil.etat.modejeu?.phrase ?? ""
                    etat: accueil.modeJeu === "interrompu" ? "attention" : "info"
                }
            }
            Kirigami.Heading {
                Layout.fillWidth: true
                level: 1
                type: Kirigami.Heading.Type.Primary
                font.pointSize: Style.tailleBandeau
                font.weight: Font.Bold
                text: accueil.etat.phrase ?? "Premier relevé en cours…"
                wrapMode: Text.WordWrap
            }
            Controls.Label {
                Layout.fillWidth: true
                visible: text !== ""
                text: accueil.etat.phrase2 ?? "Les informations arrivent dans un instant."
                color: Style.texteAttenue
                font.pointSize: Style.tailleCorps
                wrapMode: Text.WordWrap
            }
            Controls.Label {
                objectName: "verification-accueil"
                text: Style.derniereVerification(accueil.etat.genere, accueil.maintenant)
                color: Style.texteAttenue
                font.pointSize: Style.tailleMeta
            }
            Flow {
                Layout.fillWidth: true
                spacing: Style.espace(2)

                BoutonPrincipal {
                    objectName: "bouton-principal"
                    enabled: !accueil.boutonsBloques
                    text: "Tout mettre à jour"
                    raccourci: "Ctrl+U"
                    Accessible.name: text + " (Ctrl+U)"
                    onClicked: applicationWindow().demanderMaj(false)
                }
                Bouton {
                    enabled: !accueil.boutonsBloques
                    text: "Mettre à jour et éteindre"
                    icon.name: "system-shutdown"
                    onClicked: applicationWindow().demanderMaj(true)
                }
            }
        }

        // --- Quatre tuiles ---
        GridLayout {
            objectName: "grille-tuiles"
            Layout.fillWidth: true
            columns: colonne.width >= Kirigami.Units.gridUnit * 40 ? 4 : 2
            columnSpacing: Style.gouttiere
            rowSpacing: Style.gouttiere
            uniformCellWidths: true

            Tuile {
                readonly property int changements: accueil.etat.depuis_visite?.nombre ?? 0

                objectName: "tuile-majs"
                Layout.fillWidth: true
                Layout.fillHeight: true
                icone: "view-refresh"
                // Les changements depuis la visite d'abord ; sinon, les mises à jour disponibles (jamais « À jour »
                // quand il y en a), que le badge signale dans les deux cas.
                valeur: changements > 0 ? String(changements) : accueil.disponibles > 0 ? String(accueil.disponibles) : "À jour"
                legende: changements > 0 ? "depuis ta dernière visite" : accueil.disponibles > 0 ? "à installer" : "Rien de nouveau"
                etat: accueil.disponibles > 0 ? "info" : ""
                badgeTexte: "Disponibles"
            }
            Tuile {
                objectName: "tuile-espace"
                Layout.fillWidth: true
                Layout.fillHeight: true
                icone: "drive-harddisk"
                valeur: accueil.volumeSerre ? accueil.libreCourt(accueil.volumeSerre.libre_go) : "—"
                legende: accueil.volumeSerre ? "libres sur " + (accueil.volumeSerre.nom ?? accueil.volumeSerre.chemin) : "Pas encore mesurés"
                etat: accueil.volumeSerre && accueil.etatVolume(accueil.volumeSerre) !== "ok" ? accueil.etatVolume(accueil.volumeSerre) : ""
                badgeTexte: "Peu d'espace libre"
            }
            Tuile {
                objectName: "tuile-temperatures"
                Layout.fillWidth: true
                Layout.fillHeight: true
                icone: "temperature-normal"
                valeur: isFinite(accueil.temperatureMax) ? Math.round(accueil.temperatureMax) + " °C" : "—"
                legende: isFinite(accueil.temperatureMax)
                         ? "GPU " + accueil.degres(accueil.sante.gpu?.temperature) + " · CPU " + accueil.degres(accueil.sante.temperatures?.cpu)
                         : "Pas encore mesurées"
            }
            Tuile {
                objectName: "tuile-etat"
                Layout.fillWidth: true
                Layout.fillHeight: true
                icone: "dialog-information"
                valeur: accueil.aRegarder.length === 0 ? "Rien" : accueil.aRegarder.length + (accueil.aRegarder.length > 1 ? " points" : " point")
                legende: "à regarder"
                etat: accueil.etatGlobal?.badge ?? ""
                badgeTexte: accueil.etatGlobal?.mot ?? ""
            }
        }

        // --- Bandeaux ---
        Bandeau {
            visible: accueil.majEnCours
            icone: "system-software-update"
            titre: accueil.enCours?.global !== undefined ? "Mise à jour en cours : " + accueil.enCours.global + " %"
                 : accueil.enCours?.unite ? "Une mise à jour système tourne déjà"
                 : "Lancement de la mise à jour…"
            texte: accueil.enCours?.unite
                   ? "Bazzite se met à jour en arrière-plan (" + accueil.enCours.unite + "). « Tout mettre à jour » la suivra, puis fera le reste."
                   : (accueil.etapeActuelle() || "Tu peux continuer à utiliser ton PC.")
            progression: (accueil.enCours?.global ?? -100) / 100
            indetermine: accueil.enCours?.global === undefined

            Bouton {
                flat: true
                text: "Voir le détail"
                onClicked: accueil.ouvrirPage("majs")
            }
        }

        Bandeau {
            id: bandeauExtinction

            readonly property bool compteARebours: !!accueil.extinction?.a
            readonly property int secondes: Math.max(0, Math.round((accueil.date(accueil.extinction?.a) - accueil.maintenant) / 1000))
            readonly property bool annulee: accueil.extinctionAnnuleeIci
            readonly property string raison: accueil.enCours?.etapes?.extinction?.detail ?? ""

            visible: accueil.extinctionPrevue
            icone: "system-shutdown"
            teinte: Style.attention
            titre: annulee ? "Extinction annulée."
                 : !compteARebours ? "Ton PC s'éteindra à la fin de la mise à jour."
                 : secondes > 0 ? "Ton PC s'éteint dans " + secondes + " s." : "Ton PC s'éteint…"
            texte: annulee ? (raison.startsWith("un jeu") ? "Ton PC reste allumé : " + raison + "." : "Ton PC restera allumé.")
                 : compteARebours ? "La mise à jour est terminée. Tu peux encore annuler l'extinction."
                 : "Tu peux annuler l'extinction à tout moment ; un compte à rebours de 60 s la précédera."

            Bouton {
                visible: !bandeauExtinction.annulee
                text: "Annuler l'extinction"
                icon.name: "dialog-cancel"
                onClicked: {
                    applicationWindow().annulerExtinction();
                }
            }
        }

        Bandeau {
            readonly property string version: accueil.pointRedemarrage ? String(accueil.pointRedemarrage.id).slice("redemarrage:".length) : ""

            visible: !!accueil.etat.redemarrage && !accueil.redemarrageReporte
            icone: "system-reboot"
            titre: version !== "" ? "Bazzite " + version + " est prête." : "Une nouvelle version de Bazzite est prête."
            // Redémarrer pendant une mise à jour la couperait : le bouton attend la fin.
            texte: accueil.enCours ? "Elle s'appliquera au prochain redémarrage. Attends la fin de la mise à jour en cours avant de redémarrer."
                                   : "Elle s'appliquera au prochain redémarrage."

            Bouton {
                flat: true
                text: "Plus tard"
                onClicked: accueil.redemarrageReporte = true
            }
            Bouton {
                visible: !accueil.enCours
                text: "Redémarrer"
                icon.name: "system-reboot"
                onClicked: confirmationRedemarrage.open()
            }
        }

        // --- Depuis ta dernière visite | Santé ---
        GridLayout {
            Layout.fillWidth: true
            columns: colonne.width >= Kirigami.Units.gridUnit * 40 ? 2 : 1
            columnSpacing: Style.gouttiere
            rowSpacing: Style.gouttiere

            Carte {
                Layout.fillWidth: true
                Layout.preferredWidth: 11
                Layout.alignment: Qt.AlignTop
                titre: "Depuis ta dernière visite"

                EtatVide {
                    objectName: "vide-visite"
                    Layout.fillWidth: true
                    visible: accueil.chronologie.length === 0
                    icone: "checkmark"
                    texte: "Rien de nouveau depuis ta dernière visite."
                }
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 0

                    Repeater {
                        model: accueil.chronologie

                        delegate: Item {
                            id: etape

                            required property var modelData
                            required property int index
                            readonly property bool derniere: index === accueil.chronologie.length - 1
                            readonly property var quand: accueil.date(modelData.heure)
                            readonly property real colonneTexte: Kirigami.Units.gridUnit * 4.5

                            Layout.fillWidth: true
                            implicitHeight: textes.implicitHeight + (derniere ? 0 : Kirigami.Units.largeSpacing * 2)

                            ColumnLayout {
                                width: etape.colonneTexte - Kirigami.Units.gridUnit * 1.25
                                spacing: 0

                                Controls.Label {
                                    text: etape.quand ? accueil.heure(etape.quand) : ""
                                    color: Style.texteAttenue
                                    font.pointSize: Style.tailleMeta
                                    font.features: ({ "tnum": 1 })
                                }
                                Controls.Label {
                                    visible: text !== ""
                                    text: etape.quand ? accueil.jour(etape.quand) : ""
                                    color: Style.texteAttenue
                                    font.pointSize: Style.tailleMeta
                                }
                            }
                            Rectangle {
                                id: pastille

                                x: etape.colonneTexte - Kirigami.Units.gridUnit
                                y: Math.round((titreEtape.implicitHeight - height) / 2)
                                width: Kirigami.Units.smallSpacing * 2
                                height: width
                                radius: width / 2
                                color: Style.accent
                            }
                            Rectangle {
                                visible: !etape.derniere
                                x: pastille.x + pastille.width / 2
                                y: pastille.y + pastille.height + Kirigami.Units.smallSpacing
                                width: 1
                                height: etape.height - pastille.height - 2 * Kirigami.Units.smallSpacing
                                color: Style.ligne2
                            }
                            ColumnLayout {
                                id: textes

                                x: etape.colonneTexte
                                width: etape.width - x
                                spacing: Math.round(Kirigami.Units.smallSpacing / 2)

                                Controls.Label {
                                    id: titreEtape

                                    Layout.fillWidth: true
                                    text: etape.modelData.titre ?? ""
                                    font.weight: Font.DemiBold
                                    elide: Text.ElideRight
                                }
                                Controls.Label {
                                    Layout.fillWidth: true
                                    visible: text !== ""
                                    text: accueil.resumeEtape(etape.modelData)
                                    color: Style.texteAttenue
                                    wrapMode: Text.WordWrap
                                    maximumLineCount: 2
                                    elide: Text.ElideRight
                                }
                            }
                            HoverHandler {
                                cursorShape: Qt.PointingHandCursor
                            }
                            TapHandler {
                                onTapped: accueil.ouvrirPage("majs")
                            }
                        }
                    }
                }
            }

            Carte {
                Layout.fillWidth: true
                Layout.preferredWidth: 9
                Layout.alignment: Qt.AlignTop
                titre: "Santé"

                Controls.Label {
                    visible: (accueil.sante.volumes ?? []).length === 0
                    text: "Volumes pas encore mesurés."
                    color: Style.texteAttenue
                }
                Repeater {
                    model: accueil.sante.volumes ?? []

                    delegate: Jauge {
                        required property var modelData

                        objectName: "jauge-" + modelData.chemin
                        Layout.fillWidth: true
                        nom: modelData.nom ?? modelData.chemin
                        libreGo: modelData.libre_go ?? 0
                        totalGo: modelData.total_go ?? 0
                        etat: accueil.etatVolume(modelData)
                    }
                }
                Controls.Label {
                    Layout.fillWidth: true
                    visible: text !== ""
                    text: accueil.syntheseSante()
                    color: Style.texteAttenue
                    wrapMode: Text.WordWrap
                }
            }
        }

        // --- À regarder ---
        Carte {
            Layout.fillWidth: true
            titre: "À regarder"

            EtatVide {
                objectName: "vide-points"
                Layout.fillWidth: true
                visible: accueil.aRegarder.length === 0
                icone: "checkmark"
                texte: "Rien à regarder pour l'instant."
            }
            ColumnLayout {
                Layout.fillWidth: true
                spacing: 0

                Repeater {
                    model: accueil.aRegarder

                    delegate: ColumnLayout {
                        id: rangPoint

                        required property var modelData
                        required property int index

                        Layout.fillWidth: true
                        spacing: 0

                        Kirigami.Separator {
                            Layout.fillWidth: true
                            color: Style.ligne
                            visible: rangPoint.index > 0
                        }
                        PointLigne {
                            Layout.fillWidth: true
                            Layout.topMargin: Style.espace(3)
                            Layout.bottomMargin: Style.espace(3)
                            point: rangPoint.modelData
                            onAgir: pont.agir(rangPoint.modelData.id)
                            onNePlusSignaler: accueil.nePlusSignaler(rangPoint.modelData)
                        }
                    }
                }
            }
        }
    }

    // Bandeau teinté (redémarrage, mise à jour en cours, extinction) ; les boutons vont à droite.
    component Bandeau: Rectangle {
        id: bandeau

        property string icone
        property string titre
        property string texte
        property color teinte: Style.accent
        property real progression: -1           // de 0 à 1 ; négatif : pas de barre
        property bool indetermine: false
        default property alias boutons: zoneBoutons.data

        Layout.fillWidth: true
        implicitHeight: rangee.implicitHeight + 2 * Kirigami.Units.largeSpacing
        radius: Style.rayonCarte
        color: Style.teinteFond(teinte)
        border.width: 1
        border.color: Style.teinteBordure(teinte)

        RowLayout {
            id: rangee

            anchors.fill: parent
            anchors.margins: Kirigami.Units.largeSpacing
            anchors.leftMargin: Kirigami.Units.largeSpacing * 1.5
            spacing: Kirigami.Units.largeSpacing * 1.5

            Kirigami.Icon {
                Layout.alignment: Qt.AlignVCenter
                implicitWidth: Kirigami.Units.iconSizes.smallMedium
                implicitHeight: Kirigami.Units.iconSizes.smallMedium
                source: bandeau.icone
                color: bandeau.teinte
            }
            ColumnLayout {
                Layout.fillWidth: true
                spacing: Math.round(Kirigami.Units.smallSpacing / 2)

                Controls.Label {
                    Layout.fillWidth: true
                    text: bandeau.titre
                    font.weight: Font.DemiBold
                    wrapMode: Text.WordWrap
                }
                Controls.Label {
                    Layout.fillWidth: true
                    visible: text !== ""
                    text: bandeau.texte
                    color: Style.texteAttenue
                    wrapMode: Text.WordWrap
                }
                Progression {
                    Layout.fillWidth: true
                    Layout.topMargin: Style.espace(1)
                    visible: bandeau.indetermine || bandeau.progression >= 0
                    valeur: bandeau.indetermine ? -1 : Math.max(0, bandeau.progression)
                    teinte: bandeau.teinte
                }
            }
            RowLayout {
                id: zoneBoutons

                Layout.alignment: Qt.AlignVCenter
                spacing: Kirigami.Units.smallSpacing
            }
        }
    }
}
