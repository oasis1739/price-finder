import os
import httpx
from .base import BaseScraper, SearchResult

MALL_FILTER = {
    "GS샵": ["GS샵", "GS SHOP", "gsshop", "GSSHOP"],
    "퀸잇": ["퀸잇", "Queenit", "queenit"],
}


class NaverScraper(BaseScraper):
    site_name = "네이버쇼핑"
    BASE_URL = "https://openapi.naver.com/v1/search/shop.json"

    def __init__(self):
        self.client_id = os.getenv("NAVER_CLIENT_ID", "")
        self.client_secret = os.getenv("NAVER_CLIENT_SECRET", "")

    def _has_credentials(self) -> bool:
        return bool(self.client_id and self.client_secret)

    async def _fetch(self, query: str, display: int = 20, sort: str = "sim") -> list[dict]:
        if not self._has_credentials() or not query.strip():
            return []
        headers = {
            "X-Naver-Client-Id": self.client_id,
            "X-Naver-Client-Secret": self.client_secret,
        }
        params = {"query": query, "display": display, "sort": sort}
        async with httpx.AsyncClient(timeout=15) as client:
            try:
                resp = await client.get(self.BASE_URL, headers=headers, params=params)
                resp.raise_for_status()
                return resp.json().get("items", [])
            except Exception:
                return []

    def _to_results(self, items: list, query: str) -> list[SearchResult]:
        results = []
        for item in items:
            try:
                price = int(item.get("lprice", 0))
                mall_name = item.get("mallName", "")
                results.append(SearchResult(
                    site=f"네이버({mall_name})" if mall_name else "네이버쇼핑",
                    product_name=item.get("title", "").replace("<b>", "").replace("</b>", ""),
                    product_number=query,
                    price=price,
                    shipping_fee=0,
                    total_price=price,
                    url=item.get("link", ""),
                    image_url=item.get("image", ""),
                ))
            except (ValueError, KeyError):
                continue
        return results

    async def search_by_number(self, product_number: str) -> list[SearchResult]:
        # 네이버쇼핑 일반: 연관도순 상위 20개
        items = await self._fetch(product_number, display=20, sort="sim")
        return self._to_results(items, product_number)

    async def search_by_name(self, product_name: str) -> list[SearchResult]:
        # 네이버쇼핑 일반: 연관도순 상위 20개
        items = await self._fetch(product_name, display=20, sort="sim")
        return self._to_results(items, product_name)


class NaverMallScraper(BaseScraper):
    """특정 쇼핑몰 상품만 네이버에서 검색하는 기반 클래스"""
    site_name = ""
    mall_keywords: list = []

    def __init__(self):
        self._naver = NaverScraper()

    def _filter(self, results: list[SearchResult]) -> list[SearchResult]:
        keywords = self.mall_keywords
        filtered = [r for r in results if any(k.lower() in r.site.lower() for k in keywords)]
        for r in filtered:
            r.site = self.site_name
        return filtered

    async def _search_mall(self, query: str) -> list[SearchResult]:
        """0건이면 앞 단어 제거 후 재시도 (최대 2회), 결과는 해당 몰만 필터"""
        # 1차: 정확한 쿼리로 100개 검색
        items = await self._naver._fetch(query, display=100, sort="sim")
        all_results = self._naver._to_results(items, query)
        filtered = self._filter(all_results)

        # 결과 없으면 앞 단어 제거 후 재시도
        if not filtered:
            words = query.split()
            for drop in range(1, min(3, len(words) - 1)):
                shorter = " ".join(words[drop:])
                if len(shorter) < 3:
                    break
                items = await self._naver._fetch(shorter, display=100, sort="sim")
                all_results = self._naver._to_results(items, query)
                filtered = self._filter(all_results)
                if filtered:
                    break

        return filtered

    async def search_by_number(self, product_number: str) -> list[SearchResult]:
        return await self._search_mall(product_number)

    async def search_by_name(self, product_name: str) -> list[SearchResult]:
        return await self._search_mall(product_name)


class NaverGSScraper(NaverMallScraper):
    site_name = "GS샵"
    mall_keywords = ["GS샵", "GS SHOP", "gsshop", "GSSHOP"]


class NaverQueenItScraper(NaverMallScraper):
    site_name = "퀸잇"
    mall_keywords = ["퀸잇", "Queenit", "queenit"]
