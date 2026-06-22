from datetime import datetime, timedelta, timezone

from app.database.db import get_connection
from app.services.chore_service import ChoreService


def _insert_person(name: str) -> int:
    now = datetime.now(timezone.utc).isoformat()
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO persons(name, created_at, updated_at) VALUES (?, ?, ?)",
            (name, now, now),
        )
        return cur.lastrowid


def _insert_completion(task_id: int, person_id: int, completed_at_iso: str) -> None:
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO chore_completions(task_id, person_id, completed_at) VALUES (?, ?, ?)",
            (task_id, person_id, completed_at_iso),
        )


def test_create_list_soft_delete(temp_db):
    svc = ChoreService()
    task = svc.create_task("Treppe saugen", "🧹")
    assert task["active"] is True
    assert task["sort_order"] == 0

    task2 = svc.create_task("Müll rausbringen")
    assert task2["sort_order"] == 1

    assert [t["id"] for t in svc.list_tasks()] == [task["id"], task2["id"]]

    assert svc.delete_task(task["id"]) is True
    active_ids = [t["id"] for t in svc.list_tasks()]
    assert task["id"] not in active_ids
    assert task2["id"] in active_ids

    all_tasks = {t["id"]: t for t in svc.list_tasks(include_inactive=True)}
    assert all_tasks[task["id"]]["active"] is False


def test_log_completion_and_task_stats_week(temp_db):
    svc = ChoreService()
    task = svc.create_task("Geschirr einräumen")
    dennis = _insert_person("Dennis")
    anna = _insert_person("Anna")

    svc.log_completion(task["id"], dennis)
    svc.log_completion(task["id"], dennis)
    svc.log_completion(task["id"], anna)

    stats = svc.task_stats(task["id"], "week")
    assert stats["task_name"] == "Geschirr einräumen"
    by_person = {p["person_id"]: p["count"] for p in stats["persons"]}
    assert by_person == {dennis: 2, anna: 1}
    assert stats["leader"]["person_id"] == dennis
    assert stats["leader"]["count"] == 2


def test_task_stats_week_boundary(temp_db):
    svc = ChoreService()
    tz = svc._local_tz()
    now_local = datetime.now(tz)
    person_id = _insert_person("Dennis")
    task = svc.create_task("Aufgabe Woche")

    start = svc._period_start_utc("week", now_local)
    _insert_completion(task["id"], person_id, (start - timedelta(seconds=1)).isoformat())
    _insert_completion(task["id"], person_id, (start + timedelta(seconds=1)).isoformat())

    stats = svc.task_stats(task["id"], "week")
    assert len(stats["persons"]) == 1
    assert stats["persons"][0]["person_id"] == person_id
    assert stats["persons"][0]["count"] == 1


def test_task_stats_month_boundary(temp_db):
    svc = ChoreService()
    tz = svc._local_tz()
    now_local = datetime.now(tz)
    person_id = _insert_person("Dennis")
    task = svc.create_task("Aufgabe Monat")

    start = svc._period_start_utc("month", now_local)
    _insert_completion(task["id"], person_id, (start - timedelta(seconds=1)).isoformat())
    _insert_completion(task["id"], person_id, (start + timedelta(seconds=1)).isoformat())

    stats = svc.task_stats(task["id"], "month")
    assert len(stats["persons"]) == 1
    assert stats["persons"][0]["person_id"] == person_id
    assert stats["persons"][0]["count"] == 1


def test_task_stats_year_boundary(temp_db):
    svc = ChoreService()
    tz = svc._local_tz()
    now_local = datetime.now(tz)
    person_id = _insert_person("Dennis")
    task = svc.create_task("Aufgabe Jahr")

    start = svc._period_start_utc("year", now_local)
    _insert_completion(task["id"], person_id, (start - timedelta(seconds=1)).isoformat())
    _insert_completion(task["id"], person_id, (start + timedelta(seconds=1)).isoformat())

    stats = svc.task_stats(task["id"], "year")
    assert len(stats["persons"]) == 1
    assert stats["persons"][0]["person_id"] == person_id
    assert stats["persons"][0]["count"] == 1


def test_task_stats_unknown_task_returns_none(temp_db):
    svc = ChoreService()
    assert svc.task_stats(999, "week") is None


def test_overall_weekly_stats_combines_active_tasks(temp_db):
    svc = ChoreService()
    task1 = svc.create_task("Treppe saugen")
    task2 = svc.create_task("Müll rausbringen")
    inactive_task = svc.create_task("Alte Aufgabe")
    svc.delete_task(inactive_task["id"])

    dennis = _insert_person("Dennis")
    anna = _insert_person("Anna")

    svc.log_completion(task1["id"], dennis)
    svc.log_completion(task1["id"], dennis)
    svc.log_completion(task2["id"], dennis)
    svc.log_completion(task1["id"], anna)
    svc.log_completion(inactive_task["id"], anna)

    stats = svc.overall_weekly_stats()
    by_person = {p["person_id"]: p["total_completions"] for p in stats["persons"]}
    assert by_person == {dennis: 3, anna: 1}
    assert stats["leader"]["person_id"] == dennis
    assert stats["leader"]["total_completions"] == 3


def test_delete_completion(temp_db):
    svc = ChoreService()
    task = svc.create_task("Treppe saugen")
    dennis = _insert_person("Dennis")

    entry = svc.log_completion(task["id"], dennis)
    assert svc.task_stats(task["id"], "week")["persons"][0]["count"] == 1

    assert svc.delete_completion(entry["id"]) is True
    stats = svc.task_stats(task["id"], "week")
    assert stats["persons"] == []
    assert stats["leader"] is None

    assert svc.delete_completion(entry["id"]) is False


def test_list_completions_filters_and_delete(temp_db):
    svc = ChoreService()
    task = svc.create_task("Treppe saugen")
    dennis = _insert_person("Dennis")
    anna = _insert_person("Anna")

    first = svc.log_completion(task["id"], dennis)
    second = svc.log_completion(task["id"], anna)

    recent = svc.list_completions(task["id"], "week")
    assert [r["id"] for r in recent] == [second["id"], first["id"]]
    assert recent[0]["name"] == "Anna"
    assert recent[1]["name"] == "Dennis"

    dennis_only = svc.list_completions(task["id"], "week", person_id=dennis)
    assert [r["id"] for r in dennis_only] == [first["id"]]

    svc.delete_completion(second["id"])
    recent = svc.list_completions(task["id"], "week")
    assert [r["id"] for r in recent] == [first["id"]]
