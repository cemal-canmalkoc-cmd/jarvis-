"""Ausgaben-Sperre: ohne Budget startet Jarvis nichts Kostenpflichtiges von selbst."""
from datetime import datetime
from types import SimpleNamespace

from jarvis import autopilot, brain, budget, config, store


def test_cost_counting(monkeypatch):
    usage = SimpleNamespace(input_tokens=1_000_000, output_tokens=0, cache_creation_input_tokens=0,
                            cache_read_input_tokens=0, server_tool_use=SimpleNamespace(web_search_requests=3))
    assert round(budget.cost_of("claude-haiku-5-5", usage), 4) == round(0.10 + 0.03, 4)
    fake = SimpleNamespace(messages=SimpleNamespace(create=lambda **kw: SimpleNamespace(usage=usage, content=[])))
    monkeypatch.setattr(brain, "client", lambda: fake)
    before = budget.today_spend()
    brain.create(model="claude-haiku-5-5", max_tokens=1, messages=[])
    assert round(budget.today_spend() - before, 4) == 0.13


def test_no_budget_means_ask_not_spend(monkeypatch):
    monkeypatch.setattr(config, "DAILY_BUDGET_USD", 0.0)
    ran = []
    monkeypatch.setattr(autopilot, "morning", lambda force=False: ran.append("morning"))
    monkeypatch.setattr(autopilot, "day_round", lambda now=None: ran.append("day"))
    monkeypatch.setattr(autopilot, "_now", lambda: datetime(2031, 5, 5, 11, 0))
    conn = store.connect()
    store.set_state(conn, "morning", "")
    autopilot.tick()
    assert ran == []
    texts = [n["text"] for n in store.notifications(conn, 5)]
    assert any("Soll ich heute nach Kandidaten suchen" in t for t in texts)
    assert any("Inserat" in t and "Soll ich" in t for t in texts)


def test_budget_allows_auto(monkeypatch):
    monkeypatch.setattr(config, "DAILY_BUDGET_USD", 100.0)
    assert budget.auto_allowed(0.5)
    monkeypatch.setattr(config, "DAILY_BUDGET_USD", 0.0)
    assert not budget.auto_allowed(0.01)


def test_ensure_minimum_stops_when_found_or_cap(monkeypatch):
    from jarvis.models import Assessment, ScoredCandidate
    from jarvis.scoring import score
    monkeypatch.setattr(config, "DAILY_MINIMUM", 1)
    monkeypatch.setattr(config, "MINIMUM_MAX_USD", 0.30)
    calls = []

    def fake_run(**kw):
        calls.append(kw["web_focuses"])
        budget.record("claude-haiku-5-5", SimpleNamespace(usage=SimpleNamespace(
            input_tokens=100_000, output_tokens=0, server_tool_use=SimpleNamespace(web_search_requests=5))))
        if len(calls) == 2:   # erst in der zweiten Runde wird jemand gefunden
            a = Assessment(full_name=f"Neu {len(calls)}", category="pflege", nursing_field="Psychiatrie",
                           has_diploma_certificate=True, german_level="C1", summary=f"neu {datetime.now()}")
            p, t, r, m = score(a)
            store.upsert(store.connect(), ScoredCandidate(assessment=a, source="https://x", score=p, tier=t,
                                                          reasons=r, missing=m))
        return {}
    monkeypatch.setattr(autopilot.pipeline, "run", fake_run)
    conn = store.connect()
    conn.execute("DELETE FROM candidates WHERE found_on=?", (__import__("datetime").date.today().isoformat(),))
    conn.commit()
    r = autopilot.ensure_minimum(datetime(2031, 5, 5, 9))
    assert r["gefunden_heute"] >= 1 and r["runden"] == 2 and calls[0] != calls[1]

    calls.clear()
    monkeypatch.setattr(config, "DAILY_MINIMUM", 99)
    r = autopilot.ensure_minimum(datetime(2031, 5, 5, 13))
    assert r["kosten"] <= 0.30 + 0.06 and r["runden"] < 8   # Kostengrenze stoppt die Suche
