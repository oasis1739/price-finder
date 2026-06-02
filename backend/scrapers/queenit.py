import re
from playwright.async_api import async_playwright
from .base import BaseScraper, SearchResult


class QueenItScraper(BaseScraper):
    site_name = "퀸잇"
    SEARCH_URL = "https://web.queenit.kr/search?q={query}"

    async def _search(self, query: str) -> list[SearchResult]:
        url = self.SEARCH_URL.format(query=query)
        results = []
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
                page = await browser.new_page(user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36")
                await page.goto(url, wait_until="networkidle", timeout=25000)
                await page.wait_for_timeout(2000)

                items = await page.query_selector_all("[class*='ProductCard'], [class*='product-card'], [class*='item']")
                for item in items[:5]:
                    try:
                        name_el = await item.query_selector("[class*='name'], [class*='title'], h3, h4")
                        price_el = await item.query_selector("[class*='price'], [class*='Price']")
                        link_el = await item.query_selector("a")
                        img_el = await item.query_selector("img")

                        if not link_el:
                            continue

                        name = await name_el.inner_text() if name_el else ""
                        price_text = await price_el.inner_text() if price_el else "0"
                        price = int(re.sub(r"[^\d]", "", price_text) or 0)
                        href = await link_el.get_attribute("href") or ""
                        if href.startswith("/"):
                            href = "https://web.queenit.kr" + href
                        img = await img_el.get_attribute("src") if img_el else ""

                        if price > 0 and name:
                            results.append(SearchResult(
                                site=self.site_name,
                                product_name=name.strip(),
                                product_number=query,
                                price=price,
                                shipping_fee=0,
                                total_price=price,
                                url=href,
                                image_url=img or "",
                            ))
                    except Exception:
                        continue
                await browser.close()
        except Exception:
            pass
        return results

    async def search_by_number(self, product_number: str) -> list[SearchResult]:
        return await self._search(product_number)

    async def search_by_name(self, product_name: str) -> list[SearchResult]:
        return await self._search(product_name)
