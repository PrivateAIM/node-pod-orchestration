import json
import logging

import pytest


@pytest.fixture(autouse=True)
def reset_root_logger():
    """Snapshot and restore the root logger around each test.

    po_logging.get_logger() mutates the root logger's handlers and level,
    and is idempotent based on whether a JsonFormatter is already attached.
    Each test needs a clean slate.
    """
    root = logging.getLogger()
    original_handlers = root.handlers[:]
    original_level = root.level

    root.handlers = []

    yield

    root.handlers = original_handlers
    root.level = original_level


class TestJsonFormatter:
    def _make_record(self, **overrides):
        defaults = {
            "name": "test.logger",
            "level": logging.INFO,
            "pathname": "/some/path/mod.py",
            "lineno": 10,
            "msg": "hello",
            "args": (),
            "exc_info": None,
        }
        defaults.update(overrides)
        return logging.LogRecord(**defaults)

    def test_emits_required_fields(self):
        from src.utils.po_logging import JsonFormatter

        record = self._make_record()
        output = JsonFormatter().format(record)
        parsed = json.loads(output)

        assert "timestamp" in parsed
        assert parsed["level"] == "INFO"
        assert parsed["msg"] == "hello"

    def test_emits_extra_fields(self):
        from src.utils.po_logging import JsonFormatter

        record = self._make_record(name="my.logger", pathname="/x/foo.py")
        parsed = json.loads(JsonFormatter().format(record))

        assert parsed["logger"] == "my.logger"
        assert parsed["module"] == "foo"

    def test_output_is_single_line(self):
        from src.utils.po_logging import JsonFormatter

        record = self._make_record(msg="line1\nline2")
        output = JsonFormatter().format(record)

        # json.dumps escapes \n → no raw newlines in output
        assert "\n" not in output
        assert json.loads(output)["msg"] == "line1\nline2"

    def test_timestamp_format(self):
        from src.utils.po_logging import JsonFormatter

        record = self._make_record()
        parsed = json.loads(JsonFormatter().format(record))

        # ISO-ish: YYYY-MM-DDTHH:MM:SS
        import re
        assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$", parsed["timestamp"])

    def test_message_with_args_is_formatted(self):
        from src.utils.po_logging import JsonFormatter

        record = self._make_record(msg="user %s did %d things", args=("alice", 3))
        parsed = json.loads(JsonFormatter().format(record))

        assert parsed["msg"] == "user alice did 3 things"

    def test_exc_info_adds_error_field(self):
        from src.utils.po_logging import JsonFormatter

        try:
            raise ValueError("boom")
        except ValueError:
            import sys
            exc_info = sys.exc_info()

        record = self._make_record(level=logging.ERROR, msg="failed", exc_info=exc_info)
        parsed = json.loads(JsonFormatter().format(record))

        assert "error" in parsed
        assert "ValueError" in parsed["error"]
        assert "boom" in parsed["error"]

    def test_no_error_field_when_no_exc_info(self):
        from src.utils.po_logging import JsonFormatter

        record = self._make_record()
        parsed = json.loads(JsonFormatter().format(record))

        assert "error" not in parsed

    def test_non_serializable_msg_falls_back_to_str(self):
        from src.utils.po_logging import JsonFormatter

        class Weird:
            def __str__(self):
                return "weird-repr"

        record = self._make_record(msg=Weird())
        output = JsonFormatter().format(record)

        # getMessage() calls str() on non-string msg → JSON encodes as string
        parsed = json.loads(output)
        assert parsed["msg"] == "weird-repr"

    def test_custom_level_name_in_output(self):
        from src.utils.po_logging import JsonFormatter, get_logger

        get_logger()  # registers ACTION / STATUS_LOOP levels

        record = self._make_record(level=21)  # ACTION
        parsed = json.loads(JsonFormatter().format(record))
        assert parsed["level"] == "ACTION"


class TestGetLogger:
    def test_returns_logger(self):
        from src.utils.po_logging import get_logger

        logger = get_logger()
        assert isinstance(logger, logging.Logger)

    def test_attaches_json_formatter_to_root(self):
        from src.utils.po_logging import JsonFormatter, get_logger

        get_logger()

        root = logging.getLogger()
        json_handlers = [h for h in root.handlers if isinstance(h.formatter, JsonFormatter)]
        assert len(json_handlers) == 1

    def test_sets_root_level_to_info(self):
        from src.utils.po_logging import get_logger

        get_logger()
        assert logging.getLogger().level == logging.INFO

    def test_is_idempotent(self):
        from src.utils.po_logging import JsonFormatter, get_logger

        get_logger()
        get_logger()
        get_logger()

        root = logging.getLogger()
        json_handlers = [h for h in root.handlers if isinstance(h.formatter, JsonFormatter)]
        # multiple calls must NOT stack duplicate handlers
        assert len(json_handlers) == 1

    def test_registers_custom_levels(self):
        from src.utils.po_logging import get_logger

        get_logger()

        assert logging.getLevelName(21) == "ACTION"
        assert logging.getLevelName(22) == "STATUS_LOOP"
        assert hasattr(logging.getLoggerClass(), "action")
        assert hasattr(logging.getLoggerClass(), "status_loop")

    def test_end_to_end_emits_json_to_stream(self, capsys):
        from src.utils.po_logging import get_logger

        logger = get_logger()
        logger.info("end-to-end message")

        captured = capsys.readouterr()
        # StreamHandler(sys.stdout) — message lands on stdout
        line = captured.out.strip().splitlines()[-1]
        parsed = json.loads(line)

        assert parsed["level"] == "INFO"
        assert parsed["msg"] == "end-to-end message"
        assert "timestamp" in parsed

    def test_end_to_end_custom_level(self, capsys):
        from src.utils.po_logging import get_logger

        logger = get_logger()
        logger.action("custom-level message")  # type: ignore[attr-defined]

        captured = capsys.readouterr()
        line = captured.out.strip().splitlines()[-1]
        parsed = json.loads(line)

        assert parsed["level"] == "ACTION"
        assert parsed["msg"] == "custom-level message"

    def test_end_to_end_exception_populates_error_field(self, capsys):
        from src.utils.po_logging import get_logger

        logger = get_logger()
        try:
            raise RuntimeError("kaboom")
        except RuntimeError:
            logger.exception("caught it")

        captured = capsys.readouterr()
        line = captured.out.strip().splitlines()[-1]
        parsed = json.loads(line)

        assert parsed["msg"] == "caught it"
        assert "error" in parsed
        assert "RuntimeError" in parsed["error"]
        assert "kaboom" in parsed["error"]
