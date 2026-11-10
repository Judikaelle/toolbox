import QtQuick
import org.kde.kirigami as Kirigami
import "."

// Dialogue de confirmation : celui de Kirigami, habillé comme ceux de GitHub Hub (fond du menu, rayon 18, bordure
// fine, sans ombre, marges larges). Son contenu et ses boutons prennent la palette KDE de l'appli (apparence.py).
Kirigami.PromptDialog {
    id: dialogue

    contentPadding: Style.espace(5)
    background: Rectangle {
        color: Style.fondMenu
        radius: Style.rayonBandeau
        border.width: 1
        border.color: Style.ligne2
    }
    // Les boutons du pied s'écartent des coins arrondis (Kirigami ne laisse que 8 px) ; sans bouton, le pied reste
    // la petite marge de Kirigami (bufferMode).
    Component.onCompleted: {
        if (footer && footer.padding !== undefined)
            footer.padding = Qt.binding(() => footer.bufferMode ? 0 : Style.gouttiere);
    }
}
