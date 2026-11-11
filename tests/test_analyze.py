from datetime import timedelta

from conftest import utc
from oncall_handoff.analyze import alert_key, analyze, find_flaky, find_threads
from oncall_handoff.sources import Message, Page, Shift, Ticket, load_directory

START, END = utc(2026, 3, 2, 9), utc(2026, 3, 3, 9)


def page(id, title, minute, *, service="api", minutes=5, status="resolved", urgency="high"):
    created = START + timedelta(minutes=minute)
    resolved = created + timedelta(minutes=minutes) if status == "resolved" else None
    return Page(id, title, service, urgency, status, created, resolved)


def test_alert_key_ignores_numbers_and_ids():
    assert alert_key("p99 latency above 800ms") == alert_key("p99  latency above 920ms")
    assert alert_key("Disk 91% on node-3") == alert_key("Disk 88.5% on node-12")
    assert alert_key("job deadbeef01 failed") == alert_key("job 0123abcd99 failed")
    assert alert_key("disk full") != alert_key("disk slow")


def test_flaky_groups_by_service_and_normalised_title():
    pages = [page("1", "latency above 800ms", 0), page("2", "latency above 900ms", 60),
             page("3", "latency above 900ms", 90, service="web"), page("4", "disk full", 120)]
    flaky = find_flaky(pages, threshold=2)
    assert [(f.service, f.count) for f in flaky] == [("api", 2)]
    assert flaky[0].flapping and flaky[0].median_minutes == 5 and not flaky[0].still_open
    assert find_flaky(pages, threshold=3) == []


def test_slow_repeats_are_flaky_but_not_flapping_and_open_is_noted():
    pages = [page("1", "queue deep", 0, minutes=50), page("2", "queue deep", 100, minutes=70),
             page("3", "queue deep", 300, status="triggered")]
    (f,) = find_flaky(pages, threshold=2)
    assert f.count == 3 and not f.flapping and f.still_open and f.median_minutes == 60


def test_window_carry_over_and_open_ordering():
    shift = Shift(pages=[
        page("old-open", "replica lag", -600, status="acknowledged"),
        page("old-done", "ancient", -600),
        page("low", "cert expiring", 30, status="triggered", urgency="low"),
        page("high", "db down", 60, status="triggered"),
        page("future", "after the window", 60 * 30),
    ])
    r = analyze(shift, START, END)
    assert [p.id for p in r.pages] == ["low", "high"]
    assert [p.id for p in r.carried_over] == ["old-open"]
    assert [p.id for p in r.open_pages] == ["old-open", "high", "low"]  # high urgency first


def test_recently_resolved_high_urgency_pages_are_flagged():
    late = Page("late", "queue deep", "worker", "high", "resolved", END - timedelta(hours=1), END - timedelta(minutes=30))
    early = page("early", "db down", 10)
    low = Page("low", "disk", "worker", "low", "resolved", END - timedelta(hours=1), END - timedelta(minutes=30))
    r = analyze(Shift(pages=[early, late, low]), START, END)
    assert [p.id for p in r.recently_resolved] == ["late"]


def test_tickets_are_filtered_by_activity_in_window():
    def ticket(key, status, updated, priority="P3"):
        return Ticket(key, key, status, priority, updated=updated)

    shift = Shift(tickets=[
        ticket("B-2", "Open", START + timedelta(hours=1)),
        ticket("A-1", "Open", START + timedelta(hours=2), "P1"),
        ticket("C-3", "Done", START + timedelta(hours=3)),
        ticket("D-4", "Open", START - timedelta(days=9)),
        Ticket("E-5", "no dates", "Open"),
    ])
    r = analyze(shift, START, END)
    assert [t.key for t in r.open_tickets] == ["A-1", "B-2", "E-5"]  # urgent first; undated kept
    assert [t.key for t in r.closed_tickets] == ["C-3"]


def test_watch_messages_match_handoff_phrases_inside_window_only():
    def msg(minute, text):
        return Message(START + timedelta(minutes=minute), "priya", text, "ops", str(minute))

    shift = Shift(messages=[
        msg(1, "Keep an eye on the cache nodes"), msg(2, "lunch?"), msg(3, "applied a temporary workaround"),
        msg(4, "TODO: rotate the key"), msg(5, "all good now"), msg(6, "alert silenced until Monday"),
        msg(-50, "follow up on this from the previous shift"), msg(7, ""),
    ])
    r = analyze(shift, START, END)
    assert [m.text for m in r.watch_messages] == [
        "Keep an eye on the cache nodes", "applied a temporary workaround", "TODO: rotate the key",
        "alert silenced until Monday"]


def test_threads_need_three_messages_and_are_ranked_by_replies():
    def msg(minute, user, thread):
        return Message(START + timedelta(minutes=minute), user, f"m{minute}", "ops", thread)

    messages = [msg(0, "a", "t1"), msg(1, "b", "t1"), msg(2, "a", "t1"),
                msg(3, "a", "t2"), msg(4, "b", "t2"), msg(5, "c", "t2"), msg(6, "c", "t2"),
                msg(7, "a", "t3"), msg(8, "b", "t3")]
    threads = find_threads(messages)
    assert [(t.text, t.replies, t.participants) for t in threads] == [
        ("m3", 3, ["a", "b", "c"]), ("m0", 2, ["a", "b"])]


def test_empty_shift_is_quiet_and_stats_are_none():
    r = analyze(Shift(), START, END)
    assert r.quiet and r.median_minutes_to_resolve is None and r.by_service == []


def test_example_shift_end_to_end(examples):
    r = analyze(load_directory(examples), START, END)
    assert len(r.pages) == 7 and [p.id for p in r.carried_over] == ["P1001"]
    assert [(f.service, f.count, f.flapping) for f in r.flaky] == [("checkout-api", 3, True)]
    assert [p.id for p in r.recently_resolved] == ["P1008"]
    assert [t.key for t in r.open_tickets] == ["OPS-412", "OPS-409"]
    assert [t.key for t in r.closed_tickets] == ["OPS-405"]
    assert len(r.watch_messages) == 4 and r.threads[0].replies == 4
    assert r.by_service[0] == ("checkout-api", 3)
