from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urljoin

from ..models import Listing
from ..normalise import canonical_url, collapse_spaces, extract_postcode, source_id_from_url


PRICE_RE = re.compile(r"£\s*([0-9][0-9,]*)\s*(?:pcm|per\s+month|pm|p/m)?", re.IGNORECASE)
BEDS_RE = re.compile(r"\b([0-9]+(?:\.[0-9])?)\s*(?:bed|beds|bedroom|bedrooms|br)\b", re.IGNORECASE)
FURNISHED_RE = re.compile(r"\b(part[-\s]?furnished|unfurnished|furnished)\b", re.IGNORECASE)


class GenericSource:
    def __init__(self, *, name: str, config: dict, runtime_config: dict):
        self.name = name
        self.config = config
        self.runtime = runtime_config

    def fetch(self) -> list[Listing]:
        try:
            import requests
            from bs4 import BeautifulSoup
        except ImportError as exc:
            raise RuntimeError("Install dependencies first: python -m pip install -e .") from exc

        headers = {"User-Agent": self.runtime.get("user_agent", "GlasgowRentAgent/0.1")}
        timeout = int(self.runtime.get("request_timeout_seconds", 20))
        listings: list[Listing] = []
        seen_urls: set[str] = set()
        for search in self.config.get("searches", []):
            response = requests.get(search["url"], headers=headers, timeout=timeout)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "html.parser")
            page_listings = self._parse_search_page(soup, search["url"], search)
            if self.runtime.get("fetch_detail_pages", True):
                page_listings = self._enrich_detail_pages(
                    requests=requests,
                    headers=headers,
                    timeout=timeout,
                    listings=page_listings,
                    max_pages=int(self.runtime.get("max_detail_pages_per_search", 20)),
                )
            for listing in page_listings:
                url = canonical_url(listing.url)
                if url in seen_urls:
                    continue
                seen_urls.add(url)
                listings.append(listing)
        return listings

    def _parse_search_page(self, soup, base_url: str, search: dict) -> list[Listing]:
        listings = self._parse_json_ld(soup, base_url, search)
        listings.extend(self._parse_cards(soup, base_url, search))
        limit = int(self.runtime.get("max_search_results_per_search", 25))
        return listings[:limit]

    def _parse_json_ld(self, soup, base_url: str, search: dict) -> list[Listing]:
        found: list[Listing] = []
        for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
            raw = script.string or script.get_text(" ", strip=True)
            if not raw:
                continue
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                continue
            for item in iter_json_ld_items(data):
                listing = self._listing_from_json_ld(item, base_url, search)
                if listing:
                    found.append(listing)
        return found

    def _listing_from_json_ld(self, item: dict[str, Any], base_url: str, search: dict) -> Listing | None:
        url = item.get("url") or item.get("@id")
        name = item.get("name") or item.get("headline")
        if not url or not name:
            return None
        offer = item.get("offers") or {}
        if isinstance(offer, list):
            offer = offer[0] if offer else {}
        price = parse_price(str(offer.get("price") or item.get("price") or ""))
        address = item.get("address") or {}
        address_text = json.dumps(address) if isinstance(address, dict) else str(address)
        description = collapse_spaces(item.get("description") or "")
        full_text = " ".join([name, description, address_text])
        return Listing(
            source=self.name,
            source_listing_id=source_id_from_url(str(url)),
            url=urljoin(base_url, str(url)),
            title=collapse_spaces(str(name)),
            price_pcm=price or parse_price(full_text),
            bedrooms=parse_bedrooms(full_text),
            postcode=extract_postcode(full_text),
            area=collapse_spaces(address_text) or search.get("zone_hint"),
            furnished=parse_furnishing(full_text),
            image_url=parse_image(item.get("image")),
            description=description,
            search_name=search.get("name"),
            zone_hint=search.get("zone_hint"),
            fetched_at=datetime.now(timezone.utc),
            raw={"json_ld": item, "search": search.get("name")},
        )

    def _parse_cards(self, soup, base_url: str, search: dict) -> list[Listing]:
        listings: list[Listing] = []
        anchors = soup.select("a.search-property-card[href]")
        if not anchors:
            anchors = soup.find_all("a", href=True)
        for anchor in anchors:
            href = str(anchor.get("href"))
            if not looks_like_listing_url(href):
                continue
            card = nearest_card(anchor)
            text = collapse_spaces(card.get_text(" ", strip=True) if card else anchor.get_text(" ", strip=True))
            if len(text) < 20:
                continue
            title = extract_title(card, anchor) or text[:100]
            url = urljoin(base_url, href)
            listing = Listing(
                source=self.name,
                source_listing_id=source_id_from_url(url),
                url=url,
                title=title,
                price_pcm=parse_price(text),
                bedrooms=parse_bedrooms(text),
                postcode=extract_postcode(text),
                area=search.get("zone_hint"),
                furnished=parse_furnishing(text),
                image_url=extract_image(card, base_url) if card else None,
                description=text[:1200],
                search_name=search.get("name"),
                zone_hint=search.get("zone_hint"),
                fetched_at=datetime.now(timezone.utc),
                raw={"search": search.get("name"), "card_text": text[:2000]},
            )
            listings.append(listing)
        return dedupe_by_url(listings)

    def _enrich_detail_pages(self, *, requests, headers: dict, timeout: int, listings: list[Listing], max_pages: int):
        enriched: list[Listing] = []
        for index, listing in enumerate(listings):
            if index >= max_pages:
                enriched.append(listing)
                continue
            try:
                response = requests.get(listing.url, headers=headers, timeout=timeout)
                response.raise_for_status()
            except Exception as exc:  # Network/site failure should not kill the whole run.
                listing.raw["detail_error"] = str(exc)
                enriched.append(listing)
                continue
            try:
                from bs4 import BeautifulSoup
            except ImportError:
                enriched.append(listing)
                continue
            soup = BeautifulSoup(response.text, "html.parser")
            detail_text = collapse_spaces(soup.get_text(" ", strip=True))
            meta_description = meta_content(soup, "description") or meta_content(soup, "og:description")
            meta_title = meta_content(soup, "og:title") or meta_content(soup, "title")
            if meta_title and len(meta_title) > len(listing.title):
                listing.title = collapse_spaces(meta_title)
            listing.description = collapse_spaces(" ".join([meta_description or "", detail_text[:1800]]))[:2200]
            listing.price_pcm = listing.price_pcm or parse_price(detail_text)
            listing.bedrooms = listing.bedrooms or parse_bedrooms(detail_text)
            listing.postcode = listing.postcode or extract_postcode(detail_text)
            listing.furnished = listing.furnished or parse_furnishing(detail_text)
            listing.image_url = listing.image_url or meta_content(soup, "og:image")
            listing.raw["detail_fetched"] = True
            enriched.append(listing)
        return enriched


