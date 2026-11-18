"use client";
import Link from "next/link";
import { useMemo, useState } from "react";

import { Chip, Empty, ErrorNote, Loading } from "@/components/ui";
import type { IncidentSummary, Page, ReviewItem } from "@/lib/api";
import { useCategoryNames, useLoad } from "@/lib/hooks";
import { ago, categoryName, ITEM_TYPE } from "@/lib/labels";

const TARGET_MINUTES = 15;

function caseLink(i: ReviewItem): string {
  if (i.item_type === "ambiguous_match" || i.item_type === "report_quarantine") return `/case/?id=${i.id}`;
  return `/incident/?id=${i.incident_id}${i.item_type === "publication_review" ? `&item=${i.id}` : ""}`;
}

function describe(i: ReviewItem, names: Record<string, string>): { title: string; sub: string } {
  const s = i.summary;
  const cat = categoryName(s?.category, names);
  switch (i.item_type) {
    case "ambiguous_match":
      return { title: `New ${cat.toLowerCase()} report could belong to ${s?.candidate_count ?? "several"} incidents`,
        sub: `Report ${s?.report_reference ?? ""} · stays on its own until you decide` };
    case "report_quarantine":
      return { title: `${cat} report held back`, sub: `Report ${s?.report_reference ?? ""} · not on the public map` };
    case "publication_review":
      return { title: s?.incident_title ?? cat, sub: "Sensitive type: not on the public map until approved" };
    default:
      return { title: s?.incident_title ?? cat,
        sub: `${s?.incident_report_count ?? 0} report${s?.incident_report_count === 1 ? "" : "s"}` };
  }
}

export default function QueuePage() {
  const names = useCategoryNames();
  const items = useLoad<Page<ReviewItem>>("/review/items?limit=200");
  const open = useLoad<Page<IncidentSummary>>("/incidents?verification_status=unverified&operational_status=active&limit=200");
  const [tab, setTab] = useState<string>("all");

  const list = useMemo(() => items.data?.items ?? [], [items.data]);
  const shown = tab === "all" ? list : list.filter((i) => i.item_type === tab);
  const oldest = list.length ? list.reduce((a, b) => (a.created_at < b.created_at ? a : b)) : null;
  const oldestMin = oldest ? Math.round((Date.now() - new Date(oldest.created_at).getTime()) / 60000) : 0;
  const counts = Object.fromEntries(Object.keys(ITEM_TYPE).map((t) => [t, list.filter((i) => i.item_type === t).length]));
  const unconfirmed = open.data?.items.length ?? null;

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Needs attention</h1>
          <p className="muted" style={{ margin: "4px 0 0" }}>Cases the system was not sure about. Oldest first.</p>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <button className="btn btn-secondary" onClick={() => { items.reload(); open.reload(); }}>Refresh</button>
          {shown[0] ? <Link className="btn btn-primary" href={caseLink(shown[0])}>Take next case</Link> : null}
        </div>
      </div>

      <div className="kpis">
        <div className="card kpi"><span className="muted small">Open cases</span>
          <span className="kpi-value">{items.data ? list.length : "–"}</span>
          <span className="muted small">{counts.ambiguous_match ?? 0} possible duplicates</span></div>
        <div className="card kpi"><span className="muted small">Oldest waiting</span>
          <span className={`kpi-value ${oldestMin > TARGET_MINUTES ? "kpi-warn" : ""}`}>{oldest ? ago(oldest.created_at) : "–"}</span>
          <span className="muted small">Target: under {TARGET_MINUTES} min</span></div>
        <div className="card kpi"><span className="muted small">Unconfirmed and ongoing</span>
          <span className="kpi-value">{unconfirmed === null ? "–" : unconfirmed >= 200 ? "200+" : unconfirmed}</span>
          <span className="muted small"><Link href="/incidents/?verification_status=unverified">See them</Link></span></div>
      </div>

      <section className="card" aria-label="Review cases">
        <div role="tablist" className="tabs">
          {[["all", "All"], ...Object.entries(ITEM_TYPE).map(([k, v]) => [k, v.label])].map(([k, label]) => (
            <button key={k} role="tab" aria-selected={tab === k} className="tab" onClick={() => setTab(k)}>
              {label} <span style={{ opacity: 0.7 }}>{k === "all" ? list.length : counts[k]}</span>
            </button>
          ))}
        </div>
        <ErrorNote>{items.error}</ErrorNote>
        {!items.data && !items.error ? <Loading /> : null}
        {items.data && shown.length === 0 ? (
          <Empty title="Nothing waiting">New cases appear here when the system can&apos;t decide on its own.</Empty>
        ) : null}
        {shown.length > 0 ? (
          <div className="table-wrap">
            <table>
              <thead><tr><th style={{ width: 190 }}>Type</th><th>Case</th><th style={{ width: 110 }}>Waiting</th><th style={{ width: 100 }} /></tr></thead>
              <tbody>
                {shown.map((i) => {
                  const t = ITEM_TYPE[i.item_type] ?? { label: i.item_type, tone: "neutral" as const };
                  const d = describe(i, names);
                  const mins = (Date.now() - new Date(i.created_at).getTime()) / 60000;
                  return (
                    <tr key={i.id}>
                      <td><Chip tone={t.tone}>{t.label}</Chip></td>
                      <td><div className="cell-title">{d.title}</div><div className="cell-sub">{d.sub}{i.status === "claimed" ? " · being handled" : ""}</div></td>
                      <td style={{ fontWeight: 600, color: mins > TARGET_MINUTES ? "var(--signal)" : undefined }}>{ago(i.created_at)}</td>
                      <td><Link className="btn btn-secondary btn-small" href={caseLink(i)}>Open</Link></td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : null}
      </section>
    </>
  );
}
