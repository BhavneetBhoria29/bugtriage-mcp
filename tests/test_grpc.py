"""gRPC round-trip: start the real server on a free port and call it through generated stubs."""
import grpc
import pytest

from bugtriage_mcp.grpc_server import build_server
from bugtriage_mcp.v1 import triage_pb2 as pb
from bugtriage_mcp.v1 import triage_pb2_grpc as pb_grpc


@pytest.fixture(scope="module")
def stub():
    server, port = build_server(0)  # port 0 = let the OS pick
    server.start()
    channel = grpc.insecure_channel(f"localhost:{port}")
    yield pb_grpc.BugTriageStub(channel)
    channel.close()
    server.stop(grace=None)


def test_triage_bug(stub):
    r = stub.TriageBug(pb.TriageBugRequest(title="WiFi hotspot drops",
                                           description="clients lose DHCP lease, DHCP_NO_LEASE in log"))
    assert r.component == "wifi"
    assert 0 < r.component_confidence <= 1
    assert "DHCP_NO_LEASE" in r.error_codes
    assert len(r.possible_duplicates) == 3
    assert abs(sum(r.severity_probs.values()) - 1) < 1e-2


def test_find_similar_clamps_k(stub):
    assert len(stub.FindSimilarBugs(pb.FindSimilarBugsRequest(text="CAN_BUS_OFF after deep sleep", k=500)).hits) == 20
    assert len(stub.FindSimilarBugs(pb.FindSimilarBugsRequest(text="CAN_BUS_OFF after deep sleep")).hits) == 5


def test_get_bug_roundtrip_and_not_found(stub):
    first = stub.FindSimilarBugs(pb.FindSimilarBugsRequest(text="OTA signature", k=1)).hits[0].bug
    assert stub.GetBug(pb.GetBugRequest(bug_id=first.id)).title == first.title
    with pytest.raises(grpc.RpcError) as e:
        stub.GetBug(pb.GetBugRequest(bug_id="CONMOD-99999"))
    assert e.value.code() == grpc.StatusCode.NOT_FOUND


def test_search_logs(stub):
    r = stub.SearchLogs(pb.SearchLogsRequest(query="ota_sig_invalid", level="ERROR", limit=3))
    assert r.total_matches > 0 and len(r.lines) <= 3 and r.affected_vehicles > 0


def test_invalid_arguments(stub):
    for call, req in [(stub.TriageBug, pb.TriageBugRequest()),
                      (stub.FindSimilarBugs, pb.FindSimilarBugsRequest(text="  ")),
                      (stub.SearchLogs, pb.SearchLogsRequest(since="not-a-date"))]:
        with pytest.raises(grpc.RpcError) as e:
            call(req)
        assert e.value.code() == grpc.StatusCode.INVALID_ARGUMENT
