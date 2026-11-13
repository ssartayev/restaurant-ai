# One entry point for people and for coding agents. Every target works from the repository root.
PY := .venv/bin/python
SCENARIO ?= dinner_basic
SPEED ?= 20
VIDEO_PORT ?= 8002
MODEL := .models/yolox_s.onnx

empty :=
space := $(empty) $(empty)

# Use the workspace PostgreSQL instance when initialized, with DATABASE_URL taking priority.
ifneq ($(wildcard .local-postgres/data/PG_VERSION),)
DATABASE_URL ?= postgresql+psycopg:///restaurant_ai_restored?host=$(subst $(space),%20,$(CURDIR)/.local-postgres/socket)&port=55432
export DATABASE_URL
endif

.PHONY: setup video-setup video dev api web build test test-api test-worker typecheck e2e cv-eval simulate openapi clean

setup:            ## create .venv, install Python and web dependencies
	python3 -m venv .venv
	$(PY) -m pip install -q -e "apps/api[dev]" -e "apps/worker[dev]" numpy
	cd apps/web && npm install --no-audit --no-fund

build:            ## build the web app into apps/web/dist (the API serves it)
	cd apps/web && npm run build

video-setup: setup $(MODEL) .models/pose_landmarker_lite.task
	$(PY) -m pip install -e "apps/worker[video]" python-multipart "mediapipe>=0.10.32,<0.11"

$(MODEL):
	mkdir -p .models
	curl -fL --retry 2 https://github.com/Megvii-BaseDetection/YOLOX/releases/download/0.1.1rc0/yolox_s.onnx -o $@.tmp
	mv $@.tmp $@

.models/pose_landmarker_lite.task:
	mkdir -p .models
	curl -fL --retry 2 https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_lite/float16/1/pose_landmarker_lite.task -o $@.tmp
	mv $@.tmp $@

dev: video

video: build
	PYTHONPATH=apps/worker $(PY) -m uvicorn app.video:app --app-dir apps/api --port $(VIDEO_PORT)

api:              ## API only, for use with `make web`
	$(PY) -m uvicorn app.main:app --app-dir apps/api --port 8000 --reload

web:              ## Vite dev server on :5173 with hot reload, proxying /v1 to :8000
	cd apps/web && npm run dev

test: test-api test-worker typecheck   ## all fast tests

test-api:
	env -u DATABASE_URL $(PY) -m pytest apps/api -q

test-worker:
	cd apps/worker && ../../$(PY) -m pytest -q

typecheck:
	cd apps/web && npm run typecheck

e2e: build
	@tmp=$$(mktemp -d); \
	  DATABASE_URL=sqlite:///$$tmp/e2e.db SEED_DEV=0 PYTHONPATH=apps/worker $(PY) -m uvicorn app.video:app --app-dir apps/api --port 8010 --log-level warning & \
	  pid=$$!; trap 'kill $$pid 2>/dev/null; wait $$pid 2>/dev/null; rm -rf "$$tmp"' EXIT; \
	  sleep 3; BASE_URL=http://127.0.0.1:8010 node e2e/golden.cjs

cv-eval:          ## vision evaluation on the held-out split -> eval/report.md
	cd apps/worker && ../../$(PY) -m worker.evaluate --manifest ../../eval/manifest.json --split heldout \
	  --out ../../eval/report.md --json ../../eval/report.json

simulate:         ## replay a scenario over HTTP against `make dev` (SCENARIO=..., SPEED=...)
	$(PY) tools/simulate.py $(SCENARIO) --speed $(SPEED) --assert

openapi:          ## write the API contract to packages/contracts/openapi.json
	cd apps/api && SEED_DEV=0 ../../$(PY) -c "import json; from app.main import app; print(json.dumps(app.openapi(), indent=1))" > ../../packages/contracts/openapi.json

clean:
	rm -rf dev.db dev.db-* .dev-device-token apps/web/dist e2e/artifacts
