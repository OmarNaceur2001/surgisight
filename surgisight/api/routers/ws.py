"""Authenticated WebSocket replay of previously computed 1 Hz prediction records."""
from __future__ import annotations

import asyncio
import time
from typing import Annotated

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from sqlalchemy import select
from sqlalchemy.orm import Session

from surgisight.api.auth import decode_token
from surgisight.api.deps import record_access_log
from surgisight.contract.models import StreamMessage
from surgisight.db import AnalysisRunModel, UserModel, get_db
from surgisight.worker.replay import iter_per_second_records

router = APIRouter(prefix="/ws", tags=["replay"])


@router.websocket("/replay/{session_id}")
async def replay_websocket(
    websocket: WebSocket,
    session_id: str,
    db: Annotated[Session, Depends(get_db)],
) -> None:
    """Authenticate via initial message and stream contract records at requested playback speed."""
    await websocket.accept()
    try:
        auth_message = await websocket.receive_json()
        if auth_message.get("type") != "auth" or not auth_message.get("access_token"):
            await websocket.close(code=4401, reason="Authentication required")
            return
        try:
            token = decode_token(auth_message["access_token"], expected_type="access")
        except ValueError:
            await websocket.close(code=4401, reason="Invalid access token")
            return
        user = db.execute(select(UserModel).where(UserModel.id == token.get("sub"))).scalar_one_or_none()
        if user is None or not user.is_active:
            await websocket.close(code=4401, reason="Account unavailable")
            return
        run = db.execute(select(AnalysisRunModel).where(AnalysisRunModel.id == session_id)).scalar_one_or_none()
        if run is None:
            await websocket.close(code=4404, reason="Analysis not found")
            return
        speed = float(auth_message.get("speed", 1.0))
        if not 0.1 <= speed <= 8.0:
            await websocket.close(code=4400, reason="Playback speed must be between 0.1 and 8")
            return
        record_access_log(db, action="websocket_replay", user_id=user.id, video_id=run.video_id)

        previous_t: float | None = None
        for record in iter_per_second_records(session_id):
            if previous_t is not None:
                await asyncio.sleep(max(0.0, (record.t - previous_t) / speed))
            started = time.perf_counter()
            message = StreamMessage(
                session_id=session_id,
                record=record,
                latency_ms=(time.perf_counter() - started) * 1000,
            )
            await websocket.send_json(message.model_dump(mode="json"))
            previous_t = record.t
        await websocket.close(code=1000)
    except FileNotFoundError:
        await websocket.close(code=4404, reason="Predictions are not available")
    except WebSocketDisconnect:
        return
    except Exception:
        await websocket.close(code=1011, reason="Replay could not be completed")
