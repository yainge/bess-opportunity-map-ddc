# Renewable installations data – source notes

Owner: Isabella. Raw files are immutable; fix problems through `config/datasets.yaml` or code.

**Where the data comes from**

- Website: *Visor ambiental i dades d'energies renovables*, Generalitat de Catalunya
  (Departament de Territori, Habitatge i Transició Ecològica)
  https://mediambient.gencat.cat/ca/05_ambits_dactuacio/avaluacio_ambiental/energies_renovables/visor/index.html
- Download service (WFS, open in QGIS as a WFS layer): https://sig.gencat.cat/ows/ENERGIA/wfs
- Downloaded on: 15 October 2026
- Coordinates: EPSG:25831 (UTM 31N), plus longitude/latitude columns
- Licence: Generalitat open data, attribution required

**Files**

| File | What it is | Rows | Period |
|---|---|---|---|
| `ENERGIA_PARCSSOLARS_MULTIPOLI_20261015.csv` | Ground-mounted solar PV plants over 100 kW: in service, authorised, in permitting, refused, withdrawn. WFS layer `ENERGIA_PARCSSOLARS_MULTIPOLI`. Coordinates are the centre of each plant polygon. | 491 | Plants permitted since November 2019 (Decret llei 16/2019); older plants not included. Status as of download date. |
| `ENERGIA_EOLICA_CATALUNYA_20261015.csv` | Wind farms: existing and authorised parks (WFS layer `ENERGIA_EOLICA_PARCS`, turbines aggregated to one row per park) plus projects in permitting (WFS layer `ENERGIA_PARCSEOLICS_MULTIPUNT`). Column `CAPA_ORIGEN` says which layer a row comes from. | 120 (66 parks + 54 projects) | Park records dated 2010–2024 by the source; projects as of download date. |

**Main columns in both files**: name (`NOM`), capacity in MW (`POTENCIA` in the solar file,
`POTENCIA_MW` in the wind file), status (`ESTAT`: *En servei* / *Servei* = operating,
*Autoritzat* and *En tramitació* = pipeline, *No autoritzat* and *Desistit* = not going ahead),
coordinates (`X_UTM31N`, `Y_UTM31N`, `LON`, `LAT`). Both files use `;` as separator.

**Known gaps**

- The solar layer only contains plants permitted since November 2019, so operating PV built
  before that date is missing. Operating capacity near nodes will be underestimated until an
  older-plant source is added.
- The two files have different column names and must be concatenated (or registered as two
  datasets) before the `renewables` stage can read them; `config/datasets.yaml` does not yet
  have a real `renewables_installations` entry.

**Citation**: Generalitat de Catalunya, Departament de Territori, Habitatge i Transició Ecològica.
Visor ambiental i dades d'energies renovables, capes SIG ENERGIA (WFS). Retrieved 15 October 2026.
