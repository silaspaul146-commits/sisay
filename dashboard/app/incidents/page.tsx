"use client";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";

import { Chip, Empty, ErrorNote, Loading } from "@/components/ui";
import type { IncidentSummary, Page } from "@/lib/api";
import { useCategoryNames, useLoad } from "@/lib/hooks";
import { agoPhrase, categoryName, OPERATIONAL, SEVERITY_LABEL, VERIFICATION } from "@/lib/labels";

function IncidentList() {
  const params = useSearchParams();
  const names = useCategoryNames();
  const [verification, setVerification] = useState(params.get("verification_status") ?? "");
  const [operational, setOperational] = useState(params.get("operational_status") ?? "");
  const q = new URLSearchParams({ limit: "100" });
  if (verification) q.set("verification_status", verification);
  if (operational) q.set("operational_status", operational);
  const { data, error, reload } = useLoad<Page<IncidentSummary>>(`/incidents?${q}`);

  return (
    <>
      <div className="page-head">
        <div><h1>Incidents</h1><p className="muted" style={{ margin: "4px 0 0" }}>Newest first. Exact locations are visible to staff only.</p></div>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 10, alignItems: "flex-end" }}>
          <label className="field">How sure
            <select value={verification} onChange={(e) => setVerification(e.target.value)}>
              <option value="">Any</option>
              {Object.entries(VERIFICATION).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
            </select>
          </label>
          <label className="field">Still going on?
            <select value={operational} onChange={(e) => setOperational(e.target.value)}>
              <option value="">Any</option>
              {Object.entries(OPERATIONAL).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
            </select>
          </label>
          <button className="btn btn-secondary" onClick={reload}>Refresh</button>
        </div>
      </div>
      <section className="card">
        <ErrorNote>{error}</ErrorNote>
        {!data && !error ? <Loading /> : null}
        {data && data.items.length === 0 ? <Empty title="No incidents match these filters" /> : null}
        {data && data.items.length > 0 ? (
          <div className="table-wrap">
            <table>
              <thead><tr><th>Incident</th><th>How sure</th><th>Going on?</th><th>Severity</th><th>Reports</th><th>Updated</th></tr></thead>
              <tbody>
                {data.items.map((i) => {
                  const v = VERIFICATION[i.verification_status];
                  const o = OPERATIONAL[i.operational_status];
                  return (
                    <tr key={i.id}>
                      <td><Link href={`/incident/?id=${i.id}`} className="cell-title" style={{ color: "var(--ink)", textDecoration: "none" }}>{i.title}</Link>
                        <div className="cell-sub">{categoryName(i.category, names)}{i.is_provisional ? " · created automatically" : ""}</div></td>
                      <td>{v ? <Chip tone={v.tone}>{v.label}</Chip> : i.verification_status}</td>
                      <td>{o ? <Chip tone={o.tone}>{o.label}</Chip> : i.operational_status}</td>
                      <td>{SEVERITY_LABEL[i.severity] ?? i.severity}</td>
                      <td>{i.reports_count}</td>
                      <td className="muted">{agoPhrase(i.updated_at)}</td>
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

export default function IncidentsPage() {
  return <Suspense fallback={<Loading />}><IncidentList /></Suspense>;
}
