# FitOps — ERD, Django Apps & Repository Architecture v1.2.1

> Version 1.2.1 adds `WorkspaceArchive` to the `workspaces` app for the approved retention and
> restoration lifecycle.
> Version 1.2 adds the approved **FitOps Billing** domain and the `billing` app (§20A).
> Version 1.1 decisions remain in force and unchanged.
> The product name is **FitOps**. Earlier drafts used the working title "Coaching SaaS".

## 1. Final Architecture

The core architectural decision is:

> **User is global. Workspace is the tenant. Membership connects Users to Workspaces.**

A Client can belong to multiple Workspaces, but each coaching relationship remains isolated by Workspace.

```text
                         User
                          │
             ┌────────────┼────────────┐
             │            │            │
       CoachProfile   ClientProfile   Platform Admin
             │            │
             │            │
             └──────┬─────┘
                    │
               Membership
                    │
                    ▼
                Workspace
                    │
       ┌────────────┼─────────────┐
       │            │             │
   Packages       Clients       Orders
                                  │
                              Payments
                                  │
                           Subscriptions
```

---

## 2. Global Client Architecture

A Client is a global User and can have relationships with multiple Coaches/Workspaces.

```text
User
 │
 └── ClientProfile
       │
       ├── Membership → Workspace A
       ├── Membership → Workspace B
       └── Membership → Workspace C
```

The Client does not see all memberships in the UI.

The active Workspace is determined by the URL slug and resolved server-side.

Example:

```text
app.platform.com/bergo
        ↓
Bergo Workspace
        ↓
ClientMembership check
        ↓
Bergo Client Portal
```

A Client who also belongs to another Workspace will not see that Workspace inside the Bergo Portal.

---

# 1. Core ERD

```text
┌──────────────────────┐
│        User          │
├──────────────────────┤
│ id PK                │
│ email UNIQUE         │
│ password_hash        │
│ first_name           │
│ last_name            │
│ phone                │
│ is_active             │
│ email_verified_at    │
│ platform_role        │
│ created_at           │
│ updated_at           │
└──────────┬───────────┘
           │
     ┌─────┴───────────────┐
     │                     │
     ▼                     ▼
┌──────────────┐    ┌──────────────┐
│CoachProfile  │    │ClientProfile │
├──────────────┤    ├──────────────┤
│id            │    │id            │
│user_id FK    │    │user_id FK    │
│bio           │    │DOB           │
│image         │    │gender        │
│website       │    │height        │
│instagram     │    │weight        │
└──────────────┘    │goal          │
                    └──────┬───────┘
                           │
                           ▼
                   ┌─────────────────┐
                   │   Membership    │
                   ├─────────────────┤
                   │id PK            │
                   │user_id FK       │
                   │workspace_id FK  │
                   │role             │
                   │status           │
                   │joined_at        │
                   │created_at       │
                   │updated_at       │
                   └────────┬────────┘
                            │
                            ▼
                   ┌─────────────────┐
                   │    Workspace    │
                   ├─────────────────┤
                   │id PK            │
                   │name             │
                   │slug UNIQUE      │
                   │logo             │
                   │description      │
                   │brand_color      │
                   │currency         │
                   │timezone         │
                   │status           │
                   └────────┬────────┘
                            │
            ┌───────────────┼────────────────┐
            │               │                │
            ▼               ▼                ▼
       ┌─────────┐     ┌─────────┐      ┌─────────────┐
       │ Package │     │  Order  │      │TrainingPlan │
       └─────────┘     └────┬────┘      └─────────────┘
                            │
                            ▼
                       ┌──────────┐
                       │ Payment  │
                       └────┬─────┘
                            │
                            ▼
                      Subscription
```

---

# 2. Workspace Membership

Membership is the main relationship between Users and Workspaces.

```text
Membership
----------------
id
user_id
workspace_id
role
status
joined_at
created_at
updated_at
```

Roles:

```text
OWNER
COACH
CLIENT
```

Future role:

```text
ASSISTANT_COACH
```

### Constraint

```text
UNIQUE(user_id, workspace_id)
```

A User cannot have duplicate memberships in the same Workspace.

---

