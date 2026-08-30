# Symbole der Unterrichtsmodule

Hier liegen die mitgelieferten Symbole als PNG mit transparentem Hintergrund:
ein weißes Motiv, die farbige Kachel zeichnet das Programm selbst.

Der Dateiname ist der `icon_key` des jeweiligen Eintrags, zum Beispiel
`partner.png` für Partnerarbeit oder `binder.png` für den Hefter. Fehlt eine
Datei, zeichnet das Programm ersatzweise ein einfaches Vektorsymbol.

Erzeugt werden die Dateien aus einem einzelnen Symbolblatt:

    python tools/slice_icon_sheet.py blatt.png --preview build/preview

Eigene Bilder pro Eintrag lassen sich unabhängig davon in der Verwaltung
zuweisen; sie haben Vorrang vor den Dateien in diesem Ordner.
