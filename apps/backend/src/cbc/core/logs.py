"""One logging setup for both applications, plain or JSON.

The worker called `basicConfig` with a human format and the API called nothing at
all, so the two halves of the same job logged in two shapes and one of them only
by accident, through uvicorn's own configuration. Neither was parseable: a log
aggregator given `17:42:01 INFO  job build_proposal done - 3 artifacts` has to
regex its way back to the fields that were thrown away to write it.

`LOG_FORMAT=json` emits one object per line instead. `LOG_LEVEL` sets the level
for both. The default stays human-readable, because the common case is still
somebody watching `docker compose logs -f`.

Context - which job, which project, who asked - is attached with `bind`, not
formatted into the message, so it survives into the JSON as fields.
"""
from __future__ import annotations

import json
import logging
import os
import sys
from typing import Any

# Attributes LogRecord always carries. Anything else on a record was put there
# deliberately by `bind`, and is worth emitting.
_STANDARD = frozenset(
    """args asctime created exc_info exc_text filename funcName levelname levelno
    lineno module msecs message msg name pathname process processName relativeCreated
    stack_info thread threadName taskName""".split()
)


class JsonFormatter(logging.Formatter):
    """One JSON object per line, with whatever context was bound to the record."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in _STANDARD and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        # default=str so an ObjectId or a datetime in the context cannot turn a
        # log line into a crash inside the logging call.
        return json.dumps(payload, default=str)


def configure(service: str) -> logging.Logger:
    """Set up root logging for one service and return its logger.

    Idempotent: calling it twice replaces the handler rather than doubling every
    line, which is what `basicConfig` would do.
    """
    level = getattr(logging, os.environ.get("LOG_LEVEL", "INFO").upper(), logging.INFO)

    handler = logging.StreamHandler(sys.stdout)
    if os.environ.get("LOG_FORMAT", "").lower() == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)-7s %(message)s", datefmt="%H:%M:%S")
        )

    root = logging.getLogger()
    for existing in root.handlers[:]:
        root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(level)
    return logging.getLogger(service)


def bind(logger: logging.Logger, **context: Any) -> logging.LoggerAdapter:
    """A logger that carries `context` as fields on every record it makes.

    Fields rather than message text: `log.info("done")` on a bound logger emits
    the job id and project code as their own keys under LOG_FORMAT=json, and
    nothing has to parse them back out of a sentence.
    """
    return logging.LoggerAdapter(logger, {k: v for k, v in context.items() if v is not None})
