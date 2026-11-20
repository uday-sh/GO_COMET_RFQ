# BidBolt — Better routes. Better bids. Better business.

BidBolt is a buyer and supplier freight marketplace built with FastAPI, async SQLAlchemy, Jinja, and browser JavaScript. Buyers publish RFQs and suppliers find work that matches their routes and service capabilities, then compete in a British reverse auction. The canonical comparison amount is `freight_charges + origin_charges + destination_charges`, stored as `NUMERIC(18,2)`. Ranking uses each supplier's best accepted quote, then earliest server-side acceptance time, then bid ID for deterministic ties.

## Architecture

The application is a modular monolith. `main.py` only creates the FastAPI app; `core/app_factory.py` configures it, and HTTP error and security behavior live under `core/`. All endpoint paths and handlers live under `routes/`, grouped by authentication, RFQs, buyer/supplier APIs, administration, and system pages. Business workflows and persistence remain in focused modules. Browser helpers live in `static/js/utils/`, with the UI entry point in `static/js/app.js`.

```mermaid
flowchart LR
  Browser[BidBolt UI: Jinja + JavaScript] --> Nginx[Nginx round-robin proxy]
  Nginx --> App1[Stateless FastAPI replica 1]
  Nginx --> App2[Stateless FastAPI replica 2]
  App1 --> Routes[routes/ endpoint modules]
  App2 --> Routes
  Routes --> Identity[Authentication and account APIs]
  Routes --> Auctions[RFQ and auction workflows]
  Identity --> DB[(Shared PostgreSQL: users, sessions, RFQs, quotes)]
  Auctions --> DB
  Auctions --> Audit[Bid, extension, and activity ledger]
  Auctions -. future committed events .-> Notify[Optional notification service]
```

The database is the source of truth, including active login sessions. Both FastAPI replicas use the same signing key and PostgreSQL session table; no sticky sessions are needed, and logout revokes a session across both replicas. A bid transaction locks the RFQ row where the database supports row locks, checks the database/server deadline, validates a strictly lower supplier quote, recalculates rankings, applies the configured extension if eligible, and writes audit records before commit. `idempotency_key` is unique per supplier/RFQ so safe client retries do not create duplicate submissions.

## Freight categories and marketplace filters

Suppliers save supported transport modes and services in their account profile. The current modes are road, air, ocean, rail, multimodal, and courier. Services include full and less-than-truck/container loads, reefer, hazmat, oversized freight, express, customs, warehousing, and last mile.

Buyers choose one or more transport modes and optional services when creating an RFQ, and can include origin, destination, pickup date, and remarks. Buyers and suppliers can filter their RFQ lists by mode, service, origin, destination, pickup-date range, status, accepted quotes, notes, and auctions closing within 24 hours. Suppliers can also match saved capabilities. Bid detail filters show each supplier’s current best quote and the top three ranks. Selected filters apply immediately and appear as active chips. Admins can filter and inspect auctions and bids across the marketplace.

## Dashboards and analytics

Buyer and supplier workspaces include a role-aware sidebar, overview metrics, 14-day activity charts, paginated RFQ lists, paginated quote history, and account settings. Buyer analytics count only that buyer’s RFQs and received quotes. Supplier analytics use only that supplier’s quotations and leading ranks. The senior-admin dashboard shows global account, RFQ, and quote metrics, with paginated user and auction directories and per-account activity views.

## Business rules

- Auction IDs are assigned by the server from the database sequence; buyers enter the auction name, schedule, and supplier-facing remarks, not an ID.
- Buyer remarks are stored with the RFQ and shown in buyer and supplier detail views. Account history records buyer RFQ creation and supplier quotation submissions.
- Buyer lists and detail views are scoped to RFQs owned by that buyer. Suppliers can browse RFQs and see only their own quote amounts.
- All API timestamps must include a timezone and are normalized to UTC.
- An auction starts at `bid_start_at`, naturally closes at `current_close_at`, and becomes `force_closed` at `forced_close_at`. The forced deadline is absolute.
- A supplier may submit a new bid only when it is strictly below that supplier's best accepted quote.
- L1/L2/L3 are calculated from one best accepted quote per supplier. Ties use earliest accepted server-side timestamp, then bid ID.
- Extension modes are `bid_received`, `rank_change`, and `l1_change`. The trigger window is evaluated relative to the current close, repeated extensions are allowed, and close time is capped at the forced close.
- Buyers can see all accepted quotation details. Suppliers can see auction progress and their own accepted quotations, but not competitor quote details.

## Local setup

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```powershell
Copy-Item .env.example .env
# Set SECRET_KEY in .env to a generated value, for example:
python -c "import secrets; print(secrets.token_urlsafe(48))"
uv sync
uv run alembic upgrade head
uv run fastapi dev main.py
```

Open http://localhost:8000. Public signup lets users choose a buyer or supplier account. Weak-password choices prompt a recommendation modal but remain allowed. Buyer dashboards show only RFQs created by that buyer; supplier dashboards show the filtered RFQ marketplace. Both roles have an account page, analytics, and paginated activity history.

