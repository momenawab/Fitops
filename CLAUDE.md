# FitOps — Project Instructions

> **This file is an implementation guide and index. It does NOT replace the documentation.**
> If anything here conflicts with the source documents, **the source documents are authoritative**.
> Nothing in this file may be treated as a new requirement, a new model field, or a new endpoint.

**Current documentation baseline: Architecture v1.2.1 (approved and locked).**

v1.2 added the **FitOps Billing** domain (§24) on top of the unchanged v1.1 baseline.
v1.2.1 adds the expiration retention / archive / restoration lifecycle and the explicit
Coach-commerce `Payment.status` enum.

---

## 0. Source of Truth

All documentation lives under `docs/`.

| # | Document | Path | Covers |
|---|---|---|---|
| 1 | MVP Specification v1.2.1 | `docs/01-product/fitops_mvp_spec_v1.md` | Product, users, flows, MVP scope, FitOps billing scope, out-of-scope |
| 2 | Technology Stack v1.2.1 | `docs/02-architecture/fitops_technology_stack_v1.md` | Stack, infrastructure, Platform Admin panel, auth + email decisions |
| 3 | Database & Authentication Architecture v1.2.1 | `docs/02-architecture/fitops_database_auth_architecture_v1.md` | Models, fields, auth model, tenancy security, **billing domain §22–§22G** |
| 4 | API Specification v1.2.1 | `docs/02-architecture/fitops_api_specification_v1.md` | Endpoints, permissions, errors, security rules, **billing API §20A** |
| 5 | ERD / Django Apps / Repository Architecture v1.2.1 | `docs/02-architecture/fitops_erd_django_repository_architecture_v1.md` | ERD, Django app split, repo + frontend structure |
| 6 | Development Blueprint v1.2.1 | `docs/03-development/fitops_development_blueprint_v1.md` | Approved decision log, Epics 01–22, Stories, order, testing, DoD, agent rules |
| 7 | Design System v1.2.1 | `docs/04-design/design.md` | Visual direction, tokens, components, billing UI, Stitch/Claude workflow |
| — | **Missing Decisions Registry** | `docs/MISSING_DECISIONS.md` | Decisions deliberately left unresolved — **stop and ask, never guess** |
| — | **Implementation Progress** | `PROGRESS.md` | Mandatory implementation handoff: what is done, in progress, and next |

**Blueprint §38 status:** MVP Scope, Technology Stack, Database/Auth Architecture, ERD/Repository Architecture, API Specification, and Development Blueprint are all **LOCKED**. Design System §38: Visual Direction **LOCKED**.

**Canonical decision log:** Development Blueprint **§2A** (v1.1 decisions 1–18) and **§2B** (v1.2 billing decisions 19–37, plus v1.2.1 decisions 38–43).

**Rule:** Read the relevant approved document(s) before modifying code (Blueprint §34 Rule 1). If implementation detail conflicts with these documents, **stop and resolve the conflict before coding** (Blueprint §2).

**Unresolved-decision rule:** `docs/MISSING_DECISIONS.md` is the central registry of decisions that are intentionally not made. **If an implementation encounters a decision listed in MISSING_DECISIONS.md, stop and ask for an explicit decision rather than guessing.**

**Handoff rule — read before coding:** `PROGRESS.md` (repository root) is the mandatory implementation handoff file. Any agent starting work on FitOps reads **`CLAUDE.md` → `PROGRESS.md` → `docs/MISSING_DECISIONS.md`**, then the authoritative documents for the current Story. **Do not start coding before understanding `PROGRESS.md` and the current Story.** Source-of-truth priority: approved documentation → `docs/MISSING_DECISIONS.md` → `PROGRESS.md` → code. `PROGRESS.md` records implementation state only and never overrides an approved decision; if it conflicts with the authoritative documentation, stop and report the conflict.

---

## 1. Product Overview & Positioning

FitOps is a **coaching management SaaS for coaches who already have a website**. The coach keeps their site and adds a "Start Coaching" / "Client Login" link pointing at our platform. FitOps owns everything after that click:

> **Application → Payment → Client → Plans → Check-ins → Progress**

Three separate experiences (Stack doc, "Application Structure"):

| Experience | Owner | Scope |
|---|---|---|
| Platform Admin Panel | SaaS owner | All coaches, all workspaces, SaaS billing, platform data |
| Coach Dashboard | Coach | Own workspace, own clients, orders, check-ins |
| Client Portal | Client | Own account, own plans, own progress |

