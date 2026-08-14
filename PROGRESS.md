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
| **Current Story** | Story 1.3 — Next.js Frontend Setup — **IN PROGRESS** |
| **Overall status** | Epic 01 in progress — 2 of 8 Stories complete; 1.3 started |
| **Execution model** | Delegated. Claude = Master; workers = Codex / AGY / OpenCode via `delegate-skills` |
| **Last updated** | 2026-08-14 |
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

**Story: 1.3 — Next.js Frontend Setup** (Epic 01 — Project Foundation)

Started 2026-08-14. **Option A execution model, user-approved:** Master performs only the
network-dependent provisioning, then **one** bounded implementation task goes to Codex.

### Acceptance criteria (Blueprint §6)

- Frontend builds successfully.
- Development server works.
- Basic application shell exists.

### Blocker resolved by Option A

The Codex sandbox has **no outbound network** — verified empirically with a read-only probe
(`curl: (6) Could not resolve host: registry.npmjs.org`, 0 files touched). Story 1.3 requires package
downloads, so Master provisions and Codex implements. `--sandbox danger-full-access`,
`--dangerously-skip-permissions` and AGY headless are all **prohibited** by user decision.

### Task board

```
[x] P   Master provisioning (network only)      Claude   ✅ COMPLETE
[~] I   Story 1.3 implementation (ONE task)     Codex    DISPATCHED
[ ] R   Master review + final acceptance        Claude   blocked on I
```

### Master provisioning scope — verified against the approved stack

| Command | Justification |
|---|---|
| `create-next-app --ts --tailwind --eslint --app --no-src-dir --import-alias "@/*" --use-npm` | Technology Stack "Next.js + TypeScript", "Tailwind CSS"; App Router required by ERD §25 route groups `(marketing)` / `[workspaceSlug]`; no `src/` because ERD §25 shows `frontend/app/` |
| `npm install react-hook-form zod @tanstack/react-query` | Technology Stack "Forms: React Hook Form", "Zod", "Server State: TanStack Query" |
| `npx shadcn@latest init` | Technology Stack "shadcn/ui"; brings lucide-react, mandated by design.md §25 |

Scaffolded into a temp directory first, because `create-next-app` refuses a non-empty target and
`frontend/` holds Story 1.1 `.gitkeep` placeholders. **Master deletes nothing** — placeholders merge
and their cleanup belongs to Codex.

**Nothing else installed:** no Prettier, no test libraries, no state managers, no HTTP clients, no
component kits.

**Judgment surfaced:** `--eslint` included because it is part of the official Next.js scaffold, even
though Blueprint Story 1.7 owns the lint/format/typecheck *baseline*. Flagged to the user.

### Provisioning status — PARTIAL, blocked on a decision

| Step | Status |
|---|---|
| `create-next-app` scaffold | ✅ Next.js 16.3.1, React 19.2.8, Tailwind 4, TypeScript 5, ESLint 9 |
| Scaffold moved into `frontend/` | ✅ 6 files deliberately excluded (`.git`, `.next`, `AGENTS.md`, `CLAUDE.md`, `README.md`, `.gitignore`) |
| `react-hook-form` + `zod` + `@tanstack/react-query` | ✅ 7.85.0 / 4.4.3 / 5.101.4 |
| `shadcn init` | ✅ `style: radix-nova`, `radix-ui` installed, `iconLibrary: lucide`, no Base UI |

**Note:** `create-next-app` now generates its own `AGENTS.md` and `CLAUDE.md` in every project. Both
were excluded. This is very likely the origin of the Story 1.2 `AGENTS.md` artifact — a scaffolder
convention, not a rogue worker. Recorded as evidence; no retroactive attribution asserted.

### RESOLVED — shadcn/ui primitive library: **Radix UI** (user decision, 2026-08-14)

**Approved: `shadcn/ui` → Radix UI primitives.** Base UI and React Aria are explicitly rejected.

This is the foundation under every FitOps component from here on. It is recorded here as an
implementation decision; the architecture documents were **not** modified, since the Technology Stack
already names "shadcn/ui" and no approved document specifies a primitive library.

Initialized with `npx shadcn@latest init -b radix -y --no-monorepo`.

#### Two failed init attempts before this (recorded for accuracy)

1. `--base-color neutral` → `error: unknown option` (flag removed from the CLI). Nothing created.
2. `-y --no-monorepo` → hung on an interactive "Select a component library" prompt that `-y` does
   not skip. Nothing created.

**Both returned shell exit code 0 because the command was piped through `tail`** — the wrapper
succeeded while the tool did nothing. Caught only by inspecting the filesystem
(`components.json` absent, no shadcn dependencies installed).

**Process lesson: never read a piped command's exit code as the tool's exit code.** Subsequent runs
use `set -o pipefail` and an explicit exit-code echo, and every provisioning step is confirmed
against the filesystem rather than against a status line.

### Provisioned stack (final, verified on the filesystem)

