import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami
import "."

// L'onglet Durée : ce qui est à regarder (le point « démarrage plus lent »), la durée découpée en phases et comparée aux
// démarrages précédents, ce qui ralentit le plus (une phrase de français pour chacun), puis ce qui tourne en arrière-plan
// sans retarder le bureau (une unité de ta session porte « (session) »). Tant que le démarrage n'est pas fini, la durée
// n'existe pas : on le dit.
ColumnLayout {
    id: onglet

    required property var page      // la page Démarrage : ses données

    readonly property var duree: page.duree
    readonly property var phases: duree?.phases ?? []
    readonly property real somme: phases.reduce((t, p) => t + p.secondes, 0)
    // Les badges des ralentisseurs : un mot, et l'état qui le colore.
    readonly property var mots: ({
        "bureau": { "mot": "Retarde le bureau", "etat": "attention" },
        "initrd": { "mot": "Pendant l'initrd", "etat": "neutre" },
        "fond": { "mot": "En arrière-plan", "etat": "neutre" }
    })

    // La place que prend ce qui suit la carte des ralentisseurs (l'intertitre et les lignes d'arrière-plan).
    readonly property real suite: onglet.page.arrierePlan.length > 0
        ? arriereTitre.height + arriereLignes.implicitHeight + 2 * spacing : 0

    function badge(r) {
        if (r.type === "phase")
            return r.lent ? { "mot": "Lent", "etat": "attention" } : { "mot": "Normal", "etat": "ok" };
        return mots[r.type] ?? mots["fond"];
    }
    function habituel() {
        const n = page.precedents.length;
        return page.habituel === null
            ? "Pas encore d'habitude : il faut quelques démarrages."
            : "Habituel : " + Style.dureeLisible(page.habituel) + " (" + page.pluriel(n, "démarrage précédent", "démarrages précédents") + ")";
    }

    objectName: "demarrage-duree"
    spacing: Style.gouttiere

    Kirigami.InlineMessage {
        objectName: "demarrage-erreurs"
        Layout.fillWidth: true
        visible: onglet.page.erreurs.length > 0
        type: Kirigami.MessageType.Warning
        text: onglet.page.erreurs.join("\n")
    }
    ARegarder {
        Layout.fillWidth: true
        rubrique: "demarrage"
    }

    Carte {
        objectName: "duree-carte"
        Layout.fillWidth: true

        RowLayout {
            Layout.fillWidth: true
            spacing: Style.espace(3)

            Kirigami.Heading {
                Layout.fillWidth: true
                level: 2
                font.pointSize: Style.tailleTitreCarte
                font.weight: Font.Bold
                text: "Durée du démarrage"
                elide: Text.ElideRight
            }
            Controls.Label {
                objectName: "demarrage-total"
                visible: onglet.duree !== null
                text: onglet.duree ? Style.dureeLisible(onglet.duree.total) : ""
                font.pointSize: Style.tailleChiffre
                font.weight: Font.Bold
                font.features: ({ "tnum": 1 })
            }
        }
        EtatVide {
            objectName: "duree-pas-finie"
            Layout.fillWidth: true
            visible: onglet.duree === null
            icone: "chronometer"
            texte: "Le démarrage n'est pas encore fini : sa durée sera relevée au prochain passage."
        }
        // La barre : un segment par phase, de largeur proportionnelle à sa durée.
        Rectangle {
            id: barre

            objectName: "barre-phases"
            Layout.fillWidth: true
            visible: onglet.duree !== null
            implicitHeight: Style.espace(4)
            radius: Style.rayonBarre
            color: Style.releve
            clip: true

            Row {
                anchors.fill: parent

                Repeater {
                    model: onglet.phases

                    delegate: Rectangle {
                        required property var modelData
                        required property int index

                        objectName: "phase-" + modelData.cle
                        width: onglet.somme > 0 ? barre.width * modelData.secondes / onglet.somme : 0
                        height: barre.height
                        color: Style.phases[index % Style.phases.length]
                    }
                }
            }
        }
        // La légende : le nom et la durée de chaque phase (la couleur seule ne dit rien).
        Flow {
            Layout.fillWidth: true
            visible: onglet.duree !== null
            spacing: Style.espace(4)

            Repeater {
                model: onglet.phases

                delegate: Row {
                    required property var modelData
                    required property int index

                    spacing: Style.espace(1.5)

                    Rectangle {
                        anchors.verticalCenter: parent.verticalCenter
                        implicitWidth: Style.espace(2.5)
                        implicitHeight: implicitWidth
                        radius: Style.espace(0.5)
                        color: Style.phases[index % Style.phases.length]
                    }
                    Controls.Label {
                        objectName: "legende-" + modelData.cle
                        text: modelData.nom + " " + modelData.duree
                        color: Style.texteAttenue
                        font.pointSize: Style.tailleMeta
                    }
                }
            }
        }
        Controls.Label {
            objectName: "duree-habituel"
            Layout.fillWidth: true
            visible: onglet.duree !== null
            text: onglet.habituel()
            color: Style.texteAttenue
            font.pointSize: Style.tailleMeta
            wrapMode: Text.WordWrap
        }
    }

    Carte {
        id: ralentisseursCarte

        objectName: "ralentisseurs-carte"
        Layout.fillWidth: true
        visible: onglet.duree !== null || onglet.page.ralentisseurs.length > 0
        titre: "Ce qui ralentit le plus"

        Controls.Label {
            objectName: "ralentisseurs-aucun"
            Layout.fillWidth: true
            visible: onglet.page.ralentisseurs.length === 0
            text: "Rien ne ralentit le démarrage de façon notable."
            color: Style.texteAttenue
            wrapMode: Text.WordWrap
        }
        // La liste défile dans sa propre zone quand elle déborde de l'écran : la carte au-dessus, sa marge, puis ce qui suit.
        Flickable {
            id: liste

            objectName: "ralentisseurs-liste"
            Layout.fillWidth: true
            visible: onglet.page.ralentisseurs.length > 0
            Layout.preferredHeight: Math.min(contentHeight, Math.max(Kirigami.Units.gridUnit * 6,
                onglet.page.hauteurOnglet - ralentisseursCarte.y - ralentisseursCarte.decalageContenu - liste.y
                - Style.margeCarte - onglet.suite))
            contentWidth: width
            contentHeight: lignes.implicitHeight
            clip: true
            interactive: contentHeight > height
            boundsBehavior: Flickable.StopAtBounds
            Controls.ScrollBar.vertical: Controls.ScrollBar {
                policy: Controls.ScrollBar.AsNeeded
            }

            ColumnLayout {
                id: lignes

                width: liste.width - (liste.contentHeight > liste.height ? Style.espace(4) : 0)
                spacing: Style.espace(2)

                Repeater {
                    model: onglet.page.ralentisseurs

                    delegate: ColumnLayout {
                        id: rang

                        required property var modelData
                        required property int index
                        readonly property var mot: onglet.badge(modelData)

                        objectName: "ralentisseur-" + modelData.id
                        Layout.fillWidth: true
                        spacing: Style.espace(1)

                        Kirigami.Separator {
                            Layout.fillWidth: true
                            Layout.bottomMargin: Style.espace(1)
                            visible: rang.index > 0
                            color: Style.ligne
                        }
                        RowLayout {
                            Layout.fillWidth: true
                            spacing: Style.espace(3)

                            TexteAbrege {
                                objectName: "nom-ralentisseur-" + rang.modelData.id
                                Layout.fillWidth: true
                                text: rang.modelData.nom ?? ""
                                font.weight: Font.DemiBold
                            }
                            Controls.Label {
                                objectName: "duree-ralentisseur-" + rang.modelData.id
                                text: rang.modelData.duree ?? ""
                                font.weight: Font.DemiBold
                                font.features: ({ "tnum": 1 })
                            }
                            Badge {
                                objectName: "badge-ralentisseur-" + rang.modelData.id
                                texte: rang.mot.mot
                                etat: rang.mot.etat
                            }
                        }
                        Controls.Label {
                            objectName: "explication-ralentisseur-" + rang.modelData.id
                            Layout.fillWidth: true
                            text: rang.modelData.explication ?? ""
                            color: Style.texteAttenue
                            font.pointSize: Style.tailleMeta
                            wrapMode: Text.WordWrap
                        }
                    }
                }
            }
        }
    }

    Intertitre {
        id: arriereTitre

        objectName: "arriere-plan-titre"
        visible: onglet.page.arrierePlan.length > 0
        text: "En arrière-plan, sans retarder le bureau"
    }
    ColumnLayout {
        id: arriereLignes

        Layout.fillWidth: true
        visible: onglet.page.arrierePlan.length > 0
        spacing: Style.espace(1.5)

        Repeater {
            model: onglet.page.arrierePlan

            delegate: RowLayout {
                id: fond

                required property var modelData

                objectName: "arriere-plan-" + modelData.id
                Layout.fillWidth: true
                spacing: Style.espace(3)

                TexteAbrege {
                    objectName: "fond-nom-" + fond.modelData.id
                    Layout.preferredWidth: Kirigami.Units.gridUnit * 14
                    text: (fond.modelData.nom ?? "") + (fond.modelData.portee === "session" ? " (session)" : "")
                    font.weight: Font.DemiBold
                }
                Controls.Label {
                    objectName: "fond-duree-" + fond.modelData.id
                    text: fond.modelData.duree ?? ""
                    font.features: ({ "tnum": 1 })
                }
                TexteAbrege {
                    Layout.fillWidth: true
                    text: fond.modelData.explication ?? ""
                    color: Style.texteAttenue
                    font.pointSize: Style.tailleMeta
                }
            }
        }
    }
}
