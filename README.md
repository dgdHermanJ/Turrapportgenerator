# Turrapportgenerator
AI-generert turrapport for Blogger fra en zip med bilder og GPX-spor.

- **extract** – leser GPX og EXIF, plasserer bildene langs ruta, henter stedsnavn (Kartverket), vær (Open-Meteo),
  tegner kart (Kartverket topo) og høydeprofil, og lager webversjoner av bildene uten metadata.
- **render** – gjør en `report.md` (skrevet av Claude) om til HTML som kan limes inn i Blogger, pluss en lokal forhåndsvisning.

```
python -m turrapport extract tur.zip --out trips/min-tur
# skriv trips/min-tur/report.md
python -m turrapport render trips/min-tur [--urls-from blogger-utkast.html]
```

Se `CLAUDE.md` for hele arbeidsflyten.
