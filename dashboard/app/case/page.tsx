"use client";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";

import { Chip, ErrorNote, Loading } from "@/components/ui";
import type { ReviewItemDetail } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useAction, useCategoryNames, useLoad } from "@/lib/hooks";
import { agoPhrase, categoryName, clock, ITEM_TYPE, OPERATIONAL, VERIFICATION } from "@/lib/labels";

function Case() {
  const id = useSearchParams().get("id");
  const names = useCategoryNames();
  const { state } = useAuth();
  const item = useLoad<ReviewItemDetail>(id ? `/review/items/${id}` : null);
  const act = useAction();
  const [pick, setPick] = useState<string | null>(null);
  const [reason, setReason] = useState("");
  const [done, setDone] = useState<string | null>(null);

  if (!id) return <ErrorNote>No case selected.</ErrorNote>;
  if (item.error) return <ErrorNote>{item.error}</ErrorNote>;
  const it = item.data;
  if (!it) return <Loading />;

  const t = ITEM_TYPE[it.item_type] ?? { label: it.item_type, tone: "neutral" as const };
  const r = it.report;
  const isOpen = it.status === "open" || it.status === "claimed";
  const mine = state.status === "ready" && it.assigned_to === state.me.id;
  const takenByOther = it.status === "claimed" && !mine;
  const candidates = it.match?.candidates ?? [];
  const choice = pick ?? candidates[0]?.incident_id ?? "none";

  async function claim() {
    if (await act.run(`/review/items/${id}/claim`, "POST", {})) item.reload();
  }
  async function decideMatch() {
    if (reason.trim().length < 3) { act.setError("Write a short reason. It is saved in the history."); return; }
    const ok = choice === "none"
      ? await act.run(`/review/items/${id}/resolve`, "POST", { resolution: "left_unassociated", reason })
      : await act.run(`/incidents/${choice}/report-associations`, "POST", { report_id: it!.report_id, reason });
    if (ok) { setDone(choice === "none" ? "Kept as a separate report." : "Report added to the incident."); item.reload(); }
  }
  async function decideQuarantine(resolution: "accepted" | "rejected") {
    if (await act.run(`/review/items/${id}/resolve`, "POST", { resolution, reason: reason || null })) {
      setDone(resolution === "accepted" ? "Accepted. The report goes through normal matching now." : "Rejected. It stays off the map.");
      item.reload();
    }
  }
  async function dismiss() {
    if (await act.run(`/review/items/${id}/resolve`, "POST", { resolution: "dismissed", reason: reason || null })) {
      setDone("Case dismissed."); item.reload();
    }
  }

  return (
    <>
      <div className="crumb"><Link href="/">Needs attention</Link> / {t.label}</div>
      <div className="page-head">
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          <Chip tone={t.tone}>{t.label}</Chip>
          <h1>{it.item_type === "ambiguous_match" ? "Which incident does this report belong to?"
            : it.item_type === "report_quarantine" ? "Should this report be accepted?" : t.label}</h1>
          <p className="muted" style={{ margin: 0 }}>
            {it.item_type === "ambiguous_match" ? "The system found close matches and would not guess. The report stays on its own until you decide."
              : it.item_type === "report_quarantine" ? "Abuse checks held this report back. It is not on the public map." : null}
            {" "}Waiting {agoPhrase(it.created_at)}.
          </p>
        </div>
        {isOpen && !mine && !takenByOther ? <button className="btn btn-secondary" disabled={act.busy} onClick={claim}>Take this case</button> : null}
        {isOpen && mine ? <Chip tone="brand">You&apos;re handling this</Chip> : null}
        {takenByOther ? <Chip tone="amber">Another reviewer is handling this</Chip> : null}
      </div>

      {done ? <div className="note note-ok" role="status">{done} <Link href="/">Back to the queue</Link></div> : null}
      {!isOpen && !done ? <div className="note note-info">This case is closed ({it.resolution ?? it.status}).</div> : null}

      {r ? (
        <section className="card">
          <div className="card-head"><h2>Report {r.public_reference}</h2>
            <a className="small" target="_blank" rel="noopener noreferrer"
              href={`https://www.openstreetmap.org/?mlat=${r.location.latitude}&mlon=${r.location.longitude}#map=17/${r.location.latitude}/${r.location.longitude}`}>Exact spot ↗</a></div>
          <div className="card-body">
            <div style={{ font: "700 18px var(--font-head)" }}>{categoryName(r.category, names)}</div>
            {r.description ? <div>&ldquo;{r.description}&rdquo;</div> : <div className="muted">No note.</div>}
            <dl className="facts">
              <dt>Seen</dt><dd>{clock(r.observed_at)}</dd>
              <dt>Received</dt><dd>{clock(r.received_at)}</dd>
              <dt>Location</dt><dd>{r.location.source === "manual" ? "Placed by hand" : "From the phone"}, ±{r.location.accuracy_m ?? "?"} m</dd>
              {r.intake_reason ? (<><dt>Why held</dt><dd>{r.intake_reason}</dd></>) : null}
            </dl>
          </div>
        </section>
      ) : null}

      {it.item_type === "ambiguous_match" && isOpen && !takenByOther ? (
        <>
          <div role="radiogroup" aria-label="Where does the report belong" className="cards-grid">
            {candidates.map((c, n) => (
              <div key={c.incident_id} style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              <button type="button" role="radio" aria-checked={choice === c.incident_id} className="option" onClick={() => setPick(c.incident_id)}>
                <span className="option-kicker">Incident {String.fromCharCode(65 + n)}{n === 0 ? " · closest match" : ""}</span>
                <span className="option-title">{c.title}</span>
                <span className="small muted">{Math.round(c.distance_m)} m away · {categoryName(c.category, names)} · match score {Math.round(c.total_score * 100)}%</span>
                <span className="chips">
                  {VERIFICATION[c.verification_status] ? <Chip tone={VERIFICATION[c.verification_status].tone}>{VERIFICATION[c.verification_status].label}</Chip> : null}
                  {OPERATIONAL[c.operational_status] ? <Chip tone={OPERATIONAL[c.operational_status].tone}>{OPERATIONAL[c.operational_status].label}</Chip> : null}
                </span>
                {c.contradictions.length ? <span className="small" style={{ color: "var(--signal)" }}>Doesn&apos;t fit: {c.contradictions.join(", ").replace(/_/g, " ")}</span> : null}
              </button>
              <Link href={`/incident/?id=${c.incident_id}`} className="small" target="_blank">Open incident {String.fromCharCode(65 + n)} in a new tab ↗</Link>
              </div>
            ))}
            <button type="button" role="radio" aria-checked={choice === "none"} className="option" onClick={() => setPick("none")}>
              <span className="option-kicker">Neither</span>
              <span className="option-title">Keep it on its own</span>
              <span className="small muted">Use this if it describes a different event.</span>
            </button>
          </div>
          <section className="card"><div className="card-body">
            <label className="field">Reason (required, saved in history)
              <input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. Same junction, 3 minutes apart, same type" />
            </label>
            <ErrorNote>{act.error}</ErrorNote>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
              <button className="btn btn-primary" disabled={act.busy} onClick={decideMatch}>
                {choice === "none" ? "Keep it separate" : `Add to incident ${String.fromCharCode(65 + candidates.findIndex((c) => c.incident_id === choice))}`}
              </button>
              <button className="btn btn-secondary" disabled={act.busy} onClick={dismiss}>Dismiss case</button>
            </div>
          </div></section>
        </>
      ) : null}

      {it.item_type === "report_quarantine" && isOpen && !takenByOther ? (
        <section className="card"><div className="card-body">
          <label className="field">Note (optional)<input value={reason} onChange={(e) => setReason(e.target.value)} /></label>
          <ErrorNote>{act.error}</ErrorNote>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
            <button className="btn btn-primary" disabled={act.busy} onClick={() => decideQuarantine("accepted")}>Accept report</button>
            <button className="btn btn-danger" disabled={act.busy} onClick={() => decideQuarantine("rejected")}>Reject report</button>
          </div>
        </div></section>
      ) : null}
    </>
  );
}

export default function CasePage() {
  return <Suspense fallback={<Loading />}><Case /></Suspense>;
}
