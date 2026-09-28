"""gRPC server over the same triage engine the MCP server uses.

MCP is the interface for LLM clients. This is the interface for other services
(a ticketing webhook, a CI job, a batch backfill) that want a typed contract,
proper status codes and low per-call overhead. Both share one loaded model state.

Run:  python -m bugtriage_mcp.grpc_server               (listens on :50051)
      GRPC_PORT=6000 python -m bugtriage_mcp.grpc_server

Stubs are generated from proto/bugtriage_mcp/v1/triage.proto; regenerate with
    python -m grpc_tools.protoc -Iproto --python_out=src --pyi_out=src --grpc_python_out=src \
        proto/bugtriage_mcp/v1/triage.proto
"""
from __future__ import annotations

import logging
import os
import signal
import sys
import time
from concurrent import futures

import grpc

from .engine import search_logs as _search_logs
from .state import load_state
from .v1 import triage_pb2 as pb
from .v1 import triage_pb2_grpc as pb_grpc

log = logging.getLogger("bugtriage.grpc")

MAX_TEXT = 20_000  # characters; reject oversized payloads instead of vectorising them


def _bug(b) -> pb.Bug:
    return pb.Bug(id=b.id, title=b.title, description=b.description, component=b.component, severity=b.severity)


def _clamp(v: int, default: int, lo: int, hi: int) -> int:
    return default if v <= 0 else max(lo, min(v, hi))


class BugTriageServicer(pb_grpc.BugTriageServicer):
    def __init__(self, state: dict | None = None) -> None:
        self.s = state or load_state()

    def TriageBug(self, request, context):
        if not (request.title or request.description):
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, "title or description is required")
        if len(request.title) + len(request.description) > MAX_TEXT:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, f"text longer than {MAX_TEXT} characters")
        r = self.s["triager"].predict(request.title, request.description)
        dups = self.s["index"].search(f"{request.title}. {request.description}", k=3)
        return pb.TriageBugResponse(
            component=r["component"],
            component_confidence=r["component_confidence"],
            component_alternatives=[pb.ComponentProbability(component=a["component"], p=a["p"])
                                    for a in r["component_alternatives"]],
            severity=r["severity"],
            severity_probs=r["severity_probs"],
            error_codes=r["error_codes"],
            needs_human_review=r["needs_human_review"],
            possible_duplicates=[_bug(h.bug) for h in dups],
        )

    def FindSimilarBugs(self, request, context):
        if not request.text.strip():
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, "text is required")
        if len(request.text) > MAX_TEXT:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, f"text longer than {MAX_TEXT} characters")
        k = _clamp(request.k, 5, 1, 20)
        hits = self.s["index"].search(request.text, k=k)
        return pb.FindSimilarBugsResponse(hits=[pb.ScoredBug(bug=_bug(h.bug), score=h.score) for h in hits])

    def GetBug(self, request, context):
        b = self.s["index"].by_id.get(request.bug_id)
        if b is None:
            context.abort(grpc.StatusCode.NOT_FOUND, f"unknown bug id {request.bug_id}")
        return _bug(b)

    def SearchLogs(self, request, context):
        try:
            r = _search_logs(self.s["logs"], request.query, request.level or None, request.module or None,
                             request.since or None, request.until or None, _clamp(request.limit, 50, 1, 200))
        except ValueError as e:  # malformed ISO timestamp
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(e))
        return pb.SearchLogsResponse(
            total_matches=r["total_matches"],
            code_counts=r["code_counts"],
            affected_vehicles=r["affected_vehicles"],
            lines=[pb.LogLine(**l) for l in r["lines"]],
        )


class LatencyInterceptor(grpc.ServerInterceptor):
    """One log line per RPC with method, status and latency, like the MCP server's per-tool log."""

    def intercept_service(self, continuation, handler_call_details):
        handler = continuation(handler_call_details)
        if handler is None or handler.unary_unary is None:
            return handler
        method, inner = handler_call_details.method, handler.unary_unary

        def wrapped(request, context):
            t = time.perf_counter()
            try:
                return inner(request, context)
            finally:
                code = context.code() if hasattr(context, "code") else None
                log.info("rpc=%s status=%s latency_ms=%.1f", method, getattr(code, "name", code) or "OK",
                         (time.perf_counter() - t) * 1000)

        return grpc.unary_unary_rpc_method_handler(wrapped, request_deserializer=handler.request_deserializer,
                                                   response_serializer=handler.response_serializer)


def build_server(port: int, state: dict | None = None, max_workers: int = 8) -> tuple[grpc.Server, int]:
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=max_workers), interceptors=[LatencyInterceptor()],
                         options=[("grpc.max_receive_message_length", 1 * 1024 * 1024)])
    pb_grpc.add_BugTriageServicer_to_server(BugTriageServicer(state), server)
    bound = server.add_insecure_port(f"[::]:{port}")  # put TLS / mTLS at the ingress or pass server credentials here
    return server, bound


def main() -> None:
    logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    load_state()  # fit models before accepting traffic
    server, port = build_server(int(os.environ.get("GRPC_PORT", 50051)))
    server.start()
    log.info("gRPC BugTriage listening on :%d", port)
    signal.signal(signal.SIGTERM, lambda *_: server.stop(grace=5))
    server.wait_for_termination()


if __name__ == "__main__":
    main()
