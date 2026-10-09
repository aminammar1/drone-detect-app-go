"""Reconnecting sender for detection events (FR-D6).

Bounded queue survives short outages. Backoff 1s doubling, 30s cap. Unacked
events are requeued; server dedupes on event_id so redelivery is safe.
"""

import asyncio
import json
import logging

import websockets

logger = logging.getLogger(__name__)


class DetectorClient:
    """Async sender with a bounded in-memory queue."""

    def __init__(self, url: str, queue_size: int = 100, token: str = "") -> None:
        self._url = url
        self._queue: asyncio.Queue[tuple[str, str]] = asyncio.Queue(maxsize=queue_size)
        self._pending: dict[str, str] = {}
        self._run_task: asyncio.Task[None] | None = None
        self._stopping = False
        # Shared secret for the server's X-Detector-Token check; empty sends
        # no header (server check disabled).
        self._token = token
        # Last server reply per event_id (ack or error); drives snapshot pruning.
        self.acks: dict[str, dict] = {}

    async def run(self) -> None:
        """Hold the connection until close. Never raises."""
        backoff = 1.0
        headers = {"X-Detector-Token": self._token} if self._token else None
        while not self._stopping:
            try:
                logger.info("connecting to %s", self._url)
                async with websockets.connect(
                    self._url, ping_interval=20, additional_headers=headers
                ) as ws:
                    logger.info("connected to %s", self._url)
                    backoff = 1.0
                    sender = asyncio.create_task(self._send_loop(ws))
                    receiver = asyncio.create_task(self._recv_loop(ws))
                    try:
                        done, pending = await asyncio.wait(
                            (sender, receiver), return_when=asyncio.FIRST_COMPLETED
                        )
                    except asyncio.CancelledError:
                        sender.cancel()
                        receiver.cancel()
                        raise
                    for task in pending:
                        task.cancel()
                    for task in done:
                        if not task.cancelled() and task.exception() is not None:
                            raise task.exception()  # type: ignore[misc]
            except asyncio.CancelledError:
                break
            # Broad by design: any transport failure must reconnect. noqa: BLE001
            except Exception as exc:  # noqa: BLE001
                self._requeue_pending()
                if self._stopping:
                    break
                hint = (
                    " -- HTTP 403 means the server's DETECTOR_TOKEN check rejected us; "
                    "set DETECTOR_TOKEN to match the server (empty disables the check)"
                    if "403" in str(exc)
                    else ""
                )
                logger.warning("connection lost (%s); retrying in %.0fs%s", exc, backoff, hint)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30.0)
        logger.info("client stopped")

    async def submit(self, event_id: str, payload: str) -> None:
        """Queue one event; full queue drops the oldest (logged)."""
        try:
            self._queue.put_nowait((event_id, payload))
        except asyncio.QueueFull:
            dropped_id, _ = self._queue.get_nowait()
            logger.warning("queue full, dropping oldest queued event event_id=%s", dropped_id)
            self._queue.task_done()
            self._queue.put_nowait((event_id, payload))

    async def drain(self, timeout: float = 60.0) -> bool:
        """Block until queued events are acked; False on timeout."""
        try:
            await asyncio.wait_for(self._queue.join(), timeout=timeout)
            async with asyncio.timeout(timeout):
                while self._pending:
                    await asyncio.sleep(0.05)
            return True
        except TimeoutError:
            logger.warning(
                "drain timed out: %d queued, %d unacked",
                self._queue.qsize(),
                len(self._pending),
            )
            return False

    async def close(self) -> None:
        """Stop the run loop; call after drain."""
        self._stopping = True
        if self._run_task is not None:
            self._run_task.cancel()

    def attach(self) -> asyncio.Task[None]:
        """Start run in background; await the task on shutdown."""
        self._run_task = asyncio.create_task(self.run())
        return self._run_task

    async def _send_loop(self, ws) -> None:  # type: ignore[no-untyped-def]
        while True:
            event_id, payload = await self._queue.get()
            try:
                await ws.send(payload)
            except Exception:
                # Head of line; run() requeues the rest.
                self._prepend(event_id, payload)
                self._queue.task_done()
                raise
            self._pending[event_id] = payload
            self._queue.task_done()

    async def _recv_loop(self, ws) -> None:  # type: ignore[no-untyped-def]
        async for raw in ws:
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                logger.warning("ignoring non-JSON frame: %r", raw[:120])
                continue
            event_id = msg.get("event_id", "?")
            kind = msg.get("type")
            if kind == "ack":
                self._pending.pop(event_id, None)
                self.acks[event_id] = msg
                drone = msg.get("drone") or {}
                # Identified names come from IDENT/beacon -> DB, never pixels.
                drone_txt = (
                    f"{drone.get('manufacturer', '')} {drone.get('model', '')} "
                    f"{drone.get('serial_number', '')}".strip()
                    if drone
                    else "unidentified"
                )
                logger.info(
                    "ack event_id=%s decision=%s reason=%s drone=%s",
                    event_id,
                    msg.get("decision"),
                    msg.get("reason"),
                    drone_txt,
                )
            elif kind == "error":
                self._pending.pop(event_id, None)
                self.acks[event_id] = msg
                logger.error(
                    "server rejected event_id=%s code=%s message=%s",
                    event_id,
                    msg.get("code"),
                    msg.get("message"),
                )
            else:
                logger.warning("unexpected message type=%s event_id=%s", kind, event_id)

    def _requeue_pending(self) -> None:
        """Return unacked events to the queue after disconnect."""
        if not self._pending:
            return
        logger.warning("requeuing %d unacked events", len(self._pending))
        items = list(self._pending.items())
        self._pending.clear()
        for event_id, payload in items:
            try:
                self._queue.put_nowait((event_id, payload))
            except asyncio.QueueFull:
                logger.error("dropping unacked event event_id=%s (queue full)", event_id)

    def _prepend(self, event_id: str, payload: str) -> None:
        """Head-of-line requeue; may drop oldest when bounded."""
        items = [(event_id, payload)]
        while not self._queue.empty():
            items.append(self._queue.get_nowait())
            self._queue.task_done()
        for item in items:
            try:
                self._queue.put_nowait(item)
            except asyncio.QueueFull:
                logger.error("dropping queued event event_id=%s (queue full)", item[0])
