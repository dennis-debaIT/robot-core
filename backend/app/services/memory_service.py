from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone

from app.database.db import get_connection


class MemoryService:
    def build_session_context(self, person_name: str | None) -> str | None:
        if not person_name:
            return None
        parts: list[str] = []

        with get_connection() as conn:
            topic_rows = conn.execute(
                "SELECT title, mentions, last_seen FROM active_topics "
                "WHERE person_name = ? AND status = 'active' "
                "ORDER BY importance DESC, mentions DESC LIMIT 10",
                (person_name,),
            ).fetchall()
            if topic_rows:
                lines = [
                    f"- {r['title']} ({r['mentions']}x, zuletzt {r['last_seen'][:10]})"
                    for r in topic_rows
                ]
                parts.append("Aktive Gesprächsthemen:\n" + "\n".join(lines))

            day_rows = conn.execute(
                "SELECT date, topics FROM daily_summaries "
                "WHERE person_name = ? "
                "ORDER BY date DESC LIMIT 7",
                (person_name,),
            ).fetchall()
            if day_rows:
                lines = [f"- {r['date']}: {r['topics']}" for r in day_rows]
                parts.append("Tagesrückblick (letzte Tage):\n" + "\n".join(lines))

            week_rows = conn.execute(
                "SELECT week_start, summary FROM weekly_summaries "
                "WHERE person_name = ? "
                "ORDER BY week_start DESC LIMIT 26",
                (person_name,),
            ).fetchall()
            if week_rows:
                lines = [f"- {r['week_start']}: {r['summary']}" for r in week_rows]
                parts.append("Wochengedächtnis:\n" + "\n".join(lines))

        return "\n\n".join(parts) if parts else None

    def ensure_todays_daily_summary(self, person_name: str) -> None:
        today = datetime.now().strftime("%Y-%m-%d")
        today_start = f"{today}T00:00:00"
        today_end = f"{today}T23:59:59"
        now_iso = datetime.now(timezone.utc).isoformat()

        with get_connection() as conn:
            rows = conn.execute(
                "SELECT topic, SUM(score) as total_score FROM topic_mentions "
                "WHERE created_at >= ? AND created_at <= ? AND person_name = ? "
                "GROUP BY topic ORDER BY total_score DESC LIMIT 8",
                (today_start, today_end, person_name),
            ).fetchall()
            if not rows:
                return

            topics_str = ", ".join(r["topic"] for r in rows)

            msgs = conn.execute(
                "SELECT message FROM conversation_messages "
                "WHERE role = 'user' AND created_at >= ? AND created_at <= ? AND person_name = ? "
                "ORDER BY id DESC LIMIT 5",
                (today_start, today_end, person_name),
            ).fetchall()
            sample = " | ".join(m["message"][:80] for m in msgs)

            conn.execute(
                """
                INSERT INTO daily_summaries(person_name, date, topics, sample_messages, created_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(person_name, date) DO UPDATE SET
                    topics = excluded.topics,
                    sample_messages = excluded.sample_messages
                """,
                (person_name, today, topics_str, sample, now_iso),
            )

    def refresh_active_topics(self, person_name: str) -> None:
        cutoff_recent = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%dT00:00:00")
        cutoff_archive = (datetime.now() - timedelta(days=60)).strftime("%Y-%m-%dT00:00:00")
        now_iso = datetime.now(timezone.utc).isoformat()

        with get_connection() as conn:
            conn.execute(
                "UPDATE active_topics SET status = 'archived', updated_at = ? "
                "WHERE person_name = ? AND status = 'active' AND last_seen < ?",
                (now_iso, person_name, cutoff_archive),
            )

            rows = conn.execute(
                "SELECT topic, COUNT(*) as cnt, MAX(created_at) as last_seen, SUM(score) as total_score "
                "FROM topic_mentions "
                "WHERE person_name = ? AND created_at >= ? "
                "GROUP BY topic ORDER BY total_score DESC LIMIT 20",
                (person_name, cutoff_recent),
            ).fetchall()

            for row in rows:
                importance = min(1.0, 0.1 + row["cnt"] / 20.0)
                conn.execute(
                    """
                    INSERT INTO active_topics(
                        person_name, title, importance, last_seen, mentions, status, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, 'active', ?, ?)
                    ON CONFLICT(person_name, title) DO UPDATE SET
                        importance = excluded.importance,
                        last_seen = excluded.last_seen,
                        mentions = excluded.mentions,
                        status = 'active',
                        updated_at = excluded.updated_at
                    """,
                    (person_name, row["topic"], importance, row["last_seen"], row["cnt"], now_iso, now_iso),
                )

    def compress_dailies_to_weekly(self, person_name: str) -> None:
        cutoff = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
        now_iso = datetime.now(timezone.utc).isoformat()

        with get_connection() as conn:
            rows = conn.execute(
                "SELECT date, topics FROM daily_summaries "
                "WHERE person_name = ? AND date < ? ORDER BY date ASC",
                (person_name, cutoff),
            ).fetchall()
            if not rows:
                return

            weeks: dict[str, dict[str, int]] = defaultdict(dict)
            for row in rows:
                d = datetime.strptime(row["date"], "%Y-%m-%d")
                week_start = (d - timedelta(days=d.weekday())).strftime("%Y-%m-%d")
                for topic in row["topics"].split(", "):
                    t = topic.strip()
                    if t:
                        weeks[week_start][t] = weeks[week_start].get(t, 0) + 1

            for week_start, topic_counts in weeks.items():
                top = sorted(topic_counts.items(), key=lambda x: -x[1])[:10]
                summary = ", ".join(t for t, _ in top)
                conn.execute(
                    """
                    INSERT INTO weekly_summaries(person_name, week_start, summary, created_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(person_name, week_start) DO UPDATE SET summary = excluded.summary
                    """,
                    (person_name, week_start, summary, now_iso),
                )

            dates = [row["date"] for row in rows]
            conn.execute(
                f"DELETE FROM daily_summaries WHERE person_name = ? AND date IN ({','.join('?' * len(dates))})",
                (person_name, *dates),
            )

    def prune_old_summaries(self, person_name: str) -> None:
        cutoff = (datetime.now() - timedelta(days=183)).strftime("%Y-%m-%d")
        with get_connection() as conn:
            conn.execute(
                "DELETE FROM weekly_summaries WHERE person_name = ? AND week_start < ?",
                (person_name, cutoff),
            )

    def get_all_person_names(self) -> list[str]:
        with get_connection() as conn:
            rows = conn.execute("SELECT name FROM persons").fetchall()
            return [r["name"] for r in rows]
