from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

import models
from config import settings
from database import Base, engine
from core.http import install_http_behavior
from routes import admin_api, admin_pages, auth_api, buyers_api, rfqs, suppliers_api, system


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Local SQLite startup stays convenient. Production schema changes run once
    # through the Compose migration job before either replica serves traffic.
    if settings.database_url.startswith("sqlite"):
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
    yield
    await engine.dispose()


def create_app() -> FastAPI:
    app = FastAPI(
        title="BidBolt Freight Marketplace",
        version="1.1.0",
        lifespan=lifespan,
        openapi_tags=[
            {"name": "authentication", "description": "Sign in, sign up, and authenticate an account."},
            {"name": "buyers", "description": "Buyer-only profile and RFQ activity, scoped to the signed-in buyer."},
            {"name": "suppliers", "description": "Supplier profile, service capabilities, and quotation activity."},
            {"name": "admin", "description": "Senior-admin-only directory and role-specific activity; password data is never returned."},
            {"name": "rfqs", "description": "RFQ creation, supplier marketplace filtering, and reverse-auction workflows."},
        ],
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT"],
        allow_headers=["Authorization", "Content-Type"],
    )
    app.mount("/static", StaticFiles(directory="static"), name="static")
    for route_group in (auth_api, rfqs, buyers_api, suppliers_api, admin_api):
        app.include_router(route_group.router, prefix="/api")
    app.include_router(admin_pages.router)
    app.include_router(system.router)
    install_http_behavior(app)
    return app
