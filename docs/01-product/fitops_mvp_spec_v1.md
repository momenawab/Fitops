# FitOps — MVP Specification v1.2.1

> Version 1.2.1 adds the approved expiration retention, archive and restoration lifecycle (§19A)
> and the explicit Coach-commerce payment statuses (§8).
> Version 1.2 adds the approved **FitOps Billing** scope (§19A).
> Version 1.1 decisions remain in force and unchanged.
> The product name is **FitOps**. Earlier drafts used the working title "Coaching SaaS".

## 1. Product

A coaching management platform for coaches who already have a website.

The coach keeps their existing website and adds a link such as **Start Coaching** or **Client Login** that points to our platform.

Our platform manages what happens after that:

**Application → Payment → Client → Plans → Check-ins → Progress**

---

## 2. Users

### Coach

The workspace owner who manages:

- Clients
- Packages
- Orders
- Payments
- Plans
- Check-ins
- Subscriptions

### Client

The coach's customer who can:

- Apply
- Choose a package
- Pay
- Upload payment proof
- View plans
- Submit check-ins
- Track progress
- Receive coach feedback

### Platform Admin

The SaaS owner who can manage:

- Coaches
- Workspaces
- Platform subscriptions
- Basic platform metrics

The Platform Admin does **not** need a large admin system in Phase 1.

---

## 3. Coach Onboarding

The coach:

1. Signs up
2. Creates a workspace
3. Adds:
   - Coach name
   - Logo
   - Profile image
   - Description
   - Brand color
   - WhatsApp number
   - Currency
4. Creates the first package
5. Gets a Client Portal URL

Example:

`app.platform.com/coach-name`

---

## 4. Coach Dashboard

### Overview

Display:

- Active Clients
- New Orders
- Pending Payments
- Pending Check-ins
- Revenue
- Expiring Subscriptions

### Quick Actions

- Create Package
- Add Client
- View Orders
- Review Check-ins

---

## 5. Packages

The coach can create a package with:

- Name
- Description
- Price
- Currency
- Duration
- Features
- Status

Actions:

- Create
- Edit
- Duplicate
- Activate / Deactivate

Packages must be generic and configurable per coach.

---

## 6. Client Acquisition

Each coach gets a Client Portal URL:

`app.platform.com/coach-name`

The client can see:

- Coach profile
- Packages
- Package details
- Start Coaching CTA

---

## 7. Application

The client selects a package and submits an application.

Fields:

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

Then:

**Continue to Payment**

---

## 8. Payment

### Phase 1: Manual Payment

Payment methods are configurable per Coach/Workspace.

Supported MVP payment method types:

- InstaPay
- Vodafone Cash
- Bank Transfer
- Custom

For each payment method the Workspace can configure:

- Name
- Instructions
- Account / number details
- Optional QR code or image
- Active / inactive state

The client:

**Selects payment method → Pays → Uploads proof**

Optional:

- Payment screenshot
- Reference number

Payment statuses (authoritative enum: Database & Authentication Architecture §13):

- PENDING
- SUBMITTED
- APPROVED
- REJECTED
- CANCELLED

These are Coach Commerce statuses (Client → Coach) and are separate from FitOps billing payment
statuses (§19A).

Automated payment gateways are **not** part of Phase 1.

---

## 9. Orders

An order is automatically created.

Example:

**Order #1024**

- Client: Ahmed
- Package: Pro Coaching
- Amount: $100
- Payment: Pending

Coach actions:

- Approve
- Reject

Order statuses (authoritative enum: Database & Authentication Architecture §12):

- PENDING_PAYMENT
- PAYMENT_SUBMITTED
- APPROVED
- REJECTED
- CANCELLED

---

## 10. Client Activation

When payment is approved:

**Payment → Order Approved → Subscription Created → Client Activated → Client Portal Access**

The client can then access their coaching experience.

---

## 11. Client Dashboard

The Client Portal includes:

### Home

- Current Package
- Days Remaining
- Latest Coach Feedback
- Check-in Status
- Progress Summary

### Navigation

- Home
- My Plan
- Nutrition
- Check-in
- Progress
- Profile

The portal should feel mobile-first and app-like.

---

## 12. Training Plans

The coach can create:

- Plan name
- Duration
- Weeks
- Days
- Exercises
- Sets
- Reps
- Notes

