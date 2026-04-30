import type { VerdictDecision } from "../types/debate";

interface Props {
  verdict: VerdictDecision | null;
}

const VERDICT_TONE: Record<string, string> = {
  APPROVE: "verdict-approve",
  REJECT: "verdict-reject",
  "ESCALATE TO HUMAN": "verdict-escalate",
};

export function VerdictCard({ verdict }: Props) {
  if (!verdict) return null;
  const cls = VERDICT_TONE[verdict.outcome] ?? "verdict-escalate";
  return (
    <section className={`verdict-card ${cls}`}>
      <span className="verdict-eyebrow">Verdict</span>
      <h2 className="verdict-outcome">{verdict.outcome}</h2>
      <p className="verdict-reason">{verdict.reason}</p>
      {verdict.source === "frontend_threshold" && (
        <p className="verdict-note">
          Escalated by frontend threshold rule.
        </p>
      )}
      {verdict.escalation_packet && (
        <details className="escalation-packet">
          <summary>Reviewer handoff packet</summary>
          <pre>{JSON.stringify(verdict.escalation_packet, null, 2)}</pre>
        </details>
      )}
    </section>
  );
}
