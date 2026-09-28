"""Core ML: hybrid similar-bug retrieval, supervised triage, unsupervised clustering, log search.

Kept framework-free (scikit-learn + rank-bm25) so it runs on a laptop and in a
small container. The MCP layer in server.py is a thin wrapper around this.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime

import numpy as np
from rank_bm25 import BM25Okapi
from sklearn.cluster import KMeans
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import FeatureUnion, Pipeline

from .data import Bug, LogLine

_TOKEN = re.compile(r"[A-Za-z0-9_=]+")
_ERR_CODE = re.compile(r"\b[A-Z][A-Z0-9]+(?:_[A-Z0-9]+)+\b")
_FW = re.compile(r"\bFW \d+\.\d+\.\d+\b")


def signals(text: str) -> set[str]:
    """Structured fields a triage engineer would match on: error codes and firmware builds."""
    return set(_ERR_CODE.findall(text)) | set(_FW.findall(text))


def tokenize(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN.findall(text)]


def bug_text(b: Bug) -> str:
    return f"{b.title}. {b.description}"


def _features() -> FeatureUnion:
    # word n-grams for wording, char n-grams so error codes like NAS_REJECT still match partially
    return FeatureUnion([
        ("word", TfidfVectorizer(ngram_range=(1, 2), min_df=2, sublinear_tf=True)),
        ("char", TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), min_df=3, sublinear_tf=True)),
    ])


# ---------------------------------------------------------------- triage (supervised)
class Triager:
    """Predicts component and severity with calibrated-ish probabilities (logistic regression)."""

    def __init__(self) -> None:
        self.component = Pipeline([("f", _features()), ("clf", LogisticRegression(max_iter=2000, C=4.0))])
        self.severity = Pipeline([("f", _features()), ("clf", LogisticRegression(max_iter=2000, C=1.0, class_weight="balanced"))])

    def fit(self, bugs: list[Bug]) -> "Triager":
        X = [bug_text(b) for b in bugs]
        self.component.fit(X, [b.component for b in bugs])
        # severity also sees the component so eCall-type issues lean critical
        self.severity.fit([f"{b.component} {x}" for b, x in zip(bugs, X)], [b.severity for b in bugs])
        return self

    def predict(self, title: str, description: str, top_k: int = 3) -> dict:
        text = f"{title}. {description}"
        cp = self.component.predict_proba([text])[0]
        comp_classes = self.component.classes_
        order = np.argsort(cp)[::-1][:top_k]
        comp = comp_classes[order[0]]
        sp = self.severity.predict_proba([f"{comp} {text}"])[0]
        sev_classes = self.severity.classes_
        confidence = float(cp[order[0]])
        return {
            "component": comp,
            "component_confidence": round(confidence, 3),
            "component_alternatives": [{"component": comp_classes[i], "p": round(float(cp[i]), 3)} for i in order],
            "severity": sev_classes[int(np.argmax(sp))],
            "severity_probs": {c: round(float(p), 3) for c, p in zip(sev_classes, sp)},
            "error_codes": sorted(set(_ERR_CODE.findall(text))),
            # low confidence goes to a human instead of silently auto-routing
            "needs_human_review": confidence < 0.6,
        }


# ---------------------------------------------------------------- similar bugs (hybrid retrieval)
@dataclass
class Hit:
    bug: Bug
    score: float


class BugIndex:
    """BM25 (terms) + TF-IDF cosine (wording) + structured-signal match (error codes, FW builds),
    fused with reciprocal rank fusion. mode="hybrid" uses the first two only, "hybrid+signals" all three.
    """

    def __init__(self, bugs: list[Bug], rrf_k: int = 60) -> None:
        self.bugs = bugs
        self.by_id = {b.id: b for b in bugs}
        self.rrf_k = rrf_k
        texts = [bug_text(b) for b in bugs]
        self.sigs = [signals(t) for t in texts]
        df = Counter(s for sig in self.sigs for s in sig)
        # rare signals (one FW build) count more than common ones (an error code shared by 25 root causes)
        self.sig_idf = {s: np.log(len(bugs) / c) for s, c in df.items()}
        self.bm25 = BM25Okapi([tokenize(t) for t in texts])
        self.vec = _features().fit(texts)
        m = self.vec.transform(texts)
        self.mat = m.multiply(1 / np.sqrt(m.multiply(m).sum(axis=1))).tocsr()  # row-normalise

    def _dense_scores(self, query: str) -> np.ndarray:
        q = self.vec.transform([query])
        q = q / max(np.sqrt(q.multiply(q).sum()), 1e-9)
        return np.asarray((self.mat @ q.T).todense()).ravel()

    def _signal_scores(self, query: str) -> np.ndarray:
        q = signals(query)
        return np.array([sum(self.sig_idf.get(s, 0.0) for s in q & sig) for sig in self.sigs])

    def search(self, query: str, k: int = 5, mode: str = "hybrid+signals", exclude_id: str | None = None) -> list[Hit]:
        n = len(self.bugs)
        if mode == "bm25":
            fused = np.asarray(self.bm25.get_scores(tokenize(query)))
        elif mode == "dense":
            fused = self._dense_scores(query)
        else:
            rankers = [self.bm25.get_scores(tokenize(query)), self._dense_scores(query)]
            if mode == "hybrid+signals":
                rankers.append(self._signal_scores(query))
            fused = np.zeros(n)
            for scores in rankers:
                ranks = np.empty(n, dtype=int)
                ranks[np.argsort(-np.asarray(scores))] = np.arange(n)
                fused += 1.0 / (self.rrf_k + ranks + 1)
        hits = []
        for i in np.argsort(-fused):
            if self.bugs[i].id == exclude_id:
                continue
            hits.append(Hit(self.bugs[i], float(fused[i])))
            if len(hits) == k:
                break
        return hits


# ---------------------------------------------------------------- clustering (unsupervised)
def cluster_bugs(bugs: list[Bug], n_clusters: int = 8, seed: int = 0) -> list[dict]:
    texts = [bug_text(b) for b in bugs]
    vec = TfidfVectorizer(ngram_range=(1, 2), min_df=2, max_df=0.5, sublinear_tf=True, stop_words="english")
    X = vec.fit_transform(texts)
    km = KMeans(n_clusters=n_clusters, n_init=10, random_state=seed).fit(X)
    terms = np.array(vec.get_feature_names_out())
    out = []
    for c in range(n_clusters):
        idx = np.where(km.labels_ == c)[0]
        members = [bugs[i] for i in idx]
        codes = Counter(code for b in members for code in _ERR_CODE.findall(bug_text(b)))
        out.append({
            "cluster": c,
            "size": len(members),
            "top_terms": terms[np.argsort(-km.cluster_centers_[c])[:6]].tolist(),
            "top_error_codes": [c_ for c_, _ in codes.most_common(3)],
            "component_mix": dict(Counter(b.component for b in members).most_common(3)),
            "severity_mix": dict(Counter(b.severity for b in members)),
            "example_ids": [b.id for b in members[:5]],
        })
    return sorted(out, key=lambda d: -d["size"])


# ---------------------------------------------------------------- log search
def search_logs(logs: list[LogLine], query: str = "", level: str | None = None, module: str | None = None,
                since: str | None = None, until: str | None = None, limit: int = 50) -> dict:
    q = query.lower().split()
    t0 = datetime.fromisoformat(since) if since else None
    t1 = datetime.fromisoformat(until) if until else None
    matched = []
    for l in logs:
        if level and l.level != level.upper():
            continue
        if module and l.module != module:
            continue
        ts = datetime.fromisoformat(l.ts)
        if (t0 and ts < t0) or (t1 and ts > t1):
            continue
        hay = f"{l.code} {l.message}".lower()
        if all(tok in hay for tok in q):
            matched.append(l)
    return {
        "total_matches": len(matched),
        "code_counts": dict(Counter(l.code for l in matched).most_common(10)),
        "affected_vehicles": len({l.vin_suffix for l in matched}),
        "lines": [l.__dict__ for l in matched[:limit]],
    }
