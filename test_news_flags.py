"""Self-check for the news safety-filter keyword screen (config.red_flags_in).
No network, no cache - pure keyword/guard logic, which is the only tricky part. Run: python test_news_flags.py"""
from config import red_flags_in


def test_red_flags():
    # Genuine red flags fire.
    assert "Regulatory / legal" in red_flags_in("SEBI adjudication order and penalty imposed on the company")
    assert "Distress / dilution" in red_flags_in("Invocation of pledge over promoter shares")
    assert "Distress / dilution" in red_flags_in("Company admitted under IBC, NCLT initiates insolvency")
    assert "Rating downgrade" in red_flags_in("CRISIL revised rating: downgrade to BB with negative outlook")
    assert "Governance exit" in red_flags_in("Resignation of the Managing Director with immediate effect")
    assert "Accounting concern" in red_flags_in("Auditor issues qualified opinion; restatement of accounts")

    # Guards cancel routine paperwork that happens to contain a keyword.
    assert "Rating downgrade" not in red_flags_in("Rating upgrade to AA, outlook stable")
    assert "Rating downgrade" not in red_flags_in("Agency reaffirm the existing rating, no change")
    assert "Governance exit" not in red_flags_in("Resignation of Company Secretary and compliance officer")
    assert "Distress / dilution" not in red_flags_in("Release of pledge over 10,000 shares")
    assert "Distress / dilution" not in red_flags_in("Disclosure of defaults on payment - NIL default")

    # Clean routine filings flag nothing.
    assert red_flags_in("Outcome of Board Meeting - dividend declared") == []
    assert red_flags_in("Intimation of analyst meet") == []
    assert red_flags_in("") == []
    print("test_news_flags OK")


if __name__ == "__main__":
    test_red_flags()
