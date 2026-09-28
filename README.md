# bugtriage-mcp

<img width="2633" height="1895" alt="1CD65DA2-C3A3-4549-83B0-976802D26EB9" src="https://github.com/user-attachments/assets/ff14e1c2-905e-42e3-9f80-100f63e33e01" />


An MCP server that gives any AI assistant or agent ML-backed tools for bug analysis on a vehicle connectivity module (LTE modem, WiFi, Bluetooth, eCall, OTA, CAN gateway): search ECU logs, triage a new bug report, find likely duplicates, and cluster historical bugs into recurring failure themes.

I built it to explore what "AI in the series development process" looks like in practice. It's the sort of tooling a dev team could point Claude Code or an internal agent at: engineers ask in plain language, and the agent calls real models instead of guessing.

> **All data is synthetic.** There is no real automotive data here. The generator (`src/bugtriage_mcp/data.py`) is deliberately noisy: shared vocabulary across components, 5% mislabeled tickets, vague reporter titles, and error codes shared by many unrelated root causes. That keeps the eval honest. The numbers below describe this synthetic set, not real-world performance.

## Tools

| Tool | What it does | Under the hood |
|---|---|---|
| `triage_bug` | Predicts owning component and severity with probabilities, extracts error codes, flags low-confidence cases for human review, returns 3 likely duplicates | TF-IDF word + char n-grams → logistic regression |
| `find_similar_bugs` | Duplicate / related-bug search | BM25 + TF-IDF cosine + structured-signal match, fused with reciprocal rank fusion |
| `cluster_bugs` | Groups bugs into themes, with top terms, top error codes, component and severity mix | TF-IDF + k-means |
| `search_logs` | Filters ECU logs by text, level, module, time window; returns error-code counts and affected vehicles | In-memory scan |
| `get_bug` | Fetches one ticket | |

## Results

`python eval/run_eval.py` — the train/test split is **grouped by root cause** (a random split leaks near-duplicate tickets across the split and inflates everything). 218 test bugs, 95% bootstrap CIs over 1000 resamples.

| Metric | Score |
|---|---|
| Component accuracy | 0.917 [0.876, 0.954] |
| Component macro-F1 | 0.917 [0.877, 0.951] |
| Severity macro-F1 | 0.463 [0.399, 0.526] (majority baseline 0.198) |
| Human-review gate | flags 15.6% of tickets; accuracy 0.957 on auto-routed vs 0.706 on flagged |

Duplicate retrieval (relevant = other tickets with the same root cause):

| Ranker | Recall@5 | MRR@10 |
|---|---|---|
| BM25 | 0.165 [0.138, 0.190] | 0.319 [0.271, 0.368] |
| TF-IDF cosine | 0.155 [0.130, 0.180] | 0.286 [0.242, 0.329] |
| BM25 + TF-IDF (RRF) | 0.165 [0.139, 0.190] | 0.329 [0.281, 0.377] |
| **+ structured signals (RRF)** | **0.275 [0.238, 0.311]** | **0.487 [0.428, 0.544]** |

**What I learned:**

- **Plain hybrid search didn't help.** Duplicate tickets are written by different people with different words, and the same error code turns up across ~25 unrelated root causes, so text similarity mostly matched on template wording. Adding a ranker that matches extracted error codes and firmware builds, weighted by rarity, is what moved recall. The CIs don't overlap with text-only ranking. That's the same thing a triage engineer does by eye: same FW build + same code → probably the same bug.
- **Severity is hard from text alone** (0.46 macro-F1). It's well above baseline but not something to auto-assign. In a real setup it should come from telemetry and the component's safety classification, with the model only suggesting.
- **The review gate is worth more than a few accuracy points.** At confidence < 0.6 it routes 16% of tickets to a human, and those are exactly where the model is weakest (71% vs 96%).

Latency per tool call (900 bugs, 20k log lines, single process): `triage_bug` p95 8 ms, `find_similar_bugs` p95 4 ms, `search_logs` p95 3 ms, `cluster_bugs` p95 81 ms. Models fit at startup in about 1 s.

## Run it

