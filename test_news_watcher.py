"""Offline checks for the news watcher filter (no network, no Telegram).

The filter is the whole design: too loose and you mute it inside a week, too tight and you
miss the one filing that mattered. These pin the specific noise classes measured on 5 days of
real NSE filings.
"""
from datetime import datetime

import news_watcher as nw


def _row(desc, text="", symbol="AAA", seq=None):
    return {'symbol': symbol, 'desc': desc, 'attchmntText': text,
            'an_dt': '31-Jul-2026 22:55:18', 'seq_id': seq}


def test_material_events_pass():
    for desc in ('Acquisition', 'Scheme of Arrangement', 'Open Offer', 'Buyback'):
        assert nw.is_high_signal(_row(desc)), f"{desc} should alert"
    # Substance lives in the filing text, not always the category.
    assert nw.is_high_signal(_row('General Updates', 'board approved the merger of X with Y'))


def test_board_meeting_outcomes_are_dropped():
    """187 of 390 matches under the old flat list - the single biggest noise source."""
    assert not nw.is_high_signal(_row('Outcome of Board Meeting',
                                      'financial results for the quarter were approved'))


def test_routine_appointments_are_dropped():
    assert not nw.is_high_signal(
        _row('General Updates', 're-appointment of Mr N as Whole-Time Director and CFO')), \
        "a re-appointment is not a leadership change"
    assert not nw.is_high_signal(_row('Appointment', 'appointment of statutory auditor'))
    assert not nw.is_high_signal(_row('Appointment', 'appointment of company secretary'))


def test_senior_leadership_changes_pass():
    assert nw.is_high_signal(_row('Resignation', 'resignation of the Managing Director'))
    assert nw.is_high_signal(_row('Change in Management', 'the Chief Executive has stepped down'))
    assert not nw.is_high_signal(_row('Resignation', 'resignation of the compliance officer'))


def test_routine_rating_reaffirmations_are_dropped():
    assert not nw.is_high_signal(_row('Credit Rating', 'rating reaffirmed at AA stable'))
    assert nw.is_high_signal(_row('Credit Rating', 'rating downgraded to BBB'))
    assert nw.is_high_signal(_row('Credit Rating', 'placed on rating watch with negative implications'))


def test_fingerprints_are_stable_and_distinct():
    a, b = _row('Acquisition', seq='123'), _row('Acquisition', seq='123')
    assert nw._fingerprint(a) == nw._fingerprint(b), "same filing must dedupe"
    assert nw._fingerprint(_row('Acquisition', seq='124')) != nw._fingerprint(a)
    # Missing seq_id must still produce a stable id rather than colliding or crashing.
    c = _row('Acquisition', 'text', symbol='BBB')
    assert nw._fingerprint(c) == nw._fingerprint(_row('Acquisition', 'text', symbol='BBB'))
    assert nw._fingerprint(c) != nw._fingerprint(_row('Acquisition', 'text', symbol='CCC'))


def test_active_window_covers_evening_filings():
    """Filings land well after the 15:30 close - that is the point of this watcher."""
    t = lambda h, m, d=3: datetime(2026, 8, d, h, m, tzinfo=nw.IST)
    assert nw.in_active_window(t(20, 0)), "8pm filings must be collected"
    assert nw.in_active_window(t(9, 0))
    assert not nw.in_active_window(t(23, 45))
    assert not nw.in_active_window(t(6, 0))
    assert not nw.in_active_window(t(12, 0, d=1)), "Saturday"




def _no_triage():
    """Disable the LLM so grouping/fallback can be tested offline."""
    original = nw.analyze_group
    nw.analyze_group = lambda symbol, filings, timeout=45: None
    return original


def test_triage_failure_falls_back_to_urgent():
    """A filing must never be dropped because the model was slow or rate-limited. No triage
    means treat it as urgent and send the raw text - the old behaviour."""
    original = _no_triage()
    try:
        alerts = nw.build_alerts([_row('Acquisition', 'acquired a business', seq='9001')], {})
        assert len(alerts) == 1
        assert alerts[0][2] == 'HIGH', "untriaged filing must default to urgent"
        assert 'acquired a business' in alerts[0][1]
    finally:
        nw.analyze_group = original


def test_same_company_filings_collapse_to_one_alert():
    """One corporate event arrives as several filings minutes apart - Nazara published four in
    one evening. Without grouping that is four notifications for one news day."""
    original = _no_triage()
    try:
        rows = [_row('Resignation', 'CEO resigned', symbol='NAZARA', seq='1'),
                _row('Press Release', 'acquisition USD 303 Million', symbol='NAZARA', seq='2'),
                _row('Appointment', 'appointed Chief Executive Officer', symbol='NAZARA', seq='3'),
                _row('Fund Raising', 'qualified institutional placement', symbol='PNGJL', seq='4')]
        alerts = nw.build_alerts(rows, {})
        assert len(alerts) == 2, f"expected one alert per company, got {len(alerts)}"
        naz = next(a for a in alerts if a[4] == 'NAZARA')
        assert len(naz[0]) == 3, "all three Nazara fingerprints must be marked seen"
        assert "3 filing(s) today" in naz[1]
        for d in ('Resignation', 'Press Release', 'Appointment'):
            assert d in naz[1], f"{d} missing from the grouped message"
    finally:
        nw.analyze_group = original


def test_digest_batches_and_sends_once():
    import os, tempfile
    nw.DIGEST_FILE = os.path.join(tempfile.mkdtemp(), 'd.json')
    sent = []
    nw.send, nw.ALLOWED = (lambda c, m: sent.append(m)), {'1'}
    day = datetime(2026, 8, 3, 15, 0, tzinfo=nw.IST)
    nw._queue_for_digest(day, 'AAA', 'MEDIUM', 'raised funds')
    assert nw.maybe_send_digest(day) == 0, "must not send before the digest hour"
    evening = datetime(2026, 8, 3, 21, 30, tzinfo=nw.IST)
    assert nw.maybe_send_digest(evening) == 1
    assert nw.maybe_send_digest(evening) == 0, "must not send the same digest twice"
    assert len(sent) == 1 and 'AAA' in sent[0]


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith('test_'):
            fn()
    print("news watcher: OK")
