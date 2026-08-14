# FitOps — Design System v1.2.1

> Version 1.2.1 adds the expiration-retention and restoration UI rules (§19A).
> Version 1.2 adds the approved **FitOps Billing** UI rules (§19A).
> The visual direction itself is unchanged.

## 1. Purpose

This document is the visual and UX source of truth for FitOps.

Google Stitch should use this document when generating UI designs.

Claude should use this document when implementing approved UI.

The design system must remain consistent across:

- Marketing website
- Coach dashboard
- Client portal
- Platform admin

The visual theme may change per Coach, but the underlying design language must remain consistent.

---

# 2. Product Visual Direction

FitOps should feel:

- Clean
- Premium
- Modern
- Trustworthy
- Professional
- Fitness-focused without looking like a generic gym website
- SaaS-first
- Simple and highly usable

The product should avoid:

- Overly colorful dashboards
- Heavy gradients
- Excessive glassmorphism
- Gaming/neon aesthetics
- Excessive shadows
- Excessive rounded cards
- Dense enterprise UI
- Generic template-looking layouts

Visual reference direction:

> Premium modern SaaS + modern fitness coaching brand.

---

# 3. Core Color Architecture

FitOps uses two color layers:

```text
FitOps Foundation
        +
Coach Brand Theme
```

The foundation remains stable across the product.

Coach branding changes selected accent/theme tokens.

---

# 4. Default Platform Theme — Clean Light

The default FitOps visual theme is Clean Light.

## Foundation Colors

```text
Background       #F8F9FA
Surface          #FFFFFF
Surface Muted    #F1F3F5

Text Primary     #111827
Text Secondary   #4B5563
Text Muted       #6B7280

Border           #E5E7EB
Border Strong    #D1D5DB
```

## Default Platform Accent

```text
Primary          #2563EB
Primary Hover    #1D4ED8
Primary Soft     #EFF6FF
```

The default platform accent is used for FitOps-owned UI when no Coach brand theme is active.

---

# 5. Semantic Colors

Semantic colors are stable and must not be replaced by Coach branding.

```text
Success
Base             #16A34A
Soft             #F0FDF4

Warning
Base             #D97706
Soft             #FFFBEB

Error
Base             #DC2626
Soft             #FEF2F2

Info
Base             #2563EB
Soft             #EFF6FF
```

Use semantic colors only for their intended meaning.

Do not use red/green/yellow purely as decoration.

---

# 6. Coach Theme System

Each Coach can have a brand accent.

The Coach theme affects brand-facing surfaces while the FitOps foundation remains unchanged.

### Theme Tokens

```text
--brand-primary
--brand-primary-hover
--brand-primary-soft
--brand-on-primary
--brand-border
--brand-text
```

## Initial Presets

### Blue

```text
Primary          #2563EB
Hover            #1D4ED8
Soft             #EFF6FF
```

### Purple

```text
Primary          #7C3AED
Hover            #6D28D9
Soft             #F5F3FF
```

### Orange

```text
Primary          #EA580C
Hover            #C2410C
Soft             #FFF7ED
```

### Red

```text
Primary          #DC2626
Hover            #B91C1C
Soft             #FEF2F2
```

### Gold

```text
Primary          #B58900
Hover            #8F6D00
Soft             #FFF9E6
```

### Cyan

```text
Primary          #0891B2
Hover            #0E7490
Soft             #ECFEFF
```

### Lime

```text
Primary          #65A30D
Hover            #4D7C0F
Soft             #F7FEE7
```

### Coach Theme Rules

- Keep background and text foundations stable.
- Do not recolor every component.
- Use the Coach brand primarily for CTA, active navigation, links, highlights, selected states, progress emphasis, and brand elements.
- Semantic status colors remain semantic.
- Maintain accessible contrast.
- Marketing pages may use the brand color more prominently than dashboards.
- Client portals should use the brand color for motivation and progress emphasis without becoming visually overwhelming.

---

# 7. Platform Admin Theme

Platform Admin is FitOps-owned.

It does not inherit a Coach's brand theme.

Use:

```text
Foundation: Clean Light
Accent: FitOps Blue
```

Admin UI should feel operational and professional.

---

# 8. Typography

Primary font:

```text
Inter
```

Use Inter consistently across the SaaS UI.

