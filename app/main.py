"""Page-by-page paper review — local FastAPI app.

Run:  uvicorn app.main:app --reload --port 8000
"""
from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request, UploadFile, File
from fastapi.responses import (
    FileResponse,
    JSONResponse,
    PlainTextResponse,
    Response,
    StreamingResponse,
)
from fastapi.staticfiles import StaticFiles

load_dotenv()  # before the provider layer reads the environment

from .llm import LLMError, Usage, build_provider  # noqa: E402
from .pdf import render_pdf  # noqa: E402
from .prompts import (  # noqa: E402
    CROSS_SYSTEM,
    PAGE_SYSTEM,
    cross_user_content,
    page_user_content,
)

STATIC = Path(__file__).parent / "static"

MAX_PAGES = int(os.getenv("MAX_PAGES", "60"))
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "40"))
CONCURRENCY = max(1, int(os.getenv("CONCURRENCY", "3")))
CROSS_PAGE = (os.getenv("CROSS_PAGE_PASS", "true").lower() in {"1", "true", "yes", "on"})
DOC_TTL_MIN = int(os.getenv("DOC_TTL_MINUTES", "180"))

SEVERITIES = ("error", "warning", "note", "ok")
RANK = {"error": 0, "warning": 1, "note": 2, "ok": 3}


# --------------------------------------------------------------------------- store


@dataclass
class Page:
    number: int
    jpeg: bytes
    text: str
    width: int
    height: int
    result: dict | None = None
    error: str | None = None
    usage: Usage = field(default_factory=Usage)


@dataclass
class Doc:
    id: str
    name: str
    pages: list[Page]
    truncated_at: int | None = None
    created: float = field(default_factory=time.time)
    cross: list[dict] = field(default_factory=list)
    cross_error: str | None = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    @property
    def context(self) -> str:
        return self.pages[0].text[:2500] if self.pages else ""


DOCS: dict[str, Doc] = {}


def get_doc(doc_id: str) -> Doc:
    sweep()
    doc = DOCS.get(doc_id)
    if not doc:
        raise HTTPException(404, "Document not found — it may have expired. Upload it again.")
    return doc


def sweep() -> None:
    cutoff = time.time() - DOC_TTL_MIN * 60
    for key in [k for k, d in DOCS.items() if d.created < cutoff]:
        DOCS.pop(key, None)


# ----------------------------------------------------------------------------- app

app = FastAPI(title="Page-by-page paper review")
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/api/config")
async def config() -> JSONResponse:
    provider = os.getenv("PROVIDER", "anthropic").lower()
    model = os.getenv("MODEL", "")
    ready, problem = True, None
    try:
        p = build_provider()
        model = p.model or model
    except LLMError as exc:
        ready, problem = False, str(exc)
    return JSONResponse(
        {
            "provider": provider,
            "model": model or "(provider default)",
            "ready": ready,
            "problem": problem,
            "max_pages": MAX_PAGES,
            "max_upload_mb": MAX_UPLOAD_MB,
            "concurrency": CONCURRENCY,
            "cross_page": CROSS_PAGE,
        }
    )


@app.post("/api/documents")
async def upload(file: UploadFile = File(...)) -> JSONResponse:
    data = await file.read()
    if not data:
        raise HTTPException(400, "Empty upload.")
    if len(data) > MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(413, f"File is larger than MAX_UPLOAD_MB ({MAX_UPLOAD_MB} MB).")
    if not data.startswith(b"%PDF"):
        raise HTTPException(400, "That does not look like a PDF.")

    try:
        rendered = await asyncio.to_thread(render_pdf, data, MAX_PAGES)
    except Exception as exc:  # corrupt or encrypted
        raise HTTPException(400, f"Could not read the PDF: {exc}") from exc
    if not rendered.pages:
        raise HTTPException(400, "The PDF has no pages.")

    doc = Doc(
        id=uuid.uuid4().hex[:12],
        name=Path(file.filename or "document.pdf").name,
        pages=[Page(p.number, p.jpeg, p.text, p.width, p.height) for p in rendered.pages],
        truncated_at=rendered.truncated_at,
    )
    sweep()
    DOCS[doc.id] = doc
    return JSONResponse(
        {
            "id": doc.id,
            "name": doc.name,
            "page_count": len(doc.pages),
            "truncated_at": doc.truncated_at,
            "has_text_layer": any(p.text for p in doc.pages),
            "pages": [
                {"number": p.number, "width": p.width, "height": p.height} for p in doc.pages
            ],
        }
    )


