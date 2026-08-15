# FitOps — Development Blueprint v1.2.1

> Version 1.2.1 adds the retention/archive/restoration Stories and the explicit Coach-commerce
> payment statuses.
> Version 1.2 adds the approved **FitOps Billing** scope: Epic 22 (§26A).
> Version 1.1 decisions remain in force and unchanged.
> The product name is **FitOps**. Earlier drafts used the working title "Coaching SaaS".

## 1. Purpose

This document converts the approved MVP, technology stack, database/authentication architecture, API specification, and ERD/repository architecture into an implementation plan.

The implementation must follow this blueprint incrementally.

### Core rule

> Implement one Story at a time, test it, verify it against the approved architecture/API contract, then move to the next Story.

Do not introduce architecture changes or unapproved Phase 2 features during implementation.

---

# 2. Source of Truth

The following documents are authoritative for Phase 1:

1. MVP Specification — `docs/01-product/fitops_mvp_spec_v1.md`
2. Technology Stack — `docs/02-architecture/fitops_technology_stack_v1.md`
3. Database & Authentication Architecture — `docs/02-architecture/fitops_database_auth_architecture_v1.md`
4. API Specification — `docs/02-architecture/fitops_api_specification_v1.md`
5. ERD / Django Apps / Repository Architecture — `docs/02-architecture/fitops_erd_django_repository_architecture_v1.md`
6. Design System — `docs/04-design/design.md`

If implementation details conflict with these documents, stop and resolve the conflict before coding.

---

# 2A. Approved Architecture Decisions — v1.1

These twelve decisions are approved and are reflected in the documents above. They are recorded here
as the canonical decision log.

| # | Decision |
|---|---|
| 1 | **Email** — Django's email backend abstraction with an SMTP provider. The specific SMTP provider is deployment configuration and is set through environment variables. |
| 2 | **Workspace creation** — `POST /api/v1/workspace` creates the Coach's first Workspace during onboarding and creates the OWNER Membership. |
| 3 | **Coach workspace context** — Coach dashboard routes are Workspace-slug-scoped (`/{workspaceSlug}/dashboard`, `/{workspaceSlug}/clients`, …). The backend resolves the Workspace from the slug and verifies an active Membership. A frontend-provided `workspace_id` is never trusted. |
| 4 | **Application → Order** — the public Client Application creates the initial Order as part of the application flow, consistently and safely. Authenticated Clients use `POST /orders` for subsequent purchases. |
| 5 | **Payment methods** — configurable per Coach/Workspace: InstaPay, Vodafone Cash, Bank Transfer, Custom, each with name, instructions, account/number details, optional QR/image, and active/inactive state. No automated payment gateways in Phase 1. |
| 6 | **Check-in schedule** — simple Workspace-level configuration: Weekly or Biweekly, plus day of week. The design must allow future expansion without the MVP implementing complex scheduling. |
| 7 | **Tenant-scoped foreign keys** — Workspace-specific business relationships use `Membership` as the tenant-specific identity relationship. A global `ClientProfile`/`User` reference alone must not be used where that would lose Workspace context. Workspace-scoped records stay explicitly Workspace-scoped, and the global `User` + `ClientProfile` architecture is preserved. |
| 8 | **Sessions** — Django's built-in session framework. No custom `UserSession` / `token_hash` system. Sessions must still provide HttpOnly cookies, Secure cookies in production, appropriate SameSite, CSRF protection, session revocation/logout, and authentication rate limiting. Scope of "revocation" is narrowed by decision 13 below: `POST /auth/logout` only, no per-session management. |
| 9 | **`Application.user_id`** — nullable, because a public application may come from an anonymous visitor. The flow may later create/reuse `User`, create/reuse `ClientProfile`, create `Membership`, and associate `Application.user_id`. No authenticated User is required at public application creation time. |
| 10 | **Documentation structure** — `docs/01-product`, `docs/02-architecture`, `docs/03-development`, `docs/04-design`. The project/repository uses the product name **FitOps**. |
| 11 | **`applications` Django app** — `backend/apps/applications/` owns public applications, application lifecycle and status, the Application → initial Order flow, and Application → Client conversion. `clients` keeps Client-facing business operations; `ClientProfile` stays in `accounts`. |
| 12 | **`Membership.joined_at`** — part of the authoritative Membership schema. |

### Final v1.1 Decisions

| # | Decision |
|---|---|
| 13 | **Session management** — `GET /auth/sessions` and `POST /auth/sessions/{id}/revoke` are removed from the MVP. `POST /auth/logout` is kept. Per-session management is not implemented; "log out everywhere" is a future feature. |
| 14 | **Payments** — no separate Payments list module in the MVP. Payments are represented through Orders and their payment-related states. The Coach dashboard keeps **Orders** as the primary navigation item; any "Payments" navigation item is a filtered Orders view, not a separate backend domain. |
| 15 | **Client Portal navigation** — Home, My Plan, Nutrition, Check-in, Progress, Profile. |
| 16 | **Epic count** — the 21-Epic list in §5 is canonical. Orders and Payments remain one Epic (Epic 08). §29 is a finer-grained implementation sequence, not a second Epic list, and no Epic is added to resolve the numbering. |
| 17 | **SMTP** — the provider remains deployment configuration and is not selected. |
| 18 | **Approved inferences** — `GET`/`PATCH /workspace/check-in-schedule`; a non-slug onboarding route for the period before the first Workspace exists; `PaymentMethod.account_details` and `PaymentMethod.image`. |

---

# 2B. Approved Billing Decisions — v1.2

FitOps Billing (Coach → FitOps) is approved. Authoritative rules: Database & Authentication
Architecture §22–§22G. Summary:

