# Frontend Integration (Lightweight UI)

This doc describes how to put a thin frontend on top of the current Python engine.

## 1) Current State

- No bundled frontend exists in this repository.
- Engine APIs are Python-first and can already be wrapped by a service layer.

## 2) Recommended Integration Pattern

```text
UI (web desktop)
  -> API layer (FastAPI/Flask)
  -> orchestration wrapper (your app code)
  -> existing engine functions in bma_standard_formulas
```

## 3) Suggested API Endpoints

Minimal endpoint set:

- `POST /runs`
  - submit run with paths + assumptions payload
- `GET /runs/{id}`
  - status and error details
- `GET /runs/{id}/outputs`
  - list output files/tables
- `GET /runs/{id}/preview`
  - small DataFrame-derived JSON preview

## 4) Job Model

Because large portfolios can be slow:

- run jobs asynchronously
- store progress/status outside request cycle
- persist manifest and logs per run id

## 5) UX Guidance for Novice Users

Prioritize:

- clear units labels (percent vs decimal)
- clear indexing labels (age-indexed vs period-indexed)
- preflight validation before execution
- explicit examples on curve length requirements

## 6) Safety and Guardrails

Expose safe defaults:

- default scenario templates
- bounded upload size
- controlled filesystem access to configured input roots

## 7) What Should Stay Out of UI Logic

- formula implementation
- portfolio aggregation logic
- persistence schema decoding

The UI should orchestrate existing APIs, not duplicate engine logic.
