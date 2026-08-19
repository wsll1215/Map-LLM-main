# Map2-LLM-Multiple

Merged Django + GIS mapping agent project.

## Run

```powershell
copy .env.example .env
pip install -r requirements.txt
python manage.py runserver
```

The Django entrypoint is `manage.py`. The GIS package is available as `gis_mapping_agent` from the project root.

## Layout

- `xy_neo4j/`, `accounts/`, `myneo4j/`, `mapping/`: Django project and apps.
- `gis_mapping_agent/`: Map-LLM agent package.
- `data/`: Neo4j CSV data plus GIS shapefile datasets.
- `outputs/`: generated GIS outputs and `outputs/states/map_states.db`.
- `generated_maps/`: web app generated map files.
