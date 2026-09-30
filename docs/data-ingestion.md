# Karachi data ingestion

This pipeline is limited to real, source-attributed records that fit the existing
database contract. It does not calculate risk scores, infer unavailable measurements,
or turn land-cover classes into environmental metrics without an approved method.

## Reproducible commands

Install the data-processing tools separately from the production backend image:

```text
python -m pip install -r requirements-data.txt
python -m scripts.karachi_data_pipeline prepare
python -m scripts.karachi_data_pipeline import
```

`prepare` acquires any missing raw files, validates them, and writes
`data/processed/karachi/processed.json` plus `provenance.json`. Raw responses and
downloads remain under ignored `data/raw/`; existing raw files are validated and
reused rather than overwritten. `import` validates the committed JSON through
`ProcessedBatch`, reports inserted versus updated IDs, and calls the existing atomic
`import_processed()` helper. It never deletes records omitted from the batch.

Public-source acquisition uses `Settings(_env_file=None)` and cannot read the database
secret. Only the explicit import command loads `DATABASE_URL`; it never prints it.

## Selected sources

| Data | Exact resource | Source date | CRS / resolution | Units / use |
| --- | --- | --- | --- | --- |
| Karachi boundary | [OSM relation 6080948](https://www.openstreetmap.org/relation/6080948), version 42 | OSM edit timestamp 2025-01-14T11:35:00Z | EPSG:4326; vector administrative boundary | City geometry only |
| Gulshan-e-Iqbal Town | [OSM relation 16350240](https://www.openstreetmap.org/relation/16350240), version 4 | OSM edit timestamp 2024-07-08T09:15:43Z | EPSG:4326; vector administrative boundary | Area geometry only |
| Population | [WorldPop Pakistan 2025 constrained R2025A v1](https://data.worldpop.org/GIS/Population/Global_2015_2030/R2025A/2025/PAK/v1/1km_ua/constrained/pak_pop_2025_CN_1km_R2025A_UA_v1.tif), catalog ID 78735, DOI 10.5258/SOTON/WP00840 | Product/release date 2025-09-01; population year 2025 | EPSG:4326; 30 arc-seconds, approximately 1 km | Modelled people per source pixel |
| PM2.5 / PM10 | [Open-Meteo Air Quality API](https://open-meteo.com/en/docs/air-quality-api), CAMS Global domain | 2025-09-01T00:00:00Z model timestep | Returned CAMS point 24.900002N, 67.100006E; 0.4 degrees, approximately 45 km | µg/m³; one regional model point, not a street-level monitor |
| Peri-urban land cover | [EO4SD Karachi LULC 2017](https://datacatalogfiles.worldbank.org/ddh-published/0041102/DR0051284/eo4sd_karachi_lulchr_2017.zip) | Resource labelled 2017; current EnergyData catalog metadata captured in `provenance.json` | EPSG:32642; 31,137 source polygons | Seven original Level-2 class names/codes retained for review |
| Informal settlements | [EO4SD Karachi Informal Settlements 2017](https://datacatalogfiles.worldbank.org/ddh-published/0039832/1/DR0049551/eo4sd_karachi_informal_2017.zip) | Resource labelled 2017 | EPSG:32642; 1,927 source polygons | Source geometry retained for review, not converted to vulnerability |

OpenStreetMap is community-maintained and is not represented as an official cadastral
boundary. WorldPop is an alpha, constrained Random-Forest dasymetric estimate rather
than a census count. The CAMS value is regional model output. The two EO4SD archives
are CC BY 4.0; their source classes are not risk or green scores.

The questionable archive published as 2017 **core** LULC is not downloaded or used by
this pipeline. Its internal 2005 filenames remain an unresolved source discrepancy.

## Geometry and grid processing

The OSM relation outer ways are polygonized, oriented, and checked for valid 2D
geometry. Gulshan-e-Iqbal is verified to be covered by the sourced Karachi Division
boundary before processing.

The analysis grid uses the selected WorldPop raster's native 30 arc-second pixels, so
no arbitrary grid resolution is introduced. Each intersecting pixel is clipped to the
Gulshan boundary. IDs encode the immutable source raster row and column, for example
`gulshan-e-iqbal-wp2025-r01462-c00747`. Grid geometry is emitted in EPSG:4326 and
centroids are calculated after projecting the clipped polygon to EPSG:32642. Stored
grid geometry uses a 1 cm inward precision buffer of the sourced boundary so PostGIS
can verify exact containment across geometry-engine precision models; population
allocation continues to use the original unbuffered boundary.

For a boundary pixel, the source population count is multiplied by the fraction of its
area inside Gulshan, calculated in EPSG:32642. This assumes population is uniform inside
that approximately 1 km source pixel; it does not turn the modelled estimate into a
census count. The stored area population is the exact sum of stored cell values.

The CAMS request uses the sourced Gulshan polygon centroid. Open-Meteo returned the
nearest CAMS grid coordinate shown above. Only the unaggregated 00:00 UTC timestep is
stored, and only in the analysis cell containing that returned coordinate. It is not
copied across the 1 km grid.

## Current processed batch

| Table | Records | Contents |
| --- | ---: | --- |
| `cities` | 1 | `karachi`, with sourced OSM geometry |
| `areas` | 1 | `gulshan-e-iqbal`, sourced OSM geometry and modelled 2025 population total |
| `grid_cells` | 210 | Valid clipped WorldPop-native cells with stable IDs and centroids |
| `environmental_data` | 210 | Population in every cell; PM2.5/PM10 in one CAMS-containing cell |
| `risk_scores` | 0 | No approved Chip methodology is committed |

The imported area total is **2,144,041.503522 modelled people**. The initial live
import updated the two existing bootstrap IDs and inserted 210 grid plus 210
environmental records. A validation rerun updated those same stable IDs and inserted
no duplicates. PostGIS confirms SRID 4326, valid geometry, and zero grid cells outside
the area boundary.

`temperature`, `ndvi`, `rainfall`, `elevation`, `slope`, `road_density`, and
`green_percentage` remain null. Their source/product or feature definition is not yet
approved. In particular, the EO4SD class labels are preserved but not silently mapped
to `green_percentage`, and informal-settlement polygons are not converted into risk.

The exact checksums, class list, source bounds, source metadata, processing decisions,
limitations, field availability, and record counts are machine-readable in
`data/processed/karachi/provenance.json`.

## Remaining scientific decisions

- Chip must supply the approved risk-score formulas, weights, thresholds, aggregation,
  and required time alignment before `risk_scores` can be populated.
- The team must approve Landsat/Sentinel scenes, bands, cloud handling, and dates for
  temperature/NDVI.
- The team must choose the IMERG product/version and rainfall transformation.
- The team must choose a DEM product and slope method.
- OSM road selectors and the road-density denominator need agreement.
- EO4SD Level-2 classes need an approved definition of what contributes to
  `green_percentage`.
- The schema has no durable provenance columns or informal-settlement table; the
  committed provenance file remains the source record unless the database contract is
  intentionally extended.
