"""
ECO-IOT-GW Audit Service
NIS2-compliant audit logging
"""
import json
import logging
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from threading import Lock
from typing import Any, Dict, List, Optional

from ..config import settings
from ..models.schemas import AuditLogEntry, AuditLogQuery

logger = logging.getLogger(__name__)


class AuditService:
    """Service for NIS2-compliant audit logging."""

    def __init__(self):
        self._db_path = settings.AUDIT_DB_PATH
        self._lock = Lock()
        self._initialized = False

    def initialize(self):
        """Initialize the audit database."""
        if self._initialized:
            return

        # Ensure directory exists
        self._db_path.parent.mkdir(parents=True, exist_ok=True)

        with self._lock:
            conn = sqlite3.connect(str(self._db_path))
            try:
                cursor = conn.cursor()

                # Create audit log table
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS audit_logs (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp TEXT NOT NULL,
                        username TEXT NOT NULL,
                        action TEXT NOT NULL,
                        resource TEXT NOT NULL,
                        details TEXT,
                        ip_address TEXT NOT NULL,
                        success INTEGER NOT NULL,
                        created_at TEXT DEFAULT CURRENT_TIMESTAMP
                    )
                """)

                # Create indexes for efficient querying
                cursor.execute("""
                    CREATE INDEX IF NOT EXISTS idx_audit_timestamp
                    ON audit_logs(timestamp)
                """)
                cursor.execute("""
                    CREATE INDEX IF NOT EXISTS idx_audit_username
                    ON audit_logs(username)
                """)
                cursor.execute("""
                    CREATE INDEX IF NOT EXISTS idx_audit_action
                    ON audit_logs(action)
                """)
                cursor.execute("""
                    CREATE INDEX IF NOT EXISTS idx_audit_resource
                    ON audit_logs(resource)
                """)

                conn.commit()
                self._initialized = True
                logger.info(f"Audit database initialized at {self._db_path}")

            finally:
                conn.close()

    def log(
        self,
        username: str,
        action: str,
        resource: str,
        ip_address: str,
        success: bool = True,
        details: Optional[Dict[str, Any]] = None
    ) -> int:
        """
        Log an audit event.

        Args:
            username: User performing the action
            action: Action type (login, logout, create, update, delete, etc.)
            resource: Resource being accessed (auth, docker, vpn, etc.)
            ip_address: Client IP address
            success: Whether the action succeeded
            details: Additional details (will be JSON serialized)

        Returns:
            Audit log entry ID
        """
        if not self._initialized:
            self.initialize()

        timestamp = datetime.now().isoformat()
        details_json = json.dumps(details) if details else None

        with self._lock:
            conn = sqlite3.connect(str(self._db_path))
            try:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO audit_logs
                    (timestamp, username, action, resource, details, ip_address, success)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (timestamp, username, action, resource, details_json, ip_address, int(success)))

                conn.commit()
                log_id = cursor.lastrowid

                # Log to file as well
                status_str = "SUCCESS" if success else "FAILED"
                logger.info(
                    f"AUDIT: [{status_str}] {username}@{ip_address} - "
                    f"{action} on {resource}"
                )

                return log_id

            finally:
                conn.close()

    def query(self, query: AuditLogQuery) -> List[AuditLogEntry]:
        """
        Query audit logs with filters.

        Args:
            query: Query parameters

        Returns:
            List of matching audit log entries
        """
        if not self._initialized:
            self.initialize()

        conditions = []
        params = []

        if query.start_date:
            conditions.append("timestamp >= ?")
            params.append(query.start_date.isoformat())

        if query.end_date:
            conditions.append("timestamp <= ?")
            params.append(query.end_date.isoformat())

        if query.username:
            conditions.append("username = ?")
            params.append(query.username)

        if query.action:
            conditions.append("action = ?")
            params.append(query.action)

        if query.resource:
            conditions.append("resource = ?")
            params.append(query.resource)

        where_clause = " AND ".join(conditions) if conditions else "1=1"

        with self._lock:
            conn = sqlite3.connect(str(self._db_path))
            conn.row_factory = sqlite3.Row
            try:
                cursor = conn.cursor()
                cursor.execute(f"""
                    SELECT id, timestamp, username, action, resource,
                           details, ip_address, success
                    FROM audit_logs
                    WHERE {where_clause}
                    ORDER BY timestamp DESC
                    LIMIT ? OFFSET ?
                """, params + [query.limit, query.offset])

                results = []
                for row in cursor.fetchall():
                    details = json.loads(row["details"]) if row["details"] else None
                    results.append(AuditLogEntry(
                        id=row["id"],
                        timestamp=datetime.fromisoformat(row["timestamp"]),
                        username=row["username"],
                        action=row["action"],
                        resource=row["resource"],
                        details=details,
                        ip_address=row["ip_address"],
                        success=bool(row["success"])
                    ))

                return results

            finally:
                conn.close()

    def get_stats(self, days: int = 7) -> Dict[str, Any]:
        """Get audit statistics for the last N days."""
        if not self._initialized:
            self.initialize()

        start_date = (datetime.now() - timedelta(days=days)).isoformat()

        with self._lock:
            conn = sqlite3.connect(str(self._db_path))
            try:
                cursor = conn.cursor()

                # Total events
                cursor.execute("""
                    SELECT COUNT(*) FROM audit_logs WHERE timestamp >= ?
                """, (start_date,))
                total = cursor.fetchone()[0]

                # Events by action
                cursor.execute("""
                    SELECT action, COUNT(*) as count
                    FROM audit_logs
                    WHERE timestamp >= ?
                    GROUP BY action
                    ORDER BY count DESC
                """, (start_date,))
                by_action = {row[0]: row[1] for row in cursor.fetchall()}

                # Events by user
                cursor.execute("""
                    SELECT username, COUNT(*) as count
                    FROM audit_logs
                    WHERE timestamp >= ?
                    GROUP BY username
                    ORDER BY count DESC
                """, (start_date,))
                by_user = {row[0]: row[1] for row in cursor.fetchall()}

                # Failed events
                cursor.execute("""
                    SELECT COUNT(*) FROM audit_logs
                    WHERE timestamp >= ? AND success = 0
                """, (start_date,))
                failed = cursor.fetchone()[0]

                return {
                    "total_events": total,
                    "failed_events": failed,
                    "by_action": by_action,
                    "by_user": by_user,
                    "period_days": days
                }

            finally:
                conn.close()

    def cleanup(self, retention_days: Optional[int] = None):
        """Remove old audit logs beyond retention period."""
        if not self._initialized:
            self.initialize()

        retention = retention_days or settings.AUDIT_RETENTION_DAYS
        cutoff = (datetime.now() - timedelta(days=retention)).isoformat()

        with self._lock:
            conn = sqlite3.connect(str(self._db_path))
            try:
                cursor = conn.cursor()
                cursor.execute("""
                    DELETE FROM audit_logs WHERE timestamp < ?
                """, (cutoff,))
                deleted = cursor.rowcount
                conn.commit()

                if deleted > 0:
                    logger.info(f"Cleaned up {deleted} audit logs older than {retention} days")

                return deleted

            finally:
                conn.close()


# Global audit service instance
audit_service = AuditService()
