"""One observer task per backend process; bounded latest-state queues per viewer."""
import asyncio
from contextlib import suppress
from starlette.concurrency import run_in_threadpool
from .meters_service import meters_service


def difference(previous, current):
    if previous is None:
        return {'type': 'snapshot', **current}
    old = {d['name']: d for d in previous['devices']}
    new = {d['name']: d for d in current['devices']}
    changed = []
    for name, device in new.items():
        before = old.get(name)
        if before == device:
            continue
        if before is None:
            changed.append(device)
            continue
        patch = {'name': name, **{k: v for k, v in device.items() if k != 'readings' and before.get(k) != v}}
        if 'readings' in device:
            prior = {r['tag']: r for r in before.get('readings', [])}
            current_readings = {r['tag']: r for r in device['readings']}
            patch['readings'] = [
                {'tag': tag, **{k: v for k, v in r.items() if prior.get(tag, {}).get(k) != v}}
                for tag, r in current_readings.items() if prior.get(tag) != r
            ]
            patch['removed_readings'] = [tag for tag in prior if tag not in current_readings]
        changed.append(patch)
    removed = [name for name in old if name not in new]
    meta = {k: v for k, v in current.items() if k not in ('devices', 'updated_at')}
    if not changed and not removed and all(previous.get(k) == v for k, v in meta.items()):
        return None
    return {'type': 'delta', **meta, 'devices': changed, 'removed': removed, 'updated_at': current['updated_at']}


class MeterStream:
    def __init__(self):
        self.viewers = set()
        self.task = None
        self.latest = None

    def subscribe(self):
        queue = asyncio.Queue(maxsize=1)
        self.viewers.add(queue)
        if self.latest is not None:
            queue.put_nowait(self.latest)
        if self.task is None:
            self.task = asyncio.create_task(self._watch())
        return queue

    async def unsubscribe(self, queue):
        self.viewers.discard(queue)
        if not self.viewers and self.task:
            task, self.task = self.task, None
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
            self.latest = None

    async def _watch(self):
        while True:
            try:
                current = await run_in_threadpool(meters_service.get_latest)
                if difference(self.latest, current):
                    self.latest = current
                    for queue in self.viewers:
                        if queue.full():
                            queue.get_nowait()
                        queue.put_nowait(current)
            except Exception:
                # Keep the watcher alive, report failure rather than silently
                # allowing fresh-looking values when the observer broke.
                current = {'devices': [], 'source': 'unavailable', 'notice': 'Local telemetry could not be read.', 'connector': {}, 'updated_at': None}
                for queue in self.viewers:
                    if queue.full():
                        queue.get_nowait()
                    queue.put_nowait(current)
            await asyncio.sleep(1)


meter_stream = MeterStream()
