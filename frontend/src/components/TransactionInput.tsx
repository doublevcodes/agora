import { useState } from "react";

const DEMOS: Array<{ key: string; label: string; value: string }> = [
  {
    key: "clean",
    label: "Clean — AWS",
    value:
      "04/30 AMAZON WEB SERVICES 340.00 GBP REF:INV-AWS-9923 Monthly cloud infrastructure",
  },
  {
    key: "fraud",
    label: "Fraud — AWS spoof",
    value:
      "04/30 AMAZ0N WEB SERVICES 47000.00 GBP REF:INV-AWS-2281 Urgent infrastructure payment",
  },
  {
    key: "ambiguous",
    label: "Ambiguous — Briefcase",
    value:
      "04/30 BRIEFCASE TECHNOLOGIES 8500.00 GBP REF:INV-Q1-LICENSE Q1 platform licensing end of quarter reconciliation",
  },
];

interface Props {
  disabled?: boolean;
  onSubmit: (
    raw: string,
    escalationEmail?: string,
    escalationThreshold?: number
  ) => void;
  onReset: () => void;
}

export function TransactionInput({ disabled, onSubmit, onReset }: Props) {
  const [value, setValue] = useState("");
  const [escalationEmail, setEscalationEmail] = useState(
    (import.meta.env.VITE_ESCALATION_EMAIL as string | undefined) ?? ""
  );
  const [escalationThreshold, setEscalationThreshold] = useState("");
  const trimmedEmail = escalationEmail.trim();
  const trimmedThreshold = escalationThreshold.trim();
  const emailIsValid =
    trimmedEmail.length === 0 || /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(trimmedEmail);
  const parsedThreshold =
    trimmedThreshold.length > 0 ? Number(trimmedThreshold) : null;
  const thresholdIsValid =
    parsedThreshold === null ||
    (Number.isFinite(parsedThreshold) && parsedThreshold > 0);
  const emailError =
    trimmedEmail.length > 0 && !emailIsValid
      ? "Enter a valid email address (e.g. ops@example.com)."
      : null;
  const thresholdError =
    trimmedThreshold.length > 0 && !thresholdIsValid
      ? "Enter a positive number (e.g. 10000)."
      : null;

  const handleSubmit = () => {
    const trimmed = value.trim();
    if (!trimmed || !emailIsValid || !thresholdIsValid) return;
    const targetEmail = trimmedEmail;
    onSubmit(trimmed, targetEmail || undefined, parsedThreshold ?? undefined);
  };

  return (
    <section className="input-card">
      <h2 className="input-title">Transaction</h2>
      <p className="input-subtitle">
        Paste a raw bank statement line. Hermes argues for, Nemesis argues
        against, Verdict decides.
      </p>
      <textarea
        className="input-textarea"
        placeholder="04/30 ACME LIMITED 1250.00 GBP REF:INV-001 ..."
        value={value}
        onChange={(e) => setValue(e.target.value)}
        rows={3}
        disabled={disabled}
      />
      <div className="input-email-row">
        <label className="input-email-label" htmlFor="escalation-email">
          Escalation delivery email
        </label>
        <input
          id="escalation-email"
          className="input-email"
          type="email"
          placeholder="ops@example.com"
          value={escalationEmail}
          onChange={(e) => setEscalationEmail(e.target.value)}
          disabled={disabled}
        />
        {emailError && <p className="input-email-error">{emailError}</p>}
      </div>
      <div className="input-email-row">
        <label className="input-email-label" htmlFor="escalation-threshold">
          Payment escalation threshold
        </label>
        <input
          id="escalation-threshold"
          className="input-email"
          type="number"
          min="0"
          step="0.01"
          placeholder="10000"
          value={escalationThreshold}
          onChange={(e) => setEscalationThreshold(e.target.value)}
          disabled={disabled}
        />
        {thresholdError && <p className="input-email-error">{thresholdError}</p>}
      </div>
      <div className="input-actions">
        <div className="demo-group">
          {DEMOS.map((d) => (
            <button
              key={d.key}
              className="demo-btn"
              onClick={() => setValue(d.value)}
              disabled={disabled}
              type="button"
            >
              {d.label}
            </button>
          ))}
        </div>
        <div className="primary-actions">
          <button
            type="button"
            className="reset-btn"
            onClick={() => {
              setValue("");
              setEscalationEmail("");
              setEscalationThreshold("");
              onReset();
            }}
            disabled={disabled}
          >
            Reset
          </button>
          <button
            type="button"
            className="submit-btn"
            onClick={handleSubmit}
            disabled={
              disabled || !value.trim() || !emailIsValid || !thresholdIsValid
            }
          >
            Run Debate
          </button>
        </div>
      </div>
    </section>
  );
}
