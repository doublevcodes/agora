import { useEffect, useMemo, useRef, useState } from "react";
import type { AgentRole, AgentStructuredMessage } from "../types/debate";
import { confidenceToLabel } from "../lib/confidence";

interface Props {
  role: AgentRole;
  title: string;
  subtitle: string;
  messages: AgentStructuredMessage[];
  accent: string;
}

const TYPE_SPEED_MS = 18;
const CHUNK_SIZE = 2;

type TypingPhase = "pending" | "typing" | "done";

function TypingText({
  text,
  phase,
  onComplete,
}: {
  text: string;
  phase: TypingPhase;
  onComplete: () => void;
}) {
  const [visibleChars, setVisibleChars] = useState(0);
  const onCompleteRef = useRef(onComplete);
  const isReducedMotion = useMemo(
    () =>
      typeof window !== "undefined" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches,
    []
  );
  useEffect(() => {
    onCompleteRef.current = onComplete;
  }, [onComplete]);

  useEffect(() => {
    if (phase === "done") {
      setVisibleChars(text.length);
      return;
    }
    if (phase === "pending") {
      setVisibleChars(0);
      return;
    }
    if (isReducedMotion) {
      setVisibleChars(text.length);
      onCompleteRef.current();
      return;
    }
    setVisibleChars(0);
    const timer = window.setInterval(() => {
      setVisibleChars((prev) => {
        const next = Math.min(prev + CHUNK_SIZE, text.length);
        if (next >= text.length) {
          window.clearInterval(timer);
          onCompleteRef.current();
        }
        return next;
      });
    }, TYPE_SPEED_MS);
    return () => window.clearInterval(timer);
  }, [isReducedMotion, phase, text]);

  const shownText = text.slice(0, visibleChars);
  const isTyping = phase === "typing" && shownText.length < text.length;

  return (
    <p className="agent-message-text">
      {shownText}
      {isTyping && <span className="typing-caret" aria-hidden="true" />}
    </p>
  );
}

export function DebateColumn({
  role,
  title,
  subtitle,
  messages,
  accent,
}: Props) {
  const filtered = messages.filter((m) => m.role === role);
  const [completedKeys, setCompletedKeys] = useState<Set<string>>(new Set());

  useEffect(() => {
    const validKeys = new Set(filtered.map((m) => `${m.role}-${m.round}`));
    setCompletedKeys((prev) => {
      const next = new Set<string>();
      prev.forEach((key) => {
        if (validKeys.has(key)) {
          next.add(key);
        }
      });
      return next;
    });
  }, [filtered]);

  const firstPendingIndex = filtered.findIndex(
    (msg) => !completedKeys.has(`${msg.role}-${msg.round}`)
  );

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
        {filtered.map((msg, idx) => {
          const msgKey = `${msg.role}-${msg.round}`;
          const phase: TypingPhase =
            completedKeys.has(msgKey) || firstPendingIndex === -1 || idx < firstPendingIndex
              ? "done"
              : idx === firstPendingIndex
                ? "typing"
                : "pending";
          const label = confidenceToLabel(msg.confidence);
          return (
            <article
              key={msgKey}
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
              <TypingText
                text={msg.text}
                phase={phase}
                onComplete={() => {
                  if (phase !== "typing") return;
                  setCompletedKeys((prev) => {
                    if (prev.has(msgKey)) return prev;
                    const next = new Set(prev);
                    next.add(msgKey);
                    return next;
                  });
                }}
              />
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
