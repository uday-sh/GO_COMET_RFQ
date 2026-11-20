from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.templating import Jinja2Templates

templates = Jinja2Templates(directory="templates")


def install_http_behavior(app: FastAPI) -> None:
    @app.exception_handler(RequestValidationError)
    async def render_validation_error(request: Request, exc: RequestValidationError):
        if request.url.path.startswith("/api/"):
            return JSONResponse(
                {
                    "detail": [
                        {key: error[key] for key in ("loc", "msg", "type") if key in error}
                        for error in exc.errors()
                    ]
                },
                status_code=422,
            )
        return templates.TemplateResponse(
            request,
            "access_error.html",
            {
                "title": "Check your filters",
                "message": "One or more values in this request are invalid. Update them and try again.",
                "status_code": 422,
            },
            status_code=422,
        )

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

    @app.exception_handler(Exception)
    async def render_unexpected_error(request: Request, _exc: Exception):
        if request.url.path.startswith("/api/"):
            return JSONResponse({"detail": "An unexpected error occurred."}, status_code=500)
        return templates.TemplateResponse(
            request,
            "access_error.html",
            {
                "title": "Something went wrong",
                "message": "We couldn’t complete this page. Please try again.",
                "status_code": 500,
            },
            status_code=500,
        )

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        if request.url.path.startswith(("/admin", "/api/admin", "/api/buyers/me", "/api/suppliers/me")):
            response.headers["Cache-Control"] = "no-store, private"
        return response
