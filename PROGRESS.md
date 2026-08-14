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
| **Current Story** | Story 1.2 — Django Backend Setup — **IN PROGRESS** |
| **Overall status** | Epic 01 in progress — 1 of 8 Stories complete, 1.2 started |
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

**Story: 1.2 — Django Backend Setup** (Epic 01 — Project Foundation)

Started 2026-08-14. Executed via **delegated workers** (`delegate-skills`), Claude as Master.

### Acceptance criteria (Blueprint §6)

- Django starts successfully.
- Database connection works.
- All approved apps load correctly.

### Task board

```
[x] T1  Django skeleton + split settings + env loading + requirements + common/   Codex     ✅ PASS (89ea8e5)
[x] T2  Nine canonical Django app packages                                        OpenCode/GLM  ✅ PASS (a2b8988, merged f4a0292)
[x] T3  Register nine apps in INSTALLED_APPS                                      Codex     ✅ PASS (2bc78e3)
[x] T4  DRF config (session auth + pagination)                                    Codex     ✅ PASS (56658c4)
[x] T5  Session framework + cookie/CSRF security                                  Codex     ✅ PASS (ac106f1)
[x] T6  PostgreSQL DATABASES from env                                             OpenCode/GLM  ✅ PASS (842440f) — live connection verified
[x] T7  Email backend + SMTP from env                                             OpenCode/GLM  ✅ PASS (8182cab)
[~] T8  Static/media handling                                                     OpenCode/GLM  DISPATCHED (holds settings lock)
[ ] T9  Acceptance verification                                                   Claude    blocked on T1-T8
```

### Approved scope decisions for this Story

- **DRF error envelope DEFERRED** — T4 configures DRF infrastructure only (session auth +
  pagination). The custom `{"error":{...}}` handler lands in a later API/error-handling Story.
  This is a Story-scope clarification; the API architecture document was **not** changed.
- **`common/` skeleton created in T1** — empty packages with `__init__.py` only, zero business
  logic. Real functionality stays owned by its Blueprint Story (e.g. tenant utilities in 3.4).

### Isolation

Settings-lock: only one worker may modify `backend/config/settings/base.py` at a time. Worktree
isolation is managed by Master via `git worktree` and dispatched into with the relay's `--cd` flag —
`delegate-skills` relays provide no worktree flag of their own.

**Wave 1 live isolation (2026-08-14):**

| Task | Worker | Working tree | Exclusive scope |
|---|---|---|---|
| T2 | AGY | worktree `t2-apps` at `…/scratchpad/wt-apps` | `backend/apps/**` |
| T4 | Codex | main tree (branch `main`) | `backend/config/settings/base.py` + `backend/common/pagination/__init__.py` |

The two scopes are file-disjoint, and each brief names the other worker's territory as
"ANOTHER WORKER IS EDITING THIS CONCURRENTLY — do not touch". T4 holds the settings lock.

**Landing order:** T4 lands on `main` first (it is already in the main tree), then branch `t2-apps`
is merged. Merging requires a clean main tree, so the order is not interchangeable.

**Standing rule discovered in T1:** workers have no network. Master performs all package installs
and runs all gates that need them.

### Current state

**T1 COMPLETE and landed** — commit `89ea8e5`. All other tasks unstarted, awaiting approval.

#### T1 review record (Master-executed, not worker self-report)

| Gate | Result |
|---|---|
| `pip install -r backend/requirements.txt` | `Successfully installed Django-6.0.7 asgiref-3.12.1 djangorestframework-3.17.1 psycopg-3.3.4 sqlparse-0.6.0` |
| `manage.py check` dev / prod | `System check identified no issues (0 silenced).` (both) |
| prod without `DJANGO_SECRET_KEY` | `ImproperlyConfigured: DJANGO_SECRET_KEY must be set in production.` ✅ intended |
| `.venv` ignored · forbidden config absent · no apps early · `common/` 0-byte | all ✅ |

#### T4 review record (Master-executed) — commit `56658c4`

