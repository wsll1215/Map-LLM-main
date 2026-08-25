# GIS Data Storage

The application uses one PostgreSQL database with the PostGIS extension as its
primary data store. Docker persists it under `runtime/postgis/` in the project
directory.

- `Dataset` stores catalog metadata, source, version, CRS, and bounding box.
- `DatasetFeature` stores normalized geometries in EPSG:4326 with a GiST index
  and JSON properties for spatial filtering.
- `data/` remains the immutable local source file directory.
- `data_cache/` stores downloaded source files and is not a database substitute.
- Redis stores task state, locks, and short-lived SSE events.
- Neo4j stores graph relationships and topology that need graph traversal.

## Docker

```powershell
docker compose up -d postgis redis neo4j
docker compose run --rm web python manage.py migrate
docker compose run --rm web python manage.py catalog_datasets
docker compose run --rm web python manage.py import_datasets_to_postgis --replace
```

The PostGIS feature endpoint is:

`GET /mapping/api/datasets/{dataset_id}/features/?bbox=minx,miny,maxx,maxy&limit=2000`

The endpoint always requires a bbox and caps a response at 10,000 features so
large layers do not accidentally become a huge GeoJSON response.
