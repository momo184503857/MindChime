"""One local queue consumer, with explicit restart recovery."""
import asyncio
import signal
from datetime import datetime, timezone

from .db import db
from .jobs import Ctx, HANDLERS, JobControl, emit_job, settings, error_description


class Worker:
    def __init__(self, require_api=False):
        self.stop = asyncio.Event()
        self.task = None
        self.require_api = require_api
        self.running = set()

    async def start(self):
        self.stop.clear()
        runtime = db.get("business-runtime")
        api_started = runtime["data"].get("started_at", "") if runtime else ""
        for job in db.list("job"):
            if job["status"] in {"running", "pause_requested"} or (job["status"] == "queued" and api_started and job["created_at"] < api_started):
                emit_job(db.update(job["id"], status="interrupted", data={"stage": "服务重启，请确认恢复"}))
        self.task = asyncio.create_task(self.run())

    async def close(self):
        self.stop.set()
        if self.task:
            try:
                await asyncio.wait_for(asyncio.shield(self.task), timeout=12)
            except asyncio.TimeoutError:
                self.task.cancel()

    async def run(self):
        while not self.stop.is_set():
            if self.require_api:
                runtime = db.get("business-runtime")
                heartbeat = runtime["data"].get("heartbeat") if runtime else None
                alive = heartbeat and runtime["status"] == "running" and (datetime.now(timezone.utc) - datetime.fromisoformat(heartbeat)).total_seconds() < 8
                if not alive:
                    if self.running:
                        self.stop.set()
                        break
                    await asyncio.sleep(.5)
                    continue
            self.running = {task for task in self.running if not task.done()}
            capacity = max(1, min(8, int(settings().get("max_concurrent_tasks", 1))))
            job = db.claim_job() if len(self.running) < capacity else None
            if job:
                task = asyncio.create_task(self.execute(job))
                self.running.add(task)
            else:
                try:
                    await asyncio.wait_for(self.stop.wait(), timeout=.3)
                except asyncio.TimeoutError:
                    pass
        if self.running:
            await asyncio.gather(*self.running, return_exceptions=True)

    async def execute(self, job):
        ctx = Ctx(job, self.stop)
        emit_job(job)
        try:
            handler = HANDLERS.get(job["data"]["kind"])
            if not handler:
                raise ValueError("此任务类型尚未注册。")
            result = await handler(ctx, job)
            current = db.get(job["id"], "job")
            if not current or current["status"] == "cancelled":
                return
            status = "partial" if isinstance(result, dict) and result.get("partial") else "completed"
            emit_job(db.update(job["id"], status=status, data={"result": result, "stage": "部分完成" if status == "partial" else "完成", "active_step": None}))
        except JobControl as exc:
            current = db.get(job["id"], "job")
            if not current:
                return
            if current["status"] == "cancelled":
                exc.status = "cancelled"
            if ctx.partial_output and exc.status in {"cancelled", "interrupted"}:
                from .domain import save_message
                cid = current["data"]["input"].get("conversation_id")
                if cid:
                    save_message(cid, ctx.partial_output.get("speaker_name") or "未完成回复", {
                        **ctx.partial_output, "role": "assistant", "job_id": job["id"], "references": [],
                        "source_ids": [], "incomplete": True}, status="incomplete")
            if current and current["data"].get("pending_interjection") and exc.status == "paused":
                from .domain import save_message
                save_message(current["data"]["input"]["conversation_id"], "我", {"role": "user", "text": current["data"]["pending_interjection"], "speaker_name": "我", "interjection": True})
                db.update(job["id"], data={"pending_interjection": None})
            emit_job(db.update(job["id"], status=exc.status, data={"active_step": None, "stage": {"paused": "已暂停", "interrupted": "服务已中断，请确认恢复", "cancelled": "已取消"}.get(exc.status, exc.status)}))
        except asyncio.CancelledError:
            current = db.get(job["id"], "job")
            if current and current["status"] != "cancelled":
                emit_job(db.update(job["id"], status="interrupted", data={"stage": "服务已中断，请确认恢复"}))
            raise
        except Exception as exc:
            current = db.get(job["id"], "job")
            if current and current["status"] != "cancelled":
                emit_job(db.update(job["id"], status="waiting_error", data={"active_step": None, "stage": "等待处理异常", "error": error_description(exc)}))


async def main():
    from .domain import register_handlers
    from .enhancements import register_handlers as register_extra
    register_handlers()
    register_extra()
    worker = Worker(require_api=True)
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, worker.stop.set)
    await worker.start()
    await worker.task


if __name__ == "__main__":
    asyncio.run(main())