The coach can assign a plan to a client.

In Phase 1, clients only need to view their assigned plans.

---

## 13. Nutrition Plans

Keep this simple in Phase 1.

Fields:

- Plan name
- Calories
- Meals
- Food
- Notes

The coach can assign a nutrition plan to a client.

---

## 14. Check-ins

The coach can configure a simple check-in schedule per Workspace:

- Frequency: **Weekly** or **Biweekly**
- Day of week

The schedule must remain simple in Phase 1. The design should allow future expansion
(for example per-client schedules or custom cadences) without the MVP implementing
complex scheduling.

The client submits:

- Weight
- Energy
- Sleep
- Diet adherence
- Training adherence
- Notes
- Progress photos

Then:

**Submit Check-in**

---

## 15. Coach Review

The coach has a:

**Pending Check-ins** queue.

Opening a check-in shows:

- Current weight
- Previous weight
- Answers
- Progress photos
- Client notes

The coach can:

- Write Coach Feedback
- Mark as Reviewed

The client can then see the feedback in the Client Portal.

---

## 16. Progress

### Weight

Display a simple weight history chart.

### Progress Photos

Support:

- Front
- Side
- Back

Each photo should have a date.

Both the coach and client can access relevant progress information.

---

## 17. Subscriptions

Each client subscription contains:

- Package
- Start Date
- End Date
- Status

Statuses (authoritative enum: Database & Authentication Architecture §14):

- ACTIVE
- EXPIRING
- EXPIRED
- CANCELLED

In Phase 1, renewal can be handled manually.

---

## 18. Notifications

### Coach Notifications

- New order
- Payment proof uploaded
- New check-in
- Subscription expiring

### Client Notifications

- Application approved
- Payment rejected
- Plan assigned
- Coach feedback
- Check-in reminder

Start with in-app notifications.

Email is part of Phase 1 because it is required for client OTP login, coach email
verification, and password reset. Email is sent through Django's email backend
abstraction using an SMTP provider configured through environment variables. The
specific SMTP provider does not need to be selected yet.

---

## 19. Multi-Tenancy

Multi-tenancy is mandatory from Day 1.

Each coach has an isolated workspace.

Example:

```text
Platform
├── Workspace A
│   ├── Clients
│   ├── Orders
│   ├── Packages
│   └── Plans
├── Workspace B
└── Workspace C
```

A coach must never be able to access data belonging to another workspace.

All business data must be tenant/workspace scoped.

---

## 19A. FitOps Billing (Coach → FitOps)

> **Status: APPROVED — Architecture v1.2.**
> Full rules: Database & Authentication Architecture §22–§22G.

FitOps is itself a SaaS product. Coaches/Workspaces subscribe to FitOps.

This is completely separate from §8, which covers how a Coach's own Clients pay the Coach.

| Domain | Direction | Covered in |
|---|---|---|
| Coach Commerce | Client → Coach | §7–§10, §17 |
| FitOps Billing | Coach → FitOps | this section |

### Plans

FitOps offers the plans **Starter**, **Growth** and **Pro**. Prices are configured by the Platform
Admin and are not fixed by this specification. Monthly billing is the MVP interval; annual billing
is architecturally reserved but not implemented.

The Platform Admin can create, edit, and activate/deactivate plans. A plan referenced by an existing
subscription can never be destructively deleted.

### MVP payment method

FitOps subscription payments are handled **manually through InstaPay**, in **EGP**. No payment
gateway, automated card billing, or automated recurring charge is part of this stage.

FitOps' own InstaPay details are configured by the **Platform Admin**, never by individual Coaches.

### Free trial

Every Workspace starts on a **7-day free trial**. Creating a Workspace creates the FitOps
subscription in `TRIALING`. Converting the trial needs no payment gateway.

### Initial subscription flow

```text
Coach signs up → creates Workspace → subscription starts as TRIALING (7 days)
      ↓
System shows InstaPay payment instructions
      ↓
Coach transfers the amount manually
      ↓
Coach submits payment proof / reference
      ↓
FitOps Platform Admin reviews and approves
      ↓
Workspace subscription becomes ACTIVE
```

### Renewal

