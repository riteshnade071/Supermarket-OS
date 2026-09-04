# Supermarket OS — MVP

Billing (POS) + Inventory + Purchase/AI Reorder + Owner Dashboard, ek FastAPI backend mein. Multi-tenant, offline-first billing frontend included.

## What's built (Phase 1 MVP)

- **POS/Billing** — create sale, deduct stock, FEFO batch pick, cancel/reverse sale
- **Inventory** — products, barcode lookup, receive stock (with batch+expiry), manual adjustments, expiry alerts
- **Purchase / AI Reorder** — smart reorder suggestions based on last-30-days sale velocity, purchase orders
- **Dashboard** — today's sales/profit/margin, low-stock count, expiry count, prioritized "action required" feed
- **Offline-first billing screen** (`frontend/pos.html`) — queues sales in localStorage if API is unreachable, auto-syncs when back online
- Every stock change goes through one immutable `InventoryTransaction` ledger — so "stock 500 se 472 kaise hua" is always answerable

## Not yet built (Phase 2/3 — next)
Customer CRM, loyalty, WhatsApp bills, staff shift/cash-drawer reconciliation, shrinkage detection, multi-store transfer, customer-facing app.

## Local setup

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

export DATABASE_URL="postgresql://user:pass@localhost:5432/supermarket_os"
uvicorn app.main:app --reload
```

Tables auto-create on startup (`Base.metadata.create_all`). API docs at `http://localhost:8000/docs`.

## Deploy to Render

1. Push this folder to a GitHub repo
2. On Render: New → Blueprint → point at the repo (uses `render.yaml`, creates web service + free Postgres automatically)
3. Once live, open `frontend/pos.html`, set `API_BASE` to your Render URL

## First-time data setup (do this once per store, via `/docs` Swagger UI)

1. Insert a `Tenant` row and a `Store` row directly in DB (no signup UI yet — MVP)
2. `POST /inventory/products` — add your products with barcode, price, GST
3. `POST /inventory/receive-stock` — bring in opening stock
4. Open `frontend/pos.html`, plug in `tenant_id` and `store_id` → start billing

## API quick reference

| Endpoint | What it does |
|---|---|
| `POST /pos/sales` | Create a bill, deduct stock |
| `POST /pos/sales/{id}/cancel` | Cancel + reverse stock |
| `GET /pos/sales` | Recent bills |
| `POST /inventory/products` | Add product |
| `GET /inventory/products/barcode/{code}` | Barcode scan lookup |
| `POST /inventory/receive-stock` | Goods received from supplier |
| `POST /inventory/adjust-stock` | Damage/shrinkage/manual correction |
| `GET /inventory/expiry-alerts` | Products expiring soon |
| `GET /purchase/reorder-suggestions` | 🧠 AI: what to reorder + how much |
| `POST /purchase/orders` | Create purchase order |
| `GET /dashboard/summary` | Today's sales/profit/margin |
| `GET /dashboard/actions-required` | Prioritized owner action feed |

## Why this architecture

- **`InventoryTransaction`** is the single source of truth for stock. `StockLevel` is just a fast-read cache derived from it — never edited directly. This is the pattern your plan called out in section 36 as the most important table.
- **Offline-first billing**: the POS screen queues failed sale requests in `localStorage` and retries automatically on reconnect, so a supermarket's till never stops working because of a bad internet connection.
- **Multi-tenant from day one**: every table carries `tenant_id`, so one deployment can serve many supermarkets with isolated data — matches your plan to eventually sell this as SaaS to multiple stores.
