"""Feedback data ingestion for NOVA empirical model refinement."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from statistics import mean

from nova.core.input_schema import HotFireTestResult, ManufacturingReport


class FeedbackIngester:
    """Accept real-world test/manufacturing data and update coefficients."""

    def __init__(self, db_path: str | Path = "nova/feedback/db/feedback.sqlite") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS hot_fire (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    engine_id TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS manufacturing (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    part_id TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS coefficients (
                    key TEXT PRIMARY KEY,
                    value REAL NOT NULL,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

    def ingest_hot_fire_data(self, test_data: HotFireTestResult) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO hot_fire(engine_id, payload) VALUES (?, ?)",
                (test_data.engine_id, test_data.model_dump_json()),
            )

    def ingest_manufacturing_outcome(self, mfg_data: ManufacturingReport) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO manufacturing(part_id, payload) VALUES (?, ?)",
                (mfg_data.part_id, mfg_data.model_dump_json()),
            )

    def recalibrate_model(self) -> None:
        with self._connect() as conn:
            rows = conn.execute("SELECT payload FROM hot_fire").fetchall()
            isp_values = [json.loads(row[0])["measured_isp_s"] for row in rows]
            if isp_values:
                conn.execute(
                    "INSERT OR REPLACE INTO coefficients(key, value) VALUES (?, ?)",
                    ("mean_measured_isp_s", mean(isp_values)),
                )
            mfg_rows = conn.execute("SELECT payload FROM manufacturing").fetchall()
            channel_values = [json.loads(row[0])["min_resolved_channel_mm"] for row in mfg_rows]
            if channel_values:
                conn.execute(
                    "INSERT OR REPLACE INTO coefficients(key, value) VALUES (?, ?)",
                    ("observed_min_channel_mm", mean(channel_values)),
                )

    def coefficients(self) -> dict[str, float]:
        with self._connect() as conn:
            return {key: value for key, value in conn.execute("SELECT key, value FROM coefficients").fetchall()}

