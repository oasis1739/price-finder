import re
from playwright.async_api import async_playwright
from .base import BaseScraper, SearchResult


class GSShopScraper(BaseScraper):
    site_name = "GS샵"
    SEARCH_URL = "https://www.gsshop.com/search/search.gs?keyword={query}&lseq=gnb-search"

    async def _search(self, query: str) -> list[SearchResult]:
        url = self.SEARCH_URL.format(query=query)
        results = []
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
                page = await browser.new_page(user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
                await page.goto(url, wait_until="domcontentloaded", timeout=20000)
                await page.wait_for_timeout(2000)

                items = await page.query_selector_all(".prd-list li, .product-item, [class*='prd-item']")
                for item in items[:5]:
                    try:
                        name_el = await item.query_selector(".prd-name, .name")
                        price_el = await item.query_selector(".sell-price, .price strong, [class*='price']")
                        link_el = await item.query_selector("a")
                        img_el = await item.query_selector("img")

                        if not (name_el and price_el and link_el):
                            continue

                        name = await name_el.inner_text()
                        price_text = await price_el.inner_text()
                        price = int(re.sub(r"[^\d]", "", price_text) or 0)
                        href = await link_el.get_attribute("href") or ""
                        if href.startswith("/"):
                            href = "https://www.gsshop.com" + href
                        img = await img_el.get_attribute("src") if img_el else ""

                        if price > 0:
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
