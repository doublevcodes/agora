export type AgentRole = "hermes" | "nemesis";
export type Stance = "approve" | "reject" | "escalate";
export type VerdictOutcome = "APPROVE" | "REJECT" | "ESCALATE TO HUMAN";

export type SseEventType =
  | "status"
  | "specter_brief"
  | "agent_message"
  | "round_state"
  | "verdict"
  | "error"
  | "done";

export interface ParsedTransaction {
  raw: string;
  date?: string | null;
  vendor: string;
  amount?: number | null;
  currency?: string | null;
  reference?: string | null;
  notes?: string | null;
}

export interface SpecterBrief {
  status: "available" | "unavailable";
  summary: string;
  vendor_found: boolean;
  vendor_name?: string | null;
  domain?: string | null;
  founded_year?: number | null;
  legitimacy_score?: number | null;
  red_flags: string[];
}

export interface AgentStructuredMessage {
  role: AgentRole;
  round: number;
  stance: Stance;
  claim: string;
  evidence: string;
  counterpoint: string;
  risk_tags: string[];
  confidence: number;
  text: string;
  structured_available: boolean;
}

export interface VerdictDecision {
  outcome: VerdictOutcome;
  reason: string;
  escalation_packet?: Record<string, unknown> | null;
}

export interface SseEnvelope<T = Record<string, unknown>> {
  event_id: string;
  trace_id: string;
  event_type: SseEventType;
  timestamp: string;
  payload: T;
}

export interface DebateRequest {
  raw_transaction: string;
  max_rounds?: number;
}
