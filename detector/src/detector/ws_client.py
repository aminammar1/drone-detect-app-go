"""Reconnecting WebSocket client for detection events (FR-D6).

One connection, two tasks: a sender drains the bounded queue, a receiver logs
acks/errors. Exponential backoff (1s doubling, 30s cap) on disconnects.
Events sent but unacked are requeued on reconnect; the server is idempotent
on `event_id`, so redelivery is safe.
"""

import asyncio
import json
import logging

import websockets

logger = logging.getLogger(__name__)


class DetectorClient:
    """Async sender with a bounded in-memory queue. Create, `run`, `submit`."""

    def __init__(self, url: str, queue_size: int = 100) -> None:
        self._url = url
        self._queue: asyncio.Queue[tuple[str, str]] = asyncio.Queue(maxsize=queue_size)
        self._pending: dict[str, str] = {}
        self._run_task: asyncio.Task[None] | None = None
        self._stopping = False

    async def run(self) -> None:
        """Maintain the connection until `close`. Never raises."""
        backoff = 1.0
        while not self._stopping:
            try:
                logger.info("connecting to %s", self._url)
                async with websockets.connect(self._url, ping_interval=20) as ws:
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
            # Any transport failure (refused, reset, timeout, ...) must reconnect,
            # so this is intentionally broad. noqa: BLE001
            except Exception as exc:  # noqa: BLE001
                self._requeue_pending()
                if self._stopping:
                    break
                logger.warning("connection lost (%s); retrying in %.0fs", exc, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30.0)
        logger.info("client stopped")

    async def submit(self, event_id: str, payload: str) -> None:
        """Queue one event; drops the oldest queued event when full (logged)."""
        try:
            self._queue.put_nowait((event_id, payload))
        except asyncio.QueueFull:
            dropped_id, _ = self._queue.get_nowait()
            logger.warning("queue full, dropping oldest queued event event_id=%s", dropped_id)
            self._queue.task_done()
            self._queue.put_nowait((event_id, payload))

    async def drain(self, timeout: float = 15.0) -> bool:
        """Wait until everything queued is sent and acked. False on timeout."""
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
        """Stop the run loop. Call after `drain`."""
        self._stopping = True
        if self._run_task is not None:
            self._run_task.cancel()

    def attach(self) -> asyncio.Task[None]:
        """Start `run` in the background; keep the task to await on shutdown."""
        self._run_task = asyncio.create_task(self.run())
        return self._run_task

    async def _send_loop(self, ws) -> None:  # type: ignore[no-untyped-def]
        while True:
            event_id, payload = await self._queue.get()
            try:
                await ws.send(payload)
            except Exception:
                # Put it back at the head of the line; run() requeues the rest.
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
                logger.info(
                    "ack event_id=%s decision=%s reason=%s",
                    event_id,
                    msg.get("decision"),
                    msg.get("reason"),
                )
            elif kind == "error":
                self._pending.pop(event_id, None)
                logger.error(
                    "server rejected event_id=%s code=%s message=%s",
                    event_id,
                    msg.get("code"),
                    msg.get("message"),
                )
            else:
                logger.warning("unexpected message type=%s event_id=%s", kind, event_id)

    def _requeue_pending(self) -> None:
        """Move unacked events back to the queue after a disconnect."""
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
        """Put one item back at the head of the queue (bounded: may drop oldest)."""
        items = [(event_id, payload)]
        while not self._queue.empty():
            items.append(self._queue.get_nowait())
            self._queue.task_done()
        for item in items:
            try:
                self._queue.put_nowait(item)
            except asyncio.QueueFull:
                logger.error("dropping queued event event_id=%s (queue full)", item[0])
