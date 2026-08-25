# Repository Guidelines

## Project Structure & Module Organization

`manage.py` is the Django entrypoint. Project configuration, ASGI/WSGI wiring, and
legacy Neo4j QA helpers live in `xy_neo4j/`; shared local configuration lives in
`config/`. Django apps are in `accounts/`, `mapping/`, and `myneo4j/`. The
`mapping/` app owns map request models, REST/API views, SSE streaming protocol,
admin customizations, database-admin helpers, migrations, management commands, and
Django-scoped templates under `mapping/templates/`.

The mapping-agent implementation is in `gis_mapping_agent/`, organized by concern:
`agent/`, `tools/`, `state/`, `specs/`, `generalization/`, `adjustment/`, `gis/`,
`models/`, `algorithms/`, `rendering/`, and `utils/`. Prefer adding new agent
interfaces to the closest existing package instead of creating broad catch-all
modules.

The React/Vite workbench lives in `frontend/`; source code is under `frontend/src/`
with `api/`, `components/`, `hooks/`, `lib/`, `map/`, `state/`, `styles/`, and
`types/`. Django templates shared by the legacy pages stay in `templates/`, while
static assets stay in `static/`, `assets/`, or generated frontend output under
`static/frontend/`.

`data/` contains committed GIS/Neo4j inputs; do not modify source datasets casually.
`docs/` contains project documentation and `scripts/` contains operational helpers.
Runtime artifacts belong in ignored runtime directories such as `generated_maps/`,
`outputs/`, `staticfiles/`, `.pytest_cache/`, frontend caches, and local package
caches. Put new automated Python tests in `tests/` as `test_<feature>.py`; keep
frontend unit tests next to the relevant `frontend/src/` modules as `*.test.ts` or
`*.test.tsx`.

## Build, Test, and Development Commands

```powershell
copy .env.example .env           # create local configuration; add API keys locally
pip install -r requirements.txt  # install Django, agent, GIS, and test dependencies
python manage.py runserver       # start Django's development server
python manage.py check           # validate Django settings, URLs, models, and apps
pytest                           # run Python tests from tests/
```

```powershell
cd frontend
npm install                      # install React/Vite dependencies
npm run dev                      # start the Vite development server
npm run build                    # typecheck and build the frontend
npm run test                     # run Vitest frontend unit tests
npm run typecheck                # run TypeScript checks only
```

```powershell
docker compose up --build
docker compose --profile init run --rm neo4j-init
```

Use `python manage.py check` after settings, URL, model, template, or app wiring
changes. Use `pytest` for backend and agent changes, and use the relevant `npm`
commands after frontend changes. The Docker stack runs the web app, Neo4j, Redis,
and nginx; the `neo4j-init` profile imports Neo4j CSV data.

## Coding Style & Naming Conventions

Target Python 3.9+ and use four-space indentation. Format Python with Black
(88-column lines) and sort imports with isort's Black profile:

```powershell
black .
isort .
mypy gis_mapping_agent
```

Use `snake_case` for Python files, functions, variables, and test names; use
`PascalCase` for classes and Pydantic/Django models. Keep type annotations on
public functions and new agent interfaces. Prefer small modules focused on one
workflow, and reuse the existing `specs`, `state`, `tools`, and `rendering`
boundaries when adding agent behavior.

For frontend code, use TypeScript, React function components, and the existing
`frontend/src/` layout. Keep component names in `PascalCase`, hooks prefixed with
`use`, reducers/state helpers in `camelCase`, and shared API types in `types/`.
Keep CSS in `frontend/src/styles/` or the nearest established stylesheet rather
than scattering inline styles.

## Testing Guidelines

Tests use pytest for Python and Vitest for frontend code. Backend tests primarily
cover specs, state handling, tools, agent routing, SSE protocol behavior, data path
resolution, and Django integration boundaries. Name tests by behavior, e.g.
`test_state_rollback_restores_map`.

Add regression coverage for every bug fix. Avoid tests that require external LLM
credentials, a running Neo4j instance, or mutating committed data fixtures unless
the test explicitly provisions those dependencies. Keep manual/browser checks named
`tests/manual_*.py` and do not treat them as required CI-style tests.

## Data, Runtime State, and Secrets

Never commit `.env`, API keys, production database credentials, or generated SQLite
state. Keep generated maps, agent outputs, map-state databases, collected static
files, frontend build artifacts, dependency caches, and screenshots out of source
modules unless they are deliberate documentation assets. When adding code that
reads datasets, route paths through the existing configuration/path-resolution
helpers so local and Docker layouts continue to work.

## Commit & Pull Request Guidelines

This checkout does not include accessible Git history, so no repository-specific
commit convention can be confirmed. Use concise imperative subjects such as
`Add map-state rollback validation`. Keep each commit focused. Pull requests should
describe behavior and configuration changes, link the relevant issue when present,
list test commands run, and include screenshots for template, frontend, or
map-rendering UI changes.
