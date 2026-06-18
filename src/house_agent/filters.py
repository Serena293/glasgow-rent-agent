from __future__ import annotations

from .models import FilterDecision, Listing
from .normalise import dedupe_key, extract_postcode, normalize_text, postcode_outward


def apply_filters(listing: Listing, criteria: dict) -> FilterDecision:
    text = normalize_text(" ".join([listing.title, listing.description, listing.area or "", listing.postcode or ""]))
    reasons: list[str] = []
    notes: list[str] = []

    if listing.price_pcm is None:
        reasons.append("missing price")
    elif listing.price_pcm > int(criteria.get("max_price_pcm", 10**9)):
        reasons.append(f"price over max: {listing.price_pcm}")
    else:
        notes.append(f"price <= GBP {criteria.get('max_price_pcm')}")

    min_bedrooms = float(criteria.get("min_bedrooms", 1))
    if listing.bedrooms is None:
        reasons.append("missing bedrooms")
    elif listing.bedrooms < min_bedrooms:
        reasons.append(f"bedrooms below min: {listing.bedrooms}")
    else:
        notes.append(f"{listing.bedrooms:g}+ bedroom")

    if not matches_property_kind(text, criteria.get("property_kinds", [])):
        reasons.append("not clearly a flat/apartment")

    furnishing_decision = matches_furnishing(listing, text, criteria.get("furnishing", {}))
    if furnishing_decision:
        notes.append(furnishing_decision)
    else:
        reasons.append("not furnished or part-furnished")

    exclude_hit = first_keyword_hit(text, criteria.get("exclude_keywords", []))
    if exclude_hit:
        reasons.append(f"excluded keyword: {exclude_hit}")

    location_note = matches_location(listing, criteria.get("allowed_locations", {}))
    if location_note:
        notes.append(location_note)
    else:
        reasons.append("outside configured postcodes/areas")

    accepted = not reasons
    if accepted:
        ensure_dedupe_key(listing)
    return FilterDecision(accepted=accepted, reasons=reasons, notes=notes)


def ensure_dedupe_key(listing: Listing) -> str:
    if not listing.postcode:
        listing.postcode = extract_postcode(" ".join([listing.title, listing.description, listing.area or ""]))
    listing.dedupe_key = dedupe_key(
        title=listing.title,
        url=listing.url,
        price_pcm=listing.price_pcm,
        bedrooms=listing.bedrooms,
        postcode=listing.postcode,
        area=listing.area,
        zone_hint=listing.zone_hint,
    )
    return listing.dedupe_key


def matches_property_kind(text: str, kinds: list[str]) -> bool:
    if any(block in text for block in [" room ", " house share", " flat share", " flatshare", " shared "]):
        return False
    wanted = {kind.lower() for kind in kinds}
    if "flat" in wanted and "flat" in text:
        return True
    if "apartment" in wanted and "apartment" in text:
        return True
    return False


def matches_furnishing(listing: Listing, text: str, furnishing_cfg: dict) -> str | None:
    accepted = {normalize_text(item) for item in furnishing_cfg.get("accepted", [])}
    furnishing = normalize_text(listing.furnished)
    if "unfurnished" in text or furnishing == "unfurnished":
        return None
    if "part furnished" in text or "part-furnished" in text or furnishing == "part-furnished":
        return "part-furnished"
    if "furnished" in text or furnishing == "furnished":
        return "furnished"
    if furnishing and furnishing in accepted:
        return furnishing
    if furnishing_cfg.get("reject_unknown", True):
        return None
    return "furnishing unknown"


def first_keyword_hit(text: str, keywords: list[str]) -> str | None:
    padded = f" {text} "
    for keyword in keywords:
        keyword_norm = normalize_text(keyword)
        if keyword_norm and keyword_norm in padded:
            return keyword
    return None


def matches_location(listing: Listing, allowed_locations: dict) -> str | None:
    postcodes = [normalize_text(code).upper() for code in allowed_locations.get("postcodes", [])]
    area_terms = [normalize_text(term) for term in allowed_locations.get("area_terms", [])]
    haystack = normalize_text(" ".join([listing.title, listing.description, listing.area or "", listing.zone_hint or ""]))
    postcode = listing.postcode or extract_postcode(haystack)
    if postcode:
        postcode_norm = postcode.upper()
        outward = postcode_outward(postcode_norm)
        for allowed in postcodes:
            if " " in allowed:
                if postcode_norm.startswith(allowed):
                    return f"postcode {allowed}"
            elif outward == allowed:
                return f"postcode {allowed}"
        return None
    if listing.zone_hint:
        zone_hint = normalize_text(listing.zone_hint).upper()
        if zone_hint in postcodes:
            return f"search zone {zone_hint}"
    for term in area_terms:
        if term and term in haystack:
            return f"area {term}"
    return None