# 3. Workspace

```text
Workspace
----------------
id
name
slug
logo
profile_image
description
brand_color
currency
timezone
whatsapp_number
status
created_at
updated_at
```

Example:

```text
name: Bergo Coaching
slug: bergo
```

Portal:

```text
app.platform.com/bergo
```

---

# 4. Client Architecture

## ClientProfile

Client identity is global.

```text
ClientProfile
----------------
id
user_id
date_of_birth
gender
height
current_weight
goal
training_experience
notes
created_at
updated_at

# IMPORTANT:
# ClientProfile is global and MUST NOT contain workspace_id.
# Workspace relationships are represented by Membership.
```

The relationship with a Coach is represented through Workspace Membership.

Example:

```text
Ahmed
 │
 └── ClientProfile
       │
       ├── Bergo Membership
       └── Coach B Membership
```

All coaching business data is still Workspace-scoped.

## Tenant-Scoped Identity References

Because `User` and `ClientProfile` are global, a global reference alone would lose Workspace context
on a Workspace-scoped record.

- `client_id` on Workspace-scoped business records is a foreign key to **`Membership`**
  (`role = CLIENT`).
- `coach_id` (for example on `CoachFeedback`) is a foreign key to **`Membership`**
  (`role` in `OWNER`, `COACH`).
- These records still carry an explicit `workspace_id`, which must match `Membership.workspace_id`.
- Global identity data is read through `Membership → User → ClientProfile` and never duplicated onto
  Workspace-scoped records.
- `Application` is the exception and references the global `User` through a nullable `user_id`
  (see §6).

See Database & Authentication Architecture §10 for the authoritative rule.

---

# 5. Orders

```text
Order
----------------
id
workspace_id
client_id
package_id
order_number
amount
currency
status
created_at
updated_at
```

The Client is global, but the Order belongs to a Workspace.

Example:

```text
Ahmed
 ├── Order #100 → Bergo
 └── Order #200 → Coach B
```

---

# 6. Client Applications

Applications represent the public onboarding request before the coaching relationship is fully activated.

Applications live in the dedicated `applications` Django app (see §19A).

```text
Application
----------------
id
workspace_id
package_id
user_id            # NULLABLE
status
full_name
email
phone
age
gender
height
weight
goal
training_experience
notes
created_at
updated_at
```

Recommended lifecycle:

```text
SUBMITTED
   ↓
REVIEWING
   ↓
APPROVED / REJECTED
```

The application belongs to the Workspace identified by the public URL slug.

`user_id` is **nullable**: a public application may originate from an anonymous visitor, so an
authenticated User is not required at application creation time.

Submitting an application creates the **initial Order** in the same flow. The Application and its
initial Order must be created consistently and safely in one transaction:

```text
Application (SUBMITTED)
      ↓
Find/Create User
      ↓
Find/Create ClientProfile
      ↓
Create Membership(role=CLIENT) if missing
      ↓
Associate Application.user_id
      ↓
Create initial Order
```

The same global User may already have a Membership in another Workspace; that does not expose the other Workspace to the Client.

Subsequent purchases by an authenticated Client use `POST /orders` instead of the application flow.

---

# 7. Payments

```text
Payment
----------------
id
workspace_id
order_id
method
amount
currency
reference
proof_file
status
paid_at
created_at
```

Payments are associated with Orders and therefore with the corresponding Workspace.

---

# 8. Client Subscriptions

Client coaching subscription:

```text
Subscription
----------------
id
workspace_id
client_id
package_id
order_id
start_date
end_date
status
created_at
updated_at
```

This is separate from the Coach's SaaS subscription.

## Platform Subscription

The Workspace's subscription to FitOps — a **separate domain** from the Client coaching
`Subscription` above.

```text
PlatformSubscription
----------------
id
workspace_id
plan_id                 # FK → Plan (replaces the v1.1 scalar `plan`)
status                  # TRIALING | ACTIVE | PAST_DUE | EXPIRED | CANCELLED
start_date
current_period_start
renewal_date
trial_ends_at
cancel_at_period_end
cancelled_at
created_at
updated_at
```

