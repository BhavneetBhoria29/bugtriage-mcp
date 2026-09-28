"""Shared model state for every transport (MCP stdio/HTTP and gRPC).

Loaded once per process: data is generated on first run, then the index and
triage models are fit and cached.
"""
from __future__ import annotations

import logging
import os
import time
from functools import lru_cache
from pathlib import Path

from .data import load_bugs, load_logs, write_dataset
from .engine import BugIndex, Triager

DATA_DIR = Path(os.environ.get("BUGTRIAGE_DATA", Path(__file__).resolve().parents[2] / "data"))

log = logging.getLogger("bugtriage")


@lru_cache(maxsize=1)
def load_state() -> dict:
    if not (DATA_DIR / "bugs.jsonl").exists():
        write_dataset(DATA_DIR)
    bugs, logs = load_bugs(DATA_DIR / "bugs.jsonl"), load_logs(DATA_DIR / "logs.jsonl")
    t = time.perf_counter()
    state = {"bugs": bugs, "logs": logs, "index": BugIndex(bugs), "triager": Triager().fit(bugs)}
    log.info("loaded %d bugs, %d log lines, models fit in %.2fs", len(bugs), len(logs), time.perf_counter() - t)
    return state
