import { config } from "./config";

/** The API's error envelope: {"error": {"code", "message", "details", "request_id"}}. */
export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public details: { field?: string; message?: string }[] = [],
  ) {
    super(message);
  }
}

export type TokenGetter = () => Promise<string>;

export async function apiFetch<T>(getToken: TokenGetter, path: string, init: RequestInit = {}): Promise<T> {
  const token = await getToken();
  let res: Response;
  try {
    res = await fetch(`${config.apiBase}${path}`, {
      ...init,
      headers: {
        Authorization: `Bearer ${token}`,
        ...(init.body ? { "Content-Type": "application/json" } : {}),
        ...(init.headers ?? {}),
      },
    });
  } catch {
    throw new ApiError(0, "network_error", "Can't reach the server. Check your connection and try again.");
  }
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    const e = body?.error;
    throw new ApiError(res.status, e?.code ?? "http_error", e?.message ?? `Request failed (${res.status}).`,
      e?.details ?? []);
  }
  return (await res.json()) as T;
}

/** Turn an API error into one sentence a reviewer can act on. */
export function explain(err: unknown): string {
  if (!(err instanceof ApiError)) return "Something went wrong. Try again.";
  if (err.code === "version_conflict") return "Someone else changed this incident. Reload to see their change, then try again.";
  if (err.status === 403) return "Your account doesn't have permission to do this.";
  if (err.status === 401) return "Your session ended. Reload the page to sign in again.";
  const detail = err.details?.[0]?.message;
  return detail ? `${err.message} ${detail}` : err.message;
}

// --- Response types (subset of the staff API) ---------------------------------------------------

export type Me = { id: string; email: string | null; permissions: string[] };

export type IncidentSummary = {
  id: string; category: string; title: string; verification_status: string; operational_status: string;
  severity: string; confidence_level: string; reports_count: number; is_provisional: boolean;
  created_at: string; updated_at: string;
};

export type IncidentDetail = IncidentSummary & {
  version: number; description: string | null; freshness_status: string;
  location: { latitude: number; longitude: number; uncertainty_m: number };
  first_observed_at: string; last_observed_at: string; redirect_to: string | null;
  public: { public_id: string; publication_state: string; on_map: boolean } | null;
};

export type IncidentReport = {
  report_id: string; public_reference: string; category: string; observed_at: string; received_at: string;
  intake_status: string; location_accuracy_m: number | null; redacted: boolean;
};

export type HistoryEvent = {
  event_type: string; actor_type: string; actor_id: string | null; previous_value: string | null;
  new_value: string | null; reason: string | null; created_at: string;
};

export type ReviewItem = {
  id: string; item_type: string; status: string; priority: number | string; report_id: string | null;
  incident_id: string | null; match_decision_id: string | null; assigned_to: string | null;
  resolution: string | null; created_at: string;
  summary?: { category: string | null; incident_title: string | null; incident_report_count: number | null;
    report_reference: string | null; candidate_count: number };
};

export type ReviewItemDetail = ReviewItem & {
  report?: { public_reference: string; category: string; description: string | null; observed_at: string;
    received_at: string; intake_status: string; intake_reason: string | null; incident_id: string | null;
    location: { latitude: number; longitude: number; accuracy_m: number | null; source: string } };
  match?: { outcome: string; policy_version: string; reason: string | null;
    candidates: { incident_id: string; rank: number; total_score: number; distance_m: number;
      contradictions: string[]; category: string; title: string; verification_status: string;
      operational_status: string }[] };
};

export type Page<T> = { items: T[]; next_cursor?: string | null };
export type Category = { code: string; name: string };