Full billing domain — `Plan`, `PlatformPaymentInstruction`, `BillingPayment`, `BillingEvent`,
lifecycle and access rules — is in Database & Authentication Architecture §22–§22G, and the app
that owns it is §20A below.

---

# 9. Coaching Structure

## Training

```text
TrainingPlan
      │
      ├── TrainingWeek
      │       │
      │       └── TrainingDay
      │               │
      │               └── Exercise
```

Models:

```text
TrainingPlan
TrainingWeek
TrainingDay
Exercise
```

All are Workspace-scoped.

## Nutrition

```text
NutritionPlan
      │
      └── NutritionMeal
```

Models:

```text
NutritionPlan
NutritionMeal
```

All are Workspace-scoped.

---

# 10. Plan Assignment

```text
PlanAssignment
----------------
id
workspace_id
client_id
training_plan_id
nutrition_plan_id
start_date
end_date
status
created_at
```

Plan history is preserved.

Example:

```text
Ahmed
│
├── Plan A
│   Jan → Mar
│
├── Plan B
│   Apr → Jun
│
└── Plan C
    Jul → Sep
```

---

# 11. Check-ins

```text
CheckIn
----------------
id
workspace_id
client_id
weight
energy
sleep
diet_adherence
training_adherence
notes
status
submitted_at
reviewed_at
created_at
```

Progress photos:

```text
ProgressPhoto
----------------
id
workspace_id
client_id
check_in_id
photo_type
file_path
thumbnail_path
created_at
```

---

# 12. Coach Feedback

```text
CoachFeedback
----------------
id
workspace_id
client_id
check_in_id
coach_id
content
created_at
```

Feedback belongs to a specific Client, Check-in, Coach, and Workspace.

---

# 13. Authentication Models

```text
User
 │
 ├── CoachSecurity
 └── LoginOTP
```

Sessions use Django's built-in session framework. There is no custom `UserSession` model in
Phase 1.

## CoachSecurity

```text
CoachSecurity
----------------
id
user_id
two_factor_enabled
two_factor_secret
created_at
updated_at
```

## LoginOTP

```text
LoginOTP
----------------
id
user_id
email
code_hash
expires_at
attempts
used_at
created_at
```

## Sessions

Django's built-in session framework, database-backed session store, secure HttpOnly cookies,
CSRF protection, and logout/revocation behavior. No application-level session model.

---

# 14. Notifications

```text
Notification
----------------
id
workspace_id
user_id
type
title
message
is_read
created_at
```

A notification for a Client inside Bergo is scoped to:

```text
workspace_id = BERGO
user_id = CLIENT
```

This keeps notifications isolated between Workspaces.

---

# 15. Django Apps

The backend is divided by business domains rather than creating one Django app per model.

```text
backend/
│
├── config/
│
├── apps/
│   ├── accounts/
│   ├── workspaces/
│   ├── coaching/
│   ├── clients/
│   ├── applications/
│   ├── commerce/
│   ├── billing/            # FitOps subscription billing (Coach → FitOps)
│   ├── notifications/
│   └── audit/
│
├── common/
│
└── manage.py
```

---

# 16. `accounts`

Responsible for identity and authentication.

Models:

```text
User
CoachProfile
ClientProfile
CoachSecurity
Membership
LoginOTP
```

Sessions are provided by Django's session framework, not by a model in this app.

Responsibilities:

- Registration
- Login
- Logout
- Email verification
- Password reset
- Client OTP
- 2FA
- Sessions
- Roles
- Memberships

---

# 17. `workspaces`

Responsible for:

```text
Workspace
WorkspaceArchive
PaymentMethod
CheckInSchedule
Workspace settings
Branding
```

Responsibilities:

- Workspace creation (including the OWNER Membership for the creator)
- Workspace settings
- Branding
- Public portal configuration
- Payment methods
- Check-in schedule configuration
- Workspace cleanup, archiving and restoration (retention lifecycle)

## WorkspaceArchive

```text
WorkspaceArchive
----------------
id
owner_user_id
workspace_slug
workspace_name
archived_at
archive_reference
status              # AVAILABLE | RESTORED
created_at
updated_at
```

