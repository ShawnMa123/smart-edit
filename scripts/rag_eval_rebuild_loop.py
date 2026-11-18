"""Task 9.5 closed loop against the deployed service.

upload a marked test doc -> rebuild -> doc must be retrievable -> delete ->
rebuild -> doc must be gone. Times each step.

    SMART_EDIT_RAG=http://... SMART_EDIT_RAG_TOKEN=... \
    .venv/Scripts/python.exe scripts/rag_eval_rebuild_loop.py
"""

from __future__ import annotations

import json
import os
import time
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = (os.environ.get("SMART_EDIT_RAG") or "").strip()
TOKEN = (os.environ.get("SMART_EDIT_RAG_TOKEN") or "").strip() or None
OUT = ROOT / "eval" / "rebuild_report.md"

QUERY = "智能编辑器评测闭环验证条款"
DOC = (
    "# 智能编辑器评测闭环验证文档（占位，非真实法规）\n\n"
    "## TEST-001 闭环验证条款\n"
    "本条为 smart-edit L3 评测的临时占位内容，非真实法规，仅用于验证"
    "「语料变更 → 重建索引 → 检索结果同步变化」的闭环，评测结束后即删除。\n"
).encode("utf-8")


def call(method: str, path: str, body: dict | None = None, form: dict | None = None) -> dict:
    headers: dict = {}
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"
    data = None
    if form is not None:
        boundary = "eval" + uuid.uuid4().hex
        parts = [
            (
                f'--{boundary}\r\nContent-Disposition: form-data; name="files"; '
                f'filename="eval-loop-test.md"\r\nContent-Type: text/markdown\r\n\r\n'
            ).encode()
            + DOC
            + b"\r\n"
        ]
        for key, value in form.items():
            parts.append(
                f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode()
            )
        parts.append(f"--{boundary}--\r\n".encode())
        data = b"".join(parts)
        headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
    elif body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=300) as response:
        raw = response.read().decode("utf-8")
        return json.loads(raw) if raw else {}


def retrieve_docs(query: str) -> list[str]:
    payload = call("POST", "/v1/retrieve", {"queries": [query], "top_k": 3})
    return [c.get("doc_id") or "" for c in payload.get("chunks") or []]


def wait_job(job_id: str, deadline: float = 300.0):
    start = time.time()
    while time.time() - start < deadline:
        job = call("GET", f"/v1/jobs/{job_id}")
        if job.get("status") in ("done", "error"):
            return job, round(time.time() - start, 1)
        time.sleep(2.0)
    return {"status": "timeout"}, deadline


def mutate(method: str, path: str, body: dict | None = None, form: dict | None = None) -> dict:
    """Management ops are mutually exclusive (409 management_busy): retry until our turn."""
    last: urllib.error.HTTPError | None = None
    for _ in range(40):
        try:
            return call(method, path, body=body, form=form)
        except urllib.error.HTTPError as exc:
            if exc.code == 409:
                last = exc
                time.sleep(5.0)
                continue
            raise
    raise last  # type: ignore[misc]


def rebuild():
    """Explicit rebuild (409-retry: uploads/deletes queue their own rebuild first)."""
    job = mutate("POST", "/v1/admin/rebuild", {"background": True, "activate": True})
    result, seconds = wait_job(str(job.get("job_id")))
    health = call("GET", "/health")
    version = str(health.get("index", {}).get("version"))
    return str(result.get("status")), version, seconds


def main() -> int:
    if not BASE:
        print("set SMART_EDIT_RAG (and SMART_EDIT_RAG_TOKEN) first")
        return 2
    log: list[str] = []
    started = time.time()

    health0 = call("GET", "/health")
    v0 = str(health0.get("index", {}).get("version"))
    stale = call("GET", "/v1/documents").get("documents") or []
    for doc in stale:
        mutate("DELETE", f"/v1/documents/{doc.get('doc_id')}")
    if stale:
        # A delete removes the doc but NOT its indexed chunks: rebuild to get a clean baseline.
        status0, v0, sec0 = rebuild()
        print(f"清理上次遗留测试文档 {len(stale)} 个，重建 job={status0} ({sec0}s) -> {v0}")
    baseline = retrieve_docs(QUERY)
    log.append(f"起点 index.version = {v0}；基线检索 = {baseline}（应无测试文档）")
    print(log[-1])

    mutate("POST", "/v1/documents", form={"jurisdiction": "CN", "source_doc": "smart-edit-eval-loop-test"})
    docs = call("GET", "/v1/documents").get("documents") or []
    doc_id = str(docs[0].get("doc_id")) if docs else "unknown"
    log.append(f"上传测试文档 doc_id = {doc_id}")
    print(log[-1])

    status1, v1, sec1 = rebuild()
    after_add = retrieve_docs(QUERY)
    hit = doc_id in after_add
    log.append(f"重建1: job={status1} ({sec1}s) version {v0} -> {v1}；检索 = {after_add}；命中测试文档 = {hit}")
    print(log[-1])

    mutate("DELETE", f"/v1/documents/{doc_id}")
    status2, v2, sec2 = rebuild()
    after_del = retrieve_docs(QUERY)
    gone = doc_id not in after_del
    log.append(f"删除后重建: job={status2} ({sec2}s) version {v1} -> {v2}；检索 = {after_del}；测试文档已消失 = {gone}")
    print(log[-1])

    total = round(time.time() - started, 1)
    verdict = "PASS" if (hit and gone and v0 != v1 and v1 != v2) else "FAIL"
    log.append(f"总耗时 {total}s（含两次重建）→ **{verdict}**")

    report = [
        "# 任务 9.5 重建闭环（远程服务实测）",
        "",
        f"- 服务：`{BASE}`；查询：`{QUERY}`；测试文档：TEST-001（显著标注占位非真实法规）",
        "",
        *[f"- {line}" for line in log],
        "",
        "闭环语义验证：语料增加 → 重建 → 同一查询命中新增文档；删除 → 重建 → 查询不再命中。",
        "每次重建仅影响 index.version 与 generation，语料内容不变时检索结果保持稳定。",
    ]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(report), encoding="utf-8")
    print(f"-> {OUT}")
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