| Gate | Result |
|---|---|
| `manage.py check` dev / prod | `System check identified no issues (0 silenced).` (both) |
| `rest_framework` in INSTALLED_APPS | `True` |
| `LOCAL_APPS` still empty (T3's territory) | `True` ✅ |
| auth classes | `['SessionAuthentication']` — matches locked Phase 1 auth decision |
| permission classes | `['IsAuthenticated']` — deny-by-default |
| paginator | `FitOpsPageNumberPagination` · page_size 20 · param `page_size` · max 100 |
| EXCEPTION_HANDLER | DRF default — custom envelope correctly **deferred** ✅ |
| throttle classes | `[]` — correctly not configured (Epic 20) |
| scope | only the 2 allowed files; DATABASE/SESSIONS/EMAIL/STATIC sections untouched ✅ |

**Master decision — now USER-APPROVED (2026-08-14):** `DEFAULT_PERMISSION_CLASSES = IsAuthenticated`
is the approved deny-by-default posture for this project. Public endpoints must explicitly opt out
with `AllowAny` in their own future Stories when required.

#### T2 review record (Master-executed) — commit `a2b8988`, merged `f4a0292`

| Gate | Result |
|---|---|
| file inventory | 28 files under `backend/apps` (1 + 9×3) ✅ · 9 app dirs ✅ |
| unexpected modules (models/views/admin/tests/urls/serializers) | none ✅ |
| all `__init__.py` empty | 0 non-empty ✅ |
| AppConfig dotted names | all nine resolve as `apps.<name>` with `BigAutoField` ✅ |
| canonical list | accounts, applications, audit, billing, clients, coaching, commerce, notifications, workspaces — no extras, no omissions; `coaching` unsplit, `audit` present ✅ |
| scope | nothing outside `backend/apps/` touched ✅ |
| post-merge `manage.py check` dev/prod | `System check identified no issues (0 silenced).` (both) ✅ |
| T4 config survived merge · LOCAL_APPS still empty | ✅ |

Worktree `t2-apps` merged with `--no-ff`, then worktree and branch removed. Main tree clean.

#### T2 dispatch failures — three attempts, no code involved in the first two

| Attempt | Worker | Outcome |
|---|---|---|
| 1 | AGY | `failed`, exit 1, **0 files touched**. Headless mode hit a tool-permission prompt it cannot answer and auto-denied itself. Fix needs `--dangerously-skip-permissions` (security escalation) or an allow-rule in the user's global `settings.json` — neither taken unilaterally. |
| 2 | OpenCode (no model) | Refused to start: "no model given — opencode has no safe default". 0 files touched. |
| 3 | OpenCode `zai-coding-plan/glm-5.2` | ✅ Succeeded. Model chosen from the user's own configured providers; "OpenCode / **GLM**" is the approved worker name. |

Worktree verified pristine before every re-dispatch, so no worker entered a dirty tree (Rule 12).

**AGY — USER DECISION (2026-08-14):** do **not** use `--dangerously-skip-permissions`, do **not**
modify `~/.claude/settings.json`. AGY stays temporarily unavailable for headless delegation.
**T8 reassigned from AGY → OpenCode/GLM.** No rework required for the failed T2 dispatch attempts:
the final result passed review and every worktree was verified pristine beforehand.

#### T3 review record (Master-executed) — commit `2bc78e3`

| Gate | Result |
|---|---|
| diff scope | exactly one file, `backend/config/settings/base.py`; only the `LOCAL_APPS` list changed ✅ |
| `manage.py check` default / dev / prod | `System check identified no issues (0 silenced).` (all three) |
| all nine apps load | ✅ every AppConfig resolves with `name == "apps.<label>"` |
| registered app count | 16 = 6 django + 1 drf + 9 local ✅ |
| migrations created | none ✅ (correct — no models exist yet) |
| other sections untouched | `DATABASES = {}` intact; SESSION_COOKIE / EMAIL_ / MEDIA_ROOT / STATIC_ROOT all still absent ✅ |

Canonical order preserved: accounts, workspaces, coaching, clients, applications, commerce, billing,
notifications, audit. `coaching` unsplit, `audit` present.

#### T5 review record (Master-executed) — commit `ac106f1`

Security-critical task. All eight required verifications run by Master:

| # | Check | Result |
|---|---|---|
| 1 | Exact diff scope | 3 files; `base.py` diff is **only** the SESSIONS & SECURITY section ✅ |
| 2 | `manage.py check` default / dev / prod | `System check identified no issues (0 silenced).` ×3 |
| 3 | Session auth is the only mechanism | `DRF auth = ['SessionAuthentication']` ✅ |
| 4 | Cookie/security settings vs DB §5, §29 | see matrix below ✅ |
| 5 | No custom session model | no `UserSession` class, no `token_hash` field, 0 models, 0 migrations ✅ |
| 6 | No token/JWT | `jwt`, `authtoken`, `TokenAuthentication`, `simplejwt`, `oauth` all absent. Sole `Token` hit is `X-CSRFToken` in a comment ✅ |
| 7 | No hardcoded secrets | none; only T1's pre-existing dev-only `django-insecure-` fallback ✅ |
| 8 | No unrelated settings modified | REST_FRAMEWORK, DATABASE, EMAIL, STATIC banners all untouched ✅ |

Cookie matrix as verified at runtime:

| Setting | dev | prod |
|---|---|---|
| `SESSION_ENGINE` | `django.contrib.sessions.backends.db` | same |
| `SESSION_COOKIE_HTTPONLY` | `True` (hardcoded) | `True` |
| `SESSION_COOKIE_SECURE` | `False` | **`True` — hardcoded, not env-overridable** |
| `CSRF_COOKIE_SECURE` | `False` | **`True` — hardcoded, not env-overridable** |
| `SESSION_COOKIE_SAMESITE` / `CSRF_COOKIE_SAMESITE` | `Lax` | `Lax` |
| `CSRF_COOKIE_HTTPONLY` | `False` (required — frontend reads csrftoken) | `False` |
| `CSRF_TRUSTED_ORIGINS` | from env | from env |

**Downgrade test:** prod was loaded with `SESSION_COOKIE_SECURE=False CSRF_COOKIE_SECURE=False` in
the environment and still reported `True` for both. A misconfigured deployment cannot silently
serve insecure cookies.

**Master scope decisions (surfaced, not absorbed):** three items named in DB §5 were deliberately
excluded from T5 as belonging to other Stories — authentication **rate limiting** (Epic 20), the
**logout endpoint** (Epic 02; T5 is settings-only), and **SSL redirect / HSTS / security headers**
(Nginx, Blueprint Story 21.2). `SESSION_COOKIE_AGE` was **not** set because no approved document
specifies a session lifetime.

#### T6 review record (Master-executed) — commit `842440f`

**PostgreSQL availability confirmed BEFORE implementation** (client-vs-server distinction respected):

| Probe | Result |
|---|---|
| TCP 5432 listener | `postgres` PID 3454 on `127.0.0.1:5432` and `[::1]:5432` ✅ |
| Server processes | walwriter, background writer, autovacuum, logical replication launcher ✅ |
| Unix socket | `/tmp/.s.PGSQL.5432` ✅ |
| Service | `postgresql@16 started` (brew) ✅ |
| Live query | `PostgreSQL 16.13 (Homebrew) on aarch64-apple-darwin25.2.0` ✅ |

| Gate | Result |
|---|---|
| diff scope | one file; only the DATABASE section (14 changed lines) ✅ |
| `check` default / dev / prod | `System check identified no issues (0 silenced).` ×3 |
| engine | `django.db.backends.postgresql`, exactly the six keys, no extras ✅ |
| PASSWORD default | empty string, no hardcoded credential ✅ |
| **REAL connection (Master-run)** | `SERVER: PostgreSQL 16.13 …` · `CONNECTED AS: ('postgres','momen')` · round-trip `SELECT 1+1 → 2` · `vendor=postgresql driver=psycopg` ✅ |
| models / migrations / `migrate` | 0 / 0 / not run ✅ |
| SQLite fallback | absent ✅ |
| new db libs (dj-database-url, psycopg2, django-environ) | absent ✅ |
| infrastructure/Docker touched | none ✅ |
| other sections intact | SESSION_ENGINE, CSRF_COOKIE_HTTPONLY, REST_FRAMEWORK, LOCAL_APPS all present ✅ |

**Story 1.2 AC #2 "Database connection works" is now EMPIRICALLY VERIFIED by Master**, not accepted
on a worker's report.

**Scope boundary honoured:** the `fitops` database and `fitops` role do **not** exist on this
machine — re-confirmed as absent after the task ran. Creating the development database is Blueprint
**Story 1.4** ("Configure development database"). The live-connection proof therefore used an env
override against the existing `postgres` database as role `momen`, creating nothing.

**Carry-forward for Story 1.4:** it must create role `fitops` and database `fitops` (or the `.env`
must be pointed at an existing database) before `migrate` can run. Existing databases: `couch`,
`erp`, `postgres`. Existing roles: `momen`, `erp`.

#### T7 review record (Master-executed) — commit `8182cab`

| # | Check | Result |
|---|---|---|
| 1 | Exact diff scope | 2 files; `base.py` EMAIL section + one line in `dev.py` ✅ |
| 2 | `check` default / dev / prod | `System check identified no issues (0 silenced).` ×3 |
| 3 | Django SMTP backend | base = `django.core.mail.backends.smtp.EmailBackend` ✅ |
| 4 | Env-driven host/port/user/password/TLS/from | injected `smtp.example.invalid:2525`, TLS False, custom from-address — all honoured end to end ✅ |
| 5 | No hardcoded credentials | every value via `env()` with empty default; **no email address literal anywhere in backend/*.py** ✅ |
| 6 | No provider-specific implementation | sendgrid, mailgun, postmark, amazonses, ses, gmail, resend, brevo, mailtrap, anymail, sparkpost, mandrill — all absent; `requirements.txt` unchanged (Django, DRF, psycopg only) ✅ |
| 7 | No unrelated settings changed | `prod.py` untouched; DATABASES, SESSION_ENGINE, CSRF_COOKIE_HTTPONLY, REST_FRAMEWORK, LOCAL_APPS, STATIC_URL all intact ✅ |
| 8 | No email business logic | `send_mail`, `EmailMessage`, `EmailMultiAlternatives`, `get_connection`, `shared_task` all absent; 0 files under `backend/apps` changed; no templates dir ✅ |

Resolved during review: the two `mail.` grep hits are Django's own dotted backend paths
(`django.core.mail.backends.{smtp,console}.EmailBackend`) — legitimate, not provider code.

| Setting | dev | base/prod |
|---|---|---|
| `EMAIL_BACKEND` | console (built-in, no dependency) | `smtp.EmailBackend` |
| `EMAIL_HOST` / `EMAIL_HOST_USER` / `EMAIL_HOST_PASSWORD` | `''` | from env, `''` default |
| `EMAIL_PORT` | `587` (int) | from env, int-coerced |
| `EMAIL_USE_TLS` | `True` | from env, default True |
| `DEFAULT_FROM_EMAIL` | `''` | from env, `''` default |

**MISSING_DECISIONS.md unchanged — the SMTP provider remains deliberately unresolved.** T7 built
only the plumbing so the decision can later be answered by environment variables alone. No delivery
test was attempted, by design; the probe used the unresolvable TLD `.invalid` so nothing could
reach a real host.

#### Worker environment limitation#### Worker environment limitation#### Worker environment limitation (important for future delegations)

**Codex's sandbox had no outbound network access to PyPI.** It therefore could not install
dependencies or run `manage.py check`, and pinned `requirements.txt` to current stable PyPI versions
without local verification. Codex disclosed this honestly in its DEVIATIONS section rather than
faking a green gate.

Master resolved it: created `.venv`, installed the pinned versions — **they installed cleanly on
Python 3.14.6** — and ran every gate. The pins are now empirically verified.

**Carry forward:** any future worker task that needs package installation must either be run by
Master, or the worker must be given a pre-populated environment. Do not assume workers have network.

#### Scope violation found and corrected

Codex created **`AGENTS.md`** — an unrequested file outside its allowed list, containing a copy of
`CLAUDE.md` with content silently altered (e.g. "Stitch/Claude workflow" → "Stitch/Codex workflow").
Master **deleted it before committing**. It was never committed and is not in history.

Rationale for deletion rather than keeping: it duplicates the project's single index document and
would drift from it, and altering `CLAUDE.md` content is outside any worker's authority. See
*Known Issues / Risks* — the user may still choose to add a short pointer-style `AGENTS.md` later.

### Last completed step### Last completed step

"T7 accepted by user as COMPLETE. T8 dispatched to OpenCode/GLM (reassigned from AGY) under the settings lock."

### Next step

"Review T8 (10 checks); if PASS, land it and STOP — T9 requires explicit user approval."

---

## Next

| Field | Value |
|---|---|
| **Epic** | Epic 01 — Project Foundation |
| **Story ID** | Story 1.2 |
| **Story title** | Django Backend Setup |

**Why it is next:** Blueprint §6 lists 1.2 immediately after 1.1 within Epic 01, and §29 fixes
Foundation as the first block. Story 1.1 (its only prerequisite) is complete.

**Dependencies:** Story 1.1 — complete.

**Scope (Blueprint §6, quoted tasks):** initialize the Django project · configure Django REST
Framework · create the approved apps · configure the settings structure · configure environment
variables · configure PostgreSQL · configure static/media handling · configure Django's session
framework · configure Django's email backend with SMTP settings sourced from environment variables.

**Approved apps for 1.2:** `accounts`, `workspaces`, `coaching`, `clients`, `applications`,
`commerce`, `billing`, `notifications`, `audit`.

**Prerequisite checks before starting:**

1. User approval to start Story 1.2 (do not start automatically).
2. Python and PostgreSQL availability confirmed — **Unknown / not verified** in this environment.
3. Re-read Blueprint §6 Story 1.2, Technology Stack (sessions, email), Database & Auth Architecture
   §5 (Django session framework) and ERD §15–§23 (app boundaries).
4. ~~Note the ERD §24 discrepancy~~ — resolved 2026-08-14. §24, §15 and Story 1.2 now agree on the
   canonical nine apps.

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
