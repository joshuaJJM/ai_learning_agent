# AGENTS.md — 好学 Hackathon Engineering Rules

This file is the operating contract for Codex / AI coding agents working in this repository.

## 1. Project Mission

Build a reliable 48H hackathon demo for **好学**, a Personal Learning Agent.

The product must prove one complete loop:

```text
scan → understand → diagnose → learn → practice → update mastery
```

**Demo reliability > technical ambition.**

Do not expand scope without explicit human approval.

---

## 2. Repository

Canonical repository:

```text
https://github.com/joshuaJJM/ai_learning_agent
```

If working in an existing clone:

- preserve the existing `.git` history;
- do NOT reinitialize Git;
- verify the remote before pushing.

If and only if `.git` does not exist:

```bash
git init
git remote add origin https://github.com/joshuaJJM/ai_learning_agent.git
```

Never force-push unless explicitly instructed by a human.

---

## 3. Phase Discipline

Read `DEVELOPMENT_PLAN.md` and `PHASES.md` before coding.

Every Phase MUST end with a Git commit.

Recommended commit messages:

```text
phase-0: bootstrap project and freeze contracts
phase-1: build ios shell and mock learning flow
phase-2: implement scan and image preparation flow
phase-3: implement tutor practice and scratchpad
phase-4: implement backend learning agent pipeline
phase-5: complete product states and harden demo fallback
phase-6: integrate ios with live backend
phase-7: polish final ui and motion
```

Do not collapse multiple completed phases into one giant commit.

Before each phase commit:

1. build / run relevant tests;
2. fix compile errors;
3. verify the phase's Definition of Done;
4. inspect `git diff`;
5. ensure no secret was added.

---

## 4. Frontend / Backend Boundary

Backend is the Source of Truth for learning data.

The iOS app MUST NOT independently invent or calculate authoritative mastery values.

Frontend responsibilities:

- SwiftUI UI / navigation;
- scan / perspective correction;
- multi-image preview and “上传更多”;
- PencilKit scratchpad;
- presentation state;
- networking / DTO mapping;
- local demo fallback.

Backend responsibilities:

- image understanding;
- question recognition;
- correctness evaluation;
- knowledge mapping;
- diagnosis;
- Evidence;
- Knowledge State;
- Wrong Questions;
- Tutor / Practice decision logic;
- persistent data.

Do not couple SwiftUI Views directly to a concrete LLM provider.

---

## 5. API Contract

Read `API_CONTRACT.md` before implementing networking.

Important rule:

> Backend owns final JSON schemas. iOS owns a stable adapter layer.

Use:

```text
JSON DTO
  ↓
Mapper
  ↓
Domain Model
  ↓
ViewModel
  ↓
View
```

Do not scatter raw JSON dictionary access throughout the UI.

---

## 6. Tutor Rules

Hackathon Tutor UI supports:

- A / B / C / D structured choices;
- a visual “写下你的想法……” input field.

Current v1 behavior:

- A-D are submitted to backend;
- free-text input is UI-only and does not need to be uploaded;
- do not spend time building a full chat product.

The Tutor should feel adaptive because the student's answer changes the next turn.

---

## 7. Scan Rules

The iOS app may preprocess images only for document-style cleanup:

- page detection;
- perspective correction;
- crop / straighten;
- compression.

Do NOT implement heavy OCR / question understanding on device for the Hackathon version.

Users may add more images after the first scan. The UI action is **“上传更多”**, not “重新扫描”.

---

## 8. Secrets & Security

NEVER commit:

- API keys;
- model keys;
- database passwords;
- auth tokens;
- private coordination URLs containing tokens;
- `.env` files containing secrets.

Use environment variables.

For the hackathon AI-to-AI coordination endpoint, read it from:

```text
HACKATHON_COORDINATION_URL
```

The actual URL is intentionally stored only in the local ignored file `LOCAL_COORDINATION.md` / local environment, not in Git history.

---

## 9. AI-to-AI Coordination

Frontend and backend agents may coordinate through the hackathon coordination service when useful.

Rules:

- keep messages concise and machine-readable when possible;
- share API changes immediately;
- include version / timestamp / affected endpoint;
- never send secrets beyond what the coordination service already requires;
- do not use coordination as a replacement for updating `API_CONTRACT.md` when the contract becomes stable.

---

## 10. Scope Guardrails

Do NOT add during the 48H build unless explicitly approved:

- complex multi-agent systems;
- autonomous infinite loops;
- broad multi-subject support;
- teacher dashboard;
- parent dashboard;
- full production billing;
- handwriting semantic recognition;
- elaborate analytics platform;
- unnecessary infrastructure.

If something does not directly improve the demo loop, defer it.

---

## 11. Final Two Phases Are Reserved

The final two phases have fixed purposes:

### Phase 6

Frontend / Backend Integration.

### Phase 7

Final UI Polish & Motion.

Do not consume Phase 7 time early by polishing unfinished flows.

---

## 12. When Unsure

Prefer:

```text
working simple implementation
>
clever incomplete implementation
```

If a decision may change architecture, API contract, or demo scope, ask the human team before proceeding.