| # | Decision |
|---|---|
| 19 | **Separate domain** — FitOps Billing never reuses Coach Commerce `Order` or `PaymentMethod`. Canonical app: `backend/apps/billing/`. |
| 20 | **Plans** — Starter / Growth / Pro, platform-owned, prices configured by Platform Admin, monthly billing (annual reserved). Admin can create, edit and activate/deactivate; no destructive deletion when referenced by a subscription. |
| 21 | **Subscription** — owned by the Workspace, states `TRIALING`, `ACTIVE`, `PAST_DUE`, `EXPIRED`, `CANCELLED`. Subscription state is never duplicated onto `Workspace`. |
| 22 | **Trial** — 7 days, created with the Workspace, no gateway needed to convert. |
| 23 | **Payment method** — manual InstaPay, EGP, provider-agnostic. No Stripe/Paymob/Paddle/card/automated recurring gateways. |
| 24 | **Platform InstaPay configuration** — `PlatformPaymentInstruction`, configured by Platform Admin only; no sensitive credentials stored. |
| 25 | **BillingPayment** — `PENDING` → `SUBMITTED` → `APPROVED`, or `SUBMITTED` → `REJECTED` → `SUBMITTED`. Carries subscription, workspace, amount, currency, reference, proof, timestamps and reviewer. |
| 26 | **Approval** — transactional and idempotent: approve payment → update subscription → extend period → `BillingEvent` → `AuditLog`. |
| 27 | **Renewal** — 30-day periods, manual payment. Late payment never resets the cycle; the new period is anchored to the previous period end. |
| 28 | **Grace** — `PAST_DUE` for 7 days, then `EXPIRED`. Coach dashboard restricted while billing stays accessible; Client Portal unaffected. |
| 29 | **Restricted access** — billing, subscription info, renewal/payment, account settings and logout remain; coaching-management functionality is blocked. Client data is never auto-deleted or disabled. |
| 30 | **Reactivation** — `EXPIRED` returns to `ACTIVE` on a new approved payment, with the same anchoring rule. |
| 31 | **Cancellation** — `cancel_at_period_end = true`; the paid period runs out. No immediate cancellation, no refunds, no proration. |
| 32 | **Plan changes** — not supported mid-cycle; any change applies at the next renewal period. |
| 33 | **Workspace suspension** — `Workspace.status` (`ACTIVE`/`SUSPENDED`) is independent of subscription status and supersedes it. `SUSPENDED` is never a subscription status. |
| 34 | **BillingEvent vs AuditLog** — `BillingEvent` is business billing history; `AuditLog` is security/administrative actions. Both are written on admin decisions; responsibilities are not duplicated. |
| 35 | **Renewal alerts** — in-app, 7/3/1 days before renewal, on the renewal date, and daily while `PAST_DUE`. Semantic colors only, never the Coach brand color. |
| 36 | **OWNER permission** — only the Workspace OWNER views and manages the FitOps subscription. Platform Admin retains full billing authority. |
| 37 | **Epic 22** — `EPIC 22 — FitOps Billing & Subscriptions` is an approved roadmap addition. The previous 21 Epics are unchanged and not renumbered. |

### Approved v1.2.1 Decisions

| # | Decision |
|---|---|
| 38 | **EXPIRED client access** — the Client Portal does not become unavailable immediately. Clients keep Portal access and their existing plans and data for **30 days** after the subscription becomes EXPIRED. Coach stays restricted with billing, subscription info, renewal/payment, account settings and logout available. |
| 39 | **Retention window** — after those 30 days the Workspace is cleaned up/deactivated and leaves the operational system. |
| 40 | **Archive** — cleanup archives rather than destroys. The archive is not an active tenant, is not reachable through normal application routes, and exists only for recovery/restoration. |
| 41 | **Returning Coach** — an explicit choice between **Restore Previous Data** and **Start Fresh**. Never restore automatically; never expose the archive as an active Workspace. |
| 42 | **Coach-commerce `Payment.status`** — `PENDING`, `SUBMITTED`, `APPROVED`, `REJECTED`, `CANCELLED`. Completely separate from the FitOps `BillingPayment` enum. |
| 43 | **Cancellation timing** — unchanged and confirmed: `cancel_at_period_end = true`, the period runs out, the request is recorded as a `SUBSCRIPTION_CANCELLED` event with effective-date metadata, and `cancelled_at` is set when the subscription actually enters CANCELLED. No separate request event type. |

---

# 3. Phase 1 Product Goal

The MVP must support the complete coaching business loop:

```text
Coach
 ↓
Create Workspace
 ↓
Configure Branding
 ↓
Create Package
 ↓
Publish Portal
 ↓
Client Applies
 ↓
Client Login via Email OTP
 ↓
Order Created
 ↓
Payment Proof Submitted
 ↓
Coach Reviews Payment
 ↓
Order Approved
 ↓
Client Activated
 ↓
Training/Nutrition Plan Assigned
 ↓
Client Views Plan
 ↓
Client Submits Check-in
 ↓
Client Uploads Progress Photos
 ↓
Coach Reviews Check-in
 ↓
Coach Sends Feedback
 ↓
Client Tracks Progress
```

The MVP is successful when this flow works end-to-end in production-like conditions.

---

# 4. Implementation Principles

## 4.1 Tenant Isolation First

Every Workspace business operation must respect tenant isolation.

Never trust:

```text
workspace_id
```

from the frontend.

The active Workspace is resolved from the URL slug and authenticated Membership.

---

## 4.2 Global User Identity

`User` is global.

`ClientProfile` is global.

A Client can belong to multiple Workspaces through Membership.

The Client Portal must only operate inside the Workspace represented by the current URL.

Workspace-scoped business records reference the Client (and the Coach on `CoachFeedback`) through
`Membership`, never through a global `User` or `ClientProfile` reference alone. `Application` is the
exception and carries a nullable `user_id`.

---

## 4.3 Backend Owns Business Rules

The frontend must never be trusted for:

- Prices
- Workspace ownership
- Client ownership
- Subscription state
- Order state
- Payment approval
- Permissions
- Activation state

The backend is authoritative.

---

## 4.4 Small Incremental Changes

Each Story should produce a small, reviewable change.

Preferred cycle:

```text
Plan
 ↓
Implement
 ↓
Test
 ↓
Review
 ↓
Commit
 ↓
Next Story
```

---

## 4.5 No Scope Creep

Do not implement Phase 2 features unless explicitly promoted into Phase 1.

Examples of Phase 2 / future work:

- Automated payment gateways
- WhatsApp API automation
- Native mobile apps
- AI coaching
- Advanced analytics
- Marketplace features
- Complex SaaS billing automation

---

# 5. Epic Overview

```text
EPIC 01 — Project Foundation
EPIC 02 — Authentication & Identity
EPIC 03 — Workspace & Multi-Tenancy
EPIC 04 — Coach Onboarding & Settings
EPIC 05 — Packages
EPIC 06 — Public Coach Portal
EPIC 07 — Client Applications & OTP
EPIC 08 — Orders & Manual Payments
EPIC 09 — Client Subscriptions
EPIC 10 — Client Management
EPIC 11 — Training Plans
EPIC 12 — Nutrition Plans
EPIC 13 — Plan Assignments
EPIC 14 — Check-ins
EPIC 15 — Progress Tracking
EPIC 16 — Notifications
EPIC 17 — Coach Dashboard
EPIC 18 — Client Portal
EPIC 19 — Platform Admin
EPIC 20 — Security & Hardening
EPIC 21 — Production Deployment
```

