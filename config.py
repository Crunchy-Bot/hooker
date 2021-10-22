import os

EMBED_ICON_CR = "https://cdn.discordapp.com/emojis/676087821596885013.png?v=1"
EMBED_ICON_FUN = "https://cdn.discordapp.com/emojis/863507001912066068.png?v=1"
EMBED_COLOUR_CR = 0xff9900
EMBED_COLOUR_FUN = 0xFFFFFF

ANILIST_API_URL = "https://graphql.anilist.co/"

IMAGE_SERVER_URL = os.getenv("IMAGE_SERVER_URL", "https://images.crunchy.gg/create")
IMAGE_SERVER_API_KEY = os.getenv("IMAGE_SERVER_API_KEY")

LUST_HOST = os.getenv("LUST_HOST", "https://images.crunchy.gg")

CRUNCHY_API_URL = os.getenv("CRUNCHY_API_URL", "http://192.168.1.132:8000/v0")
CRUNCHY_API_AUTH = os.getenv("CRUNCHY_API_AUTH")

NEWS_RSS_URL = os.getenv("NEWS_RSS_URL", "https://www.crunchyroll.com/newsrss")
RELEASE_RSS_URL = os.getenv("RELEASE_RSS_URL", "https://animeschedule.net/subrss.xml")
