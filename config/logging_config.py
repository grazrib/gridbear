import logging
import sys
import threading

from config.settings import LOG_LEVEL


def setup_logging() -> logging.Logger:
    _logger = logging.getLogger("gridbear")
    _logger.setLevel(getattr(logging, LOG_LEVEL.upper(), logging.INFO))

    if not _logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setLevel(logging.DEBUG)
        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )
        handler.setFormatter(formatter)
        _logger.addHandler(handler)

    return _logger


logger = setup_logging()


class DatabaseLogHandler(logging.Handler):
    """Captures WARNING+ logs to admin.log_entries table.

    Uses a background thread to avoid blocking the logging call.
    Initializes the table on first write.
    """

    _TABLE_SQL = """
        CREATE TABLE IF NOT EXISTS admin.log_entries (
            id SERIAL PRIMARY KEY,
            level TEXT NOT NULL,
            logger_name TEXT,
            message TEXT NOT NULL,
            created_at TIMESTAMPTZ DEFAULT NOW()
        )
    """
    _CLEANUP_SQL = (
        "DELETE FROM admin.log_entries WHERE created_at < NOW() - INTERVAL '7 days'"
    )

    def __init__(self):
        super().__init__(level=logging.WARNING)
        self._db = None
        self._table_ready = False
        self._lock = threading.Lock()

    def _get_db(self):
        if self._db is None:
            from core.registry import get_database

            self._db = get_database()
        return self._db

    def _ensure_table(self, conn):
        if not self._table_ready:
            conn.execute(self._TABLE_SQL)
            conn.execute(self._CLEANUP_SQL)
            conn.commit()
            self._table_ready = True

    def emit(self, record):
        try:
            db = self._get_db()
            if not db:
                return
            msg = self.format(record)
            # Truncate long messages
            if len(msg) > 2000:
                msg = msg[:2000] + "..."
            with self._lock:
                with db.acquire_sync() as conn:
                    self._ensure_table(conn)
                    conn.execute(
                        "INSERT INTO admin.log_entries (level, logger_name, message) "
                        "VALUES (%s, %s, %s)",
                        (record.levelname, record.name, msg),
                    )
                    conn.commit()
        except Exception:
            # Never let log handler errors propagate
            pass


def attach_db_log_handler():
    """Attach the DatabaseLogHandler to the gridbear logger.

    Call after database initialization.
    """
    _logger = logging.getLogger("gridbear")
    # Avoid duplicates on repeated calls
    if not any(isinstance(h, DatabaseLogHandler) for h in _logger.handlers):
        handler = DatabaseLogHandler()
        handler.setFormatter(logging.Formatter("%(message)s"))
        _logger.addHandler(handler)
