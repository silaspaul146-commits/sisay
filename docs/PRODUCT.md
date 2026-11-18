# What we are building

One-page summary of the eight specification documents in [source/](source/): Vision, PRD, SRS, Use Cases,
Domain Model, Engineering pack, API Contract and Physical DB spec. The Word documents remain the
authority; [DECISIONS.md](DECISIONS.md) records where the code had to choose between them.

## In one sentence

A community safety platform for crisis-affected areas. People report incidents anonymously, even offline.
The platform groups those reports into incidents, shows them on a privacy-safe public map, warns people
nearby, and gives approved NGOs governed intelligence. It never pretends to know more than it does.

**Pilot:** selected communities in Cameroon's **North-West and South-West regions**.

## The problem

In crises, people rely on WhatsApp groups, calls and word of mouth. That information is late,
duplicated, contradictory, hard to verify and not tied to a map. People know *something* happened,
but not whether it affects their street, where they are going, or the road in between. NGOs face the
same gap when they plan operations.

## Who it is for

| Who | What they need | What they get |
|---|---|---|
| **Citizens** (the main users) | Report fast, without an account, under stress and with poor signal. Know what is happening around places that matter. | A report flow taking seconds (only category and location are required), an offline queue, a public map, route checks and alerts. |
| **Reviewers / moderators** | Decide what is credible and keep the record correct. | Review queues, all linked reports, verify/dispute/correct/merge, and full history. |
| **NGO analysts** | Patterns and impact for planning. | Trends by area, time and category, with clear data-quality labels and governed exports. |
| **Organization admins** | Manage their own staff's access. | Invitations, roles and revocation, scoped to their organization. |
| **Platform admins** | Run the platform safely. | Access control, categories, audit logs and processing health. |

## The four parts

### 1. Citizen mobile app (Flutter, Android first)
Three main actions: **Report**, **Map** and **Alerts**.
- **Report:** pick a category, confirm the location (GPS or tap on the map), and optionally add a
  description or photo. No account is needed. It works **offline**: the report is saved on the phone,
  survives restarts and is sent automatically when signal returns, without ever creating a duplicate.
  The app shows the report as *saved on phone*, *sending*, *sent* or *needs attention*. Sent does not
  mean verified.
- **Map:** opens on the user's location if allowed, or anywhere by search or panning. It shows
  incidents, including unconfirmed ones, labelled clearly, at approximate locations, with how fresh
  they are. Filters cover category, date and status.
- **Route check:** enter where you are going and see incidents near the route. It **never says a route
  is safe**.
- **Alerts:** save places and routes and get warnings when something happens nearby. There is an
  in-app alert history as well as push notifications.
- **Follow-up:** add another observation, propose a correction or dispute an incident.

### 2. Reviewer dashboard (Next.js website)
A sign-in-only workspace: an incident list and map at exact locations, an incident page (reports,
timeline, evidence), and verify / dispute / set severity / resolve / correct / merge / split. A review
queue holds the cases the system was unsure about. Every decision has a reason and is recorded.

### 3. Alerts engine (server)
- Alerts start **localized** (people near the incident) and expand to **wider** and then **broad**
  distribution only when confidence, severity or impact justifies it. They never expand just because
  more reports arrived, since copied reports are not independent.
- Unconfirmed alerts say so clearly.
- Alerts are deduplicated, updated, withdrawn and expired. Delivery attempts are tracked, and "Firebase
  accepted it" is not treated as "the person saw it".

### 4. Organizations and humanitarian intelligence
NGOs apply, a platform admin approves them, and their admin invites members with roles. Approved
members see trends and maps and can export with provenance. Humanitarian *impact* (people displaced,
facilities damaged…) is kept separate from incidents and labelled **reported / estimated / confirmed**.

## Rules that apply everywhere

