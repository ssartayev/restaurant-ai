# One image: builds the web app, then serves API + web from a single process.
# NOT yet built or run in CI (see AGENTS.md, remaining task OPS-1).
FROM node:22-slim AS web
WORKDIR /web
COPY apps/web/package*.json ./
RUN npm ci --no-audit --no-fund
COPY apps/web ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /srv
COPY apps/api/pyproject.toml apps/api/
COPY apps/api/app apps/api/app
RUN pip install --no-cache-dir "./apps/api[postgres]"
COPY packages packages
COPY fixtures fixtures
COPY --from=web /web/dist apps/web/dist
ARG GIT_SHA=dev
ENV GIT_SHA=$GIT_SHA SEED_DEV=0 COOKIE_SECURE=1 \
    FIXTURES_DIR=/srv/fixtures CONTRACTS_DIR=/srv/packages/contracts WEB_DIST=/srv/apps/web/dist
EXPOSE 8000
# One worker: the event stream fan-out is in-process (see AGENTS.md section 5.7).
CMD ["uvicorn", "app.main:app", "--app-dir", "apps/api", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