@app.get("/api/documents/{doc_id}/pages/{number}/image")
async def page_image(doc_id: str, number: int) -> Response:
    doc = get_doc(doc_id)
    if not 1 <= number <= len(doc.pages):
        raise HTTPException(404, "No such page.")
    return Response(
        doc.pages[number - 1].jpeg,
        media_type="image/jpeg",
        headers={"Cache-Control": "private, max-age=3600"},
    )


@app.delete("/api/documents/{doc_id}")
async def forget(doc_id: str) -> JSONResponse:
    DOCS.pop(doc_id, None)
    return JSONResponse({"ok": True})


# ------------------------------------------------------------------------ analysis


def normalise(raw: dict, page: Page) -> dict:
    findings = []
    for item in raw.get("findings") or []:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        sev = str(item.get("severity") or "note").lower().strip()
        if sev in {"critical", "major", "wrong", "incorrect"}:
            sev = "error"
        elif sev in {"minor", "suggestion", "improve", "improvement", "info"}:
            sev = "note"
        elif sev in {"verified", "check", "checked", "good"}:
            sev = "ok"
        if sev not in SEVERITIES:
            sev = "note"
        findings.append({"severity": sev, "text": text})

    findings.sort(key=lambda f: RANK[f["severity"]])
    actionable = [f for f in findings if f["severity"] != "ok"]
    severity = actionable[0]["severity"] if actionable else "clean"

    return {
        "number": page.number,
        "gist": (str(raw.get("gist") or "").strip() or f"Page {page.number}")[:120],
        "section": (str(raw.get("section") or "").strip() or f"page {page.number}")[:60],
        "summary": str(raw.get("summary") or "").strip(),
        "findings": findings,
        "severity": severity,
        "counts": {s: sum(1 for f in findings if f["severity"] == s) for s in SEVERITIES},
        "usage": {"input": page.usage.input_tokens, "output": page.usage.output_tokens},
    }


async def analyse_page(provider, doc: Doc, page: Page) -> dict:
    reply = await provider.complete_json(
        PAGE_SYSTEM,
        page_user_content(page.number, len(doc.pages), page.text, doc.context),
        page.jpeg,
    )
    page.usage = reply.usage
    page.error = None
    page.result = normalise(reply.data, page)
    return page.result


def digest(doc: Doc) -> str:
    lines = []
    for p in doc.pages:
        if not p.result:
            continue
        lines.append(f"Page {p.number} — {p.result['gist']} ({p.result['section']})")
        lines.append(p.result["summary"])
        for f in p.result["findings"]:
            lines.append(f"  [{f['severity']}] {f['text']}")
        lines.append("")
    return "\n".join(lines)[:60000]


async def analyse_cross(provider, doc: Doc) -> list[dict]:
    reply = await provider.complete_json(CROSS_SYSTEM, cross_user_content(digest(doc)))
    out = []
    for item in reply.data.get("findings") or []:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        sev = str(item.get("severity") or "warning").lower()
        if sev not in {"error", "warning", "note"}:
            sev = "warning"
        pages = [int(n) for n in (item.get("pages") or []) if str(n).isdigit()]
        out.append({"severity": sev, "pages": pages, "text": text})
    out.sort(key=lambda f: RANK[f["severity"]])
    doc.cross = out
    doc.cross_error = None
    return out


