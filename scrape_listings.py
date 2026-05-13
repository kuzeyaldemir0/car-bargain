import asyncio
import csv
import os
from urllib.parse import urlparse
from bs4 import BeautifulSoup
import httpx

INPUT_FILE = "urls.txt"
OUTPUT_FILE = "cars.csv"
FAILED_FILE = "failed_urls.txt"
UNAVAILABLE_FILE = "unavailable_urls.txt"

CONCURRENCY = 100
REQUESTS_PER_MINUTE = 450
REQUEST_TIMEOUT = 12
MAX_RETRIES = 3
WRITE_BATCH_SIZE = 100

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
    "Cache-Control": "no-cache",
}

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


def has_listing_data(data):
    return bool(data.get("price") or data.get("brand") or data.get("model"))


def is_listing_detail_url(url):
    return urlparse(str(url)).path.startswith("/ilan/")


class RateLimiter:
    def __init__(self, max_requests, period):
        self.interval = period / max_requests
        self.next_request_at = 0
        self.lock = asyncio.Lock()

    async def wait(self):
        async with self.lock:
            loop = asyncio.get_running_loop()
            now = loop.time()
            wait_for = max(0, self.next_request_at - now)
            self.next_request_at = max(now, self.next_request_at) + self.interval

        if wait_for:
            await asyncio.sleep(wait_for)


async def fetch_listing(client, limiter, url):
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            await limiter.wait()
            response = await client.get(url)
            if response.status_code in {404, 410}:
                return None, "unavailable"
            response.raise_for_status()

            if not is_listing_detail_url(response.url):
                return None, "unavailable"

            data = parse_listing(response.text, url)
            if not has_listing_data(data):
                raise ValueError("listing markers not found in response")

            return data, None
        except Exception:
            await asyncio.sleep(min(2 ** attempt, 10))

    return None, "failed"


async def flush_rows(batch, csvfile, writer, write_lock, counters):
    if not batch:
        return

    async with write_lock:
        writer.writerows(batch)
        csvfile.flush()
        counters["written"] += len(batch)
    batch.clear()


async def write_failed_url(url, failedfile, failure_lock, counters):
    async with failure_lock:
        failedfile.write(url + "\n")
        failedfile.flush()
        counters["failed"] += 1


async def write_unavailable_url(url, unavailablefile, unavailable_lock, counters):
    async with unavailable_lock:
        unavailablefile.write(url + "\n")
        unavailablefile.flush()
        counters["unavailable"] += 1


async def worker(
    queue,
    client,
    limiter,
    csvfile,
    failedfile,
    unavailablefile,
    writer,
    write_lock,
    failure_lock,
    unavailable_lock,
    counters,
):
    batch = []

    try:
        while True:
            url = await queue.get()
            try:
                if url is None:
                    break

                data, error_type = await fetch_listing(client, limiter, url)
                if data:
                    batch.append(data)
                elif error_type == "unavailable":
                    await write_unavailable_url(url, unavailablefile, unavailable_lock, counters)
                else:
                    await write_failed_url(url, failedfile, failure_lock, counters)

                counters["processed"] += 1
                if counters["processed"] % 100 == 0:
                    print(
                        f"[{counters['processed']}/{counters['total']}] processed | "
                        f"{counters['written']} written | "
                        f"{counters['unavailable']} unavailable | "
                        f"{counters['failed']} failed"
                    )

                if len(batch) >= WRITE_BATCH_SIZE:
                    await flush_rows(batch, csvfile, writer, write_lock, counters)
            finally:
                queue.task_done()
    finally:
        await flush_rows(batch, csvfile, writer, write_lock, counters)


async def main():
    with open(INPUT_FILE) as f:
        urls = list(dict.fromkeys(line.strip() for line in f if line.strip()))

    scraped = set()
    if os.path.exists(OUTPUT_FILE):
        with open(OUTPUT_FILE, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                scraped.add(row["url"])

    urls = [u for u in urls if u not in scraped]
    print(f"Resuming: {len(scraped)} already scraped, {len(urls)} remaining")
    print(
        f"HTTP scraper: concurrency={CONCURRENCY}, "
        f"limit={REQUESTS_PER_MINUTE}/minute, retries={MAX_RETRIES}"
    )

    if not urls:
        print(f"Done. Saved to {OUTPUT_FILE}")
        return

    queue = asyncio.Queue()
    for url in urls:
        queue.put_nowait(url)

    file_exists = os.path.exists(OUTPUT_FILE) and os.path.getsize(OUTPUT_FILE) > 0
    limits = httpx.Limits(max_connections=CONCURRENCY, max_keepalive_connections=CONCURRENCY)
    timeout = httpx.Timeout(REQUEST_TIMEOUT)
    limiter = RateLimiter(REQUESTS_PER_MINUTE, 60)
    write_lock = asyncio.Lock()
    failure_lock = asyncio.Lock()
    unavailable_lock = asyncio.Lock()
    counters = {
        "processed": 0,
        "written": 0,
        "unavailable": 0,
        "failed": 0,
        "total": len(urls),
    }

    with (
        open(OUTPUT_FILE, "a", newline="", encoding="utf-8") as csvfile,
        open(FAILED_FILE, "w", encoding="utf-8") as failedfile,
        open(UNAVAILABLE_FILE, "w", encoding="utf-8") as unavailablefile,
    ):
        writer = csv.DictWriter(csvfile, fieldnames=FIELDS)
        if not file_exists:
            writer.writeheader()

        async with httpx.AsyncClient(
            headers=HEADERS,
            follow_redirects=True,
            limits=limits,
            timeout=timeout,
        ) as client:
            tasks = [
                asyncio.create_task(
                    worker(
                        queue,
                        client,
                        limiter,
                        csvfile,
                        failedfile,
                        unavailablefile,
                        writer,
                        write_lock,
                        failure_lock,
                        unavailable_lock,
                        counters,
                    )
                )
                for i in range(min(CONCURRENCY, len(urls)))
            ]

            try:
                await queue.join()
            except asyncio.CancelledError:
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                raise
            else:
                for _ in tasks:
                    queue.put_nowait(None)
                await asyncio.gather(*tasks, return_exceptions=True)

    if counters["failed"]:
        print(f"Saved {counters['failed']} failed URLs to {FAILED_FILE}")
    if counters["unavailable"]:
        print(f"Saved {counters['unavailable']} unavailable URLs to {UNAVAILABLE_FILE}")

    print(f"Done. Saved to {OUTPUT_FILE}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print(
            f"\nInterrupted. Completed rows are in {OUTPUT_FILE}; "
            f"failed URLs so far are in {FAILED_FILE}; "
            f"unavailable URLs so far are in {UNAVAILABLE_FILE}."
        )
