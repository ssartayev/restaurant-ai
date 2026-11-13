# Restaurant table management

A fixed camera notices when a party sits down or leaves. Staff see each table as **Ready**,
**Occupied** or **Needs clearing**, get one alert when a table needs clearing, and the host
seats the next waiting party that fits. Everything also works by hand when the camera is off.

```bash
make setup
make dev        # http://localhost:8000  ->  "Start demo"
make test       # 59 API tests, 21 worker tests, web type-check
make e2e        # browser test of the full demo path
```

Seeded logins for local use: `admin@demo.test / demo-admin`, `host@demo.test / demo-host`,
`staff@demo.test / demo-staff`.

- **[AGENTS.md](AGENTS.md)** — how the system works (all key algorithms), how to change it
  safely, what is verified, and the remaining tasks. Written for developers and for any LLM
  coding assistant.
- **[docs/PLAN.md](docs/PLAN.md)** — product scope, milestones, acceptance criteria, launch checklists.
- **[eval/report.md](eval/report.md)** — latest vision evaluation (synthetic data for now).

Status: the complete workflow runs and is tested with simulated camera events. It has not
yet been run with a real camera, real footage, PostgreSQL or a hosted deployment; see
AGENTS.md sections 7 and 8.
