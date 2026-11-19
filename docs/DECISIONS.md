# Implementation decisions

Source documents live in `docs/source/`. Where they disagree, this file records the choice the
code makes. Every row is reversible; change the row and the code together.

Precedence used: **confirmed domain decisions ([C] in the DB spec, "Confirmed" in the Domain Model)
> Physical Database Design v0.2 > API Contract v1.0 > Engineering Pack v1.0 > PRD/SRS/Use cases**.
The DB spec is the most detailed and most recent, so it wins on storage and processing; the API
contract wins on client-facing names where Appendix A recommends it.

## API Contract Appendix A conflicts

| # | Topic | Decision in code |
|---|-------|------------------|
| 1 | Severity | `unknown, low, moderate, high, critical` everywhere. Provisional incidents start at `unknown`. |
| 2 | Verification | `unverified, under_review, verified, disputed, rejected` everywhere (DB `refuted` renamed to `rejected`). |
| 3 | Operational status | DB set: `active, monitoring, resolved, closed, merged, withdrawn`. `ongoing`/`contained` dropped. |
| 4 | Freshness | `current, aging, stale, expired` everywhere. |
| 5 | Alert distribution | Not in this slice. Proposal: levels 1–3 map to `internal`/`subscribers`/`priority`; no area broadcast. |
| 6 | Report access token | Client may send its own token (`rpt_` + 43 base64url chars) on submission; otherwise the server generates one and returns it **only** in the first 201 response. |
| 7 | Token header | `X-Report-Access-Token` (submission and status). Never in a URL. |
| 8 | Public reference | 12 Crockford base32 chars, `XXXX-XXXX-XXXX` (60 random bits). Never authorizes. |
| 9 | Intake status | First response returns `received`; enumeration is `received, accepted, needs_review, rejected, quarantined`. |
| 10 | Public identifier | Public routes use `public_id` (random v4 projection id). Internal UUIDv7 ids are never exposed publicly. |
| 11 | Public detail fields | No `title`, no `reports_count`. `description` only when the disclosure policy allows and only staff-written text. |
| 12 | Location source | Stored as `device_gps, device_network, manual_pin, geocoded_address`. API also accepts aliases `gps`→`device_gps`, `manual`/`map_pin`→`manual_pin`. `accuracy_m` optional; server default per source. |
| 13 | Description length | API limit 2,000 chars (DB CHECK 5,000). |
| 14 | Categories | Union of both lists seeded (15 codes). The 7 codes not in the DB spec have **proposed** disclosure policies that need field/protection review before launch. |
| 15–22 | Corrections, acks, journeys, subscriptions, permissions, auth, impact PATCH, account status | Out of this slice; resolve when the owning phase starts. |

## Other conflicts

| Topic | Conflict | Decision |
|-------|----------|----------|
| When matching runs | Engineering Pack §2.5 puts association in the submit transaction; DB spec §8.1 and API §3.3 run it in the worker | Worker. Submission commits report + submitter + credential + outbox atomically and returns without waiting. Matching commits decision + association + incident + outbox atomically. |
| Public map format | API §4.3 shows `{items, next_cursor}`; Engineering Pack §5.1/§9.2 require GeoJSON | GeoJSON `FeatureCollection` with `next_cursor` and a `notice` as foreign members. |
| Submission status code | API: 201; DB spec: 202 | 201 on first submission, 200 on idempotent replay (replay never contains the token). |
| `area_only` disclosure mode | Projection CHECK requires a point when visible, `area_only` nulls the point | `area_only` incidents are not shown on the map in v1. No seeded policy uses it. |
| Public freshness | Projection has no freshness column | Derived from `public_observed_at` age: ≤6 h current, ≤24 h aging, otherwise stale. Provisional; make category-specific later. |
| ORM | DB spec suggests GeoAlchemy2 models | SQLAlchemy Core with explicit SQL. The spec's queries are PostGIS-specific and hand-tuned; models add little. |
| Installations | No registration endpoint in the contract for the slice | `X-Installation-ID` (+ optional `X-Client-Platform`) is upserted on first use. Revisit with push-endpoint registration. |

## Staff API (2026-11-18)