| Package | Version | Approved by |
|---|---|---|
| next / react / react-dom | 16.3.1 / 19.2.8 / 19.2.8 | Technology Stack "Next.js" |
| typescript | 5 | "Next.js + TypeScript" |
| tailwindcss + @tailwindcss/postcss | 4 | "Tailwind CSS" |
| shadcn/ui → **radix-ui** | `style: radix-nova`, `iconLibrary: lucide` | "shadcn/ui"; Radix per user decision; Lucide per design.md §25 |
| clsx / tailwind-merge / class-variance-authority / lucide-react | 2.1.1 / 3.6.0 / 0.7.1 / 1.31.0 | shadcn/ui transitive |
| react-hook-form | 7.85.0 | "Forms: React Hook Form" |
| zod | 4.4.3 | "Zod" |
| @tanstack/react-query | 5.101.4 | "Server State: TanStack Query" |
| eslint / eslint-config-next | 9 / 16.3.1 | Next.js official scaffold |

**Not installed, deliberately:** `@hookform/resolvers` (not in the approved stack — the first Story
that builds a real form will need it), react-query devtools, Prettier, any test library.

**Divergence to resolve in a later UI Story:** the `nova` preset ships **Geist** as its font, while
design.md §8 mandates **Inter**. Theme tokens are explicitly out of Story 1.3 scope; design.md
remains authoritative and was NOT modified.

### shadcn init took four attempts — all recorded

| # | Command | Result |
|---|---|---|
| 1 | `--base-color neutral` | `error: unknown option` — flag removed from CLI. Nothing created. |
| 2 | `-y --no-monorepo` | Hung on interactive "Select a component library" prompt. Nothing created. |
| 3 | `-b radix -p radix-nova` | `Invalid preset: radix-nova. Available: nova, vega, maia, lyra, mira, luma, sera, rhea`. Nothing created. |
| 4 | `-b radix -p nova` | ✅ Success — `components.json`, `lib/utils.ts`, fonts + `globals.css` updated |

Attempts 1–2 reported shell exit code **0** while the tool did nothing, because the command was
piped through `tail`. **Process lesson applied from attempt 3 onward: `set -o pipefail` plus an
explicit `echo $?`, and every provisioning step confirmed against the filesystem rather than a
status line.** Attempt 3's real failure (`SHADCN_EXIT=1`) was caught only because of that change.

### Codex implementation task — dispatched

ONE bounded task covering: package identity, app shell + root layout, TanStack Query provider
(per-session client, not module scope), Zod example schema proving configuration, TypeScript strict
+ `@/*` alias + `typecheck` script, `frontend/.env.example`, and `.gitkeep` cleanup only where
directories now hold real files.

**Explicitly fenced out of the brief:** the ERD §25 route tree, all product UI, auth flows, API
integration, business logic, design-system implementation, shadcn component additions, dependency
changes, test/lint/CI setup, backend and docs changes, and `AGENTS.md`.

**Scope call recorded:** ERD §25's route tree (`(marketing)/`, `auth/`, `onboarding/`, `admin/`,
`[workspaceSlug]/**`) is **not** created in this Story. Story 1.3's criterion is "Basic application
shell exists"; those 15 route areas are owned by Epics 06–19.

### Last completed step

"Provisioning complete (Next.js + Tailwind + TS + shadcn/Radix + RHF + Zod + TanStack Query); single Codex implementation task dispatched."

### Next step

"Independently review Codex's final diff, run all Story 1.3 gates (typecheck, lint, build, dev-server boot), then final Story acceptance."

---

## Next step

"Await user decision on the network-bound scaffolding step, then dispatch the single Story 1.3 implementation brief."

---

## Next

| Field | Value |
|---|---|
| **Epic** | Epic 01 — Project Foundation |
| **Story ID** | Story 1.3 |
| **Story title** | Next.js Frontend Setup |

**Why it is next:** Blueprint §6 lists 1.3 immediately after 1.2 within Epic 01. Story 1.2, its only
prerequisite, is COMPLETE.

**Dependencies:** Story 1.1 ✅ · Story 1.2 ✅.

**Scope (Blueprint §6, quoted tasks):** initialize Next.js · configure TypeScript · configure
Tailwind · configure shadcn/ui · configure React Hook Form · configure Zod · configure TanStack Query.

**Acceptance criteria (Blueprint §6):** frontend builds successfully · development server works ·
basic application shell exists.

**Prerequisite checks before starting:**

1. **User approval to start Story 1.3** — do not start automatically.
2. Node v24.12.0 confirmed present ✅.
3. `frontend/` currently holds only `.gitkeep` placeholders from Story 1.1 — scaffolding may need
   them removed.
4. Re-read Blueprint §6 Story 1.3, ERD §25 (frontend structure) and `docs/04-design/design.md`.
5. Confirm no unresolved decision in `docs/MISSING_DECISIONS.md` applies (none currently do).

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
