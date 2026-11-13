// Hand-written types mirroring the API (see AGENTS.md section 8: generate these from OpenAPI).

export type TableState = "ready" | "occupied" | "needs_clearing";
export type Role = "staff" | "host" | "admin";

export interface Table {
  id: string; label: string; capacity: number; min_party: number; x: number; y: number;
  state: TableState; state_since: string; version: number; manual_hold: boolean;
  greeted_at: string | null; current_party_id: string | null; guests_seated_hint: boolean;
}
export interface Alert {
  id: string; table_id: string; type: "needs_clearing" | "greet_reminder";
  status: "open" | "acknowledged" | "resolved"; created_at: string;
  acknowledged_by: string | null; renotified_at: string | null;
}
export interface Party {
  id: string; name: string | null; party_size: number; arrived_at: string; status: string;
}
export interface Camera {
  id: string; name: string; status: "online" | "offline"; health: "ok" | "degraded";
  health_reason: string | null; last_heartbeat_at: string | null; config_version: number;
}
export interface DemoStatus {
  scenario: string; speed: number; step: number; steps: number; paused: boolean; done: boolean;
  note: string | null;
}
export interface Floor {
  restaurant: { id: string; name: string; timezone: string; automation_enabled: boolean;
                is_demo: boolean; settings: { greet_reminders?: boolean } };
  server_time: string; role: Role; tables: Table[]; alerts: Alert[]; waitlist: Party[];
  suggestions: { table_id: string; party_id: string }[]; cameras: Camera[]; demo: DemoStatus | null;
}
export interface Me {
  id: string; name: string; email: string;
  memberships: { restaurant_id: string; restaurant_name: string; role: Role; is_demo: boolean }[];
}
export interface TableEvent {
  id: string; source: string; type: string; from_state: string | null; to_state: string | null;
  applied: boolean; reason: string | null; actor: string | null; observed_at: string;
}
export interface Member { id: string; email: string; name: string; role: Role; active: boolean }
export interface Zone { id: string; camera_id: string; table_id: string; polygons: [number, number][][] }
export interface Summary {
  tables: number; turns: number; turns_per_table: number; avg_turn_minutes: number | null;
  median_departure_to_ready_minutes: number | null; cleared_count: number; occupancy_pct: number;
}
export interface PeakHours {
  timezone: string;
  by_hour: { weekday: number; hour: number; arrivals: number; per_week: number }[];
  by_shift: { weekday: number; shift: string; arrivals: number; per_week: number }[];
}

export class ApiError extends Error {
  constructor(public status: number, public detail: any) {
    super(typeof detail === "string" ? detail : detail?.message ?? `HTTP ${status}`);
  }
}

export async function api<T = any>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(path, {
    method,
    credentials: "same-origin",
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const text = await res.text();
  const data = text ? JSON.parse(text) : null;
  if (!res.ok) throw new ApiError(res.status, data?.detail ?? data);
  return data as T;
}

export const STATE_LABEL: Record<TableState, string> = {
  ready: "Ready", occupied: "Occupied", needs_clearing: "Needs clearing",
};
export const STATE_ICON: Record<TableState, string> = { ready: "✓", occupied: "●", needs_clearing: "!" };

export function duration(ms: number): string {
  const s = Math.max(0, Math.floor(ms / 1000));
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
  return h > 0 ? `${h}h ${String(m).padStart(2, "0")}m` : `${m}:${String(sec).padStart(2, "0")}`;
}

export const atLeast = (role: Role, min: Role) =>
  ["staff", "host", "admin"].indexOf(role) >= ["staff", "host", "admin"].indexOf(min);
