# app/api.py
from datetime import date
from typing import Optional, List, Dict, Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from .cache import cache_get_json, cache_set_json, clear_cache
from .index_logic import (
    build_index,
    get_index_performance,
    get_index_composition,
    get_composition_changes,
)
from .export import export_to_excel

app = FastAPI(title="Custom Equal-Weighted Index API")


# -----------------------
# Pydantic models
# -----------------------
class BuildIndexRequest(BaseModel):
    start_date: date
    end_date: Optional[date] = None


class IndexDay(BaseModel):
    trade_date: date
    index_level: float
    daily_return: float
    cumulative_return: float


class ExportRequest(BaseModel):
    start_date: date
    end_date: date


# -----------------------
# Endpoints
# -----------------------

@app.post("/build-index")
def build_index_endpoint(payload: BuildIndexRequest):
    """
    Build the equal-weighted index between start_date and end_date (inclusive).
    Index building *must* happen at API runtime.
    """
    try:
        result = build_index(payload.start_date, payload.end_date)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Clear any cached index_* responses since data has just changed
    clear_cache()
    
    return {
        "status": "success",
        "message": "Index built successfully",
        "metadata": result,
    }


@app.get("/index-performance", response_model=List[IndexDay])
def index_performance(start_date: date, end_date: date):
    """
    Returns daily index performance with daily and cumulative returns.
    Cached in Redis.
    """
    cache_key = f"index_performance:{start_date}:{end_date}"
    cached = cache_get_json(cache_key)
    if cached is not None:
        return cached

    data = get_index_performance(start_date, end_date)
    cache_set_json(cache_key, data)
    return data


@app.get("/index-composition")
def index_composition(date_: date = Query(..., alias="date")):
    """
    Returns index composition (100 stocks) for a given date.
    Cached in Redis.
    """
    cache_key = f"index_composition:{date_}"
    cached = cache_get_json(cache_key)
    if cached is not None:
        return cached

    data = get_index_composition(date_)
    if not data:
        raise HTTPException(status_code=404, detail="No composition for given date")

    cache_set_json(cache_key, data)
    return data


@app.get("/composition-changes")
def composition_changes(start_date: date, end_date: date):
    """
    List days when composition changed, with stocks entered and exited.
    Cached in Redis.
    """
    cache_key = f"composition_changes:{start_date}:{end_date}"
    cached = cache_get_json(cache_key)
    if cached is not None:
        return cached

    data = get_composition_changes(start_date, end_date)
    cache_set_json(cache_key, data)
    return data


@app.post("/export-data")
def export_data(payload: ExportRequest):
    """
    Export index performance, daily compositions, and composition changes
    to a single Excel (.xlsx) file.
    """
    buffer = export_to_excel(payload.start_date, payload.end_date)

    filename = f"index_export_{payload.start_date}_{payload.end_date}.xlsx"
    headers = {
        "Content-Disposition": f'attachment; filename="{filename}"'
    }
    return StreamingResponse(
        buffer,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers=headers,
    )
