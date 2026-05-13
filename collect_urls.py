import asyncio
import random
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup

BASE_URL = "https://www.arabam.com/ikinci-el/otomobil/{}?take=50&page={}"
OUTPUT_FILE = "urls.txt"
MAX_PAGES = 50
CONCURRENCY = 5

BRANDS = [
    "bmw", "mercedes-benz", "volkswagen", "toyota", "ford",
    "renault", "fiat", "honda", "hyundai", "opel", "peugeot",
    "citroen", "audi", "seat", "skoda", "kia", "nissan",
    "dacia", "volvo", "porsche"
]


async def get_listing_urls(semaphore, browser, brand, page_number):
    async with semaphore:
        page = await browser.new_page()
        for attempt in range(3):
            try:
                await page.goto(BASE_URL.format(brand, page_number))
                await page.wait_for_load_state("domcontentloaded")
                soup = BeautifulSoup(await page.content(), "html.parser")
                anchors = soup.find_all("a", class_="link-overlay", href=True)
                await page.close()
                await asyncio.sleep(random.uniform(1.0, 2.5))
                return list({
                    "https://www.arabam.com" + a["href"]
                    for a in anchors
                    if a["href"].startswith("/ilan/")
                })
            except Exception as e:
                print(f"  Attempt {attempt + 1} failed ({brand} p{page_number}): {e}")
                await asyncio.sleep(5)
        await page.close()
        return []


async def main():
    semaphore = asyncio.Semaphore(CONCURRENCY)
    all_urls = set()

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)

        with open(OUTPUT_FILE, "a") as f:
            for brand in BRANDS:
                print(f"\nScraping brand: {brand}")
                tasks = [
                    get_listing_urls(semaphore, browser, brand, page_number)
                    for page_number in range(1, MAX_PAGES + 1)
                ]
                results = await asyncio.gather(*tasks)

                for urls in results:
                    new_urls = [u for u in urls if u not in all_urls]
                    all_urls.update(new_urls)
                    for url in new_urls:
                        f.write(url + "\n")

                print(f"  Brand done | Total: {len(all_urls)}")

        await browser.close()

    print(f"\nDone. Saved {len(all_urls)} unique URLs to {OUTPUT_FILE}")


asyncio.run(main())