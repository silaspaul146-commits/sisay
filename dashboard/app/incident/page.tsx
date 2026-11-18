"use client";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";

import { Chip, ErrorNote, Loading, Segmented } from "@/components/ui";
import type { HistoryEvent, IncidentDetail, IncidentReport, Page, ReviewItemDetail } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useAction, useCategoryNames, useLoad } from "@/lib/hooks";
import {
  agoPhrase, categoryName, clock, DECISIONS, HISTORY_LABEL, OPERATIONAL, OPERATIONAL_CHOICES, SEVERITY,
  SEVERITY_LABEL, valueLabel, VERIFICATION,
} from "@/lib/labels";

function Workspace() {
  const params = useSearchParams();
  const id = params.get("id");
  const itemId = params.get("item");
  const names = useCategoryNames();
  const incident = useLoad<IncidentDetail>(id ? `/incidents/${id}` : null);
  const reports = useLoad<Page<IncidentReport>>(id ? `/incidents/${id}/reports` : null);
  const history = useLoad<Page<HistoryEvent>>(id ? `/incidents/${id}/history` : null);
  const reloadAll = () => { incident.reload(); reports.reload(); history.reload(); };

  if (!id) return <ErrorNote>No incident selected.</ErrorNote>;
  if (incident.error) return <ErrorNote>{incident.error}</ErrorNote>;
  const d = incident.data;
  if (!d) return <Loading />;

  const v = VERIFICATION[d.verification_status];
  const o = OPERATIONAL[d.operational_status];
  const closed = d.operational_status === "merged" || d.operational_status === "withdrawn";
  const osm = `https://www.openstreetmap.org/?mlat=${d.location.latitude}&mlon=${d.location.longitude}#map=17/${d.location.latitude}/${d.location.longitude}`;

  return (
    <>
      <div className="crumb"><Link href="/">Needs attention</Link> / <Link href="/incidents/">Incidents</Link> / {d.title}</div>
      <div className="page-head">
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          <h1>{d.title}</h1>
          <div className="chips">
            {v ? <Chip tone={v.tone}>{v.label}</Chip> : null}
            {o ? <Chip tone={o.tone}>{o.label}</Chip> : null}
            <Chip tone="neutral">{categoryName(d.category, names)}</Chip>
            {d.is_provisional ? <Chip tone="neutral">Created automatically {clock(d.created_at)}</Chip> : null}
            {d.public ? (
              <Chip tone={d.public.on_map ? "brand" : "grey"}>
                {d.public.on_map ? "On the public map (blurred)" : `Not on the public map (${d.public.publication_state})`}
              </Chip>
            ) : <Chip tone="grey">Not on the public map yet</Chip>}
          </div>
        </div>
        <button className="btn btn-secondary" onClick={reloadAll}>Refresh</button>
      </div>

      {d.redirect_to ? (
        <div className="note note-info">This incident was merged. <Link href={`/incident/?id=${d.redirect_to}`}>Open the surviving incident</Link>.</div>
      ) : null}

      <div className="row">
        <div className="col-main">
          <section className="card">
            <div className="card-head"><h2>Facts</h2><a href={osm} target="_blank" rel="noopener noreferrer" className="small">Open exact spot in OpenStreetMap ↗</a></div>
            <div className="card-body">
              <dl className="facts">
                <dt>Exact location</dt><dd>{d.location.latitude.toFixed(5)}, {d.location.longitude.toFixed(5)} · ±{d.location.uncertainty_m} m <span className="muted small">(staff only)</span></dd>
                <dt>First seen</dt><dd>{clock(d.first_observed_at)}</dd>
                <dt>Latest report</dt><dd>{clock(d.last_observed_at)} ({agoPhrase(d.last_observed_at)})</dd>
                <dt>Severity</dt><dd>{SEVERITY_LABEL[d.severity] ?? d.severity}</dd>
                <dt>Confidence</dt><dd>{d.confidence_level}</dd>
                {d.description ? (<><dt>Description</dt><dd>{d.description}</dd></>) : null}
              </dl>
            </div>
          </section>

          <ReportsCard reports={reports.data?.items} error={reports.error} canUnlink={!closed} onChange={reloadAll} />

          <section className="card">
            <div className="card-head"><h2>History</h2></div>
            <div className="card-body">
              <ErrorNote>{history.error}</ErrorNote>
              {!history.data ? <Loading /> : (
                <div className="timeline">
                  {[...history.data.items].reverse().map((e, n) => (
                    <div className="tl-row" key={n}>
                      <span className="tl-time">{clock(e.created_at)}</span>
                      <span>
                        <b>{e.actor_type === "user" ? "Reviewer" : "System"}</b>{" "}
                        {e.event_type.startsWith("corrected_") ? `corrected ${e.event_type.slice(10).replace(/_id$/, "").replace(/_/g, " ")}`
                          : HISTORY_LABEL[e.event_type] ?? e.event_type.replace(/_/g, " ")}
                        {e.event_type.endsWith("_assessed") ? <b> {valueLabel(e.new_value)}</b> : null}
                        {e.reason ? <div className="tl-reason">“{e.reason}”</div> : null}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </section>
        </div>

        <div className="col-side">
          {itemId ? <PublicationPanel itemId={itemId} onDone={reloadAll} /> : null}
          {closed ? <div className="note note-info">Merged or withdrawn incidents can&apos;t be changed.</div> : (
            <>
              <DecisionPanel d={d} onDone={reloadAll} />
              <CorrectionPanel d={d} names={names} onDone={reloadAll} />
              <MergePanel id={d.id} onDone={reloadAll} />
            </>
          )}
        </div>
      </div>
    </>
  );
}

function DecisionPanel({ d, onDone }: { d: IncidentDetail; onDone: () => void }) {
  const { can } = useAuth();
  const [decision, setDecision] = useState(d.verification_status);
  const [severity, setSeverity] = useState(d.severity);
  const [op, setOp] = useState(d.operational_status);
  const [reason, setReason] = useState("");
  const [saved, setSaved] = useState(false);
  const act = useAction();
  useEffect(() => { setDecision(d.verification_status); setSeverity(d.severity); setOp(d.operational_status); }, [d]);

  const verifyChanged = decision !== d.verification_status;
  const patch: Record<string, string> = {};
  if (severity !== d.severity) patch.severity = severity;
  if (op !== d.operational_status) patch.operational_status = op;
  const nothing = !verifyChanged && Object.keys(patch).length === 0;

  async function save() {
    setSaved(false);
    if (reason.trim().length < 3) { act.setError("Write a short reason. It is saved in the history."); return; }
    // PATCH first: it checks the version we loaded; verification bumps the version afterwards.
    if (Object.keys(patch).length) {
      const ok = await act.run(`/incidents/${d.id}`, "PATCH", { ...patch, reason, expected_version: d.version });
      if (!ok) return;
    }
    if (verifyChanged) {
      const ok = await act.run(`/incidents/${d.id}/verify`, "POST", { decision, reason });
      if (!ok) return;
    }
    setReason(""); setSaved(true); onDone();
  }

  return (
    <section className="card" aria-label="Decision">
      <div className="card-body">
        <h2 style={{ fontSize: 18, fontWeight: 800 }}>Your decision</h2>
        <div className="field">How sure are we?
          <div role="radiogroup" aria-label="How sure are we" className="choices">
            {DECISIONS.map((c) => (
              <button key={c.value} type="button" role="radio" aria-checked={decision === c.value} className="choice"
                disabled={!can("incident.verify")} onClick={() => setDecision(c.value)}>
                <span className={`dot dot-${c.value}`} />
                <span><span className="choice-title">{c.label}</span><br /><span className="choice-help">{c.help}</span></span>
              </button>
            ))}
            {decision === "unverified" ? <span className="hint">Currently unconfirmed: nobody has decided yet.</span> : null}
          </div>
        </div>
        <div className="field">How serious?
          <Segmented label="Severity" value={severity} onChange={setSeverity}
            options={SEVERITY.map((s) => ({ value: s, label: SEVERITY_LABEL[s] }))} />
        </div>
        <div className="field">Still going on?
          <Segmented label="Still going on" value={op} onChange={setOp}
            options={OPERATIONAL_CHOICES.map((s) => ({ value: s, label: OPERATIONAL[s].label }))} />
        </div>
        <label className="field">Reason (required, saved in history)
          <textarea value={reason} onChange={(e) => setReason(e.target.value)} placeholder="What did you check?" maxLength={2000} />
        </label>
        <ErrorNote>{act.error}</ErrorNote>
        {saved ? <div className="note note-ok" role="status">Saved. The public map updates within a minute.</div> : null}
        <button className="btn btn-primary btn-block" disabled={nothing || act.busy} onClick={save}>
          {act.busy ? "Saving…" : nothing ? "No changes" : "Save decision"}
        </button>
        <span className="hint">If you reject or dispute this, people who got an alert will be told (once alerts are live).</span>
      </div>
    </section>
  );
}

function CorrectionPanel({ d, names, onDone }: { d: IncidentDetail; names: Record<string, string>; onDone: () => void }) {
  const { can } = useAuth();
  const [open, setOpen] = useState(false);
  const [title, setTitle] = useState(d.title);
  const [category, setCategory] = useState(d.category);
  const [reason, setReason] = useState("");
  const act = useAction();
  if (!can("incident.correct")) return null;
  const body: Record<string, string> = {};
  if (title.trim() && title !== d.title) body.title = title.trim();
  if (category !== d.category) body.category = category;

  async function save() {
    if (reason.trim().length < 3) { act.setError("Write a short reason. It is saved in the history."); return; }
    const ok = await act.run(`/incidents/${d.id}`, "PATCH", { ...body, reason, expected_version: d.version });
    if (ok) { setReason(""); setOpen(false); onDone(); }
  }

  return (
    <section className="card">
      <div className="card-head"><h2>Correct details</h2>
        <button className="btn btn-secondary btn-small" aria-expanded={open} onClick={() => setOpen(!open)}>{open ? "Close" : "Edit"}</button></div>
      {open ? (
        <div className="card-body">
          <label className="field">Title<input value={title} onChange={(e) => setTitle(e.target.value)} maxLength={200} /></label>
          <label className="field">Type
            <select value={category} onChange={(e) => setCategory(e.target.value)}>
              {Object.entries(names).map(([code, name]) => <option key={code} value={code}>{name}</option>)}
            </select>
          </label>
          <label className="field">Reason (required)<input value={reason} onChange={(e) => setReason(e.target.value)} /></label>
          <span className="hint">The old values are kept in the history. Changing the type takes the incident off the public map until it is regenerated.</span>
          <ErrorNote>{act.error}</ErrorNote>
          <button className="btn btn-primary" disabled={!Object.keys(body).length || act.busy} onClick={save}>Save correction</button>
        </div>
      ) : null}
    </section>
  );
}

function MergePanel({ id, onDone }: { id: string; onDone: () => void }) {
  const { can } = useAuth();
  const [source, setSource] = useState("");
  const [reason, setReason] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const act = useAction();
  if (!can("incident.merge")) return null;
  async function merge() {
    const r = await act.run<{ reports_moved?: number }>(`/incidents/${id}/merge`, "POST",
      { source_incident_id: source.trim(), reason });
    if (r) { setMsg("Merged. The other incident now points here."); setSource(""); setReason(""); onDone(); }
  }
  return (
    <section className="card">
      <div className="card-head"><h2>Merge a duplicate into this incident</h2></div>
      <div className="card-body">
        <label className="field">Duplicate incident ID<input value={source} onChange={(e) => setSource(e.target.value)} placeholder="Paste the other incident's ID" /></label>
        <label className="field">Reason (required)<input value={reason} onChange={(e) => setReason(e.target.value)} /></label>
        <ErrorNote>{act.error}</ErrorNote>
        {msg ? <div className="note note-ok" role="status">{msg}</div> : null}
        <button className="btn btn-secondary" disabled={!source.trim() || reason.trim().length < 3 || act.busy} onClick={merge}>Merge into this one</button>
      </div>
    </section>
  );
}

function ReportsCard({ reports, error, canUnlink, onChange }: {
  reports?: IncidentReport[]; error: string | null; canUnlink: boolean; onChange: () => void;
}) {
  const { can } = useAuth();
  const [unlinking, setUnlinking] = useState<string | null>(null);
  const [reason, setReason] = useState("");
  const act = useAction();
  async function unlink(rid: string) {
    const r = await act.run<{ incident_remaining_reports: number | null }>(`/reports/${rid}/unassociate`, "POST", { reason });
    if (r) { setUnlinking(null); setReason(""); onChange(); }
  }
  return (
    <section className="card">
      <div className="card-head"><h2>Reports ({reports?.length ?? "…"})</h2><span className="muted small">Reporter identity is never shown</span></div>
      <ErrorNote>{error}</ErrorNote>
      {!reports ? <Loading /> : reports.length === 0 ? <div className="pad muted">No reports are linked any more. Consider closing this incident.</div> : reports.map((r) => (
        <div className="report" key={r.report_id}>
          <span className="report-ref">{r.public_reference}</span>
          <div style={{ flexGrow: 1, minWidth: 0 }}>
            <div>Seen {clock(r.observed_at)} · received {clock(r.received_at)}
              {new Date(r.received_at).getTime() - new Date(r.observed_at).getTime() > 30 * 60000 ? <Chip tone="neutral">sent late</Chip> : null}</div>
            <div className="cell-sub">Location ±{r.location_accuracy_m ?? "?"} m{r.redacted ? " · details cleaned (retention)" : ""}</div>
            {unlinking === r.report_id ? (
              <div className="inline-form">
                <input autoFocus aria-label="Reason for unlinking" placeholder="Why doesn't this report belong here?" value={reason} onChange={(e) => setReason(e.target.value)} />
                <button className="btn btn-danger btn-small" disabled={reason.trim().length < 3 || act.busy} onClick={() => unlink(r.report_id)}>Unlink</button>
                <button className="btn btn-secondary btn-small" onClick={() => setUnlinking(null)}>Cancel</button>
                <ErrorNote>{act.error}</ErrorNote>
              </div>
            ) : null}
          </div>
          {canUnlink && can("report.review") && unlinking !== r.report_id ? (
            <button className="btn btn-secondary btn-small" onClick={() => { setUnlinking(r.report_id); act.setError(null); }}>Unlink</button>
          ) : null}
        </div>
      ))}
    </section>
  );
}

function PublicationPanel({ itemId, onDone }: { itemId: string; onDone: () => void }) {
  const item = useLoad<ReviewItemDetail>(`/review/items/${itemId}`);
  const [reason, setReason] = useState("");
  const act = useAction();
  const it = item.data;
  if (!it || it.item_type !== "publication_review") return null;
  if (it.status !== "open" && it.status !== "claimed") {
    return <div className="note note-info">Publication already decided: {it.resolution}.</div>;
  }
  async function decide(resolution: "approved" | "rejected") {
    const ok = await act.run(`/review/items/${itemId}/resolve`, "POST", { resolution, reason: reason || null });
    if (ok) { item.reload(); onDone(); }
  }
  return (
    <section className="card" style={{ border: "2px solid var(--purple)" }}>
      <div className="card-body">
        <h2>Check before publishing</h2>
        <p className="small muted" style={{ margin: 0 }}>This type is sensitive. It stays off the public map until you approve it.</p>
        <label className="field">Note (optional)<input value={reason} onChange={(e) => setReason(e.target.value)} /></label>
        <ErrorNote>{act.error}</ErrorNote>
        <div style={{ display: "flex", gap: 8 }}>
          <button className="btn btn-primary" disabled={act.busy} onClick={() => decide("approved")}>Approve for the map</button>
          <button className="btn btn-secondary" disabled={act.busy} onClick={() => decide("rejected")}>Keep it off</button>
        </div>
      </div>
    </section>
  );
}

export default function IncidentPage() {
  return <Suspense fallback={<Loading />}><Workspace /></Suspense>;
}