## Type Scale

```text
Display XL      48–56px
Display         40–48px
H1              32–40px
H2              24–32px
H3              20–24px
H4              18–20px

Body Large      18px
Body            16px
Body Small      14px

Caption         12px
```

Recommended weights:

```text
Regular         400
Medium          500
Semibold        600
Bold            700
```

Marketing pages may use larger typography and stronger weight contrast.

Dashboards should prioritize readability.

---

# 9. Spacing

Use a consistent 4px-based spacing system.

```text
4
8
12
16
20
24
32
40
48
64
80
96
```

Default component spacing should favor:

```text
8px
12px
16px
24px
32px
```

Avoid arbitrary spacing values unless required by the design.

---

# 10. Layout

## Marketing

Marketing pages should use:

- Wide content areas
- Strong visual hierarchy
- Large hero sections
- Generous whitespace
- Clear CTA hierarchy
- Real coach/client imagery where available

Recommended maximum content width:

```text
1200–1280px
```

## Dashboard

Dashboard layout:

```text
Sidebar
+
Topbar
+
Main Content
```

Recommended content width:

```text
1200–1440px
```

The UI should remain comfortable on laptop screens.

## Client Portal

Client portal should feel lighter and more personal than the Coach dashboard.

Prioritize:

1. Current program
2. Today's actions
3. Check-in status
4. Progress
5. Feedback

---

# 11. Border Radius

Use restrained rounding.

```text
Small controls       8px
Inputs               8px
Cards                12px
Large surfaces       16px
Modal                16px
```

Avoid excessive pill-shaped UI.

Pills are reserved for:

- Status badges
- Tags
- Small filters

---

# 12. Borders

Default:

```text
1px solid #E5E7EB
```

Use borders to define structure.

Do not outline every element.

---

# 13. Shadows

Use subtle shadows only when elevation is needed.

Preferred:

```text
Subtle
0 1px 2px rgba(0,0,0,0.05)

Elevated
0 8px 24px rgba(0,0,0,0.08)
```

Avoid large decorative shadows.

---

# 14. Buttons

## Primary

```text
Background: Brand Primary
Text: Brand On Primary
Radius: 8px
Height: 40–44px
```

## Secondary

```text
Background: White
Border: Border
Text: Primary Text
```

## Ghost

Use for low-priority actions.

## Destructive

Use semantic Error color.

### Button Rules

Every primary action on a screen should be visually obvious.

Avoid multiple competing primary CTAs.

---

# 15. Inputs

Inputs should be:

- Clear
- Spacious
- Accessible
- Easy to scan

Default:

```text
Height: 40–44px
Radius: 8px
Border: #E5E7EB
```

Focus:

```text
Brand-colored focus ring
```

Validation states:

```text
Success
Error
Warning
```

Always provide visible labels for important form fields.

---

# 16. Cards

Cards should provide hierarchy, not decoration.

Default:

```text
Background: White
Border: #E5E7EB
Radius: 12px
Padding: 16–24px
```

Use cards for:

- Stats
- Client summaries
- Orders
- Packages
- Check-ins
- Plan sections

Do not put every piece of information inside a separate card.

---

# 17. Tables

Tables are primarily used in Coach and Admin dashboards.

Requirements:

- Clear column hierarchy
- Compact but readable rows
- Status badges
- Search/filter controls
- Pagination where needed
- Responsive fallback on mobile

Important actions should be visible without excessive menu nesting.

---

# 18. Status Badges

Use compact badges for:

```text
Active
Pending
Approved
Rejected
Cancelled
Expired
Draft
Submitted
Reviewed
```

Semantic colors should communicate state consistently.

---

# 19. Navigation

## Coach Dashboard

Primary navigation:

```text
Overview
Clients
Orders
Payments
Packages
Training Plans
Nutrition Plans
Check-ins
Progress
Notifications
Billing
Settings
```

**Billing** is the Workspace's FitOps subscription and is visible to the Workspace OWNER only (§19A).

**Orders** is the primary commercial navigation item. **Payments** is a filtered Orders view — a
presentation of orders by payment state — not a separate backend domain. There is no separate
Payments module in the MVP.

Use icons + labels.

The active item uses the Coach brand accent.

## Client Portal

