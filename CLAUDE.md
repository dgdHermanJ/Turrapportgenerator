# Turrapportgenerator – arbeidsflyt for Claude

Brukeren gir en zip med bilder (med EXIF) og en GPX-fil. Claude skriver turrapporten; Python-koden gjør alt det mekaniske.

## Oppsett (én gang)
```
python -m venv .venv
.venv\Scripts\python -m pip install --use-feature=truststore -r requirements.txt
```
Maskinen har TLS-inspeksjon (antivirus) – pip trenger `--use-feature=truststore`; koden bruker `truststore` automatisk.
Kjør med `PYTHONIOENCODING=utf-8` i Git Bash for å unngå æøå-feil i konsollen.

## Per tur
1. `.venv/Scripts/python -m turrapport extract "<zip>" --out trips/<kort-navn>`
   - Kameraklokke feil? `--time-offset <minutter>`.
2. Les `trips/<navn>/brief.md` og **se på hvert bilde** i `images/` (Read) før du skriver.
3. Skriv `trips/<navn>/report.md` (syntaks øverst i `turrapport/render.py`):
   - Norsk bokmål, personlig jeg/vi-form, blogg-tone. Ikke dikt opp fakta: navn på personer, hunderaser,
     villrein vs. tamrein o.l. – hold det generelt hvis det ikke er sikkert.
   - Bruk stedsnavn fra brief (Kartverket) og kartet; vær fra Open-Meteo er modellverdier, bruk dem løst.
   - Skilt/offisielle høyder slår GPS-høyde; overstyr med `[nøkkeltall: Høyeste punkt=...]`.
   - Bilder merket «før turen»/«etter turen» er ikke langs sporet – plasser dem i fortellingen deretter.
4. `.venv/Scripts/python -m turrapport render trips/<navn>` → `blogger.html` + `preview.html`.
   Sjekk gjerne visuelt: headless Edge `--screenshot` av `preview.html`.
5. Publisering: brukeren laster opp bildene fra `images/` (alfabetisk rekkefølge) i et Blogger-utkast,
   kopierer HTML-visningen til en fil, og kjører `render ... --urls-from <fil>`. Da peker `blogger.html` til Blogger-URLene
   og kan limes inn i HTML-visningen i Blogger.

`trips/` er i .gitignore – private bilder og posisjoner skal ikke committes.