Created when a Workspace is cleaned up after 30 days in `EXPIRED`. It is **not an active tenant**,
is never resolved from a slug, and is never reachable through normal application routes. It exists
only so a returning Coach can be offered **Restore Previous Data** or **Start Fresh**.

Full rules: Database & Authentication Architecture §22H.

## PaymentMethod

```text
PaymentMethod
----------------
id
workspace_id
type              # INSTAPAY | VODAFONE_CASH | BANK_TRANSFER | CUSTOM
name
instructions
account_details
image             # optional QR code / image
is_active
created_at
updated_at
```

## CheckInSchedule

```text
CheckInSchedule
----------------
id
workspace_id
frequency         # WEEKLY | BIWEEKLY
day_of_week
created_at
updated_at
```

Both are Workspace-scoped. See Database & Authentication Architecture §13A and §18A.

---

# 18. `coaching`

Responsible for the core coaching domain:

```text
Package

TrainingPlan
TrainingWeek
TrainingDay
Exercise

NutritionPlan
NutritionMeal

PlanAssignment

CheckIn
ProgressPhoto
CoachFeedback
```

---

# 19. `clients`

Responsible for Client-facing business operations:

- Client portal
- Client dashboard
- Client activity
- Client-specific access

`ClientProfile` remains in `accounts` because it is part of identity.

---

# 19A. `applications`

Dedicated business-domain app for the public onboarding funnel.

Models:

```text
Application
```

Responsibilities:

- Public applications
- Application lifecycle
- Application status
- Application → initial Order flow
- Application → Client conversion (User / ClientProfile / Membership)

Boundaries:

- The `clients` app remains responsible for Client-facing business operations.
- `ClientProfile` remains in `accounts` because it is identity.
- `Order` remains in `commerce`; the `applications` app invokes the Order creation flow rather than
  owning the Order model.

---

# 20. `commerce`

Responsible for Client → Coach commerce only:

```text
Order
Payment
Subscription
```

Responsibilities:

- Orders
- Payment proofs
- Manual payments
- Payment approval
- Client subscriptions
- Renewals
- Client commercial state

`PlatformSubscription` moves to the `billing` app (§20A). FitOps subscription billing
(Coach → FitOps) is a separate domain and must not share models with Client → Coach commerce.

---

# 20A. `billing`

> **Status: APPROVED — Architecture v1.2.** See Database & Authentication Architecture §22–§22G
> for models, lifecycle, access rules and the approved decision record.

Dedicated business-domain app for **FitOps Billing** (Coach → FitOps).

Models:

```text
Plan
PlatformPaymentInstruction
PlatformSubscription      # moved here from `commerce`
BillingPayment
BillingEvent
```

Responsibilities:

- FitOps subscription plan catalogue
- Workspace subscription state and billing periods
- Manual InstaPay payment submission and proof handling
- Platform Admin approval / rejection
- Manual renewal and period extension
- Billing history and audit events
- Provider-agnostic payment boundary

Boundaries:

- `commerce` keeps Client → Coach commerce (`Order`, `Payment`, `Subscription`) and **loses**
  `PlatformSubscription` to this app.
- The Coach's client-facing `Order` model is never reused for FitOps billing.
- The Coach's `PaymentMethod` (in `workspaces`) describes how the Coach's Clients pay the Coach and
  is unrelated to how the Coach pays FitOps.
- `notifications` delivers the Coach renewal alerts; `billing` raises them.
- `audit` keeps `AuditLog` for admin actions; `BillingEvent` stays here as billing state history.

`backend/apps/billing/` is the canonical home of FitOps subscription billing. Billing
responsibilities stay separate from `commerce`, `clients`, `accounts` and `workspaces`.

---

# 21. `notifications`

Responsible for:

```text
Notification
```

Future possibilities:

```text
EmailNotification
PushNotification
```

Phase 1 focuses on in-app notifications and required email notifications.

---

# 22. `audit`

Responsible for:

```text
AuditLog
```

Used for:

- Platform Admin actions
- Sensitive Coach actions
- Security events
- Commercial state changes

---

# 23. `common`

Contains shared infrastructure rather than business models.

