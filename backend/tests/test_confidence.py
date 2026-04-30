from app.utils.confidence import confidence_to_label


def test_low_bucket():
    assert confidence_to_label(0.0) == "Low"
    assert confidence_to_label(0.33) == "Low"


def test_medium_bucket():
    assert confidence_to_label(0.34) == "Medium"
    assert confidence_to_label(0.66) == "Medium"


def test_high_bucket():
    assert confidence_to_label(0.67) == "High"
    assert confidence_to_label(1.0) == "High"


def test_clamps_outside_range():
    assert confidence_to_label(-0.5) == "Low"
    assert confidence_to_label(1.5) == "High"
