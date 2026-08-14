# FitOps

Coaching management SaaS for coaches who already have a website. The coach keeps their site and adds
a "Start Coaching" / "Client Login" link pointing at FitOps, which owns everything after that click:

> **Application → Payment → Client → Plans → Check-ins → Progress**

FitOps is multi-tenant from day one. Each coach owns a **Workspace**; all business data is
workspace-scoped and isolated.

---

## Documentation

The approved architecture is the source of truth. **Read it before changing code.**

| Document | Path |
|---|---|
| Project instructions / index | [`CLAUDE.md`](CLAUDE.md) |
| Implementation progress & handoff | [`PROGRESS.md`](PROGRESS.md) |
| Unresolved decisions registry | [`docs/MISSING_DECISIONS.md`](docs/MISSING_DECISIONS.md) |
| MVP Specification | [`docs/01-product/`](docs/01-product/) |
| Technology Stack · Database & Auth · API · ERD/Repository | [`docs/02-architecture/`](docs/02-architecture/) |
| Development Blueprint (Epics & Stories) | [`docs/03-development/`](docs/03-development/) |
| Design System | [`docs/04-design/`](docs/04-design/) |

Current documentation baseline: **Architecture v1.2.1**.

---

## Repository structure

```text
fitops/
├── frontend/           # Next.js + TypeScript (Story 1.3)
├── backend/            # Django + Django REST Framework (Story 1.2)
│   ├── config/         # project settings
│   ├── apps/           # business-domain apps
│   ├── common/         # shared tenant/security infrastructure
│   └── tests/
├── infrastructure/
│   ├── docker/
│   ├── nginx/
│   ├── scripts/
│   └── backups/
├── docs/
│   ├── 01-product/
│   ├── 02-architecture/
│   ├── 03-development/
│   └── 04-design/
├── .env.example
├── .gitignore
├── CLAUDE.md
├── PROGRESS.md
└── README.md
```

`docker-compose.yml` is added in Story 1.6.

---

## Technology stack

| Layer | Technology |
|---|---|
| Frontend | Next.js + TypeScript, Tailwind CSS, shadcn/ui |
| Forms / validation | React Hook Form + Zod |
| Server state | TanStack Query |
| Backend | Django + Django REST Framework |
| Sessions | Django built-in session framework |
| Email | Django email backend + SMTP (env-configured) |
| Database | PostgreSQL |
| Background jobs | Celery + Redis |
| Image processing | Pillow → WebP |
| File storage | Hetzner volume / local storage (storage abstraction) |
| Reverse proxy | Nginx |
| CDN / DNS / SSL | Cloudflare |
| Containers | Docker + Docker Compose |
| CI/CD | GitHub Actions |
| Deployment | Hetzner VPS |

---

## Local setup

### Prerequisites

- Git
- Python 3.x and PostgreSQL — required from Story 1.2 / 1.4
- Node.js — required from Story 1.3
- Docker + Docker Compose — required from Story 1.6

### Getting started

```bash
# 1. Clone the repository
git clone <repository-url> fitops
cd fitops

# 2. Create your local environment file
cp .env.example .env

# 3. Edit .env and fill in real values for your environment
#    .env is git-ignored and must never be committed.
```

At this point the repository structure and configuration template exist. Backend, frontend and the
containerized stack are set up in the following Stories:

| Story | Adds |
|---|---|
| 1.2 | Django project, DRF, business-domain apps, settings, PostgreSQL config |
| 1.3 | Next.js app, TypeScript, Tailwind, shadcn/ui, React Hook Form, Zod, TanStack Query |
| 1.4 | PostgreSQL service, development/test databases, migrations |
| 1.5 | Redis and Celery worker |
| 1.6 | `docker-compose.yml` for the full development stack |
| 1.7 | Test, lint, format and type-check baseline |
| 1.8 | GitHub Actions CI pipeline |

Run commands for each are documented as those Stories land.

---

## Environment variables

All configuration comes from environment variables. `.env.example` is the template — it contains
**placeholders only**.

**Never commit secrets.** `.env` and every `.env.*` variant except `.env.example` are git-ignored.

---

## Contributing

- Implement **one Story at a time** (Development Blueprint §1).
- Read the relevant approved documents before modifying code.
- Never trust a frontend-supplied `workspace_id`; resolve the Workspace from the URL slug
  server-side and verify Membership.
- Commits use `type(scope): message`, e.g. `feat(accounts): add custom user model`.
- Update `PROGRESS.md` as part of completing a Story.
- If you hit a decision listed in `docs/MISSING_DECISIONS.md`, **stop and ask** — do not guess.

---

## Status

Implementation in progress. See [`PROGRESS.md`](PROGRESS.md) for what is done, what is in progress,
and what comes next.
