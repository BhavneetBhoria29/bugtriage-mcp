"""Eval harness: triage accuracy and duplicate-retrieval quality with bootstrap confidence intervals.

Split is grouped by root cause, so near-duplicate tickets never sit on both sides
of the split (a random split leaks and inflates every number).

    python eval/run_eval.py            # prints table, writes eval/results.json
    python eval/run_eval.py --wandb    # also logs the run to Weights & Biases

W&B is optional: without --wandb nothing is imported or sent. With it, the run logs
config (split, bootstrap settings, gate threshold), every metric with its CI bounds,
a per-mode retrieval table, and results.json as a versioned artifact, so eval runs
can be compared across code changes. Set WANDB_MODE=offline to log locally with no account.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
from sklearn.metrics import f1_score
from sklearn.model_selection import GroupShuffleSplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from bugtriage_mcp.data import generate_bugs  # noqa: E402
from bugtriage_mcp.engine import BugIndex, Triager, bug_text  # noqa: E402

N_BOOT = 1000


def boot_ci(values: np.ndarray, stat=np.mean, seed: int = 0) -> tuple[float, float, float]:
    rng = np.random.default_rng(seed)
    n = len(values)
    samples = [stat(values[rng.integers(0, n, n)]) for _ in range(N_BOOT)]
    return float(stat(values)), float(np.percentile(samples, 2.5)), float(np.percentile(samples, 97.5))


def boot_f1(y_true, y_pred, seed: int = 0) -> tuple[float, float, float]:
    y_true, y_pred = np.asarray(y_true), np.asarray(y_pred)
    rng = np.random.default_rng(seed)
    n = len(y_true)
    samples = []
    for _ in range(N_BOOT):
        i = rng.integers(0, n, n)
        samples.append(f1_score(y_true[i], y_pred[i], average="macro"))
    return float(f1_score(y_true, y_pred, average="macro")), float(np.percentile(samples, 2.5)), float(np.percentile(samples, 97.5))


def fmt(t):
    return f"{t[0]:.3f} [{t[1]:.3f}, {t[2]:.3f}]"


def _git_sha() -> str | None:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, text=True,
                                       stderr=subprocess.DEVNULL).strip()
    except Exception:
        return None


def log_to_wandb(results: dict, config: dict, project: str) -> None:
    """Flatten (point, lo, hi) tuples into metric/lo/hi keys so W&B can chart them and compare runs."""
    import wandb  # optional dependency, only needed with --wandb

    run = wandb.init(project=project, job_type="eval", config=config)
    summary: dict[str, float] = {}

    def put(key: str, val) -> None:
        if isinstance(val, (list, tuple)) and len(val) == 3:
            summary[key], summary[f"{key}/ci_lo"], summary[f"{key}/ci_hi"] = val
        elif isinstance(val, (int, float)) and val is not None:
            summary[key] = float(val)

    for k, v in results["component"].items():
        put(f"component/{k}", v)
    for k, v in results["severity"].items():
        put(f"severity/{k}", v)
    for k, v in results["human_review_gate"].items():
        put(f"review_gate/{k}", v)
    table = wandb.Table(columns=["mode", "recall@5", "recall@5_lo", "recall@5_hi", "mrr@10", "mrr@10_lo", "mrr@10_hi"])
    for mode, r in results["retrieval"].items():
        put(f"retrieval/{mode}/recall@5", r["recall@5"])
        put(f"retrieval/{mode}/mrr@10", r["mrr@10"])
        table.add_data(mode, *r["recall@5"], *r["mrr@10"])

    run.summary.update(summary)
    run.log({"retrieval_by_mode": table})
    art = wandb.Artifact("bugtriage-eval-results", type="eval-results")
    art.add_file(str(ROOT / "eval" / "results.json"))
    run.log_artifact(art)
    run.finish()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--wandb", action="store_true", help="log this eval run to Weights & Biases")
    ap.add_argument("--wandb-project", default=os.environ.get("WANDB_PROJECT", "bugtriage-mcp"))
    args = ap.parse_args()
    bugs = generate_bugs()
    groups = [b.root_cause_id for b in bugs]
    tr_idx, te_idx = next(GroupShuffleSplit(n_splits=1, test_size=0.25, random_state=42).split(bugs, groups=groups))
    train, test = [bugs[i] for i in tr_idx], [bugs[i] for i in te_idx]

    # ---- triage
    triager = Triager().fit(train)
    preds = [triager.predict(b.title, b.description) for b in test]
    comp_true, comp_pred = [b.component for b in test], [p["component"] for p in preds]
    sev_true, sev_pred = [b.severity for b in test], [p["severity"] for p in preds]
    comp_correct = np.array([t == p for t, p in zip(comp_true, comp_pred)], dtype=float)
    flagged = np.array([p["needs_human_review"] for p in preds])
    majority = max(set(sev_true), key=sev_true.count)

    # ---- retrieval: query = test bug, relevant = other bugs sharing its root cause (anywhere in corpus)
    index = BugIndex(bugs)
    by_rc: dict[str, set[str]] = {}
    for b in bugs:
        by_rc.setdefault(b.root_cause_id, set()).add(b.id)
    retrieval = {}
    for mode in ("bm25", "dense", "hybrid", "hybrid+signals"):
        rec, rr = [], []
        for b in test:
            relevant = by_rc[b.root_cause_id] - {b.id}
            if not relevant:
                continue
            hits = [h.bug.id for h in index.search(bug_text(b), k=10, mode=mode, exclude_id=b.id)]
            rec.append(len(set(hits[:5]) & relevant) / min(5, len(relevant)))
            rr.append(next((1 / (r + 1) for r, h in enumerate(hits) if h in relevant), 0.0))
        retrieval[mode] = {"recall@5": boot_ci(np.array(rec)), "mrr@10": boot_ci(np.array(rr))}

    results = {
        "dataset": {"total": len(bugs), "train": len(train), "test": len(test), "label_noise": 0.05,
                    "note": "synthetic data; split grouped by root cause"},
        "component": {"accuracy": boot_ci(comp_correct), "macro_f1": boot_f1(comp_true, comp_pred)},
        "severity": {"macro_f1": boot_f1(sev_true, sev_pred),
                     "majority_baseline_macro_f1": f1_score(sev_true, [majority] * len(sev_true), average="macro")},
        "human_review_gate": {
            "flagged_rate": float(flagged.mean()),
            "accuracy_auto_routed": float(comp_correct[~flagged].mean()) if (~flagged).any() else None,
            "accuracy_flagged": float(comp_correct[flagged].mean()) if flagged.any() else None,
        },
        "retrieval": retrieval,
    }
    (ROOT / "eval" / "results.json").write_text(json.dumps(results, indent=2))

    print(f"test bugs: {len(test)} (grouped split, {N_BOOT} bootstrap resamples, 95% CI)\n")
    print(f"component accuracy     {fmt(results['component']['accuracy'])}")
    print(f"component macro-F1     {fmt(results['component']['macro_f1'])}")
    print(f"severity macro-F1      {fmt(results['severity']['macro_f1'])}   (majority baseline {results['severity']['majority_baseline_macro_f1']:.3f})")
    g = results["human_review_gate"]
    print(f"review gate            flags {g['flagged_rate']:.1%}; acc auto-routed {g['accuracy_auto_routed']:.3f} vs flagged {g['accuracy_flagged']:.3f}")
    print("\nduplicate retrieval    recall@5                  MRR@10")
    for mode, r in retrieval.items():
        print(f"  {mode:<15}      {fmt(r['recall@5'])}   {fmt(r['mrr@10'])}")

    if args.wandb:
        config = {"n_boot": N_BOOT, "test_size": 0.25, "split_seed": 42, "split": "GroupShuffleSplit(root_cause)",
                  "review_gate_threshold": 0.6, "rrf_k": 60, "n_bugs": len(bugs), "git_sha": _git_sha()}
        log_to_wandb(results, config, args.wandb_project)


if __name__ == "__main__":
    main()