Keep navigation intentionally small:

```text
Home
My Plan
Nutrition
Check-in
Progress
Profile
```

## Platform Admin

```text
Overview
Coaches
Workspaces
Subscriptions
Plans                 # FitOps plan management
Billing Payments      # manual payment review queue
Activity
Audit Logs
Settings
```

---

# 19A. FitOps Billing UI

> **Status: APPROVED — Architecture v1.2.** See Database & Authentication Architecture §22–§22G.

Billing UI is FitOps-owned, not Coach-branded. Even inside a Coach's Workspace, the FitOps
subscription is a platform relationship: use the **FitOps Blue** accent and Clean Light foundation
rather than the Coach brand theme, so it never reads as part of the Coach's own commerce.

### Coach renewal alert

A dashboard-level banner, not a card buried in Settings. It must show plan, status, renewal date,
amount due, InstaPay instructions, and a submit-proof action.

Severity follows the semantic scale — never the Coach brand color:

```text
Approaching renewal   Info / Warning
PAST_DUE              Warning
EXPIRED               Error
```

The alert appears above dashboard content and stays dismissible-but-recurring while unresolved. Do
not use it as a permanent decorative banner in `ACTIVE` status.

### Coach billing screen

Reached from Settings. Shows the current plan, status badge, current period, renewal date, amount
due, InstaPay instructions, the payment-proof upload, and payment history with per-payment status
badges (`SUBMITTED`, `APPROVED`, `REJECTED`) plus any rejection reason.

Uses the existing file-upload pattern (§27) for proof images.

### Platform Admin review queue

A standard admin table (§17): Workspace, Coach, plan, amount, submitted date, status, with proof
preview and Approve / Reject actions. Rejection requires a reason. Follows the operational,
FitOps-owned admin styling in §7.

### Expiration retention notice

While the subscription is `EXPIRED` and inside the 30-day retention window, the Coach sees an Error
banner stating that the workspace will be removed from the operational system when the window ends,
with the remaining days and the payment action. Clients see no billing messaging at all — their
Portal keeps working normally for the whole window.

### Restoration choice

When a returning Coach has an archive, present an explicit, unambiguous choice before any workspace
is created:

```text
Previous coaching data was found.

[ Restore Previous Data ]   [ Start Fresh ]
```

Rules:

- Both options are visible and equally reachable; neither is preselected.
- Restoring is never automatic and never a side effect of another action.
- Start Fresh must not be presented as deleting the previous data.
- Use FitOps Blue, not the Coach brand theme — at this point no workspace theme exists yet.

### Status badges

Billing adds `TRIALING`, `PAST_DUE` and `EXPIRED` to the badge set in §18. These are FitOps
subscription states and must be visually distinguishable from the Client coaching subscription
states, which reuse similar words.

---

# 20. Dashboard Principles

The Coach dashboard is action-oriented.

The first screen should answer:

> What needs my attention right now?

Priority:

```text
Pending actions
↓
Orders / Payments
↓
Check-ins
↓
Clients
↓
Revenue / Metrics
↓
Recent activity
```

Do not make the dashboard an analytics wall.

---

# 21. Client Portal Principles

The Client Portal is personal, simple, and motivating.

The home screen should answer:

> What should I do today?

Prioritize:

- Current program
- Remaining subscription time
- Today's training
- Nutrition
- Check-in
- Progress
- Coach feedback

Avoid exposing administrative concepts.

---

# 22. Public Coach Website Principles

The public website is brand-first.

Typical hierarchy:

```text
Hero
↓
Coach credibility
↓
Transformations
↓
How it works
↓
Packages
↓
Testimonials
↓
CTA
```

The exact page structure can vary by Coach.

Use real Coach content and real testimonials whenever available.

Do not invent testimonials, statistics, transformations, or claims.

---

# 23. Marketing Visual Style

Marketing pages should use:

- Large typography
- Strong photography
- Clean whitespace
- Clear CTAs
- Brand accent
- Transformation-focused storytelling
- Premium but approachable composition

Do not make the marketing website look like the dashboard.

---

# 24. Imagery

Prefer:

1. Real Coach photography
2. Real client transformations
3. Real testimonials
4. Real brand assets

When content is unavailable:

- Use clearly marked placeholders during design exploration.
- Never invent social proof.
- Never fabricate client results.

