# Logistria project rules (Cline reads this automatically)

- The source of truth is BUILD_BRIEF.md. Read it fully at the start of every task.
- Work on ONE phase at a time. When a phase's acceptance checks pass, STOP and report. Do not start the next phase.
- Backend: Python 3.11+, FastAPI, LangGraph, SQLAlchemy + SQLite (Postgres-ready via DATABASE_URL), LiteLLM for all LLM calls.
- Frontend: React + Vite + TypeScript + Tailwind, Leaflet for maps.
- Never hardcode secrets. Read them from .env (provide .env.example). Never print or commit keys.
- Numbers that decide money (supplier score, confidence, auto-approve vs review) are computed in plain Python, never by the LLM. The LLM only explains and narrates.
- Default LLM provider is Groq via LiteLLM (switchable by .env only). Every LLM call must have a timeout, one retry, and a rule-based/template fallback so the pipeline never crashes if the model/API fails or is rate limited (429).
- Every agent action emits an event to the message bus (see brief). No agent talks to another agent except through the bus.
- Write pytest tests for scoring, confidence, and routing logic. Run them before declaring a phase done.
- Keep files small and typed. Add a short README section per phase on how to run it.
- Ask me only if blocked. Otherwise choose the sensible default and note it in the README.