**Users:** Coach (workspace owner), Client (coach's customer), Platform Admin (SaaS owner). Platform Admin does not need a large admin system in Phase 1 (MVP §2).

**Naming:** the product is **FitOps**. Earlier drafts used the working title "Coaching SaaS"; treat them as the same product.

---

## 2. MVP Scope & Explicit Non-Goals

### The MVP core loop (MVP §21, API §27, Blueprint §3)

```
Coach signs up → creates workspace → creates package → gets portal link
  → Client applies (application + initial order created together) → OTP login
  → uploads payment proof → Coach approves → subscription created → Client activated
  → Coach assigns training/nutrition plan → Client views plan
  → Client submits check-in + photos → Coach reviews + sends feedback → Client tracks progress
```

The MVP is successful when this flow works end-to-end in production-like conditions.

### Explicitly OUT of Phase 1 (MVP §20, Blueprint §4.5)

Website Builder · Custom Domains · Merch · Supplements · Inventory · AI · WhatsApp API · Mobile App · Automated Payment Gateways · Team Accounts · Advanced Analytics · Marketing Automation · Affiliate System · Marketplace · Complex/automated SaaS billing.

Also deferred by the specs:
- **Webhooks** — not required; reserve `/api/v1/webhooks/...` only (API §24).
- **JWT** — not required for Phase 1.
- **Custom `UserSession` / `token_hash` system** — not implemented; Django sessions only.
- **Per-session management** — no `GET /auth/sessions`, no `POST /auth/sessions/{id}/revoke`. `POST /auth/logout` only; "log out everywhere" is a future feature.
- **Separate Payments module** — payments live inside Orders and their payment states. A "Payments" nav item is a filtered Orders view, never a separate backend domain.
- **SMS 2FA** — not required; TOTP only.
- **Client passwords / client 2FA** — not in Phase 1.
- **Automated renewal** — Phase 1 renewal is manual, for both Client coaching subscriptions and FitOps billing.
- **FitOps billing extras** — no refunds, no proration, no mid-cycle plan changes, no annual billing, no immediate cancellation.
- **Complex check-in scheduling** (per-client schedules, custom cadences) — Weekly/Biweekly + day of week only.
- **S3 / object storage** — Hetzner storage in Phase 1, behind a storage abstraction.

---

## 3. Technology Stack (LOCKED)

| Layer | Technology |
|---|---|
| Frontend | Next.js + TypeScript |
| UI | Tailwind CSS + shadcn/ui |
| Forms | React Hook Form + Zod |
| Server state | TanStack Query |
| Backend | Django + Django REST Framework |
| Sessions | Django built-in session framework |
| Email | Django email backend abstraction + SMTP, configured via environment variables |
| Database | PostgreSQL |
| Background jobs | Celery + Redis |
| Image processing | Pillow → WebP + resize/compress |
| File storage | Hetzner Volume / local storage (via storage abstraction) |
| Reverse proxy | Nginx |
| CDN / DNS / SSL | Cloudflare |
| Containers | Docker + Docker Compose |
| CI/CD | GitHub Actions |
| Deployment | Hetzner VPS |

**Email:** send through Django's email API only — never a provider-specific SDK. SMTP host, port, credentials, TLS settings and from-address come from environment variables. The specific SMTP provider is deployment configuration and is not yet selected; it does not block any Story.

**Image pipeline defaults** (adjustable during implementation): max upload 10 MB, max processed width 1600 px, thumbnail width 400 px, WebP quality ~80–85.

**Docker services:** `frontend`, `backend`, `postgres`, `redis`, `celery`, `nginx`.

---

## 4. Repository Architecture (Monorepo)

```
fitops/                   # repo root (this working directory is /Users/momen/Fitops)
├── frontend/             # Next.js
├── backend/
│   ├── config/
│   ├── apps/{accounts,workspaces,coaching,clients,applications,commerce,billing,notifications,audit}/
│   ├── common/
│   ├── tests/
│   └── manage.py
├── infrastructure/{docker,nginx,scripts,backups}/
├── docs/
│   ├── 01-product/
│   ├── 02-architecture/
│   ├── 03-development/
│   └── 04-design/
├── docker-compose.yml
├── .env.example
├── .gitignore
└── README.md
```

### Frontend structure (ERD §25)

```
frontend/
├── app/
│   ├── (marketing)/
│   ├── auth/                  # coach register / login / password reset (no workspace yet)
│   ├── onboarding/            # create first workspace
│   ├── admin/                 # platform admin (never workspace-scoped)
│   └── [workspaceSlug]/
│       ├── page.tsx           # public coach portal
│       ├── login/             # client OTP login
│       ├── apply/             # public application
│       ├── portal/            # client portal
│       ├── dashboard/         # coach dashboard
│       ├── clients/  orders/  check-ins/  plans/  settings/  billing/
├── components/  features/  lib/  hooks/  types/
```

---

## 5. Django App Structure (ERD §15–23)

Apps are split by **business domain**, not one app per model.

| App | Models / responsibility |
|---|---|
| `accounts` | `User`, `CoachProfile`, `ClientProfile`, `CoachSecurity`, `Membership`, `LoginOTP` — registration, login/logout, email verification, password reset, client OTP, 2FA, roles, memberships. Sessions come from Django's framework, not a model here |
| `workspaces` | `Workspace`, `WorkspaceArchive`, `PaymentMethod`, `CheckInSchedule` — workspace creation (+ OWNER membership), settings, branding, public portal config, payment methods, check-in schedule, retention cleanup/archive/restore |
| `coaching` | `Package`, `TrainingPlan`, `TrainingWeek`, `TrainingDay`, `Exercise`, `NutritionPlan`, `NutritionMeal`, `PlanAssignment`, `CheckIn`, `ProgressPhoto`, `CoachFeedback` |
| `clients` | Client-facing business operations: client portal, client dashboard, client activity, client-specific access. **`ClientProfile` stays in `accounts`** (it is identity) |
| `applications` | `Application` — public applications, application lifecycle and status, Application → initial Order flow, Application → Client conversion. Does **not** own `Order` |
| `commerce` | `Order`, `Payment`, `Subscription` — Client → Coach commerce only: orders, payment proofs, manual payments, approval, client subscriptions, renewals |
| `billing` | `Plan`, `PlatformPaymentInstruction`, `PlatformSubscription`, `BillingPayment`, `BillingEvent` — Coach → FitOps subscription billing. See §24 |
| `notifications` | `Notification` (in-app; required emails in Phase 1) |
| `audit` | `AuditLog` — admin actions, sensitive coach actions, security events, commercial state changes |
| `common` | Shared infrastructure, **not** business models: `models/ permissions/ exceptions/ pagination/ storage/ utils/ middleware/` — including `WorkspaceScopedModel`, `WorkspacePermission`, `TenantQuerySet`, `WorkspaceMiddleware`/context, Membership resolution |

---

## 6. Database Architecture

Single shared PostgreSQL database, **shared schema**, `workspace_id`-based tenant isolation (DB §30).

Full field lists are in DB Architecture §2–§23 and ERD §1–§14 — **read them before writing models; do not add fields from memory.**

### Identity & auth models (global, no `workspace_id`)
`User` (email unique, `platform_role` ∈ {NONE, ADMIN}) · `CoachProfile` · `ClientProfile` · `CoachSecurity` · `LoginOTP`
Sessions are Django's database-backed sessions — **no `UserSession` model**.

### Tenant models
`Workspace` (unique `slug`, status ∈ {ACTIVE, SUSPENDED}) · `Membership` (role ∈ {OWNER, COACH, CLIENT}, `joined_at`, `UNIQUE(user_id, workspace_id)`)

### Workspace-scoped business models — each carries an explicit `workspace_id` (ERD §28)
`Package` · `Application` · `PaymentMethod` · `CheckInSchedule` · `Order` · `Payment` · `Subscription` · `TrainingPlan` (→ `TrainingWeek` → `TrainingDay` → `Exercise`) · `NutritionPlan` (→ `NutritionMeal`) · `PlanAssignment` · `CheckIn` · `ProgressPhoto` · `CoachFeedback` · `Notification`

Keep `workspace_id` explicit **even when it could be inferred through a relation** — for explicit scoping, simpler queries, stronger security, easier indexing and auditing.

`PlatformSubscription` is workspace-linked but is the SaaS-side subscription; `AuditLog` carries `user_id` + `workspace_id`.

### Tenant-scoped identity references (DB §10, ERD §4)
- `client_id` on a Workspace-scoped record → FK to **`Membership`** (`role = CLIENT`).
- `coach_id` (e.g. `CoachFeedback`) → FK to **`Membership`** (`role` ∈ {OWNER, COACH}).
- `Membership.workspace_id` must match the record's `workspace_id`.
- Global identity data is read through `Membership → User → ClientProfile`, never duplicated onto workspace-scoped records.
- **Exception:** `Application.user_id` is a **nullable** FK to the global `User`, because an application can precede any Membership.

### Key enums (authoritative: DB Architecture)
- `Order.status`: `PENDING_PAYMENT`, `PAYMENT_SUBMITTED`, `APPROVED`, `REJECTED`, `CANCELLED`
- `Payment.status` *(Coach Commerce)*: `PENDING`, `SUBMITTED`, `APPROVED`, `REJECTED`, `CANCELLED` — never merged with the FitOps `BillingPayment` enum
- `Payment.method`: `MANUAL_BANK`, `INSTAPAY`, `VODAFONE_CASH`, `OTHER`
- `PaymentMethod.type`: `INSTAPAY`, `VODAFONE_CASH`, `BANK_TRANSFER`, `CUSTOM`
- `CheckInSchedule.frequency`: `WEEKLY`, `BIWEEKLY` (+ `day_of_week`)
- `Subscription.status`: `ACTIVE`, `EXPIRING`, `EXPIRED`, `CANCELLED`
- `CheckIn.status`: `DRAFT`, `SUBMITTED`, `REVIEWED`
- `ProgressPhoto.photo_type`: `FRONT`, `SIDE`, `BACK`, `OTHER`
- `Application.status`: `SUBMITTED` → `REVIEWING` → `APPROVED`/`REJECTED`

### Storage
PostgreSQL stores **metadata only**. Uploaded media (progress photos, payment proofs, payment-method QR images, coach images, workspace logos) lives in Hetzner media storage, processed by Pillow before storage. Never expose raw storage paths.

---

## 7. Global User Architecture

> **User is global. Workspace is the tenant. Membership connects Users to Workspaces.** (ERD §1)

- One central `User` model — **no** separate CoachUser / ClientUser / AdminUser.
- `platform_role` on `User` is `NONE` or `ADMIN`. Coach/Client roles are **not** on `User`; they come from `Membership`.
- Coach public/personal info lives on `CoachProfile`; workspace branding lives on `Workspace` — so a Coach can operate more than one Workspace in future.
- A single `User` may be OWNER in one Workspace, COACH in another and CLIENT in a third.

---

## 8. ClientProfile Architecture

- `ClientProfile` is **global identity** and **MUST NOT contain `workspace_id`** (DB §10, ERD §4, Blueprint Story 2.3).
- The Client↔Workspace relationship is expressed **only** through `Membership(role=CLIENT)`.
- A Client may belong to multiple Workspaces while keeping one identity.
- The Client Portal **never** exposes the Client's other memberships, and Clients never receive or select a list of memberships (API §1, §28).
- Workspace-scoped records point at the Client's `Membership`, not at `ClientProfile` (§6 above).

---

## 9. Membership & Multi-Workspace Model

```
Membership: id, user_id, workspace_id, role, status, joined_at, created_at, updated_at
Roles: OWNER | COACH | CLIENT        Future: ASSISTANT_COACH (do not implement now)
Constraint: UNIQUE(user_id, workspace_id)
```

- `POST /api/v1/workspace` creates the first Workspace **and** the creator's `OWNER` Membership in one transaction.
- The public application flow creates or reuses `User`, `ClientProfile` and `Membership(role=CLIENT)`, then creates the initial `Order` — a global Client User may already exist because of another Workspace (ERD §6, Blueprint Story 7.3).
- Membership is also the tenant-scoped identity used by workspace business records.

---

## 10. Workspace Isolation Rules (non-negotiable)

1. Every Workspace business operation respects tenant isolation.
2. **Never trust a `workspace_id` supplied by the frontend.** Ever.
3. Resolve the active Workspace from the URL slug server-side, then verify the authenticated User's Membership (and role) before granting access.
4. Tenant-scoped lookups must return **no result** for unauthorized objects — never reveal that an object exists (DB §26).
5. Client access requires **two** checks (DB §27, API §28): (a) active Membership in the requested Workspace, (b) the resource belongs to that Client **and** that Workspace.
6. A Client authenticated for Workspace A must not reach Workspace B resources **even when the same User has a valid Membership in B**.
7. Coach APIs must never expose platform-wide administrative access.

Required request pipeline (ERD §27):

```
Request → Authentication → User → Workspace Context (slug) → Membership Check
        → Tenant Query → Object Ownership → Response
```

---

## 11. URL-Based Workspace Context

The **Workspace slug in the URL is the authoritative Workspace context** for every workspace-scoped area:

```
/{workspaceSlug}                 public coach portal
/{workspaceSlug}/apply           public application
/{workspaceSlug}/login           client OTP login
/{workspaceSlug}/portal          client portal
/{workspaceSlug}/dashboard       coach dashboard
/{workspaceSlug}/clients | /orders | /check-ins | /plans | /settings
```

- The backend resolves slug → Workspace → Membership → context, and checks the role is appropriate to the requested area.
- The frontend never provides or chooses the authoritative `workspace_id`.
- Client OTP request/verify include `workspace_slug` (API §5).
- **Not** slug-scoped: coach auth routes, first-workspace onboarding, and the Platform Admin panel.
- `GET /auth/me` deliberately does **not** return a single global "current Workspace" (API §4).

---

## 12. Authentication Strategy (LOCKED)

- **Django's built-in session framework**, database-backed store, with secure HttpOnly session cookies. Secure flag in production, appropriate SameSite, CSRF protection on state-changing requests, secure logout, authentication rate limiting.
- **No custom `UserSession` / `token_hash` model.** Do not introduce one.
- **No per-session management in the MVP.** `POST /auth/logout` terminates the current session; session listing and per-session revocation are out of scope.
- **JWT is not required for Phase 1.**
- Sessions are shared at the **User identity** level; the active Workspace is resolved separately from the URL slug.

### Coach authentication
Email + password → email verification → optional TOTP 2FA → session.
Requirements: password hashing, email verification, secure password reset (no account enumeration), TOTP 2FA (authenticator apps; **no SMS**), secure sessions, secure logout, login rate limiting. TOTP state lives on `CoachSecurity`.

### Client OTP authentication
Email → one-time code → session. No password, no 2FA in Phase 1.

```
Generate OTP → hash → store hash → email the real code
→ client enters code → hash input → compare hashes
```

Requirements: **never store the OTP in plaintext**, ~10-minute expiry, one-time use, max verification attempts, rate limiting (strict — controls email cost/abuse), invalidate the previous active OTP when a new one is generated, secure session creation. Clients must not need a new OTP on every visit while their session is valid.

### Platform Admin permissions
- Represented **only** by `User.platform_role = ADMIN`. It is **not** a Workspace membership.
- Operates globally; admin endpoints live under `/admin/...` and are completely separated from tenant APIs.
- Stricter access controls than Coach accounts: separate admin permission layer, admin-only routes, audit logging of sensitive actions.
- **Never expose platform-wide data through Coach APIs.**

---

## 13. API Implementation Rules

REST, versioned under `/api/v1/`. JSON; `multipart/form-data` for uploads; ISO 8601 timestamps; **UUIDs for public resource identifiers**; monetary values as decimal strings.

**Standard error envelope** (API §2):

```json
{ "error": { "code": "VALIDATION_ERROR", "message": "…", "fields": { "email": ["…"] } } }
```

Use only the documented codes (`AUTHENTICATION_REQUIRED`, `INVALID_CREDENTIALS`, `INVALID_OTP`, `OTP_EXPIRED`, `OTP_RATE_LIMITED`, `EMAIL_NOT_VERIFIED`, `TWO_FACTOR_REQUIRED`, `INVALID_TWO_FACTOR_CODE`, `PERMISSION_DENIED`, `NOT_FOUND`, `VALIDATION_ERROR`, `CONFLICT`, `RATE_LIMITED`, `FILE_TOO_LARGE`, `UNSUPPORTED_FILE_TYPE`, `INTERNAL_ERROR`).

**Pagination:** `?page=1&page_size=20` → `{count, next, previous, results}`.

**The 17 API security rules (API §25) are mandatory** — never trust client `workspace_id`; resolve tenant server-side from the URL slug on every workspace-scoped route including coach routes; scope all workspace resources; scope through the caller's `Membership` and verify it matches the resolved Workspace; scope Client requests to the authenticated Client; never expose another Client's data; never expose payment proof without authorization; HttpOnly cookies; rate-limit auth endpoints; hash OTPs and sensitive tokens; log sensitive admin actions; use transactions for order approval + subscription creation; validate ownership before every mutation; UUIDs externally; no raw storage paths; consistent errors.

**Backend owns business rules** (Blueprint §4.3). The frontend is never trusted for prices, workspace ownership, client ownership, subscription state, order state, payment approval, permissions, or activation state.

**Transactional flows:**
- `POST /api/v1/workspace` — reserve slug → create Workspace → create OWNER Membership → audit event.
- `POST /public/coaches/{slug}/applications` — create Application → create/resolve User + ClientProfile → create Membership → associate `Application.user_id` → create **initial Order**. All-or-nothing.
- `POST /orders/{id}/approve` — validate order/payment → approve payment → approve order → create Subscription → activate Client → notifications → audit event.

**`POST /orders`** is only for **subsequent** purchases by an authenticated Client.

**Idempotency required** (API §23) for: order approval, payment submission, subscription creation, subscription renewal, client activation. Double-clicking *Approve* must not create two subscriptions.

**Rate limiting mandatory** (API §22) for: login, password reset, email verification, client OTP request, client OTP verify, file uploads, public application endpoints, sensitive admin actions.

**Files** (API §21): validate MIME + size, process with Pillow, convert to WebP where appropriate, generate thumbnails, store on Hetzner, metadata in PostgreSQL, serve only through authenticated permission-checked endpoints.

**API module map:** `auth` (coach auth, 2FA, password reset, client OTP, logout), `workspace` (create, settings, branding, payment methods, check-in schedule), `public` (coaches, applications), `dashboard`, `packages`, `clients`, `orders`, `payments` *(order-scoped endpoints only — not a separate domain)*, `subscriptions`, `training-plans`, `nutrition-plans`, `plan-assignments`, `check-ins`, `progress`, `notifications`, `admin`. Endpoint-by-endpoint contracts are in API Spec §4–§20 — **implement exactly those; invent nothing.**

---

## 14. Frontend Architecture

- Next.js + TypeScript, organized around product experiences (see §4). Workspace-scoped areas live under `app/[workspaceSlug]/`.
- **TanStack Query** for all server state: requests, caching, mutations, loading/error states, invalidation.
- **React Hook Form + Zod** for every form and client-side validation; Zod schemas mirror API contracts but never become the authority on business rules.
- shadcn/ui + Tailwind for components; the UI must stay custom-branded and must not look like a generic SaaS template.
- Client portal is **mobile-first and app-like**.
- Auth is cookie-based — no token storage in JS-accessible storage; send the CSRF token on state-changing requests.

---

## 15. Design System Rules

`docs/04-design/design.md` is the visual/UX source of truth for marketing site, coach dashboard, client portal, and platform admin. Read it before writing any UI.

### Clean Light visual direction (default theme, LOCKED)

```
Background #F8F9FA   Surface #FFFFFF   Surface Muted #F1F3F5
Text Primary #111827   Text Secondary #4B5563   Text Muted #6B7280
Border #E5E7EB   Border Strong #D1D5DB
Default accent: Primary #2563EB   Hover #1D4ED8   Soft #EFF6FF
```

Semantic colors are **stable and never replaced by coach branding**: Success `#16A34A`/`#F0FDF4`, Warning `#D97706`/`#FFFBEB`, Error `#DC2626`/`#FEF2F2`, Info `#2563EB`/`#EFF6FF`. Use them only for meaning, never decoration.

Feel: clean, premium, modern, trustworthy, professional, SaaS-first. Avoid: overly colorful dashboards, heavy gradients, excessive glassmorphism, neon/gaming aesthetics, excessive shadows, excessive rounding, dense enterprise UI, generic templates.

Foundations: **Inter**; 4px spacing scale; radius 8px controls/inputs, 12px cards, 16px large surfaces/modals; 1px `#E5E7EB` borders; subtle shadows only (`0 1px 2px rgba(0,0,0,.05)`, `0 8px 24px rgba(0,0,0,.08)`); **Lucide** icons only; skeleton loading; useful empty states; human-readable error states; toast/inline success. Accessibility minimums: WCAG-aware contrast, keyboard navigation, visible focus, real labels, semantic HTML, alt text, never color alone for status.

### Coach theme system

Two layers: **FitOps Foundation + Coach Brand Theme**. Coach branding changes only accent tokens:

```
--brand-primary  --brand-primary-hover  --brand-primary-soft
--brand-on-primary  --brand-border  --brand-text
```

Presets: Blue, Purple, Orange, Red, Gold, Cyan, Lime (exact hexes in design.md §6). Rules: keep background/text foundations stable; do not recolor every component; use brand for CTA, active nav, links, highlights, selected states, progress emphasis; semantics stay semantic; maintain contrast; marketing may use brand more prominently than dashboards.

**Theme customization must be token-based** — `Component → Design Token → Coach Theme`. Never create per-coach component implementations (`BergoButton`, `Coach2Button` is wrong).

**Platform Admin does not inherit coach themes** — always Clean Light + FitOps Blue.

### Google Stitch / Claude workflow (design.md §36–37)

```
design.md + current screen prompt → Stitch generates → review → refine → approve
```

- Work in **batches of three screens**; do not dump all future UI prompts at once.
- Approved Stitch screens become implementation references.
- Claude implements from: `design.md` + approved Stitch design + architecture documents + development blueprint.
- Reproduce the approved design faithfully while keeping responsive behavior, accessibility, reusable components, theme tokens, and existing architecture.
- **Do not redesign an approved screen during implementation unless explicitly requested.**
- Next design artifact per design.md §38: *Marketing Screens 01–03*.

---

## 16. Development Workflow

**Core rule (Blueprint §1):** implement **one Story at a time**, test it, verify it against the approved architecture/API contract, then move on.

Per-Story cycle: `Plan → Implement → Test → Review → Update PROGRESS.md → Commit → Next Story`.

**Updating `PROGRESS.md` is part of completing a Story.** A Story is not handed off until implementation is complete, tests/checks have actually run, every acceptance criterion is verified, `PROGRESS.md` is updated, and the next Story is identified. Break each Story into a task checklist first, and update `PROGRESS.md` after every significant task — not only at the end — so an interrupted session can be resumed without repeating work. Do not automatically start the next Story.

**Vertical slices, not isolated FE/BE projects** (Blueprint §37):

```
Database → Backend Model → Service/Business Logic → API → Backend Tests
        → Frontend API Integration → UI → E2E Test → Commit
```

### Claude implementation rules (Blueprint §34) — binding

1. Read all approved architecture documents before modifying code.
2. Implement only the current Story.
3. Do not redesign existing architecture unless a blocking contradiction is discovered.
4. Do not invent API endpoints that are not required.
5. Do not add Phase 2 features.
6. Never bypass tenant permissions for convenience.
7. Never trust frontend-provided Workspace IDs, prices, roles, or state.
8. Run relevant tests after every Story.
9. Do not silently change database models without updating the architecture documentation.
10. At the end of each Story, report: **Implemented · Changed Files · Database Changes · API Changes · Tests · Security Checks · Known Issues · Next Recommended Story**.

---

## 17. Epic & Story Workflow

22 Epics (Blueprint §5; Epic 22 added in v1.2):

```
01 Project Foundation        08 Orders & Manual Payments   15 Progress Tracking
02 Authentication & Identity 09 Client Subscriptions       16 Notifications
03 Workspace & Multi-Tenancy 10 Client Management          17 Coach Dashboard
04 Coach Onboarding & Settings 11 Training Plans           18 Client Portal
05 Packages                  12 Nutrition Plans            19 Platform Admin
06 Public Coach Portal       13 Plan Assignments           20 Security & Hardening
07 Client Applications & OTP 14 Check-ins                  21 Production Deployment
```

Epics 01–21 are the v1.1 canonical list — Orders and Payments are **one** Epic (08) and none were renumbered. **Epic 22 — FitOps Billing & Subscriptions** was added in v1.2 and runs after Epic 19.

**Recommended implementation order (Blueprint §29 — a finer-grained sequence within those 21 Epics, not a second Epic list; use this exact order):**
Foundation → Authentication → Workspace/Tenant Infrastructure → Coach Onboarding → Packages → Public Portal → Applications/Client OTP → Orders → Payments → Subscriptions → Client Management → Training Plans → Nutrition Plans → Plan Assignments → Check-ins → Progress → Notifications → Coach Dashboard → Client Portal → Platform Admin → Security Hardening → Production Deployment.

**Parallelization (Blueprint §28):** only after Foundation is stable — auth ∥ workspace ∥ public-portal foundation; packages ∥ public package UI; training ∥ nutrition ∥ check-ins feeding assignments; admin UI after core models/permissions are stable. **Do not parallelize work that depends on unresolved database or authentication decisions.**

**Milestones:** 1 Foundation · 2 Identity · 3 Commercial Flow · 4 Coaching Flow · 5 Product Completion · 6 Production.

Story definitions (tasks + acceptance criteria) live in Blueprint §6–§26. Follow them; do not restate or reinterpret them here.

---

## 18. Testing Requirements

Three levels are **required** (Blueprint §30):

- **Unit:** models, services, validators, permissions, business rules.
- **API:** authentication, authorization, **tenant isolation**, request validation, response contracts, state transitions.
- **E2E:** the full core loop — coach registers → email verified → 2FA configured → workspace created → package created → public portal opened → client applies → client OTP login → order created → payment proof uploaded → coach approves → subscription created → client activated → plan assigned → client submits check-in → coach reviews → client sees feedback.

Mandatory tenant-isolation tests (Blueprint Story 3.5): Coach A cannot access Workspace B; Client A cannot access Client B; a Client cannot access their own data in another Workspace without Membership there; orders, plans and check-ins cannot cross workspaces.

Idempotency tests (Story 20.5): repeated order approval, payment submission, subscription creation, renewal, and client activation must not duplicate business state.

Run relevant tests after every Story. Report failures honestly with output — never claim a green suite that did not run.

---

## 19. Security Requirements

Phase 1 must include (DB §29, Blueprint Epic 20):

**Coach:** password hashing · email verification · secure password reset · TOTP 2FA · secure sessions · secure logout · login rate limiting.
**Client:** OTP hashing · OTP expiry · OTP attempt limits · OTP rate limiting · previous-OTP invalidation · secure sessions.
**Platform:** strict admin permissions · workspace isolation · client isolation · audit logs · secure cookies · HTTPS · CSRF protection.
**Files:** MIME validation · size validation · image processing · WebP conversion · thumbnails · authorized access only · no raw filesystem paths.
**API:** object-level authorization · input validation · rate limits · consistent errors · no sensitive data leakage · no cross-tenant access.

Anti-enumeration is required on: registration/resend verification, password forgot, and client OTP request (always return a generic success response).

Audit-log the sensitive actions: admin login, coach suspension/reactivation, workspace creation and changes, subscription changes, order approval, and other sensitive administrative actions.

**Never commit secrets.** `.env.example` only.

---

## 20. Definition of Done

### Story DONE (Blueprint §31)
Backend complete where required · frontend complete where required · API contract matches the approved API specification · permissions implemented · **tenant isolation verified** · validation exists · error states handled · tests pass · no secrets committed · **no unrelated scope added** · code reviewed · documentation updated if behavior changed · commit created.

### Epic DONE (Blueprint §32)
All Stories DONE · integration tests pass · relevant E2E flow works · no known critical tenant-isolation issue · API and UI behavior match · migrations stable · the Epic is usable by the next dependent Epic.

### MVP DONE (Blueprint §33)
Authentication (coach register/login, TOTP, client OTP, secure logout) · Multi-tenancy (multiple workspaces, multi-workspace client, no cross-portal leakage, cross-tenant tests pass) · Commerce (packages, applications, orders, manual payment proof, approval/rejection, subscriptions) · Coaching (clients, training, nutrition, assignments, check-ins, progress, feedback) · Dashboards (coach, client portal, platform admin) · Infrastructure (Docker, CI, Hetzner deploy, backups, file processing) · Security (tenant isolation verified, auth hardened, file access protected, rate limiting active, idempotency verified).

---

## 21. Git & Commit Conventions

Small, scoped commits using `type(scope): message` (Blueprint §35):

```
feat(accounts): add custom user model
feat(auth): add coach registration
feat(auth): add totp 2fa
feat(workspaces): add workspace creation endpoint
feat(workspaces): add tenant context
feat(applications): add public application flow
feat(orders): add manual payment flow
feat(checkins): add client check-ins
```

Avoid mega-commits like `feat: build entire application`. One Story ≈ one (or a few) small reviewable commits. Never commit secrets or generated media. This working directory is **not yet a git repository** — initializing it is Story 1.1.

---

## 22. Rules Against Scope Creep

- Implement **only** the current Story. Nothing adjacent, nothing "while we're here".
- No Phase 2 features unless explicitly promoted into Phase 1 by the user.
- No endpoints, models, fields, statuses, or enum values that are not in the approved documents.
- No new dependencies beyond the locked stack without approval.
- No refactors of approved architecture for elegance.
- "No unrelated scope was added" is part of the Story Definition of Done.
- If you believe something is missing from the specs, **report it — do not fill the gap silently**.
- Check `docs/MISSING_DECISIONS.md` before starting a Story. If the work reaches a decision listed there, **stop and ask** — do everything that does not depend on it, and report what is blocked.

---

## 23. Handling Architecture Conflicts

1. **Stop before coding.** Do not resolve a documentation conflict by choosing an interpretation and continuing (Blueprint §2).
2. **Precedence order:**
   1. Blueprint **§2A — Approved Architecture Decisions v1.1** (the decision log).
   2. Sections marked as locked overrides — API §28 "Locked Multi-Workspace Rules", DB §31, ERD §31 and "Architecture Corrections", Stack "Authentication Decision".
   3. The specialized document for the subject: DB/Auth Architecture for models & auth; API Spec for endpoints & contracts; ERD doc for app/repo structure; Blueprint for process & scope; design.md for UI.
   4. MVP Specification for product intent.
   5. This CLAUDE.md — lowest precedence, always.
3. **Report the conflict** with document + section for each side, plus the options, and wait for a decision.
4. If a model or contract genuinely must change, **update the architecture documentation in the same change** (Blueprint Rule 9) — never silently diverge.

### Previously open items — all resolved

| Item | Resolution (Blueprint §2A, Final v1.1 Decisions) |
|---|---|
| Per-session listing / revocation | **Removed from the MVP.** `POST /auth/logout` only; "log out everywhere" is a future feature |
| Coach "Payments" navigation | **No separate Payments module.** Orders is the primary nav item; "Payments" is a filtered Orders view |
| Client portal navigation | **Home · My Plan · Nutrition · Check-in · Progress · Profile** |
| Epic count | **21 Epics canonical in v1.1**, plus Epic 22 added in v1.2. Orders + Payments stay one Epic; §29 is a finer-grained sequence |
| Check-in schedule endpoints | **Approved:** `GET`/`PATCH /workspace/check-in-schedule` |
| Non-slug onboarding route | **Approved** for the period before the first Workspace exists |
| `PaymentMethod` fields | **Approved:** `account_details` and `image` |

### Still open

**All unresolved decisions live in `docs/MISSING_DECISIONS.md`** — the single central registry. It
currently holds **B24** (archive retention duration), **B25** (archive restoration scope), **B26**
(long-expired multi-period reactivation), **B27** (terminal `CANCELLED` cleanup lifecycle), plus the
deliberately unselected **SMTP provider** (deployment configuration; blocks no Story).

If implementation reaches any of them: **stop and ask for an explicit decision rather than
guessing.**

---

## 24. FitOps Billing — APPROVED v1.2

FitOps is itself a SaaS. Coaches/Workspaces subscribe to FitOps. **Two payment domains exist and must never share models:**

| Domain | Direction | Models | App |
|---|---|---|---|
| Coach Commerce | Client → Coach | `Order`, `Payment`, `PaymentMethod`, `Subscription` | `commerce`, `workspaces` |
| **FitOps Billing** | Coach → FitOps | `Plan`, `PlatformPaymentInstruction`, `PlatformSubscription`, `BillingPayment`, `BillingEvent` | `billing` |

Never reuse the Coach's client-facing `Order` for FitOps subscription billing. The Coach's `PaymentMethod` records are how that Coach's *Clients* pay *the Coach* — unrelated to how the Coach pays FitOps.

**MVP billing is manual through InstaPay, in EGP.** No Stripe, Paymob, Paddle, Lemon Squeezy, automated card billing, or automated recurring charge. The domain stays provider-agnostic: no provider-specific fields on the core models, `/api/v1/webhooks/...` stays reserved, and no provider credentials or card data are ever stored. FitOps' own InstaPay details are configured by the **Platform Admin** (`PlatformPaymentInstruction`), never by a Coach.

**Key rules that are easy to get wrong:**

- **7-day trial** created automatically with the Workspace (`TRIALING`), then **30-day** periods.
- **Late payment never resets the cycle.** The new period runs from the previous `renewal_date` to that date + 30 days — never from the payment or approval date. Paid Sept 5 for a period ending Aug 31 → new period Aug 31 → Sep 30.
- **`PAST_DUE` lasts 7 days**, then `EXPIRED`.
- **A billing state never removes Client access immediately.** Portal stays up on `PAST_DUE` and `CANCELLED`, and for **30 days** after `EXPIRED`. Client data is never auto-deleted or disabled.
- **After 30 days in `EXPIRED`** the Workspace is cleaned up and leaves the operational system, retained only as a `WorkspaceArchive` — never an active tenant, never reachable through normal routes.
- **A returning Coach with an archive gets an explicit choice**: *Restore Previous Data* or *Start Fresh*. Never restore automatically.
- Restricted Coach access still allows billing, subscription info, renewal/payment, account settings and logout.
- **Cancellation is cancel-at-period-end.** No refunds, no proration, no mid-cycle plan changes.
- **`SUSPENDED` is a Workspace state, never a subscription status**, and it supersedes subscription status.
- **Only the Workspace `OWNER`** may view or manage the FitOps subscription.
- `BillingPayment` states: `PENDING` → `SUBMITTED` → `APPROVED`, or `SUBMITTED` → `REJECTED` → `SUBMITTED` — distinct from the Coach-commerce `Payment.status` enum in §6.
- Approval is transactional and idempotent, and writes both a `BillingEvent` (business history) and an `AuditLog` entry (admin action).

**Billing statuses:** `TRIALING`, `ACTIVE`, `PAST_DUE`, `EXPIRED`, `CANCELLED` — a separate enum from the Client coaching `Subscription` statuses (`ACTIVE`, `EXPIRING`, `EXPIRED`, `CANCELLED`). Do not merge them.

**Renewal is manual:** a recurring period and renewal date that the Coach pays each cycle via InstaPay, with Platform Admin approval extending the subscription. Approval is one idempotent transaction that also writes a `BillingEvent` and an `AuditLog` entry.

Where it is documented:

| Aspect | Source |
|---|---|
| Product framing, flows, alerts | MVP Spec §19A |
| Models, lifecycle, access rules, provider boundary, open decisions | DB & Auth Architecture §22–§22G |
| API surface (coach + admin) and billing security rules | API Spec §20A |
| `billing` Django app and boundaries | ERD §20A |
| Epic 22 and its Stories | Blueprint §26A |
| Billing UI, renewal banner, admin queue | design.md §19A |

Roadmap: **Epic 22 — FitOps Billing & Subscriptions**, an approved addition. The previous 21 Epics are unchanged and are not renumbered or merged.

Billing has four unresolved decisions (B24–B27) in `docs/MISSING_DECISIONS.md`, touching Stories 22.6, 22.9, 22.10b and 22.10c. Stop and ask if you reach one.

---

## 25. Current Project State

- Repository contains **documentation only**. No application code, no git repo, no Epic started.
- Documentation baseline is **Architecture v1.1** with all twelve approved decisions applied.
- **Do not start Epic 01 or write application code until the user explicitly says to begin.**