| Topic | Conflict | Decision |
|-------|----------|----------|
| Permission names | API contract 16.1 names (`incident.update`, `incident.view_reports`, `incident.review_matches`, `incident.manage_associations`, `incident.view_history`) are not in the DB CHECK list | DB vocabulary wins. `incident.view` covers detail, reports and history; `report.review` covers the review queue, match candidates, associations and quarantine; `incident.assess`, `incident.verify` and `incident.merge` as named. Publication approval needs `incident.verify`. |
| Sign-in | API contract `/auth/register`, `/auth/login`, `/auth/refresh` | Replaced by the external OIDC provider (U-1). The API validates provider tokens (JWKS, issuer, audience). `GET /auth/me` is kept. |
| Staff provisioning | Not specified | `python -m app.manage grant --subject <sub> --email <e> reviewer` (owner connection). Unknown subjects are refused; accounts are never auto-created on first sign-in. |
| Organization reviewers | API contract allows them to verify | Not in this phase: only platform permissions authorize staff routes. Org-scoped access comes with the organizations phase. |
| Assessment types | Contract lists `geographic_impact` | Not in the DB CHECK; rejected with 422 until the schema adds it. |
| `PATCH /incidents/{id}` | Contract sends `operational_status: "ongoing"` and mixes corrections with status | Fields: `title`, `description`, `category`, `location`, `operational_status` (`active`/`monitoring`/`resolved`/`closed`), `severity`, plus a required `reason` and optional `expected_version` (409 `version_conflict` if someone changed it meanwhile). Content fields need `incident.correct`; status and severity need `incident.assess`. Each corrected field writes an `incident_corrections` row (old and new value); status and severity write assessments (migration 0016 adds the `operational` type). Category, location or description changes restrict the public projection at once and the worker regenerates it. The `reviewer` bundle now includes `incident.correct`. |
| Unlinking a report | Contract inventory: `POST /reports/{id}/unassociate` | Built as listed (`report.review`, reason required). Writes `review_unassign` history; the report stays and can be linked again. The response gives the incident's remaining report count so the dashboard can suggest closing an empty incident. |
| Not yet built | `POST /incidents` (manual create), reviewer notes, incident split | Next staff increment. |

## Alerts (2026-11-19)

| Topic | Conflict / gap | Decision |
|-------|----------------|----------|
| Who subscribes | PRD open question: account vs guest | **Guest by default.** The app registers once (`POST /installations`) and receives a secret `ins_` token, stored as an HMAC like report tokens. Personal routes need `X-Installation-Token`; another installation's ids answer 404. A raw installation id is never enough to read someone's saved places. |
| Distribution levels | PRD levels 1–3 vs DB `internal`/`subscribers`/`priority` | `subscribers` = Level 1 (one eligible report is enough, clearly unconfirmed); `priority` = Level 2 (verified **and** high or critical); `internal` = held (protected category awaiting publication approval). No Level 3 area broadcast: phones are never tracked. Report counts never widen an alert on their own. |
| Unknown severity | DB spec A-7: unknown never passes `min_severity` | New, unrated incidents use the category's `default_severity` (Shooting = high) so the first warning is not blocked. A reviewer's assessment replaces it. |
| Material changes | When to notify again | New version and push only on a level change, a change of wording (verified, disputed), withdrawal (rejected) or "over" (resolved/closed). More reports about the same event: no new version. Merges withdraw quietly (the survivor carries the warning). Expiry is silent. |
| Old observations | Offline reports synced late | No new alert if the latest observation is older than the category window (clamped 2–72 h). |
| Protected categories | Alerts vs publication review | Held until the publication review is approved (the same gate as the public map). The public delay itself does not delay alerts; the category's `min_alert_radius_m` floor still blunts the location oracle (F-15). |
| Alert list in the app | Deliveries need a push endpoint | New `alerting.alert_inbox` (one row per subscriber per version) feeds `GET /alerts`, so the list works without push or when push fails. `alert_deliveries` stays the per-device push record. |
| What citizens see | Citizen role must not read `incident.*` | Each version stores a snapshot (category, verification, effective severity, status, location snapped to the public grid). |
| Push sending | FCM | Deliveries are queued now; sending through Firebase is the next increment. |

## Product-owner decisions (2026-11-18)

| ID | Decision | Consequence in code |
|----|----------|---------------------|
| U-1 Authentication | **External OIDC identity provider.** No passwords or refresh-token tables in our database. | `identity.users.auth_subject` holds the provider subject. The API contract's `/auth/register` and `/auth/login` are replaced by provider sign-in, and our API validates provider-issued tokens. Provider choice is still open. |
| U-2 Retention | **Reports are short-lived.** After a short window the raw report is redacted (precise location snapped to 1 km, free text removed, credentials revoked, reporter link purged). The incident record, which holds no reporter identity, is kept as history. | Nightly retention job in the worker (`app/modules/retention`). Windows are configurable: `REPORT_RETENTION_DAYS` (default 30) and `REPORT_SUBMITTER_RETENTION_DAYS` (default 7). Legal review for Cameroon is still advised. |
| U-8 Alert automation | **All necessary alerts are sent automatically.** There is no human approval gate. Every alert states its uncertainty, starts localized, and expands by policy. | Applies when the alerts phase is built. |
| Hosting | **Neon** Postgres with PostGIS, and **Render** for the API web service and the background worker. | `render.yaml`, `docs/DEPLOY.md`. |
| Frontends | **A UI/UX design and branding phase comes before any frontend code.** | No Flutter or Next.js work until the design is approved. |

## Deferred (as the engineering pack §12.1 directs)

Notifications/alerts, subscriptions, journey checks, organizations, humanitarian intelligence,
evidence upload. Their tables exist (migrations
0010–0012) so the schema is final; their code does not.
