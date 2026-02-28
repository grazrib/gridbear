"""SQLite audit logging for Executor operations.

E6 Improvements:
- source_ip field for tracking request origin
- Automatic retention cleanup (configurable days)
- Alert detection for suspicious patterns
"""

import logging
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from threading import Lock

from .schemas import AuditEntry

logger = logging.getLogger(__name__)

# Configuration
DEFAULT_RETENTION_DAYS = int(os.environ.get("AUDIT_RETENTION_DAYS", "90"))
ALERT_FAILURE_THRESHOLD = 10  # Failures in window to trigger alert
ALERT_WINDOW_MINUTES = 5


class AuditLog:
    """SQLite-based audit logging with retention and alerting."""

    def __init__(
        self,
        db_path: str = "/app/data/audit/executor.db",
        retention_days: int = DEFAULT_RETENTION_DAYS,
    ):
        """Initialize audit log.

        Args:
            db_path: Path to SQLite database
            retention_days: Days to keep audit entries (0 = forever)
        """
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._retention_days = retention_days
        self._cleanup_lock = Lock()
        self._last_cleanup: datetime | None = None
        self._init_db()

    def _init_db(self) -> None:
        """Create tables if not exists."""
        with self._get_connection() as conn:
            # Check if source_ip column exists
            cursor = conn.execute("PRAGMA table_info(audit_log)")
            columns = {row[1] for row in cursor.fetchall()}

            if "source_ip" not in columns and "audit_log" in self._get_tables(conn):
                # Add source_ip to existing table
                conn.execute("ALTER TABLE audit_log ADD COLUMN source_ip TEXT")
                logger.info("Added source_ip column to audit_log table")

            conn.execute("""
                CREATE TABLE IF NOT EXISTS audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    project TEXT NOT NULL,
                    container TEXT NOT NULL,
                    command TEXT NOT NULL,
                    user TEXT NOT NULL,
                    success INTEGER NOT NULL,
                    exit_code INTEGER,
                    error TEXT,
                    source_ip TEXT
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_audit_timestamp
                ON audit_log(timestamp)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_audit_project
                ON audit_log(project)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_audit_source_ip
                ON audit_log(source_ip)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_audit_success
                ON audit_log(success, timestamp)
            """)
            conn.commit()

    def _get_tables(self, conn) -> set:
        """Get list of tables in database."""
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        return {row[0] for row in cursor.fetchall()}

    @contextmanager
    def _get_connection(self):
        """Context manager for database connections."""
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def log(
        self,
        project: str,
        container: str,
        command: str,
        user: str,
        success: bool,
        exit_code: int | None = None,
        error: str | None = None,
        source_ip: str | None = None,
    ) -> int:
        """Log an operation.

        Args:
            project: Project identifier
            container: Container name
            command: Executed command
            user: User identifier
            success: Whether operation succeeded
            exit_code: Command exit code
            error: Error message if any
            source_ip: Client IP address

        Returns:
            ID of the log entry
        """
        timestamp = datetime.utcnow().isoformat()

        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO audit_log
                (timestamp, project, container, command, user, success, exit_code, error, source_ip)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    timestamp,
                    project,
                    container,
                    command,
                    user,
                    int(success),
                    exit_code,
                    error,
                    source_ip,
                ),
            )
            conn.commit()
            log_id = cursor.lastrowid

        # Check for alert conditions after logging failure
        if not success and source_ip:
            self._check_alert_conditions(source_ip)

        # Periodic cleanup
        self._maybe_cleanup()

        return log_id

    def _check_alert_conditions(self, source_ip: str) -> None:
        """Check if recent failures from IP exceed threshold.

        Logs a warning if suspicious activity detected.
        """
        cutoff = (
            datetime.utcnow() - timedelta(minutes=ALERT_WINDOW_MINUTES)
        ).isoformat()

        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT COUNT(*) as failure_count
                FROM audit_log
                WHERE source_ip = ? AND success = 0 AND timestamp > ?
                """,
                (source_ip, cutoff),
            )
            row = cursor.fetchone()
            failure_count = row["failure_count"] if row else 0

        if failure_count >= ALERT_FAILURE_THRESHOLD:
            logger.warning(
                f"ALERT: Suspicious activity detected from IP {source_ip}: "
                f"{failure_count} failures in last {ALERT_WINDOW_MINUTES} minutes"
            )

    def _maybe_cleanup(self) -> None:
        """Run cleanup if enough time has passed since last cleanup."""
        if self._retention_days <= 0:
            return

        # Only try cleanup once per hour
        now = datetime.utcnow()
        if self._last_cleanup and (now - self._last_cleanup).total_seconds() < 3600:
            return

        # Use lock to prevent concurrent cleanup
        if not self._cleanup_lock.acquire(blocking=False):
            return

        try:
            self._last_cleanup = now
            deleted = self.cleanup_old_entries()
            if deleted > 0:
                logger.info(
                    f"Audit cleanup: deleted {deleted} entries older than {self._retention_days} days"
                )
        finally:
            self._cleanup_lock.release()

    def cleanup_old_entries(self) -> int:
        """Delete entries older than retention period.

        Returns:
            Number of entries deleted
        """
        if self._retention_days <= 0:
            return 0

        cutoff = (datetime.utcnow() - timedelta(days=self._retention_days)).isoformat()

        with self._get_connection() as conn:
            cursor = conn.execute(
                "DELETE FROM audit_log WHERE timestamp < ?",
                (cutoff,),
            )
            conn.commit()
            return cursor.rowcount

    def get_stats(self) -> dict:
        """Get audit log statistics.

        Returns:
            Dictionary with statistics
        """
        with self._get_connection() as conn:
            # Total entries
            cursor = conn.execute("SELECT COUNT(*) as total FROM audit_log")
            total = cursor.fetchone()["total"]

            # Success/failure counts
            cursor = conn.execute(
                "SELECT success, COUNT(*) as count FROM audit_log GROUP BY success"
            )
            counts = {bool(row["success"]): row["count"] for row in cursor.fetchall()}

            # Oldest entry
            cursor = conn.execute("SELECT MIN(timestamp) as oldest FROM audit_log")
            oldest = cursor.fetchone()["oldest"]

            # Database file size
            db_size = self._db_path.stat().st_size if self._db_path.exists() else 0

        return {
            "total_entries": total,
            "success_count": counts.get(True, 0),
            "failure_count": counts.get(False, 0),
            "oldest_entry": oldest,
            "database_size_bytes": db_size,
            "retention_days": self._retention_days,
        }

    def query(
        self,
        project: str | None = None,
        container: str | None = None,
        user: str | None = None,
        success: bool | None = None,
        source_ip: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[AuditEntry]:
        """Query audit log.

        Args:
            project: Filter by project
            container: Filter by container
            user: Filter by user
            success: Filter by success status
            source_ip: Filter by source IP
            limit: Maximum results
            offset: Offset for pagination

        Returns:
            List of audit entries
        """
        conditions = []
        params = []

        if project is not None:
            conditions.append("project = ?")
            params.append(project)

        if container is not None:
            conditions.append("container = ?")
            params.append(container)

        if user is not None:
            conditions.append("user = ?")
            params.append(user)

        if success is not None:
            conditions.append("success = ?")
            params.append(int(success))

        if source_ip is not None:
            conditions.append("source_ip = ?")
            params.append(source_ip)

        where_clause = ""
        if conditions:
            where_clause = "WHERE " + " AND ".join(conditions)

        query = f"""
            SELECT * FROM audit_log
            {where_clause}
            ORDER BY timestamp DESC
            LIMIT ? OFFSET ?
        """
        params.extend([limit, offset])

        with self._get_connection() as conn:
            cursor = conn.execute(query, params)
            rows = cursor.fetchall()

        return [
            AuditEntry(
                id=row["id"],
                timestamp=row["timestamp"],
                project=row["project"],
                container=row["container"],
                command=row["command"],
                user=row["user"],
                success=bool(row["success"]),
                exit_code=row["exit_code"],
                error=row["error"],
                source_ip=row["source_ip"],
            )
            for row in rows
        ]


# Singleton instance
_audit_log: AuditLog | None = None


def get_audit_log() -> AuditLog:
    """Get the audit log singleton."""
    global _audit_log
    if _audit_log is None:
        _audit_log = AuditLog()
    return _audit_log
