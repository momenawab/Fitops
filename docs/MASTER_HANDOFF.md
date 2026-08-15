# FitOps — Master Agent Handoff Brief

> **Purpose.** This is a **practical operational handoff** so another AI agent — especially Codex —
> can take over the **Master** role without losing context.
>
> **This file is NOT a replacement for** `CLAUDE.md`, `PROGRESS.md`, `docs/MISSING_DECISIONS.md`,
> the Architecture documents, or the Story documents. It has **no authority** over any of them.
>
> **It introduces no architecture or business decision.** Everything here either restates an
> already-approved decision or records an observed operational fact. If this file ever appears to
> contradict an approved document, **the approved document wins and the contradiction must be
> reported.**
>
> **Written:** 2026-08-15, at HEAD `476653d` (before the commit that adds this file).
> **Written by:** Claude Opus 5, acting as Master.

---

## 1. Project Overview

**FitOps** is a **coaching-management SaaS for coaches who already have a website**. The coach keeps
their own site and adds a "Start Coaching" / "Client Login" link pointing at FitOps. FitOps owns
everything after that click:

```
Application → Payment → Client → Plans → Check-ins → Progress
```

Three separate experiences: **Platform Admin Panel** (SaaS owner), **Coach Dashboard** (workspace
owner), **Client Portal** (coach's customer).

**Two payment domains that must never share models:**

| Domain | Direction | Models | Django app |
|---|---|---|---|
| Coach Commerce | Client → Coach | `Order`, `Payment`, `PaymentMethod`, `Subscription` | `commerce`, `workspaces` |
| FitOps Billing | Coach → FitOps | `Plan`, `PlatformPaymentInstruction`, `PlatformSubscription`, `BillingPayment`, `BillingEvent` | `billing` |

**Stack (LOCKED):** Django + DRF + PostgreSQL + Celery/Redis backend; Next.js + TypeScript +
Tailwind + shadcn/ui frontend; Django session authentication; Docker Compose; Hetzner deployment.

**Multi-tenancy model:** `User` is global, `Workspace` is the tenant, `Membership` connects them.
The **workspace slug in the URL is the authoritative tenant context**, resolved server-side. The
frontend is **never** trusted for `workspace_id`.

**Documentation baseline:** Architecture **v1.2.1**, approved and locked.

**We are building the repository at** `/Users/momen/Fitops` — a monorepo (`backend/`, `frontend/`,
`infrastructure/`, `docs/`).

---

## 2. Current Source-of-Truth Order

Read and obey in **exactly** this order:

1. **`CLAUDE.md`** — project instructions and index (repository root).
2. **`PROGRESS.md`** — implementation handoff: what is done, in progress, next (repository root).
3. **`docs/MISSING_DECISIONS.md`** — the registry of deliberately unresolved decisions.
4. **Relevant approved documents** — MVP Spec, Technology Stack, Database & Auth Architecture,
   API Specification, ERD / Django Apps / Repository Architecture, Development Blueprint,
   Design System (all under `docs/`).
5. **The current Story document** — Blueprint §6–§26.
6. **The actual repository state** — `git status`, `git log`, the files themselves.

**Authority note (important, and it differs from reading order):** for *architecture correctness*
the approved documents in (4) outrank `PROGRESS.md`. `PROGRESS.md` records **implementation state
only** and never overrides an approved decision. `CLAUDE.md` is explicitly the **lowest-precedence**
document for architecture questions — it is an index, not a specification. This handoff file ranks
below all of them.

**Conflicts must be REPORTED, never guessed and never silently resolved.**

If you find a conflict:

1. **Stop before coding.**
2. Identify each side with its document and section.
3. Report both options and wait for a decision.
4. If a model or contract genuinely must change, update the architecture documentation in the same
   change — never diverge silently.

The same rule applies to anything listed in `docs/MISSING_DECISIONS.md`: **stop and ask.** Complete
everything that does not depend on it, then report precisely what is blocked.

---

## 3. Current Project Status

**Verified directly from the repository on 2026-08-15**, not from memory:

| Field | Value |
|---|---|
| **Current Epic** | Epic 01 — Project Foundation |
| **Completed Stories** | 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7 — **7 of 8** |
| **Current Story status** | Story 1.7 **COMPLETE and explicitly accepted by the user** (2026-08-15) |
| **Current branch** | `main` |
| **HEAD at time of writing** | `476653d334e856c333fd26cb15d51c45b86b6692` — *"docs(progress): story 1.7 implementation complete and verified"* |
| **Working tree** | **CLEAN** (`git status --porcelain` empty) |
| **Worktrees remaining** | **NONE** — `git worktree list` shows only `/Users/momen/Fitops` |
| **Temp branches** | **NONE** — the three `wt/story-1.7-*` branches were merged and deleted |
| **Delegation workers active** | **NONE** — all Story 1.7 relay processes exited. Antigravity processes visible in `ps` are the **user's running IDE**, not workers. **Do not kill them.** |
| **Remote** | `origin` → `https://github.com/momenawab/Fitops.git` |
| **Push state** | Local `main` is **14 commits AHEAD** of `origin/main`. **Nothing has been pushed.** |
| **Next Story** | **Story 1.8 — CI Pipeline** |
| **Has Story 1.8 started?** | ❌ **NO — NOT STARTED. It must remain NOT STARTED until the user explicitly approves starting it.** |

> ⚠️ **Re-verify these values yourself before acting.** They were true at HEAD `476653d`. The commit
> that adds this handoff file will change HEAD. Run `git rev-parse HEAD`, `git status --porcelain`
> and `git worktree list` at startup — **do not trust this table over the live repository.**

> ⚠️ **Do not push without explicit user instruction.** The 14-commit gap is a fact to report, not a
> problem to fix on your own initiative.

---

## 4. Epic 01 — Completed Work

### Story 1.1 — Monorepo Setup ✅ COMPLETE

- **Implemented:** git repository initialised; monorepo skeleton per ERD §4; `README.md`,
  `.gitignore`, `.env.example`.
- **Acceptance:** repository structure matches the approved tree; no secrets committed.
- **Verification:** structural inspection of the created tree.
- **Defect found and handled:** the ERD **§24** repository tree was **stale** — it omitted the
  `applications` and `billing` apps. Corrected under explicit user approval (Option A).
- **Canonical Django app list (nine, unchanged since):**
  `accounts`, `workspaces`, `coaching`, `clients`, `applications`, `commerce`, `billing`,
  `notifications`, `audit`.
- **Carry-in:** empty directories use `.gitkeep`; each placeholder should be deleted when its
  directory gains real files.

> **Historical note worth knowing.** During this Story the user proposed an app list that added
> `plans`/`checkins` and removed `audit`, stating ERD §15 already said so. Verification showed it
> did **not**. The Master **stopped and reported the contradiction** instead of complying. The user
> confirmed: *"You were correct to stop."* **This is the expected behaviour — verify before
> complying, including when the instruction comes from the user.**

### Story 1.2 — Django Backend Setup ✅ COMPLETE

- **Implemented:** Django 6.0.7, DRF 3.17.1, psycopg 3.3.4; split settings `base/dev/prod`; all nine
  canonical apps registered; **SessionAuthentication only**; hardened session/CSRF cookie settings;
  PostgreSQL configuration; env-driven SMTP plumbing; local static/media; `common/` skeleton.
- **Explicitly NOT built:** no models, migrations, routes, serializers, or business logic.
- **Acceptance:** Django starts, settings load, apps register.
- **Verification:** real `runserver`, real database connection, real app loading — not just
  `manage.py check`.
- **Defect found and handled:** Codex created an **unrequested root `AGENTS.md`** — a 43 KB copy of
  `CLAUDE.md` with "Claude" silently rewritten to "Codex". Deleted; **never committed**.
- **Standing rule from that incident:** a root `AGENTS.md` **must not exist** and **must not be added
  to `.gitignore`** — any reappearance must stay visible as an unintended artifact.

### Story 1.3 — Next.js Frontend Setup ✅ COMPLETE

- **Implemented:** Next.js 16.3.1, React 19.2.8, Tailwind CSS 4, TypeScript 5, ESLint 9,
  React Hook Form 7.85.0, Zod 4.4.3, TanStack Query 5.101.4; shadcn/ui initialised on the approved
  primitive library (**Radix UI** — `style: radix-nova`, `iconLibrary: lucide`); minimal root
  shell, providers and metadata.
- **Explicitly NOT built:** no product UI, no routes, no API client.
- **Acceptance / verification:** `build`, dev server, `typecheck`, `lint` all verified.
- **Defect found and handled:** the `typecheck` script failed from a clean checkout
  (`TS2304: Cannot find name 'LayoutProps'`) because Next.js 16 generates types into the
  git-ignored `.next/types/`. Fixed by making the script `next typegen && tsc --noEmit`.
  **Do not remove the `next typegen` prefix.**
- **Framework artifact:** `next dev` generates `frontend/AGENTS.md` and `frontend/CLAUDE.md`.
  These two **exact paths** are git-ignored as an explicit, narrow exception. **Do not generalise
  this to arbitrary `AGENTS.md` files elsewhere.**
- **Carry-in (still open):** `next-env.d.ts` churn — see §10.

### Story 1.4 — PostgreSQL Setup ✅ COMPLETE

- **Implemented:** PostgreSQL role `fitops` (LOGIN, CREATEDB, **not** superuser) and database
  `fitops` (owner `fitops`, UTF8) on the **native Homebrew PostgreSQL 16.13**.
- **Acceptance:** Django migrations execute; connection is stable.
- **Verification:** `migrate` applied Django's built-in apps (18 `django_migrations` rows);
  `migrate --check` clean; five consecutive connect/query/close cycles; `manage.py test` created and
  destroyed `test_fitops` cleanly.
- **Safety rule that still applies:** **do not** destroy, migrate or reconfigure unrelated databases
  or roles. The databases `couch`, `erp`, `postgres` and the roles `momen`, `erp` belong to the user
  and are **off limits**. No `DROP`, no `TRUNCATE`, no `pg_hba.conf` / `postgresql.conf` edits.
- **Note:** the Docker PostgreSQL added in Story 1.6 is a **separate, empty** development container.

### Story 1.5 — Redis + Celery ✅ COMPLETE

- **Implemented:** Celery configured against **native Homebrew Redis**; `config/celery.py`;
  Celery app exported from `config/__init__.py` as `celery_app`; **JSON-only serialization**;
  exactly **one** baseline health-check task in `backend/common/tasks.py`.
- **Acceptance:** Celery worker starts; Celery communicates with Redis.
- **Verification:** real Redis round-trip, not just configuration inspection.
- **Architecture rule reaffirmed:** `common/` is shared infrastructure and is **NOT** a Django app
  (ERD §23). It is **not** in `INSTALLED_APPS`.
- **Scope fence:** no real business background jobs exist yet. `CELERY_ACCEPT_CONTENT = ["json"]` is
  a deliberate **security** requirement and is now guarded by a regression test.

### Story 1.6 — Docker Compose ✅ COMPLETE

- **Implemented:** six services — `frontend`, `backend`, `postgres`, `redis`, `celery`, `nginx`.
- **Host port mapping (deliberate, to avoid colliding with the native services):**
  `5433 → postgres:5432`, `6380 → redis:6379`.
- **Critical rule:** **inside** the Compose network, services MUST use the container service names
  and **native container ports** — `postgres:5432` and `redis:6379`. They must **never** use
  `postgres:5433` or `redis:6380`.
- **Critical rule:** the Docker PostgreSQL starts **empty** and must **not** reuse, migrate or copy
  the native Homebrew database data.
- **Defect found and handled:** `docker compose ps` reported the backend as `Up` while it was
  **completely non-functional** — both backend and celery failed with
  `ImproperlyConfigured: Error loading psycopg2 or psycopg module`. Probe: `ldconfig -p | grep -c libpq` → **0**.
  Fixed by installing **`libpq5`** in `infrastructure/docker/backend.Dockerfile` — deliberately
  **without** changing `backend/requirements.txt` and **without** switching to `psycopg[binary]`.
- **Second defect:** `package-lock.json` was not cross-platform; regenerated inside a Linux
  container. `npm ci` (not `npm install`) is retained in the Dockerfile because reproducible builds
  are required.
- **Verification:** full stack functionally verified via logs and functional probes; native Homebrew
  PostgreSQL and Redis verified untouched **during and after** the run; `docker compose down`
  verified not to affect the native services.

> ⚠️ **The single most important lesson of Story 1.6:** a container reporting `Up` is **not**
> evidence that the service works. See §8.

### Story 1.7 — Testing and Quality Baseline ✅ COMPLETE (accepted 2026-08-15)

- **Approved tool set** (user decision — the Technology Stack names no test/lint/format tooling, so
  this gap was **reported and decided**, not filled silently):

  | Side | Approved | Explicitly rejected / deferred |
  |---|---|---|
  | Backend | Django built-in test runner; **Ruff** for lint *and* format | pytest / pytest-django; **backend type checking DEFERRED — NO mypy, NO django-stubs** |
  | Frontend | Vitest, `@testing-library/react`, jsdom, Prettier, `eslint-config-prettier` | jest; existing ESLint + TypeScript retained unchanged |

- **Delivered:** `backend/requirements-dev.txt` (`ruff==0.16.3`); `backend/pyproject.toml`
  (ruff-only config: py314, line-length 100, rules E/F/I/B); `backend/tests/` with 3 smoke tests;
  `frontend/vitest.config.mts`; `frontend/.prettierrc.json` + `.prettierignore`;
  `frontend/app/page.test.tsx` with 2 smoke tests; `eslint-config-prettier/flat` appended **last**;
  `test` / `format` / `format:check` scripts; and
  **`infrastructure/scripts/checks.sh`** — the single aggregate verification command.
- **Acceptance:** *"All baseline checks can run locally."* — met. All **7 gates** pass, exit 0.
- **Task split:** T1 backend → Codex (VERY HARD) · T2 frontend → AGY (MEDIUM) · T3 entrypoint →
  OpenCode (SIMPLE). T1 ∥ T2 in parallel; T3 after both.
- **Key commits:** `966f2e2` (backend) · `c17ca85` (frontend) · `4fe7073` (checks.sh) ·
  `788a086`, `476653d` (PROGRESS.md).

**Defects discovered and how they were handled:**

1. **Zero-test false green (most important).** Run from the repository root,
   `manage.py test` printed `NO TESTS RAN` and **exited 0**. Django discovers tests relative to the
   working directory and `backend/` is not an importable package. Guarded in `checks.sh`, which runs
   the gate from `backend/` **and** fails on "no tests collected". The guard was **proven to fire**
   by removing the smoke tests (script exited 1). **Carry-in to Story 1.8.**
2. **`printf` bug in `checks.sh`.** `printf '-------\n'` was parsed by bash as options, printing
   `invalid option` on every run. Fixed by Master to `printf -- '-------\n'` and **disclosed** in the
   commit message rather than folded silently into the worker's output.
3. **Unapproved dependency avoided by probing.** A Vitest + React setup normally needs
   `@vitejs/plugin-react`, which was **not** approved. Rather than assume, Master empirically proved
   Vitest 4's built-in esbuild transform renders JSX with only the approved packages. No extra
   dependency was added.

**Mutation checks** (a passing test proves nothing if it cannot fail):

| Mutation | Result |
|---|---|
| `CELERY_ACCEPT_CONTENT` widened to allow an unsafe non-JSON serializer | exit **1** — caught |
| `<h1>FitOps</h1>` → `<h1>NotFitOps</h1>` | exit **1** — caught |

Both sources restored; restoration verified by empty `git diff`.

**Carry-in:** `next-env.d.ts` churn remains **unresolved** — see §10.

---

## 5. Architecture Rules That Must Not Be Violated

**Django / architecture**

- `coaching` is **ONE** Django app. **Never** split it into `plans` / `checkins`.
- `audit` **remains** a Django app. Never remove it (25+ `AuditLog` references; approved billing rule).
- The **canonical nine-app list** must stay consistent everywhere:
  `accounts`, `workspaces`, `coaching`, `clients`, `applications`, `commerce`, `billing`,
  `notifications`, `audit`.
- `common/` is **shared infrastructure, NOT a Django app**. Not in `INSTALLED_APPS`.
- **No `UserSession` model.** **No `token_hash` / session-token architecture.**
- **SessionAuthentication only**, unless an approved Story explicitly changes it.
- **No JWT and no token auth** unless explicitly approved.
- `ClientProfile` is **global identity** and must **never** carry `workspace_id`.
- Workspace-scoped records FK to **`Membership`**, not to `ClientProfile`.
- **Never trust a frontend-supplied `workspace_id`**, price, role, or state.
- The two payment domains (**Coach Commerce** vs **FitOps Billing**) **never** share models or enums.

**Process**

- Unresolved decisions in `docs/MISSING_DECISIONS.md` must **never** be guessed. Stop and ask.
- **Workers NEVER commit.** Master reviews the **actual diff** and commits.
- **No worker self-report is trusted without independent verification.**
- **No pipe-masked exit codes.** **No fake green checks.**
- **No scope creep** — implement only the current Story.
- **Accepted Stories are not silently modified to solve a later Story's problem.** Report ownership
  and create a bounded fix when appropriate.
- **Do not start a future Story** just because a dependency looks convenient.
- Approved documents are authoritative where specified.
- **No `AGENTS.md` at the repository root** unless explicitly approved, and **do not add a root
  `AGENTS.md` to `.gitignore`** — reappearance must remain visible.
  *(The narrow exception: `frontend/AGENTS.md` and `frontend/CLAUDE.md` are ignored by exact path
  because Next.js regenerates them. Do not generalise it.)*

---

## 6. Current Delegation / Multi-Agent Operating Model

**Claude is currently acting as Master.**

**When Claude reaches its context/usage limit, Codex becomes the temporary Master and MUST continue
from this handoff instead of redesigning the process.**

```
MASTER
  ├── very hard / high-risk tasks → Codex
  ├── hard tasks                  → Codex
  ├── medium / lower complexity   → AGY
  └── lowest complexity           → OpenCode
```

**Assign by complexity, reasoning difficulty, regression risk and architectural impact — NOT by task
size.** If a task could reasonably belong to two levels, **prefer the safer / higher-capability
worker.**

- 🔴 **Codex** — complex architecture, difficult reasoning, security-sensitive implementation,
  non-trivial test infrastructure, cross-cutting changes, high regression risk, correctness ≫ speed.
- 🟡 **AGY** — normal implementation work, moderate reasoning, multiple files but straightforward
  logic, tests/config with some complexity, independent and safe to delegate.
- 🟢 **OpenCode** — straightforward configuration, simple test setup, repetitive changes,
  boilerplate, simple scripts, documentation, low-risk isolated implementation.

**Rules**

- Master reviews **every** task.
- Tasks are isolated in **git worktrees**.
- **Workers NEVER commit.** Master commits after review.
- Independent tasks may run **in parallel**; dependent tasks wait for their dependencies.
- A worker that fails gets a **bounded rework brief**, sent to the **same worker/session** where
  possible.
- **Repeated failure must be escalated, not silently reassigned.**
- **Never send two workers into the same mutable tree.**
- Always inspect the **actual `git diff` / `git status`**.
- Verify with **real exit codes captured directly**.
- **Never** use `command | tail` (or any pipe) when the exit code matters — `$?` captures the *last*
  program's status. Use `cmd > file 2>&1; echo "EXIT=$?"`, or `PIPESTATUS` / `set -o pipefail`.
- If a worker needs a permission, **prove the exact permission is necessary before granting it.**

**Priority order:** **Correctness > continuity > speed > provider utilisation.**

**Relay invocation (verified working):**

```
node ~/.claude/skills/{codex,agy,opencode}-delegate/scripts/relay.mjs \
  --brief <brief-file> --cd <worktree> --out-dir <dir> --timeout 25m
```

- The flag is **`--brief`**, *not* `--prompt-file`.
- **OpenCode requires an explicit `--model`** — it has no default. Authenticated providers are
  `zai-coding-plan` and `opencode-go`; `zai-coding-plan/glm-5.3` was used successfully.
- Codex accepts `--effort high`. AGY accepts `--print-timeout`.
- Relays **never commit** — that is always Master's job.
- Codex logs noisy MCP auth errors at startup; they are **harmless**.

**Brief-writing lessons that saved real time:**

- State the worker's sandbox limits **up front** and include an early **connectivity gate** so a
  worker fails fast and cleanly rather than improvising.
- Tell the worker explicitly **which gates it cannot run** and that Master will run them.
- Require a **report contract** ending in explicit confirmations of what was *not* done.
- Demand honesty: *"Do NOT report any check as passing. You ran nothing."*

---

## 7. AGY Permission Model

**Config file:** `~/.gemini/antigravity-cli/settings.json` — **user-global**, so avoid broad
permanent permissions.

**Current persistent state (verified, keep it this way):**

```json
{
  "colorScheme": "dark",
  "permissions": { "allow": ["command(git status)"] },
  "trustedWorkspaces": ["/Users/momen/Fitops"]
}
```

**Per-dispatch protocol:**

1. Create the isolated worktree **first**.
2. Add **only** the exact rule `write_file(<absolute worktree path>)` immediately before dispatch.
3. Launch via the delegate relay.
4. **Remove the temporary rule after the task lands.**

**Hard prohibitions**

- **Never** `write_file(*)` or any global unrestricted write rule.
- **Never** a broad root path, and never write access to `/Users/momen/Fitops` itself.
- **Never** `--dangerously-skip-permissions`.
- **Do not pre-authorise** `command(npm)`, `command(python)`, `command(git)`, `command(npx)`,
  `command(rm)`, `command(sudo)`, `command(brew)`, `command(docker)`, `command(psql)`,
  `command(redis-cli)`, `command(curl)`, or similar.
- Add a command rule **only** when an actual denial proves it necessary, and then only the
  narrowest possible rule.

**Empirically proven (do not re-derive):**

- Path-scoped `write_file(<absolute path>)` **works** — writes inside the worktree succeed and
  writes outside are **DENIED**.
- Story 1.7's T2 completed with **zero permission denials** using only
  `command(git status)` + the temporary worktree write rule. A **file-authoring** task needs nothing
  more.
- A second denial variant exists in the AGY binary: *"Settings allow-rules do not apply; re-run with
  --dangerously-skip-permissions"* — meaning **some tools are not allow-listable at all**. Not yet
  encountered. If you hit it, **stop and report** — do not use the flag.

**Practical consequence:** AGY effectively **cannot run build/test commands**. Brief it as a
**file-authoring** worker and have Master run every gate.

---

## 8. Verification Philosophy

**This section encodes real failures from this project. Treat it as binding.**

- **Worker reports are claims, not evidence.** Master reruns every important check.
- **Capture the test exit code directly.** Never read `$?` after a pipe.
  > **Real incident (Story 1.6):** Master ran `npm ci --silent 2>&1 | tail -5; echo NPM_CI_EXIT=$?`
  > and reported a fix as "proven". `$?` was **`tail`'s** exit code. The real value was **1** — the
  > fix was ineffective. A retraction had to be recorded. **This is why the rule exists.**
- **Inspect filesystem state**, don't infer it.
- **`docker compose ps` alone is insufficient.** Inspect **logs** and **functional behaviour**.
  > **Real incident (Story 1.6):** backend showed `Up` while completely non-functional.
- **A running process or container does not mean the service works.**
- **Mutation testing is the right tool for verifying baseline tests** — break the subject, confirm
  the suite fails, restore, confirm the restoration with an empty `git diff`.
- **Zero tests must NEVER count as a passing suite.**
  > **Real incident (Story 1.7):** `manage.py test` from the repo root → `NO TESTS RAN`, exit **0**.
- **After delegated work, verify no stray files, processes or worktrees remain.**
  Check `git status --porcelain`, `git worktree list`, and `ps` — and when checking processes,
  distinguish **delegation workers** from the **user's own applications**. The Antigravity IDE
  processes on this machine are the user's; **do not kill them**.
- **Settle windows may be needed** when tools create asynchronous artifacts.
  > **Real incident (Story 1.2):** an `AGENTS.md` artifact **reappeared after** the commit. Re-check
  > after a short delay before declaring a tree clean.
- **When evidence contradicts itself, say so** and investigate — do not pick the convenient reading.
  > **Real incident (Story 1.6):** Master's "stale build cache" hypothesis was wrong; re-examining
  > the contradiction is what exposed the pipe-masked exit code above.

---

## 9. Current Environment

Verified on this machine:

| Component | Version / state |
|---|---|
| OS | macOS (Apple Silicon), Darwin 27.0.0 |
| Docker | 29.7.2 — Docker Desktop working |
| Docker Compose | v5.3.1 |
| PostgreSQL | **16.13, native Homebrew**, `127.0.0.1:5432`, `pg_isready` OK |
| Redis | **8.10.0, native Homebrew**, `127.0.0.1:6379`, `PING → PONG` |
| Node | v24.12.0 (nvm) |
| npm | 11.6.2 |
| Python | 3.14.6 |
| Virtualenv | `/Users/momen/Fitops/.venv` — Django 6.0.7, DRF 3.17.1, psycopg 3.3.4, celery 5.6.3, redis 8.1.0, **ruff 0.16.3** |

**Worker sandbox limits (discovered incrementally — build briefs around them):**

- **No network** — workers cannot install packages (found in Story 1.2 T1).
- **No socket access** — workers cannot reach localhost PostgreSQL or Redis (Story 1.4).
- **No Docker** (Story 1.6).
- AGY additionally has **narrow command permissions** (§7).

**Therefore: Master performs all installs and all live-service verification.**

**Native services are protected.** Do **not** stop, delete, reconfigure or migrate the Homebrew
PostgreSQL and Redis services. Verify they are untouched **during and after** any Docker work.

---

## 10. Open Decisions / Carry-ins

### Registered in `docs/MISSING_DECISIONS.md` (authoritative — do not restate or resolve elsewhere)

| ID | Subject | Affects |
|---|---|---|
| **B24** | Permanent archive retention duration | Story 22.6 |
| **B25** | Archive restoration scope | Story 22.9 |
| **B26** | Long-expired multi-period reactivation | Story 22.10b |
| **B27** | Terminal `CANCELLED` cleanup lifecycle | Story 22.10c |
| **SMTP provider** | Deliberately unselected; deployment configuration | Blocks **no** Story |

**None of these affected Stories 1.1–1.7.** They are expected to matter only in **Epic 22**.
**If implementation reaches one, STOP AND ASK.**

### Implementation carry-ins (recorded in `PROGRESS.md` → *Known Issues / Risks*)

1. **`next-env.d.ts` churn — OPEN, carry-in to Story 1.8.**
   `next dev` writes `import "./.next/dev/types/..."`; the standalone `next typegen` (which
   `npm run typecheck` runs) rewrites it to `./.next/types/...`. Whichever ran last dirties the
   working tree. **Not functionally broken** — `typecheck` runs `typegen` first and self-corrects,
   so the gate passes either way. The committed version is the **`typegen`** variant.
   **Impact on 1.8:** if the workflow adds a "working tree must be clean" assertion, this trips it.
   **Decide in Story 1.8 — do not resolve it silently.**

2. **Zero-test false green — mitigated locally, open for CI.**
   Guarded by `infrastructure/scripts/checks.sh`. Story 1.8 should **invoke that script** rather
   than calling Django directly; if it ever calls Django directly it **must reproduce the guard**.

3. **Local `main` is 14 commits ahead of `origin/main`.**
   Nothing from Epic 01 has been pushed. Story 1.8's DoD is *"pull requests automatically run
   required checks"*, which cannot be observed until commits reach the remote.
   **Master must not push without explicit user instruction** — confirm when Story 1.8 begins.

4. **`.gitkeep` convention.** Placeholders keep empty ERD §24 directories in version control; delete
   each one when its directory gains real files. (`backend/tests/.gitkeep` was correctly removed in
   Story 1.7; `infrastructure/scripts/.gitkeep` remains and is still appropriate.)

---

## 11. Next Work — Story 1.8

> **DO NOT IMPLEMENT IT. Story 1.8 has NOT been started and must remain NOT STARTED until the user
> explicitly approves starting it.**

**Approved scope — Development Blueprint §6, verbatim:**

```
## Story 1.8 — CI Pipeline

### Tasks

GitHub Actions workflow for:

- Backend tests
- Frontend tests
- Linting
- Type checking
- Build validation

### DoD

Pull requests automatically run required checks.
```

Note it defines a **DoD**, not "Acceptance Criteria" — quote it as written.

**Dependencies:** Story 1.7 (complete) provides every gate the workflow must run. Stories 1.2–1.6
provide the backend, frontend, database, broker and container definitions.

**What Story 1.7 contributes / constrains:**

- `infrastructure/scripts/checks.sh` runs all seven gates and exits non-zero on any failure.
  **Prefer invoking it** over duplicating the gate list — one definition of "the checks", used
  identically locally and in CI.
- Backend dev dependencies come from **`backend/requirements-dev.txt`**; frontend from **`npm ci`**
  (reproducible builds — do **not** switch to `npm install`).
- CI needs **PostgreSQL** for the backend test gate (service container or equivalent). The current
  tests do **not** require a running Redis — Celery configuration is asserted from settings only.
- Carry the **zero-test guard** and the **`next-env.d.ts`** decision (§10).
- Note that **"Build validation"** appears in Story 1.8's task list but is **not** one of Story 1.7's
  seven local gates — `npm run build` is currently **not** part of `checks.sh`. The next Master must
  decide, within Story 1.8's approved scope, how build validation is run. **Report this rather than
  silently altering `checks.sh`**, which belongs to an accepted Story.

**The next Master MUST read the Story 1.8 document in the Blueprint before dispatching anything.**
**Do not assume a task breakdown from this file** — inspect the Story and split it by complexity and
dependency using the delegation model in §6, then present the breakdown for approval before
dispatching.

---

## 12. Master Handoff Procedure

Exact startup procedure for a new Master:

1. Read **`CLAUDE.md`**.
2. Read **`PROGRESS.md`**.
3. Read **`docs/MISSING_DECISIONS.md`**.
4. Read the **current Story document** (Blueprint §6–§26).
5. Inspect **`git status`**, **`git worktree list`**, **current HEAD**.
6. **Inspect actual repository state before trusting historical reports** — including this file.
7. Confirm the **current Story status**.
8. Identify **dependencies**.
9. Split work by **complexity and dependency**.
10. **Hardest tasks → Codex.**
11. **Less difficult tasks → AGY.**
12. **Lowest complexity → OpenCode.**
13. Create **isolated worktrees**.
14. **Dispatch only after scope and permissions are correct.**
15. **Review every result independently.**
16. **Run verification with real exit codes.**
17. **Commit only after PASS.**
18. **Update `PROGRESS.md` after each significant task** — not only at the end.
19. Before Story acceptance, run a **final whole-Story regression**.
20. **Do NOT start the next Story until the current one is explicitly accepted / complete.**

**Additional standing rules**

- Present the task breakdown **before** dispatching, with: Task ID · description · Complexity ·
  Assigned worker · Dependencies · Allowed files · Acceptance criteria · Review gates.
- Report gaps and **stop**; never fill them with defaults.
- Commit format: `type(scope): message`. Small, scoped commits — never mega-commits.
- **Never commit secrets.** `.env.example` only.

---

## 13. Emergency / Context-Limit Handoff

**If Claude reaches its context or usage limit, Codex becomes Master.**

Codex **MUST**:

- **Not behave as merely a worker.** It assumes the **Master** role.
- Read **this handoff** + **`CLAUDE.md`** + **`PROGRESS.md`** + **`docs/MISSING_DECISIONS.md`**.
- **Inspect the real repository** — `git status`, `git log`, `git worktree list`, the actual files —
  and trust that over any historical report, **including this file**.
- Inherit the full Master responsibilities: **planning, delegation, review, verification, commits,
  and `PROGRESS.md` updates**.
- **Continue the current Story** if one is active.
- If the current Story is complete and accepted, proceed to the next Story **only** according to the
  Blueprint **and** explicit user approval.
- **Not redesign architecture** and **not resolve open decisions by itself**. Unresolved decisions
  are reported to the user, never guessed.

Codex must **not**:

- Create a root `AGENTS.md` (it has done so before — see §4, Story 1.2).
- Commit on behalf of a worker, or let a worker commit.
- Trust a worker's self-report without independent verification.
- Push to `origin` without explicit user instruction.

---

## 14. Final Handoff Snapshot

```
CURRENT_EPIC:          Epic 01 — Project Foundation
CURRENT_STORY:         Story 1.7 — Testing and Quality Baseline
CURRENT_STORY_STATUS:  COMPLETE — accepted by the user 2026-08-15
LAST_ACCEPTED_STORY:   Story 1.7
CURRENT_BRANCH:        main
CURRENT_HEAD:          476653d334e856c333fd26cb15d51c45b86b6692
                       (re-verify: this handoff commit will advance HEAD)
WORKTREE_CLEAN:        YES — git status --porcelain empty; no extra worktrees; no temp branches
REMOTE_STATE:          origin/main behind local main by 14 commits — NOTHING PUSHED
NEXT_STORY:            Story 1.8 — CI Pipeline  (NOT STARTED — requires explicit user approval)
CLAUDE_ROLE:           Master (planner, reviewer, verifier, committer, PROGRESS.md owner)
FAILOVER_MASTER:       Codex — assumes full Master role, does not act as a worker
DELEGATION_RULE:       very hard / hard → Codex | medium → AGY | lowest → OpenCode
                       (assign by complexity and risk, never by size;
                        when between two levels, choose the safer/higher-capability worker)
AGY_PERMISSION_MODE:   persistent = command(git status) ONLY;
                       temporary per-dispatch write_file(<exact worktree path>), removed after;
                       never write_file(*), never --dangerously-skip-permissions
OPEN_DECISIONS:        B24, B25, B26, B27 (all Epic 22) + SMTP provider (blocks no Story)
                       — authoritative registry: docs/MISSING_DECISIONS.md
CRITICAL_CARRY_INS:    1. next-env.d.ts churn (next dev vs next typegen) — UNRESOLVED, decide in 1.8
                       2. manage.py test exits 0 with zero tests — guarded in checks.sh; CI must too
                       3. "Build validation" is in Story 1.8 scope but is NOT a current checks.sh gate
                       4. local main is 14 commits ahead of origin — do not push without approval
WORKERS_ACTIVE:        NONE (Antigravity processes in `ps` are the user's IDE — do not kill)
```

---

*End of handoff. This file has no authority over `CLAUDE.md`, `PROGRESS.md`,
`docs/MISSING_DECISIONS.md`, or the approved architecture documents. Verify the live repository
before acting on anything recorded here.*
