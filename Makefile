# One entry point for people and for coding agents. Every target works from the repository root.
PY := .venv/bin/python
SCENARIO ?= dinner_basic
SPEED ?= 20

.PHONY: setup dev api web build test test-api test-worker typecheck e2e cv-eval simulate openapi clean

setup:            ## create .venv, install Python and web dependencies
	python3 -m venv .venv
	$(PY) -m pip install -q -e "apps/api[dev]" -e "apps/worker[dev]" numpy
	cd apps/web && npm install --no-audit --no-fund

build:            ## build the web app into apps/web/dist (the API serves it)
	cd apps/web && npm run build

dev: build        ## run everything on http://localhost:8000 (SQLite file dev.db, seeded logins)
	$(PY) -m uvicorn app.main:app --app-dir apps/api --port 8000 --reload

api:              ## API only, for use with `make web`
	$(PY) -m uvicorn app.main:app --app-dir apps/api --port 8000 --reload

web:              ## Vite dev server on :5173 with hot reload, proxying /v1 to :8000
	cd apps/web && npm run dev

test: test-api test-worker typecheck   ## all fast tests

test-api:
	$(PY) -m pytest apps/api -q

test-worker:
	cd apps/worker && ../../$(PY) -m pytest -q

typecheck:
	cd apps/web && npm run typecheck

e2e: build        ## browser test against a throwaway server on :8010
	@rm -f /tmp/rai-e2e.db
	@DATABASE_URL=sqlite:////tmp/rai-e2e.db SEED_DEV=0 $(PY) -m uvicorn app.main:app --app-dir apps/api --port 8010 --log-level warning & \
	  pid=$$!; sleep 3; BASE_URL=http://localhost:8010 node e2e/golden.cjs; code=$$?; kill $$pid; exit $$code

cv-eval:          ## vision evaluation on the held-out split -> eval/report.md
	cd apps/worker && ../../$(PY) -m worker.evaluate --manifest ../../eval/manifest.json --split heldout \
	  --out ../../eval/report.md --json ../../eval/report.json

simulate:         ## replay a scenario over HTTP against `make dev` (SCENARIO=..., SPEED=...)
	$(PY) tools/simulate.py $(SCENARIO) --speed $(SPEED) --assert

openapi:          ## write the API contract to packages/contracts/openapi.json
	cd apps/api && SEED_DEV=0 ../../$(PY) -c "import json; from app.main import app; print(json.dumps(app.openapi(), indent=1))" > ../../packages/contracts/openapi.json

clean:
	rm -rf dev.db dev.db-* .dev-device-token apps/web/dist e2e/artifacts
