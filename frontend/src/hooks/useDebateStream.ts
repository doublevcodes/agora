import { useCallback, useEffect, useRef, useState } from "react";
import type {
  AgentStructuredMessage,
  ParsedTransaction,
  SpecterBrief,
  SseEnvelope,
  VerdictDecision,
} from "../types/debate";

const DEFAULT_API = "http://localhost:8000";
const API_URL =
  (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, "") ||
  DEFAULT_API;

const MESSAGE_DELAY_MS = 800;

export type DebateStatus =
  | "idle"
  | "starting"
  | "streaming"
  | "complete"
  | "error";

export interface DebateState {
  status: DebateStatus;
  transaction: ParsedTransaction | null;
  brief: SpecterBrief | null;
  messages: AgentStructuredMessage[];
  verdict: VerdictDecision | null;
  statusMessages: string[];
  riskLevel: string | null;
  routingRationale: string | null;
  error: string | null;
  traceId: string | null;
}

const initialState: DebateState = {
  status: "idle",
  transaction: null,
  brief: null,
  messages: [],
  verdict: null,
  statusMessages: [],
  riskLevel: null,
  routingRationale: null,
  error: null,
  traceId: null,
};

interface QueueItem {
  envelope: SseEnvelope;
}

export function useDebateStream() {
  const [state, setState] = useState<DebateState>(initialState);
  const queueRef = useRef<QueueItem[]>([]);
  const flushingRef = useRef(false);
  const abortRef = useRef<AbortController | null>(null);

  const reset = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    queueRef.current = [];
    flushingRef.current = false;
    setState(initialState);
  }, []);

  useEffect(() => () => abortRef.current?.abort(), []);

  const apply = useCallback((env: SseEnvelope) => {
    setState((prev) => {
      switch (env.event_type) {
        case "status": {
          const next: DebateState = { ...prev };
          const payload = env.payload as Record<string, unknown>;
          if (typeof payload.message === "string") {
            next.statusMessages = [...prev.statusMessages, payload.message];
          }
          if (payload.transaction) {
            next.transaction = payload.transaction as ParsedTransaction;
          }
          if (typeof payload.risk_level === "string") {
            next.riskLevel = payload.risk_level;
          }
          if (typeof payload.rationale === "string") {
            next.routingRationale = payload.rationale;
          }
          if (!prev.traceId && env.trace_id) {
            next.traceId = env.trace_id;
          }
          next.status = "streaming";
          return next;
        }
        case "specter_brief": {
          const payload = env.payload as { brief: SpecterBrief };
          return {
            ...prev,
            brief: payload.brief,
            status: "streaming",
            traceId: prev.traceId ?? env.trace_id,
          };
        }
        case "agent_message": {
          const payload = env.payload as {
            message: AgentStructuredMessage;
          };
          return {
            ...prev,
            messages: [...prev.messages, payload.message],
            status: "streaming",
          };
        }
        case "round_state": {
          return prev;
        }
        case "verdict": {
          const payload = env.payload as { verdict: VerdictDecision };
          return {
            ...prev,
            verdict: payload.verdict,
            status: "streaming",
          };
        }
        case "error": {
          const payload = env.payload as { message?: string };
          return {
            ...prev,
            status: "error",
            error: payload.message ?? "Unknown error",
          };
        }
        case "done": {
          return { ...prev, status: "complete" };
        }
        default:
          return prev;
      }
    });
  }, []);

  const drainQueue = useCallback(async () => {
    if (flushingRef.current) return;
    flushingRef.current = true;
    while (queueRef.current.length > 0) {
      const item = queueRef.current.shift()!;
      apply(item.envelope);
      const ev = item.envelope.event_type;
      if (ev === "agent_message" || ev === "verdict" || ev === "specter_brief") {
        await new Promise((resolve) => setTimeout(resolve, MESSAGE_DELAY_MS));
      }
    }
    flushingRef.current = false;
  }, [apply]);

  const enqueue = useCallback(
    (envelope: SseEnvelope) => {
      queueRef.current.push({ envelope });
      void drainQueue();
    },
    [drainQueue]
  );

  const startDebate = useCallback(
    async (rawTransaction: string, maxRounds = 6) => {
      reset();
      const ctrl = new AbortController();
      abortRef.current = ctrl;
      setState({ ...initialState, status: "starting" });

      try {
        const resp = await fetch(`${API_URL}/debate`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            raw_transaction: rawTransaction,
            max_rounds: maxRounds,
          }),
          signal: ctrl.signal,
        });

        if (!resp.ok || !resp.body) {
          const text = await resp.text().catch(() => "");
          setState((prev) => ({
            ...prev,
            status: "error",
            error: `Backend returned ${resp.status}: ${text || resp.statusText}`,
          }));
          return;
        }

        const reader = resp.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";

        while (true) {
          const { value, done } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          let sepIdx;
          while ((sepIdx = buffer.indexOf("\n\n")) !== -1) {
            const rawEvent = buffer.slice(0, sepIdx);
            buffer = buffer.slice(sepIdx + 2);
            const dataLine = rawEvent
              .split("\n")
              .find((l) => l.startsWith("data:"));
            if (!dataLine) continue;
            const json = dataLine.slice(5).trim();
            if (!json) continue;
            try {
              const env = JSON.parse(json) as SseEnvelope;
              enqueue(env);
            } catch {
              // ignore malformed event
            }
          }
        }
      } catch (err) {
        if ((err as DOMException)?.name === "AbortError") return;
        setState((prev) => ({
          ...prev,
          status: "error",
          error: (err as Error).message ?? "Network error",
        }));
      }
    },
    [enqueue, reset]
  );

  return { state, startDebate, reset };
}
