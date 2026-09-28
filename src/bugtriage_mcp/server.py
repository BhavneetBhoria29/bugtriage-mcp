"""MCP server exposing bug-triage and log-search tools to any MCP client (Claude, Cursor, an agent).

Run:  python -m bugtriage_mcp.server            (stdio, for Claude Desktop / Claude Code)
      python -m bugtriage_mcp.server --http     (streamable HTTP on :8000, for containers)
"""
from __future__ import annotations

import logging
import os
import sys
import time
from functools import wraps

from mcp.server.fastmcp import FastMCP

from .engine import cluster_bugs as _cluster, search_logs as _search_logs
from .state import load_state as _state

# stdout is the MCP transport in stdio mode, so all logging goes to stderr
logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("bugtriage")

mcp = FastMCP("bugtriage", host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))


def _timed(fn):
    """Per-tool latency log line; cheap stand-in for a proper tracing backend."""
    @wraps(fn)
    def wrapper(*a, **kw):
        t = time.perf_counter()
        try:
            return fn(*a, **kw)
        finally:
            log.info("tool=%s latency_ms=%.1f", fn.__name__, (time.perf_counter() - t) * 1000)
    return wrapper


@mcp.tool()
@_timed
def search_logs(query: str = "", level: str | None = None, module: str | None = None,
                since: str | None = None, until: str | None = None, limit: int = 50) -> dict:
    """Search connectivity-ECU logs. All query tokens must appear in the error code or message.

    level: INFO | WARN | ERROR. module: modem_mgr | wlan_d | bt_stack | ecall_svc | ota_agent | can_gw.
    since/until: ISO timestamps. Returns match count, top error codes, affected vehicles, sample lines.
    """
    limit = max(1, min(limit, 200))
    return _search_logs(_state()["logs"], query, level, module, since, until, limit)


@mcp.tool()
@_timed
def triage_bug(title: str, description: str) -> dict:
    """Predict owning component and severity for a new bug report, with probabilities.

    needs_human_review is true when component confidence is below 0.6.
    Also returns the 3 most similar historical bugs as likely duplicates.
    """
    s = _state()
    result = s["triager"].predict(title, description)
    result["possible_duplicates"] = [
        {"id": h.bug.id, "title": h.bug.title, "component": h.bug.component}
        for h in s["index"].search(f"{title}. {description}", k=3)
    ]
    return result


@mcp.tool()
@_timed
def find_similar_bugs(text: str, k: int = 5) -> list[dict]:
    """Hybrid (BM25 + TF-IDF, reciprocal rank fusion) search over historical bug reports."""
    k = max(1, min(k, 20))
    return [{"id": h.bug.id, "score": round(h.score, 4), "title": h.bug.title,
             "description": h.bug.description, "component": h.bug.component, "severity": h.bug.severity}
            for h in _state()["index"].search(text, k=k)]


@mcp.tool()
@_timed
def get_bug(bug_id: str) -> dict:
    """Fetch one historical bug report by id, e.g. CONMOD-00042."""
    b = _state()["index"].by_id.get(bug_id)
    return b.__dict__ if b else {"error": f"unknown bug id {bug_id}"}


@mcp.tool()
@_timed
def cluster_bugs(n_clusters: int = 8, component: str | None = None) -> list[dict]:
    """Group historical bugs into themes (TF-IDF + k-means) to spot recurring failure patterns.

    Optionally restrict to one component. Returns size, top terms, top error codes, component/severity mix.
    """
    bugs = _state()["bugs"]
    if component:
        bugs = [b for b in bugs if b.component == component]
    n_clusters = max(2, min(n_clusters, 20, len(bugs)))
    return _cluster(bugs, n_clusters=n_clusters)


def main() -> None:
    _state()  # warm up before the first request
    mcp.run(transport="streamable-http" if "--http" in sys.argv else "stdio")


if __name__ == "__main__":
    main()
