import type { AgentRole, AgentStructuredMessage } from "../types/debate";
import { confidenceToLabel } from "../lib/confidence";

interface Props {
  role: AgentRole;
  title: string;
  subtitle: string;
  messages: AgentStructuredMessage[];
  accent: string;
}

export function DebateColumn({
  role,
  title,
  subtitle,
  messages,
  accent,
}: Props) {
  const filtered = messages.filter((m) => m.role === role);

  return (
    <section
      className={`debate-column debate-column-${role}`}
      style={{ borderTopColor: accent }}
    >
      <header className="column-header">
        <h3 style={{ color: accent }}>{title}</h3>
        <p>{subtitle}</p>
      </header>
      <div className="message-list">
        {filtered.length === 0 && (
          <div className="empty-message">Awaiting opening argument…</div>
        )}
        {filtered.map((msg) => {
          const label = confidenceToLabel(msg.confidence);
          return (
            <article
              key={`${msg.role}-${msg.round}`}
              className="agent-message"
              style={{ borderLeftColor: accent }}
            >
              <div className="agent-message-meta">
                <span className="round-tag">Round {msg.round}</span>
                <span className={`stance-tag stance-${msg.stance}`}>
                  {msg.stance}
                </span>
                <span className={`confidence-tag confidence-${label.toLowerCase()}`}>
                  Confidence: {label}
                </span>
                {!msg.structured_available && (
                  <span className="warn-tag">unstructured</span>
                )}
              </div>
              <p className="agent-message-text">{msg.text}</p>
              {msg.risk_tags.length > 0 && (
                <div className="risk-tag-row">
                  {msg.risk_tags.map((rt) => (
                    <span key={rt} className="risk-chip">
                      {rt}
                    </span>
                  ))}
                </div>
              )}
            </article>
          );
        })}
      </div>
    </section>
  );
}