Image treatment should be clean and premium.

Avoid excessive filters.

---

# 25. Icons

Use a single consistent icon family.

Preferred:

```text
Lucide
```

Icons should be simple and functional.

Avoid mixing multiple icon styles.

---

# 26. Charts

Charts should be minimal and readable.

Use Coach brand color for primary data when appropriate.

Semantic colors should remain semantic.

Charts should prioritize:

- Weight progression
- Client activity
- Revenue
- Subscription status

Avoid unnecessary decorative charts.

---

# 27. File Upload UI

File uploads are important for:

- Payment proofs
- Progress photos
- Payment method QR codes / images
- Workspace logo and coach imagery

The component should show:

```text
Upload
↓
Preview
↓
Processing
↓
Success / Error
```

For images:

- Generate optimized formats
- Show thumbnail
- Preserve original metadata only when needed
- Display upload progress where practical

---

# 28. Loading States

Prefer:

- Skeletons
- Inline spinners for actions
- Disabled button states

Avoid full-screen loaders unless the entire application must initialize.

---

# 29. Empty States

Every important list should have a useful empty state.

Example:

```text
No clients yet

Once clients join your coaching program,
they will appear here.

[ View Public Portal ]
```

Empty states should explain the next action.

---

# 30. Error States

Errors should be:

- Clear
- Human-readable
- Actionable

Avoid exposing technical errors or stack traces.

Example:

```text
Something went wrong

We couldn't load your clients.
Please try again.

[ Try Again ]
```

---

# 31. Success States

Use lightweight confirmation.

Examples:

```text
Payment proof uploaded
Client approved
Plan assigned
Check-in submitted
Changes saved
```

Prefer toast/inline confirmation over unnecessary full-page success screens.

---

# 32. Responsive Design

The product must work across:

```text
Mobile
Tablet
Laptop
Desktop
```

## Mobile

- Sidebar becomes drawer/bottom navigation where appropriate.
- Tables may become cards.
- Multi-column layouts stack.
- Primary actions remain reachable.
- Forms become single-column.

## Tablet

Maintain comfortable spacing while allowing columns to collapse when necessary.

## Desktop

Use the full dashboard layout.

Never design mobile as an afterthought.

---

# 33. Accessibility

Minimum requirements:

- WCAG-aware color contrast
- Keyboard navigation
- Visible focus states
- Proper form labels
- Semantic HTML
- Accessible buttons
- Accessible modals
- Alt text for meaningful images
- Do not rely on color alone to communicate status

---

# 34. Theme Customization

Coach customization should be token-based.

Do not create separate component implementations for each Coach.

Correct:

```text
Component
    ↓
Design Token
    ↓
Coach Theme
```

Incorrect:

```text
BergoButton
Coach2Button
Coach3Button
```

Theme changes should update the UI consistently.

---

# 35. Design Consistency Rules

Google Stitch and Claude must:

- Follow this document.
- Reuse established components.
- Reuse established spacing.
- Reuse established typography.
- Reuse established colors.
- Reuse established interaction patterns.
- Avoid introducing one-off visual patterns without reason.

If a new component is required, it should follow the existing design language.

---

# 36. Stitch Workflow

Google Stitch should receive:

```text
design.md
+
current screen prompt
```

Do not provide every future UI prompt at once.

Work in batches of three screens.

For each batch:

```text
Prompt
↓
Generate
↓
Review
↓
Refine
↓
Approve
```

Approved screens become implementation references for Claude.

---

# 37. Claude UI Implementation Rules

Claude should use:

```text
design.md
+
approved Stitch design
+
architecture documents
+
development blueprint
```

Claude must reproduce the approved design faithfully while maintaining:

- Responsive behavior
- Accessibility
- Reusable components
- Theme tokens
- Existing architecture

Do not redesign an approved screen during implementation unless explicitly requested.

---

# 38. Design Status

```text
Visual Direction       LOCKED
Base Theme             Clean Light
Coach Theme System     LOCKED
Platform Admin Theme   FitOps Blue / Clean Light
Typography             Inter
Spacing System         4px-based
Component Style        Clean / Premium / Minimal
```

The next design artifact is the first UI prompt batch:

```text
Marketing Screens 01–03
```