Approved addition in v1.2. The previous 21 Epics are unchanged and are **not** renumbered or
merged:

```text
EPIC 22 — FitOps Billing & Subscriptions      # approved v1.2, see §26A
```

---

# 6. EPIC 01 — Project Foundation

## Goal

Create the production-ready repository and development environment.

### Story 1.1 — Monorepo Setup — ✅ COMPLETE (2026-08-14)

Create:

```text
fitops/
├── frontend/
├── backend/
├── infrastructure/
├── docs/
│   ├── 01-product/
│   ├── 02-architecture/
│   ├── 03-development/
│   └── 04-design/
└── README.md
```

### Tasks

- Initialize Git repository
- Create frontend directory
- Create backend directory
- Create infrastructure directory
- Create docs structure
- Add root README
- Add `.gitignore`
- Add `.env.example`

### Acceptance Criteria

- Repository structure matches architecture document.
- No secrets are committed.
- Local setup instructions exist.

### DoD

- Clean clone can initialize successfully.
- README explains setup.

---

## Story 1.2 — Django Backend Setup — ✅ COMPLETE (2026-08-14)

### Tasks

- Initialize Django project
- Configure Django REST Framework
- Create approved apps
- Configure settings structure
- Configure environment variables
- Configure PostgreSQL
- Configure static/media handling
- Configure Django's session framework
- Configure Django's email backend with SMTP settings sourced from environment variables

### Apps

```text
accounts
workspaces
coaching
clients
applications
commerce
billing
notifications
audit
```

### Acceptance Criteria

- Django starts successfully.
- Database connection works.
- All approved apps load correctly.

---

## Story 1.3 — Next.js Frontend Setup — ✅ COMPLETE (2026-08-15)

### Tasks

- Initialize Next.js
- Configure TypeScript
- Configure Tailwind
- Configure shadcn/ui
- Configure React Hook Form
- Configure Zod
- Configure TanStack Query

### Acceptance Criteria

- Frontend builds successfully.
- Development server works.
- Basic application shell exists.

---

## Story 1.4 — PostgreSQL Setup — ✅ COMPLETE (2026-08-15)

### Tasks

- Create PostgreSQL service
- Configure development database
- Configure test database strategy
- Configure migrations

### Acceptance Criteria

- Django migrations execute.
- Database connection is stable.

---

## Story 1.5 — Redis + Celery — ✅ COMPLETE (2026-08-15)

### Tasks

- Add Redis
- Configure Celery
- Create worker configuration
- Create basic health task

### Acceptance Criteria

- Celery worker starts.
- Celery can communicate with Redis.

---

## Story 1.6 — Docker Compose — ✅ COMPLETE (2026-08-15)

### Services

```text
frontend
backend
postgres
redis
celery
nginx
```

### Acceptance Criteria

- Entire development stack starts with Docker Compose.
- Services communicate correctly.

---

## Story 1.7 — Testing and Quality Baseline

### Tasks

- Backend test setup
- Frontend test setup
- Linting
- Formatting
- Type checking
- Basic CI checks

### Acceptance Criteria

All baseline checks can run locally.

---

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

---

# 7. EPIC 02 — Authentication & Identity

## Goal

Implement the approved authentication model.

```text
Coach
Email + Password + TOTP 2FA
        ↓
Secure Session

Client
Email + OTP
        ↓
Secure Session

Admin
Authenticated User + Platform Role
```

---

## Story 2.1 — Custom User Model

### Tasks

Create User model with:

- UUID
- Email
- Password
- First name
- Last name
- Phone
- Active state
- Email verification state
- Platform role
- Timestamps

### Acceptance Criteria

- Email is unique.
- User model is used as Django AUTH_USER_MODEL.
- Passwords are securely hashed.

---

## Story 2.2 — Coach Profile

Create:

```text
CoachProfile
```

Fields include approved public/profile data.

---

## Story 2.3 — Client Profile

Create:

```text
ClientProfile
```

Important:

> `ClientProfile` MUST NOT contain `workspace_id`.

Client identity is global.

---

## Story 2.4 — Coach Registration

### API

```text
POST /auth/register
```

### Flow

```text
Register
 ↓
Create User
 ↓
Send verification email
 ↓
Verify
```

---

## Story 2.5 — Email Verification

Implement:

```text
POST /auth/email/verify
POST /auth/email/resend
```

Requirements:

- Expiring token
- Secure token storage
- Rate limiting
- Generic responses where necessary

---

## Story 2.6 — Coach Login

Implement:

```text
POST /auth/login
```

Flow:

```text
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

---

## Story 2.7 — TOTP 2FA

Implement:

```text
POST /auth/2fa/setup
POST /auth/2fa/confirm
POST /auth/2fa/verify
POST /auth/2fa/disable
```

Requirements:

- TOTP secret protection
- Setup confirmation
- Verification attempt limits
- Secure recovery strategy

---

## Story 2.8 — Client OTP

Implement:

```text
POST /auth/client/request-code
POST /auth/client/verify-code
```

Requirements:

- OTP hashing
- Expiration
- Attempt limit
- Rate limiting
- Previous OTP invalidation
- Secure session creation

The request must include the Workspace slug/context.

---

## Story 2.9 — Sessions

Implement:

```text
GET  /auth/me
POST /auth/logout
```

Use Django's built-in session framework with secure HttpOnly cookies, the Secure flag in
production, appropriate SameSite configuration, CSRF protection, secure logout, and
authentication rate limiting.

Do not implement a custom `UserSession` / `token_hash` system.

Out of MVP scope: session listing and per-session revocation
(`GET /auth/sessions`, `POST /auth/sessions/{id}/revoke`). "Log out everywhere" is a future feature.

---

## Story 2.10 — Password Reset

Implement:

```text
POST /auth/password/forgot
POST /auth/password/reset
```

Prevent account enumeration.

---

# 8. EPIC 03 — Workspace & Multi-Tenancy

## Goal

Build the tenant boundary.

---

## Story 3.1 — Workspace Model

Create:

```text
Workspace
```

with:

- Name
- Slug
- Logo
- Profile image
- Description
- Brand color
- Currency
- Timezone
- WhatsApp number
- Status
- Timestamps

---

## Story 3.2 — Membership Model

Create:

```text
Membership
```

Fields include `joined_at`.

Roles:

```text
OWNER
COACH
CLIENT
```

Constraint:

```text
UNIQUE(user_id, workspace_id)
```

---

## Story 3.3 — Workspace Resolution

Implement server-side resolution:

```text
URL slug
 ↓
