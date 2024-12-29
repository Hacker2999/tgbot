import aiohttp

async def fetch_random_joke():
    async with aiohttp.ClientSession() as session:
        async with session.get("https://baneks.site/random/") as response:
            if response.status == 200:
                return await response.text()
            return "Ошибка загрузки анекдота."
