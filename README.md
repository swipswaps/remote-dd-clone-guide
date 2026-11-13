# Pages ↔ Local Docker Bridge — Audit & Interactive Guide

Site: https://swipswaps.github.io/remote-dd-clone-guide/

Static-first GitHub Pages frontends that **probe a localhost Docker backend**
and **degrade gracefully** when it is absent. Audited from five live repos:

- `solar-nostoc-cad-bridge`
- `hardened-agent-harness-explainer`
- `ram-catalog-app`
- `receipts-ocr-rag`
- `receipts-ocr`

The page walks through the detection contract, the verbatim fallback strings
each repo emits, and the generic `docker compose up -d` upgrade path. No
OCR, CAD, or RAG code is included — only the bridge pattern.

## Helper script

`scripts/bridge-check.sh` probes a local backend and prints whether
advanced mode is available, without depending on any specific repo.

```bash
bash scripts/bridge-check.sh 8080
```