Renewal is manual. The subscription has a recurring **30-day** period and a renewal date, but the
Coach pays each cycle through InstaPay. Paying late never resets the cycle — the new period is
anchored to the previous period end, so late payment creates no free extra days.

```text
Renewal date approaches → Coach receives an in-app alert
      ↓
Coach sees renewal amount and due date
      ↓
Coach pays via InstaPay → submits proof/reference
      ↓
Admin reviews and approves
      ↓
Renewal recorded, new renewal date calculated
```

### Coach renewal alert

Before the subscription expires, the Coach sees an in-app alert on the Coach dashboard containing:

- Subscription plan
- Current status
- Renewal date
- Amount due
- InstaPay payment instructions
- An action to submit payment proof

Example: *"Your FitOps subscription expires in X days."*

MVP reminder cadence: **7 days, 3 days and 1 day before renewal, on the renewal date, and daily
while PAST_DUE**. Alerts use semantic colors, never the Coach's brand color.

Only the Workspace **OWNER** can view and manage the FitOps subscription.

### Subscription states

```text
TRIALING · ACTIVE · PAST_DUE · EXPIRED · CANCELLED
```

These are FitOps billing states. They are separate from the Client coaching subscription states in
§17 and the two enums must not be merged.

### Access

`ACTIVE` and `TRIALING` grant the Coach normal access.

When the renewal date passes unpaid the subscription becomes `PAST_DUE` for a **7-day grace
period**, then `EXPIRED`.

While `PAST_DUE`, `EXPIRED` or `CANCELLED`, the Coach keeps access to billing, subscription
information, renewal/payment actions, account settings and logout, but not to normal
coaching-management functionality.

**A billing state never removes Client access immediately.** A Client's relationship is with the
Coach, not with FitOps. On `PAST_DUE` and `CANCELLED` the Client Portal stays accessible. On
`EXPIRED` the Client Portal does not become unavailable immediately — Clients keep their Portal and
their existing plans and data for **30 days**.

Cancellation is cancel-at-period-end: the paid period runs out first. There are no refunds and no
proration in MVP.

### Expiration retention and restoration

```text
EXPIRED → 30-day retention window → Workspace cleanup → archive only
```

During the 30 days after the subscription becomes `EXPIRED`:

- Coach: coaching functionality restricted; billing, subscription information, renewal/payment,
  account settings and logout remain available.
- Clients: Portal remains accessible, existing plans and data remain available, and nothing is
  deleted.

After 30 days the Workspace is cleaned up and leaves the operational system. The data is **not**
destroyed — a backup/archive is retained for potential restoration. The archive is not an active
workspace and is not reachable through normal application routes.

If a returning Coach has an archive, they are shown an explicit choice:

```text
"Previous coaching data was found."
1. Restore Previous Data
2. Start Fresh
```

Previous data is never restored automatically.

Workspace suspension is separate from billing: a Platform Admin may suspend a Workspace at any time,
and `SUSPENDED` is never a subscription status.

---

## 20. Phase 1 — Out of Scope

Do not include these in the MVP:

- Website Builder
- Custom Domains
- Merch
- Supplements
- Inventory
- AI
- WhatsApp API
- Mobile App
- Automated Payment Gateways (both for Coach Commerce and for FitOps Billing — no Stripe, Paymob, Paddle, Lemon Squeezy, automated card billing, or automated recurring charges)
- Annual FitOps billing (architecturally reserved, not implemented)
- Mid-period FitOps plan changes, upgrades, downgrades, and proration
- Team Accounts
- Advanced Analytics
- Marketing Automation
- Affiliate System
- Marketplace

These can be considered for Phase 2+.

---

## 21. MVP Core Loop

The MVP must make this flow work end-to-end:

**Coach signs up → Creates package → Gets portal link → Client applies → Selects package → Pays → Uploads proof → Coach approves → Client is activated → Coach assigns plan → Client submits check-in → Coach reviews progress**

If this flow is fast, clean, reliable, and easy to understand, we have a real MVP that can be demonstrated to coaches and used to validate willingness to pay.

---

## 22. Next Step

After approving this MVP specification, the next stage is:

**Database Schema → API Architecture → Repository Structure → Technology Stack → Development Tasks**

Only after those are defined should implementation begin.

The goal is to build a focused, multi-tenant SaaS MVP rather than a large platform with unnecessary features.
