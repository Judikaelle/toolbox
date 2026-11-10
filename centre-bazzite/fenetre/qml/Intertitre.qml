import QtQuick
import QtQuick.Controls as Controls
import "."

// Intertitre de GitHub Hub : 11 px demi-gras, en capitales, interlettrage de 0,08 em, très atténué.
Controls.Label {
    color: Style.texteDim
    font.pointSize: Style.tailleIntertitre
    font.weight: Font.DemiBold
    font.letterSpacing: Style.interlettrage
    font.capitalization: Font.AllUppercase
}
