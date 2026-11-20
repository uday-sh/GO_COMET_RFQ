import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from core.http import install_http_behavior


@pytest.mark.anyio
async def test_unexpected_browser_errors_render_html_without_internal_details():
    app = FastAPI()
    install_http_behavior(app)

    @app.get("/broken-page")
    async def broken_page():
        raise RuntimeError("private traceback detail")

    @app.get("/api/broken")
    async def broken_api():
        raise RuntimeError("private traceback detail")

    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        browser_response = await client.get("/broken-page")
        api_response = await client.get("/api/broken")

    assert browser_response.status_code == 500
    assert browser_response.headers["content-type"].startswith("text/html")
    assert "Something went wrong" in browser_response.text
    assert "private traceback detail" not in browser_response.text
    assert api_response.status_code == 500
    assert api_response.headers["content-type"].startswith("application/json")
    assert api_response.json() == {"detail": "An unexpected error occurred."}
