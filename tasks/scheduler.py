import asyncio
import logging
import aioredis
from datetime import timedelta
from tasks.config import REDIS_HOST, REDIS_DB, REDIS_PORT

logger = logging.getLogger("scheduler")


async def run_timer(timer, callback):
    while True:
        sleep_for = timer()

        if isinstance(sleep_for, timedelta):
            sleep_for = sleep_for.total_seconds()

        await asyncio.sleep(sleep_for)

        try:
            await callback()
        except Exception as e:
            logger.error(f"ignoring exception on callback: {callback!r} due to error {e!r}")


class Scheduler:
    def __init__(self):
        self.redis: aioredis.Redis = aioredis.Redis(
            host=REDIS_HOST,
            db=int(REDIS_DB),
            port=REDIS_PORT,
        )
        self.callbacks = {}
        self.tasks = []

    async def start(self):
        for key, value in self.callbacks.items():
            logger.info(f"starting cron on task: {key}")

            timer_callback = value['timer']
            callback = value['callback']
            t = asyncio.create_task(run_timer(timer_callback, callback))
            self.tasks.append(t)

    async def wait(self):
        await asyncio.gather(*self.tasks)


app = Scheduler()
