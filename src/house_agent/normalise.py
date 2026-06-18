from __future__ import annotations

import hashlib
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


SPACE_RE = re.compile(r"\s+")
NON_WORD_RE = re.compile(r"[^a-z0-9]+")
POSTCODE_RE = re.compile(r"\b(G\d{1,2})\s*([0-9][A-Z]{2})?\b", re.IGNORECASE)


def collapse_spaces(value: str | None) -> str:
    if not value:
        return ""
    return SPACE_RE.sub(" ", value).strip()


def normalize_text(value: str | None) -> str:
    return collapse_spaces(value).lower()


def normalize_slug(value: str | None, max_len: int = 80) -> str:
    normalized = NON_WORD_RE.sub(" ", normalize_text(value))
    words = [
        word
        for word in normalized.split()
        if word
        and word
        not in {
            "glasgow",
            "flat",
            "apartment",
            "property",
            "rent",
            "to",
            "let",
            "pcm",
            "per",
            "month",
            "bed",
            "bedroom",
            "bedrooms",
        }
    ]
    return "-".join(words)[:max_len] or "listing"


def canonical_url(url: str) -> str:
    parts = urlsplit(url)
    keep_params = []
    for key, value in parse_qsl(parts.query, keep_blank_values=False):
        key_l = key.lower()
        if key_l.startswith("utm_") or key_l in {"gclid", "fbclid", "msclkid"}:
            continue
        keep_params.append((key, value))
    query = urlencode(sorted(keep_params))
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, query, ""))


def extract_postcode(text: str | None) -> str | None:
    if not text:
        return None
    match = POSTCODE_RE.search(text.upper())
    if not match:
        return None
    outward = match.group(1).upper()
    inward = match.group(2)
    if inward:
        return f"{outward} {inward.upper()}"
    return outward


def postcode_outward(postcode: str | None) -> str | None:
    if not postcode:
        return None
    match = POSTCODE_RE.search(postcode.upper())
    if not match:
        return None
    return match.group(1).upper()


def source_id_from_url(url: str) -> str | None:
    path = urlsplit(url).path.rstrip("/")
    candidates = re.findall(r"(\d{5,})", path)
    if candidates:
        return candidates[-1]
    if path:
        return hashlib.sha1(path.encode("utf-8")).hexdigest()[:12]
    return None


def dedupe_key(
    *,
    title: str,
    url: str,
    price_pcm: int | None,
    bedrooms: float | None,
    postcode: str | None,
    area: str | None,
    zone_hint: str | None,
) -> str:
    location = postcode or zone_hint or area or "unknown-location"
    beds = str(bedrooms or "unknown-beds")
    title_key = normalize_slug(title)
    raw = "|".join([location.upper(), beds, title_key])
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()
