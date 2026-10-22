"""Local durable worker; same execution contract can be hosted after AWS authorization work."""

import asyncio
import time

from services import test_jobs as jobs
from services.db import uid
from services.test_cases import execute


async def process_one(owner):
    job_id = jobs.claim(owner)
    if not job_id:
        return False
    job = jobs.get(job_id)
    result = {"scenarios": []}

    def progress(value):
        nonlocal result
        result = value
        jobs.store(job_id, owner, value)

    try:
        with jobs.Session() as db:
            from services.db import TestJob

            deadline = db.get(TestJob, job_id).deadline
        result, status = await asyncio.wait_for(
            execute(job["suite"], progress), timeout=max(0.01, deadline - time.time() - 1)
        )
        jobs.store(job_id, owner, result, status)
    except Exception:
        result = result | {
            "error": "Test execution stopped. Inspect saved case results and worker readiness."
        }
        try:
            jobs.store(job_id, owner, result, "error")
        except RuntimeError:
            pass  # Expiration already fenced this worker; never overwrite a later run.
    return True


async def run():
    if not jobs.configured():
        raise RuntimeError("Only the explicitly enabled local mock worker is available")
    owner = uid()

    async def heartbeat():
        while True:
            jobs.presence()
            await asyncio.sleep(3)

    beat = asyncio.create_task(heartbeat())
    try:
        while True:
            await process_one(owner)
            if beat.done():
                beat.result()
            await asyncio.sleep(1)
    finally:
        beat.cancel()
        await asyncio.gather(beat, return_exceptions=True)


if __name__ == "__main__":
    asyncio.run(run())
