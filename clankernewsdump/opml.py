"""OPML import/export for RSS feed subscriptions."""
from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

from .sources import RSS_FEEDS


def export_opml(path: str | Path) -> int:
    """Export all RSS feeds as OPML. Returns count of feeds exported."""
    path = Path(path)
    opml = ET.Element("opml", version="2.0")
    head = ET.SubElement(opml, "head")
    ET.SubElement(head, "title").text = "clankernewsdump feeds"
    body = ET.SubElement(opml, "body")

    # Group by category
    cats: dict[str, list[tuple[str, str]]] = {}
    for name, url, category in RSS_FEEDS:
        cats.setdefault(category, []).append((name, url))

    count = 0
    for cat, feeds in sorted(cats.items()):
        outline = ET.SubElement(body, "outline", text=cat, title=cat)
        for name, url in feeds:
            ET.SubElement(
                outline, "outline",
                type="rss",
                text=name,
                title=name,
                xmlUrl=url,
                category=cat,
            )
            count += 1

    tree = ET.ElementTree(opml)
    ET.indent(tree, space="  ")
    tree.write(path, xml_declaration=True, encoding="utf-8")
    return count


def import_opml(path: str | Path) -> list[dict[str, str]]:
    """Import feeds from OPML. Returns list of {name, url, category} dicts.

    These can be added to config.toml as extra_feeds.
    """
    path = Path(path)
    tree = ET.parse(path)
    root = tree.getroot()
    feeds: list[dict[str, str]] = []

    def _walk(element: ET.Element, parent_cat: str = "blog"):
        for outline in element.findall("outline"):
            xml_url = outline.get("xmlUrl")
            if xml_url:
                feeds.append({
                    "name": outline.get("title") or outline.get("text") or "Untitled",
                    "url": xml_url,
                    "category": outline.get("category") or parent_cat,
                })
            else:
                # Folder node — use its text as category hint
                cat = outline.get("text") or outline.get("title") or parent_cat
                _walk(outline, cat)

    body = root.find("body")
    if body is not None:
        _walk(body)
    return feeds
