from dataclasses import dataclass
from datetime import datetime


@dataclass
class Item:
    source: str
    category: str  # blog, newsletter, lab, podcast, reddit, hn, arxiv
    title: str
    url: str
    published: datetime
    snippet: str = ""
    score: int = 0  # upvotes / points where applicable

    @property
    def key(self) -> str:
        return self.url
