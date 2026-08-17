# Page-by-page paper review

Upload a PDF, get back a per-page summary and a list of findings — errors, warnings and
suggestions — rendered side by side with the page itself. Runs locally; the only thing that
leaves your machine is the page image and text you send to the model provider you configure.

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate     # optional
pip install -r requirements.txt
cp .env.example .env                                   # then add your key
uvicorn app.main:app --port 8000
```

Open <http://localhost:8000>. No poppler, no system packages — page rendering uses
`pypdfium2`, which ships its own PDFium binary.

Want to see the interface before spending anything? Set `PROVIDER=mock` in `.env`, which
runs the whole pipeline with canned findings and no network calls.

## Configuring the model

One `.env` variable picks the transport. Both paths need a **vision-capable** model,
because each page is sent as an image.

### Anthropic

```env
PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-...
MODEL=claude-sonnet-4-6
```

### Anything OpenAI-compatible

Works with OpenAI, OpenRouter, Together, Groq, vLLM, LM Studio, Ollama — anything serving
`POST /chat/completions`.

```env
PROVIDER=openai
OPENAI_API_KEY=sk-...
OPENAI_BASE_URL=https://api.openai.com/v1
MODEL=gpt-4.1
```

```env
# a local vision model, no key needed
PROVIDER=openai
OPENAI_BASE_URL=http://localhost:1234/v1
MODEL=qwen2.5-vl-7b-instruct
OPENAI_JSON_MODE=false        # some local servers reject response_format
```

Other settings — `CONCURRENCY`, `MAX_PAGES`, `MAX_OUTPUT_TOKENS`, `REQUEST_TIMEOUT`,
`CROSS_PAGE_PASS`, `DOC_TTL_MINUTES` — are documented inline in `.env.example`.

## How it works

1. **Upload.** The PDF is rendered page by page to ~1000 px JPEGs and held in memory,
   keyed by a document id that expires after `DOC_TTL_MINUTES`. Nothing is written to disk.
2. **Per-page review.** Each page goes to the model as an image *plus* its extracted text
   layer, if the PDF has one. Sending both matters: the image carries tables, figures and
   layout, while the text lets the model quote exact numbers instead of reading them off a
   raster. Pages with no text layer are handled from the image alone.
3. **Streaming.** Pages are analysed `CONCURRENCY` at a time and streamed back over
   Server-Sent Events, so the index fills in as results land rather than after the last
   page. Each page also carries a short context excerpt from page 1 for orientation.
4. **Cross-page pass.** When every page is done, the summaries and findings go back to the
   model in one text-only request that looks for contradictions no single page could reveal
   — the same quantity given two values in different sections, an abstract claim the results
   do not support. Findings link to the pages involved. Turn it off with
   `CROSS_PAGE_PASS=false`.
5. **Export.** `Report .md` and `.json` download the whole review.

Findings come back at four severities. `error` is demonstrably wrong — bad arithmetic, a
contradicted number, a broken cross-reference. `warning` is probably a problem. `note` is an
improvement. `ok` records a non-trivial check that held, so you can see what was verified
rather than only what failed. The strip under the header colours every page by its worst
finding, which is the fastest way to see where the trouble is.

## Interface

| | |
|---|---|
| `←` `→` or `j` `k` | previous / next page, within the current filter |
| `F` | cycle All → Errors → Warnings → Minor |
| `Z` | Fit → 100% → 150% |
| `Esc` | leave the cross-page panel |
| Click the page | cycle zoom |
| Re-read page | re-run one page, e.g. after a timeout |

## Cost and accuracy notes

- One request per page plus one for the cross-page pass. A 27-page paper is 28 requests;
  input dominates, at roughly 1.5–2k tokens per page (image plus text layer).
- Lower `CONCURRENCY` if your provider rate-limits you. Raise it if you are running locally.
- The model is a reader, not an oracle. It is good at catching arithmetic that does not
  reproduce, numbers that disagree between prose and a table, and broken references; it will
  occasionally invent a problem or miss one. Treat the output as a reviewer's first pass, and
  check anything you plan to act on.
- Findings only cover what is on the page, plus what the cross-page pass sees in the
  summaries. A claim on page 3 refuted by a table on page 17 is exactly what the cross-page
  pass is for, but it works from summaries, so it is weaker than a full-text comparison.

## Troubleshooting

**"Not configured yet"** — no key found. Check `.env` sits next to `requirements.txt` and
that you restarted the server; `.env` is read once at startup.

**Every page fails with HTTP 400** — usually the model is not vision-capable, or the name is
wrong for that endpoint. OpenRouter, for instance, wants `anthropic/claude-sonnet-4.6`,
not `claude-sonnet-4-6`.

**"Model did not return usable JSON"** — a small local model ignoring the format
instruction. Try `OPENAI_JSON_MODE=true`, a larger model, or raise `MAX_OUTPUT_TOKENS` if the
JSON is being cut off mid-object.

**Timeouts on dense pages** — raise `REQUEST_TIMEOUT`, then use *Re-read page* on the ones
that failed. Failures are per page; the rest of the run is unaffected.

**Slow first upload of a big PDF** — rendering is synchronous per document and runs in a
worker thread. A 60-page paper takes a few seconds.

## Layout

```
app/
  main.py       FastAPI: upload, SSE analysis, retry, .md/.json export
  pdf.py        page rasterisation + text extraction (pypdfium2)
  llm.py        Anthropic / OpenAI-compatible / mock providers, retries, JSON recovery
  prompts.py    the reviewer prompt and the cross-page prompt
  static/       index.html, styles.css, app.js
.env.example    every setting, documented
```

To change what the reviewer looks for, edit `PAGE_SYSTEM` in `app/prompts.py` — that prompt
is the whole behaviour of the tool. Narrow it to your field, add house-style rules, or ask
for a different severity scheme (adjust the mapping in `normalise()` in `main.py` if you do).