1. **Anonymous by default.** Identity is never required to report.
2. **Only category and location are mandatory.**
3. **Report ≠ Incident ≠ Alert.** A report is one person's observation; an incident is the event; an
   alert is a warning. They are never mixed up.
4. **Be honest about uncertainty.** Statuses go reported → under review → corroborated → verified, plus
   disputed. Verification is separate from whether the event is still happening (active / monitoring /
   resolved). Severity, confidence and freshness are rated separately.
5. **No reports ≠ safe.** The platform never says or implies an area or route is safe.
6. **Protect people.** Reporter identity, exact reporter GPS, raw photos and tactical details are never
   public. Missing persons and children get stricter rules. Photo metadata (EXIF) is stripped.
7. **Report count is not proof.** Ten copies of one rumour are not ten witnesses.
8. **Never silently delete or overwrite.** Original reports, corrections and decisions stay traceable.
9. **Keep three times.** When it happened, when the phone created the report, and when the server got
   it. A report synced late must not look new.
10. **Out of scope:** guaranteeing safety, emergency dispatch or rescue, tracking people in the
    background, automatic "verified" decisions, predicting violence, and tactical military information.

## Releases (from the PRD)

| Release | Contents |
|---|---|
| **Pilot / MVP** | Anonymous reporting, offline queue, public map, area search, incident details, **reviewer dashboard**, incident grouping, **localized alerts**, audit. |
| **Release 1** | Route checks, saved routes, citizen corrections/disputes, organization onboarding and roles, basic NGO analytics. |
| **Later** | Advanced impact analysis, richer exports, more regions and categories, integrations. |

## Where we are (2026-11-18)

The **server engine for the core flow is live** at https://sisay.onrender.com. There are **no
screens yet**.

| Area | Server | App / dashboard |
|---|---|---|
| Anonymous reporting, duplicate-safe retries, status code for the reporter | ✅ Live | ❌ Mobile app not started |
| Grouping reports into incidents (conservative; unsure cases go to review) | ✅ Live | — |
| Public map data (sanitized, blurred locations, GeoJSON) | ✅ Live | ❌ |
| Staff sign-in (Auth0), verify, assess, associate, merge, review queue, history | ✅ Live | ❌ Dashboard not started |
| Operational status (resolve/monitor), corrections, unlink report, split incident | ❌ | ❌ |
| Photos / evidence | ❌ Needs a storage provider | ❌ |
| Alerts, saved places/routes, push notifications | ❌ | ❌ |
| Route checks | ❌ | ❌ |
| Organizations, NGO intelligence, exports | ❌ | ❌ |
| Admin (categories, audit search, processing health) | ❌ | ❌ |

Engineering roadmap ([Engineering pack §12](source/)): phases 0–5 are done and phase 6 (review and
audit) is mostly done. Then come 7 evidence, 8 alerts, 9 subscriptions and journeys, 10 organizations,
11 the apps, and 12 production readiness.

**Shortest path to the pilot:** finish phase 6, then alerts (8), evidence (7), the reviewer dashboard
and the citizen app. Route checks and NGO features can wait for Release 1.

## Decisions the documents leave open

They do not block the code yet, but they are needed before the pilot.

- **Categories:** the final launch list, and which ones get stricter publication or expiry rules.
- **Alert subscriptions:** can guests subscribe, or is a lightweight account needed (phone OTP is
  suggested)? Default alert radius and route corridor width.
- **Map, geocoding and routing provider** (cost, coverage in Cameroon, licensing).
- **Photo storage provider** and file limits.
- **Languages** (English, French, Pidgin?) and accessibility.
- **Reviewers:** who they are, their hours, escalation, and who may merge or split.
- **Retention periods** for reports, media, locations and audit logs. The code currently uses 30 days
  for report details and 7 days for reporter links (DECISIONS U-2).
- **NGO approval rules** and data-sharing limits.
- **Legal and safeguarding review** under Cameroon data protection law.
- **Funding and operating model** for moderation and hosting.
