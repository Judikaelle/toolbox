import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami
import "."

// Résumé de la santé (Task 19), d'un coup d'œil : ce qui est à regarder (rubrique sante), puis une ligne par domaine avec
// sa mesure clé et son état écrit (la pire gravité de ses points de santé actifs), le bilan de la semaine et, s'il y en a,
// les points mis en sourdine. Un clic sur une ligne ouvre son onglet ; celle du bilan ouvre Système, où vit son détail,
// celle des sourdines ouvre Journal, où chacun a « Signaler à nouveau ».
ColumnLayout {
    id: resume

    required property var page      // la page Santé : ses données et ses formats

    readonly property var sante: page.sante
    readonly property var bilan: sante.bilan_hebdo ?? null

    function pluriel(n, mot, mots) {
        return n + " " + (n > 1 ? mots : mot);
    }
    // « Marque SSD X9 PRO usé à 1 %, 35 °C · 3 erreurs d'E/S · /var/mnt/DONNEES non monté »
    function phraseDisques() {
        const parts = (sante.ssd ?? []).filter(d => d.sante).map(d => String(d.modele ?? "").split(" with ")[0]
            + " usé à " + page.pourcent(d.sante.usure) + ", " + page.degres(d.sante.temperature));
        const n = sante.erreurs_disque?.nombre ?? 0;
        if (n > 0)
            parts.push(pluriel(n, "erreur d'E/S", "erreurs d'E/S"));
        for (const chemin of sante.non_montes ?? [])
            parts.push(chemin + " non monté");
        if (parts.length > 0)
            return parts.join(" · ");
        return (sante.ssd ?? []).length === 0 ? "Disques pas encore mesurés" : "Santé non disponible par l'USB";
    }
    // « NVIDIA GeForce RTX 4070, 38 °C · Ollama arrêté · 9 gels »
    function phraseGpu() {
        const parts = [];
        if (sante.gpu)
            parts.push((sante.gpu.nom ?? "Carte graphique") + ", " + page.degres(sante.gpu.temperature));
        if (sante.ollama)
            parts.push(sante.ollama.actif ? "Ollama actif" : "Ollama arrêté");
        const gels = sante.gels?.nombre ?? 0;
        if (gels > 0)
            parts.push(pluriel(gels, "gel", "gels"));
        return parts.length > 0 ? parts.join(" · ") : "Carte graphique pas encore mesurée";
    }
    function phraseSysteme() {
        const services = sante.services_en_echec ?? null;
        if (services === null)
            return "Services pas encore vérifiés";
        if (services.length === 0)
            return "Aucun service en échec";
        return pluriel(services.length, "service en échec", "services en échec") + " : " + services.join(", ");
    }
    // « Image à jour · 0 runtime inutilisé », ou ce qui est disponible, ou ce qui n'a pas pu être vérifié.
    function phraseControles() {
        const c = page.controles;
        if (c === null)
            return "Contrôles pas encore faits";
        const parts = [c.image == null ? "Image non vérifiée"
                       : page.pointDe("maj:dispo:image:") ? "Bazzite " + (c.image.disponible ?? "") + " disponible"
                       : "Image à jour"];
        const flatpak = page.pointDe("maj:dispo:flatpak");
        if (flatpak)
            parts.push(Math.round(flatpak.mesure) + " Flatpak à mettre à jour");
        if (c.runtimes != null)
            parts.push(pluriel((c.runtimes.inutilises ?? []).length + (c.runtimes.gl_obsoletes ?? []).length,
                               "runtime inutilisé", "runtimes inutilisés"));
        return parts.join(" · ");
    }
    // « 15 erreurs · 23 plantages » (les erreurs comptées comme le point journal:erreurs).
    function phraseJournal() {
        const erreurs = (sante.erreurs_journal ?? []).reduce((total, e) => total + (e.nombre ?? 1), 0);
        return pluriel(erreurs, "erreur", "erreurs") + " · " + pluriel((sante.plantages ?? []).length, "plantage", "plantages");
    }

    readonly property var lignes: [
        { "cle": "disques", "phrase": phraseDisques() },
        { "cle": "gpu", "phrase": phraseGpu() },
        { "cle": "systeme", "phrase": phraseSysteme() },
        { "cle": "controles", "phrase": phraseControles() },
        { "cle": "journal", "phrase": phraseJournal() }
    ]

    objectName: "sante-onglet-resume"
    spacing: Style.gouttiere

    ARegarder {
        Layout.fillWidth: true
        rubrique: "sante"
    }

    Carte {
        objectName: "resume-domaines"
        Layout.fillWidth: true

        ColumnLayout {
            Layout.fillWidth: true
            spacing: Style.espace(1)

            Repeater {
                model: resume.lignes

                delegate: ColumnLayout {
                    id: rang

                    required property var modelData
                    required property int index
                    readonly property string etat: resume.page.etatDomaine(modelData.cle)

                    Layout.fillWidth: true
                    spacing: Style.espace(1)

                    Kirigami.Separator {
                        Layout.fillWidth: true
                        visible: rang.index > 0
                        color: Style.ligne
                    }
                    LigneResume {
                        cle: rang.modelData.cle
                        nom: resume.page.libelles[rang.modelData.cle]
                        phrase: rang.modelData.phrase
                        etat: rang.etat
                        mot: resume.page.motsEtat[rang.etat]
                        onClicked: resume.page.choisir(rang.modelData.cle)
                    }
                }
            }
            Kirigami.Separator {
                Layout.fillWidth: true
                color: Style.ligne
            }
            // Le bilan de la semaine : sa synthèse et sa semaine ; son détail est dans l'onglet Système.
            LigneResume {
                cle: "bilan"
                nom: "Bilan de la semaine"
                phrase: resume.bilan ? (resume.page.syntheseSemaine(resume.bilan.semaine) || "Le détail est dans Système.")
                                     : "Pas encore de bilan hebdomadaire."
                date: resume.bilan ? "Semaine du " + resume.page.jourCourt(resume.bilan.semaine?.du ?? resume.bilan.date) : ""
                onClicked: resume.page.choisir("systeme")
            }
            // Les points mis en sourdine : combien, lesquels ; leur liste (et « Signaler à nouveau ») est dans Journal.
            Kirigami.Separator {
                Layout.fillWidth: true
                visible: ligneSourdines.visible
                color: Style.ligne
            }
            LigneResume {
                id: ligneSourdines

                visible: resume.page.sourdines.length > 0
                cle: "sourdines"
                nom: resume.page.sourdines.length + " en sourdine"
                phrase: resume.page.sourdines.map(p => p.titre).join(" · ")
                onClicked: resume.page.choisir("journal")
            }
        }
    }

    // Une ligne du résumé : le nom du domaine, sa phrase, son état écrit (sauf le bilan, qui a sa semaine) ; un clic ouvre
    // son onglet.
    component LigneResume: Controls.AbstractButton {
        id: ligne

        property string cle
        property string nom
        property string phrase
        property string etat: ""
        property string mot: ""
        property string date: ""

        objectName: "resume-ligne-" + cle
        Layout.fillWidth: true
        hoverEnabled: true
        topPadding: Style.espace(2)
        bottomPadding: Style.espace(2)
        leftPadding: Style.espace(2)
        rightPadding: Style.espace(2)
        Accessible.role: Accessible.Button
        Accessible.name: nom + " : " + phrase + (mot !== "" ? ", " + mot : "") + ". Ouvre son onglet."

        contentItem: RowLayout {
            spacing: Style.espace(3)

            Controls.Label {
                objectName: "resume-nom-" + ligne.cle
                Layout.preferredWidth: Kirigami.Units.gridUnit * 8.5
                text: ligne.nom
                font.weight: Font.DemiBold
                elide: Text.ElideRight
            }
            TexteAbrege {
                objectName: "resume-phrase-" + ligne.cle
                Layout.fillWidth: true
                text: ligne.phrase
                color: Style.texteAttenue
            }
            Controls.Label {
                objectName: "resume-date-" + ligne.cle
                visible: ligne.date !== ""
                text: ligne.date
                color: Style.texteAttenue
                font.pointSize: Style.tailleMeta
            }
            // La place du badge le plus long : les phrases s'alignent d'une ligne à l'autre.
            Item {
                Layout.preferredWidth: plusLong.implicitWidth
                implicitHeight: plusLong.implicitHeight
                visible: ligne.date === ""

                Badge {
                    id: plusLong

                    visible: false
                    texte: "Attention"
                }
                Badge {
                    objectName: "resume-badge-" + ligne.cle
                    anchors.verticalCenter: parent.verticalCenter
                    visible: ligne.etat !== ""
                    texte: ligne.mot
                    etat: ligne.etat
                }
            }
            Kirigami.Icon {
                Layout.alignment: Qt.AlignVCenter
                implicitWidth: Kirigami.Units.iconSizes.small
                implicitHeight: implicitWidth
                source: "go-next-symbolic"
                color: ligne.hovered ? Style.texte : Style.texteDim
            }
        }
        background: Rectangle {
            radius: Style.rayonControle
            color: ligne.hovered || ligne.down ? Style.releve : "transparent"
            border.width: ligne.visualFocus ? 2 : 0
            border.color: Style.accent

            Behavior on color {
                ColorAnimation { duration: Style.dureeSurvol }
            }
        }
    }
}
