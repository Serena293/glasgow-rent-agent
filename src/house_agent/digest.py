from __future__ import annotations

from datetime import datetime
from html import escape
from zoneinfo import ZoneInfo


def build_digest_html(listings: list[dict], *, mode: str, timezone_name: str, include_empty: bool) -> str:
    now = datetime.now(ZoneInfo(timezone_name))
    title = "Morning rent digest" if mode == "morning" else "Evening rent digest"
    rows = "".join(render_listing_card(item) for item in listings)
    if not listings and include_empty:
        rows = """
        <p style="margin: 16px 0; color: #475569;">
          No new matching listings since the last check.
        </p>
        """
    count = len(listings)
    return f"""<!doctype html>
<html>
  <body style="margin:0; padding:0; background:#f8fafc; color:#0f172a; font-family:Arial, sans-serif;">
    <main style="max-width:720px; margin:0 auto; padding:24px;">
      <h1 style="font-size:22px; margin:0 0 6px;">{escape(title)}</h1>
      <p style="margin:0 0 20px; color:#475569;">
        {count} matching listing{'s' if count != 1 else ''} · {escape(now.strftime('%d %b %Y, %H:%M'))}
      </p>
      {rows}
    </main>
  </body>
</html>"""


def build_digest_text(listings: list[dict], *, mode: str, include_empty: bool) -> str:
    title = "Morning rent digest" if mode == "morning" else "Evening rent digest"
    if not listings and include_empty:
        return f"{title}\n\nNo new matching listings since the last check."
    lines = [title, ""]
    for item in listings:
        reason = item.get("notification_reason", "new")
        lines.extend(
            [
                f"{item.get('title', 'Untitled')} ({reason})",
                f"GBP {item.get('last_price_pcm')} pcm - {item.get('bedrooms')} bed - {item.get('area') or item.get('postcode') or ''}",
                str(item.get("canonical_url")),
                "",
            ]
        )
    return "\n".join(lines)


def render_listing_card(item: dict) -> str:
    title = escape(str(item.get("title") or "Untitled listing"))
    url = escape(str(item.get("canonical_url") or "#"))
    price = escape(str(item.get("last_price_pcm") or item.get("price_pcm") or "?"))
    bedrooms = escape(format_bedrooms(item.get("bedrooms")))
    location = escape(str(item.get("postcode") or item.get("area") or "Glasgow"))
    source = escape(str(item.get("source") or "source"))
    reason = escape(reason_label(str(item.get("notification_reason") or "new")))
    furnishing = escape(str(item.get("furnished") or "furnished"))
    image = item.get("image_url")
    image_html = ""
    if image:
        image_html = f'<img src="{escape(str(image))}" alt="" style="width:110px; height:82px; object-fit:cover; border-radius:6px; margin-right:14px;">'
    price_drop_html = ""
    if item.get("notification_reason") == "price_drop" and item.get("last_sent_price_pcm"):
        price_drop_html = (
            f'<p style="margin:8px 0 0; color:#166534;">'
            f'Price drop: GBP {escape(str(item.get("last_sent_price_pcm")))} -> GBP {price}</p>'
        )
    return f"""
      <section style="background:#ffffff; border:1px solid #e2e8f0; border-radius:8px; padding:14px; margin:0 0 12px;">
        <div style="display:flex; gap:0;">
          {image_html}
          <div style="min-width:0;">
            <p style="margin:0 0 6px; color:#2563eb; font-size:12px; text-transform:uppercase; letter-spacing:.04em;">{reason}</p>
            <h2 style="font-size:17px; line-height:1.25; margin:0 0 8px;">
              <a href="{url}" style="color:#0f172a; text-decoration:none;">{title}</a>
            </h2>
            <p style="margin:0; color:#334155;">
              GBP {price} pcm · {bedrooms} · {location} · {furnishing} · {source}
            </p>
            {price_drop_html}
            <p style="margin:10px 0 0;"><a href="{url}" style="color:#2563eb;">Open listing</a></p>
          </div>
        </div>
      </section>
    """


def format_bedrooms(value) -> str:
    if value is None:
        return "? bed"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return f"{value} bed"
    if number.is_integer():
        number_text = str(int(number))
    else:
        number_text = str(number)
    return f"{number_text} bed"


def reason_label(reason: str) -> str:
    if reason == "price_drop":
        return "Price drop"
    if reason == "new":
        return "New listing"
    return reason.replace("_", " ").title()

