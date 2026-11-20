from collections import defaultdict, deque
from time import monotonic

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.templating import Jinja2Templates

from config import settings

templates = Jinja2Templates(directory="templates")
rate_buckets: dict[str, deque[float]] = defaultdict(deque)


def install_http_behavior(app: FastAPI) -> None:
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
        limited_paths = {
            "/api/auth/token",
            "/api/auth/admin/token",
            "/api/auth/register",
        }
        if request.method == "POST" and (request.url.path in limited_paths or request.url.path.endswith("/bids")):
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
        if request.url.path.startswith(("/admin", "/api/admin", "/api/buyers/me", "/api/suppliers/me")):
            response.headers["Cache-Control"] = "no-store, private"
        return response
