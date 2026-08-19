# Repository Guidelines

## Project Structure & Module Organization

`manage.py` is the Django entrypoint. Project configuration and ASGI/WSGI wiring
live in `xy_neo4j/`; Django apps are in `accounts/`, `mapping/`, and `myneo4j/`.
The mapping-agent implementation is in `gis_mapping_agent/`, organized by concern
(`agent/`, `tools/`, `state/`, `generalization/`, `adjustment/`, and `utils/`).
Keep browser templates in `templates/` and static assets in `static/` or `assets/`.
`data/` contains committed GIS/Neo4j inputs; do not modify source datasets casually.
Put new automated tests in `tests/` as `test_<feature>.py`.

## Build, Test, and Development Commands

```powershell
copy .env.example .env          # create local configuration; add API keys locally
pip install -r requirements.txt # install application and development dependencies
python manage.py runserver      # start Django's development server
pytest                          # run the test suite
docker compose up --build       # run web, Neo4j, Redis, and nginx containers
docker compose --profile init run --rm neo4j-init # import the Neo4j CSV data
```

Use `python manage.py check` after settings, URL, model, or app changes. Generated
maps and SQLite state belong in runtime directories such as `generated_maps/` and
`outputs/`, not in source modules.

## Coding Style & Naming Conventions

Target Python 3.9+ and use four-space indentation. Format with Black (88-column
lines) and sort imports with isort's Black profile:

```powershell
black .
isort .
mypy gis_mapping_agent
```

Use `snake_case` for files, functions, variables, and test names; use `PascalCase`
for classes and Pydantic/Django models. Keep type annotations on public functions
and new agent interfaces. Prefer small modules focused on one workflow.

## Testing Guidelines

Tests use pytest and are primarily unit tests around specs, state handling, tools,
and agent routing. Name tests by behavior, e.g. `test_state_rollback_restores_map`.
Add regression coverage for every bug fix and run `pytest` before opening a review.
Avoid tests that require external LLM credentials, a running Neo4j instance, or
mutating the committed data fixtures unless the test explicitly provisions them.

## Commit & Pull Request Guidelines

This checkout does not include accessible Git history, so no repository-specific
commit convention can be confirmed. Use concise imperative subjects such as
`Add map-state rollback validation`. Keep each commit focused. Pull requests should
describe behavior and configuration changes, link the relevant issue when present,
list test commands run, and include screenshots for template or map-rendering UI
changes. Never commit `.env`, API keys, or production database credentials.
