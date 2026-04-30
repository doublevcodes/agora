from __future__ import annotations

from typing import Literal

ConfidenceLabel = Literal["Low", "Medium", "High"]


def confidence_to_label(confidence: float) -> ConfidenceLabel:
    """Map a 0..1 confidence float to a human-readable label.

    Buckets:
      Low:    0.00 - 0.33
      Medium: 0.34 - 0.66
      High:   0.67 - 1.00
    """
    c = max(0.0, min(1.0, float(confidence)))
    if c <= 0.33:
        return "Low"
    if c <= 0.66:
        return "Medium"
    return "High"
