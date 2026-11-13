# How we got here

This document explains the pattern that motivates this repo. It is not part of
the user-facing guide — the page at the repo root is the working dd clone tool.

## The bridge pattern

Five sibling repos use the same architecture: a static GitHub Pages frontend
that probes a localhost Docker backend and degrades gracefully when the backend
is absent. The contract is:

1. The page loads with zero backend and prints a verbatim reason why advanced
   features are unavailable.
2. Running `docker compose up -d` locally causes the page to unlock those
   features on the next reload.
3. The fallback string names the exact command the user should run.

## Audit of the five repos

| Repo | Pages frontend | Local backend | Verbatim fallback |
|---|---|---|---|
| solar-nostoc-cad-bridge | static index.html + src/, Dockerfile.frontend/.backend + compose | CFD bridge on localhost | (backend optional; no banner captured) |
| hardened-agent-harness-explainer | public/ + server/; compose referenced on page | Express server on localhost | `static mode — limited (no localhost backend — run: docker compose up -d)` |
| ram-catalog-app | public/ + backend/; host port moved to 8080 | Backend on localhost:8080 | (unlocks GLB / WebGL; no fallback captured) |
| receipts-ocr-rag | frontend/ + backend/; page shows Backend Offline | RAG backend on localhost | `Backend Offline · Entries: 0 · Code Blocks: 0 · Errors: 0` |
| receipts-ocr | root index.html; explicit Docker probe | PaddleOCR on localhost | `Checking Docker connection...` -> `Docker backend unavailable, using Tesseract.js fallback` |

## Why it matters here

The bridge pattern is how a static site can offer an optional privileged
operation without asking the user to install anything until they choose to. This
repo applies it to a dd clone tool: manual mode is fully usable; Docker mode
adds a job queue, advanced options, and a UI.

## Detection contract

The page probes GET http://127.0.0.1:8080/health. The backend returns:

    {"status": "ok", "version": "1.0.0", "features": ["compression", "bandwidth", "verify", "resume", "remote_dst"]}

If the probe fails or times out (2.5 s via AbortController), the page shows the
fallback and hides the panel. On success, the panel is revealed, and the
features array controls which advanced options the UI offers.

## The generic upgrade path

Any sibling repo can adopt this by:

1. Adding a docker-compose.yml bound to 127.0.0.1:8080 and a Dockerfile.backend.
2. Adding a GET /health endpoint returning {status, version, features}.
3. Adding a small probe to the page that respects AbortController and prints a
   verbatim fallback.
4. Gating every mutating endpoint behind Authorization: Bearer $BACKEND_TOKEN and
   an explicit confirm parameter.
