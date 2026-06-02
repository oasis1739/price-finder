from .naver import NaverScraper, NaverGSScraper, NaverQueenItScraper
from .fashionplus import FashionPlusScraper

ALL_SCRAPERS = [
    NaverScraper,
    NaverGSScraper,
    NaverQueenItScraper,
    FashionPlusScraper,
]

SCRAPER_MAP = {s.site_name: s for s in ALL_SCRAPERS}
