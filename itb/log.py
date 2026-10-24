"""Structured JSONL event log. One line per event, wall-clock ns + monotonic ns.

The log is the audit trail for judges: every RPC call, every built / sent tx,
every spend-cap decision lands here.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

_sink: Path | None = None
_echo = True


def set_sink(path: Path, echo: bool = True) -> None:
    global _sink, _echo
    path.parent.mkdir(parents=True, exist_ok=True)
    _sink = path
    _echo = echo


def log(event: str, **fields) -> None:
    rec = {"t_ns": time.time_ns(), "mono_ns": time.monotonic_ns(), "event": event, **fields}
    line = json.dumps(rec, default=str)
    if _sink is not None:
        with _sink.open("a") as f:
            f.write(line + "\n")
    if _echo and event not in ("rpc",):
        print(line[:300], file=sys.stderr, flush=True)
