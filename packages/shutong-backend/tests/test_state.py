from __future__ import annotations

from shutong_backend.state import ResearchState


def test_wake_up_empty_state(tmp_path):
    state = ResearchState(storage_dir=str(tmp_path))
    assert state.wake_up() == ""


def test_record_session_writes_diary_and_passport(tmp_path):
    state = ResearchState(storage_dir=str(tmp_path))
    passport = state.passport.create(project_name="Test", research_goals=["goal"])
    result = state.record_session(
        session_id="s1",
        topics=["topic"],
        sources=["src"],
        insights=["insight"],
        open_questions=["q"],
        passport_id=passport["passport_id"],
    )
    assert result["diary_entry_id"]
    assert result["passport_updated"] == passport["passport_id"]

    # Diary has the entry
    entries = state.diary.recent(count=1)
    assert entries and entries[0].session_id == "s1"

    # Passport merged the sources/insights/questions
    loaded = state.passport.load(passport["passport_id"])
    assert "src" in loaded["sources_consulted"]
    assert any(i.get("insight") == "insight" for i in loaded["key_insights"])
    assert any(q.get("question") == "q" for q in loaded["open_questions"])


def test_wake_up_includes_passport_and_diary(tmp_path):
    state = ResearchState(storage_dir=str(tmp_path))
    passport = state.passport.create(project_name="Test", research_goals=["goal"])
    state.record_session(
        session_id="s1",
        topics=["topic"],
        sources=["src"],
        insights=["insight"],
        open_questions=["q"],
        passport_id=passport["passport_id"],
    )
    context = state.wake_up(passport_id=passport["passport_id"])
    assert "Test" in context
    assert "Recent sessions" in context


def test_snapshot_reports_all_stores(tmp_path):
    state = ResearchState(storage_dir=str(tmp_path))
    state.passport.create(project_name="Test")
    snap = state.snapshot()
    assert set(snap.keys()) == {"passports", "graph", "diary_dates", "memory_threads"}
    assert len(snap["passports"]) == 1
