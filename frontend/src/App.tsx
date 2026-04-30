import { TransactionInput } from "./components/TransactionInput";
import { SpecterBriefCard } from "./components/SpecterBriefCard";
import { DebateColumn } from "./components/DebateColumn";
import { VerdictCard } from "./components/VerdictCard";
import { useDebateStream } from "./hooks/useDebateStream";

const HERMES_GOLD = "#F5A623";
const NEMESIS_RED = "#C0392B";

export function App() {
  const { state, startDebate, reset } = useDebateStream();

  const isBusy = state.status === "starting" || state.status === "streaming";

  return (
    <div className="app-shell">
      <header className="app-header">
        <h1>Agora</h1>
        <p className="app-tagline">
          A two-agent adversarial payment authorisation system. Hermes argues
          for, Nemesis argues against, Verdict decides — humans only intervene
          when the agents truly disagree.
        </p>
      </header>

      <TransactionInput
        disabled={isBusy}
        onSubmit={(raw, escalationEmail) => startDebate(raw, 6, escalationEmail)}
        onReset={reset}
      />

      {state.statusMessages.length > 0 && (
        <div className="status-strip">
          {state.statusMessages.slice(-3).map((m, idx) => (
            <span key={`${m}-${idx}`} className="status-pill">
              {m}
            </span>
          ))}
          {state.routingRationale && (
            <span className="status-pill subtle">
              {state.routingRationale}
            </span>
          )}
        </div>
      )}

      <SpecterBriefCard
        brief={state.brief}
        transaction={state.transaction}
        riskLevel={state.riskLevel}
      />

      {state.error && <div className="error-banner">Error: {state.error}</div>}

      <main className="debate-grid">
        <DebateColumn
          role="hermes"
          title="Hermes"
          subtitle="Payment Advocate"
          messages={state.messages}
          accent={HERMES_GOLD}
        />
        <DebateColumn
          role="nemesis"
          title="Nemesis"
          subtitle="Payment Prosecutor"
          messages={state.messages}
          accent={NEMESIS_RED}
        />
      </main>

      <VerdictCard verdict={state.verdict} />

      <footer className="app-footer">
        <span>Trace: {state.traceId ?? "—"}</span>
        <span>Status: {state.status}</span>
      </footer>
    </div>
  );
}
