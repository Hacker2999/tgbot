import httpx
from bs4 import BeautifulSoup
import markdownify
from typing import Optional

async def fetch_random_joke() -> Optional[str]:
    """
    Fetch a random joke from baneks.site asynchronously.
    Returns the joke as markdown text, or None if an error occurs.
    """
    url = 'https://baneks.site/random'
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(url)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "html.parser")
            joke_divs = soup.select('div[class="joke mdl-shadow--6dp block mdl-card mdl-card--border"]')
            if not joke_divs:
                return None
            paragraphs = joke_divs[0].select('p')
            if not paragraphs:
                return None
            div_html = paragraphs[0].prettify()
            joke_markdown = markdownify.markdownify(div_html, heading_style="ATX")
            return joke_markdown.strip()
    except Exception as e:
        # Optionally log the error here
        return None
