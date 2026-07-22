from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.signals.event_ingestion import backfill_event_signals
from app.signals.evidence_ingestion import backfill_evidence_signals
from app.signals.fixtures import seed_concept_board_fixture
from app.signals.schemas import SignalDetail, SignalListResponse, SignalStatusUpdate
from app.signals.service import get_signal_detail, list_signals, update_signal_status
from app.utils.auth import verify_api_key

router = APIRouter()


@router.get("", response_model=SignalListResponse)
async def list_signal_items(
    scope: str = Query("all"),
    source_type: str | None = None,
    signal_type: str | None = None,
    status: str | None = None,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    items, total = await list_signals(
        db,
        scope=scope,
        source_type=source_type,
        signal_type=signal_type,
        status=status,
        limit=limit,
        offset=offset,
    )
    return {"items": items, "total": total}


@router.post("/backfill/events")
async def backfill_events(
    limit: int = Query(200, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
    _=Depends(verify_api_key),
):
    return await backfill_event_signals(db, limit=limit)


@router.post("/backfill/evidence")
async def backfill_evidence(
    source_type: str | None = None,
    limit: int = Query(200, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
    _=Depends(verify_api_key),
):
    return await backfill_evidence_signals(db, source_type=source_type, limit=limit)


@router.post("/fixtures/concept-board")
async def seed_fixture_concept_board(
    concept: str = Query("optical_module"),
    db: AsyncSession = Depends(get_db),
    _=Depends(verify_api_key),
):
    return await seed_concept_board_fixture(db, concept)


@router.get("/{signal_id}", response_model=SignalDetail)
async def get_signal_item(signal_id: str, db: AsyncSession = Depends(get_db)):
    detail = await get_signal_detail(db, signal_id)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"Signal {signal_id} not found")
    return detail


@router.post("/{signal_id}/status", response_model=SignalDetail)
async def set_signal_status(
    signal_id: str,
    body: SignalStatusUpdate,
    db: AsyncSession = Depends(get_db),
    _=Depends(verify_api_key),
):
    try:
        detail = await update_signal_status(db, signal_id, body.status)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if detail is None:
        raise HTTPException(status_code=404, detail=f"Signal {signal_id} not found")
    return detail
