"""L3 retrieval eval: 20 questions against the deployed mercatoria service (task 2.4 / 8.1 / 8.2).

Uses the production `HttpRetriever` (auth included), so the eval doubles as a live check of the
client wiring. Gold is annotated at **document level** (the routing unit for 143 laws); article
level is recorded where it was verified by reading the corpus.

Metrics:
- Recall@5: fraction of gold documents present in the top-5 retrieved chunks' doc_ids
- MRR: 1 / rank of the first gold document in the retrieved order

Usage:
    SMART_EDIT_RAG=http://59.110.213.187:8080 \
    SMART_EDIT_RAG_TOKEN=<token> \
    .venv/Scripts/python.exe scripts/rag_eval_retrieval.py

Gold lives in `eval/gold_retrieval.json` (spec §L3); edit that file to add/change questions —
no code change needed. Writes `eval/retrieval_report.md` (local artifact).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.regulatory.retriever import HttpRetriever  # noqa: E402

BASE = (os.environ.get("SMART_EDIT_RAG") or "").strip()
TOKEN = (os.environ.get("SMART_EDIT_RAG_TOKEN") or "").strip() or None
TOP_K = 5
OUT = ROOT / "eval" / "retrieval_report.md"
GOLD = ROOT / "eval" / "gold_retrieval.json"


def load_questions() -> list[tuple[str, list[str], list[str]]]:
    payload = json.loads(GOLD.read_text(encoding="utf-8"))
    items = payload.get("questions") or []
    if len(items) != 20:
        raise ValueError(f"spec §L3 requires exactly 20 questions, got {len(items)}")
    return [
        (item["question"], item.get("gold_docs") or [], item.get("gold_articles") or [])
        for item in items
    ]


def main() -> int:
    if not BASE:
        print("set SMART_EDIT_RAG (and SMART_EDIT_RAG_TOKEN) first")
        return 2
    retriever = HttpRetriever(BASE, timeout=60.0, token=TOKEN)
    questions = load_questions()

    rows = []
    corpus_documents = "?"
    recall_sum = 0.0
    mrr_sum = 0.0
    for index, (question, gold_docs, gold_articles) in enumerate(questions, start=1):
        payload = retriever.retrieve([question], {}, top_k=TOP_K)
        corpus_documents = payload.get("corpus", {}).get("documents", corpus_documents)
        chunks = payload.get("chunks") or []
        retrieved_docs: list[str] = []
        for chunk in chunks:
            doc = chunk.get("doc_id") or ""
            if doc and doc not in retrieved_docs:
                retrieved_docs.append(doc)

        gold_set = set(gold_docs)
        hits = [doc for doc in retrieved_docs if doc in gold_set]
        recall = len(hits) / len(gold_docs) if gold_docs else 0.0
        first_rank = next((i + 1 for i, doc in enumerate(retrieved_docs) if doc in gold_set), None)
        rr = 1.0 / first_rank if first_rank else 0.0
        recall_sum += recall
        mrr_sum += rr

        rows.append(
            {
                "q": question,
                "gold_docs": gold_docs,
                "gold_articles": gold_articles,
                "retrieved_docs": retrieved_docs,
                "hits": hits,
                "recall5": recall,
                "first_rank": first_rank,
                "rr": rr,
                "article_labels": [f"{c.get('doc_id')}:{a}" for c in chunks for a in (c.get("articles") or [])],
            }
        )
        status = "OK  " if hits else "MISS"
        print(f"[{index:02d}] {status} R@5={recall:.2f} RR={rr:.2f} gold={','.join(gold_docs)} got={','.join(retrieved_docs)}")

    count = len(questions)
    report = [
        "# L3 检索评测（20 题 · 任务 2.4 / 8.1 / 8.2）",
        "",
        f"- 服务：`{BASE}`（检索走生产客户端 `HttpRetriever`，鉴权含在内）",
        f"- 语料：corpus.documents = {corpus_documents}",
        f"- 指标：**Recall@5 = {recall_sum / count:.3f}** ｜ **MRR = {mrr_sum / count:.3f}**（文档级 gold）",
        "",
        "| # | 问题 | gold 文档 | 检索到的文档（按序） | R@5 | 首位命中排名 |",
        "|---|---|---|---|---|---|",
    ]
    for index, row in enumerate(rows, start=1):
        report.append(
            f"| {index} | {row['q']} | {', '.join(row['gold_docs'])} "
            f"| {', '.join(row['retrieved_docs'])} | {row['recall5']:.2f} | {row['first_rank'] or '—'} |"
        )
    report += [
        "",
        "## 限制声明（任务 8.6）",
        "- gold 为文档级标注（143 部法规下以「路由到正确法规」为度量单位），条文级 gold 仅在已核实条目上记录",
        "- 未做 rerank 对照（服务端已开启 gte-rerank-v2，无法关闭对比）",
        "- gold 标注由 AI 依据语料清单与已核实条文完成，**需人工复核**",
    ]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(report), encoding="utf-8")
    (ROOT / "eval" / "retrieval_raw.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Recall@5 = {recall_sum / count:.3f}  MRR = {mrr_sum / count:.3f}  -> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
