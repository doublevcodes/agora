import type { ParsedTransaction, SpecterBrief } from "../types/debate";

interface Props {
  brief: SpecterBrief | null;
  transaction: ParsedTransaction | null;
  riskLevel: string | null;
}

export function SpecterBriefCard({ brief, transaction, riskLevel }: Props) {
  if (!brief && !transaction) return null;

  const formattedAmount =
    transaction?.amount != null
      ? new Intl.NumberFormat(undefined, {
          style: "currency",
          currency: transaction.currency ?? "USD",
          maximumFractionDigits: 2,
        }).format(transaction.amount)
      : "—";

  const conciseSummary = brief?.summary
    ? brief.summary
        .split(/(?<=[.!?])\s+|:\s+/)
        .map((part) => part.trim())
        .find(Boolean) ?? ""
    : "";

  return (
    <section className="specter-card">
      <header className="specter-header">
        <div>
          <span className="specter-tag">Specter Intelligence</span>
          <h3 className="specter-title">Vendor intelligence snapshot</h3>
        </div>
        <div className="specter-badge-row">
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
        </div>
      </header>

      {transaction && (
        <div className="tx-grid">
          <div>
            <span className="tx-label">Vendor</span>
            <span className="tx-value">{transaction.vendor}</span>
          </div>
          <div>
            <span className="tx-label">Amount</span>
            <span className="tx-value">{formattedAmount}</span>
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
          <div className="specter-metrics">
            <div className="specter-metric">
              <span className="specter-metric-label">Vendor Match</span>
              <span className="specter-metric-value">
                {brief.vendor_found ? "Found" : "Unknown"}
              </span>
            </div>
            <div className="specter-metric">
              <span className="specter-metric-label">Legitimacy Score</span>
              <span className="specter-metric-value">
                {brief.legitimacy_score ?? "—"}
              </span>
            </div>
            <div className="specter-metric">
              <span className="specter-metric-label">Domain</span>
              <span className="specter-metric-value">{brief.domain ?? "—"}</span>
            </div>
            <div className="specter-metric">
              <span className="specter-metric-label">Founded</span>
              <span className="specter-metric-value">
                {brief.founded_year ?? "—"}
              </span>
            </div>
          </div>
          <p className="specter-note">
            {brief.status === "available"
              ? conciseSummary || "Specter brief retrieved successfully."
              : "Specter brief is currently unavailable. Proceed with manual verification for this vendor."}
          </p>
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
