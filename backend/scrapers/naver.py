import os
import httpx
from .base import BaseScraper, SearchResult

# 네이버 쇼핑 검색 후 mallName으로 분류할 사이트 목록
MALL_FILTER = {
    "GS샵": ["GS샵", "GS SHOP", "gsshop", "GSSHOP"],
    "퀸잇": ["퀸잇", "Queenit", "queenit"],
    "네이버쇼핑": [],  # 빈 리스트 = 전체
}


class NaverScraper(BaseScraper):
    site_name = "네이버쇼핑"
    BASE_URL = "https://openapi.naver.com/v1/search/shop.json"

    def __init__(self):
        self.client_id = os.getenv("NAVER_CLIENT_ID", "")
        self.client_secret = os.getenv("NAVER_CLIENT_SECRET", "")

    def _has_credentials(self) -> bool:
        return bool(self.client_id and self.client_secret)

    async def _fetch(self, query: str, display: int = 100) -> list[dict]:
        """단일 쿼리로 네이버 쇼핑 API 호출"""
        if not self._has_credentials() or not query.strip():
            return []

        headers = {
            "X-Naver-Client-Id": self.client_id,
            "X-Naver-Client-Secret": self.client_secret,
        }
        params = {"query": query, "display": display, "sort": "asc"}

        async with httpx.AsyncClient(timeout=15) as client:
            try:
                resp = await client.get(self.BASE_URL, headers=headers, params=params)
                resp.raise_for_status()
                data = resp.json()
                return data.get("items", [])
            except Exception:
                return []

    async def _search_with_fallback(self, query: str) -> list[SearchResult]:
        """검색어로 조회하고 결과 없으면 앞 단어 제거 후 재시도 (최대 2회)"""
        items = await self._fetch(query)

        # 결과가 없으면 단어 하나씩 제거하며 재시도 (단, 최소 2단어 이상 남아야 함)
        if not items:
            words = query.split()
            # 앞에서부터 단어 제거하며 재시도
            for drop in range(1, min(3, len(words) - 1)):
                shorter_query = " ".join(words[drop:])
                if len(shorter_query) < 4:
                    break
                items = await self._fetch(shorter_query)
                if items:
                    break

        return self._items_to_results(items, query)

    def _items_to_results(self, items: list, query: str) -> list[SearchResult]:
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
        return await self._search_with_fallback(product_number)

    async def search_by_name(self, product_name: str) -> list[SearchResult]:
        return await self._search_with_fallback(product_name)


class NaverGSScraper(BaseScraper):
    """네이버 쇼핑에서 GS샵 상품만 검색"""
    site_name = "GS샵"

    def _get_naver(self):
        return NaverScraper()

    def _filter(self, results: list[SearchResult]) -> list[SearchResult]:
        keywords = MALL_FILTER["GS샵"]
        filtered = [r for r in results if any(k.lower() in r.site.lower() for k in keywords)]
        for r in filtered:
            r.site = self.site_name
        return filtered

    async def search_by_number(self, product_number: str) -> list[SearchResult]:
        all_results = await self._get_naver()._search_with_fallback(product_number)
        return self._filter(all_results)

    async def search_by_name(self, product_name: str) -> list[SearchResult]:
        all_results = await self._get_naver()._search_with_fallback(product_name)
        return self._filter(all_results)


class NaverQueenItScraper(BaseScraper):
    """네이버 쇼핑에서 퀸잇 상품만 검색"""
    site_name = "퀸잇"

    def _get_naver(self):
        return NaverScraper()

    def _filter(self, results: list[SearchResult]) -> list[SearchResult]:
        keywords = MALL_FILTER["퀸잇"]
        filtered = [r for r in results if any(k.lower() in r.site.lower() for k in keywords)]
        for r in filtered:
            r.site = self.site_name
        return filtered

    async def search_by_number(self, product_number: str) -> list[SearchResult]:
        all_results = await self._get_naver()._search_with_fallback(product_number)
        return self._filter(all_results)

    async def search_by_name(self, product_name: str) -> list[SearchResult]:
        all_results = await self._get_naver()._search_with_fallback(product_name)
        return self._filter(all_results)
