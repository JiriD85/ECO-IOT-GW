"""
ECO-IOT-GW Meters API

Read-only child-device telemetry + connector health, derived from the gateway.
No direct Modbus access, no config editing (that stays in ThingsBoard).
"""
import logging
import hashlib
import json
import asyncio
from contextlib import suppress
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, status, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from ..models.schemas import UserInfo
from ..security.auth import get_current_user
from ..services.meters_service import meters_service

logger = logging.getLogger(__name__)
router = APIRouter()


@router.websocket('/stream')
async def stream(websocket: WebSocket):
    from ..security.auth import _user_from_token
    from ..security.tailscale_identity import identity_for_request
    from ..services.meter_stream import meter_stream, difference
    # Same-origin protection matters for automatically authenticated tailnet users.
    origin = urlsplit(websocket.headers.get('origin', ''))
    if origin.netloc != websocket.headers.get('host') or origin.scheme not in ('http', 'https'):
        await websocket.close(code=4403)
        return
    await websocket.accept()
    queue = None
    disconnected = None
    try:
        raw = await asyncio.wait_for(websocket.receive_text(), timeout=5)
        if len(raw) > 4096:
            await websocket.close(code=4401)
            return
        message = json.loads(raw)
        token = message.get('token')
        async def authorized():
            if token:
                user = await run_in_threadpool(_user_from_token, token)
                if user:
                    return user
            return await run_in_threadpool(identity_for_request, websocket)
        if not await authorized():
            await websocket.close(code=4401)
            return
        queue = meter_stream.subscribe()
        disconnected = asyncio.create_task(websocket.receive())
        previous = None
        checked = asyncio.get_running_loop().time()
        while True:
            if asyncio.get_running_loop().time() - checked >= 25:
                if not await authorized():
                    await websocket.close(code=4401)
                    return
                checked = asyncio.get_running_loop().time()
            next_sample = asyncio.create_task(queue.get())
            try:
                ready, _ = await asyncio.wait({next_sample, disconnected}, timeout=25, return_when=asyncio.FIRST_COMPLETED)
                if disconnected in ready:
                    return
                if not ready:
                    await asyncio.wait_for(websocket.send_json({'type': 'heartbeat'}), timeout=10)
                    continue
                current = next_sample.result()
                payload = difference(previous, current)
                if payload:
                    await asyncio.wait_for(websocket.send_json(payload), timeout=10)
                    previous = current
            finally:
                next_sample.cancel()
                with suppress(asyncio.CancelledError):
                    await next_sample
    except (WebSocketDisconnect, asyncio.TimeoutError, ValueError, TypeError, AttributeError):
        pass
    finally:
        if disconnected:
            disconnected.cancel()
            with suppress(asyncio.CancelledError):
                await disconnected
        if queue is not None:
            await meter_stream.unsubscribe(queue)


@router.get("/latest")
async def get_latest(request: Request, user: UserInfo = Depends(get_current_user)):
    """
    Latest values reported by each child device (P-Flow meters, AIOX temperatures)
    plus a connector health summary.

    Values come from the local Modbus observer; this API never queries the bus.
    """
    try:
        data = await run_in_threadpool(meters_service.get_latest)
        # Keep acquisition time out of the validator: unchanged data costs only
        # a 304, but sample timestamps and stale/disconnect transitions invalidate.
        payload = {k: v for k, v in data.items() if k != 'updated_at'}
        etag = '"' + hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest() + '"'
        headers = {'ETag': etag, 'Cache-Control': 'private, no-cache', 'Vary': 'Authorization, Cookie'}
        if etag in request.headers.get('if-none-match', '').split(', '):
            return Response(status_code=304, headers=headers)
        return JSONResponse(data, headers=headers)
    except Exception as e:
        logger.error(f"Failed to read meter values: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not read meter values from the gateway.",
        )
