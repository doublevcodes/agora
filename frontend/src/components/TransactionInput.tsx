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
    label: "Fraud — Nexus Capital",
    value:
      "04/30 NEXUS CAPITAL SOLUTIONS LTD 47000.00 GBP REF:INV-2281 Consultancy services",
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
  onSubmit: (raw: string) => void;
  onReset: () => void;
}

export function TransactionInput({ disabled, onSubmit, onReset }: Props) {
  const [value, setValue] = useState("");

  const handleSubmit = () => {
    const trimmed = value.trim();
    if (!trimmed) return;
    onSubmit(trimmed);
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
            disabled={disabled || !value.trim()}
          >
            Run Debate
          </button>
        </div>
      </div>
    </section>
  );
}
