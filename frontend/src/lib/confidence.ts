export type ConfidenceLabel = "Low" | "Medium" | "High";

export function confidenceToLabel(confidence: number): ConfidenceLabel {
  const c = Math.max(0, Math.min(1, confidence));
  if (c <= 0.33) return "Low";
  if (c <= 0.66) return "Medium";
  return "High";
}