```text
common/
├── models/
├── permissions/
├── exceptions/
├── pagination/
├── storage/
├── utils/
└── middleware/
```

Important shared components:

```text
WorkspaceScopedModel
WorkspacePermission
TenantQuerySet
WorkspaceMiddleware / Context
```

---

# 24. Repository Structure

Use a Monorepo. The repository is named after the product: **fitops**.

```text
fitops/
│
├── frontend/
│   ├── app/
│   ├── components/
│   ├── features/
│   ├── lib/
│   ├── hooks/
│   ├── types/
│   └── ...
│
├── backend/
│   ├── config/
│   ├── apps/
│   │   ├── accounts/
│   │   ├── workspaces/
│   │   ├── coaching/
│   │   ├── clients/
│   │   ├── applications/
│   │   ├── commerce/
│   │   ├── billing/
│   │   ├── notifications/
│   │   └── audit/
│   │
│   ├── common/
│   ├── tests/
│   └── manage.py
│
├── infrastructure/
│   ├── docker/
│   ├── nginx/
│   ├── scripts/
│   └── backups/
│
├── docs/
│   ├── 01-product/
│   ├── 02-architecture/
│   ├── 03-development/
│   └── 04-design/
│
├── docker-compose.yml
├── .env.example
├── .gitignore
└── README.md
```

---

# 25. Frontend Structure

The Next.js frontend is organized around product experiences.

```text
frontend/
│
├── app/
│   ├── (marketing)/
│   ├── auth/                  # coach registration / login / password reset (no workspace yet)
│   ├── onboarding/            # create first workspace
│   ├── admin/                 # platform admin (never workspace-scoped)
│   │
│   └── [workspaceSlug]/
│       ├── page.tsx           # public coach portal
│       ├── login/             # client OTP login
│       ├── apply/             # public application
│       ├── portal/            # client portal
│       │
│       ├── dashboard/         # coach dashboard
│       ├── clients/
│       ├── orders/
│       ├── check-ins/
│       ├── plans/
│       ├── billing/           # FitOps subscription billing (OWNER only)
│       └── settings/
│
├── components/
├── features/
├── lib/
├── hooks/
└── types/
```

Coach dashboard routes are Workspace-scoped and carry the Workspace slug. The slug — never a
frontend-supplied `workspace_id` — is the authoritative Workspace context.

---

# 26. URL-Based Workspace Context

The public portal, the Client portal, and the Coach dashboard all use the Workspace slug.

Examples:

```text
app.platform.com/bergo                 # public coach portal
app.platform.com/bergo/portal          # client portal
app.platform.com/bergo/dashboard       # coach dashboard
app.platform.com/bergo/clients
app.platform.com/bergo/orders
app.platform.com/bergo/check-ins
```

Routes that exist before or outside any Workspace — coach authentication, first-Workspace
onboarding, and the Platform Admin panel — are not slug-scoped.

Next.js extracts:

```text
workspaceSlug = "bergo"
```

The backend resolves:

```text
slug
 ↓
Workspace
 ↓
Authenticated User
 ↓
Membership
 ↓
Access
```

The frontend does not provide or choose the authoritative `workspace_id`.

The backend resolves the URL slug to a Workspace and validates the authenticated User's Membership before establishing Workspace context.

---

# 27. Tenant Security Architecture

Every request should follow:

```text
Request
  ↓
Authentication
  ↓
User
  ↓
Workspace Context
  ↓
Membership Check
  ↓
Tenant Query
  ↓
Object Ownership
  ↓
Response
```

### Coach

```text
Coach
 ↓
Membership
 ↓
Workspace
 ↓
Order.workspace_id
```

### Client

```text
Client
 ↓
Membership
 ↓
Workspace from URL
 ↓
ClientProfile
 ↓
Order.workspace_id
 ↓
Order.client_id
```

Both Workspace membership and resource ownership must be validated.

---

# 28. Final Data Ownership Rule

The following business models must be Workspace-scoped:

```text
Package
Application
PaymentMethod
CheckInSchedule
Order
Payment
Subscription
TrainingPlan
NutritionPlan
PlanAssignment
CheckIn
ProgressPhoto
CoachFeedback
Notification
PlatformSubscription
BillingPayment
BillingEvent
```

