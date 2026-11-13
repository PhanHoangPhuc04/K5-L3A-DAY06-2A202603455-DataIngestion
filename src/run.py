"""Day 06 pipeline. Run from repo root:

    python -m src.run ingest       # raw HTML -> clean units, manifest, error log
    python -m src.run check        # verify every benchmark evidence quote exists in its gold article
    python -m src.run experiment   # build A/B/C in Chroma, run benchmark, write traces + metrics
    python -m src.run reingest     # re-ingest same version, prove no duplicates
"""
from __future__ import annotations

import csv
import hashlib
import json
import platform
import statistics
import sys
import time
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path

from .chunking import by_paragraph, fixed_size
from .evaluation import evaluate_query, norm, summarize
from .ingestion import load_corpus, write_clean
from .models import Chunk, DocumentPage

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"
BENCH = ROOT / "benchmark" / "questions.json"
CLEAN = ROOT / "data" / "clean" / "units.jsonl"
STORE = ROOT / "store" / "chroma"

STRATEGIES = {
    "A": {"chunking": "fixed_size", "size": 500, "overlap": 50, "use_filter": False},
    "B": {"chunking": "by_paragraph", "max_size": 1000, "use_filter": False},
    "C": {"chunking": "by_paragraph", "max_size": 1000, "use_filter": True},
}


