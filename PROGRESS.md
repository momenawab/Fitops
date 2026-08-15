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

---

## Current Status

| Field | Value |
|---|---|
| **Current phase** | Implementation |
| **Current Epic** | Epic 01 — Project Foundation |
| **Current Story** | Story 1.7 — Testing and Quality Baseline — **IN PROGRESS** |
| **Overall status** | Epic 01 in progress — 6 of 8 Stories complete |
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

### Story 1.7 — Testing and Quality Baseline  (Epic 01 — Project Foundation)

**Status:** Implementation COMPLETE and independently verified by Master on 2026-08-15.
**AWAITING USER ACCEPTANCE** — not yet moved to the Completed section, per the project rule that a
Story is accepted by the user, not self-declared.

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
| **Epic** | Epic 01 — Project Foundation |
| **Story ID** | Story 1.8 |
| **Story title** | CI/CD Pipeline (GitHub Actions) |

**Why it is next:** Blueprint §6 lists 1.8 after 1.7. Story 1.7 implementation is complete and
verified, pending user acceptance.

**Do NOT start automatically — user approval required.**

**Notes before starting:**

1. Story 1.7 delivered `infrastructure/scripts/checks.sh`, which runs all seven gates and exits
   non-zero on any failure. Story 1.8's workflow should invoke that script rather than duplicating
   the gate list — one definition of "the checks", used identically locally and in CI.
2. **Carry-in — the zero-test trap.** `manage.py test` exits 0 while collecting zero tests when run
   from the repository root. `checks.sh` already guards this. If Story 1.8 ever calls Django
   directly instead of through the script, it must reproduce the guard.
3. **Carry-in — `next-env.d.ts` churn.** `next dev` and `next typegen` write different contents to
   that file. If the workflow adds a "working tree must be clean" assertion, this will trip it.
   Unresolved — decide in Story 1.8.
4. CI needs PostgreSQL for the backend test gate (a service container or equivalent). It does not
   need Redis for the current tests, but Celery configuration is asserted from settings only.
5. Backend dev dependencies come from `backend/requirements-dev.txt`; frontend from `npm ci`.

---

## Decisions Made During Implementation

**None.** No implementation has occurred, so no implementation-level decisions exist.

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

**Impact on implementation so far:** none — implementation has not started. B24–B27 are expected to
become relevant only in Epic 22 (Stories 22.6, 22.9, 22.10b, 22.10c).

When an unresolved decision affects implementation, record it here as:

| Decision ID | Why it matters here | Was implementation blocked? | What was done instead |
|---|---|---|---|

---

## Known Issues / Risks

**No implementation issues.** Nothing has been built, so there are no bugs, integration failures, or
deferred work items.

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

**No automated test framework exists yet** — it is established in Blueprint Story 1.7. Story 1.1
introduced no application code to unit-test. Verification was structural and was **actually
executed** against this repository on 2026-08-14.

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