## User data and senior administration

Create or promote the senior administrator with `uv run python scripts/create_admin.py`. The script prompts for username, email, and a hidden password, then stores only an Argon2 password hash. The admin portal at `/admin` includes marketplace analytics, auction and bid oversight at `/admin/auctions`, and a searchable, filterable account directory at `/admin/users`. User and quote history pages are paginated. Browser requests without admin access receive a Jinja HTML error page.

The OpenAPI docs group role-specific account APIs under **Buyers**, **Suppliers**, and **Admin**. Buyers use `GET /api/buyers/me`, `/api/buyers/me/activity`, and `/api/buyers/me/analytics`; suppliers use `GET /api/suppliers/me`, `/api/suppliers/me/activity`, and `/api/suppliers/me/analytics`, and can save capabilities with `PUT /api/suppliers/me/capabilities`. Activity endpoints and RFQ bid details accept page parameters and return totals and `has_more`. Admin-only endpoints include `GET /api/admin/analytics`, `/api/admin/users`, `/api/admin/buyers/{id}`, and `/api/admin/suppliers/{id}`. Buyer, supplier, and admin detail responses have separate schemas; none include password hashes. Buyer and supplier endpoints are scoped to the signed-in person, and admin endpoints require the senior-admin flag.

## Docker

```powershell
# Copy .env.example to .env, then set SECRET_KEY and POSTGRES_PASSWORD.
docker compose up --build
```

Open http://localhost:8000. Nginx is the only public container; its default upstream policy distributes requests round-robin between `app1` and `app2`. The app containers have no published host ports and hold no user/session state. PostgreSQL persists the marketplace data and revocable login sessions in the `postgres_data` volume. Compose runs migrations once before either app replica starts. The application image runs as a non-root user, and `.dockerignore` excludes local secrets, databases, and virtual environments.

For a public HTTPS deployment, point a DNS A record at the VM and set `HTTP_PORT=80`, `HTTPS_PORT=443`, and `CORS_ORIGINS=https://your-domain` in `.env`. First start the stack with HTTP so the ACME challenge can complete, then request a Let's Encrypt certificate and switch Nginx to the TLS config:

```powershell
docker compose up -d --build
docker compose --profile tls run --rm certbot certonly --webroot --webroot-path=/var/www/certbot --cert-name bidbolt --email you@example.com --agree-tos --no-eff-email -d your-domain.example
docker compose -f docker-compose.yml -f docker-compose.tls.yml up -d nginx
```

Schedule certificate renewal on the VM (for example, twice daily) with `docker compose --profile tls run --rm certbot renew --webroot --webroot-path=/var/www/certbot`, followed by `docker compose -f docker-compose.yml -f docker-compose.tls.yml exec nginx nginx -s reload`.

Generate the two secrets with URL-safe hexadecimal values before editing `.env` (the database password is embedded in the connection URL):

```powershell
python -c "import secrets; print('SECRET_KEY=' + secrets.token_urlsafe(48)); print('POSTGRES_PASSWORD=' + secrets.token_hex(32))"
```

For a new Oracle Cloud VM, choose an Always Free Ampere A1 shape and Ubuntu image, allow inbound TCP ports 80 and 443 in both the OCI network security list and the VM firewall, then install Docker Engine and the Compose plugin using [Docker's official Ubuntu instructions](https://docs.docker.com/engine/install/ubuntu/). Clone the repository on the VM, create `.env` from `.env.example`, set `HTTP_PORT=80`, `HTTPS_PORT=443`, the generated secrets, and your HTTPS origin, then run the commands above. Do not add port 8000 or PostgreSQL port 5432 to the public ingress rules.

### Free-tier deployment target

The Compose topology is sized for an Oracle Cloud Always Free Ampere VM with up to 2 OCPUs and 12 GB of memory. This runs two application containers on one VM; it gives request-level balancing between app processes, but the VM, Nginx, and PostgreSQL remain a single host failure point. Oracle requires payment-card verification for signup, free capacity can vary by region, and Oracle may reclaim compute it considers idle. See [Oracle Always Free resources](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm) and [Oracle Free Tier terms and limits](https://www.oracle.com/cloud/free/).

Render Free cannot run this exact topology: a free web service is limited to one instance, and free Key Value data is in-memory and lost when the service restarts. Render web services also sleep after 15 minutes without inbound traffic. See [Render's free service limits](https://render.com/docs/free) and [instance scaling limits](https://render.com/docs/scaling). Keep regular database backups; the free VM volume is not a substitute for a backup plan.

## Tests

```powershell
uv run pytest -q
```

The test suite uses a temporary SQLite database and covers API authorization, freight capability updates and filters, bid filters and pagination, role-scoped analytics, admin directory and auction oversight, monetary precision, rank/tie behavior, trigger modes, forced-close rules, idempotent retries, and concurrent submission coverage.
