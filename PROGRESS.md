# FitOps — Implementation Progress

> **This is the persistent implementation handoff document.** Any AI agent picking up FitOps reads
> `CLAUDE.md`, then this file, then `docs/MISSING_DECISIONS.md`, then the authoritative
> documentation for the current Story — **before writing any code**.
>
> **Source-of-truth priority:**
> 1. Approved architecture/product documentation (`docs/`)
> 2. `docs/MISSING_DECISIONS.md`
> 3. `PROGRESS.md` (this file)
> 4. Implementation/code
>
> This file records **implementation state and handoff context only**. It never overrides an
> approved architecture decision. **If this file conflicts with the authoritative documentation,
> stop and report the conflict** — do not resolve it by following this file.
>
> **Accuracy rule:** never record a completed Story, test result, file change, decision, date, or
> bug fix that did not actually happen. If something is unknown, write
> **"Unknown / not verified."**
>
> **Taking over the Master role?** Also read **`docs/MASTER_HANDOFF.md`** — the operational handoff
> covering the delegation model, worker permissions, verification rules and environment. It has
> **no architecture authority**; this file and the approved documents outrank it.

---

## Current Status

| Field | Value |
|---|---|
| **Current phase** | Implementation |
| **Current Epic** | Epic 01 — Project Foundation |
| **Current Epic** | Epic 02 — Authentication & Identity |
| **Current Story** | Story 2.5 — Email Verification — **COMPLETE and merged** (2026-08-17) |
| **Overall status** | ✅ Epic 01 COMPLETE (8/8). **Epic 02 in progress — Stories 2.1–2.5 complete**; Story 2.6 NOT started |
| **Execution model** | Delegated. Claude = Master; workers = Codex / AGY / OpenCode via `delegate-skills` |
| **Last updated** | 2026-08-15 |
| **Current AI/agent** | Claude Opus 5 (Claude Code session) |

**Repository state:** git repository initialized on branch `main`, working tree clean. Story 1.1
complete; one approved documentation correction applied since (ERD §24 repository tree). Monorepo skeleton, `.gitignore`, `.env.example` and `README.md` in place. **No
application code yet** — Django arrives in Story 1.2, Next.js in Story 1.3, `docker-compose.yml` in
Story 1.6.

**Documentation baseline:** Architecture **v1.2.1** (approved and locked).

Files currently in the repository:

```
CLAUDE.md
PROGRESS.md                                                  (this file)
docs/MISSING_DECISIONS.md
docs/01-product/fitops_mvp_spec_v1.md
docs/02-architecture/fitops_technology_stack_v1.md
docs/02-architecture/fitops_database_auth_architecture_v1.md
docs/02-architecture/fitops_api_specification_v1.md
docs/02-architecture/fitops_erd_django_repository_architecture_v1.md
docs/03-development/fitops_development_blueprint_v1.md
docs/04-design/design.md
```

**Implementation is authorized and has begun** (user instruction, 2026-08-14). Work proceeds one
Story at a time; do not start the next Story without approval.

---

## Completed

> **Story 1.7 — Testing and Quality Baseline** is also COMPLETE and accepted. Because of its
> length it is recorded in its own **"Completed — Story 1.7"** section further down this file,
> below *In Progress*. Stories 1.1–1.7 are all complete; Epic 01 has 8 Stories.

### Story 1.6 — Docker Compose  (Epic 01 — Project Foundation)

| Field | Value |
|---|---|
| **Status** | ✅ COMPLETE |
| **Date** | 2026-08-15 |
| **Execution** | Master verified Docker; one bounded Codex task; **one bounded rework** (libpq); Master ran all live verification |
| **Commit** | `1d231c9` |

**Acceptance criteria — 2/2 PASS, verified functionally rather than by container state:**

| AC | Evidence |
|---|---|
| Entire stack starts with Docker Compose | `COMPOSE_UP_EXIT=0`; all six services running; postgres and redis `healthy`; backend log `System check identified no issues`, Django 6.0.7 serving on 0.0.0.0:8000; celery log `celery@930981157f5b ready.`; **0 exceptions in either log** |
| Services communicate correctly | Django → **`172.18.0.2:5432`** (a Docker network address, proving the Compose DB not the native one), query `6*7=42` · Celery broker `redis://redis:6379/0`, `ping → pong`, `health_check.delay()` round-trip → `"ok"`, `successful True` · nginx `/` → 200 proxied to frontend, `/api/` → 200 to backend · direct `:3000` and `:8000` → 200 · container DB/Redis reachable on host `5433`/`6380` |

**Approved port strategy implemented correctly:** host `5433→5432` and `6380→6379`; **all in-network
traffic uses `postgres:5432` and `redis:6379`**, never the host ports — confirmed at runtime, not
just by reading the file.

**Native services untouched throughout.** Verified *while the stack was up* and *after teardown*:
native PostgreSQL :5432 answering, native Redis :6379 `PONG`, Story 1.4's `fitops` database intact at
**18 `django_migrations` rows**, both Homebrew services still `started`. The Compose PostgreSQL
started empty by design and nothing was migrated, copied or referenced from the native database.

**Teardown:** `docker compose down --remove-orphans` → exit 0, **0 containers remaining**, network
removed, host ports 5433/6380/3000/8000/80 all released, native 5432/6379 still held by Homebrew.

**Delivered:** `docker-compose.yml` at repo root · `infrastructure/docker/{backend,frontend}.Dockerfile`
· `infrastructure/nginx/dev.conf` · `.dockerignore`. backend+celery share `fitops-backend:dev`;
frontend uses an anonymous volume so the bind mount cannot shadow `node_modules`; both images
non-root; no secrets (`${VAR:-development-only-change-me}` throughout); **0 changes to backend or
frontend source**.

#### Rework — missing system library (caught only by reading logs)

`docker compose ps` reported backend as **`Up`** while it was completely non-functional. Both backend
and celery were failing with:

```
django.core.exceptions.ImproperlyConfigured: Error loading psycopg2 or psycopg module
```

Probing the image directly: `import psycopg` → `no pq wrapper available … libpq library not found`;
`ldconfig -p | grep -c libpq` → **0**. `psycopg==3.3.4` is the pure-Python implementation and needs
the `libpq` system library at runtime; the host has it via Homebrew PostgreSQL (which is why Stories
1.2/1.4/1.5 passed), but `python:3.14-slim` does not ship it.

Fixed in **Story 1.6's own file** — `infrastructure/docker/backend.Dockerfile` now installs `libpq5`
(runtime only, apt lists cleaned in the same layer, before `USER fitops`). **`requirements.txt` was
deliberately NOT changed and `psycopg[binary]` deliberately NOT substituted** — the pin is correct
for a host with libpq; the container image was the gap. Proof: `import psycopg` in the rebuilt image
→ exit 0, `psycopg 3.3.4 OK`.

**Lesson recorded: `docker compose ps` = `Up` is NOT evidence a service works.** Django's `runserver`
stays alive while unable to load its database backend. Application logs and functional probes are
authoritative. Had the review stopped at container state, a stack with two dead Python services would
have been reported as a partial pass.

---

### Story 1.5 — Redis + Celery  (Epic 01 — Project Foundation)

| Field | Value |
|---|---|
| **Status** | ✅ COMPLETE |
| **Date** | 2026-08-15 |
| **Execution** | Master preflighted Redis and provisioned dependencies; one bounded Codex task implemented; Master reviewed and ran all runtime verification |
| **Commit** | `a70c73f` |

**Acceptance criteria — 2/2 PASS, proven against live Redis 8.10.0:**

| AC | Evidence |
|---|---|
| Celery worker starts | `celery@Momens-Mac-mini.local v5.6.3` · transport `redis://localhost:6379/0` · results `redis://localhost:6379/0` · concurrency 1 (prefork) · `[tasks] . common.tasks.health_check` · **`ready.`** · process alive · clean SIGTERM shutdown |
| Celery communicates with Redis | `app.control.ping()` → `[{'celery@…': {'ok': 'pong'}}]` · `health_check.delay()` → task `cd99a051-…` → **result `"ok"`**, `successful() True` — a full round trip through Redis |

**Redis preflight (inspection only, nothing installed or modified):** redis-server + redis-cli
present at `/opt/homebrew/bin` · server PID 1456 listening on `127.0.0.1:6379` and `[::1]:6379` ·
`PING → PONG` · raw TCP connect OK · Homebrew formula installed, service `started` · **Redis 8.10.0**.

**Provisioned by Master (network work):** `celery==5.6.3`, `redis==8.1.0` — pinned to the versions
actually installed, not guessed. No transitive pins, no flower, no `django-celery-beat`, no
`django-celery-results`.

**Implemented:** CELERY settings section in `base.py` (env-driven from `CELERY_BROKER_URL` with
`REDIS_URL` fallback; result backend defaults to the broker so no new required env var appears) ·
`config/celery.py` creating the `fitops` app with the `CELERY` namespace and `autodiscover_tasks()` ·
`config/__init__.py` exporting `celery_app` · `common/tasks.py` with the single `health_check` task.

**Security:** JSON-only serialization enforced — `task_serializer`, `result_serializer` and
`accept_content` all `json`, verified at runtime. Serializers capable of executing arbitrary code on
untrusted payloads are not accepted. Broker URL carries no credentials; local Redis needs no auth.

**Architecture guard held.** `autodiscover_tasks()` conventionally scans `INSTALLED_APPS`, but
`common` is deliberately **not** a Django app (ERD §23: shared infrastructure, not a business
domain). The brief forbade adding it to `INSTALLED_APPS` and required a stop-and-report if the
worker thought otherwise. Codex complied — it imported `common.tasks` explicitly in `celery.py` with
a comment explaining why. **INSTALLED_APPS/LOCAL_APPS unchanged.**

**Scope held — deliberately NOT implemented:** Docker/compose (Story 1.6) · Celery Beat / periodic
schedules · every real background job named in the Technology Stack (notifications, email sending,
image processing, subscription reminders, billing renewal alerts, workspace retention cleanup,
check-in reminders) — those belong to their owning Epics · models, migrations, views, serializers,
URLs, admin · frontend and docs untouched · root `.env.example` unmodified.

Verified: exactly one `@shared_task` exists in the entire backend; 5 files changed, all under
`backend/`; no secrets.

**Delegation note:** the brief stated the socket constraint up front (learned in Story 1.4), listed
only socket-free verification commands, and explicitly forbade `celery worker`, `celery inspect`,
`redis-cli` and `app.control.ping()` in the worker — so Codex did not waste a run failing on them.
Master performed all runtime verification. This pattern should be reused for every Story with a
live-service acceptance criterion.

---

### Story 1.4 — PostgreSQL Setup  (Epic 01 — Project Foundation)

| Field | Value |
|---|---|
| **Status** | ✅ COMPLETE |
| **Date** | 2026-08-15 |
| **Execution** | Master provisioned role+database (user-authorised); single Codex task dispatched, hit its connectivity gate and correctly stopped; Master performed verification |
| **Repository changes** | **NONE** — a legitimate outcome; the DATABASES config from Story 1.2 already pointed at `fitops`/`fitops` |

**Acceptance criteria — 2/2 PASS, Master-verified:**

| AC | Evidence |
|---|---|
| Django migrations execute | `migrate` applied 18 migrations across `contenttypes`, `auth`, `admin`, `sessions` — all `OK`. `migrate --check` EXIT=0, no pending migrations |
| Database connection is stable | Connected as `('fitops','fitops')` using the FitOps config with **no `.env`** (defaults apply); **5/5** consecutive connect→query→close cycles OK |

**Provisioning performed by Master (explicitly user-authorised):**

| Object | Result |
|---|---|
| Role `fitops` | `LOGIN`, `CREATEDB`, **NOT superuser** (least privilege) |
| Database `fitops` | owner `fitops`, UTF8 |

**Pre-flight before any mutation:** role absent (count 0), database absent (count 0) — both verified
read-only first. Creation used guarded, idempotent SQL.

**Safety verified after the change:** `couch` (owner momen), `erp` (owner erp), `postgres`
(owner momen) all intact with original owners; roles `erp` and `momen` untouched; no `DROP` of any
pre-existing object; `pg_hba.conf` and `postgresql.conf` unmodified.

**No credential invented or committed.** `pg_hba.conf` uses `trust` for local/127.0.0.1 (standard
Homebrew dev configuration), so Django's existing empty-string password default works. Nothing
secret was written to any file, and no `.env` was created.

**Schema created (10 tables in `public`):** `auth_group`, `auth_group_permissions`,
`auth_permission`, `auth_user`, `auth_user_groups`, `auth_user_user_permissions`,
`django_admin_log`, `django_content_type`, `django_migrations`, `django_session`.

#### Test database strategy — verified by capability proof, and why

`manage.py test` reported **"Skipping setup of unused database(s): default"** because zero tests
exist yet, so that run proved *nothing* about test-database creation. Verified directly instead:
role `fitops` created `test_fitops_probe` (owner `fitops`) and dropped it successfully — exactly the
`CREATEDB` capability Django's test runner requires for `test_fitops`.

Strategy: Django's default naming (`test_` + NAME). **No `TEST` block was added** — the default is
the strategy, and adding one speculatively would be invention. The full path will be exercised when
Story 1.7 introduces the first tests.

#### Delegation outcome — worker blocked, gate worked as designed

The Codex sandbox **cannot open sockets at all, including localhost**:

```
psycopg.OperationalError: connection to server at "127.0.0.1", port 5432 failed:
Operation not permitted
```

The brief's Step 0 connectivity gate caught this: the worker **stopped immediately, changed nothing,
and reported the exact error** rather than switching to SQLite or altering settings. Master then took
over verification, as the brief specified.

**Carry-forward, generalising the Story 1.2/1.3 finding:** worker sandboxes have no network **and no
local socket access**. Any task requiring a live database, package install, or dev-server boot must
be verified by Master. Briefs should include an explicit early gate so workers fail fast and cleanly
instead of improvising.