Workspace
 ↓
Authenticated User
 ↓
Membership
 ↓
Workspace Context
```

This applies to the Coach dashboard routes (`/{workspaceSlug}/dashboard`, `/{workspaceSlug}/clients`,
`/{workspaceSlug}/orders`, …) as well as the public and Client portals.

Never trust Workspace IDs from the frontend.

---

## Story 3.4 — Tenant Query Infrastructure

Create shared utilities for:

- Workspace-scoped models
- Tenant querysets
- Workspace permissions
- Tenant context
- Object ownership
- Membership resolution (the tenant-scoped identity used by Workspace-scoped business records)

---

## Story 3.5 — Tenant Isolation Tests

Test:

- Coach A cannot access Workspace B.
- Client A cannot access Client B.
- Client A cannot access the same Client's data in another Workspace unless Membership exists.
- Orders cannot cross Workspaces.
- Plans cannot cross Workspaces.
- Check-ins cannot cross Workspaces.

---

# 9. EPIC 04 — Coach Onboarding & Settings

## Story 4.1 — Create Workspace

After Coach authentication:

```text
POST /api/v1/workspace
```

Creates the Coach's first Workspace during onboarding.

In a single transaction:

```text
Validate + reserve slug
 ↓
Create Workspace
 ↓
Create Membership(role=OWNER)
 ↓
Create PlatformSubscription (TRIALING, 7-day trial)   # Epic 22, Story 22.3
 ↓
Audit event
```

Creator becomes:

```text
OWNER
```

After creation, every Workspace-scoped route for this Coach uses the Workspace slug.

---

## Story 4.2 — Workspace Settings

Implement:

```text
GET /workspace
PATCH /workspace
```

---

## Story 4.3 — Branding

Implement:

```text
PATCH /workspace/branding
POST /workspace/logo
```

---

## Story 4.4 — Payment Methods

Implement:

```text
GET    /workspace/payment-methods
POST   /workspace/payment-methods
PATCH  /workspace/payment-methods/{id}
DELETE /workspace/payment-methods/{id}
```

Types:

```text
INSTAPAY
VODAFONE_CASH
BANK_TRANSFER
CUSTOM
```

Each payment method supports name, instructions, account/number details, an optional QR code or
image, and an active/inactive state.

No automated payment gateway integration in Phase 1.

---

# 10. EPIC 05 — Packages

## Story 5.1 — Package CRUD

Implement:

```text
GET    /packages
POST   /packages
GET    /packages/{id}
PATCH  /packages/{id}
DELETE /packages/{id}
```

---

## Story 5.2 — Package State

Implement:

```text
POST /packages/{id}/activate
POST /packages/{id}/deactivate
```

---

## Story 5.3 — Duplicate Package

Implement:

```text
POST /packages/{id}/duplicate
```

---

# 11. EPIC 06 — Public Coach Portal

## Story 6.1 — Public Coach Page

Implement:

```text
GET /public/coaches/{slug}
```

Display:

- Coach profile
- Branding
- Description
- Active packages

---

## Story 6.2 — Public Packages

Implement:

```text
GET /public/coaches/{slug}/packages
```

---

## Story 6.3 — Public Application

Implement:

```text
POST /public/coaches/{slug}/applications
```

Application becomes a first-class business record.

---

# 12. EPIC 07 — Client Applications & OTP

## Story 7.1 — Application Model

Create the `applications` Django app (`backend/apps/applications/`) and its model:

```text
Application
```

Workspace-scoped. `user_id` is nullable.

---

## Story 7.2 — Application Submission

Capture:

- Full name
- Email
- Phone
- Age
- Gender
- Height
- Weight
- Goal
- Training experience
- Notes
- Package

---

## Story 7.3 — Client Onboarding

Application flow, in a single transaction:

```text
Application (SUBMITTED)
 ↓
Find/Create User
 ↓
Find/Create ClientProfile
 ↓
Create Client Membership
 ↓
Associate Application.user_id
 ↓
Create initial Order
```

The public endpoint does not require an authenticated User; `Application.user_id` starts null when
the visitor is anonymous.

The Application and its initial Order must be created consistently and safely — no Application
without its Order, no Order without its Application.

A global Client User can already exist because of another Workspace.

Subsequent purchases by an authenticated Client use `POST /orders` (Story 8.2), not this flow.

---

## Story 7.4 — Client Portal Authentication

Client requests OTP from the Workspace-specific portal.

The Client must have valid Membership for that Workspace before accessing protected data.

---

# 13. EPIC 08 — Orders & Manual Payments

## Story 8.1 — Order Model

Create Workspace-scoped Order.

---

## Story 8.2 — Order Creation

Implement:

```text
POST /orders
```

For **subsequent** purchases by an authenticated Client. The initial Order is created by the
application flow (Story 7.3).

Backend determines:

- Client (through the Client's Membership in the resolved Workspace)
- Workspace
- Package
- Price
- Currency

---

## Story 8.3 — Payment Submission

Implement:

```text
POST /orders/{id}/payment
```

Support manual payment proof.

Coach-commerce `Payment.status`:

```text
PENDING
SUBMITTED
APPROVED
REJECTED
CANCELLED
```

Separate from the FitOps `BillingPayment` enum (Epic 22). Never share or merge the two.

---

## Story 8.4 — Payment Proof Access

Implement authorized proof retrieval.

---

## Story 8.5 — Order Approval

Implement:

```text
POST /orders/{id}/approve
```

Transactional sequence:

```text
Validate Order
 ↓
Validate Payment
 ↓
Approve Payment
 ↓
Approve Order
 ↓
Create Subscription
 ↓
Activate Client
 ↓
Notifications
 ↓
