import asyncio
import base64
import logging

import aiohttp
import bs4
import re
from datetime import timedelta, datetime, date, time as dtime
from config import LUST_HOST, IMAGE_SERVER_API_KEY, CRUNCHY_API_URL, CRUNCHY_API_AUTH

query = '''
query ($noIn: [Int]) {
  AiringSchedule (id_not_in: $noIn, sort: TIME, notYetAired: true) { # Insert our variables into the query arguments (id) (type: ANIME is hard-coded in the query)
  id,
  episode,
  media {
      title {
          romaji,
          english,
          native,
      },
      description (
         asHtml: false
      ),
      genres,
      averageScore,
      coverImage {
        large,
      },
      externalLinks {
        url,
        site,
      },
  },
  timeUntilAiring
  }
}
'''

url = 'https://graphql.anilist.co'
ALLOWED_LINKS = ("Funimation", "Crunchyroll")

logger = logging.getLogger("anilist")


def how_long_until_midnight():
    tomorrow = date.today() + timedelta(days=1)
    midnight = datetime.combine(tomorrow, dtime())
    now = datetime.now()
    return (midnight - now).seconds


async def get_todays_releases(session: aiohttp.ClientSession):
    logger.info("getting today's releases")
    time_until_airing = 0

    variables = {
        "noIn": []
    }

    while time_until_airing < how_long_until_midnight():
        async with session.post(url, json={'query': query, 'variables': variables}) as r:
            if r.status != 200:
                logger.error(f"{r.json()!r}")
                r.raise_for_status()

            data = (await r.json())['data']['AiringSchedule']
        media = data['media']

        id_ = data['id']
        title = media['title']
        links = media.get("externalLinks")
        variables['noIn'].append(id_)
        if links is None:
            continue

        valid = False
        is_cr = False
        ref_link = ""
        for link in links:
            site = link['site']
            if site not in ALLOWED_LINKS:
                continue

            ref_link = link['url']
            valid = True
            if site == ALLOWED_LINKS[1]:  # cr
                is_cr = True
                break

        if not valid:
            continue

        thumbnail_image = media['coverImage']['large']
        rating = round((media['averageScore'] or 10) / 10, 1)
        time_until_airing = data['timeUntilAiring']
        desc = bs4.BeautifulSoup(media['description'].replace("\n", " "), 'lxml').text
        while "  " in desc:
            desc = desc.replace("  ", " ")

        comp = re.compile(r"\(Source: [a-zA-Z0-9 -]+\)", re.IGNORECASE)
        desc = comp.sub("", desc)

        payload = {
            "title": title['romaji'],
            "title_english": title['english'],
            "title_japanese": title['native'],
            "description": desc,
            "rating": rating,
            "img_url": thumbnail_image,
            "link": ref_link,
            "time_until_airing": time_until_airing,
            "crunchyroll": is_cr,
            "genres": media['genres'],
            "episode": data['episode'],
        }

        payload = await process_release_img(session, payload)
        logger.info(f"got release: {payload['title_english'] or payload['title']}")
        payload['anime_id'] = await add_anime_if_new(session, payload)
        await asyncio.sleep(1)


async def process_release_img(session: aiohttp.ClientSession, payload: dict) -> dict:
    async with session.get(payload['img_url']) as r:
        r.raise_for_status()
        data = base64.standard_b64encode(await r.read()).decode("utf-8")

    format_ = "jpeg"
    if payload['img_url'].endswith(".png"):
        format_ = "png"
    elif payload['img_url'].endswith(".webp"):
        format_ = "webp"

    img_payload = {
        "format": format_,
        "data": data,
        "category": "thumbnails"
    }

    headers = {
        "Authorization": IMAGE_SERVER_API_KEY
    }

    async with session.post(f"{LUST_HOST}/admin/create/image", json=img_payload, headers=headers) as r:
        r.raise_for_status()
        data = (await r.json())['data']

    file_id = data['file_id']
    payload['img_url'] = f"{LUST_HOST}/content/thumbnails/{file_id}"
    return payload


async def add_anime_if_new(session: aiohttp.ClientSession, payload: dict) -> str:
    async with session.get(
        f"{CRUNCHY_API_URL}/data/genres/flags",
        params={"genres": payload['genres']}
    ) as r:
        r.raise_for_status()
        flags = (await r.json())['data']

    payload2 = payload.copy()
    payload2['genres'] = flags

    headers = {
        "Authorization": CRUNCHY_API_AUTH
    }
    async with session.post(
        f"{CRUNCHY_API_URL}/data/anime",
        json=payload2,
        headers=headers,
    ) as r:
        if r.status == 422:
            logger.error(await r.json(), payload)
        r.raise_for_status()

        data = (await r.json())['data']['id']
    return data
