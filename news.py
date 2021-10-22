import logging

import aiohttp
import feedparser
import bs4
import discord  # noqa

from limiter import limiter
from tasks.scheduler import app
from config import (
    NEWS_RSS_URL,
    IMAGE_SERVER_API_KEY,
    IMAGE_SERVER_URL,
    EMBED_COLOUR_CR,
    EMBED_ICON_CR, CRUNCHY_API_AUTH, CRUNCHY_API_URL,
)

logger = logging.getLogger("news-hooks")


async def check_news():
    logger.info("checking news....")
    async with aiohttp.ClientSession() as sess:
        embed = await get_and_parse_rss(sess)
        if embed is None:
            return
        await send_news_webhooks(sess, embed)


async def send_news_webhooks(session: aiohttp.ClientSession, embed: discord.Embed):
    logger.info(f"news updates! fetching data")
    hooks = []

    i = 0
    while True:
        headers = {
            "Authorization": CRUNCHY_API_AUTH
        }

        async with session.get(
            f"{CRUNCHY_API_URL}/events/news",
            headers=headers,
            params={"limit": 500, "page": i},
            timeout=None,
        ) as r:
            r.raise_for_status()
            content = await r.json()

        results = content['data']
        hooks.extend(results)
        if len(results) < 500:
            break

        i += 1

    logger.info(f"preparing to send {len(hooks)} webhooks")

    remove = []
    for hook in hooks:
        ok = await send_webhook(session, hook['webhook_url'], embed)
        if not ok:
            remove.append(hook['guild_id'])

    logger.info(
        f"finished sending: {len(hooks)} release hooks\n"
        f"total success: {len(hooks) - len(remove)}\n"
        f"total removed: {len(remove)}\n"
    )

    for todo in remove:
        await session.delete(f"{CRUNCHY_API_URL}/events/news/{todo}")
        logger.info(f"hook {todo!r} has been removed")


async def get_and_parse_rss(session: aiohttp.ClientSession):
    async with session.get(NEWS_RSS_URL) as r:
        r.raise_for_status()
        feed = feedparser.parse(await r.text())['entries'][0]

    last_id = await app.redis.get("events__news_last_id")
    if last_id is not None and feed['id'] == last_id.decode("utf-8"):
        return

    await app.redis.set("events__news_last_id", feed['id'])

    dirty_description = feed['summary']\
        .replace("<br />", "<br/>")\
        .replace("<br/>", "||", 1)\
        .replace("\xa0", " ")

    soup = bs4.BeautifulSoup(dirty_description, 'lxml')
    summary, brief = soup.text.split("||", 1)
    thumbnail = soup.find("img").get("src")
    url = feed['link']

    payload = {
        "title": feed['title'],
        "summary": summary,
        "author": feed['author'],
        "brief": brief,
        "thumbnail": thumbnail,
    }

    headers = {
        "Authorization": IMAGE_SERVER_API_KEY,
    }

    async with session.post(
        f"{IMAGE_SERVER_URL}/news",
        json=payload,
        headers=headers,
        timeout=None,
    ) as r:
        r.raise_for_status()

        thumbnail_url = (await r.json())['render']

    embed = discord.Embed(
        color=EMBED_COLOUR_CR,
        description=f"**[Read More]({url}) - [Vote for Crunchy](https://top.gg/bot/656598065532239892)**"
    )
    embed.set_author(
        icon_url=EMBED_ICON_CR,
        name="Crunchyroll Anime News! - Click for more!",
        url=url,
    )
    embed.set_image(url=thumbnail_url)

    return embed


async def send_webhook(session: aiohttp.ClientSession, hook: str, embed: discord.Embed) -> bool:
    async with limiter:
        payload = {
            "username": "Crunchy",
            "avatar_url": "https://cdn.discordapp.com/avatars/656598065532239892/39344a26ba0c5b2c806a60b9523017f3.webp?size=128",
            "embeds": [
                embed.to_dict()
            ]
        }

        try:
            async with session.post(hook, json=payload) as resp:
                if resp.status in (403, 404):
                    return False
                elif resp.status != 200:
                    logger.info(f"failed to send news webhook: {resp!r}")
                return True
        except Exception as e:
            logger.error(f"Error while sending webhook in releases: {e!r} {hook}")
            return True

