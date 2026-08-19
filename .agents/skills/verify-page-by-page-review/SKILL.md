---
name: verify-page-by-page-review
description: Verify the Page-by-page paper review FastAPI web app through its real browser UI using an isolated local mock-provider server. Use when changing or checking PDF upload, streamed page reviews, navigation, filters, zoom, cross-page findings, report downloads, retry behavior, or reset cleanup.
---

# Verify Page-by-page paper review

Work from the repository root. Drive the browser UI against a verifier-owned server and generated PDF; never reuse the app already listening on port 8000, the repository `.env` provider, a personal paper, or a production model endpoint.

## Launch

Use the existing `.venv` and the owned controller. Start the launch command in a dedicated Codex terminal/exec session with PTY enabled, retain its session ID, and let it keep running after it prints readiness:

```sh
RUN_ID="$(date +%Y%m%d-%H%M%S)-$$"
VERIFY_RUN_DIR="/tmp/page-by-page-review-verify-${RUN_ID}"
VERIFY_PORT=18765  # choose another unprivileged port if this one is occupied
CONTROL="./.agents/skills/verify-page-by-page-review/scripts/control-page-review"
"$CONTROL" launch --run-dir "$VERIFY_RUN_DIR" --port "$VERIFY_PORT"
```

`launch` refuses an existing run directory or listening port. It starts `app.main:app` on `127.0.0.1` with `PROVIDER=mock`, `MODEL=mock`, and `CROSS_PAGE_PASS=true`, records the exact PID and port, creates `scratch/verification-paper.pdf`, and waits for `/api/config`. Readiness is the `launch ok` line. The command then waits on its owned server; do not wait for command completion before driving the app.

Do not source or edit `.env`; the launch environment overrides it without revealing or using configured credentials. Do not install dependencies when `.venv` is present. If `.venv` is missing or incomplete, report the prerequisite instead of changing the environment unless the user authorized setup.

## Doctor

Run Doctor before the first drive and after any surprising browser or server behavior:

```sh
"$CONTROL" doctor --run-dir "$VERIFY_RUN_DIR" --port "$VERIFY_PORT"
```

Doctor is read-only. It requires the recorded PID to be alive, owned by this repository's Uvicorn command, listening on the recorded port from the repository root, and serving config with `provider=mock`, `model=mock`, `ready=true`, and the cross-page pass enabled. Never drive after Doctor fails.

## Drive

Use the `browser:control-in-app-browser` skill and its supported Browser API. Read that skill before browser work. Open `http://127.0.0.1:$VERIFY_PORT/` in a verifier-owned tab and inspect a fresh DOM snapshot before each new interaction family.

Stable handles from this app:

- Upload action: visible text `Drop a PDF here, or click to choose`; it is inside the label for the hidden `input[type="file"]`.
- Main actions: buttons `All`, `Errors`, `Warnings`, `Minor`, `Across pages …`, `Report .md`, `.json`, and `New PDF`.
- Page controls: buttons `← Prev`, `Next →`, `Fit`, `100%`, and `150%`; page rows are buttons under navigation `Page index`.
- Review result: text `Mock review of page <n>` and image alt `Page <n> of verification-paper.pdf`.
- Retry: button `Re-read page`; cross retry appears as `Try again` only after a cross-page failure.

Upload through the real chooser flow. Click the visible upload action rather than the hidden file input, and register the chooser wait and click together so the event wait is observed even if either operation fails:

```js
var [chooser] = await Promise.all([
  tab.playwright.waitForEvent("filechooser", { timeoutMs: 10000 }),
  tab.playwright.getByText("Drop a PDF here, or click to choose", { exact: true }).click(),
]);
await chooser.setFiles([VERIFY_RUN_DIR + "/scratch/verification-paper.pdf"]);
```

The hidden input remains useful for presence checks such as `locator('input[type="file"]').count()`, but do not click it for the chooser path in the in-app Browser.

Wait on visible state, not fixed sleeps: `Mock review of page 1`, enabled report buttons, and the visible `Across pages` button prove the stream completed. Use the matching file under `features/` for exact actions and assertions.

If Browser security policy blocks navigation to the verifier-owned local URL, stop browser work and report the requested UI proof as blocked. Do not switch browser surfaces or use API evidence to claim that the browser path passed; API checks may diagnose the app, but the skill remains browser-unproven.

## Evidence

Keep proof under `$VERIFY_RUN_DIR/evidence/`; cleanup preserves this directory. For a UI proof capture:

- `before-upload.png` showing the app identity, mock provider, and upload action;
- `after-<feature>.png` showing the resulting user-visible state;
- `after-<feature>.dom.txt` from `tab.playwright.domSnapshot()`;
- `results.json` and, when relevant, `report.md` fetched from the same document ID after the UI action;
- `proof-summary.txt` naming the feature ID, entry point, actions, observed result, run directory, port, and repository revision;
- `config.json` and `server.log`, created by launch.

Save Browser output from the Node-backed browser session with `node:fs/promises`, for example:

```js
var fs = await import("node:fs/promises");
await fs.writeFile(VERIFY_RUN_DIR + "/evidence/after-upload-review.png", await tab.screenshot({ fullPage: true }));
await fs.writeFile(VERIFY_RUN_DIR + "/evidence/after-upload-review.dom.txt", await tab.playwright.domSnapshot());
```

The page image `src` contains `/api/documents/<id>/pages/...`; extract that ID after upload and use `curl` against this verifier-owned port for the independent JSON/Markdown check. Do not substitute API setup for the browser action.

## Cleanup

When a document is loaded, first choose `New PDF` and require the upload gate to reappear; this exercises the user's forget/reset path. Then close the verifier-created tab and run:

```sh
"$CONTROL" cleanup --run-dir "$VERIFY_RUN_DIR" --port "$VERIFY_PORT"
test -d "$VERIFY_RUN_DIR/evidence"
test ! -d "$VERIFY_RUN_DIR/scratch"
```

Cleanup validates the recorded process before sending it `TERM`, removes only the verifier-owned PID/port files and scratch directory, and preserves all evidence. It never kills by process name or touches port 8000. Run it after success and every failed iteration.

## Helpers

- `scripts/control-page-review launch|doctor|cleanup` owns the isolated server lifecycle and fixture path. Run `launch` in a persistent PTY session; invoke Doctor and cleanup from separate shell calls exactly as shown above.
- `scripts/make-fixture-pdf.py OUTPUT.pdf` creates the two-page image-only PDF used by launch. The scanned-page shape is intentional because the product documents support for PDFs without a text layer.
