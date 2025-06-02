import requests
from bs4 import BeautifulSoup
import markdownify
import asyncio
from typing import Optional

async def fetch_random_joke() -> Optional[str]:
    """
    Получить случайный анекдот с baneks.site, используя requests в отдельном потоке для максимальной совместимости.
    Возвращает анекдот в виде markdown-текста или None в случае ошибки.
    """
    def sync_fetch() -> Optional[str]:
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            }
            r = requests.get('https://baneks.site/random', headers=headers, timeout=10)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")
            joke_divs = soup.select('div[class="joke mdl-shadow--6dp block mdl-card mdl-card--border"]')
            if not joke_divs:
                return None
            paragraphs = joke_divs[0].select('p')
            if not paragraphs:
                return None
            div_html = paragraphs[0].prettify()
            joke_markdown = markdownify.markdownify(div_html, heading_style="ATX")
            return joke_markdown.strip()
        except Exception:
            return None
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, sync_fetch)