def iter_json_ld_items(data: Any):
    if isinstance(data, list):
        for item in data:
            yield from iter_json_ld_items(item)
    elif isinstance(data, dict):
        if "itemListElement" in data:
            yield from iter_json_ld_items(data["itemListElement"])
        elif "item" in data and isinstance(data["item"], dict):
            yield data["item"]
        else:
            type_value = data.get("@type")
            type_text = " ".join(type_value) if isinstance(type_value, list) else str(type_value)
            if any(word in type_text.lower() for word in ["apartment", "house", "residence", "product", "offer"]):
                yield data


def looks_like_listing_url(href: str) -> bool:
    href_l = href.lower()
    if href_l.startswith("#") or "javascript:" in href_l or "mailto:" in href_l:
        return False
    positive = [
        "property",
        "properties",
        "to-rent",
        "rent",
        "letting",
        "flats-for-rent",
        "details",
    ]
    negative = ["login", "sign", "privacy", "terms", "contact", "valuation", "mortgage", "commercial"]
    return any(token in href_l for token in positive) and not any(token in href_l for token in negative)


def nearest_card(anchor):
    for parent in anchor.parents:
        if getattr(parent, "name", None) in {"article", "li"}:
            return parent
        attrs = getattr(parent, "attrs", {})
        class_text = " ".join(attrs.get("class", [])) if isinstance(attrs.get("class"), list) else str(attrs.get("class", ""))
        testid = str(attrs.get("data-testid", ""))
        if any(token in (class_text + " " + testid).lower() for token in ["card", "listing", "property", "result"]):
            return parent
    return anchor.parent


def extract_title(card, anchor) -> str:
    if card:
        img = card.find("img")
        if img and img.get("alt"):
            alt = collapse_spaces(str(img.get("alt")))
            if alt:
                return alt[:180]
        for selector in ["h1", "h2", "h3", "[data-testid*=title]", "[class*=title]"]:
            found = card.select_one(selector)
            if found:
                text = collapse_spaces(found.get_text(" ", strip=True))
                if text:
                    return text[:180]
    return collapse_spaces(anchor.get_text(" ", strip=True))[:180]


def extract_image(card, base_url: str) -> str | None:
    if not card:
        return None
    img = card.find("img")
    if not img:
        return None
    src = img.get("src") or img.get("data-src") or img.get("data-lazy")
    if not src:
        return None
    return urljoin(base_url, str(src))


def parse_image(value) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, list) and value:
        first = value[0]
        if isinstance(first, str):
            return first
        if isinstance(first, dict):
            return first.get("url")
    if isinstance(value, dict):
        return value.get("url")
    return None


def parse_price(text: str) -> int | None:
    match = PRICE_RE.search(text or "")
    if not match:
        return None
    return int(match.group(1).replace(",", ""))


def parse_bedrooms(text: str) -> float | None:
    match = BEDS_RE.search(text or "")
    if not match:
        return None
    return float(match.group(1))


def parse_furnishing(text: str) -> str | None:
    match = FURNISHED_RE.search(text or "")
    if not match:
        return None
    value = match.group(1).lower().replace(" ", "-")
    if value == "part-furnished":
        return "part-furnished"
    return value


def meta_content(soup, name: str) -> str | None:
    selectors = [
        {"name": name},
        {"property": name},
    ]
    for attrs in selectors:
        tag = soup.find("meta", attrs=attrs)
        if tag and tag.get("content"):
            return collapse_spaces(str(tag.get("content")))
    if name == "title" and soup.title:
        return collapse_spaces(soup.title.get_text(" ", strip=True))
    return None


def dedupe_by_url(listings: list[Listing]) -> list[Listing]:
    seen: set[str] = set()
    result: list[Listing] = []
    for listing in listings:
        url = canonical_url(listing.url)
        if url in seen:
            continue
        seen.add(url)
        result.append(listing)
    return result
