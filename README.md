<div align="center">

# BidBolt
### Better routes. Better bids. Better business.

**Freight RFQs and British reverse auctions for buyers and suppliers.**

![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/API-FastAPI-009688?logo=fastapi&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/Database-PostgreSQL-4169E1?logo=postgresql&logoColor=white)
![Docker](https://img.shields.io/badge/Containers-Docker-2496ED?logo=docker&logoColor=white)

</div>

> **A note about the demo:** We’re sorry the public website wasn’t ready in time. Time constraints delayed deployment. We’re working to deploy it today; until then, this repository documents the working local application and its deployment setup.

---

## Contents

- [Product](#product)
- [Screenshots](#screenshots)
- [How it works](#how-it-works)
- [Technology](#technology)
- [Security concepts](#security-concepts)
- [Data model and ORM](#data-model-and-orm)
- [API overview](#api-overview)
- [Run locally](#run-locally)
- [Run with Docker](#run-with-docker)
- [System design roadmap](#system-design-roadmap)
- [Project structure](#project-structure)
- [Tests](#tests)

## Product

BidBolt connects freight buyers who need a shipment moved with suppliers who can serve that lane. A buyer creates a Request for Quotation (RFQ), describes the shipment and requirements, chooses transport modes and services, and opens a timed reverse auction. Eligible suppliers find RFQs using marketplace filters and submit quotes. The lowest accepted quote ranks first (L1), with deterministic tie-breaking.

### What’s included

| Area | Capabilities |
| --- | --- |
| Buyer workspace | Create RFQs, add supplier-facing remarks, track bids, view analytics and activity |
| Supplier workspace | Filter and match RFQs by lane, mode, service and pickup date; submit and track quotes |
| Auction rules | Server-generated RFQ IDs, timed bidding, forced-close cap, configurable extensions, rankings |
| Administration | Search accounts, inspect buyer/supplier activity, review auctions and marketplace analytics |
| Data access | Role-scoped APIs, pagination, separate public and admin response schemas |

## Screenshots

Screenshots are stored under [`docs/images/`](docs/images/). Replace these examples with updated captures as the UI changes.

<table>
  <tr>
    <td width="50%"><img src="docs/images/145024.png" alt="BidBolt landing page and sign-in" width="100%"><br><sub>Landing page and sign-in</sub></td>
    <td width="50%"><img src="docs/images/145034.png" alt="Create buyer or supplier account" width="100%"><br><sub>Account creation</sub></td>
  </tr>
  <tr>
    <td><img src="docs/images/145043.png" alt="Choose buyer or supplier account type" width="100%"><br><sub>Role selection</sub></td>
    <td><img src="docs/images/145054.png" alt="Senior administrator sign-in" width="100%"><br><sub>Admin sign-in</sub></td>
  </tr>
  <tr>
    <td><img src="docs/images/145304.png" alt="Create a freight RFQ with categories" width="100%"><br><sub>RFQ details and freight categories</sub></td>
    <td><img src="docs/images/145317.png" alt="RFQ schedule and auction settings" width="100%"><br><sub>Schedule, extensions and publishing</sub></td>
  </tr>
  <tr>
    <td><img src="docs/images/145339.png" alt="Buyer RFQ list and filters" width="100%"><br><sub>RFQ directory and filters</sub></td>
    <td><img src="docs/images/145416.png" alt="Buyer account profile and activity" width="100%"><br><sub>Account profile and activity</sub></td>
  </tr>
  <tr>
    <td><img src="docs/images/145131.png" alt="Admin analytics dashboard" width="100%"><br><sub>Admin analytics</sub></td>
    <td><img src="docs/images/145145.png" alt="Admin user directory" width="100%"><br><sub>Account directory</sub></td>
  </tr>
  <tr>
    <td><img src="docs/images/145603.png" alt="Swagger API documentation overview" width="100%"><br><sub>Interactive API reference</sub></td>
    <td><img src="docs/images/145611.png" alt="OAuth2 authorization dialog" width="100%"><br><sub>API authorization flow</sub></td>
  </tr>
  <tr>
    <td><img src="docs/images/145625.png" alt="Buyer and supplier API groups" width="100%"><br><sub>Buyer and supplier endpoints</sub></td>
    <td><img src="docs/images/145634.png" alt="Admin and RFQ API groups" width="100%"><br><sub>Admin and RFQ endpoints</sub></td>
  </tr>
  <tr>
    <td><img src="docs/images/070613.png" alt="Earlier buyer dashboard preview" width="100%"><br><sub>Earlier dashboard preview</sub></td>
    <td><img src="docs/images/145312.png" alt="RFQ form detail" width="100%"><br><sub>RFQ form detail</sub></td>
  </tr>
</table>

## How it works

1. A buyer creates an RFQ with origin, destination, pickup date, transport mode, services, remarks and auction timing.
2. The server assigns the RFQ ID and stores the RFQ and its activity record in one database transaction.
3. Suppliers browse the marketplace and filter RFQs against their saved capabilities.
4. A supplier submits freight, origin and destination charges. The server calculates the comparison total and validates the auction window and bid rules.
5. The marketplace ranks each supplier’s best accepted quote. Buyer views can inspect all quotes; suppliers see their own quote and auction progress without competitor prices.

### Auction rules

- The comparison amount is `freight_charges + origin_charges + destination_charges`, stored as `NUMERIC(18,2)`.
- A supplier’s next accepted quote must be lower than that supplier’s current best accepted quote.
- L1, L2 and L3 are calculated from each supplier’s best accepted quote. Ties use the earliest server acceptance timestamp, then bid ID.
- Extensions can trigger on a bid, rank change or L1 change. The forced-close timestamp is the absolute upper bound.
- Idempotency keys protect bid submissions from duplicate retries.

## Technology

| Layer | Implementation | Purpose |
| --- | --- | --- |
| Web/API | FastAPI | Async HTTP endpoints, dependency injection, OpenAPI docs |
| UI | Jinja templates, HTML, CSS, JavaScript | Server-rendered pages and role-specific dashboards |
| Validation | Pydantic | Validate request data and define response schemas |
| Persistence | SQLAlchemy async ORM | Map Python models to relational tables and manage transactions |
| Database | SQLite locally; PostgreSQL in Docker | Store accounts, sessions, RFQs, bids and activity |
| Schema changes | Alembic | Versioned, repeatable database migrations |
| Authentication | Signed JWT, Argon2 password hashing | Identify users and verify passwords |
| Containers | Docker and Compose | Package the app and run the local multi-container topology |
| Edge routing | Nginx | HTTP/TLS termination, shared write-rate limiting, round-robin upstream |

## Security concepts

### Authentication and JWT

Login verifies the submitted password against an Argon2 hash. FastAPI issues a signed JWT containing the subject (`sub`), session identifier (`sid`), issue time and expiry. The signature lets the server detect token changes; the token is **signed, not encrypted**, so secrets and private data do not belong in its claims.

The browser receives the token response and an `HttpOnly`, `SameSite=Lax` cookie. The cookie is marked `Secure` on HTTPS. API callers can also send the bearer token in the `Authorization` header. Access tokens expire after the configured lifetime.

### Shared login sessions across containers

JWT signature verification alone cannot revoke a token before expiry. BidBolt stores each active session in the shared `user_sessions` table. On authenticated requests, the API validates the JWT and checks that its session row exists, belongs to the user, has not expired and has not been revoked. Logout revokes the row, so either app replica rejects that session immediately.

This lets two app containers remain stateless: both use the same `SECRET_KEY` and ask PostgreSQL about the session. Sticky routing and per-container session memory are unnecessary. Docker images contain application code; PostgreSQL and its named volume hold persistent user and session data.

### Authorization and privacy

- FastAPI dependencies enforce buyer, supplier and senior-admin roles at the endpoint.
- Buyer and supplier profile/activity APIs are scoped to the signed-in account.
- Admin routes require the admin flag; public signup cannot create an administrator.
- Pydantic response models omit password hashes and internal-only fields.
- Browser-facing access errors render Jinja HTML. API routes return structured JSON errors.
- Nginx applies write throttling in one shared layer so both replicas use the same client bucket.
- Production secrets belong in deployment environment variables, never in Git or the Docker image.

## Data model and ORM

SQLAlchemy models describe the relational schema; Alembic migrations record changes to it. Foreign keys connect marketplace records, while unique and check constraints enforce important invariants in the database as well as the request layer.

```mermaid
erDiagram
    USER ||--o{ USER_SESSION : signs_in
    USER ||--o{ RFQ : creates
    RFQ ||--o{ BID : receives
    USER ||--o{ BID : submits
    RFQ ||--o{ RFQ_TRANSPORT_MODE : supports
    RFQ ||--o{ RFQ_SERVICE : requests
    RFQ ||--o{ AUCTION_ACTIVITY : records
    RFQ ||--o{ AUCTION_EXTENSION : extends
```

Important relationships and safeguards:

- `User` has a buyer/supplier role and separate supplier capability rows.
- `RFQ` belongs to a buyer; transport modes and requested services are normalized into related tables.
- `Bid` references one RFQ and supplier, stores charge components as fixed-precision decimals, and has a per-RFQ/supplier idempotency constraint.
- `UserSession` stores revocable login state shared across replicas.
- `AuctionActivity` and `AuctionExtension` preserve the operational history of an auction.
- Alembic migration `0005_shared_user_sessions` creates the session table for deployed databases.

## API overview

Interactive documentation is available at `/docs`; the OpenAPI schema is at `/openapi.json`.

| Group | Endpoints | Access |
| --- | --- | --- |
| Authentication | `POST /api/auth/register`, `/api/auth/token`, `/api/auth/admin/token`, `/api/auth/logout`; `GET /api/auth/me` | Public login/signup; authenticated profile/logout |
| RFQs | `POST /api/rfqs`, `GET /api/rfqs`, `GET /api/rfqs/{rfq_id}`, `POST /api/rfqs/{rfq_id}/bids` | Buyer creates; authorized users browse; supplier bids |
| Buyers | `GET /api/buyers/me`, `/me/activity`, `/me/analytics` | Signed-in buyer |
| Suppliers | `GET /api/suppliers/me`, `/me/activity`, `/me/analytics`; `PUT /api/suppliers/me/capabilities` | Signed-in supplier |
| Admin | `GET /api/admin/users`, `/buyers/{buyer_id}`, `/suppliers/{supplier_id}`, `/analytics` | Senior administrator |

Paginated endpoints return page metadata, total counts and `has_more`. Admin buyer/supplier detail endpoints return distinct role-specific data shapes.

## Run locally

Requirements: Python 3.12 or later and [uv](https://docs.astral.sh/uv/).

```powershell
Copy-Item .env.example .env
# Set SECRET_KEY in .env to a fresh value printed by:
python -c "import secrets; print(secrets.token_urlsafe(48))"
uv sync
uv run alembic upgrade head
uv run fastapi dev main.py
```

Open `http://localhost:8000`. You can create buyer and supplier accounts from the landing page. Create an admin with `uv run python scripts/create_admin.py`.

## Run with Docker

Copy `.env.example` to `.env`, set a random `SECRET_KEY` and URL-safe `POSTGRES_PASSWORD`, then run:

```powershell
docker compose up --build
```

Open `http://localhost:8000`. Compose starts PostgreSQL, runs Alembic once, starts two FastAPI replicas and puts Nginx in front using round-robin. Only Nginx publishes a port. PostgreSQL persists the data in a named volume; the app containers can be rebuilt or replaced without losing login sessions or marketplace records.

For a public VPS deployment, set `HTTP_PORT=80`, `HTTPS_PORT=443` and `CORS_ORIGINS=https://your-domain` in `.env`. Point a DNS A record to the server and allow inbound ports 80/443. Start the HTTP stack, request a Let's Encrypt certificate, then switch Nginx to its TLS configuration:

```powershell
docker compose up -d --build
docker compose --profile tls run --rm certbot certonly --webroot --webroot-path=/var/www/certbot --cert-name bidbolt --email you@example.com --agree-tos --no-eff-email -d your-domain.example
docker compose -f docker-compose.yml -f docker-compose.tls.yml up -d nginx
```

Schedule `certbot renew` regularly and reload Nginx after successful renewals. Never expose PostgreSQL port 5432 publicly.

## System design roadmap

The current application is a **modular monolith**: one FastAPI deployment with clear route, service, model and utility boundaries. This keeps the auction transaction and its database writes together while the product is evolving.

| Stage | Component | Why / when |
| --- | --- | --- |
| Current | Nginx, two stateless app replicas, PostgreSQL session/data store | Simple container topology; shared sessions and business records |
| Next | Redis for cache and short-lived coordination | Reduce repeated reads; add distributed locks only where database transactions are insufficient |
| Next | Background worker and durable queue | Send email, notifications and exports outside request latency; use an outbox for reliable events |
| Growth | Object storage for attachments | Keep large documents outside app containers and database rows |
| Growth | Metrics, traces, centralized logs and alerting | Observe auction latency, bid failures, database health and deployment status |
| Scale | Separate services by proven domain boundaries | Extract notifications or reporting only when independent scaling/ownership justifies network complexity |
| Scale | Managed PostgreSQL backups, pooling and high availability | Improve recovery objectives and absorb connection growth |

For correctness, bid acceptance should remain a single atomic database operation: lock the RFQ row where supported, validate server time and supplier best quote, write the bid and activity, calculate any extension, then commit. An outbox can later publish committed events without risking a notification for a rolled-back bid.

## Project structure

```text
main.py                 FastAPI app entry point
core/                   App factory, HTTP errors and security headers
routes/                 Authentication, RFQ, buyer, supplier and admin endpoints
services/               Reusable business workflows and query logic
models.py               SQLAlchemy ORM entities and database constraints
schemas.py              Pydantic request and response models
auth.py                 Password hashing, JWT and role dependencies
database.py             Async engine, session factory and ORM base
alembic/                Versioned database migrations
templates/              Jinja page templates
static/css/             UI styles
static/js/              UI behavior and shared browser utilities
deploy/nginx/           HTTP/TLS reverse proxy and shared rate limits
tests/                  API and business-rule tests
```

## Tests

```powershell
uv run pytest -q
```

The suite covers authentication and session revocation across app instances, role/privacy boundaries, filters and pagination, auction timing and extensions, bid ranking, idempotency and HTTP error rendering.

---

<div align="center"><sub>BidBolt · Better routes. Better bids. Better business.</sub></div>
