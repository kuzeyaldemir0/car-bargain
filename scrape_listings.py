import asyncio
import random
import csv
import os
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup

INPUT_FILE = "urls.txt"
OUTPUT_FILE = "cars.csv"
CONCURRENCY = 20

FIELDS = ["url", "price", "brand", "series", "model", "year", "mileage",
          "transmission", "fuel", "body", "color", "engine", "hp", "drive",
          "condition", "heavy_damage", "paint_changed", "fuel_consumption",
          "fuel_tank", "trade_in", "seller_type"]

FIELD_MAP = {
    "Marka":               "brand",
    "Seri":                "series",
    "Model":               "model",
    "Yıl":                 "year",
    "Kilometre":           "mileage",
    "Vites Tipi":          "transmission",
    "Yakıt Tipi":          "fuel",
    "Kasa Tipi":           "body",
    "Renk":                "color",
    "Motor Hacmi":         "engine",
    "Motor Gücü":          "hp",
    "Çekiş":               "drive",
    "Araç Durumu":         "condition",
    "Ağır Hasarlı":        "heavy_damage",
    "Boya-değişen":        "paint_changed",
    "Ort. Yakıt Tüketimi": "fuel_consumption",
    "Yakıt Deposu":        "fuel_tank",
    "Takasa Uygun":        "trade_in",
    "Kimden":              "seller_type",
}


def parse_listing(html, url):
    soup = BeautifulSoup(html, "html.parser")
    data = {field: None for field in FIELDS}
    data["url"] = url

    for item in soup.find_all("div", class_="property-item"):
        key_el = item.find("div", class_="property-key")
        val_el = item.find("div", class_="property-value")
        if key_el and val_el:
            key = key_el.get_text(strip=True)
            val = val_el.get_text(strip=True)
            english_key = FIELD_MAP.get(key)
            if english_key:
                data[english_key] = val

    price_el = soup.select_one("[data-testid='desktop-information-price']")
    if price_el:
        data["price"] = price_el.get_text(strip=True)

    return data


async def scrape_url(semaphore, browser, url):
    async with semaphore:
        page = await browser.new_page()
        for attempt in range(3):
            try:
                await page.goto(url, timeout=8000)
                await page.wait_for_load_state("domcontentloaded")
                data = parse_listing(await page.content(), url)
                await asyncio.sleep(random.uniform(0.5, 1.5))
                await page.close()
                return data
            except Exception as e:
                print(f"  Attempt {attempt + 1} failed ({url}): {e}")
                await asyncio.sleep(5)
        await page.close()
        return None


async def main():
    with open(INPUT_FILE) as f:
        urls = [line.strip() for line in f if line.strip()]

    scraped = set()
    if os.path.exists(OUTPUT_FILE):
        with open(OUTPUT_FILE, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                scraped.add(row["url"])

    urls = [u for u in urls if u not in scraped]
    print(f"Resuming: {len(scraped)} already scraped, {len(urls)} remaining")

    semaphore = asyncio.Semaphore(CONCURRENCY)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)

        file_exists = os.path.exists(OUTPUT_FILE)
        with open(OUTPUT_FILE, "a", newline="", encoding="utf-8") as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=FIELDS)
            if not file_exists:
                writer.writeheader()

            tasks = [scrape_url(semaphore, browser, url) for url in urls]
            for i, coro in enumerate(asyncio.as_completed(tasks)):
                result = await coro
                if result:
                    writer.writerow(result)
                if (i + 1) % 100 == 0:
                    print(f"[{i + 1}/{len(urls)}] scraped")

        await browser.close()

    print(f"Done. Saved to {OUTPUT_FILE}")


asyncio.run(main())