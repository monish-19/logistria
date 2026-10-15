# Logistria backend

This project implements the deterministic operational flow for the procurement, manufacturing, logistics, monitoring, and chat-driven war-room workflow.

## Included phases

- Phase 1: core backend, inventory checks, supplier ranking, procurement approval gating
- Phase 2: manufacturing, logistics optimization, monitoring alerts
- Phase 3: live War Room with event stream and human approval queue
- Phase 4: chatbot and demand-spike planning with confirm-before-act execution
- Phase 5: ERPNext and generic adapter hardening, admin auth, Docker deployment

## Run tests

```bash
cd backend
pytest -q
```

## Run the API

```bash
cd backend
uvicorn app.main:app --reload
```

Then call or use the War Room UI:

- POST /api/runs
- POST /api/runs/{run_id}/approve
- GET /api/runs/{run_id}
- POST /api/chat
- POST /api/chat/confirm

## Phase 4 chat flow

Open the live dashboard at http://localhost:8000/war-room and use the demand spike chat box.

Example prompt:

- "Demand for Product X will jump 40% next month"

The chat returns a plan, material shortfall, and requires an explicit confirmation before it creates a new production run.

## Phase 5 ERPNext + hardening

Use the adapter factory by setting `ADAPTER` to `mock`, `erpnext`, or `generic` in the environment.

```bash
export ADAPTER=erpnext
export ERP_NEXT_BASE_URL=http://localhost:8001
export ERP_NEXT_API_KEY=demo
export ADMIN_API_KEY=admin-secret
```

The application will still run against the seeded SQLite model if the ERPNext endpoint is not available, which keeps local demos deterministic and testable.

### Admin auth

Admin actions require either:

- `X-Admin-Key: <value>`
- `Authorization: Bearer <value>`

This applies to `/api/runs`, `/api/runs/{run_id}/approve`, and `/api/chat/confirm`.
If `ADMIN_API_KEY` is unset, these endpoints return `503` unless
`ALLOW_INSECURE_DEV=true` is explicitly enabled. When a key is configured,
the events WebSocket also requires the same key as its `?token=` query parameter.

### Docker

```bash
cd logistria
docker compose up --build
```

This starts the backend on port 8000.

### Demo script

```bash
# scenario 1: healthy inventory
curl -X POST http://localhost:8000/api/runs \
  -H "Content-Type: application/json" \
  -H "X-Admin-Key: admin-secret" \
  -d '{"product_name":"Widget Pro","quantity":5,"due_date":"2035-01-20","urgency":"normal"}'

# scenario 2: shortage + approval gate
curl -X POST http://localhost:8000/api/runs \
  -H "Content-Type: application/json" \
  -H "X-Admin-Key: admin-secret" \
  -d '{"product_name":"Sensor Module B3","quantity":50,"due_date":"2035-01-10","urgency":"high"}'

# scenario 3: demand spike chat plan
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"Demand for Product X will jump 40% next month"}'
```
## Supabase setup

1. Create a Supabase project and open **Connect -> Connection string**.
2. Copy the **Session pooler** URI into `DATABASE_URL`, replacing the password
   placeholder. The application accepts either `postgresql://` or
   `postgresql+psycopg://` URLs and enables `pool_pre_ping`.
3. Apply the schema and seed deterministic demo data:

   ```powershell
   cd backend
   $env:DATABASE_URL="postgresql://postgres.<project-ref>:<password>@<pooler-host>:5432/postgres?sslmode=require"
   alembic upgrade head
   python -c "from app.seed import seed_database; seed_database()"
   ```

4. Start the API with the same `DATABASE_URL`, then verify a full run:

   ```powershell
   $env:ALLOW_INSECURE_DEV="true"
   uvicorn app.main:app --reload
   ```

   In another terminal, POST a `Widget Pro` run to `/api/runs` and confirm
   that the response reaches `manufacturing` and that
   `GET /api/runs/{run_id}` contains the completed route fields.
