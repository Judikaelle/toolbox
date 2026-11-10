import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami
import "."

// L'onglet Bibliothèques : tous les jeux relevés, filtrés par bibliothèque (ou les doublons) et triés par taille, par
// dernière partie ou par nom. Le filtre est gardé par la fenêtre (filtreJeux) : une ligne de la vue d'ensemble le pose.
// La liste défile dans sa propre zone, bornée au reste de l'écran ; une bibliothèque absente est dite en toutes lettres.
ColumnLayout {
    id: onglet

    required property var page      // la page Jeux : ses données et ses formats

    readonly property var tous: page.jeux.jeux ?? []
    readonly property string demande: applicationWindow().filtreJeux
    // Le filtre montré : celui que la fenêtre garde, s'il désigne encore quelque chose ; sinon toutes les bibliothèques.
    readonly property string filtre: demande === "doublons" || page.bibliotheques.some(b => b.id === demande) ? demande : ""
    readonly property bool doublons: filtre === "doublons"
    property string ordre: "taille"         // le tri choisi : taille, partie ou nom
    readonly property var tris: [{ "cle": "taille", "libelle": "Taille" }, { "cle": "partie", "libelle": "Dernière partie" },
                                 { "cle": "nom", "libelle": "Nom" }]
    readonly property var noms: page.bibliotheques.reduce((m, b) => Object.assign(m, { [b.id]: b.nom ?? b.id }), {})
    readonly property var types: page.bibliotheques.reduce((m, b) => Object.assign(m, { [b.id]: b.type ?? "" }), {})
    readonly property var parId: tous.reduce((m, j) => Object.assign(m, { [j.id]: j }), {})
    readonly property var filtres: tous.filter(j => filtre === "" || j.bibliotheque === filtre)
    readonly property var lignes: doublons ? page.doublons : trier(filtres, ordre)
    readonly property real total: filtres.reduce((t, j) => t + (j.octets ?? 0), 0)
    readonly property real enTrop: page.doublons.reduce((t, d) => t + (d.en_trop ?? 0), 0)

    function choisirFiltre(cle) {
        applicationWindow().filtreJeux = cle;
    }
    // Les inconnues (taille ou dernière partie) en dernier ; à égalité, par titre.
    function trier(liste, cle) {
        const titre = (a, b) => String(a.titre ?? "").localeCompare(String(b.titre ?? ""), "fr");
        const copie = liste.slice();
        if (cle === "nom")
            return copie.sort((a, b) => titre(a, b) || String(onglet.noms[a.bibliotheque] ?? "").localeCompare(String(onglet.noms[b.bibliotheque] ?? ""), "fr"));
        const valeur = cle === "partie" ? (j => j.derniere_partie ? Style.dateDe(j.derniere_partie)?.getTime() ?? null : null)
                                        : (j => j.octets ?? null);
        return copie.sort((a, b) => {
            const va = valeur(a), vb = valeur(b);
            if (va === null || vb === null)
                return va === null && vb === null ? titre(a, b) : va === null ? 1 : -1;
            return vb - va || titre(a, b);
        });
    }
    // « Jamais » pour Steam (une partie se note toujours), « Inconnue » ailleurs.
    function partie(j) {
        if (!j.derniere_partie)
            return j.type === "steam" ? "Jamais" : "Inconnue";
        return onglet.page.jourCourt(j.derniere_partie) || "Inconnue";
    }

    objectName: "jeux-bibliotheques"
    spacing: Style.gouttiere

    EtatVide {
        objectName: "jeux-vide"
        Layout.fillWidth: true
        visible: !onglet.page.releve
        icone: "applications-games"
        texte: onglet.page.texteVide
    }

    Carte {
        id: carte

        objectName: "bibliotheques-carte"
        Layout.fillWidth: true
        visible: onglet.page.releve

        RowLayout {
            Layout.fillWidth: true
            spacing: Style.espace(3)

            Kirigami.Heading {
                objectName: "bibliotheques-entete"
                Layout.fillWidth: true
                level: 2
                font.pointSize: Style.tailleTitreCarte
                font.weight: Font.Bold
                text: onglet.doublons
                      ? onglet.page.pluriel(onglet.page.doublons.length, "jeu en double", "jeux en double") + " · "
                        + Style.taille(onglet.enTrop) + " en trop"
                      : onglet.page.pluriel(onglet.filtres.length, "jeu", "jeux") + " · " + Style.taille(onglet.total) + " au total"
                elide: Text.ElideRight
            }
            Controls.Label {
                visible: !onglet.doublons
                text: "Trier par"
                color: Style.texteAttenue
                font.pointSize: Style.tailleMeta
            }
            Controls.ComboBox {
                id: tri

                // `choisir` : le tri par sa clé (taille, partie, nom), comme un choix dans la liste.
                function choisir(cle) {
                    onglet.ordre = cle;
                }

                objectName: "tri"
                visible: !onglet.doublons
                model: onglet.tris.map(t => t.libelle)
                currentIndex: Math.max(0, onglet.tris.findIndex(t => t.cle === onglet.ordre))
                onActivated: index => choisir(onglet.tris[index].cle)
                Accessible.name: "Trier par " + currentText
            }
        }

        // Les filtres : toutes, les doublons, puis une pastille par bibliothèque.
        Flow {
            Layout.fillWidth: true
            spacing: Style.espace(1.5)

            Filtre {
                cle: "toutes"
                valeur: ""
                texte: "Toutes"
            }
            Filtre {
                cle: "doublons"
                valeur: "doublons"
                texte: "Doublons"
            }
            Repeater {
                model: onglet.page.bibliotheques

                delegate: Filtre {
                    required property var modelData

                    cle: modelData.id ?? ""
                    valeur: modelData.id ?? ""
                    texte: modelData.nom ?? ""
                }
            }
        }

        // Une bibliothèque absente (disque débranché) : dite en toutes lettres, avec toutes ou quand on la choisit.
        Repeater {
            model: onglet.page.bibliotheques.filter(b => b.absente)

            delegate: Controls.Label {
                required property var modelData

                objectName: "absente-" + (modelData.id ?? "")
                Layout.fillWidth: true
                visible: onglet.filtre === "" || onglet.filtre === modelData.id
                text: (modelData.nom ?? "") + " : absente (disque débranché ?)"
                color: Style.texteAttenue
                wrapMode: Text.WordWrap
            }
        }

        ListView {
            id: liste

            objectName: "liste-jeux"
            Layout.fillWidth: true
            // Bornée au reste de l'écran (la page tient sur un écran) : la carte au-dessus, sa marge, puis sa marge du bas.
            Layout.preferredHeight: Math.min(contentHeight, Math.max(Kirigami.Units.gridUnit * 6,
                onglet.page.hauteurOnglet - carte.y - liste.y - 2 * Style.margeCarte))
            clip: true
            interactive: contentHeight > height
            boundsBehavior: Flickable.StopAtBounds
            model: onglet.lignes
            Controls.ScrollBar.vertical: Controls.ScrollBar {
                policy: Controls.ScrollBar.AsNeeded
            }

            delegate: ColumnLayout {
                id: rang

                required property var modelData
                required property int index
                readonly property string jid: modelData.id ?? ""

                width: ListView.view.width - Style.espace(3)
                spacing: 0

                Kirigami.Separator {
                    Layout.fillWidth: true
                    visible: rang.index > 0
                    color: Style.ligne
                }
                // Un jeu : titre, bibliothèque, taille, dernière partie.
                RowLayout {
                    Layout.fillWidth: true
                    Layout.topMargin: Style.espace(1.5)
                    Layout.bottomMargin: Style.espace(1.5)
                    visible: !onglet.doublons
                    spacing: Style.espace(3)

                    TexteAbrege {
                        objectName: "jeu-titre-" + rang.jid
                        Layout.fillWidth: true
                        text: rang.modelData.titre ?? ""
                        font.weight: Font.DemiBold
                    }
                    Badge {
                        objectName: "jeu-bibliotheque-" + rang.jid
                        texte: onglet.noms[rang.modelData.bibliotheque] ?? ""
                        etat: "neutre"
                        point: false
                    }
                    Controls.Label {
                        objectName: "jeu-taille-" + rang.jid
                        Layout.preferredWidth: Kirigami.Units.gridUnit * 4
                        horizontalAlignment: Text.AlignRight
                        text: rang.modelData.taille ?? ""
                        font.features: ({ "tnum": 1 })
                    }
                    Controls.Label {
                        objectName: "jeu-partie-" + rang.jid
                        Layout.preferredWidth: Kirigami.Units.gridUnit * 5
                        horizontalAlignment: Text.AlignRight
                        text: onglet.doublons ? "" : onglet.partie(rang.modelData)
                        color: Style.texteAttenue
                        font.features: ({ "tnum": 1 })
                    }
                }
                // Un doublon : son titre, ce qu'il prend en trop, puis une ligne par copie.
                ColumnLayout {
                    Layout.fillWidth: true
                    Layout.topMargin: Style.espace(1.5)
                    Layout.bottomMargin: Style.espace(1.5)
                    visible: onglet.doublons
                    spacing: Style.espace(0.5)

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: Style.espace(3)

                        TexteAbrege {
                            objectName: onglet.doublons ? "doublon-titre-" + (rang.modelData.titre ?? "") : ""
                            Layout.fillWidth: true
                            text: rang.modelData.titre ?? ""
                            font.weight: Font.DemiBold
                        }
                        Controls.Label {
                            objectName: onglet.doublons ? "doublon-trop-" + (rang.modelData.titre ?? "") : ""
                            text: (rang.modelData.taille_en_trop ?? "") + " en trop"
                            color: Style.attention
                            font.weight: Font.DemiBold
                        }
                    }
                    Repeater {
                        model: onglet.doublons ? (rang.modelData.jeux ?? []) : []

                        delegate: Controls.Label {
                            required property var modelData
                            readonly property var copie: onglet.parId[modelData] ?? ({})

                            objectName: "doublon-copie-" + modelData
                            Layout.fillWidth: true
                            Layout.leftMargin: Style.espace(3)
                            text: (onglet.noms[copie.bibliotheque] ?? copie.bibliotheque ?? "") + " · " + (copie.taille ?? "")
                            color: Style.texteAttenue
                            elide: Text.ElideRight
                        }
                    }
                }
            }
        }
    }

    // Une pastille de filtre : cochée quand elle est le filtre montré.
    component Filtre: Controls.AbstractButton {
        id: filtre

        property string cle
        property string valeur
        property string texte

        objectName: "filtre-" + cle
        checkable: true
        checked: onglet.filtre === valeur
        hoverEnabled: true
        text: texte
        topPadding: Style.espace(1)
        bottomPadding: Style.espace(1)
        leftPadding: Style.espace(3)
        rightPadding: Style.espace(3)
        Accessible.role: Accessible.RadioButton
        Accessible.name: texte
        onClicked: {
            onglet.choisirFiltre(valeur);
            checked = Qt.binding(() => onglet.filtre === valeur);
        }

        contentItem: Controls.Label {
            text: filtre.texte
            color: filtre.checked ? Style.accent : filtre.hovered ? Style.texte : Style.texteAttenue
            font.weight: Font.DemiBold
            font.pointSize: Style.tailleMeta
        }
        background: Rectangle {
            radius: height / 2
            color: filtre.checked ? Style.teinteFond(Style.accent) : filtre.hovered ? Style.releve : "transparent"
            border.width: filtre.visualFocus ? 2 : 1
            border.color: filtre.checked || filtre.visualFocus ? Style.teinteBordure(Style.accent) : Style.ligne2
        }
    }
}
