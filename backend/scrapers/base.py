from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass
class SearchResult:
    site: str
    product_name: str
    product_number: str
    price: int
    shipping_fee: int
    total_price: int
    url: str
    image_url: Optional[str] = None
    matched_by: str = "name"  # "number" or "name"


class BaseScraper(ABC):
    site_name: str

    @abstractmethod
    async def search_by_number(self, product_number: str) -> list[SearchResult]:
        pass

    @abstractmethod
    async def search_by_name(self, product_name: str) -> list[SearchResult]:
        pass

    async def search(self, product_number: str, product_name: str) -> list[SearchResult]:
        results = []

        # 품번으로 먼저 검색
        if product_number:
            by_number = await self.search_by_number(product_number)
            for r in by_number:
                r.matched_by = "number"
            results.extend(by_number)

        # 상품명으로도 검색
        if product_name:
            by_name = await self.search_by_name(product_name)
            for r in by_name:
                r.matched_by = "name"
            results.extend(by_name)

        # 중복 제거 (같은 URL)
        seen = set()
        unique = []
        for r in results:
            if r.url not in seen:
                seen.add(r.url)
                unique.append(r)

        return sorted(unique, key=lambda x: x.total_price)