`Plan` and `PlatformPaymentInstruction` are the deliberate exceptions: they are platform-owned
FitOps billing configuration and are not Workspace-scoped.

`WorkspaceArchive` is also outside tenant scoping by design: it references an archived Workspace
that no longer exists operationally, and must never be resolved as a tenant.

Each should have an explicit:

```text
workspace_id
```

even when the Workspace could technically be inferred through another relationship.

Reasons:

- Explicit tenant scoping
- Simpler queries
- Stronger security
- Easier indexing
- Easier auditing

---

# 29. Membership Constraints

Membership supports:

```text
OWNER
COACH
CLIENT
```

Future:

```text
ASSISTANT_COACH
```

The same User can have different memberships in different Workspaces.

Example:

```text
User A
 ├── Workspace 1 → OWNER
 ├── Workspace 2 → COACH
 └── Workspace 3 → CLIENT
```

This allows the identity system to remain global while permissions remain Workspace-scoped.

---

# 30. Final Architecture

```text
                         PLATFORM
                            │
                     Platform Admin
                            │
                            ▼
                       WORKSPACES
                            │
          ┌─────────────────┼─────────────────┐
          │                 │                 │
      Workspace A       Workspace B       Workspace C
          │                 │                 │
       Members           Members           Members
          │
     ┌────┴────┐
     │         │
  Coaches   Clients
              │
        ClientProfile
              │
       ClientMembership
              │
        ┌─────┴─────┐
        │           │
      Orders      Plans
        │           │
    Payments    Assignments
        │           │
  Subscriptions Check-ins
                    │
               Progress
```

---

# 31. Architecture Decisions Locked

The following decisions are considered locked for Phase 1:

- Global User identity
- Multi-Workspace support
- Workspace as the tenant boundary
- Membership-based Workspace access
- Client can belong to multiple Workspaces
- URL-defined active Workspace context
- Client does not see other memberships in the portal
- Workspace-scoped business data
- Explicit `workspace_id` on business models
- Separate Platform Admin role
- Django domain-based app structure
- Next.js frontend Monorepo
- Shared common tenant/security utilities

### Added in v1.1

- Coach dashboard routes are Workspace-slug-scoped (`/{workspaceSlug}/dashboard`, …)
- `POST /api/v1/workspace` creates the first Workspace and the OWNER Membership
- Dedicated `applications` Django app
- `Application.user_id` is nullable; the application flow creates the initial Order
- `PaymentMethod` and `CheckInSchedule` are Workspace-scoped models in `workspaces`
- `Membership.joined_at` is part of the authoritative schema
- Workspace-scoped business records reference Client/Coach through `Membership`
- Django session framework; no custom `UserSession` model
- Repository documentation lives in `docs/01-product`, `docs/02-architecture`,
  `docs/03-development`, `docs/04-design`

---

# 32. Next Step

The next phase is the **Development Blueprint**:

```text
MVP
 ↓
Epics
 ↓
User Stories
 ↓
Technical Tasks
 ↓
Dependencies
 ↓
Definition of Done
 ↓
Implementation Order
```

The goal is to turn the architecture into a practical build plan that Claude can implement incrementally without inventing architecture or business logic.

---

## Architecture Corrections — Multi-Workspace Baseline

The following corrections are authoritative for Phase 1:

- `User` is global.
- `ClientProfile` is global and has no `workspace_id`.
- `Membership` connects Users to Workspaces.
- A Client may have Memberships in multiple Workspaces.
- A Client Portal never exposes the Client's other memberships.
- The active Workspace is determined by the URL slug, for the Coach dashboard as well as the public
  and Client portals.
- The backend resolves the slug and validates Membership before setting tenant context.
- The frontend must never be trusted to provide the authoritative `workspace_id`.
- Business/coaching records remain explicitly Workspace-scoped.
- `Application` is a first-class onboarding/business record, owned by the `applications` app.
- Client coaching `Subscription` and SaaS `PlatformSubscription` are separate concepts.
- Authentication uses Django's session framework with secure HttpOnly session cookies for Phase 1.
- JWT is not required for Phase 1.
