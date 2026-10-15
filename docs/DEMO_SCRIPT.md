# Logistria procurement demo

Run the backend from the `backend` directory:

```powershell
uvicorn app.main:app --reload
```

The examples below use the default `AUTO_LIMIT=5000` and the development
header accepted when `ALLOW_INSECURE_DEV=true`.

## 1. Established supplier auto-approval

```powershell
curl -X POST http://127.0.0.1:8000/api/runs `
  -H "Content-Type: application/json" `
  -H "X-Admin-Key: demo" `
  -d '{"product_name":"Widget Pro","quantity":100}'
```

Expected outcome:

- HTTP `200`
- `status`: `completed`
- `decision.status`: `auto_approved`
- `decision.confidence`: at least `0.8`
- `decision.order_value`: under `5000`
- Apex Industrial Supplies is selected for the Plastic shortage

## 2. Nearly identical suppliers require review

```powershell
curl -X POST http://127.0.0.1:8000/api/runs `
  -H "Content-Type: application/json" `
  -H "X-Admin-Key: demo" `
  -d '{"product_name":"Sensor Module B3","quantity":50}'
```

Expected outcome:

- HTTP `200`
- `status`: `pending_human_review`
- The top two established suppliers for Copper, Resin, and Packaging have
  nearly identical scores, keeping confidence below `0.8`

## 3. Cold-start supplier wins

```powershell
curl -X POST http://127.0.0.1:8000/api/runs `
  -H "Content-Type: application/json" `
  -H "X-Admin-Key: demo" `
  -d '{"product_name":"Precision Gear","quantity":50}'
```

Expected outcome:

- HTTP `200`
- `status`: `pending_human_review`
- NexGen Procure wins the Coating shortage despite being a cold-start supplier
- Human review remains required because the selected supplier has no past orders

## 4. Enough stock means no purchase

```powershell
curl -X POST http://127.0.0.1:8000/api/runs `
  -H "Content-Type: application/json" `
  -H "X-Admin-Key: demo" `
  -d '{"product_name":"Stocked Widget","quantity":10}'
```

Expected outcome:

- HTTP `200`
- `status`: `completed`
- No purchase order is created
- Manufacturing and logistics proceed directly from available stock
