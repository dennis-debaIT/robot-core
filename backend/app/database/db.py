import json
import os
import sqlite3
from contextlib import contextmanager
from hashlib import sha256
from typing import Any, Iterator

def _env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        return default

DEFAULT_PERSONALITY = {
    "friendliness": _env_float("ROBOT_DEFAULT_FRIENDLINESS", 0.90),
    "humor": _env_float("ROBOT_DEFAULT_HUMOR", 0.65),
    "curiosity": _env_float("ROBOT_DEFAULT_CURIOSITY", 0.75),
    "talkativeness": _env_float("ROBOT_DEFAULT_TALKATIVENESS", 0.45),
    "caution": _env_float("ROBOT_DEFAULT_CAUTION", 0.80),
    "directness": _env_float("ROBOT_DEFAULT_DIRECTNESS", 0.70),
    "sarcasm": _env_float("ROBOT_DEFAULT_SARCASM", 0.15),
    "patience": _env_float("ROBOT_DEFAULT_PATIENCE", 0.85),
}


def get_db_path() -> str:
    return os.getenv("ROBOT_CORE_DB_PATH", "/data/robot_core.db")


def ensure_db_directory() -> None:
    db_dir = os.path.dirname(get_db_path())
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)


def create_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(get_db_path(), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def get_connection() -> Iterator[sqlite3.Connection]:
    conn = create_connection()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _set_state(conn: sqlite3.Connection, key: str, value: Any) -> None:
    conn.execute(
        """
        INSERT INTO system_state(key, value)
        VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """,
        (key, json.dumps(value)),
    )


def memory_fingerprint(subject: str | None, category: str, content: str) -> str:
    def normalize(value: str) -> str:
        return " ".join(value.strip().split()).casefold()

    canonical = "|".join(
        [
            normalize(subject or ""),
            normalize(category),
            normalize(content),
        ]
    )
    return sha256(canonical.encode("utf-8")).hexdigest()


def init_db() -> None:
    ensure_db_directory()
    with get_connection() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS personality (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                friendliness REAL NOT NULL,
                humor REAL NOT NULL,
                curiosity REAL NOT NULL,
                talkativeness REAL NOT NULL,
                caution REAL NOT NULL,
                directness REAL NOT NULL,
                sarcasm REAL NOT NULL,
                patience REAL NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS memory_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                subject TEXT,
                category TEXT NOT NULL,
                content TEXT NOT NULL,
                source TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                reviewed_at TEXT,
                fingerprint TEXT,
                candidate_kind TEXT,
                decision_reason TEXT,
                confidence REAL
            );

            CREATE TABLE IF NOT EXISTS persons (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS person_profile_facts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                person_id INTEGER NOT NULL,
                trait_type TEXT NOT NULL,
                value TEXT NOT NULL,
                source_memory_id INTEGER,
                confidence REAL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(person_id, trait_type, value),
                FOREIGN KEY(person_id) REFERENCES persons(id),
                FOREIGN KEY(source_memory_id) REFERENCES memory_entries(id)
            );

            CREATE TABLE IF NOT EXISTS person_relationship_state (
                person_id INTEGER PRIMARY KEY,
                warmth REAL NOT NULL DEFAULT 0.0,
                tension REAL NOT NULL DEFAULT 0.0,
                openness REAL NOT NULL DEFAULT 0.0,
                interaction_count INTEGER NOT NULL DEFAULT 0,
                last_interaction_at TEXT,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(person_id) REFERENCES persons(id)
            );

            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                payload TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS conversation_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                role TEXT NOT NULL,
                person_name TEXT,
                message TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS topic_mentions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                person_name TEXT,
                topic TEXT NOT NULL,
                source_role TEXT NOT NULL,
                topic_kind TEXT,
                score REAL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                action TEXT NOT NULL,
                level TEXT NOT NULL DEFAULT 'info',
                target_type TEXT NOT NULL,
                target_id TEXT,
                actor_type TEXT NOT NULL,
                actor_id TEXT,
                summary TEXT NOT NULL,
                details TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS system_state (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS robot_error_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                entity_id TEXT NOT NULL,
                source_entity_id TEXT,
                raw_state TEXT NOT NULL,
                label TEXT NOT NULL,
                occurred_at TEXT NOT NULL,
                source TEXT NOT NULL,
                imported_at TEXT NOT NULL,
                UNIQUE(entity_id, raw_state, occurred_at)
            );

            CREATE TABLE IF NOT EXISTS vehicle_location_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                vehicle_id TEXT NOT NULL,
                vehicle_label TEXT,
                source_entity_id TEXT NOT NULL,
                latitude REAL NOT NULL,
                longitude REAL NOT NULL,
                accuracy REAL,
                speed REAL,
                heading REAL,
                state TEXT,
                recorded_at TEXT NOT NULL,
                imported_at TEXT NOT NULL,
                UNIQUE(vehicle_id, recorded_at, latitude, longitude)
            );

            CREATE INDEX IF NOT EXISTS idx_memory_entries_status
            ON memory_entries(status);

            CREATE INDEX IF NOT EXISTS idx_audit_log_created_at
            ON audit_log(created_at);

            CREATE INDEX IF NOT EXISTS idx_topic_mentions_person_topic_created
            ON topic_mentions(person_name, topic, created_at);

            CREATE INDEX IF NOT EXISTS idx_robot_error_history_entity_occurred
            ON robot_error_history(entity_id, occurred_at DESC);

            CREATE INDEX IF NOT EXISTS idx_vehicle_location_history_vehicle_recorded
            ON vehicle_location_history(vehicle_id, recorded_at DESC);

            CREATE TABLE IF NOT EXISTS reminders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                text TEXT NOT NULL,
                fire_at TEXT NOT NULL,
                person_name TEXT,
                notified INTEGER NOT NULL DEFAULT 0,
                dismissed INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_reminders_fire_at
            ON reminders(fire_at, notified, dismissed);

            CREATE TABLE IF NOT EXISTS person_face_descriptors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                person_id INTEGER NOT NULL,
                descriptor TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_person_face_descriptors_person
            ON person_face_descriptors(person_id);

            CREATE TABLE IF NOT EXISTS notification_rules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                label TEXT NOT NULL,
                entity_id TEXT NOT NULL,
                condition_type TEXT NOT NULL,
                condition_value TEXT,
                message TEXT,
                enabled INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                rule_id INTEGER,
                message TEXT NOT NULL,
                entity_id TEXT,
                read INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS notification_rule_state (
                rule_id INTEGER PRIMARY KEY,
                last_value TEXT,
                last_fired_at TEXT,
                condition_active INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS light_scenes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                light_states TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS vehicle_charging_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                vehicle_id TEXT NOT NULL,
                battery_pct REAL NOT NULL,
                is_charging INTEGER NOT NULL DEFAULT 0,
                plug_connected INTEGER NOT NULL DEFAULT 0,
                recorded_at TEXT NOT NULL,
                imported_at TEXT NOT NULL,
                UNIQUE(vehicle_id, recorded_at)
            );

            CREATE INDEX IF NOT EXISTS idx_vehicle_charging_history_vehicle_recorded
            ON vehicle_charging_history(vehicle_id, recorded_at DESC);

            CREATE TABLE IF NOT EXISTS vehicle_charging_daily (
                vehicle_id TEXT NOT NULL,
                day TEXT NOT NULL,
                min_pct REAL NOT NULL,
                max_pct REAL NOT NULL,
                charged_pct REAL NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (vehicle_id, day)
            );

            CREATE TABLE IF NOT EXISTS person_notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                person_id INTEGER,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_person_notes_person
            ON person_notes(person_id);

            CREATE TABLE IF NOT EXISTS chore_tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                icon TEXT,
                points INTEGER NOT NULL DEFAULT 1,
                sort_order INTEGER NOT NULL DEFAULT 0,
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS chore_completions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER NOT NULL REFERENCES chore_tasks(id),
                person_id INTEGER NOT NULL REFERENCES persons(id),
                completed_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_chore_completions_task
            ON chore_completions(task_id, completed_at);

            CREATE TABLE IF NOT EXISTS sync_items (
                id          TEXT    PRIMARY KEY,
                text        TEXT    NOT NULL,
                checked     INTEGER NOT NULL DEFAULT 0,
                sort_order  INTEGER NOT NULL DEFAULT 0,
                created_at  TEXT    NOT NULL,
                updated_at  TEXT    NOT NULL,
                deleted     INTEGER NOT NULL DEFAULT 0,
                synced_at   TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_sync_items_updated ON sync_items(updated_at);

            CREATE TABLE IF NOT EXISTS daily_summaries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                person_name TEXT NOT NULL,
                date TEXT NOT NULL,
                topics TEXT NOT NULL,
                sample_messages TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                UNIQUE(person_name, date)
            );

            CREATE TABLE IF NOT EXISTS weekly_summaries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                person_name TEXT NOT NULL,
                week_start TEXT NOT NULL,
                summary TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(person_name, week_start)
            );

            CREATE TABLE IF NOT EXISTS active_topics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                person_name TEXT NOT NULL,
                title TEXT NOT NULL,
                importance REAL NOT NULL DEFAULT 0.5,
                last_seen TEXT NOT NULL,
                mentions INTEGER NOT NULL DEFAULT 1,
                status TEXT NOT NULL DEFAULT 'active',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(person_name, title)
            );

            CREATE INDEX IF NOT EXISTS idx_daily_summaries_person_date
            ON daily_summaries(person_name, date DESC);

            CREATE INDEX IF NOT EXISTS idx_weekly_summaries_person_week
            ON weekly_summaries(person_name, week_start DESC);

            CREATE INDEX IF NOT EXISTS idx_active_topics_person_status
            ON active_topics(person_name, status, importance DESC);
            """
        )

        columns = {row["name"] for row in conn.execute("PRAGMA table_info(memory_entries)").fetchall()}
        if "fingerprint" not in columns:
            conn.execute("ALTER TABLE memory_entries ADD COLUMN fingerprint TEXT")
        if "candidate_kind" not in columns:
            conn.execute("ALTER TABLE memory_entries ADD COLUMN candidate_kind TEXT")
        if "decision_reason" not in columns:
            conn.execute("ALTER TABLE memory_entries ADD COLUMN decision_reason TEXT")
        if "confidence" not in columns:
            conn.execute("ALTER TABLE memory_entries ADD COLUMN confidence REAL")

        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_memory_entries_fingerprint_status
            ON memory_entries(fingerprint, status)
            """
        )

        topic_columns = {row["name"] for row in conn.execute("PRAGMA table_info(topic_mentions)").fetchall()}
        if "topic_kind" not in topic_columns:
            conn.execute("ALTER TABLE topic_mentions ADD COLUMN topic_kind TEXT")
        if "score" not in topic_columns:
            conn.execute("ALTER TABLE topic_mentions ADD COLUMN score REAL")
        conn.execute("UPDATE topic_mentions SET topic_kind = 'neutral' WHERE topic_kind IS NULL")
        conn.execute("UPDATE topic_mentions SET score = 1.0 WHERE score IS NULL")

        reminder_columns = {row["name"] for row in conn.execute("PRAGMA table_info(reminders)").fetchall()}
        if "light_command" not in reminder_columns:
            conn.execute("ALTER TABLE reminders ADD COLUMN light_command TEXT")
        if "sync_server_id" not in reminder_columns:
            conn.execute("ALTER TABLE reminders ADD COLUMN sync_server_id TEXT")

        note_columns = {row["name"] for row in conn.execute("PRAGMA table_info(person_notes)").fetchall()}
        if "sync_server_id" not in note_columns:
            conn.execute("ALTER TABLE person_notes ADD COLUMN sync_server_id TEXT")

        audit_columns = {row["name"] for row in conn.execute("PRAGMA table_info(audit_log)").fetchall()}
        if "level" not in audit_columns:
            conn.execute("ALTER TABLE audit_log ADD COLUMN level TEXT NOT NULL DEFAULT 'info'")

        person_columns = {row["name"] for row in conn.execute("PRAGMA table_info(persons)").fetchall()}
        if "gender" not in person_columns:
            conn.execute("ALTER TABLE persons ADD COLUMN gender TEXT")
        if "role" not in person_columns:
            conn.execute("ALTER TABLE persons ADD COLUMN role TEXT")
        if "emoji" not in person_columns:
            conn.execute("ALTER TABLE persons ADD COLUMN emoji TEXT")
        if "sync_user_id" not in person_columns:
            conn.execute("ALTER TABLE persons ADD COLUMN sync_user_id TEXT")

        chore_task_columns = {row["name"] for row in conn.execute("PRAGMA table_info(chore_tasks)").fetchall()}
        if "points" not in chore_task_columns:
            conn.execute("ALTER TABLE chore_tasks ADD COLUMN points INTEGER NOT NULL DEFAULT 1")

        chore_comp_columns = {row["name"] for row in conn.execute("PRAGMA table_info(chore_completions)").fetchall()}
        if "sync_id" not in chore_comp_columns:
            conn.execute("ALTER TABLE chore_completions ADD COLUMN sync_id TEXT")

        rows = conn.execute(
            """
            SELECT id, subject, category, content
            FROM memory_entries
            WHERE fingerprint IS NULL OR fingerprint = ''
            """
        ).fetchall()
        for row in rows:
            conn.execute(
                "UPDATE memory_entries SET fingerprint = ? WHERE id = ?",
                (memory_fingerprint(row["subject"], row["category"], row["content"]), row["id"]),
            )

        exists = conn.execute("SELECT 1 FROM personality WHERE id = 1").fetchone()
        if not exists:
            conn.execute(
                """
                INSERT INTO personality(
                    id, friendliness, humor, curiosity, talkativeness,
                    caution, directness, sarcasm, patience, updated_at
                )
                VALUES(1, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                """,
                tuple(DEFAULT_PERSONALITY.values()),
            )

        defaults = {
            "battery_level": 100,
            "display_status": "idle",
            "last_person_detected": None,
            "last_person_detected_at": None,
            "last_conversation_at": None,
            "initiative_last_suggested_at": None,
            "device_name": "Erika",
            "site_label": "Mein Haushalt",
            "device_state": "factory",
            "network_connected": False,
            "server_connected": False,
            "local_ip": None,
            "software_version": "0.3.0",
            "update_status": "idle",
            "last_server_contact_at": None,
            "maintenance_mode": False,
            "provisioning_status": "factory_bound",
            "device_id": None,
            "device_secret": None,
            "tenant_binding": "factory_assigned",
            "tenant_id": None,
            "cloud_endpoint": None,
            "sync_enabled": False,
            "sync_mode": "hybrid",
            "sync_cursor": None,
            "global_relationship_state": {
                "warmth": 0.0,
                "tension": 0.0,
                "openness": 0.0,
                "interaction_count": 0,
                "updated_at": None,
            },
        }
        for key, value in defaults.items():
            exists = conn.execute("SELECT 1 FROM system_state WHERE key = ?", (key,)).fetchone()
            if not exists:
                _set_state(conn, key, value)


def read_state(conn: sqlite3.Connection, key: str, default: Any = None) -> Any:
    row = conn.execute("SELECT value FROM system_state WHERE key = ?", (key,)).fetchone()
    if not row:
        return default
    return json.loads(row["value"])


def write_state(conn: sqlite3.Connection, key: str, value: Any) -> None:
    _set_state(conn, key, value)
