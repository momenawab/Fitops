# FitOps — Technology Stack v1.2.1

> Version 1.2.1 notes the Workspace retention/archive lifecycle.
> Version 1.2 adds the approved **FitOps Billing** domain.
> Version 1.1 decisions remain in force and unchanged.
> The product name is **FitOps**. Earlier drafts used the working title "Coaching SaaS".

## Final Technology Stack

| Layer | Technology |
|---|---|
| Frontend | Next.js + TypeScript |
| UI | Tailwind CSS + shadcn/ui |
| Forms | React Hook Form + Zod |
| Server State | TanStack Query |
| Backend | Django + Django REST Framework |
| Sessions | Django built-in session framework |
| Email | Django email backend abstraction + SMTP (provider configured via environment variables) |
| Database | PostgreSQL |
| Background Jobs | Celery + Redis |
| Image Processing | Pillow → WebP + resize/compression |
| File Storage | Hetzner Volume / Local Storage |
| Reverse Proxy | Nginx |
| CDN / DNS / SSL | Cloudflare |
| Containers | Docker + Docker Compose |
| CI/CD | GitHub Actions |
| Deployment | Hetzner VPS |

---

## Architecture

```text
                    Cloudflare
                        │
                      Nginx
                        │
              ┌─────────┴─────────┐
              │                   │
          Next.js             Django API
              │                   │
              │            ┌──────┴──────┐
              │            │             │
              │        PostgreSQL      Redis
              │                          │
              │                       Celery
              │
              └────────── REST API ──────┘

                     Hetzner
                       │
                 Media Storage
                       │
              Pillow → WebP/Resize
```

---

## Frontend

### Next.js + TypeScript

Used for:

- Coach Dashboard
- Client Portal
- Public Coach Portal
- Authentication UI
- Responsive web experience

We are using Next.js instead of a plain React SPA because the product is a web-first SaaS with public pages, dashboards, routing, responsive interfaces, and future support for custom domains.

---

## UI

### Tailwind CSS + shadcn/ui

Used for the application design system and reusable UI components.

The UI should remain custom-branded and should not look like a generic SaaS template.

---

## Forms & Validation

### React Hook Form

Used for application forms, package creation, client data, check-ins, and settings.

### Zod

Used for client-side schema validation and type-safe form validation.

---

## Server State

### TanStack Query

Used for:

- API requests
- Caching
- Mutations
- Loading states
- Error handling
- Query invalidation

---

## Backend

### Django + Django REST Framework

Django will provide:

- REST API
- Authentication
- Business logic
- Multi-tenancy
- Permissions
- Orders
- Payments
- Subscriptions
- Clients
- Plans
- Check-ins
- Notifications

---

## Database

### PostgreSQL

Primary relational database.

All business-critical SaaS data will be stored here.

The database must be designed with multi-tenancy in mind from Day 1.

---

## Background Jobs

### Celery + Redis

Used for asynchronous tasks such as:

- Notifications
- Email sending
- Image processing
- Subscription reminders (Client coaching subscriptions)
- FitOps billing renewal alerts and subscription state transitions (PAST_DUE, EXPIRED)
- Workspace retention lifecycle: cleanup and archiving 30 days after a subscription becomes EXPIRED
- Check-in reminders
- Other scheduled/background operations

Redis will act as the Celery broker and can also be used for caching where appropriate.

---

## Image Processing

### Pillow

User-uploaded images such as:

- Progress photos
- Payment screenshots
- Coach images
- Workspace assets

will be processed before storage.

Recommended initial pipeline:

```text
Upload
  ↓
Validate type & size
  ↓
Resize
  ↓
Compress
  ↓
Convert to WebP
  ↓
Generate thumbnail when needed
  ↓
Store
```

Initial limits can be around:

- Maximum upload: 10 MB
- Maximum processed width: 1600 px
- Thumbnail width: 400 px
- WebP quality: approximately 80–85

These values can be adjusted during implementation/testing.

---

## File Storage

### Hetzner Volume / Local Storage

For Phase 1, media files will be stored on Hetzner rather than using S3.

The application should still use a storage abstraction so the implementation can support object storage later without rewriting business logic.

Example:

```text
StorageService
├── LocalStorage
└── S3Storage (future)
```

Automated backups are required because the server/storage volume itself is not a backup.

These operational backups are **separate** from the product-level `WorkspaceArchive` retained when
an expired Workspace is cleaned up (Database & Authentication Architecture §22H). The archive is a
restorable product artifact, not an infrastructure backup, and is never served as an active
tenant.

---

## Reverse Proxy

### Nginx

Nginx will sit in front of the application and handle:

- Routing
- Static/media serving where appropriate
- Reverse proxying
- Request handling

---

## Cloudflare

Used for:

- DNS
- SSL/TLS
- CDN
- Basic security
- Proxying the public application

---

## Containers

### Docker + Docker Compose

Services will be containerized for consistent development and deployment environments.

Expected services include:

```text
frontend
backend
postgres
redis
celery
nginx
```

---

## CI/CD

### GitHub Actions

Used for:

- Running tests
- Linting
- Building applications
- Deployment workflows
- Basic CI checks

---

## Deployment

### Hetzner VPS

Phase 1 will be deployed on Hetzner.

The infrastructure should remain simple and cost-efficient until actual usage justifies scaling.

---

## Platform Admin Panel

The SaaS will also have a separate **Platform Admin Panel** for us as the platform owners.

This is completely separate from the Coach Dashboard.

### Purpose

