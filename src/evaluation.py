"""Automatic Evidence Hit@1 / Hit@3. Human labels (coherence, grounding) are NOT inferred here."""
from __future__ import annotations

import re
import unicodedata
from typing import Any


def norm(s: str) -> str:
    """NFC, lowercase, collapse whitespace; used only for evidence matching."""
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", s)).strip().lower()


def is_hit(hit: dict[str, Any], gold: list[dict[str, Any]]) -> bool:
    """Hit = chunk is from a gold source+article AND contains the FULL evidence quote."""
    m = hit["metadata"]
    text = norm(hit["text"])
    return any(m["document_id"] == g["source_id"] and int(m["page"]) == int(g["page"])
               and norm(g["evidence_quote"]) in text for g in gold)


def evaluate_query(question: dict[str, Any], hits: list[dict[str, Any]]) -> dict[str, Any]:
    flags = [is_hit(h, question["gold"]) for h in hits]
    same_page = [any(h["metadata"]["document_id"] == g["source_id"]
                     and int(h["metadata"]["page"]) == int(g["page"]) for g in question["gold"])
                 for h in hits]
    filt = question.get("filter")
    filter_ok = None
    if filt:
        filter_ok = all(all(h["metadata"].get(k) == v for k, v in filt.items()) for h in hits)
    return {
        "hit_flags": flags,
        "hit@1": bool(flags[:1] and flags[0]),
        "hit@3": any(flags[:3]),
        # gold article retrieved but evidence cut across chunk borders -> counted as miss, logged
        "page_only_hit@3": any(same_page[:3]) and not any(flags[:3]),
        "filter_compliant": filter_ok,
    }


def summarize(traces: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for t in traces:
        key = f"{t['strategy']}|{t['split']}"
        s = out.setdefault(key, {"strategy": t["strategy"], "split": t["split"], "n": 0,
                                 "hit1": 0, "hit3": 0, "split_evidence": 0,
                                 "filter_q": 0, "filter_ok": 0})
        s["n"] += 1
        s["hit1"] += t["eval"]["hit@1"]
        s["hit3"] += t["eval"]["hit@3"]
        s["split_evidence"] += t["eval"]["page_only_hit@3"]
        if t["eval"]["filter_compliant"] is not None and t["filter_applied"]:
            s["filter_q"] += 1
            s["filter_ok"] += t["eval"]["filter_compliant"]
    return out
