# Bundled fonts

Barlow Semi Condensed, the visual design's instrument-readout face (spec section 9.2), copied
byte for byte from the Google Fonts repository on 2026-10-28. It is licensed under the SIL Open
Font License 1.1; the license text is `OFL.txt` beside this file. `make release` copies the
two fonts and `OFL.txt` (not this file) into `Telltale.app/Contents/Resources/Fonts`, and the app registers the fonts for its own
process at launch (`Fonts.register`). `FontsTests` reads the table below and checks that every
font in it resolves by its PostScript name after registration.

| File | PostScript name | Source URL | sha256 |
| --- | --- | --- | --- |
| BarlowSemiCondensed-Regular.ttf | BarlowSemiCondensed-Regular | https://raw.githubusercontent.com/google/fonts/main/ofl/barlowsemicondensed/BarlowSemiCondensed-Regular.ttf | e8c7242f612b13d026e18a94b63b0fd079e91a3faf009d1b6981dbb5f16d1153 |
| BarlowSemiCondensed-Medium.ttf | BarlowSemiCondensed-Medium | https://raw.githubusercontent.com/google/fonts/main/ofl/barlowsemicondensed/BarlowSemiCondensed-Medium.ttf | 4998b693a190b76f2b11315844345a8546c1e2e6a320905507a9eed04edf8b48 |
| OFL.txt | | https://raw.githubusercontent.com/google/fonts/main/ofl/barlowsemicondensed/OFL.txt | 186d750eb496a4c17a76385f82be6aea2ac1cf2de074a811d63786cf374ea73f |

Sizes: Regular 105,776 bytes, Medium 105,560 bytes, OFL.txt 4,377 bytes.