def _dump(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_pages() -> list[DocumentPage]:
    if not CLEAN.exists():
        sys.exit("data/clean/units.jsonl missing: run `python -m src.run ingest` first")
    return [DocumentPage(**json.loads(line)) for line in CLEAN.read_text(encoding="utf-8").splitlines()]


def cmd_ingest() -> None:
    errors: list[dict] = []
    t0 = time.perf_counter()
    pages = load_corpus(errors)
    write_clean(pages, CLEAN)
    sources = json.loads((ROOT / "data" / "sources.json").read_text(encoding="utf-8"))["sources"]
    manifest = {"unit_rule": "1 unit = 1 Điều (article) of the law, a self-contained legal provision; "
                             "text after NFC + whitespace normalization. HTML has no physical pages.",
                "license_or_permission": "Văn bản quy phạm pháp luật không thuộc phạm vi bảo hộ quyền tác giả "
                                         "(Điều 15 khoản 2 Luật Sở hữu trí tuệ 2005, sửa đổi 2009/2019/2022). "
                                         "HTML snapshot từ caselaw.vn chỉ dùng để lấy toàn văn; phần giao diện web bị loại khi parse.",
                "documents": []}
    for s in sources:
        units = [p for p in pages if p.document_id == s["document_id"]]
        chars = [p.metadata["char_count"] for p in units]
        manifest["documents"].append({
            "source_id": s["document_id"], "title": s["title"], "source_path_or_url": s["url"],
            "raw_snapshot": s["raw_path"],
            "raw_sha256": hashlib.sha256((ROOT / s["raw_path"]).read_bytes()).hexdigest(),
            "license_or_permission": manifest["license_or_permission"], "accessed_at": s["accessed_at"],
            "version_year": s["version_year"], "effective_date": s["effective_date"],
            "is_current": s["is_current"], "unit_count": len(units), "char_total": sum(chars),
            "units": [{"page_id": p.metadata["unit_id"], "article": p.page,
                       "title": p.metadata["article_title"], "chapter": p.metadata["chapter"],
                       "char_count": p.metadata["char_count"]} for p in units]})
    total_chars = sum(p.metadata["char_count"] for p in pages)
    manifest["totals"] = {"units": len(pages), "char_total": total_chars,
                          "units_ge_1500_chars": sum(p.metadata["char_count"] >= 1500 for p in pages),
                          "equivalent_1500_char_units": total_chars // 1500}
    _dump(ROOT / "data" / "manifest.json", manifest)
    _dump(RESULTS / "ingest_errors.json", errors)
    print(f"units={len(pages)} chars={total_chars} errors={len(errors)} "
          f"time={time.perf_counter() - t0:.2f}s")
    for e in errors:
        print("  ERROR", e)


def cmd_check() -> None:
    """Evidence must sit in the gold article after normalization; filters must be real values."""
    pages = {(p.document_id, p.page): p for p in _load_pages()}
    bench = json.loads(BENCH.read_text(encoding="utf-8"))
    qs = bench["questions"]
    problems = []
    for q in qs:
        for g in q["gold"]:
            p = pages.get((g["source_id"], int(g["page"])))
            if p is None:
                problems.append(f"{q['id']}: gold unit {g} not found")
            elif norm(g["evidence_quote"]) not in norm(p.text):
                problems.append(f"{q['id']}: evidence not in {g['source_id']} Điều {g['page']}")
            if q.get("filter") and p is not None:
                for k, v in q["filter"].items():
                    if p.metadata.get(k) != v:
                        problems.append(f"{q['id']}: gold unit does not satisfy filter {k}={v}")
    splits = {s: sum(q["split"] == s for q in qs) for s in ("dev", "test")}
    filt = {s: sum(bool(q.get("filter")) and q["split"] == s for q in qs) for s in ("dev", "test")}
    print(f"questions={len(qs)} split={splits} filter_questions={filt}")
    print(f"benchmark sha256={hashlib.sha256(BENCH.read_bytes()).hexdigest()}")
    if problems:
        print("\n".join(problems)); sys.exit(1)
    print("All evidence verified.")


def build_chunks(pages: list[DocumentPage], cfg: dict) -> list[Chunk]:
    out: list[Chunk] = []
    for p in pages:
        out += (fixed_size(p, cfg["size"], cfg["overlap"]) if cfg["chunking"] == "fixed_size"
                else by_paragraph(p, cfg["max_size"]))
    return out


def _index(store, embedder, pages):
    stats = {}
    built: dict[str, list[Chunk]] = {}
    for name, cfg in STRATEGIES.items():
        key = json.dumps({k: v for k, v in cfg.items() if k != "use_filter"}, sort_keys=True)
        t0 = time.perf_counter()
        reuse = next((n for n, c in built.items()
                      if json.dumps({k: v for k, v in STRATEGIES[n].items() if k != "use_filter"},
                                    sort_keys=True) == key), None)
        chunks = build_chunks(pages, cfg)
        vecs = embedder.embed_documents([c.text for c in chunks])
        up = store.upsert(name, chunks, vecs)
        lens = [len(c.text) for c in chunks]
        toks = [embedder.token_count(c.text) for c in chunks]
        stats[name] = {**cfg, "chunks": len(chunks), "chars_total": sum(lens),
                       "len_min": min(lens), "len_median": statistics.median(lens),
                       "len_mean": round(statistics.mean(lens), 1), "len_max": max(lens),
                       "tokens_total": sum(toks), "tokens_max": max(toks),
                       "chunks_over_model_limit": sum(t > embedder.max_seq_length for t in toks),
                       "ingest_seconds": round(time.perf_counter() - t0, 2), "cost_usd": 0,
                       "same_chunks_as": reuse, "upsert": up}
        built[name] = chunks
    return stats


def cmd_experiment() -> None:
    from .embeddings import E5Embedder
    from .store import ChromaStore
    pages = _load_pages()
    bench = json.loads(BENCH.read_text(encoding="utf-8"))
    t0 = time.perf_counter()
    emb = E5Embedder()
    load_s = round(time.perf_counter() - t0, 2)
    store = ChromaStore(STORE, emb.dimensions, emb.model_name)
    stats = _index(store, emb, pages)

    traces = []
    for name, cfg in STRATEGIES.items():
        t1 = time.perf_counter()
        for q in bench["questions"]:
            filt = q.get("filter") if cfg["use_filter"] else None
            hits = store.search(name, emb.embed_query(q["question"]), 3, filt)
            traces.append({"strategy": name, "id": q["id"], "split": q["split"], "type": q["type"],
                           "question": q["question"], "filter_in_question": q.get("filter"),
                           "filter_applied": filt, "gold": q["gold"], "hits": hits,
                           "eval": evaluate_query(q, hits)})
        stats[name]["query_seconds"] = round(time.perf_counter() - t1, 2)

    summary = summarize(traces)
    run_info = {"run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "python": platform.python_version(), "platform": platform.platform(),
                "embedding_model": emb.model_name, "dimensions": emb.dimensions,
                "max_seq_length": emb.max_seq_length, "model_load_seconds": load_s,
                "query_prefix": "query: ", "document_prefix": "passage: ", "normalized": True,
                "vector_store": f"chromadb {version('chromadb')} PersistentClient ({STORE.relative_to(ROOT)}), "
                                "HNSW approximate search, space=cosine",
                "libraries": {p: version(p) for p in ("sentence-transformers", "torch", "transformers",
                                                      "chromadb", "beautifulsoup4")},
                "benchmark_sha256": hashlib.sha256(BENCH.read_bytes()).hexdigest()}
    RESULTS.mkdir(exist_ok=True)
    for name in STRATEGIES:
        with (RESULTS / f"trace_{name}.jsonl").open("w", encoding="utf-8") as f:
            for t in traces:
                if t["strategy"] == name:
                    f.write(json.dumps(t, ensure_ascii=False) + "\n")
    _dump(RESULTS / "index_stats.json", stats)
    _dump(RESULTS / "metrics.json", {"run": run_info, "summary": summary})
    _write_table(summary, stats)
    print(json.dumps(run_info, ensure_ascii=False, indent=1))
    for k, s in summary.items():
        print(f"{k}: hit@1 {s['hit1']}/{s['n']}  hit@3 {s['hit3']}/{s['n']}  "
              f"split_evidence {s['split_evidence']}  filter {s['filter_ok']}/{s['filter_q']}")


def _write_table(summary, stats) -> None:
    with (RESULTS / "metrics_table.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["strategy", "split", "hit1", "hit3", "n", "split_evidence", "filter_ok", "filter_q",
                    "chunks", "ingest_seconds", "query_seconds", "cost_usd"])
        for s in summary.values():
            st = stats[s["strategy"]]
            w.writerow([s["strategy"], s["split"], s["hit1"], s["hit3"], s["n"], s["split_evidence"],
                        s["filter_ok"], s["filter_q"], st["chunks"], st["ingest_seconds"],
                        st["query_seconds"], 0])


def cmd_reingest() -> None:
    from .embeddings import E5Embedder
    from .store import ChromaStore
    pages = _load_pages()
    emb = E5Embedder()
    store = ChromaStore(STORE, emb.dimensions, emb.model_name)
    report = {}
    for name in ("A", "B"):
        chunks = build_chunks(pages, STRATEGIES[name])
        up = store.upsert(name, chunks, emb.embed_documents([c.text for c in chunks]))
        report[name] = {"chunks_in_input": len(chunks), **up,
                        "duplicates": up["after"] - len(chunks)}
    _dump(RESULTS / "reingest_check.json", report)
    print(json.dumps(report, indent=1))


if __name__ == "__main__":
    cmds = {"ingest": cmd_ingest, "check": cmd_check, "experiment": cmd_experiment,
            "reingest": cmd_reingest}
    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    if arg not in cmds:
        sys.exit(__doc__)
    cmds[arg]()