---

#### Corrective defect — `package-lock.json` was not cross-platform (fixed `5d5441a`)

**Discovered:** during **Story 1.6** Docker Compose build verification, not during Story 1.3's own
acceptance. The Story 1.3 gates (`typecheck`, `lint`, `build`, dev-server boot) all ran on the host
and passed legitimately — the defect only surfaces when dependencies are resolved on Linux.

**Why it belongs to Story 1.3:** `frontend/package-lock.json` is a Story 1.3 artifact. It was
generated on **Darwin arm64** and omitted the optional-dependency entries npm resolves on
**Linux aarch64**. Story 1.6 merely exposed it. Fixing it inside Story 1.6 would have widened that
Story's scope, so it was corrected separately.

**Symptom (Story 1.6 frontend image build, exit 1):**

```
npm error code EUSAGE
`npm ci` can only install packages when your package.json and package-lock.json are in sync.
Missing: @emnapi/runtime@1.11.3 from lock file
Missing: @emnapi/core@1.11.3 from lock file
```

**Correction:** `cd frontend && npm install --package-lock-only` — user-approved, run by Master.

**Diff audit before committing:**

| Check | Result |
|---|---|
| `package.json` | byte-identical, 0 changes ✅ |
| Packages added | 4, all nested under `@tailwindcss/oxide-wasm32-wasi` (Linux WASM fallback) |
| Packages removed | 0 |
| **Version changes** | **0** |
| Root `dependencies` / `devDependencies` | identical ✅ |
| `lockfileVersion` | 3 → 3, unchanged |

#### ⚠️ RETRACTION — the first verification was INVALID and `5d5441a` was ineffective

**The claim that `5d5441a` was "proven before being committed" was FALSE.** Retracted in full.

The verification command was:

```
npm ci --silent 2>&1 | tail -5; echo NPM_CI_EXIT=$?
```

`$?` captured **`tail`'s** exit code, not npm's. `tail` succeeded, so it printed `NPM_CI_EXIT=0`
while npm was failing underneath. Re-run correctly, the same lockfile gives **`REAL_NPM_CI_EXIT=1`**.

This is the exact pipe-masking trap already recorded as a standing lesson during Story 1.3's shadcn
failures — *"never read a piped command's exit code as the tool's exit code"* — and it was repeated
anyway. Two compounding process failures: trusting a pipeline exit code, and letting a passing test
override contradicting evidence instead of reconciling them.

**`5d5441a` was harmless but ineffective:** 0 version changes, `package.json` untouched, 4 WASM
fallback entries added — but `npm ci` still failed on Linux. It is superseded by `557da30`, not
reverted, so the history of the investigation stays legible.

#### Effective correction — regenerate on the TARGET platform (`557da30`)

Root cause of the failed first attempt: `npm install --package-lock-only` run **on macOS** resolves
macOS's dependency view. It can never produce the Linux-only branch of the graph. The fix is to
resolve on the target:

```
docker run --rm -v "$PWD/frontend:/app" -w /app node:24-slim npm install --package-lock-only
```

**Diff audit (vs `5d5441a`):**

| Check | Result |
|---|---|
| `package.json` | byte-identical, 0 changes ✅ |
| Added | 4 — `@emnapi/core@1.11.3` + `@emnapi/runtime@1.11.3` at top level (exactly what npm demanded), plus two nested at 1.11.1 |
| Removed | 0 |
| **Version changes** | **0** |
| Root `dependencies` / `devDependencies` | identical ✅ |

**Verification — real exit codes, no pipelines, corroborated:**

| Environment | Command | Real exit code | Corroboration |
|---|---|---|---|
| macOS host | `npm ci` in `frontend/` | **0** | `added 666 packages, audited 667` |
| Linux container | `docker compose build --no-cache frontend` | **0** | image `fitops-frontend:latest` exists (413 MB); **0 `npm error` lines** in the log |

**Both platforms accept the lockfile** — it is genuinely cross-platform, not Linux-only. The 1.11.3
entries are additive and displace nothing macOS needs.

**Standing verification rule now in force:** never report PASS from output text. Capture the real
process exit code, inspect the output, reconcile contradictory evidence, and only then judge. Where
a pipeline is unavoidable, use `set -o pipefail` or `PIPESTATUS`.

**Deliberately NOT done:** the Dockerfile keeps `npm ci`. Relaxing it to `npm install` would have
masked the real defect and given up reproducible builds. `package.json` untouched; no dependency
versions changed; no backend or frontend source modified.

**Lesson:** host-generated lockfiles are not automatically portable. Any Story whose acceptance runs
only on the host can hide a platform-resolution defect that surfaces later in containerised builds.

### Story 1.3 — Next.js Frontend Setup  (Epic 01 — Project Foundation)

| Field | Value |
|---|---|
| **Status** | ✅ COMPLETE |
| **Date** | 2026-08-15 |
| **Execution** | Option A: Master provisioned the network-bound scaffold; **one** bounded Codex task implemented; Master reviewed, sent one bounded rework, and accepted |
| **Commit** | `49f40a5` |

**Acceptance criteria — 3/3 PASS, verified from a clean `.next` state:**

| AC | Evidence |
|---|---|
| Frontend builds successfully | `npm run build` EXIT=0 — compiled in 1548ms, routes `/` and `/_not-found` prerendered static |
| Development server works | `npm run dev` → `▲ Next.js 16.3.1 (Turbopack)`, `✓ Ready in 157ms`, **HTTP 200** on `/`, page contains "FitOps" and "foundation is running", **zero** create-next-app demo content, clean shutdown, port released |
| Basic application shell exists | Root layout with metadata + Providers; minimal placeholder page; no product UI |

Also green: `npm run typecheck` EXIT=0 and `npm run lint` EXIT=0, both from a clean checkout.

**Stack provisioned (Master, network-bound only) — all traced to the approved Technology Stack:**

Next.js 16.3.1 · React 19.2.8 · TypeScript 5 (strict, `@/*`) · Tailwind CSS 4 · **shadcn/ui on Radix
UI** (`style: radix-nova`, `iconLibrary: lucide`) · react-hook-form 7.85.0 · zod 4.4.3 ·
@tanstack/react-query 5.101.4 · eslint 9. **Nothing outside the approved stack was installed.**

**Implemented by Codex (one task):** package identity `fitops-frontend` · root layout + metadata ·
`Providers` creating the QueryClient via `useState(() => …)` **per session, never at module scope**
(prevents cache leaking across server requests) · `lib/query-client.ts` · `lib/validation.ts` with a
single generic example schema · minimal placeholder page, demo content removed ·
`frontend/.env.example` with only `NEXT_PUBLIC_API_URL` · `typecheck` script.

**Rework — one round, bounded, same Codex session:** `npm run typecheck` failed from a clean
checkout with `TS2304: Cannot find name 'LayoutProps'`. Root cause: `LayoutProps<"/">` is a Next.js 16
**generated** global type in `.next/types/`, a git-ignored build artifact. Fixed by changing the
script to `next typegen && tsc --noEmit`. `layout.tsx` was explicitly left unchanged — the
`LayoutProps` usage is correct and idiomatic. **The defect originated in Master's brief**, which
specified the naive script; recorded rather than blamed on the worker.

**Scope held — deliberately NOT implemented:** the ERD §25 route tree (`(marketing)/`, `auth/`,
`onboarding/`, `admin/`, `[workspaceSlug]/**` — owned by Epics 06–19) · product UI · marketing pages ·
dashboard/portal screens · auth flows · API integration (0 fetch/axios/apiClient references) ·
business logic · the design system (0 design.md tokens in `globals.css`) · shadcn components
(`components/ui/` empty) · tests/lint baseline (Story 1.7) · Docker/CI (Stories 1.6/1.8).

Verified: 0 changes outside `frontend/`; `backend/`, `docs/`, `CLAUDE.md`, `.gitignore` and the root
`.env.example` all untouched; no secrets. `.gitkeep` removed only from `app/` and `lib/` (which now
hold real files); `components/`, `features/`, `hooks/`, `types/` correctly keep theirs.

#### Decision recorded — shadcn/ui primitive library

**`shadcn/ui` → Radix UI** (user decision, 2026-08-14). Base UI and React Aria explicitly rejected.
Recorded as an implementation decision; **architecture documents were not modified**, since the
Technology Stack already says "shadcn/ui" and no approved document names a primitive library.

**Open divergence for a later UI Story:** the `nova` preset ships **Geist**, while design.md §8
mandates **Inter**. Theme tokens are out of Story 1.3 scope; design.md remains authoritative and was
not modified.

**Not installed, deliberately:** `@hookform/resolvers` — the canonical RHF↔Zod bridge, but not in the
approved stack. The first Story that builds a real form will need it.

#### Incident — Next.js generates `AGENTS.md` and `CLAUDE.md` on every `next dev`

During the dev-server acceptance check, Next.js created **two** untracked files at `11:16:11`:

| File | Size | Content |
|---|---|---|
| `frontend/AGENTS.md` | 678 B | Next.js agent rules block |
| `frontend/CLAUDE.md` | 11 B | `@AGENTS.md` — a pointer |

Both are written by `frontend/node_modules/next/dist/server/lib/generate-agent-files.js`. The file
says so itself: *"This block is written and re-added by `next dev` … Removing it from a diff only
re-creates the uncommitted change."*

- **This is NOT the Story 1.2 artifact.** That one was 43,527 bytes and a copy of `CLAUDE.md` with
  Claude→Codex rewrites. Contents verified different. The two incidents are unrelated phenomena and
  must not be conflated.
- Both deleted per the standing rule. Neither was ever committed (0 commits in history).
- Root `CLAUDE.md` verified unmodified, sha `9616a81c67d0e0432d6bff3370f9454a6c87b090`.

**⚠️ UNRESOLVED POLICY CONFLICT — needs a user decision.** `next dev` will regenerate both files on
every run, so the frontend working tree cannot stay clean during normal development. This collides
with two standing rules: "AGENTS.md must NOT exist in the repository" and "do NOT add AGENTS.md to
`.gitignore`". Next.js's own recommendation is to commit them. **No policy chosen; nothing
gitignored.** Options: (a) delete each time and accept a permanently dirty dev tree, (b) commit both
as framework artifacts, (c) gitignore them, reversing the earlier decision, (d) disable the
generator if Next.js supports it.

---

### Story 1.2 — Django Backend Setup  (Epic 01 — Project Foundation)

| Field | Value |
|---|---|
| **Status** | ✅ COMPLETE |
| **Date** | 2026-08-14 |
| **Execution** | Delegated via `delegate-skills`; Claude as Master, 8 worker tasks + 1 Master acceptance task |
| **Final commit** | `f830aa1` (tree verified clean after T9) |

**Acceptance criteria — 3/3 PASS, all Master-verified:**

| AC | Evidence |
|---|---|
| Django starts successfully | Real `runserver` boot: process alive, **HTTP 200**, Django 6.0 welcome page served, **clean SIGTERM shutdown**, port released. With `DEBUG=False`, `/` correctly returns 404 (no routes registered yet — stock Django behaviour for an empty urlconf) |
| Database connection works | Final settings: `ensure_connection()` OK · `PostgreSQL 16.13` · session `('postgres','momen',5432)` · ORM round-trip `40+2=42` · `vendor=postgresql driver=psycopg` · `is_usable=True` · closed cleanly |
| All approved apps load correctly | All nine load; `LOCAL_APPS` order **exactly matches canonical**; `coaching` is one app (no `plans`/`checkins`); `audit` present; no extra apps; 16 registered (6 django + 1 drf + 9 local) |

**Task ledger (all reviewed by Master before landing):**

| Task | Worker | Commit | Result |
|---|---|---|---|
| T1 Django skeleton, split settings, env loading, requirements, `common/` | Codex | `89ea8e5` | ✅ PASS |
| T2 Nine canonical app packages | OpenCode/GLM | `a2b8988` → merged `f4a0292` | ✅ PASS |
| T3 Register nine apps in INSTALLED_APPS | Codex | `2bc78e3` | ✅ PASS |
| T4 DRF (session auth, IsAuthenticated, pagination) | Codex | `56658c4` | ✅ PASS |
| T5 Sessions, cookie security, CSRF | Codex | `ac106f1` | ✅ PASS |
| T6 PostgreSQL from environment | OpenCode/GLM | `842440f` | ✅ PASS |
| T7 Email backend + SMTP from environment | OpenCode/GLM | `8182cab` | ✅ PASS |
| T8 Static/media handling | OpenCode/GLM | `fc76c76` | ✅ PASS |
| T9 Final acceptance + regression | Claude (not delegated) | — | ✅ 3/3 AC PASS |

**Whole-Story regression pass (T9) — all clean:** working tree clean, 1 worktree, 20 commits ·
only `.env.example` tracked, `.env` ignored · no `UserSession`/`token_hash`/JWT/`authtoken`/
`TokenAuthentication` · SessionAuthentication only + `IsAuthenticated` + `FitOpsPageNumberPagination`
(20/`page_size`/100) · session db engine, HttpOnly session cookie, readable CSRF cookie, SameSite Lax,
prod Secure flags not env-overridable · PostgreSQL engine · SMTP env-wired with **no provider
selected** · static/media on local `FileSystemStorage`, no cloud/S3/boto3/django-storages ·
**0 models, 0 migrations, 0 views/serializers/urls, 0 routes** · `common/` skeleton-only (all 0 bytes
except the 200-byte approved paginator) · **`docs/` untouched by every commit, `MISSING_DECISIONS.md`
unchanged with B24–B27 intact, `CLAUDE.md` unmodified** · every change confined to `backend/` +
`PROGRESS.md`; `frontend/`, `infrastructure/`, `docker-compose.yml` untouched.

**Master decisions surfaced and approved during this Story:** DRF `DEFAULT_PERMISSION_CLASSES =
IsAuthenticated` (deny-by-default; public endpoints opt out per-view later) · stdlib-only env loading
(no new dependency) · Django version chosen empirically, not guessed · T8 reassigned AGY → OpenCode/GLM.