Audit Event
```

Must be idempotent.

---

## Story 8.6 — Order Rejection

Implement:

```text
POST /orders/{id}/reject
```

With rejection reason.

---

## Story 8.7 — Order Cancellation

Implement:

```text
POST /orders/{id}/cancel
```

Only for valid cancellable states.

---

# 14. EPIC 09 — Client Subscriptions

## Story 9.1 — Subscription Model

Create Client → Workspace subscription.

---

## Story 9.2 — Subscription Access

Implement:

```text
GET /subscriptions
GET /subscriptions/{id}
GET /client/subscription
```

---

## Story 9.3 — Renewal

Implement manual renewal:

```text
POST /subscriptions/{id}/renew
```

Renewal must create the appropriate commercial record.

---

## Story 9.4 — Cancellation

Implement:

```text
POST /subscriptions/{id}/cancel
```

---

# 15. EPIC 10 — Client Management

## Story 10.1 — Client List

Implement:

```text
GET /clients
```

Support:

- Search
- Status
- Subscription
- Pagination

---

## Story 10.2 — Client Details

Implement:

```text
GET /clients/{id}
```

Aggregate:

- Profile
- Orders
- Subscription
- Plans
- Check-ins
- Progress summary

---

## Story 10.3 — Manual Client Creation

Implement:

```text
POST /clients
```

---

## Story 10.4 — Client Status

Implement:

```text
PATCH /clients/{id}
POST /clients/{id}/deactivate
POST /clients/{id}/reactivate
```

---

## Story 10.5 — Client Activity

Implement:

```text
GET /clients/{id}/activity
```

---

# 16. EPIC 11 — Training Plans

## Story 11.1 — Training Plan CRUD

```text
GET    /training-plans
POST   /training-plans
GET    /training-plans/{id}
PATCH  /training-plans/{id}
DELETE /training-plans/{id}
```

---

## Story 11.2 — Training Weeks

```text
POST  /training-plans/{id}/weeks
PATCH /training-weeks/{id}
```

---

## Story 11.3 — Training Days

```text
POST  /training-weeks/{id}/days
PATCH /training-days/{id}
```

---

## Story 11.4 — Exercises

```text
POST   /training-days/{id}/exercises
PATCH  /exercises/{id}
DELETE /exercises/{id}
```

Exercise fields:

- Name
- Sets
- Reps
- Rest
- Notes
- Order

---

# 17. EPIC 12 — Nutrition Plans

## Story 12.1 — Nutrition Plan CRUD

```text
GET    /nutrition-plans
POST   /nutrition-plans
GET    /nutrition-plans/{id}
PATCH  /nutrition-plans/{id}
DELETE /nutrition-plans/{id}
```

---

## Story 12.2 — Meals

```text
POST   /nutrition-plans/{id}/meals
PATCH  /nutrition-meals/{id}
DELETE /nutrition-meals/{id}
```

Meal fields:

- Name
- Description
- Calories
- Notes
- Order

---

# 18. EPIC 13 — Plan Assignments

## Story 13.1 — Assign Plans

```text
POST /clients/{id}/plans
```

Supports:

- Training plan
- Nutrition plan
- Start date
- End date

---

## Story 13.2 — Assignment Management

```text
PATCH /plan-assignments/{id}
POST  /plan-assignments/{id}/end
```

---

## Story 13.3 — Client Plan Access

```text
GET /client/plans
GET /client/plans/history
```

---

# 19. EPIC 14 — Check-ins

## Story 14.0 — Check-in Schedule Configuration

Create the Workspace-scoped `CheckInSchedule` model and implement:

```text
GET   /workspace/check-in-schedule
PATCH /workspace/check-in-schedule
```

Supports:

```text
frequency: WEEKLY | BIWEEKLY
day_of_week
```

Keep it simple. Per-client schedules and custom cadences are out of Phase 1 scope; the model should
allow that expansion later without a redesign.

---

## Story 14.1 — Current Check-in

```text
GET /client/check-ins/current
```

---

## Story 14.2 — Create Draft

```text
POST /client/check-ins
```

---

## Story 14.3 — Update Draft

```text
PATCH /client/check-ins/{id}
```

Only `DRAFT` check-ins are editable.

---

## Story 14.4 — Check-in Photos

```text
POST /client/check-ins/{id}/photos
```

---

## Story 14.5 — Submit Check-in

```text
POST /client/check-ins/{id}/submit
```

State:

```text
DRAFT → SUBMITTED
```

---

## Story 14.6 — Coach Check-in Queue

```text
GET /check-ins
GET /check-ins/{id}
```

---

## Story 14.7 — Coach Review

```text
POST /check-ins/{id}/review
```

State:

```text
SUBMITTED → REVIEWED
```

---

# 20. EPIC 15 — Progress Tracking

## Story 15.1 — Client Progress

```text
GET /client/progress
GET /clients/{id}/progress
```

---

## Story 15.2 — Progress Photos

```text
POST   /client/progress/photos
DELETE /client/progress/photos/{id}
```

---

## Story 15.3 — Progress History

Display:

- Weight history
- Progress photos
- Check-in history

---

# 21. EPIC 16 — Notifications

## Story 16.1 — Notification Model

Create Workspace-scoped Notification.

---

## Story 16.2 — Notification List

```text
GET /notifications
GET /notifications/unread-count
```

---

## Story 16.3 — Read State

```text
POST /notifications/{id}/read
POST /notifications/read-all
```

---

## Story 16.4 — Notification Events

Create notifications for important events:

```text
New Order
Payment Submitted
Payment Rejected
Order Approved
Plan Assigned
New Check-in
Coach Feedback
Subscription Expiring
```

---

# 22. EPIC 17 — Coach Dashboard

## Story 17.1 — Dashboard API

```text
GET /dashboard
```

Return:

- Active clients
- New orders
- Pending payments
- Pending check-ins
- Revenue
- Expiring subscriptions
- Recent activity

---

## Story 17.2 — Dashboard UI

Build the Coach overview.

Priority:

1. Pending actions
2. New orders
3. Check-ins
4. Clients
5. Revenue
6. Recent activity

---

# 23. EPIC 18 — Client Portal

## Story 18.1 — Client Dashboard

```text
GET /client/dashboard
```

Display:

- Current package
- Days remaining
- Current plans
- Check-in status
- Latest feedback
- Progress summary

---

## Story 18.2 — Training Plan UI

Client can view assigned training plan.

---

## Story 18.3 — Nutrition Plan UI

Client can view assigned nutrition plan.

---

## Story 18.4 — Check-in UI

Client can:

- Fill check-in
- Upload photos
- Submit
- View previous check-ins

---

## Story 18.5 — Progress UI

Client can view their progress history.

---

# 24. EPIC 19 — Platform Admin

## Story 19.1 — Admin Authentication Boundary

Only users with:

```text
platform_role = ADMIN
```

can access admin routes.

---

## Story 19.2 — Admin Dashboard

```text
GET /admin/dashboard
```

Display:

- Total Coaches
- Active Coaches
- Workspaces
- Platform subscriptions
- Clients
- Orders
- Platform activity

---

## Story 19.3 — Coach Management

```text
GET  /admin/coaches
GET  /admin/coaches/{id}
POST /admin/coaches/{id}/suspend
POST /admin/coaches/{id}/reactivate
```

---

## Story 19.4 — Workspace Management

```text
GET  /admin/workspaces
GET  /admin/workspaces/{id}
POST /admin/workspaces/{id}/suspend
POST /admin/workspaces/{id}/reactivate
```

---

## Story 19.5 — Platform Subscriptions

```text
GET /admin/subscriptions
GET /admin/subscriptions/{id}
```

Phase 1 supports management/visibility.

Automated SaaS billing is not required.

---

## Story 19.6 — Audit Logs

```text
GET /admin/audit-logs
```

Log:

- Admin login
- Coach suspension
- Coach reactivation
- Workspace changes
- Subscription changes
- Sensitive administrative actions

---

# 25. EPIC 20 — Security & Hardening

## Story 20.1 — Tenant Isolation Audit

Verify every Workspace business query.

---

## Story 20.2 — Permission Audit

Verify:

```text
Platform Admin
Coach Owner
Coach
Client
```

permissions independently.

---

## Story 20.3 — Authentication Hardening

Verify:

- Secure cookies
- CSRF
- Password hashing
- OTP hashing
- OTP expiration
- OTP rate limits
- Login rate limits
- Secure logout / session termination
- TOTP protection

---

## Story 20.4 — File Security

Verify:

- MIME validation
- File size validation
- Image processing
- WebP conversion
- Thumbnail generation
- Authorized file access
- No raw filesystem paths

---

## Story 20.5 — Idempotency

Test:

- Order approval
- Payment submission
- Subscription creation
- Subscription renewal
- Client activation

Repeated requests must not duplicate business state.

---

## Story 20.6 — API Security

Verify:

- Object-level authorization
- Input validation
- Rate limits
- Consistent errors
- No sensitive data leakage
- No cross-tenant access

---

# 26. EPIC 21 — Production Deployment

## Story 21.1 — Production Docker Configuration

Create production-safe Docker configuration.

---

## Story 21.2 — Nginx

Configure:

- Reverse proxy
- Static files
- Media handling
- Security headers
- Request limits

---

## Story 21.3 — Cloudflare

Configure:

- DNS
- SSL/TLS
- Proxy
- Basic security

---

## Story 21.4 — Hetzner Deployment

Deploy:

```text
frontend
backend
postgres
redis
celery
nginx
```

---

## Story 21.5 — Backups

Implement automated PostgreSQL and media backup strategy.

Important:

> Hetzner storage is not itself a backup.

---

## Story 21.6 — Production Monitoring

Minimum:

- Application errors
- Worker failures
- Database availability
- Disk usage
- CPU/RAM
- Service health

---

# 26A. EPIC 22 — FitOps Billing & Subscriptions

> **Status: APPROVED — Architecture v1.2.**
> Models, lifecycle and access rules: Database & Authentication Architecture §22–§22G.
> API: API Specification §20A. App: ERD §20A. UI: design.md §19A.
>
> Epic 22 is an approved addition to the roadmap. The previous 21 Epics are unchanged.
> Document these Stories; do not implement them until told to start.

## Goal

Let Coaches subscribe to FitOps and pay manually through InstaPay in EGP, with Platform Admin
review and approval, a 7-day trial, 30-day billing periods and manual renewal.

## Placement

Billing depends on Workspaces (Epic 03), Coach onboarding (Epic 04), Notifications (Epic 16) and
Platform Admin (Epic 19). It therefore sits after Epic 19 and before Security Hardening.

---

## Story 22.1 — Plan Model and Admin Management

Create the platform-owned `Plan` model (code, name, description, price, currency `EGP`,
`billing_interval`, features, `is_active`) with the initial Starter / Growth / Pro plans, plus:

```text
GET  /billing/plans                     # coach-facing catalogue
GET  /admin/plans
POST /admin/plans
PATCH /admin/plans/{id}
POST /admin/plans/{id}/activate
POST /admin/plans/{id}/deactivate
```

No prices are specified by the architecture; the Platform Admin configures pricing.

**No destructive deletion** of a Plan referenced by an existing subscription — deactivate only, and
existing subscriptions must keep resolving to it.

---

## Story 22.2 — PlatformSubscription Migration to the Billing Domain

Move `PlatformSubscription` from `commerce` into the `billing` app, replace the scalar `plan` with
`plan_id`, add `current_period_start`, `cancel_at_period_end` and `cancelled_at`, and adopt the billing status enum
(`TRIALING`, `ACTIVE`, `PAST_DUE`, `EXPIRED`, `CANCELLED`).

---

## Story 22.3 — Trial Provisioning and Subscription Read

Workspace creation (Story 4.1) also creates the `PlatformSubscription` in `TRIALING` with
`trial_ends_at = start_date + 7 days`, writing `SUBSCRIPTION_CREATED` and `TRIAL_STARTED`.

```text
GET  /billing/subscription
```

Returns plan, status, current period, renewal date, trial end, amount due, InstaPay instructions and
whether a payment is under review. OWNER-only.

---

## Story 22.3b — Platform Payment Instructions

Create `PlatformPaymentInstruction` (InstaPay identifier, account name, instructions, optional QR
image, active state) and:

```text
GET   /admin/billing/payment-instructions
PATCH /admin/billing/payment-instructions
```

Platform Admin configures these; Coaches never do. No sensitive credentials stored.

---

## Story 22.4 — Manual Payment Submission

```text
POST /billing/payments
GET  /billing/payments
GET  /billing/payments/{id}/proof
```

Manual InstaPay reference plus proof upload. The backend determines amount, currency and period.
Payment statuses: `PENDING` → `SUBMITTED` → `APPROVED`, or `SUBMITTED` → `REJECTED` → `SUBMITTED`.
OWNER-only, rate-limited. No payment credentials stored.

---

## Story 22.5 — Admin Review Queue

```text
GET /admin/billing/payments
GET /admin/billing/payments/{id}
GET /admin/billing/payments/{id}/proof
```

Shows the related Workspace, Coach, plan, amount, submission time and payment history.

---

## Story 22.6 — Admin Approval and Rejection

```text
POST /admin/billing/payments/{id}/approve
POST /admin/billing/payments/{id}/reject
```

Approval is one transaction and must be idempotent: validate → approve payment → advance period →
set `ACTIVE` → `BillingEvent` → `AuditLog` → notify Coach. Retried requests must stay consistent.

**Period anchoring:** new period = previous `renewal_date` → previous `renewal_date` + 30 days.
Never anchored to the payment or approval date. Late payment grants no bonus days.

---

## Story 22.7 — Billing Events and Audit History

Create `BillingEvent` and write it on every state transition and payment decision:
`SUBSCRIPTION_CREATED`, `TRIAL_STARTED`, `PAYMENT_CREATED`, `PAYMENT_SUBMITTED`,
`PAYMENT_APPROVED`, `PAYMENT_REJECTED`, `SUBSCRIPTION_RENEWED`, `SUBSCRIPTION_PAST_DUE`,
`SUBSCRIPTION_EXPIRED`, `SUBSCRIPTION_CANCELLED`, `SUBSCRIPTION_REACTIVATED`.

Admin decisions also write `AuditLog`. `BillingEvent` is business history; `AuditLog` is
security/administrative action history. Do not duplicate responsibilities.

---

## Story 22.8 — Renewal Alerts

Coach-facing in-app alert showing plan, status, renewal date, amount due, InstaPay instructions, and
the action to submit proof. Visible from the Coach dashboard.

Notification types: `PLATFORM_SUBSCRIPTION_EXPIRING`, `PLATFORM_SUBSCRIPTION_PAST_DUE`,
`PLATFORM_SUBSCRIPTION_EXPIRED`, `PLATFORM_PAYMENT_APPROVED`, `PLATFORM_PAYMENT_REJECTED`.

### Reminder cadence (approved)

```text
7 days before renewal_date
3 days before renewal_date
1 day before renewal_date
on renewal_date
daily while PAST_DUE
```

Delivered by a scheduled Celery task. Alerts use semantic colors and never the Coach's brand color.
Timing should become configurable in a later phase.

---

## Story 22.9 — Subscription Status Transitions

Scheduled evaluation of `trial_ends_at` and `renewal_date`:

```text
TRIALING → PAST_DUE     trial_ends_at passes unpaid
ACTIVE   → PAST_DUE     renewal_date passes unpaid
PAST_DUE → EXPIRED      7-day grace period ends
```

Each transition writes a `BillingEvent`.

---

## Story 22.9b — Cancellation and Reactivation

```text
POST /billing/subscription/cancel
```

Sets `cancel_at_period_end = true`; the paid period runs out and the subscription enters `CANCELLED`
at `renewal_date`, setting `cancelled_at`. No immediate cancellation, no refunds, no proration.

Reactivation: an `EXPIRED` subscription returns to `ACTIVE` through a new approved payment, using
the same period anchoring rule (Story 22.6) and writing `SUBSCRIPTION_REACTIVATED`.

Mid-cycle plan changes are out of MVP scope; any change applies at the next renewal period.

---

## Story 22.10 — Workspace Access Enforcement

Gate Coach access by subscription status, after Workspace resolution and Membership verification:

| Status | Coach | Client Portal |
|---|---|---|
| TRIALING / ACTIVE | Normal | Accessible |
| PAST_DUE / EXPIRED / CANCELLED | Restricted | Accessible |

Restricted still allows billing, subscription information, renewal/payment actions, account settings
and logout, but not normal coaching-management functionality.

**Clients never lose portal access because of the Coach's FitOps billing state**, and Client data is
never automatically deleted or disabled.

Workspace suspension is separate and supersedes subscription status: while
`Workspace.status = SUSPENDED`, all Workspace-scoped access is denied for Coaches and Clients, and
only a Platform Admin can lift it. `SUSPENDED` is never a subscription status.

---

## Story 22.10b — Expiration Retention Window and Workspace Cleanup

Scheduled evaluation of the 30-day retention window that starts when a subscription enters
`EXPIRED`.

During the window: Coach restricted as in Story 22.10; **Client Portal remains accessible**, plans
and data remain available, nothing is deleted.

At the end of the window: clean up/deactivate the Workspace so it leaves the operational system, and
create the `WorkspaceArchive`. Cleanup must archive, never destroy. An approved payment during the
window reactivates the subscription and ends the window.

---

## Story 22.10c — Archive and Restoration Flow

Create `WorkspaceArchive` (owner, slug, name, `archived_at`, `archive_reference`,
`AVAILABLE` | `RESTORED`) and implement:

```text
GET  /workspace/archive
POST /workspace/archive/restore
```

Start Fresh reuses `POST /api/v1/workspace` and leaves the archive untouched.

Rules: never restore automatically; never resolve the archive as an active tenant or expose it
through normal application routes; audit-log restoration.

**Blocked sub-scope:** the exact scope of "the supported recovery rules" (B25) and the permanent
archive retention duration (B24) are unresolved. Do not invent either.

---

## Story 22.11 — Provider Abstraction Boundary

Keep the payment-confirmation path behind a provider boundary so a future automated provider can be
added without touching the subscription state machine. Manual InstaPay is the only implementation in
MVP. No provider-specific fields on `Plan`, `PlatformSubscription` or `BillingPayment`.

---

# 27. Dependency Graph

Core dependencies:

```text
Foundation
   ↓
