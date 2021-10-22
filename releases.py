import asyncio
import json
import logging
import math
from collections import defaultdict
from typing import List

import aiohttp
import discord
import feedparser
import hashlib
import re
from datetime import timedelta

from limiter import limiter
from tasks.scheduler import app
from anilist import get_todays_releases
from config import (
    CRUNCHY_API_AUTH,
    CRUNCHY_API_URL,
    EMBED_ICON_CR,
    EMBED_COLOUR_CR,
    EMBED_ICON_FUN,
    EMBED_COLOUR_FUN,
    IMAGE_SERVER_API_KEY,
    IMAGE_SERVER_URL,
    RELEASE_RSS_URL,
)


logger = logging.getLogger("release-hooks")


async def update_today(attempt=1):
    logger.info("syncing release data...")
    async with aiohttp.ClientSession() as sess:
        try:
            await get_todays_releases(sess)
        except aiohttp.ClientTimeout:
            coro = update_today(attempt + 1)
            dur = timedelta(minutes=10 * attempt).total_seconds()
            asyncio.get_running_loop().call_later(dur, lambda: asyncio.create_task(coro))
            return

    await app.redis.delete("events__release_last_id")


async def check_release():
    logger.info("checking releases....")
    async with aiohttp.ClientSession() as sess:
        await process_release(sess)


async def process_release(session: aiohttp.ClientSession()):
    async with session.get(RELEASE_RSS_URL) as r:
        r.raise_for_status()
        rss = feedparser.parse(await r.text())

    ready = []
    for entry in rss['entries'][::-1]:  # reverse it to go from oldest -> newest
        check = hashlib.md5(entry['id'].encode()).hexdigest()
        already_sent = json.loads(
            (await app.redis.get("events__release_last_id"))
            or b"[]"
        )
        if check in already_sent:
            continue

        already_sent.append(check)
        await app.redis.set("events__release_last_id", json.dumps(already_sent))

        episode = re.findall(r"(?:Episode (\d+))$", entry['id'])[0]
        title = re.subn(r"(?:Episode \d+)$", "", entry['id'], 1)[0].strip()

        headers = {"Authorization": CRUNCHY_API_AUTH}
        async with session.get(
            f"{CRUNCHY_API_URL}/data/anime/search",
            params={"query": title, "limit": 1},
            headers=headers
        ) as r:
            r.raise_for_status()
            hits = (await r.json())['data']['hits']

        if len(hits) == 0:
            return
        out = hits[0]
        out['episode'] = int(episode)
        ready.append(out)

    if ready:
        await send_release_webhooks(session, ready)


async def send_release_webhooks(session: aiohttp.ClientSession(), payloads: List[dict]):
    all_hooks = defaultdict(list)

    for anime in payloads:
        embed = await make_payload_embed(session, anime)
        hooks = await get_release_hooks(session, anime['id'])
        logger.info(f"got hooks for anime {anime['id']} with {len(hooks)=}")
        for hook in hooks:
            all_hooks[(hook['guild_id'], hook['webhook_url'])].append(embed)

    logger.info(f"preparing to send {len(all_hooks)} webhooks")

    remove = []
    for (guild_id, webhook_url), embeds in all_hooks.items():
        ok = await send_webhook(session, webhook_url, embeds)
        if not ok:
            remove.append(guild_id)

    logger.info(
        f"finished sending: {len(all_hooks)} release hooks\n"
        f"total success: {len(all_hooks) - len(remove)}\n"
        f"total removed: {len(remove)}\n"
    )

    for todo in remove:
        async with session.delete(f"{CRUNCHY_API_URL}/events/releases/{todo}"):
            ...

        logger.info(f"hook {todo!r} has been removed")


async def get_release_hooks(session: aiohttp.ClientSession, anime_id: str) -> list:
    outs = []

    i = 0
    while True:
        headers = {
            "Authorization": CRUNCHY_API_AUTH
        }

        async with session.get(
            f"{CRUNCHY_API_URL}/events/releases",
            headers=headers,
            params={"anime_id": anime_id, "limit": 500, "page": i},
            timeout=None,
        ) as r:
            r.raise_for_status()
            results = (await r.json())['data']

        outs.extend(results)
        if len(results) < 500:
            break

        i += 1

    return outs


async def make_payload_embed(session: aiohttp.ClientSession, payload: dict) -> discord.Embed:
    render_payload = {
        "title": payload['title_english'] or payload['title'],
        "episode": payload['episode'],
        "rating": math.ceil(payload['rating'] / 2),
        "description": payload['description'],
        "thumbnail": f"{payload['img_url']}?format=png",
        "tags": payload['genres'],
        "crunchyroll": payload['crunchyroll']
    }

    headers = {
        "Authorization": IMAGE_SERVER_API_KEY,
    }

    async with session.post(
        f"{IMAGE_SERVER_URL}/release",
        json=render_payload,
        headers=headers,
        timeout=None,
    ) as r:
        if r.status == 422:
            logger.error(await r.json())
        r.raise_for_status()
        thumbnail_url = (await r.json())['render']

    embed = discord.Embed(
        color=EMBED_COLOUR_CR if payload['crunchyroll'] else EMBED_COLOUR_FUN,
        description=f"**[Watch Now]({payload['link']}) - [Vote for Crunchy](https://top.gg/bot/656598065532239892)**"
    )
    embed.set_author(
        icon_url=EMBED_ICON_CR if payload['crunchyroll'] else EMBED_ICON_FUN,
        name=f"{'Crunchyroll' if payload['crunchyroll'] else 'Funimation'} Anime Release out now!",
        url=payload['link']
    )
    embed.set_image(url=thumbnail_url)
    return embed


async def send_webhook(
    session: aiohttp.ClientSession,
    hook: str,
    embeds: List[discord.Embed],
) -> bool:
    async with limiter:
        payload = {
            "username": "Crunchy",
            "avatar_url": "https://cdn.discordapp.com/avatars/656598065532239892/39344a26ba0c5b2c806a60b9523017f3.webp?size=128",
            "embeds": [
                embed.to_dict()
                for embed in embeds
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


