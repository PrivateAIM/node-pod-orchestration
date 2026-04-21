import json
import logging
import sys


class JsonFormatter(logging.Formatter):
    """Emit each log record as a single JSON line for structured log ingestion."""

    def format(self, record: logging.LogRecord) -> str:
        """Serialize the log record as a single JSON object on one line.

        Always includes ``timestamp``, ``level``, ``logger``, ``module``, and
        ``msg`` fields. When the record carries exception info, a formatted
        traceback is added under ``error``.
        """
        log = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "module": record.module,
            "msg": record.getMessage(),
        }

        if record.exc_info:
            log["error"] = self.formatException(record.exc_info)

        for field in ("analysis_id", "deployment_name", "phase"):
            value = getattr(record, field, None)
            if value is not None:
                log[field] = value

        return json.dumps(log, default=str)  # for non-serializable msgs


def get_logger() -> logging.Logger:
    """Return a process-wide logger configured for JSON output.

    Registers the custom ``ACTION`` (21) and ``STATUS_LOOP`` (22) levels,
    installs a single :class:`JsonFormatter` handler on the root logger
    (idempotent), and returns a child logger named after this module.

    Returns:
        A :class:`logging.Logger` ready for use.
    """
    _set_custom_log_level(21, 'ACTION')
    _set_custom_log_level(22, 'STATUS_LOOP')

    root = logging.getLogger()
    if not any(isinstance(h.formatter, JsonFormatter) for h in root.handlers):
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(JsonFormatter())
        root.addHandler(handler)
        root.setLevel(logging.INFO)

    logger = logging.getLogger(__name__)
    return logger


def _set_custom_log_level(level, level_name):
    """Register a new log level and expose it as a method on ``Logger`` and module function.

    After calling ``_set_custom_log_level(21, 'ACTION')`` you can write
    ``logger.action("...")`` and ``logging.action("...")``.

    Args:
        level: Integer log level (between existing stdlib levels).
        level_name: Human-readable name; used uppercase as the level name and
            lowercase as the method/function name.
    """
    def logForLevel(self, message, *args, **kws):
        if self.isEnabledFor(level):
            self._log(level, message, args, **kws)

    def logToRoot(message, *args, **kwargs):
        logging.log(level, message, *args, **kwargs)

    logging.addLevelName(level, level_name.upper())
    setattr(logging, level_name.upper(), level)
    setattr(logging.getLoggerClass(), level_name.lower(), logForLevel)
    setattr(logging, level_name.lower(), logToRoot)