Authentication
   ↓
Workspace / Multi-Tenancy
   ↓
Coach Onboarding
   ↓
Packages
   ↓
Public Portal
   ↓
Applications + Client OTP
   ↓
Orders + Payments
   ↓
Subscriptions
   ↓
Clients
   ↓
Training + Nutrition
   ↓
Assignments
   ↓
Check-ins
   ↓
Progress
   ↓
Notifications
   ↓
Dashboards
   ↓
Platform Admin
   ↓
FitOps Billing
   ↓
Security Hardening
   ↓
Production
```

---

# 28. Parallelizable Work

After Foundation is stable, some work can proceed in parallel.

```text
Authentication
        │
        ├── Workspace
        │
        └── Public Portal foundation

Packages
        │
        └── Public Package UI

Training Plans ─────┐
Nutrition Plans ────┼──→ Assignments
                    │
Check-ins ──────────┘

Admin UI can begin after core models/permissions are stable.
```

Do not parallelize work that depends on unresolved database or authentication decisions.

---

# 29. Recommended Implementation Order

This is a finer-grained implementation sequence, not a second Epic list. The 21-Epic list in §5 is
canonical; Orders and Payments are one Epic (Epic 08) even though they appear as two steps below.

Use this exact order:

```text
01 Foundation
02 Authentication
03 Workspace / Tenant Infrastructure
04 Coach Onboarding
05 Packages
06 Public Portal
07 Applications / Client OTP
08 Orders
09 Payments
10 Subscriptions
11 Client Management
12 Training Plans
13 Nutrition Plans
14 Plan Assignments
15 Check-ins
16 Progress
17 Notifications
18 Coach Dashboard
19 Client Portal
20 Platform Admin
21 FitOps Billing
22 Security Hardening
23 Production Deployment
```

---

# 30. Testing Strategy

Testing is required at three levels.

## Unit Tests

Test:

- Models
- Services
- Validators
- Permissions
- Business rules

## API Tests

Test:

- Authentication
- Authorization
- Tenant isolation
- Request validation
- Response contracts
- State transitions

## End-to-End Tests

The most important E2E flow:

```text
Coach registers
 ↓
