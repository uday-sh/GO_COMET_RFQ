from contextlib import asynccontextmanager
from collections import defaultdict, deque
from time import monotonic
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

import models
from config import settings
from database import Base, engine, get_db
from routers import admin_api, admin_pages, auth_api, buyers_api, rfqs, suppliers_api


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Keep the one-command local SQLite experience usable. Production still runs
    # Alembic before startup; create_all is idempotent and only fills a missing
    # local schema.
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield
    await engine.dispose()


app = FastAPI(
    title="FreightFlow RFQ",
    version="1.0.0",
    lifespan=lifespan,
    openapi_tags=[
        {"name": "authentication", "description": "Sign in, sign up, and authenticate a single account."},
        {"name": "buyers", "description": "Buyer-only profile and RFQ activity. Each endpoint is scoped to the signed-in buyer."},
        {"name": "suppliers", "description": "Supplier-only profile and quotation activity. Each endpoint is scoped to the signed-in supplier."},
        {"name": "admin", "description": "Senior-admin-only account directory and role-specific user activity. Password data is never returned."},
        {"name": "rfqs", "description": "RFQ and reverse-auction workflows with ownership and supplier visibility rules."},
    ],
)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origin_list, allow_credentials=True, allow_methods=["GET", "POST"], allow_headers=["Authorization", "Content-Type"])
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")
app.include_router(auth_api.router, prefix="/api")
app.include_router(rfqs.router, prefix="/api")
app.include_router(buyers_api.router, prefix="/api")
app.include_router(suppliers_api.router, prefix="/api")
app.include_router(admin_api.router, prefix="/api")
app.include_router(admin_pages.router)
rate_buckets: dict[str, deque[float]] = defaultdict(deque)


@app.exception_handler(HTTPException)
async def render_http_error(request: Request, exc: HTTPException):
    if request.url.path.startswith("/api/"):
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code, headers=exc.headers)
    if exc.status_code == 401:
        title = "Sign in required"
    elif exc.status_code == 403:
        title = "Access denied"
    elif exc.status_code == 404:
        title = "Page not found"
    else:
        title = "Request could not be completed"
    return templates.TemplateResponse(
        request,
        "access_error.html",
        {"title": title, "message": exc.detail, "status_code": exc.status_code},
        status_code=exc.status_code,
        headers=exc.headers,
    )


@app.middleware("http")
async def security_headers(request: Request, call_next):
    if request.method == "POST" and (request.url.path == "/api/auth/token" or request.url.path == "/api/auth/register" or request.url.path.endswith("/bids")):
        key = f"{request.client.host if request.client else 'unknown'}:{request.url.path}"
        bucket = rate_buckets[key]
        now = monotonic()
        while bucket and now - bucket[0] >= 60:
            bucket.popleft()
        if len(bucket) >= settings.rate_limit_per_minute:
            return JSONResponse({"detail": "Too many requests; retry shortly"}, status_code=429, headers={"Retry-After": "60"})
        bucket.append(now)
    response = await call_next(request)
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    return response


@app.get("/health")
async def health(db: Annotated[AsyncSession, Depends(get_db)]):
    try:
        await db.execute(text("SELECT 1"))
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Database unavailable") from exc
    return {"status": "healthy"}


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
@app.get("/dashboard", response_class=HTMLResponse, include_in_schema=False)
async def dashboard(request: Request):
    return templates.TemplateResponse(request, "dashboard.html", {"title": "FreightFlow"})
