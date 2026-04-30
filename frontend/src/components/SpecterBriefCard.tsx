import type { ParsedTransaction, SpecterBrief } from "../types/debate";

interface Props {
  brief: SpecterBrief | null;
  transaction: ParsedTransaction | null;
  riskLevel: string | null;
}

export function SpecterBriefCard({ brief, transaction, riskLevel }: Props) {
  if (!brief && !transaction) return null;

  return (
    <section className="specter-card">
      <header className="specter-header">
        <span className="specter-tag">Specter Intelligence</span>
        {brief && (
          <span
            className={`specter-status specter-status-${
              brief.status === "available" ? "ok" : "off"
            }`}
          >
            {brief.status === "available" ? "Retrieved" : "Unavailable"}
          </span>
        )}
        {riskLevel && (
          <span className={`risk-badge risk-${riskLevel}`}>
            Risk: {riskLevel}
          </span>
        )}
      </header>

      {transaction && (
        <div className="tx-grid">
          <div>
            <span className="tx-label">Vendor</span>
            <span className="tx-value">{transaction.vendor}</span>
          </div>
          <div>
            <span className="tx-label">Amount</span>
            <span className="tx-value">
              {transaction.amount != null
                ? `${transaction.amount.toFixed(2)}`
                : "—"}{" "}
              {transaction.currency ?? ""}
            </span>
          </div>
          <div>
            <span className="tx-label">Date</span>
            <span className="tx-value">{transaction.date ?? "—"}</span>
          </div>
          <div>
            <span className="tx-label">Reference</span>
            <span className="tx-value">{transaction.reference ?? "—"}</span>
          </div>
        </div>
      )}

      {brief && (
        <div className="specter-summary">
          <p>{brief.summary}</p>
          {brief.red_flags.length > 0 && (
            <div className="redflag-row">
              {brief.red_flags.map((rf) => (
                <span key={rf} className="redflag-chip">
                  {rf}
                </span>
              ))}
            </div>
          )}
        </div>
      )}
    </section>
  );
}
