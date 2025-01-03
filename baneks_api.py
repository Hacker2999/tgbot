import requests
from bs4 import BeautifulSoup
import markdownify

async def fetch_random_joke():
    r = requests.get('https://baneks.site/random')
    soup = BeautifulSoup(r.text, "html.parser")

    div = soup.select('div[class="joke mdl-shadow--6dp block mdl-card mdl-card--border"]')[0]
    div2= soup.select('p')[0]
    div3 = div2.prettify()
    div4 = markdownify.markdownify(div3, heading_style="ATX")
# print(anekdot)
    return div4