Email verified
 ↓
2FA configured
 ↓
Workspace created
 ↓
Package created
 ↓
Public portal opened
 ↓
Client applies
 ↓
Client OTP login
 ↓
Order created
 ↓
Payment proof uploaded
 ↓
Coach approves
 ↓
Subscription created
 ↓
Client activated
 ↓
Plan assigned
 ↓
Client submits check-in
 ↓
Coach reviews
 ↓
Client sees feedback
```

---

# 31. Definition of Done — Story Level

A Story is DONE only when:

- Backend implementation is complete where required.
- Frontend implementation is complete where required.
- API contract matches the approved API specification.
- Permissions are implemented.
- Tenant isolation is verified.
- Validation exists.
- Error states are handled.
- Tests pass.
- No secrets are committed.
- No unrelated scope was added.
- Code is reviewed.
- Documentation is updated if behavior changed.
- Commit is created.

---

# 32. Definition of Done — Epic Level

An Epic is DONE when:

- All Stories are DONE.
- Integration tests pass.
- Relevant E2E flow works.
- No known critical tenant isolation issue exists.
- API and UI behavior match.
- Database migrations are stable.
- The Epic is usable by the next dependent Epic.

---

# 33. Definition of Done — MVP

The MVP is DONE when:

### Authentication

- Coach can register/login.
- Coach can use TOTP 2FA.
- Client can login via email OTP.
- Coach and Client can log out securely.

### Multi-Tenancy

- Multiple Workspaces work.
- Client can belong to multiple Workspaces.
- Client cannot see another Workspace through the current portal.
- Cross-tenant access tests pass.

### Commerce

- Packages work.
- Applications work.
- Orders work.
- Manual payment proof works.
- Approval/rejection works.
- Subscriptions work.

### Coaching

- Clients work.
- Training plans work.
- Nutrition plans work.
- Assignments work.
- Check-ins work.
- Progress works.
- Feedback works.

### Dashboards

- Coach dashboard works.
- Client portal works.
- Platform Admin works.

### FitOps Billing

- Workspace creation starts a 7-day trial.
- Coach can see plan, status, renewal date, amount due and InstaPay instructions.
- Coach can submit payment proof; Platform Admin can approve or reject.
- Approval extends the period, anchored to the previous period end, and is idempotent.
- Renewal alerts fire on the approved cadence.
- PAST_DUE, grace expiry and access restriction behave as specified.
- Client Portal access is unaffected on PAST_DUE and CANCELLED, and survives 30 days after EXPIRED.
- Workspace cleanup after the retention window archives rather than destroys data.
- A returning Coach with an archive is offered Restore Previous Data or Start Fresh, and nothing is
  restored automatically.

### Infrastructure

- Docker works.
- CI works.
- Hetzner deployment works.
- Backups work.
- File processing works.

### Security

- Tenant isolation verified.
- Authentication hardened.
- File access protected.
- Rate limiting active.
- Idempotency verified.

---

# 34. Claude Implementation Rules

When using Claude/Coding Agent:

## Rule 1

Read all approved architecture documents before modifying code.

## Rule 2

Implement only the current Story.

## Rule 3

Do not redesign existing architecture unless a blocking contradiction is discovered.

## Rule 4

Do not invent API endpoints that are not required.

## Rule 5

Do not add Phase 2 features.

## Rule 6

Never bypass tenant permissions for convenience.

## Rule 7

Never trust frontend-provided Workspace IDs, prices, roles, or state.

## Rule 8

Run relevant tests after every Story.

## Rule 9

Do not silently change database models without updating the architecture documentation.

## Rule 10

At the end of each Story, report:

```text
Implemented
Changed Files
Database Changes
API Changes
Tests
Security Checks
Known Issues
Next Recommended Story
```

---

# 35. Commit Strategy

Prefer small commits.

Examples:

```text
feat(accounts): add custom user model
feat(auth): add coach registration
feat(auth): add email verification
feat(auth): add coach login
feat(auth): add totp 2fa
feat(workspaces): add workspace model
feat(workspaces): add workspace creation endpoint
feat(workspaces): add tenant context
feat(workspaces): add payment methods
feat(coaching): add packages
feat(applications): add public application flow
feat(billing): add fitops subscription plans
feat(billing): add manual instapay payment submission
feat(orders): add manual payment flow
feat(checkins): add client check-ins
```

Avoid large commits such as:

```text
feat: build entire application
```

---

# 36. Release Milestones

## Milestone 1 — Foundation

```text
Repository
Django
Next.js
Postgres
Redis
Celery
Docker
CI
```

## Milestone 2 — Identity

```text
Coach Auth
Client OTP
2FA
Sessions
Membership
```

## Milestone 3 — Commercial Flow

```text
Workspace
Packages
Public Portal
Applications
Orders
Payments
Subscriptions
```

## Milestone 4 — Coaching Flow

```text
Clients
Training
Nutrition
Assignments
Check-ins
Progress
Feedback
```

## Milestone 5 — Product Completion

```text
Notifications
Coach Dashboard
Client Portal
Platform Admin
FitOps Billing
```

## Milestone 6 — Production

```text
Security
Backups
Monitoring
Hetzner Deployment
E2E Verification
```

---

# 37. Final Build Rule

The MVP should be built as a sequence of verified vertical slices rather than as isolated frontend/backend projects.

Preferred pattern:

```text
Database
 ↓
Backend Model
 ↓
Service / Business Logic
 ↓
API
 ↓
Backend Tests
 ↓
Frontend API Integration
 ↓
UI
 ↓
E2E Test
 ↓
Commit
```

This keeps the product functional throughout development and prevents large late-stage integration problems.

---

# 38. Final Blueprint Status

```text
MVP Scope                         LOCKED
Technology Stack                 LOCKED
Database/Auth Architecture       LOCKED
ERD / Repository Architecture    LOCKED
API Specification                LOCKED
Development Blueprint            LOCKED
```

The next implementation artifact is the **Claude Master Implementation Prompt** based on this blueprint.
