import pytest

from bugtriage_mcp.data import generate_bugs, generate_logs
from bugtriage_mcp.engine import BugIndex, Triager, bug_text, cluster_bugs, search_logs, signals


@pytest.fixture(scope="module")
def bugs():
    return generate_bugs(n=400, seed=1)


@pytest.fixture(scope="module")
def triager(bugs):
    return Triager().fit(bugs)


def test_data_is_deterministic():
    assert [b.description for b in generate_bugs(n=50, seed=3)] == [b.description for b in generate_bugs(n=50, seed=3)]


def test_signals_extracts_codes_and_fw():
    s = signals("modem shows PDN_CONNECT_REJECT after update (FW 4.2.17)")
    assert s == {"PDN_CONNECT_REJECT", "FW 4.2.17"}


def test_triage_output_contract(triager):
    r = triager.predict("eCall failure", "SOS button pressed, MSD_TX_FAIL, PSAP never answered")
    assert r["component"] == "ecall"
    assert set(r["severity_probs"]) == {"critical", "major", "minor"}
    assert abs(sum(r["severity_probs"].values()) - 1) < 0.01
    assert "MSD_TX_FAIL" in r["error_codes"]
    assert isinstance(r["needs_human_review"], bool)


def test_vague_report_is_flagged_for_review(triager):
    r = triager.predict("system error", "something broke")
    assert r["needs_human_review"] is True


def test_similar_bugs_excludes_self_and_finds_duplicate(bugs):
    idx = BugIndex(bugs)
    q = bugs[0]
    hits = idx.search(bug_text(q), k=10, exclude_id=q.id)
    assert q.id not in [h.bug.id for h in hits]
    assert len(hits) == 10


@pytest.mark.parametrize("mode", ["bm25", "dense", "hybrid", "hybrid+signals"])
def test_all_retrieval_modes_run(bugs, mode):
    assert len(BugIndex(bugs).search("Bluetooth pairing fails", k=3, mode=mode)) == 3


def test_clusters_cover_all_bugs(bugs):
    clusters = cluster_bugs(bugs, n_clusters=5)
    assert sum(c["size"] for c in clusters) == len(bugs)


def test_log_search_filters():
    logs = generate_logs(n=2000)
    r = search_logs(logs, query="can_bus_off", level="ERROR", module="can_gw", limit=5)
    assert r["total_matches"] > 0
    assert all(l["code"] == "CAN_BUS_OFF" for l in r["lines"])
    assert len(r["lines"]) <= 5
