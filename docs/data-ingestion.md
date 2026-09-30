# Karachi data ingestion

This pipeline imports only real, source-attributed records that fit the existing
database contract. It applies Chip's committed grid models where their inputs exist;
it does not infer missing measurements, area aggregation, or land-cover meanings.

## Reproducible commands

Install the data tools separately from the production backend image:

```text
python -m pip install -r requirements-data.txt
python -m scripts.karachi_data_pipeline prepare
python -m scripts.karachi_data_pipeline import
```

`prepare` acquires missing public assets, validates them, and rewrites
`data/processed/karachi/processed.json` plus `provenance.json`. Raw responses and
clipped source rasters stay in ignored `data/raw/`. `import` validates the entire
`ProcessedBatch` and atomically upserts stable IDs without deleting omitted rows.
Public acquisition uses `Settings(_env_file=None)` and cannot read the database
secret. Only `import` loads `DATABASE_URL`, and it never prints it.

## Selected sources

| Data | Exact resource | Date / resolution | Use |
| --- | --- | --- | --- |
| Karachi boundary | [OSM relation 6080948](https://www.openstreetmap.org/relation/6080948), version 42 | 2025-01-14; EPSG:4326 vector | City geometry |
| Gulshan-e-Iqbal | [OSM relation 16350240](https://www.openstreetmap.org/relation/16350240), version 4 | 2024-07-08; EPSG:4326 vector | Area geometry |
| Population | [WorldPop Pakistan 2025 constrained R2025A v1](https://data.worldpop.org/GIS/Population/Global_2015_2030/R2025A/2025/PAK/v1/1km_ua/constrained/pak_pop_2025_CN_1km_R2025A_UA_v1.tif), DOI 10.5258/SOTON/WP00840 | 2025 model; 30 arc-seconds | Modelled people per source pixel |
| LST / NDVI | USGS Landsat 9 Collection 2 Level-2 product `LC09_L2SP_152043_20250905_02_T1`, through the public Planetary Computer mirror | 2025-09-05; 30 m | QA-masked cell-mean Celsius LST and unitless NDVI |
| PM2.5 / PM10 | [Open-Meteo Air Quality API](https://open-meteo.com/en/docs/air-quality-api), CAMS Global | 2025-09-01 00:00 and 2025-09-05 06:00 UTC; 0.4 degrees | Regional model values in one containing cell per timestep |
| Peri-urban land cover | [EO4SD Karachi LULC 2017](https://datacatalogfiles.worldbank.org/ddh-published/0041102/DR0051284/eo4sd_karachi_lulchr_2017.zip) | 2017; EPSG:32642 vector | Original seven Level-2 classes retained, not reclassified |
| Informal settlements | [EO4SD Karachi Informal Settlements 2017](https://datacatalogfiles.worldbank.org/ddh-published/0039832/1/DR0049551/eo4sd_karachi_informal_2017.zip) | 2017; EPSG:32642 vector | Retained for review, not converted to vulnerability |

OSM is community-maintained, WorldPop is a modelled dasymetric estimate rather than
a census count, CAMS is regional model output rather than a street monitor, and the
Landsat data is one overpass rather than a temporal average. The questionable archive
published as 2017 *core* LULC is not used because its internal filenames say 2005.

## Processing

The OSM relations are polygonized, oriented and validated. The analysis grid uses
WorldPop's native cells clipped to the Gulshan boundary, with stable raster-row/column
IDs. Population for a boundary cell is multiplied by its EPSG:32642 intersection-area
fraction. The stored area population is the exact sum of stored cell values.

Each CAMS request uses the sourced area centroid. Its unaggregated value is retained
only in the grid containing the provider-returned point and is never copied over the
1 km project grid.

For Landsat, `QA_PIXEL` fill, dilated cloud, cirrus, cloud, shadow and snow flags are
excluded. Cells below Chip's 35% valid-pixel threshold or above its 35% cloud threshold
stay null. The official Collection 2 scale/offset converts `ST_B10` to Celsius. Scaled
red and NIR surface reflectance produce NDVI before each grid-cell mean. Temporary
signed mirror URLs are neither committed nor copied into provenance.

Chip's heat, green, air, flood, mobility, composite and exposure functions then run
against the aligned snapshot. A component score is stored only when at least one of
that model's weighted inputs is present. Composite, exposure and overall remain null
unless all five component dimensions and population are available.

## Current processed and live data

| Table | Records | Contents |
| --- | ---: | --- |
| `cities` | 1 | `karachi`, with sourced OSM geometry |
| `areas` | 1 | `gulshan-e-iqbal`, sourced geometry and 2025 modelled population |
| `grid_cells` | 210 | Valid WorldPop-native cells with stable IDs |
| `environmental_data` | 420 | Two dated snapshots; 57 QA-valid LST/NDVI cells, population in all cells, and one CAMS cell per snapshot |
| `risk_scores` | 210 | 57 heat, 57 green, one air and 210 population-supported mobility scores |

The live import upserted the existing city, area, grid and first snapshot; inserted the
second 210 environmental records and 210 partial risk rows; and deleted nothing.
PostGIS continues to report valid EPSG:4326 geometry with every grid covered by the
area. Exact checksums, catalog metadata, quality summaries, processing decisions and
limitations are in `data/processed/karachi/provenance.json`.

## Remaining data/scientific boundaries

- Chip's grid methodology is implemented, but no committed method says how 210 grid
  scores become the existing area-level `RiskResult`. The adapter does not invent a
  mean or population-weighted aggregation.
- IMERG product/version and rainfall transformation remain unresolved.
- A DEM product, access path and slope method remain unresolved.
- OSM road selectors and the road-density denominator remain unresolved.
- Imperviousness, water distance and optional TWI have no current persisted fields.
- EO4SD classes have no approved mapping to `green_percentage`.
- The schema has no durable provenance/confidence columns; the committed provenance
  file remains the source record unless the database contract is intentionally changed.