def sse(event: str, payload: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


@app.get("/api/documents/{doc_id}/analyze")
async def analyze(doc_id: str, request: Request, force: bool = False) -> StreamingResponse:
    """Stream one result per page as it lands, then the cross-page pass."""
    doc = get_doc(doc_id)

    async def stream():
        try:
            provider = build_provider()
        except LLMError as exc:
            yield sse("fatal", {"message": str(exc)})
            return

        todo = [p for p in doc.pages if force or p.result is None]
        yield sse(
            "start",
            {
                "provider": provider.name,
                "model": provider.model,
                "total": len(doc.pages),
                "pending": len(todo),
            },
        )

        # already-analysed pages are replayed so a reconnect rebuilds the view
        for page in doc.pages:
            if page.result and page not in todo:
                yield sse("page", page.result)

        queue: asyncio.Queue = asyncio.Queue()
        gate = asyncio.Semaphore(CONCURRENCY)

        async def worker(page: Page):
            async with gate:
                if await request.is_disconnected():
                    return
                try:
                    await queue.put(("page", await analyse_page(provider, doc, page)))
                except LLMError as exc:
                    page.error = str(exc)
                    await queue.put(("failed", {"number": page.number, "message": str(exc)}))
                except Exception as exc:  # noqa: BLE001
                    page.error = repr(exc)
                    await queue.put(("failed", {"number": page.number, "message": repr(exc)}))

        async with doc.lock:  # one analysis run per document at a time
            tasks = [asyncio.create_task(worker(p)) for p in todo]
            done_count = 0
            try:
                while done_count < len(tasks):
                    try:
                        kind, payload = await asyncio.wait_for(queue.get(), timeout=1.0)
                    except asyncio.TimeoutError:
                        if await request.is_disconnected():
                            break
                        yield ": keep-alive\n\n"
                        continue
                    done_count += 1
                    yield sse(kind, payload)

                if CROSS_PAGE and any(p.result for p in doc.pages):
                    yield sse("cross_start", {})
                    try:
                        yield sse("cross", {"findings": await analyse_cross(provider, doc)})
                    except LLMError as exc:
                        doc.cross_error = str(exc)
                        yield sse("cross_failed", {"message": str(exc)})

                totals = Usage()
                for p in doc.pages:
                    totals = totals + p.usage
                yield sse(
                    "done",
                    {
                        "analysed": sum(1 for p in doc.pages if p.result),
                        "failed": sum(1 for p in doc.pages if p.error),
                        "usage": {
                            "input": totals.input_tokens,
                            "output": totals.output_tokens,
                        },
                    },
                )
            finally:
                for t in tasks:
                    t.cancel()
                await provider.close()

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/documents/{doc_id}/pages/{number}/analyze")
async def analyze_one(doc_id: str, number: int) -> JSONResponse:
    doc = get_doc(doc_id)
    if not 1 <= number <= len(doc.pages):
        raise HTTPException(404, "No such page.")
    try:
        provider = build_provider()
    except LLMError as exc:
        raise HTTPException(400, str(exc)) from exc
    page = doc.pages[number - 1]
    try:
        return JSONResponse(await analyse_page(provider, doc, page))
    except LLMError as exc:
        page.error = str(exc)
        raise HTTPException(502, str(exc)) from exc
    finally:
        await provider.close()


@app.post("/api/documents/{doc_id}/cross")
async def analyze_cross(doc_id: str) -> JSONResponse:
    """Re-run only the cross-page pass (e.g. after it failed on unusable JSON)."""
    doc = get_doc(doc_id)
    if not any(p.result for p in doc.pages):
        raise HTTPException(400, "No analysed pages to cross-check yet.")
    try:
        provider = build_provider()
    except LLMError as exc:
        raise HTTPException(400, str(exc)) from exc
    try:
        async with doc.lock:  # don't race a running full analysis
            return JSONResponse({"findings": await analyse_cross(provider, doc)})
    except LLMError as exc:
        doc.cross_error = str(exc)
        raise HTTPException(502, str(exc)) from exc
    finally:
        await provider.close()


# -------------------------------------------------------------------------- export


@app.get("/api/documents/{doc_id}/results.json")
async def results_json(doc_id: str) -> Response:
    doc = get_doc(doc_id)
    payload = {
        "document": doc.name,
        "page_count": len(doc.pages),
        "provider": os.getenv("PROVIDER", "anthropic"),
        "model": os.getenv("MODEL", ""),
        "pages": [p.result or {"number": p.number, "error": p.error} for p in doc.pages],
        "cross_page": doc.cross,
    }
    return Response(
        json.dumps(payload, ensure_ascii=False, indent=2),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{Path(doc.name).stem}-review.json"'},
    )


@app.get("/api/documents/{doc_id}/report.md")
async def report_md(doc_id: str) -> PlainTextResponse:
    doc = get_doc(doc_id)
    lines = [f"# Page-by-page review — {doc.name}", ""]
    if doc.cross:
        lines += ["## Across pages", ""]
        for f in doc.cross:
            where = f" (pages {', '.join(str(n) for n in f['pages'])})" if f["pages"] else ""
            lines.append(f"- **{f['severity']}{where}:** {f['text']}")
        lines.append("")
    for p in doc.pages:
        if not p.result:
            lines += [f"## Page {p.number} — not analysed", p.error or "", ""]
            continue
        r = p.result
        lines += [f"## Page {p.number} — {r['gist']}  ({r['section']})", r["summary"], ""]
        for f in r["findings"]:
            lines.append(f"- **{f['severity']}:** {f['text']}")
        lines.append("")
    return PlainTextResponse(
        "\n".join(lines),
        headers={"Content-Disposition": f'attachment; filename="{Path(doc.name).stem}-review.md"'},
    )