**Deliberate exclusions (other Stories own them):** authentication rate limiting (Epic 20) · logout
endpoint (Epic 02) · SSL/HSTS/security headers (Story 21.2) · storage abstraction
`backend/common/storage/` (later Story) · creating the `fitops` database and role (**Story 1.4**) ·
custom DRF error envelope (later API/error-handling Story).

#### Incident — `AGENTS.md` artifact

An untracked `AGENTS.md` (43,527 bytes, a copy of `CLAUDE.md` with 4 "Claude"→"Codex" rewrites)
appeared in the repository root **twice**: once during T1, and again at `22:40:56` — *after* every
delegated task had completed and *after* T8 was committed at `22:38:21`, when `git status` was
verifiably clean.

- **Never committed. 0 commits in history, both times.**
- Removed by Master on both occasions; deleted again during T9 cleanup.
- `CLAUDE.md` itself verified unmodified in the working tree and in every Story 1.2 commit.
- **Attribution: NOT determined, and deliberately not invented.** Observation only: the ChatGPT
  desktop app's Codex processes launched 22:40:49–22:40:54, 2–7 seconds before the file appeared.
  Correlation is recorded; causation is not asserted.
- Classification: **non-blocker** — untracked, affects no acceptance criterion, zero effect on the
  application.
- **`.gitignore` was deliberately NOT updated** (user decision), so any future reappearance stays
  visible as an unintended artifact rather than being silently hidden.

#### Process finding — stale worker processes

T9 investigated the four long-running `codex` / `opencode` / `agy` processes found in the repo.

- **None belong to this delegation session.** All started 21:19–21:24, before the first dispatch at
  21:48, and all are children of `/bin/zsh -il` inside **Antigravity IDE terminals** — the user's own
  interactive CLI sessions.
- **This delegation left zero stale processes**: every `relay.mjs` and its child had exited.
- Therefore **nothing was terminated**. Killing them would have destroyed the user's own work and
  violated "do not kill unrelated user/system processes".

**Process lesson (binding for future Stories): worker processes must be confirmed terminated before
Story-level acceptance is finalised.** A worker side-effect landed *after* review and *after* commit,
so a clean tree at land-time is not a durable guarantee. Story acceptance must re-verify
`git status -uall` after a settle window — as T9 did (20-second window, tree signature stable).

**Final tree state at acceptance:** `git status -uall` empty · 0 untracked files · `AGENTS.md` absent ·
`CLAUDE.md` sha `9616a81c67d0e0432d6bff3370f9454a6c87b090` unchanged · `.gitignore` unmodified ·
`docs/` unmodified · HEAD `f830aa1` on `main`.

---

### Story 1.1 — Monorepo Setup  (Epic 01 — Project Foundation)

| Field | Value |
|---|---|
| **Status** | ✅ COMPLETE |
| **Date** | 2026-08-14 |
| **Commit** | `6d3eedd chore(repo): initialize fitops monorepo structure` |

**Implementation summary:** initialized the git repository on branch `main` and created the monorepo
skeleton defined in ERD/Repository Architecture §24, plus the root `README.md`, `.gitignore` and
`.env.example`. No application code — this Story is structure and configuration only.

**Files/modules changed:**

- `README.md` — new. Product summary, documentation index, repository structure, stack table, local
  setup instructions, environment-variable policy, contributing rules.
- `.gitignore` — new. Ignores `.env` and every `.env.*` except `.env.example`, plus `*.pem`/`*.key`,
  Python/Django, Node/Next.js, test/coverage, backup and editor artifacts.
- `.env.example` — new. Placeholders only, grouped by the Story that consumes each variable
  (Django core, session/CSRF security, PostgreSQL, Redis/Celery, SMTP email, media storage,
  frontend).
- `frontend/{app,components,features,lib,hooks,types}/.gitkeep` — new directories.
- `backend/{config,apps,common,tests}/.gitkeep` — new directories.
- `infrastructure/{docker,nginx,scripts,backups}/.gitkeep` — new directories.
- `docs/` — unchanged; already matched ERD §24.

**Tests/checks performed:** no automated test framework exists yet (Story 1.7). Verification was
structural and executed against the real repository — see *Tests & Verification*. All three
acceptance criteria and both DoD items verified and passing.

**Acceptance criteria verification:**

| Criterion | Result | Evidence |
|---|---|---|
| Repository structure matches architecture document | ✅ PASS | 15/15 required directories and 3/3 required root files present |
| No secrets are committed | ✅ PASS | Only `.env.example` tracked; `.env` ignored via `.gitignore:4`; secret-pattern scan found nothing |
| Local setup instructions exist | ✅ PASS | `README.md` "Local setup" section with prerequisites and clone/configure steps |
| **DoD** — Clean clone can initialize successfully | ✅ PASS | Cloned to a temp dir; full structure present, no `.env`, `cp .env.example .env` succeeded and was correctly ignored |
| **DoD** — README explains setup | ✅ PASS | Verified in the clone |

Documentation work completed to date (not implementation — recorded for context only):

| Date | Work | Result |
|---|---|---|
| 2026-08-14 | Documentation review and consolidation | `CLAUDE.md` created as implementation guide/index |
| 2026-08-14 | Architecture v1.1 reconciliation | 12 decisions applied; docs restructured to `docs/NN-*`, renamed to FitOps |
| 2026-08-14 | Final v1.1 decisions | Decisions 13–18 (sessions, payments, client nav, epic count, SMTP, approved inferences) |
| 2026-08-14 | FitOps Billing discovery → approval | Architecture v1.2: billing domain, `billing` app, Epic 22 |
| 2026-08-14 | Lifecycle & payment rules | Architecture v1.2.1: retention/archive/restoration, Coach-commerce `Payment.status` |
| 2026-08-14 | Missing-decisions registry | `docs/MISSING_DECISIONS.md` created (B24–B27 + SMTP) |

---

## In Progress

**No Story currently in progress.** Story 2.5 is complete and merged; Story 2.6 has not started.

---

## Completed — Story 2.5

### Story 2.5 — Email Verification  (Epic 02 — Authentication & Identity)

**Status:** ✅ **COMPLETE** — **PR #6 merged as `8c3b016d82d196af8a380f8c51977d8661e3e966`** on
2026-08-17. Verified: `origin/main` equals that SHA from both git and the GitHub API, and the merge
introduced exactly the six Story 2.5 files and nothing else.

**Blueprint §7 Story 2.5:** implement `POST /auth/email/verify` and `POST /auth/email/resend`.
Requirements: *Expiring token · Secure token storage · Rate limiting · Generic responses where
necessary.*

---

#### 🔒 BINDING STORY 2.5 DECISIONS (user, 2026-08-16)

**Why these are recorded verbatim:** the Story 2.5 preflight found that the authoritative documents
specify **no numeric rate limits, no token expiry, no single-use requirement, and no response
bodies or status codes** for either endpoint. Rather than invent them, they were reported as
blockers and resolved explicitly. **Future agents must not rediscover, reinterpret, or "improve"
these values — they are decisions, not derivations.**

**1. Rate limiting — scoped throttles only**

| Endpoint | Rate |
|---|---|
| `POST /api/v1/auth/email/resend` | **3 requests/minute** |
| `POST /api/v1/auth/email/verify` | **10 requests/minute** |

**Do NOT introduce global throttling.** Scoped, per-endpoint throttles only. API §22 mandates rate
limiting for *email verification* but specifies no numeric rate anywhere in the API Specification or
Blueprint — these numbers are this Story's decision. Note Blueprint **Story 20.3 — Authentication
Hardening** owns *OTP* and *login* rate limits and does **not** list email verification, so there is
no ownership conflict.

**2. Verification token**

- Keep the **stateless `default_token_generator`** approach. **NO token model.** None exists in the
  approved architecture and none may be added.
- **Single-use**, achieved by incorporating `email_verified_at` into the token hash semantics.
  *Verified empirically during preflight:* Django's stock hash is
  `user.pk + user.password + last_login + timestamp + email`, and setting `email_verified_at`
  changes **none** of those — so the stock token stays valid after use. Single use therefore
  requires a custom generator, still entirely stateless.
- **Expiry: 10 minutes.** Django's default is `PASSWORD_RESET_TIMEOUT` = 259200 s (3 days), which
  was never set in this project. ⚠️ The 10-minute window must be applied **without** changing the
  global `PASSWORD_RESET_TIMEOUT`, which would also shorten password-reset tokens in Story 2.10.
- ⚠️ **Story 2.4's registration email must issue tokens from the same generator**, otherwise tokens
  issued at registration will not verify.

**3. `POST /auth/email/verify`**

- Public / `AllowAny`. Success **HTTP 200** with `{"message": "Email verified successfully."}`.
- Sets `User.email_verified_at`.
- Invalid **or** expired token → **HTTP 400** using the existing `VALIDATION_ERROR` envelope with a
  **generic** message. **Do not reveal which of the two occurred.**

**4. `POST /auth/email/resend`**

- Public / `AllowAny`. **HTTP 200** always.
- Returns the **same generic success response** whether the email exists, is already verified, or
  does not exist. **Must not allow account enumeration** (API §188 states this explicitly for this
  endpoint, unlike registration where only CLAUDE.md §19 did).
- Sends the email only when appropriate, via `transaction.on_commit()`.
- Must not expose account existence or verification state.

**5. Error handling**

Reuse the Story 2.4 error envelope. **Do not invent new error codes** — the documented
`VALIDATION_ERROR` is sufficient. (`INVALID_OTP` / `OTP_EXPIRED` exist in the closed list but name
the *Client OTP login* flow, not coach email verification.)

---

#### Preflight findings that shaped these decisions

- **No model or migration is required.** `User.email_verified_at` already exists from Story 2.1 as a
  nullable timestamp; there is no boolean flag and none may be added.
- **The "around 10 minutes / one-time use" text in DB & Auth Architecture belongs to the OTP
  Security section** (Client OTP login), **not** coach email verification. It was checked in context
  specifically to avoid misapplying it as a documented requirement.
- **No throttle configuration existed anywhere in the codebase** before this Story.
- The API §2 error envelope from Story 2.4 is live, so new endpoints inherit it automatically.

---

#### Task breakdown — 2 streams, OpenCode deliberately idle

| ID | Task | Complexity | Worker | Allowed files |
|---|---|---|---|---|
| A | Both endpoints: serializers, views, URLs, scoped throttles, custom token generator | Very hard | **Codex** | `accounts/{serializers,views,urls}.py`, `config/settings/base.py` |
| B | Spec-driven API tests | Medium | **AGY** `gemini-3.7-flash-high` | `tests/test_email_verification_api.py` |

**OpenCode stays idle.** Unlike Stories 2.2 and 2.3, preflight found **no** documentation defect to
fix — the API Specification and DB & Auth Architecture agree, and the OTP-vs-verification wording
was verified to be correct in context rather than contradictory. Manufacturing a third stream would
be artificial. A must own `settings/base.py` for throttle configuration, so no other stream may
touch it.

---

#### Two review findings, both fixed by bounded rework

**1. O(n) cryptographic scan on a public endpoint.** The first implementation resolved the user by
iterating **every unverified row** and running an HMAC per row, because the documented request body
is `{"token": ...}` only. With 10,000 unverified users a single request cost 10,000 HMACs — a
request-amplification vector that the 10/min throttle bounds per client but not across rotated
sources.

Fixed by encoding the user id **inside the opaque token** as a `uidb64` prefix, exactly as Django's
own password-reset links do. **The request contract is unchanged** — still `{"token": ...}` — because
the token value is opaque and its internal format is not part of the API contract. Verification now
decodes the uid and performs a single primary-key lookup.

*Proven, not asserted:* a query probe with **26 users** shows verification issues **4 queries** and
does not scale with user count.

⚠️ **Failure-uniformity risk this created, and how it was contained.** The uid path introduced new
ways to fail that the scan did not have — malformed uid, uid decoding to no user, tampered
signature. If any produced a distinct response, the fix would have **reintroduced enumeration
through a side door**. All of them, plus already-verified, return the identical 400.

**2. Missing `fields` in the error envelope.** Invalid-token errors raised a **bare-string**
`ValidationError`, so the API §2 envelope omitted `fields`. This is the **same defect class**
corrected in Story 2.4 (weak password). Fixed to `{"token": [INVALID_VERIFICATION_TOKEN_MESSAGE]}`,
keeping the message identical for invalid and expired.

**3. Test-side, not implementation.** The method-not-allowed tests issued four requests against a
3/minute endpoint, and DRF throttles **before** method dispatch, so the fourth returned 429 rather
than 405. The implementation was correct — the test consumed its own budget. `cache.clear()` now
runs per sub-test, applied to the verify loop too, which was fragile for the same reason.

**Master fixes applied and disclosed** (not folded silently into worker output): the token
extraction helper used a character class excluding `:` and so **silently truncated the uid prefix**
once the token format changed, rejecting valid tokens; it was rewritten format-agnostic. Import
order was corrected for ruff `I001`. **No assertion was changed.**

---

#### Verification and acceptance evidence

**Master-run local verification, real exit codes captured directly (never through a pipe):**

| Check | Exit |
|---|---|
| `manage.py check` default / dev / prod | **0** / **0** / **0** |
| repo-wide `makemigrations --check --dry-run` | **0** — confirming **no model** was introduced |
| Focused Story 2.5 tests | **0** — 31 pass |
| Full suite | **0** — **107 tests** pass against real PostgreSQL |
| `./infrastructure/scripts/checks.sh` | **0** — all 7 gates PASS |
| `cd frontend && npm run build` | **0** — `next-env.d.ts` unchanged |

**Mutation-checked — all five guards proven non-vacuous:**

