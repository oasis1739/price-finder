import httpx
import re
from .base import BaseScraper, SearchResult

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "Accept-Language": "ko-KR,ko;q=0.9",
    "Referer": "https://www.fashionplus.co.kr/",
}

FETCH_URL = "https://www.fashionplus.co.kr/search/goods/fetch"
GOODS_BASE = "https://www.fashionplus.co.kr/goods/detail/{id}"


class FashionPlusScraper(BaseScraper):
    site_name = "패션플러스"

    async def _search(self, query: str) -> list[SearchResult]:
        params = {
            "searchWord": query,
            "category1Id": "", "category2Id": "", "category3Id": "",
            "benefits": "", "brands": "", "andSearchWord": "",
            "sort": "recommend", "minPrice": 0, "maxPrice": 0,
            "page": 1, "pageSize": 10,
        }
        async with httpx.AsyncClient(headers=HEADERS, timeout=20, follow_redirects=True) as client:
            try:
                resp = await client.get(FETCH_URL, params=params)
                resp.raise_for_status()
                data = resp.json()
            except Exception:
                return []

        items = data.get("goodsPaginator", {}).get("items", [])
        results = []

        for item in items[:5]:
            try:
                name = item.get("name", "")
                price = int(item.get("displayPrice") or item.get("salePrice") or 0)
                goods_id = item.get("id", "")
                img = item.get("mainImageUrl") or item.get("thumbnailUrl") or ""

                is_free = item.get("isFreeDelivery", True)
                shipping = 0 if is_free else 3000

                if price > 0 and name:
                    results.append(SearchResult(
                        site=self.site_name,
                        product_name=name,
                        product_number=query,
                        price=price,
                        shipping_fee=shipping,
                        total_price=price + shipping,
                        url=GOODS_BASE.format(id=goods_id),
                        image_url=img,
                    ))
            except Exception:
                continue

        return results

    async def search_by_number(self, product_number: str) -> list[SearchResult]:
        return await self._search(product_number)

    async def search_by_name(self, product_name: str) -> list[SearchResult]:
        return await self._search(product_name)
