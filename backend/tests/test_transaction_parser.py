from app.core.transaction_parser import parse_transaction


def test_parses_clean_aws_line():
    tx = parse_transaction(
        "04/30 AMAZON WEB SERVICES 340.00 GBP REF:INV-AWS-9923 Monthly cloud infrastructure"
    )
    assert tx.date == "04/30"
    assert "AMAZON WEB SERVICES" in tx.vendor
    assert tx.amount == 340.00
    assert tx.currency == "GBP"
    assert tx.reference == "INV-AWS-9923"
    assert tx.notes is not None
    assert "Monthly" in tx.notes


def test_parses_fraud_line():
    tx = parse_transaction(
        "04/30 AMAZ0N WEB SERVICES 47000.00 GBP REF:INV-AWS-2281 Urgent infrastructure payment"
    )
    assert tx.amount == 47000.00
    assert tx.currency == "GBP"
    assert "AMAZ0N WEB SERVICES" in tx.vendor
    assert tx.reference == "INV-AWS-2281"


def test_parses_ambiguous_line():
    tx = parse_transaction(
        "04/30 BRIEFCASE TECHNOLOGIES 8500.00 GBP REF:INV-Q1-LICENSE Q1 platform licensing end of quarter reconciliation"
    )
    assert tx.amount == 8500.00
    assert tx.currency == "GBP"
    assert tx.vendor == "BRIEFCASE TECHNOLOGIES"
    assert tx.reference == "INV-Q1-LICENSE"
    assert tx.notes is not None
    assert tx.notes.startswith("Q1 ")


def test_handles_missing_currency():
    tx = parse_transaction("04/30 ACME CORP 250.00 REF:INV-1")
    assert tx.amount == 250.0
    assert tx.reference == "INV-1"
    assert "ACME CORP" in tx.vendor