The Platform Admin Panel is used to operate, support, monitor, and control the SaaS itself.

### Admin Overview

Display:

- Total Coaches
- Active Coaches
- New Coaches
- Active Subscriptions
- Monthly Recurring Revenue
- Total Clients
- Orders
- Platform activity

### Coach Management

Admins can:

- View all coaches
- Search and filter coaches
- Open coach details
- View workspace information
- View subscription status
- Activate / suspend a coach
- Manage account status
- Review signup date and activity
- View basic usage metrics

### Workspace Management

Admins can:

- View workspaces
- View workspace owner
- View workspace status
- Review branding/settings
- Suspend or reactivate a workspace

### SaaS Subscriptions (FitOps Billing)

The admin panel manages the platform's own subscriptions:

- Plan
- Status
- Current period
- Renewal date
- Trial status
- Pending billing payments

Subscription statuses (authoritative enum: Database & Authentication Architecture §22B):

- TRIALING
- ACTIVE
- PAST_DUE
- EXPIRED
- CANCELLED

`SUSPENDED` is a **Workspace** state, not a subscription status, and the two must never be
conflated (§22F).

MVP FitOps subscription payments are **manual, through InstaPay, in EGP**, reviewed and approved by
a Platform Admin. No payment gateway is integrated, and the domain stays provider-agnostic so a
provider can be added later without redesigning the subscription domain.

### Support / Troubleshooting

Admins should be able to inspect enough information to troubleshoot customer issues without directly modifying business data unnecessarily.

Useful information:

- Recent activity
- Orders
- Payments
- Client count
- Subscription status
- Recent errors/events

### Admin Audit Log

Important platform-admin actions should be logged:

- Admin login
- Coach suspension/reactivation
- Subscription changes
- Workspace changes
- Other sensitive administrative actions

Each log should contain:

- Admin
- Action
- Target
- Timestamp
- Relevant metadata

### Platform Settings

Manage:

- SaaS subscription plans (create, edit, activate/deactivate; no destructive deletion of a plan
  referenced by an existing subscription)
- FitOps InstaPay payment instructions shown to Coaches
- Feature availability
- Platform configuration
- System-level settings

### Security

The Platform Admin Panel must have stricter access controls than normal Coach accounts.

Requirements:

- Separate admin role/permission layer
- Secure authentication
- Admin-only routes
- Audit logging for sensitive actions
- Never expose platform-wide data through Coach APIs

The Platform Admin must be completely isolated from normal tenant/workspace permissions.

---

## Application Structure

The platform will therefore have three main experiences:

```text
                    SaaS Platform
                         │
          ┌──────────────┼──────────────┐
          │              │              │
    Platform Admin     Coach          Client
       Panel         Dashboard        Portal
          │              │              │
     All Coaches      Own Workspace   Own Data
     All Workspaces   Own Clients     Own Account
     SaaS Billing     Orders          Plans
     Platform Data    Check-ins       Progress
```

The Platform Admin operates the SaaS globally, while Coaches remain isolated to their own workspaces and Clients remain isolated to their own accounts.

---

## Authentication Decision

Authentication is locked for Phase 1.

### Authentication Strategy

The platform will use **Django's built-in session framework** with secure HttpOnly session cookies.

A custom `UserSession` / `token_hash` system is **not** implemented in Phase 1.

Requirements:

- Django session framework (database-backed session store)
- Secure HttpOnly cookies
- Secure flag in production
- Appropriate SameSite configuration
- CSRF protection for state-changing requests
- Secure logout that terminates the current session
- Authentication rate limiting

Per-session management (session listing, per-session revocation) is not part of the MVP.
"Log out everywhere" may be introduced as a future feature.

### Coach Authentication

- Email + password
- Email verification
- Optional TOTP 2FA
- Secure authenticated session

### Client Authentication

- Email + one-time login code (OTP)
- No password required
- Secure authenticated session after OTP verification

### Platform Admin Authentication

- Authenticated User
- `platform_role = ADMIN`
- Separate platform-level permissions
- Admin-only routes
- Audit logging for sensitive actions

### JWT

JWT is not required for Phase 1.

---

## Email

Email uses **Django's email backend abstraction with an SMTP provider**.

Rules:

- Configure the SMTP host, port, credentials, TLS/SSL settings, and default from-address
  entirely through environment variables.
- The specific SMTP provider does not need to be selected yet and can be changed without
  code changes.
- Application code must send mail through Django's email API, never through a
  provider-specific SDK.

Required use cases:

- Client OTP login codes
- Account verification
- Password reset
- Notifications
- Subscription/check-in reminders

---

## Stack Status

### Locked

- Next.js
- TypeScript
- Tailwind CSS
- shadcn/ui
- React Hook Form
- Zod
- TanStack Query
- Django
- Django REST Framework
- Django built-in session framework
- Django email backend + SMTP (provider set via environment variables)
- PostgreSQL
- Celery
- Redis
- Pillow
- Hetzner storage
- Nginx
- Cloudflare
- Docker
- Docker Compose
- GitHub Actions
- Hetzner VPS

### Still To Decide

- The specific SMTP provider (deployment configuration only)

The SMTP provider is selected through environment variables at deployment time and does not
change the architecture or any application code.

---

## Next Step

The next stage is:

**Database Schema + Multi-Tenancy Architecture**

We need to define:

- Core models
- Relationships
- Tenant/workspace isolation
- User roles
- Permissions
- Data ownership
- Authentication boundaries
- File ownership
- API boundaries

The database and tenant architecture should be finalized before implementation begins.