```bash
pip install -e ".[dev]"
python -m bugtriage_mcp.data          # generate synthetic data into ./data
pytest -q                             # 17 tests incl. an MCP stdio round-trip and a gRPC round-trip
python eval/run_eval.py               # metrics above, also written to eval/results.json
python eval/run_eval.py --wandb       # same, plus logs the run to Weights & Biases (pip install -e ".[wandb]")
```

**Experiment tracking (W&B):** `--wandb` logs the eval config (split, seed, bootstrap count, review-gate threshold, git SHA), every metric with its CI bounds, a per-ranker retrieval table, and `results.json` as a versioned artifact. That makes it easy to see whether a change to the retriever or the gate actually moved the numbers or just moved them inside the CI. `WANDB_MODE=offline` works without an account. Example run: [bugtriage-mcp on W&B](https://wandb.ai/bhavrajput97-brandenburgische-technische-universit-t-cot/bugtriage-mcp/runs/w2y1v2g8).

**Claude Desktop / Claude Code (stdio):**

```json
{
  "mcpServers": {
    "bugtriage": {
      "command": "python",
      "args": ["-m", "bugtriage_mcp.server"],
      "env": { "PYTHONPATH": "/path/to/bugtriage-mcp/src" }
    }
  }
}
```

Or with Claude Code: `claude mcp add bugtriage -- python -m bugtriage_mcp.server`

**Container (streamable HTTP on `:8000/mcp`):**

```bash
docker build -t bugtriage-mcp .
docker run -p 8000:8000 bugtriage-mcp
```

**gRPC (service-to-service):**

MCP is the right interface for an LLM client. For another service calling the same models (a ticketing webhook that auto-triages new tickets, a CI job, a backfill), I added a typed gRPC API over the same engine and shared model state. Contract is in [`proto/bugtriage_mcp/v1/triage.proto`](proto/bugtriage_mcp/v1/triage.proto): `TriageBug`, `FindSimilarBugs`, `GetBug`, `SearchLogs`.

```bash
pip install -e ".[grpc]"
python -m bugtriage_mcp.grpc_server   # :50051, override with GRPC_PORT
```

```python
import grpc
from bugtriage_mcp.v1 import triage_pb2 as pb, triage_pb2_grpc as rpc

stub = rpc.BugTriageStub(grpc.insecure_channel("localhost:50051"))
r = stub.TriageBug(pb.TriageBugRequest(title="Hotspot drops after cold start", description="DHCP_NO_LEASE, FW 4.2.17"))
print(r.component, r.component_confidence, r.needs_human_review)
```

Bad input gets `INVALID_ARGUMENT`, an unknown bug id gets `NOT_FOUND`, and payloads over 20k characters are rejected before vectorising. An interceptor logs method, status and latency per RPC. Client-side over loopback (300 calls each, single process): `TriageBug` p95 7.6 ms, `FindSimilarBugs` p95 4.0 ms, `SearchLogs` p95 4.6 ms. TLS is left to the ingress for now.

Example prompts once it's connected:
- "Triage this: hotspot drops after cold start, DHCP_NO_LEASE in the log, FW 4.2.17"
- "How many CAN_BUS_OFF errors did we log last week, and on how many vehicles?"
- "Cluster the OTA bugs and tell me which failure pattern is growing"

## Design notes

- Logging goes to stderr because stdout is the MCP transport in stdio mode. Every tool call logs its latency.
- One model state (`state.py`) is shared by both transports, so MCP and gRPC can never disagree about a prediction.
- Tool inputs are clamped (`limit`, `k`, `n_clusters`) so an agent can't ask for 10k rows by accident.
- Classical ML on purpose: it trains in a second, runs in a small container, and is easy to inspect. The obvious next step on real data is swapping the TF-IDF features for sentence embeddings behind the same interface and checking whether the eval moves.

## Limitations

- Synthetic data. The signal structure (codes, FW builds, triggers) is modeled on how connectivity bugs are usually reported, but real tickets will be messier and multilingual (German/English mix).
- Logs are held in memory. At fleet scale this would sit on a log store (OpenSearch, ClickHouse) and the tool would translate filters into queries.
- Models refit at startup. A real deployment would version models, track eval scores per version, and retrain on newly closed tickets.
