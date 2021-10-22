import asyncio
import logging
from datetime import timedelta, date, datetime, time

from tasks.scheduler import app

import news
import releases

logging.basicConfig(level=logging.INFO)


def how_long_until_midnight() -> timedelta:
    tomorrow = date.today() + timedelta(1)
    midnight = datetime.combine(tomorrow, time())
    now = datetime.now()
    return midnight - now


app.callbacks = {
    "news-task": {
        "timer": lambda: timedelta(minutes=5),
        "callback": news.check_news,
    },
    "release-task": {
        "timer": lambda: timedelta(minutes=5),
        "callback": releases.check_release,
    },
    "release-update": {
        "timer": how_long_until_midnight,
        "callback": releases.update_today,
    }
}


async def main():
    await app.start()

    await app.wait()


if __name__ == '__main__':
    asyncio.run(main())

