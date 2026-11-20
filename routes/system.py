from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.templating import Jinja2Templates
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db

router = APIRouter(include_in_schema=False)
templates = Jinja2Templates(directory="templates")


@router.get("/health")
async def health(db: Annotated[AsyncSession, Depends(get_db)]):
    try:
        await db.execute(text("SELECT 1"))
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Database unavailable") from exc
    return {"status": "healthy"}


@router.get("/", name="home")
@router.get("/dashboard", name="dashboard")
async def dashboard(request: Request):
    return templates.TemplateResponse(request, "dashboard.html", {"title": "BidBolt"})
