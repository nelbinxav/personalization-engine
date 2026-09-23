import pytest

from app.ingest.csv_loader import IngestError, parse_csv


def test_parses_plain_csv():
    headers, rows = parse_csv(b"name,company\nAda,Analytical\nGrace,Navy\n")
    assert headers == ["name", "company"]
    assert rows == [
        {"name": "Ada", "company": "Analytical"},
        {"name": "Grace", "company": "Navy"},
    ]


def test_strips_the_excel_bom():
    headers, _ = parse_csv("﻿name,company\nAda,Analytical\n".encode("utf-8"))
    assert headers[0] == "name"


def test_handles_semicolon_and_tab_exports():
    headers, rows = parse_csv(b"name;company\nAda;Analytical\n")
    assert headers == ["name", "company"]
    assert rows[0]["company"] == "Analytical"

    headers, rows = parse_csv(b"name\tcompany\nAda\tAnalytical\n")
    assert headers == ["name", "company"]


def test_drops_blank_rows_but_keeps_partial_ones():
    _, rows = parse_csv(b"name,company\nAda,Analytical\n,\nGrace,\n")
    assert len(rows) == 2
    assert rows[1] == {"name": "Grace", "company": ""}


def test_falls_back_to_cp1252_for_non_utf8_bytes():
    # Latin-1 encoded name, as exported by older Excel on Windows.
    _, rows = parse_csv("name,company\nRené,Café\n".encode("cp1252"))
    assert rows[0]["name"] == "René"


def test_rejects_empty_and_headerless_files():
    with pytest.raises(IngestError):
        parse_csv(b"")
    with pytest.raises(IngestError):
        parse_csv(b"name,company\n")