| Mutation | Result |
|---|---|
| Envelope reverted to a bare-string error | **2 failures** |
| `email_verified_at` dropped from the token hash (breaks single-use) | **2 failures** |
| `resend` returns 404 for an unknown email (breaks anti-enumeration) | **7 failures** |
| Throttle rates widened to 1000/minute | **2 failures** |
| O(1) lookup | proven by query probe — 26 users, 4 queries |

All mutated files were restored **byte-identical** afterwards.

**GitHub CI — accepted run
[31973449870](https://github.com/momenawab/Fitops/actions/runs/31973449870): success.** All 9 steps,
**none skipped**, `107 test(s) collected`, `All 7 gates passed`, plus the separate production build.
Tested merge SHA `592f692 = Merge 4d0748c into 0195260`.

**PR scope correction before merge.** The PR initially carried 7 files because the decisions commit
`0195260` had been committed to local `main` but never pushed. It was fast-forwarded to `main` and
the PR recomputed to **6 code-only files**. This was the **second consecutive Story** with that slip;
the standing correction is to **push tracking commits when they are made, not at PR time**.

**Merge.** PR #6 merged as `8c3b016d82d196af8a380f8c51977d8661e3e966`, using an explicit
`--match-head-commit 4d0748c…` guard after an earlier attempt was rejected for a stale SHA. Verified
post-merge: `origin/main` equals the merge commit from both git and the GitHub API, the merge
introduced exactly the six files, and `checks.sh` exits 0 with 107 tests on the merged tree.

Commits: `81a4f9f` (endpoints) · `4d0748c` (tests).

---

## Completed — Story 2.4

### Story 2.4 — Coach Registration  (Epic 02 — Authentication & Identity)

**Status:** ✅ **COMPLETE** — **PR #5 merged as `36d78af7c163a35f2c2c38a76b01ed8897d6de6d`** on
2026-08-16. Verified: `origin/main` = that SHA, and the merge introduced exactly the seven Story
2.4 code files and nothing else.

**This was the project's first API endpoint.** `backend/config/urls.py` was previously
`urlpatterns = []`, so Story 2.4 also established the routing pattern every later endpoint follows.

**Contract delivered (API Specification §4):**

    POST /api/v1/auth/register        Public        201 Created
    request : {email, password, first_name, last_name}
    response: {"message": "Account created. Please verify your email.",
               "requires_email_verification": true}

---

#### Four preflight gaps found in the authoritative documents, and their resolutions

The preflight deliberately did **not** assume the documents were complete. Four genuine gaps were
found and reported rather than guessed; all four were resolved explicitly by the user:

| Gap | Resolution |
|---|---|
| **No email-verification token model exists anywhere in the approved architecture**, yet Story 2.5 requires "expiring token / secure token storage". `LoginOTP` is the *Client OTP login* mechanism, not coach verification | **Stateless signed token** via `default_token_generator`. **No token model added.** Story 2.4 sends the email after commit; Story 2.5 owns verify/resend |
| **Registration rate limiting is NOT mandated.** API §22's list omits registration; Epic 20 owns authentication rate limiting; no throttle config exists | **No rate limiting added.** Recorded as a known, accepted exposure until Epic 20. An earlier PROGRESS.md revision wrongly claimed it was mandatory — corrected in `b72b7d2` |
| **Anti-enumeration on registration appears only in CLAUDE.md §19**, the lowest-precedence document, which self-declares it adds no requirements. API §130 is silent | **Generic anti-enumeration.** A duplicate returns the identical 201, creates no second user, and deliberately returns **no `CONFLICT`** |
| **The API §2 error envelope was never implemented** — `common/exceptions/__init__.py` was 0 bytes and the work had been deferred to a "later API/error-handling Story". The first endpoint made it due | **Implemented as Stream C.** Only documented codes; no invented codes or semantics |

Also resolved: **HTTP 201** for success, and registration creates **`User` only** — no `CoachProfile`.

---

#### Execution — 3 parallel streams, and a real defect the design caught

| ID | Task | Worker | Files |
|---|---|---|---|
| A | Registration serializer + view + URL wiring | **Codex** | `accounts/{serializers,views,urls}.py`, `config/urls.py` |
| B | Registration API tests (19) | **AGY** `gemini-3.7-flash-high` | `tests/test_registration_api.py` |
| C | API §2 error envelope | **AGY** (separate session/worktree) | `common/exceptions/__init__.py`, `config/settings/base.py` |

OpenCode was **deliberately left idle**: the error envelope is cross-cutting and inherited by every
future endpoint, so it went to the safer worker rather than being handed to the lightest one to keep
it busy.

**B — written from the specification, never having seen A's code — caught a genuine API-contract
violation on first integration:**

```
FAIL: test_weak_password_returns_400_with_validation_error_envelope
AssertionError: None is not an instance of <class 'dict'> : Error 'fields' must be a dictionary.
```

Root cause, confirmed by direct probe rather than inference
(`errors: {'non_field_errors': [...]}`, `keys: ['non_field_errors']`): `validate_password()` raised
inside DRF's **object-level** `validate()` hook propagates as `non_field_errors`, so the §2 envelope
carried no `fields` entry. API §2 requires field-level validation errors under `fields`, and a
password-strength failure is a `password` error.

**Ownership: A.** The envelope (C) and the tests (B) were both behaving to contract. **Bounded
rework** was sent to the **same Codex session**, re-raising as
`serializers.ValidationError({"password": [...]})`. The hook location was deliberately **kept** —
moving to a field-level validator would silently lose `UserAttributeSimilarityValidator`, which
needs the constructed `User`.

**A test suite written from the implementation would have asserted the buggy shape and passed.**
This is the clearest justification so far for writing tests from the specification in parallel
rather than after the fact.

**Master fixes applied and disclosed** (not folded silently into worker output): six ruff `E501`
line-length wraps in B's test file — AGY has no command permissions so it could not run ruff and
miscounted. Message wording only; no test semantics changed.

---

#### Verification and acceptance evidence

**Master-run local verification, real exit codes captured directly (never through a pipe):**

| Check | Exit |
|---|---|
| `manage.py check` default / dev / prod | **0** / **0** / **0** |
| repo-wide `makemigrations --check --dry-run` | **0** — confirming Story 2.4 adds **no model** |
| Registration tests | **0** — 19 pass |
| Full suite | **0** — **76 tests** pass against real PostgreSQL |
| `./infrastructure/scripts/checks.sh` | **0** — all 7 gates PASS |
| `cd frontend && npm run build` | **0** — `next-env.d.ts` unchanged |

**Mutation-checked — both critical guards proven non-vacuous:**

| Mutation | Result |
|---|---|
| Return `409 CONFLICT` for a duplicate email | **2 anti-enumeration assertions fail** |
| Remove `EXCEPTION_HANDLER` from settings | **6 envelope assertions fail** across 4 tests |

Both files restored **byte-identical** afterwards (`views.py` = `8646288f…`).

**GitHub CI — accepted run
[31970203175](https://github.com/momenawab/Fitops/actions/runs/31970203175): success.**
All 9 steps, **none skipped**, `76 test(s) collected`, `All 7 gates passed`, plus the separate
production build. Tested merge SHA `cebb1b7 = Merge 479dec3 into b72b7d2`.

**PR scope correction before merge.** The PR initially carried **8** files because the tracking
commit `b72b7d2` had been committed to local `main` but never pushed, so branching swept it in.
`b72b7d2` was fast-forwarded to `main` and the PR recomputed to **7 code-only files**. Note GitHub
does **not** recompute an open PR's base when the base branch moves, and pushing to `main` fires no
`pull_request` event — the base was forced to recompute with the close/reopen technique established
in Story 1.8, which also triggered the fresh run above.

Commits: `45a90e6` (error envelope) · `360c75a` (endpoint) · `479dec3` (tests).

---

## Completed — Story 2.3

### Story 2.3 — Client Profile  (Epic 02 — Authentication & Identity)

**Status:** ✅ **COMPLETE** — **PR #4 merged as `6c2fdcddcf401740030acfcfb3d697b883bb17d3`** on
2026-08-16. Merge verified: `origin/main` = that SHA, and the merge introduced only the four
Story 2.3 files.

**Authoritative field set** (Database & Auth Architecture §10; the ERD's textual listing agrees
field for field) — **11 fields**:

```
id · user_id · date_of_birth · gender · height · current_weight ·
goal · training_experience · notes · created_at · updated_at
```

**🔒 Locked rule — `ClientProfile` MUST NOT contain `workspace_id`.** Stated in four places:
Blueprint Story 2.3, DB & Auth Architecture §10, the ERD's `# IMPORTANT` note, and CLAUDE.md §8.
Client identity is global; the Client↔Workspace relationship is expressed **only** through
`Membership(role=CLIENT)`.

**Approved field decisions (user, 2026-08-16):** `gender` is a `CharField` with **no choices/enum**
(none is defined in any approved document, so inventing one would add unapproved enum values);
`height` and `current_weight` are **`DecimalField`**s; the user link is a `OneToOneField` to
`AUTH_USER_MODEL` with `related_name="client_profile"` and `CASCADE`; `id` is a UUID primary key.

**⚠️ Documented trap recorded for future agents.** DB §22 / ERD §335 and the API Specification's
public-application JSON contain a **similar-looking but different** field list belonging to the
**`Application`** model: `full_name · email · phone · age · gender · height · weight · goal ·
training_experience · notes`. `Application` has **`age`** and **`weight`**; `ClientProfile` has
**`date_of_birth`** and **`current_weight`**, and has no name/email/phone (that lives on `User`).
Both briefs called this out explicitly so no worker copies the wrong list.

**Second ERD conflict found during preflight** — same class as the CoachProfile one fixed in Story
2.2. The ERD's ASCII diagram shows `DOB`/`weight` and omits `training_experience`, `notes`,
`created_at`, `updated_at`, contradicting both DB §10 and the ERD's own textual listing. Resolved
by CLAUDE.md §23 precedence and assigned to a dedicated worker. Note it is geometrically harder
than the last one: `training_experience` is 19 characters against a 14-character box interior, so
the box must widen and its connector chain into `Membership` must be re-aligned.

**Task breakdown — 3 genuinely independent streams, no manufactured work:**

| ID | Task | Complexity | Worker | Allowed files |
|---|---|---|---|---|
| A | ClientProfile model + migration `0003` | Very hard | **Codex** | `accounts/models.py`, `migrations/0003_*.py` |
| B | Independent model tests | Medium | **AGY** `gemini-3.7-flash-high` | `tests/test_client_profile_model.py` |
| C | ERD ASCII diagram correction | Easy–medium | **OpenCode** `zai-coding-plan/glm-5.3` | ERD markdown |

No file is writable by two workers. B is written from the same authoritative specification as A,
not from A's output, so it remains an independent check — including a dedicated falsifiable guard
that no `workspace_id` / `workspace` / `membership` field or column exists.

All three workers stayed exactly in scope, and AGY reported **zero permission denials**. Its
temporary `write_file(<worktree>)` rule was revoked immediately on completion; the persistent
allow-list remains `command(git status)` only.

---

#### Approved decisions (user, 2026-08-16) — binding

| Field | Decision | Why |
|---|---|---|
| `gender` | **`CharField` with NO `choices` / NO enum** | No gender enum is defined in **any** approved document. Inventing one would introduce enum values outside the approved architecture. A test asserts `choices` is empty, guarding against a later invented enum |
| `height` | **`DecimalField`** (`numeric(5,2)`) | Fractional values must round-trip. No unit field is documented, so units stay implicit |
| `current_weight` | **`DecimalField`** (`numeric(5,2)`) | Same; fractional kilograms are normal in coaching |
| `workspace_id` | **MUST NOT EXIST** | Client identity is global. The Client↔Workspace relationship is expressed **only** through `Membership(role=CLIENT)`. Stated in Blueprint Story 2.3, DB & Auth Architecture §10, the ERD `IMPORTANT` note, and CLAUDE.md §8 |

Also: `user` is a `OneToOneField` to `settings.AUTH_USER_MODEL` (`related_name="client_profile"`,
`on_delete=CASCADE`); `id` is a UUID primary key; **no validators** were added, because no
documented rule constrains date ranges, height/weight bounds, or goal/experience values.

---

#### ERD synchronization performed in this Story

The **second** instance of the ERD-vs-DB conflict (the first, `CoachProfile`, was corrected in
Story 2.2). The ERD's entity diagram showed `DOB` and `weight` and omitted `training_experience`,
`notes`, `created_at` and `updated_at` — contradicting both DB & Auth Architecture §10 and the
ERD's *own* textual listing.

Resolved by CLAUDE.md §23 precedence: the specialized document for the subject governs model
fields, so DB & Auth Architecture wins. Applied changes: `DOB → date_of_birth`,
`weight → current_weight`, plus four added rows.

Geometrically harder than the first: `training_experience` is 19 characters against a 14-character
box interior, so the ClientProfile box was widened to a **21-character** interior and its connector
chain re-aligned. Verified **programmatically**, not by eye — the CoachProfile box keeps its
original columns (0/15), every ClientProfile border character shares one column pair (20/42), and
the `┬`→`│`→`▼` chain is aligned at a single column (31).

**Known cosmetic consequence, deliberately accepted:** the arrow now meets the `Membership` box
three columns right of its centre (31 vs 28), where it was one column off before. This is
unavoidable — the box width is forced by `training_experience`, `CoachProfile` is fixed, and the
`Membership` box was deliberately out of scope to move. The arrow still lands inside the box.

The correct textual `ClientProfile` listing, the `workspace_id` IMPORTANT note, and every other
diagram were left untouched.

---

#### Verification and acceptance evidence

**Master-run local verification, real exit codes captured directly (never through a pipe):**

| Check | Exit |
|---|---|
| `manage.py check` default / dev / prod | **0** / **0** / **0** |
| repo-wide `makemigrations --check --dry-run` | **0** |
| `migrate` against real PostgreSQL | **0** — `accounts.0003_clientprofile` applied |
| `migrate --check` | **0** |
| `manage.py test` | **0** — **57 tests** (22 new + 35 existing) |
| `./infrastructure/scripts/checks.sh` | **0** — all 7 gates PASS |

**Real database schema confirmed** — exactly **11 columns**, **0** workspace/membership columns,
`accounts_clientprofile_user_id_key` UNIQUE, and an FK to `accounts_user`. `sqlmigrate` showed the
UUID primary key and `numeric(5,2)` decimal columns.

**Mutation-checked — the locked rule is genuinely guarded.** Injecting a `workspace_id` field made
the guard fail on **both** assertions:

```
AssertionError: 'workspace_id' unexpectedly found in {...}
  : Forbidden workspace-scoping field 'workspace_id' must not exist on ClientProfile.
AssertionError: 'workspace_id' unexpectedly found in {...}
  : Forbidden database column 'workspace_id' must not exist on ClientProfile.
```

and also broke field-set equality. The model was then restored **byte-identical**
(blob `bee6434915eb51e191184c0349298b380a1a326e`).

**GitHub CI — accepted run
[31957183411](https://github.com/momenawab/Fitops/actions/runs/31957183411): success.**
Event `pull_request` → base `main`, head `d63ede3`. Tested merge
`95ed586 = Merge d63ede3 into 2ef5be0` — the actual PR merge SHA, confirmed in the checkout log.
All 9 steps succeeded, **none skipped**, `57 test(s) collected`, `All 7 gates passed`, plus the
separate production build.

**PR #4** — <https://github.com/momenawab/Fitops/pull/4>, 4 files, +374/−16.
Commits: `d36ae5b` (model) · `01db341` (tests) · `d63ede3` (ERD sync).
**Merged as `6c2fdcddcf401740030acfcfb3d697b883bb17d3`.**

---

#### Note for the next Story

**Story 2.4 cannot parallelise with 2.3** — it is `POST /auth/register`, depending on this model
plus views, serializers and URLs.

**Parallelism, three Stories in — honest assessment.** Codex has been the critical path in all
three; AGY and OpenCode consistently finish first. The real gains were (1) eliminating
review-and-wait gaps, since diffs were reviewed and Django checks run while other workers were
still active, and (2) work that would not otherwise have happened — both ERD defects were found
during preflight and fixed in-story at zero cost to the critical path. The ceiling for most
Epic 02 Stories is 2-way, because they are "one model plus tests"; the third slot is only filled
when a genuine independent defect exists. It is not filled with manufactured work.

---

## Completed — Story 2.2

### Story 2.2 — Coach Profile  (Epic 02 — Authentication & Identity)

**Status:** ✅ **COMPLETE** — PR #3 merged by the user as `ec3c7d3` on 2026-08-16.

**Acceptance:** `CoachProfile` implemented exactly per Database & Auth Architecture §9 —
`id · user_id · bio · profile_image · website_url · instagram_url · created_at · updated_at`.

**Approved decisions:**

- **`profile_image` is a `FileField`, deliberately NOT an `ImageField`.** `ImageField` requires
  Pillow, which is not installed; Story 2.2 has no upload API. No image processing, upload
  behaviour or dependency was added — that belongs to later storage/upload work.
  **Mutation-proven:** swapping to `ImageField` is rejected by Django check `fields.E210`.
- `user` is a `OneToOneField` to `settings.AUTH_USER_MODEL`, `related_name="coach_profile"`,
  `on_delete=CASCADE`; uniqueness enforced by the database.
- `id` is a UUID primary key, consistent with `User`.
- **No validators** — no documented rule constrains `bio` length or URL format, so none was invented.

**First ERD conflict found and fixed.** The ERD's diagram used `image` / `website` / `instagram` and
omitted the timestamps, contradicting DB §9. Resolved by CLAUDE.md §23 precedence (the specialized
document governs model fields) and synchronized in the same Story. Documentation synchronization
only; every `ClientProfile` field was left untouched and alignment was verified programmatically.

**Execution — first true 3-way parallel Story.** Codex (model + migration), AGY
`gemini-3.7-flash-high` (16 tests), OpenCode `zai-coding-plan/glm-5.3` (ERD sync) ran concurrently
on disjoint files with zero permission denials. Each was reviewed as it finished rather than in a
batch. **Honest assessment:** A was the critical path — B and C finished well before it, so
wall-clock was governed by Codex. The gain was removing review-and-wait gaps, not tripling
throughput. C was work that would not otherwise have happened.

**Verification by Master, real exit codes:** three `manage.py check` runs 0 · repo-wide
`makemigrations --check` 0 · migration applied to real PostgreSQL, table carrying exactly the 8
documented columns with `accounts_coachprofile_user_id_key` UNIQUE and an FK to `accounts_user` ·
35 tests pass · `checks.sh` exit 0, all 7 gates. **Mutation-checked twice:** renaming `related_name`
produced 1 failure + 2 errors from the assertions; the `FileField`→`ImageField` swap was rejected
by `fields.E210`. The model was restored byte-identical after each.

**Remote acceptance:** PR #3 → run
[31955936125](https://github.com/momenawab/Fitops/actions/runs/31955936125) **success**, all 9
steps, none skipped. Tested merge `2491db8 = Merge 0d83f2d into 289d056`.

Commits: `7e11439` (model) · `71e5af8` (tests) · `0d83f2d` (ERD sync).

---

## Completed — Story 2.1

### Story 2.1 — Custom User Model  (Epic 02 — Authentication & Identity)

**Status:** ✅ **COMPLETE** — accepted by the user 2026-08-16. **PR #2 merged** as `49270f4`.

**Acceptance criteria (Blueprint §7 Story 2.1) — all three proven:**

| AC | Evidence |
|---|---|
| Email is unique | Enforced at the **database** level; duplicate insert raises `IntegrityError` |
| User model is used as Django `AUTH_USER_MODEL` | `AUTH_USER_MODEL = "accounts.User"`; `get_user_model()` resolves to `accounts.User`; table `accounts_user` |
| Passwords are securely hashed | `create_user` uses `set_password`; stored value ≠ raw and `check_password` succeeds |

**Implemented** (`ded1b32` model, `772431e` tests):

- `backend/apps/accounts/models.py` — `User(AbstractBaseUser)`
- `backend/apps/accounts/managers.py` — `UserManager.create_user`
- `backend/apps/accounts/migrations/0001_initial.py` — generated, not hand-written
- `backend/config/settings/base.py` — `AUTH_USER_MODEL = "accounts.User"` (only change)
- `backend/tests/test_user_model.py` — 16 tests

Fields match **Database & Auth Architecture §2** and the **ERD** exactly:
`id · email · first_name · last_name · phone · is_active · email_verified_at · platform_role ·
created_at · updated_at`, plus `password` and `last_login` from `AbstractBaseUser`.

**Three interpretations, approved before implementation:**

1. **`id` is a UUID primary key.** The documents show a single `id PK` with no separate uuid
   column; Blueprint Story 2.1 lists "UUID"; API Spec §25.13 requires UUIDs for externally exposed
   identifiers.
2. **The documented `password_hash` is Django's `password` field**, provided by `AbstractBaseUser`,
   whose name Django's auth machinery requires. No field literally named `password_hash` exists.
3. **`email_verified_at` is a nullable timestamp**, not a boolean.

---

#### 🔒 ARCHITECTURE DECISION — AbstractBaseUser WITHOUT PermissionsMixin (binding)

**The `User` model uses `AbstractBaseUser` only. It deliberately does NOT use `PermissionsMixin`,
and MUST NOT gain `is_staff`, `is_superuser`, `groups`, or `user_permissions`.**

Rationale (user-approved, 2026-08-16):

- The authoritative field list in DB & Auth Architecture §2 and the ERD contains none of them.
- Platform authority is represented **only** by `platform_role = ADMIN` (CLAUDE.md §12).
- Adding `PermissionsMixin` would introduce four fields outside the approved ERD.
- `django.contrib.admin` being in `INSTALLED_APPS` is an accepted Story 1.2 artifact. Story 2.1
  deliberately did **not** expand scope to make Django admin functional, and introduced **no**
  replacement permission system.

**Consequences a future agent must respect:**

- There is deliberately **no `create_superuser`** — without an `is_superuser` field the concept does
  not exist. A Platform Admin is simply a `User` with `platform_role = ADMIN`.
- `manage.py createsuperuser` and Django admin login are therefore not usable. **This is intended.**
  Do not "fix" it by adding permission fields; if a future Story genuinely needs Django admin,
  raise it as an architecture decision.
- `backend/tests/test_user_model.py` contains a dedicated guard asserting all four fields are
  absent, plus a **set-equality** assertion on concrete fields so an invented extra field fails as
  loudly as a missing one. Both were mutation-proven to fire.

---

#### Execution — first Story under the parallel orchestration model

| Task | Worker | Model | Scope discipline |
|---|---|---|---|
| A — model, manager, migration, `AUTH_USER_MODEL` | **Codex** | high effort | exactly the 4 permitted files |
| B — 16 model tests | **AGY** | `gemini-3.7-flash-high` | exactly 1 permitted file, **zero permission denials** |

A and B ran **concurrently** in isolated worktrees with **no shared writable file**. B was written
from the same authoritative specification as A — not from A's output — so the tests are an
independent check rather than a description of the implementation. AGY finished first; its diff was
reviewed and its temporary write permission revoked while Codex was still running.

**OpenCode was deliberately left idle.** Story 2.1 is a single tightly-coupled model and supports
genuine 2-way parallelism only; manufacturing a third stream would have been artificial staging.
GLM-5.3 was verified available (`zai-coding-plan/glm-5.3`, probe exit 0) and is ready for Stories
that are genuinely separable.

**Verification by Master, real exit codes:** three `manage.py check` runs 0 · 19 tests pass
(16 new + 3 smoke) · `checks.sh` exit 0, all 7 gates · model introspection confirms UUID pk, email
unique, exact field set, `FORBIDDEN PRESENT: []`, no `create_superuser`. **Mutation-checked:**
injecting an `is_staff` field made the guard and the field-set assertion fail; the model was then
restored byte-identical (blob `78d02200fa14b923748295bf7f54ce58428a4131`).

**Remote acceptance:** PR #2 → run
[31954812214](https://github.com/momenawab/Fitops/actions/runs/31954812214) **success**, all 9
steps, none skipped, `19 test(s) collected`. Merged as `49270f4`. The merged tree is **byte-identical**
(`4433b784…`) to the tree CI validated, because `0227246` is an ancestor of `772431e` — verified,
not assumed.

---

#### 🔧 Local development database repaired (2026-08-16)

**Not a Story 2.1 code defect** — a local development-environment consequence of introducing a
custom `AUTH_USER_MODEL` after an initial `migrate` had already run.

**Symptom:**

```
django.db.migrations.exceptions.InconsistentMigrationHistory:
Migration admin.0001_initial is applied before its dependency
accounts.0001_initial on database 'default'
```

**Cause:** the local `fitops` database was migrated in Story 1.4 under Django's default
`auth.User`. `django.contrib.admin`'s initial migration depends on the swappable user model, so
swapping `AUTH_USER_MODEL` afterwards made the recorded history inconsistent. It blocked
`migrate` / `makemigrations` locally but **never affected tests or CI**, because both build a
**fresh** database — which is exactly how the migration was proven to apply cleanly.

**Repair (user-authorised, local `fitops` database only):**

1. Pre-drop inspection proved it was safe: 10 tables, **all** Django built-ins, **zero** business
   tables, `auth_user = 0` rows, `django_session = 0`, `django_admin_log = 0`. No business data
   existed because Story 2.1 created the project's first model.
2. `DROP DATABASE fitops` → recreated `OWNER fitops ENCODING 'UTF8'` using the existing approved role.
3. `manage.py migrate` from clean state — `accounts.0001_initial` now applies **first**, before
   `contenttypes` and `admin`.

`couch`, `erp`, `postgres`, `template0`, `template1` and all roles were verified **untouched** both
before and after. No migration file, application file, architecture document, or project workaround
was changed.

**Post-repair verification, real exit codes:**

| Check | Exit |
|---|---|
| `migrate` | **0** |
| `migrate --check` | **0** |
| `makemigrations --check --dry-run` (repo-wide) | **0** — no inconsistent history remains |
| `manage.py check` default / dev / prod | **0** / **0** / **0** |
| `./infrastructure/scripts/checks.sh` | **0** — all 7 gates PASS |

Live round-trip against the repaired database: `accounts_user` table present, `auth_user` table
correctly **absent**, migration order `accounts → contenttypes → admin`, a created user has a UUID
id, a hashed password satisfying `check_password`, and defaults `is_active=True`,
`platform_role='NONE'`, `email_verified_at=None`. The verification row was deleted afterwards.

**Lesson for future agents:** `makemigrations <app> --check` scoped to a single app can pass while
the **repo-wide** `makemigrations --check` fails on history inconsistency. Always run the repo-wide
form.

---

## Completed — Story 1.8

### Story 1.8 — CI Pipeline  (Epic 01 — Project Foundation)

**Status:** ✅ **COMPLETE** — DoD satisfied by a real passing GitHub Actions pull-request run, and
**explicitly accepted by the user on 2026-08-16**. PR #1 merged.

**Acceptance / DoD (Blueprint §6, verbatim):** *"Pull requests automatically run required checks."*
This DoD requires a **real GitHub pull-request workflow run**. It cannot be satisfied by local
verification alone, and the Story must not be marked complete until an actual Actions run on a PR
has passed.

**Blueprint tasks:** GitHub Actions workflow for backend tests · frontend tests · linting ·
type checking · build validation.

---

#### ⚠️ Session incident — a Codex CLI session produced work that was LOST

Between 2026-08-15 and this entry, the Master role was temporarily handed to a Codex CLI session.
State verified directly from git at resume, **not** taken from that session's own report:

**What survived (verified):**

- `origin/main` was fast-forwarded to `207bd01`. Confirmed by `git ls-remote origin main` and
  `git rev-list --left-right --count origin/main...main` → `0 0`. All 15 accepted Epic 01 commits
  are now on GitHub. **This resolves the earlier "nothing pushed" carry-in.**
- Verification runs were executed (`checks.sh` exit 0, `npm run build` exit 0). Both were
  independently re-confirmed at resume.

**What was lost (verified):**

- **HEAD never moved.** It remained at `207bd01`; the Codex session committed nothing.
- Branch `codex/story-1.8-t1` existed with **zero commits** (pointed at `207bd01`).
- The T1 deliverable `.github/workflows/ci.yml` existed **only** as an untracked file inside the
  worktree `/private/tmp/fitops-story-1.8-t1`. That directory was **deleted**, the file was never
  committed, and no stash existed. Searches of `/private/tmp` and `/tmp` found nothing.
  **The file was unrecoverable and had to be rebuilt.**
- No PR and no workflow run were ever created.

**Root cause:** the review gate passed but the **commit gate never ran**. The standing rule
*"workers never commit; Master commits after review"* only protects work if the Master's commit
actually happens **before** the worktree is discarded. Uncommitted work in a temporary worktree is
not durable.

**Standing correction:** commit reviewed work to its branch **before** removing any worktree, and
treat a `prunable` worktree as a signal that uncommitted work may already be gone.

**Also left behind and cleaned up at resume:**

| Artifact | Action |
|---|---|
| Root `AGENTS.md` (43,782 bytes) — a copy of `CLAUDE.md` with "Claude" rewritten to "Codex", corrupting instructions such as the reading-order rule and "Codex implementation rules (Blueprint §34)" | **Deleted** (user-approved). **Third occurrence.** Deliberately **NOT** added to `.gitignore` so any future reappearance stays visible |
| Stale `prunable` worktree `/private/tmp/fitops-story-1.8-t1` | Pruned |
| Orphan branch `codex/story-1.8-t1` (0 commits) | Deleted |
| `docs/CODEX_SESSION_HANDOFF.md` (21 KB, untracked) | Its workflow specification was merged into this file (below); the duplicate handoff was **deleted** (user-approved) to avoid two handoff documents drifting apart. Its "Critical Lessons" were already fully covered by `docs/MASTER_HANDOFF.md` §8 |

---

#### Approved Story 1.8 workflow specification

Preserved from the Codex session's handoff before that file was deleted. This is the specification
the workflow must satisfy:

- Trigger **only** on `pull_request` targeting `main`.
- Least-privilege permissions (`contents: read`).
- Official checkout and runtime setup actions.
- **Python 3.14**, **Node 24**.
- Provision **PostgreSQL 16** for the backend tests.
- Supply PostgreSQL environment variables matching Django's settings.
- `DJANGO_SECRET_KEY` only as a CI-safe throwaway value — **never** a production credential.
- Install backend dev dependencies from `backend/requirements-dev.txt`.
- Install frontend dependencies with `npm ci`.
- Run `./infrastructure/scripts/checks.sh` for the approved seven-gate baseline.
- Run `npm run build` separately in `frontend/` for production-build validation.
- **Do NOT** use `pull_request_target`.
- **Do NOT** add Docker, Redis, deployment, coverage, security scanning, or branch protection.
- **Do NOT** add a clean-tree assertion (see the `next-env.d.ts` carry-in).
- **Do NOT** modify application code, dependencies, or Story 1.7 tooling.
- Keep `frontend/next-env.d.ts` unchanged.

---

#### Rebuilt deliverable — `.github/workflows/ci.yml`

Rebuilt by Master **inline** rather than re-delegated: the design was fully specified above, only
the file itself was lost, and a fresh delegation risked repeating the same loss for a single
well-specified file. Disclosed here rather than presented as delegated work.

Design notes:
- One job, because `checks.sh` needs **both** the Python and Node toolchains present.
- `npm ci` runs **before** `checks.sh`, since four of the seven gates are frontend gates.
- The workflow **invokes `checks.sh`** rather than restating the gate list — one definition of
  "the checks", shared by local runs and CI, which also inherits the zero-test guard.
- Build validation is a **separate** step; `npm run build` is deliberately **not** one of the seven
  baseline gates and was not added to `checks.sh` (that file belongs to accepted Story 1.7).
- No `github.event.*` value is interpolated anywhere, so there is no script-injection surface.

**Verification by Master, real exit codes:**

| Check | Result |
|---|---|
| YAML parses; structure asserted | **OK** — trigger `pull_request` → `[main]` only; `pull_request_target` absent; `permissions.contents: read`; service image `postgres:16`; env keys match `base.py` |
| `./infrastructure/scripts/checks.sh` | **exit 0** — all 7 gates PASS |
| `cd frontend && npm run build` | **exit 0** — 4 routes prerendered |
| `frontend/next-env.d.ts` after build | **UNCHANGED** — blob `ce4e94a6b10f160ee021fe18939af160d2927dcf` before and after |

---

#### Remote phase — history split, push, and PR #1

The single commit `6f14f54` (workflow + `PROGRESS.md`) was split so the Story 1.8 PR could contain
exactly one file. Verified no-loss: the post-split tree hash is **identical** to the pre-split tree
(`c783902bac7481d78c21777ecfcaf486139c2348`), and `git diff 6f14f54..HEAD` reported **0** files.

| Ref | SHA | Contents |
|---|---|---|
| `origin/main` before | `207bd01` | — |
| docs commit | `2cb7539` | `PROGRESS.md` only |
| CI commit | `4c8a6f8` | `.github/workflows/ci.yml` only |

`2cb7539` was fast-forwarded onto `origin/main` (never force-pushed). Branch
`codex/story-1.8-ci` was published at `4c8a6f8`, and **PR #1** opened against `main`:
<https://github.com/momenawab/Fitops/pull/1> — GitHub reports `changed_files=1, +88, -0`,
exactly `.github/workflows/ci.yml`.

**The `ci.yml` commit deliberately lives only on `codex/story-1.8-ci`, never on `main`.** Local
`main` is kept aligned with `origin/main` so the workflow reaches `main` only by merging PR #1.

---

#### ⚠️ PR #1 exposed a real defect — the frontend lockfile was not valid on Linux

**This is exactly what CI is for.** The first pull-request run
([31951583598](https://github.com/momenawab/Fitops/actions/runs/31951583598)) failed at step 7,
`npm ci`, before any gate executed:

```
npm error code EUSAGE
npm error `npm ci` can only install packages when your package.json and
          package-lock.json are in sync.
npm error Missing: @emnapi/runtime@1.11.3 from lock file
npm error Missing: @emnapi/core@1.11.3 from lock file
```

**The workflow was correct.** It detected a genuine repository defect. No workflow change was made
to make CI green, and `npm ci` was deliberately **not** downgraded to `npm install` — reproducible
installs are required in both CI and the Docker image.

**Root cause — attributed to the Story 1.7 frontend dependency baseline, not the Story 1.8 CI
workflow.** Story 1.7 added the frontend test/formatting dependencies by running `npm install` on
**macOS**, regenerating `package-lock.json` there. That lockfile carried `@emnapi/*` only as nested
optional dependencies under the `wasm32-wasi` packages, so a **Linux** install tree required
top-level `@emnapi/{core,runtime}@1.11.3` entries that were absent. Story 1.6 had already fixed
this same cross-platform class once; the Story 1.7 macOS install silently reintroduced it, and
nothing caught it because **Story 1.7's gates only ever ran on macOS**.

**Fix (`5719c2c`) — regenerate the lockfile from the Linux target**, using
`npm install --package-lock-only` inside `node:24-slim` on `linux/amd64` (Node v24.19.0,
npm 11.17.0), matching the CI runner family.

Minimal, with **no dependency drift**:

| Metric | Result |
|---|---|
| Dependency versions changed | **0** |
| Packages removed | **0** |
| Packages added | **4** — only the `@emnapi` optional WASM entries npm reported missing |
| `lockfileVersion` | unchanged (3); 853 → 857 packages |
| `package.json` | **byte-identical** (`711793246e813daa16052458bfbd897a3b210de8`) |

**Verification, real exit codes captured directly (never through a pipe):**

| Check | Result |
|---|---|
| Linux `npm ci` **before** fix | **exit 1** — CI failure reproduced locally in the container |
| Linux `npm ci` **after** fix | **exit 0** |
| macOS `npm ci` **after** fix | **exit 0** |
| `./infrastructure/scripts/checks.sh` | **exit 0** — all 7 gates PASS |
| `cd frontend && npm run build` | **exit 0** |
| `frontend/next-env.d.ts` | unchanged (`ce4e94a6b10f160ee021fe18939af160d2927dcf`) |

The fix was landed on `main` as a **separate accepted-Story correction** and deliberately **not**
added to PR #1, which stays a one-file CI PR.

**Likely collateral, not yet confirmed:** `infrastructure/docker/frontend.Dockerfile:6` also runs
`npm ci` on Linux, so the Docker frontend image build was probably broken by the same lockfile and
should be fixed by `5719c2c` too. **Not verified** — the image was not rebuilt.

**Standing lesson:** a lockfile verified only on the development host is not verified. Whenever
`package-lock.json` changes, check `npm ci` on **both** macOS and the Linux deployment target.

---

---

#### ✅ DoD satisfied — the accepted GitHub Actions run

Blueprint DoD: *"Pull requests automatically run required checks."*

| Field | Value |
|---|---|
| Run | [31952441965](https://github.com/momenawab/Fitops/actions/runs/31952441965) — **conclusion: success** |
| Event | `pull_request` → base `main` |
| Tested merge | `64b4017` = *Merge `4c8a6f8` into `09b6dc2`* (confirmed in the checkout log) |
| Steps | all 9 **success**, **none skipped** |

Gate output captured from the run:

```
==> backend: ruff check              PASS
==> backend: ruff format --check     PASS
==> backend: django tests            PASS (3 test(s) collected)
==> frontend: npm run lint           PASS
==> frontend: npm run typecheck      PASS
==> frontend: npm test               PASS
==> frontend: npm run format:check   PASS
All 7 gates passed.
```

Plus the separate build step: `✓ Compiled successfully in 4.4s`, 4 static pages.
PostgreSQL: `postgres:16` pulled, health-checked with `pg_isready -U fitops -d fitops`, reported
**"postgres service is healthy"**, and Django's tests ran against it. The `3 test(s) collected`
line is the zero-test guard confirming tests genuinely executed.

**Note on runs 1–2.** Both failed at `npm ci`. Run 1 exposed the real lockfile defect (fixed in
`5719c2c`). Run 2 failed **identically because it tested the wrong commit** — its checkout log
showed `HEAD is now at d77cac8 Merge 4c8a6f8 into 2cb7539`, the *old* base. GitHub recomputes
`refs/pull/N/merge` lazily after the base moves, so an event fired too soon carries a stale merge
SHA. **Always confirm which merge commit a run checked out before interpreting a failure.** No
workflow change was ever made to force a green run.

---

#### Merge and final verification

PR #1 merged on 2026-08-16 with the repository's default merge-commit method (no force-push,
no workflow modification).

| Check | Result |
|---|---|
| PR #1 merged | ✅ `merged=true`, `merge_commit_sha=e96e8be` |
| `origin/main` | ✅ `e96e8bea879622f3151be64653d3d3a96a8f1ff5` (ls-remote **and** API) |
| Merge parents | `09b6dc2` + `4c8a6f8` |
| CI workflow on `main` | ✅ blob `83ac73223d9a19d8f17b44bc981dac8cd63ec4de` |
| PR scope after merge | ✅ still `changed_files=1, +88, -0` — only `.github/workflows/ci.yml` |
| `git diff 09b6dc2..main` | ✅ `A .github/workflows/ci.yml` — **nothing else introduced** |
| Lockfile unchanged by merge | ✅ `bee224f5325cdaa2f99ed5cc2ff9ee10ab8ad8ba` |
| Gates on merged `main` | ✅ `checks.sh` exit 0, all 7 PASS |

**Story 1.8 is COMPLETE.** CI now runs the seven-gate baseline plus a production build on every
pull request targeting `main`.

---

## Completed — Story 1.7

> Recorded here rather than in the main **Completed** section above only because of its length and
> the order in which it was written. It is a fully completed and accepted Story with the same
> status as Stories 1.1–1.6.

### Story 1.7 — Testing and Quality Baseline  (Epic 01 — Project Foundation)

**Status:** ✅ **COMPLETE** — implementation finished and independently verified by Master on
2026-08-15, and **explicitly accepted by the user on 2026-08-15**.

**Acceptance criteria (Blueprint §6):** all baseline checks can run locally.

**Approved tool set** (user decision, 2026-08-15 — this closed the pre-implementation gap that the
Technology Stack names no test/lint/format tooling):

| Side | Approved | Explicitly rejected / deferred |
|---|---|---|
| Backend | Django built-in test runner; **Ruff** for lint *and* formatting | pytest, pytest-django; **backend type checking DEFERRED** — no mypy, no django-stubs |
| Frontend | Vitest, `@testing-library/react`, jsdom, Prettier, `eslint-config-prettier` | jest; existing ESLint + TypeScript setup kept unchanged |

**Scope boundary:** Story 1.8 owns the GitHub Actions pipeline. "Basic CI checks" in Story 1.7
means the checks are runnable **locally** — no `.github/` workflow is created by this Story.

**Task breakdown** (established and approved before any dispatch):

| ID | Task | Complexity | Worker | Depends | Status |
|---|---|---|---|---|---|
| T1 | Backend test + quality baseline (Django test runner wiring, Ruff config, `requirements-dev.txt`, smoke tests) | VERY HARD | Codex | — | **LANDED** `966f2e2` |
| T2 | Frontend test + formatting baseline (Vitest config, Prettier config, ESLint interop, scripts, smoke test) | MEDIUM | AGY | — | **LANDED** `c17ca85` |
| T3 | Single local entrypoint running every backend + frontend gate | SIMPLE | OpenCode | T1, T2 | **LANDED** `4fe7073` |

T1 and T2 are genuinely independent (disjoint directories and dependency files) and run in parallel.

**Master provisioning done before dispatch** (workers have no network):

- `ruff 0.16.3` installed into `/Users/momen/Fitops/.venv`.
- `vitest 4.1.10`, `@testing-library/react 16.3.2`, `jsdom 29.1.1`, `prettier 3.9.6`,
  `eslint-config-prettier 10.1.8` installed into the T2 worktree's `frontend/node_modules`;
  `package.json` / `package-lock.json` updated by that install (Master's change, not the worker's).

**Pre-dispatch empirical check — no React transform plugin is needed.** Before briefing T2, Master
probed whether Vitest 4 can transform `.tsx` and render a React component using only the approved
package set. It can: a throwaway config + test rendering a JSX component through
`@testing-library/react` passed with real exit code 0. `@vitejs/plugin-react` was therefore **not**
added, and the brief forbids it. The probe files were deleted and the worktree re-verified clean.

**Known consequence — workers cannot run the gates.** Worker sandboxes have no sockets, so Codex
cannot run `manage.py test` (Django's runner must reach PostgreSQL to create the test database).
AGY additionally has deliberately narrow command permissions, so it runs no npm/npx command at all
and authors files only. **Master runs every gate and reports real exit codes.** Applying
`npm run format` mechanically after T2 lands is Master's step, not the worker's.

**AGY permission handling:** a single temporary rule
`write_file(<absolute T2 worktree path>)` was added to `~/.gemini/antigravity-cli/settings.json`
for this dispatch, alongside the pre-existing `command(git status)`. **Removed after T2 landed** —
the file is back to `command(git status)` only. No broad write rule, no
`--dangerously-skip-permissions`. AGY reported **no permission denials**, confirming that a
worktree-scoped `write_file(<path>)` rule is sufficient for a file-authoring task.

---

#### ⚠️ DEFECT FOUND DURING VERIFICATION — `manage.py test` exits 0 while running zero tests

Master ran the backend suite from the **repository root** and got:

```
$ .venv/bin/python backend/manage.py test
Ran 0 tests in 0.000s
NO TESTS RAN
MANAGE_TEST_EXIT=0        <-- ZERO
```

Run from **`backend/`** instead:

```
$ .venv/bin/python manage.py test
Creating test database for alias 'default'...
Ran 3 tests in 0.002s
OK
Destroying test database for alias 'default'...
Found 3 test(s).
MANAGE_TEST_FROM_BACKEND_EXIT=0
```

**Cause:** Django's runner discovers tests relative to the current working directory, and
`backend/` is not an importable package (no `__init__.py`). From the root it finds nothing — and
Django returns exit code **0** for "no tests collected".

**Why it matters:** a check script that runs the backend tests from the wrong directory reports
SUCCESS while executing nothing. This is the same class of false-green as the Story 1.6
pipe-masked-exit-code incident.

**Not a defect in T1's deliverable** — the tests are correct and pass from the right directory.
It is a defect in how the suite must be *invoked*, so the guard belongs in T3's entrypoint. T3's
brief requires the script to (a) run the Django gate from `backend/`, and (b) treat
"zero tests collected" as a FAILURE rather than trusting the exit code.

**Carry into Story 1.8:** the CI workflow must invoke the backend suite the same way. Never rely
on `manage.py test`'s exit code alone as evidence that tests ran.

---

#### Tests proven falsifiable by mutation (not just "green")

A passing test proves nothing if it cannot fail. Both smoke suites were mutation-checked:

| Mutation | Result |
|---|---|
| `CELERY_ACCEPT_CONTENT` widened to allow an unsafe non-JSON serializer alongside `json` | `MUTATED_BACKEND_TEST_EXIT=1`, assertion reported the two-element list differing from `['json']` |
| `<h1>FitOps</h1>` changed to `<h1>NotFitOps</h1>` | `MUTATED_TEST_EXIT=1`, `AssertionError: expected 'NotFitOps' to be 'FitOps'` |

Both sources were restored and the restoration verified by empty `git diff`. The first mutation
confirms the Story 1.5 JSON-only security requirement is genuinely guarded by a regression test.

---

#### Known issue — `next-env.d.ts` flip-flops between two generators

`next dev` writes `next-env.d.ts` referencing `./.next/dev/types/...`; the standalone
`next typegen` (which `npm run typecheck` runs) rewrites it to `./.next/types/...`. Whichever
command ran last dirties the working tree.

**Not functionally broken:** `typecheck` runs `next typegen` first, so it always rewrites the file
before compiling and passes either way. The committed version is the `typegen` variant.

**Carry into Story 1.8:** if CI ever adds a "working tree must be clean" assertion, this file will
trip it. Decide there whether to ignore it or normalise it — it is **not** resolved here.

---

#### Verification — all seven gates, run by Master on `main` with real exit codes

Re-run on the merged `main` tree (not in the worktrees), after `npm ci` synced `node_modules`:

| # | Gate | Command | Exit |
|---|---|---|---|
| 1 | backend lint | `ruff check .` (from `backend/`) | **0** |
| 2 | backend format | `ruff format --check .` (from `backend/`) | **0** |
| 3 | backend tests | `manage.py test` (from `backend/`) | **0** — 3 found, 3 passed, `test_fitops` created + destroyed |
| 4 | frontend lint | `npm run lint` | **0** |
| 5 | frontend types | `npm run typecheck` | **0** |
| 6 | frontend tests | `npm test` | **0** — 2 passed |
| 7 | frontend format | `npm run format:check` | **0** |

Also verified: `npm ci` succeeds on macOS from the committed lockfile (`MAIN_NPM_CI_EXIT=0`) — the
Story 1.6 cross-platform lockfile fix still holds. Django system checks pass under default, dev and
prod settings (all exit 0).

No command output was piped before reading `$?`; every exit code above is the real process status.

---

#### T3 — `infrastructure/scripts/checks.sh` (the single local entrypoint)

Placed in `infrastructure/scripts/` because that directory already exists in the approved
repository tree (ERD §4). A root `Makefile` was deliberately **not** created — it is not part of
the approved structure.

Behaviour: runs all seven gates, prints a per-gate PASS/FAIL summary, and exits 0 only if every
gate passed. Repository root resolved from `BASH_SOURCE` (no hardcoded machine path). Interpreter
resolved from `<root>/.venv` with a `PATH` fallback and a `FITOPS_PYTHON` override, so it also
works inside the Docker image where there is no `.venv`. A missing `npm` records the frontend gates
as **FAILED**, never skipped — a skipped gate must never read as a pass.

**Defect fixed by Master during review:** `printf '-------\n'` was parsed by bash as an option and
printed `printf: --: invalid option` on every run. Changed to `printf -- '-------\n'`. This was a
one-line cosmetic fix applied directly rather than a re-dispatch; it is disclosed here and in the
commit message rather than folded silently into the worker's output.

**Verification of the entrypoint itself, with real exit codes:**

| Scenario | Result |
|---|---|
| Full run on `main`, no override (must find `.venv` itself) | `FINAL_CHECKS_EXIT=0`, all 7 gates PASS |
| Run from an unrelated working directory (`cd /`) | exit 0, repo root resolved correctly |
| No `.venv` present and no `ruff` on `PATH` | exits non-zero with a clear error instead of proceeding |
| **Smoke tests removed → Django collects 0 tests** | **exit 1**, gate reports `FAIL: Django collected 0 tests. Exit status 0 is NOT accepted as a pass` |

The last row is the important one: it proves the zero-test guard actually fires, rather than merely
existing in the source.

---

#### Story 1.7 acceptance criteria

Blueprint AC: *"All baseline checks can run locally."* — **met.** One command,
`./infrastructure/scripts/checks.sh`, runs all seven gates locally and exits non-zero if any fails.

Blueprint task coverage: backend test setup (Django runner + 3 tests) · frontend test setup
(Vitest + 2 tests) · linting (Ruff + ESLint) · formatting (Ruff format + Prettier) · type checking
(TypeScript; **backend type checking deferred by explicit user decision**) · basic CI checks
(local entrypoint; the GitHub Actions workflow belongs to Story 1.8).

**Worktree hygiene:** all three delegation worktrees were removed after merge; `git worktree list`
shows only the main tree. No stale worker processes remained — the Antigravity processes on the
machine are the user's running IDE, not delegation workers, and were correctly left alone.

---

## Next

| Field | Value |
|---|---|
| **Epic** | Epic 02 — Authentication & Identity |
| **Story ID** | **Story 2.6** |
| **Story title** | Coach Login |

**Do NOT start Story 2.6 automatically — user approval required. No implementation has begun.**

**Blueprint §7 Story 2.6, verbatim:**

```
## Story 2.6 — Coach Login

Implement:

POST /auth/login

Flow:

Email + Password
       ↓
Credentials Valid
       ↓
2FA Enabled?
   ┌───┴───┐
  YES      NO
   ↓        ↓
2FA      Session
   ↓
Session
```

**Notes before starting Story 2.6 — carried from earlier Stories:**

1. **Rate limiting IS mandated here.** API §22 lists *Login* explicitly, and Blueprint Story 20.3
   (Authentication Hardening) also names login rate limits. Confirm ownership before deciding scope,
   and reuse the **scoped-throttle** pattern established in Story 2.5 — there is still deliberately
   **no** global throttling.
2. **Sessions come from Django's session framework.** There is **no** `UserSession` model, no
   `token_hash`, and no JWT. Login creates a Django session; `POST /auth/logout` terminates it.
   Per-session listing and revocation were removed from the MVP.
3. **2FA is TOTP only** and its state lives on `CoachSecurity`, a model that **does not exist yet**.
   Check whether Story 2.6 needs it, or whether the 2FA branch belongs to a later Story — the
   Blueprint flow shows the branch but the model may not be in scope here. **Resolve this in
   preflight; do not assume.**
4. **`EMAIL_NOT_VERIFIED` and `TWO_FACTOR_REQUIRED` are documented error codes.** Read API §4 for
   the exact login contract before deciding which apply. Invent no code outside the closed list.
5. **Anti-enumeration:** confirm from API §4 what login must return for a wrong password versus an
   unknown email. `INVALID_CREDENTIALS` exists in the closed list.
6. The API §2 error envelope and the scoped-throttle pattern are both live and inherited.
7. Nothing in `docs/MISSING_DECISIONS.md` (B24–B27, SMTP) blocks Story 2.6.


**Carry-ins still live:**

1. **`next-env.d.ts` churn** — `next dev` and `next typegen` write different contents to that file.
   The merged workflow deliberately adds **no** clean-tree assertion, so it does not trip. Still
   **unresolved** as a general matter; `npm run build` was verified **not** to modify the file
   (blob `ce4e94a6b10f160ee021fe18939af160d2927dcf` unchanged).
2. **Zero-test trap** — guarded inside `checks.sh`, which the workflow invokes. If any future CI
   step calls Django directly instead of through the script, it **must** reproduce the guard.
3. **Cross-platform lockfile** — whenever `frontend/package-lock.json` changes, verify `npm ci` on
   **both** macOS and the Linux target before committing. A lockfile verified only on the
   development host is not verified. This class has now broken the build **twice** (Stories 1.6
   and 1.7).
4. **Docker frontend build** — `infrastructure/docker/frontend.Dockerfile:6` runs the same
   `npm ci`, so `5719c2c` probably repaired it too. **Not verified** — the image was not rebuilt.
5. ~~**Blueprint tracking marker** — Stories 1.7 and 2.1 lacked `✅ COMPLETE (date)` headings~~
   ✅ **RESOLVED 2026-08-16.** Markers applied for Stories **1.7**, **2.1** and **2.4** under
   explicit user approval, as a grouped tracking-only change. All completed Stories 1.1–1.8 and
   2.1–2.4 now carry the heading consistently. The Blueprint diff was exactly three heading lines —
   no architecture, requirement or content change.

---

## Decisions Made During Implementation

Implementation-level decisions taken during Stories 1.1–2.4 are recorded **inline in each Story's
own section above**, next to the evidence that justified them (for example: the ERD §24 app-list
correction in Story 1.1, the `libpq5` fix in Story 1.6, the approved test/lint/format tool set in
Story 1.7, the AbstractBaseUser-without-PermissionsMixin decision in Story 2.1, and the four
preflight resolutions in Story 2.4). They are not duplicated here, so that a single Story's record
stays self-contained.

Architecture and product decisions are **not** recorded here — they live in the Development
Blueprint decision log (§2A: v1.1 decisions 1–18; §2B: v1.2 billing decisions 19–37 and v1.2.1
decisions 38–43). Do not duplicate them into this file.

Decisions that arose **during implementation** and were **explicitly approved by the user**:

| Decision | Reason | Date | Related Story | Author/agent |
|---|---|---|---|---|
| **Correct the ERD §24 repository tree** to list all nine canonical Django apps by adding `applications/` and `billing/`. Documentation-only; two inserted lines. | ERD §24's tree omitted two apps that ERD §15 and Blueprint Story 1.2 both list. The stale tree would have misled Story 1.2's app creation. | 2026-08-14 | Discovered in 1.1, blocks 1.2 | User-approved (Option A); applied by Claude Opus 5 |
| **Rejected**: a proposed nine-app list replacing `coaching` with `plans` + `checkins` and dropping `audit`. | Would have changed domain boundaries (ERD §18), removed the owner of `AuditLog` (25 references across four approved documents, including approved billing rule B15 requiring both a `BillingEvent` and an `AuditLog` on admin decisions), and created a new contradiction instead of resolving one. Reported rather than applied; user confirmed the rejection. | 2026-08-14 | Pre-1.2 | Reported by Claude Opus 5; user confirmed |

**Canonical Django app list (unchanged, confirmed):** `accounts`, `workspaces`, `coaching`,
`clients`, `applications`, `commerce`, `billing`, `notifications`, `audit`. The `coaching` app is
**not** split; the `audit` app is **not** removed.

---

## Unresolved Decisions

The authoritative registry is **`docs/MISSING_DECISIONS.md`**. Do not restate its contents here and
never resolve an item in this file.

**Rule:** if implementation reaches a decision listed there, **stop and ask for an explicit decision
rather than guessing.** Complete everything that does not depend on it, then report precisely what
is blocked.

Currently registered: **B24** (archive retention duration), **B25** (archive restoration scope),
**B26** (long-expired multi-period reactivation), **B27** (terminal `CANCELLED` cleanup lifecycle),
and the deliberately unselected **SMTP provider** (deployment configuration; blocks no Story).

**Impact on implementation so far:** none. Stories 1.1–1.7 (Epic 01 foundation work) touched no
billing or email behaviour, so no registered decision was reached. B24–B27 are expected to become
relevant only in Epic 22 (Stories 22.6, 22.9, 22.10b, 22.10c); the SMTP provider becomes relevant
at deployment and blocks no Story.

When an unresolved decision affects implementation, record it here as:

| Decision ID | Why it matters here | Was implementation blocked? | What was done instead |
|---|---|---|---|

---

## Known Issues / Risks

**Open carry-ins for Story 1.8** (real, currently unresolved):

| Description | Impact | Related Story | Status | Suggested next action |
|---|---|---|---|---|
| **`next-env.d.ts` churn between `next dev` and `next typegen`** | `next dev` writes `import "./.next/dev/types/..."`; the standalone `next typegen` (which `npm run typecheck` runs) rewrites it to `./.next/types/...`. Whichever ran last dirties the working tree. **Not functionally broken** — `typecheck` runs `typegen` first and self-corrects, so the gate passes either way. The committed version is the `typegen` variant | 1.3 → **carry-in to 1.8** | **OPEN — unresolved by decision** | If the Story 1.8 workflow adds a "working tree must be clean" assertion, this will trip it. Decide in 1.8 whether to ignore the path, normalise it, or drop the assertion. **Do not resolve it silently** |
| **`manage.py test` exits 0 while collecting zero tests** | Run from the repository root, Django's runner discovers nothing (`backend/` is not an importable package) and still returns exit code 0 — a false green. Verified directly | 1.7 → **carry-in to 1.8** | **Mitigated locally, open for CI** | `infrastructure/scripts/checks.sh` already runs the gate from `backend/` and fails on "no tests collected". Story 1.8 should invoke that script rather than calling Django directly; if it ever calls Django directly it MUST reproduce the guard |
| ~~Local `main` is 14 commits ahead of `origin/main`~~ | Nothing from Epic 01 had been pushed to `https://github.com/momenawab/Fitops.git` | 1.8 | ✅ **RESOLVED 2026-08-15** | A Codex CLI session pushed with user authorisation. Verified at resume: `git ls-remote origin main` → `207bd01`, and `git rev-list --left-right --count origin/main...main` → `0 0` |
| **Uncommitted work in a temporary worktree is not durable** | A Codex session's reviewed-and-passed `.github/workflows/ci.yml` was lost when its worktree was deleted before any commit. Review passed; the commit gate never ran | 1.8 | **Mitigated by process change** | Commit reviewed work to its branch **before** removing any worktree. Treat a `prunable` worktree as a signal that uncommitted work may already be gone |

Documented risks carried from the architecture (context for a future agent, not defects):

| Item | Impact | Related Story | Status | Suggested next action |
|---|---|---|---|---|
| ~~ERD §24 app list is stale~~ | Omitted `applications` and `billing` from the §24 repository tree | 1.2 | ✅ **RESOLVED 2026-08-14** | Corrected under user approval (Option A). §24 now matches §15 and Blueprint Story 1.2 — see *Decisions Made During Implementation* |
| B24–B27 unresolved | Epic 22 billing Stories cannot be fully completed | 22.6, 22.9, 22.10b, 22.10c | Open — registered | Ask the user before those Stories begin |
| SMTP provider unselected | None — env-configured | Epic 02 email Stories | Open by design | Configure at deployment |
| Empty dirs use `.gitkeep` | Git cannot track empty directories; `.gitkeep` placeholders keep the ERD §24 skeleton in version control. They should be deleted as each directory gains real files | 1.2, 1.3 | Accepted convention | Remove each `.gitkeep` when its directory gets real content |
| Runtime toolchain | Python 3.14.6 ✅, psql 16.13 ✅ (running server **not yet verified**), node v24.12.0 ✅, **docker NOT INSTALLED** ❌ | 1.4, 1.6 | Partly resolved | Install Docker before Story 1.6; verify a running PostgreSQL server before T6 |
| **Worker sandboxes have no network** | Codex could not reach PyPI, so it cannot install packages or run gates that need them. Discovered in T1 | all delegated tasks | Open — mitigation known | Master performs installs and runs gates; briefs must not require a worker to install packages |
| Codex created an unrequested `AGENTS.md` | Copy of `CLAUDE.md` with content silently altered; deleted before commit, never in history | T1 | Corrected | Decide whether a short pointer-style `AGENTS.md` ("read CLAUDE.md") is wanted for Codex-family workers — **user's call, not applied** |

Use this format for real issues once implementation starts:

| Description | Impact | Related Story | Status | Suggested next action |
|---|---|---|---|---|

---

## Tests & Verification

**An automated test baseline now exists** — established in Story 1.7 (2026-08-15).

**Run every baseline gate with one command:**

```
./infrastructure/scripts/checks.sh
```

It runs all seven gates and exits **non-zero** if any fails: backend `ruff check`,
`ruff format --check` and the Django test suite (from `backend/`, failing if zero tests are
collected); frontend `lint`, `typecheck`, `vitest` and `format:check`. Last full run on `main`:
**exit 0, all 7 gates PASS** (3 backend tests, 2 frontend tests).

Coverage is deliberately **baseline only**. Blueprint §30's Unit / API / **tenant-isolation** /
E2E suites belong to the Stories and Epics that introduce that behaviour — Story 1.7 added no
business-logic tests because no business logic exists yet.

---

The structural verification below is the **Story 1.1** record, executed on 2026-08-14, and is kept
for history.

| Check | Command / method | Result |
|---|---|---|
| Directory structure vs ERD §24 | Shell existence check over 15 required directories | ✅ 15/15 present |
| Required root files | Existence check: `README.md`, `.gitignore`, `.env.example` | ✅ 3/3 present |
| Tracked-file secret scan | `git ls-files` filtered for `.env*`, `*.pem`, `*.key`, `secret` | ✅ only `.env.example` |
| `.env` ignore rule | `git check-ignore -v .env` | ✅ matched `.gitignore:4` |
| Secret-pattern content scan | `git grep -nEi '(password\|secret\|api[_-]?key\|token)\s*[:=]…{20,}'` over non-docs files | ✅ no matches |
| `.env.example` placeholders | Placeholder-pattern count | ✅ 12 placeholder lines, no real values |
| **Clean clone (DoD)** | `git clone` to a temp dir, inspect tree | ✅ full structure present, no `.env` |
| **Clone setup step (DoD)** | `cp .env.example .env` inside the clone | ✅ succeeded; new `.env` correctly ignored, tree clean |
| README setup section | Grep for the "Local setup" section in the clone | ✅ present |

| Tooling check | Status |
|---|---|
| Backend tests | Not configured yet (Story 1.7) |
| Frontend tests | Not configured yet (Story 1.7) |
| Lint / format / type check | Not configured yet (Story 1.7) |
| E2E | Not configured yet (Story 1.7) |

**Known failing tests:** none — no test suite exists.

**Never record a test as passing unless it was actually executed in this repository.**

---

## Files & Architecture Notes

**No application code exists yet.** Story 1.1 created structure and configuration only.

Created in Story 1.1:

- **`.gitignore`** — the `.env` rule is deliberately `.env` + `.env.*` with a `!.env.example`
  negation, so any future `.env.local` / `.env.production` variant is ignored by default.
  `infrastructure/backups/*` is ignored except its `.gitkeep`, so database dumps can never be
  committed accidentally.
- **`.env.example`** — grouped by consuming Story rather than alphabetically, so each Story knows
  which block it owns. Variable names are a starting template and are finalized in Stories 1.2/1.4/1.5.
- **`.gitkeep` placeholders** — the only reason empty directories survive in git. Delete each one
  when its directory gains real files.
- **Branch `main`** — repository initialized with `git init -b main`. No remote is configured.

Structural facts a future agent needs (from the approved architecture — read the source documents
for detail, do not rely on this summary):

- **Monorepo** rooted at `/Users/momen/Fitops`: `frontend/`, `backend/`, `infrastructure/`, `docs/`.
- **Backend apps** (domain-split, not one-per-model): `accounts`, `workspaces`, `coaching`,
  `clients`, `applications`, `commerce`, `billing`, `notifications`, `audit`, plus `common/` for
  shared tenant/security infrastructure.
- **Two payment domains that must never share models:** Coach Commerce (Client → Coach) in
  `commerce`/`workspaces`, and FitOps Billing (Coach → FitOps) in `billing`.
- **Tenancy:** the Workspace slug in the URL is the authoritative context for every workspace-scoped
  area, including the coach dashboard. A frontend-supplied `workspace_id` is never trusted.
- **Tenant-scoped FKs:** workspace-scoped records reference `Membership`, not global `User` /
  `ClientProfile`. `Application.user_id` is the nullable exception.

Once implementation starts, record here only **non-obvious** structure: important services, unusual
configuration, cross-module relationships, and implementation decisions that would not be apparent
from reading the code.

---

## Handoff Notes

**Read in this order before doing anything:**

1. `CLAUDE.md` — project rules, architecture index, precedence order.
2. `PROGRESS.md` (this file) — implementation state.
3. `docs/MISSING_DECISIONS.md` — what must not be guessed.
4. The authoritative documents for the current Story (Blueprint §2 lists the paths).

**What was just completed:** **Story 1.1 — Monorepo Setup** (Epic 01). The repository is now a git
repository on branch `main` with one commit, `6d3eedd`. The ERD §24 skeleton, `README.md`,
`.gitignore` and `.env.example` exist. All acceptance criteria and both DoD items were verified as
passing against the real repository.

**What should happen next:** **Story 1.2 — Django Backend Setup**, but only after the user approves
starting it. Do not start it automatically.

**Currently dangerous to modify:**

- `docs/` — the approved architecture, locked at v1.2.1. Changing a model, endpoint, enum or
  business rule requires user approval plus a documentation update in the same change
  (Blueprint Rule 9).
- `.gitignore` — the `.env` rules are a security control. Do not weaken them.
- `.env.example` — placeholders only. Never put a real value in it.

**Incomplete work:** none. Story 1.1 is fully complete; nothing was left half-done.

**Test command to run first:** none exists yet. The test baseline is created in Story 1.7. To
re-verify Story 1.1, run `git status` (expect a clean tree) and confirm `git ls-files` lists no
`.env` other than `.env.example`.

**Non-obvious context for the next agent:**

- **ERD §24 was corrected on 2026-08-14** and now matches ERD §15 and Blueprint Story 1.2. All
  three agree on the canonical nine apps: `accounts`, `workspaces`, `coaching`, `clients`,
  `applications`, `commerce`, `billing`, `notifications`, `audit`. Do **not** split `coaching` into
  `plans`/`checkins` and do **not** drop `audit` — that variant was explicitly proposed, rejected
  and recorded under *Decisions Made During Implementation*. Note that `plans/` and `check-ins/` do
  appear in the docs as **frontend routes** (ERD §25), never as Django apps.
- `docker-compose.yml` is intentionally absent. It belongs to Story 1.6, not 1.1.
- `.gitkeep` files are placeholders only. Delete each one once its directory holds real files.
- The user works in strict approval gates. Report gaps and stop; never fill a gap with a sensible
  default. This applies to architecture questions and to `docs/MISSING_DECISIONS.md` items alike.
- Epic numbering: Epics 01–21 are the v1.1 canonical list (Orders and Payments are **one** Epic, 08).
  Epic 22 (FitOps Billing & Subscriptions) was added in v1.2. Blueprint §29 is a finer-grained
  sequence, **not** a second Epic list.
- Runtime toolchain availability (Python, Node, PostgreSQL, Docker) in this environment is
  **Unknown / not verified** — Story 1.1 required none of it. Verify before Story 1.2.

---

## Working Protocol

### Story-level progress tracking

Break every Story into an explicit task checklist from its acceptance criteria **before** coding.
Track it in the *In Progress* section like this:

```
Story 1.1 — Monorepo Setup

Progress:
[x] Initialize git repository
[x] Create frontend directory
[ ] Create backend directory
[ ] Add root README
[ ] Add .gitignore and .env.example

Last completed step:
"Frontend directory created."

Next step:
"Create backend directory."
```

**Update this file immediately after every significant completed task** — never wait until the
Story is finished. After each task, tell the user concisely:

```
Completed: <what was just finished>
Remaining: <what is still pending>
Next:      <next task>
```

Continue to the next task only after the current one is verified.

### Interruption safety

Assume the session can end at any moment. After every meaningful milestone, this file must record
what was completed, what remains, files changed, test/check results, and any blockers — so a new
agent can continue **without repeating completed work**.

### When to update this file

After every completed Story, and also when: a Story starts, is paused, or is blocked; a significant
implementation decision is approved; a significant bug is discovered; tests reveal an important
issue; or a handoff is needed. Before ending a work session, make sure this file reflects reality.

### Story completion

A Story is not fully handed off until **all** of these are done:

1. Implementation complete
2. Tests/checks actually run
3. Every acceptance criterion verified
4. `PROGRESS.md` updated
5. Next Story identified from the Development Blueprint

Then report **"Story X.Y completed."** with what was implemented, acceptance-criteria verification,
tests/checks with real results, files changed, and the next Story — and **STOP**. Do not
automatically start the next Story.

Per-Story reporting also follows Blueprint §34 Rule 10: **Implemented · Changed Files · Database
Changes · API Changes · Tests · Security Checks · Known Issues · Next Recommended Story**.
