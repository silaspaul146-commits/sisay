/** Plain-language labels. The API speaks in codes; reviewers read words (design: Sisay UI kit). */

export const ITEM_TYPE: Record<string, { label: string; tone: Tone }> = {
  ambiguous_match: { label: "Possible duplicate", tone: "signal" },
  incident_verification: { label: "Verify", tone: "brand" },
  publication_review: { label: "Check before publishing", tone: "purple" },
  report_quarantine: { label: "Suspicious report", tone: "danger" },
};

export const VERIFICATION: Record<string, { label: string; tone: Tone }> = {
  unverified: { label: "Unconfirmed", tone: "amber" },
  under_review: { label: "Being checked", tone: "amber" },
  verified: { label: "Verified", tone: "brand" },
  disputed: { label: "Disputed", tone: "purple" },
  rejected: { label: "Rejected", tone: "grey" },
};

export const OPERATIONAL: Record<string, { label: string; tone: Tone }> = {
  active: { label: "Ongoing", tone: "neutral" },
  monitoring: { label: "Watching", tone: "neutral" },
  resolved: { label: "Over", tone: "grey" },
  closed: { label: "Closed", tone: "grey" },
  merged: { label: "Merged", tone: "grey" },
  withdrawn: { label: "Withdrawn", tone: "grey" },
};

export const SEVERITY = ["unknown", "low", "moderate", "high", "critical"] as const;
export const SEVERITY_LABEL: Record<string, string> = {
  unknown: "Unknown", low: "Low", moderate: "Moderate", high: "High", critical: "Critical",
};
export const OPERATIONAL_CHOICES = ["active", "monitoring", "resolved", "closed"] as const;

export const DECISIONS = [
  { value: "verified", label: "Verified", help: "Our team confirmed it happened" },
  { value: "under_review", label: "Keep checking", help: "Not enough to decide yet" },
  { value: "disputed", label: "Disputed", help: "Credible information says otherwise" },
  { value: "rejected", label: "Rejected", help: "False or not an incident: removed from the public map" },
] as const;

export const HISTORY_LABEL: Record<string, string> = {
  verification_assessed: "set how sure we are to",
  severity_assessed: "set severity to",
  confidence_assessed: "set confidence to",
  freshness_assessed: "marked freshness as",
  operational_assessed: "set 'still going on?' to",
  report_auto_match: "linked a report automatically",
  report_auto_create_provisional: "created this incident from a report",
  report_review_assign: "linked a report",
  report_review_unassign: "unlinked a report",
  report_reassign: "moved a report",
  report_merge_reassign: "moved a report during a merge",
  incident_merged_into: "merged incidents",
};

export type Tone = "brand" | "amber" | "purple" | "grey" | "neutral" | "signal" | "danger";

export function valueLabel(v: string | null): string {
  if (!v) return "";
  return VERIFICATION[v]?.label ?? OPERATIONAL[v]?.label ?? SEVERITY_LABEL[v] ?? v.replace(/_/g, " ");
}

export function categoryName(code: string | null | undefined, names: Record<string, string>): string {
  if (!code) return "Report";
  return names[code] ?? code.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());
}

export function ago(iso: string, now = Date.now()): string {
  const s = Math.max(0, Math.round((now - new Date(iso).getTime()) / 1000));
  if (s < 60) return "just now";
  const m = Math.round(s / 60);
  if (m < 60) return `${m} min`;
  const h = Math.round(m / 60);
  if (h < 48) return `${h} h`;
  return `${Math.round(h / 24)} days`;
}

export function agoPhrase(iso: string): string {
  const a = ago(iso);
  return a === "just now" ? a : `${a} ago`;
}

export function clock(iso: string): string {
  return new Date(iso).toLocaleString(undefined, { hour: "2-digit", minute: "2-digit", day: "numeric", month: "short" });
}
