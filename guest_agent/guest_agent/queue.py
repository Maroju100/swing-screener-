"""SQLite approval queue + audit log. Every message and every decision is kept."""
import json
import sqlite3
from datetime import datetime, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at TEXT NOT NULL,
  property_id TEXT NOT NULL,
  guest TEXT NOT NULL,
  message TEXT NOT NULL,
  intent TEXT,
  route TEXT NOT NULL,
  draft TEXT,
  reply TEXT,
  reasons TEXT,
  status TEXT NOT NULL,          -- sent | pending | escalated | rejected
  final_text TEXT,
  decided_at TEXT,
  decided_by TEXT
);
"""


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Queue:
    def __init__(self, path="guest_agent.db"):
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)

    def record(self, property_id, guest, message, decision, sent):
        status = "sent" if sent else ("escalated" if decision.route == "emergency" else "pending")
        cur = self.db.execute(
            "INSERT INTO items (created_at, property_id, guest, message, intent, route, draft, reply,"
            " reasons, status, final_text) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (_now(), property_id, guest, message, decision.intent, decision.route, decision.draft,
             decision.reply, json.dumps(decision.reasons), status, decision.reply if sent else None))
        self.db.commit()
        return cur.lastrowid

    def pending(self):
        return [dict(r) for r in self.db.execute(
            "SELECT * FROM items WHERE status IN ('pending','escalated') ORDER BY id")]

    def get(self, item_id):
        r = self.db.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
        return dict(r) if r else None

    def decide(self, item_id, status, text=None, by="host"):
        item = self.get(item_id)
        if not item or item["status"] not in ("pending", "escalated"):
            raise ValueError(f"item {item_id} is not awaiting a decision")
        self.db.execute("UPDATE items SET status=?, final_text=?, decided_at=?, decided_by=? WHERE id=?",
                        (status, text, _now(), by, item_id))
        self.db.commit()
