import sqlite3
import json
from datetime import datetime

class AuditLogger:
    """
    Records EVERY decision made by every agent.
    Judges will look at this to verify your system is trustworthy.
    """
    
    def __init__(self, db_path="data/audit.db"):
        self.db_path = db_path
        self._setup_database()
    
    def _setup_database(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS decisions (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp     TEXT,
                agent_name    TEXT,
                delivery_id   TEXT,
                full_record   TEXT
            )
        """)
        conn.commit()
        conn.close()
    
    def log(self, decision: dict):
        """Save one agent decision to the database"""
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "INSERT INTO decisions (timestamp, agent_name, delivery_id, full_record) VALUES (?,?,?,?)",
            (
                decision.get("timestamp", datetime.utcnow().isoformat()),
                decision.get("agent", "unknown"),
                decision.get("delivery_id", "unknown"),
                json.dumps(decision)
            )
        )
        conn.commit()
        conn.close()
    
    def get_all(self):
        """Get all logged decisions as a list"""
        conn = sqlite3.connect(self.db_path)
        rows = conn.execute(
            "SELECT timestamp, agent_name, delivery_id, full_record FROM decisions ORDER BY id DESC"
        ).fetchall()
        conn.close()
        
        results = []
        for row in rows:
            record = json.loads(row[3])
            results.append({
                "timestamp": row[0],
                "agent": row[1],
                "delivery_id": row[2],
                "details": record
            })
        return results
    
    def get_for_delivery(self, delivery_id: str):
        """Get all decisions for one specific delivery"""
        conn = sqlite3.connect(self.db_path)
        rows = conn.execute(
            "SELECT full_record FROM decisions WHERE delivery_id = ? ORDER BY id",
            (delivery_id,)
        ).fetchall()
        conn.close()
        return [json.loads(r[0]) for r in rows] 