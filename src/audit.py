"""Build manual-audit sheets (no labels are computed here).

    python -m src.audit sheets   # results/audit/*.md for a human to label
    python -m src.audit score    # read results/audit/labels.json, print aggregate tables

Coherence positions are fixed by rule BEFORE looking at scores: unit index 0, 13, 26, ... 117
of data/clean/units.jsonl (spans both laws); position = middle character of that article.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from .run import CLEAN, RESULTS, STRATEGIES, _load_pages, build_chunks

AUDIT = RESULTS / "audit"


def coherence_positions(pages):
    return [(pages[i], len(pages[i].text) // 2) for i in range(0, len(pages), 13)][:10]


def _chunk_at(chunks, page, offset):
    """Chunk of the same article whose source span covers the offset (closest start if none)."""
    same = [c for c in chunks if c.document_id == page.document_id and c.page == page.page]
    cover = [c for c in same if c.metadata["char_start"] <= offset < c.metadata["char_end"]]
    return (cover or same)[0]


def cmd_sheets() -> None:
    pages = _load_pages()
    AUDIT.mkdir(parents=True, exist_ok=True)
    pos = coherence_positions(pages)
    lines = ["# Coherence audit: 10 vị trí cố định, thang 0/1/2", ""]
    for name in ("A", "B"):  # C uses exactly the same chunks as B
        chunks = build_chunks(pages, STRATEGIES[name])
        for k, (p, off) in enumerate(pos, 1):
            c = _chunk_at(chunks, p, off)
            lines += [f"## {name}-P{k}: {p.metadata['unit_id']} offset {off} -> {c.chunk_id}",
                      "```", c.text, "```", ""]
    (AUDIT / "coherence_sheet.md").write_text("\n".join(lines), encoding="utf-8")

    src = {(p.document_id, p.page): p for p in pages}
    lines = ["# Metadata + grounding audit: câu test x top-3", ""]
    for name in STRATEGIES:
        for t in map(json.loads, (RESULTS / f"trace_{name}.jsonl").read_text(encoding="utf-8").splitlines()):
            if t["split"] != "test":
                continue
            lines += [f"## {name} {t['id']}: {t['question']}", f"filter_applied={t['filter_applied']}",
                      f"gold={[(g['source_id'], g['page']) for g in t['gold']]}", ""]
            for h in t["hits"]:
                m = h["metadata"]
                real = src.get((m["document_id"], int(m["page"])))
                in_source = bool(real) and h["text"].split("\n", 1)[-1][:60] in real.text
                lines += [f"- rank {h['rank']} score {h['score']} `{h['chunk_id']}` source={m['source'][-40:]} "
                          f"page={m['page']} version_year={m['version_year']} "
                          f"title_matches_source={bool(real) and m['article_title'] == real.metadata['article_title']} "
                          f"text_found_in_source_unit={in_source}",
                          "  ```", "  " + h["text"].replace("\n", "\n  "), "  ```"]
            lines.append("")
    (AUDIT / "test_top3_sheet.md").write_text("\n".join(lines), encoding="utf-8")
    print("wrote", AUDIT / "coherence_sheet.md", AUDIT / "test_top3_sheet.md")


def cmd_score() -> None:
    lab = json.loads((AUDIT / "labels.json").read_text(encoding="utf-8"))
    out = {}
    for name in STRATEGIES:
        coh = [x["score"] for x in lab["coherence"][("B" if name == "C" else name)]]
        meta = lab["metadata"][name]
        gr = [x["score"] for x in lab["grounding"][name]]
        out[name] = {
            "coherence_mean": round(sum(coh) / len(coh), 2), "coherence_n": len(coh),
            "metadata_ok": sum(x["ok"] for x in meta), "metadata_n": 3 * len(meta),  # ok = records out of top-3
            "grounding_counts": {s: gr.count(s) for s in (0, 1, 2)},
            "grounding_mean": round(sum(gr) / len(gr), 2), "grounding_n": len(gr)}
    (AUDIT / "audit_summary.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    {"sheets": cmd_sheets, "score": cmd_score}.get(sys.argv[1] if len(sys.argv) > 1 else "",
                                                     lambda: sys.exit(__doc__))()
