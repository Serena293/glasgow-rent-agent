from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

from .config import load_config
from .digest import build_digest_html, build_digest_text
from .emailer import make_mailer
from .runner import baseline_current_listings, database_is_empty, fetch_filter_store, load_pending
from .storage import connect, init_db, mark_sent


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="house-agent")
    parser.add_argument("--config", default=None, help="Path to config.yaml")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("init-db", help="Create or update the local SQLite schema")
    baseline = subparsers.add_parser("baseline", help="Fetch current listings and mark them as already seen")
    add_run_options(baseline)
    check = subparsers.add_parser("check", help="Fetch listings and store new matches without sending email")
    add_run_options(check)
    subparsers.add_parser("show-pending", help="Show listings that would be emailed")

    morning = subparsers.add_parser("morning", help="Fetch and send the morning digest")
    morning.add_argument("--dry-run", action="store_true", help="Write HTML preview instead of sending")
    add_run_options(morning)

    evening = subparsers.add_parser("evening", help="Fetch and send the evening digest")
    evening.add_argument("--dry-run", action="store_true", help="Write HTML preview instead of sending")
    add_run_options(evening)

    scheduled = subparsers.add_parser("scheduled", help="Run morning before noon UTC, otherwise evening")
    scheduled.add_argument("--dry-run", action="store_true", help="Write HTML preview instead of sending")
    add_run_options(scheduled)

    email_test = subparsers.add_parser("email-test", help="Send a Gmail API test email")
    email_test.add_argument("--dry-run", action="store_true", help="Write HTML preview instead of sending")

    args = parser.parse_args(argv)
    config = load_config(args.config)

    if args.command == "init-db":
        with connect(config["app"]["database_url"]) as conn:
            init_db(conn)
        print("Database initialized.")
        return

    if args.command == "baseline":
        stats, marked = baseline_current_listings(
            config,
            source_filter=args.source,
            fetch_detail_pages=not args.no_detail,
            progress=print_progress,
        )
        print_stats(stats)
        print(f"Baseline complete. Marked {marked} listings as already seen.")
        return

    if args.command == "check":
        stats = fetch_filter_store(
            config,
            source_filter=args.source,
            fetch_detail_pages=not args.no_detail,
            progress=print_progress,
        )
        print_stats(stats)
        pending = load_pending(config)
        print(f"Pending email notifications: {len(pending)}")
        return

    if args.command == "show-pending":
        pending = load_pending(config)
        print_pending(pending)
        return

    if args.command == "email-test":
        send_test_email(config, dry_run=args.dry_run)
        return

    if args.command in {"morning", "evening"}:
        run_digest(
            config,
            mode=args.command,
            dry_run=args.dry_run,
            source_filter=args.source,
            fetch_detail_pages=not args.no_detail,
        )
        return

    if args.command == "scheduled":
        mode = scheduled_mode()
        print(f"Scheduled mode selected: {mode}", flush=True)
        run_digest(
            config,
            mode=mode,
            dry_run=args.dry_run,
            source_filter=args.source,
            fetch_detail_pages=not args.no_detail,
        )
        return


def add_run_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--source", help="Run only one configured source, e.g. openrent")
    parser.add_argument("--no-detail", action="store_true", help="Skip fetching individual listing pages")


def run_digest(
    config: dict,
    *,
    mode: str,
    dry_run: bool,
    source_filter: str | None,
    fetch_detail_pages: bool,
) -> None:
    if config.get("runtime", {}).get("baseline_on_empty_db") and database_is_empty(config):
        print("Database is empty. Creating first-run baseline without sending email.", flush=True)
        stats, marked = baseline_current_listings(
            config,
            source_filter=source_filter,
            fetch_detail_pages=fetch_detail_pages,
            progress=print_progress,
        )
        print_stats(stats)
        print(f"First-run baseline complete. Marked {marked} listings as already seen.")
        return

    stats = fetch_filter_store(
        config,
        source_filter=source_filter,
        fetch_detail_pages=fetch_detail_pages,
        progress=print_progress,
    )
    print_stats(stats)
    pending = load_pending(config)
    include_empty = mode == "morning"
    if not pending and not include_empty:
        print("No new listings or price drops. Evening email skipped.")
        return
    timezone_name = config["app"].get("timezone", "Europe/London")
    html = build_digest_html(pending, mode=mode, timezone_name=timezone_name, include_empty=include_empty)
    text = build_digest_text(pending, mode=mode, include_empty=include_empty)
    subject = subject_for(config, mode, pending)
    if dry_run:
        output = write_preview(mode, html)
        print(f"Dry run complete. Preview written to {output}")
        return
    if pending or include_empty:
        mailer = make_mailer(config["email"])
        result = mailer.send(subject=subject, html=html, text=text)
        print(f"Email sent: {result.get('id', 'ok')}")
        if pending:
            with connect(config["app"]["database_url"]) as conn:
                mark_sent(conn, [int(item["id"]) for item in pending])


def send_test_email(config: dict, *, dry_run: bool) -> None:
    html = """
    <html><body>
      <h1>Glasgow Rent Agent test</h1>
      <p>Email setup works. Next step: run the baseline.</p>
    </body></html>
    """
    text = "Glasgow Rent Agent test\n\nEmail setup works. Next step: run the baseline."
    if dry_run:
        output = write_preview("email-test", html)
        print(f"Dry run complete. Preview written to {output}")
        return
    mailer = make_mailer(config["email"])
    result = mailer.send(
        subject=f"{config['email'].get('subject_prefix', 'Rent alerts')} - test",
        html=html,
        text=text,
    )
    print(f"Test email sent: {result.get('id', 'ok')}")


def scheduled_mode() -> str:
    return "morning" if datetime.now(timezone.utc).hour < 12 else "evening"


def subject_for(config: dict, mode: str, pending: list[dict]) -> str:
    prefix = config["email"].get("subject_prefix", "Rent alerts")
    if not pending:
        return f"{prefix}: no new Glasgow flats"
    drops = sum(1 for item in pending if item.get("notification_reason") == "price_drop")
    new_count = len(pending) - drops
    pieces = []
    if new_count:
        pieces.append(f"{new_count} new")
    if drops:
        pieces.append(f"{drops} price drop{'s' if drops != 1 else ''}")
    return f"{prefix}: {', '.join(pieces)}"


def write_preview(name: str, html: str) -> Path:
    output_dir = Path("work")
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / f"{name}-preview.html"
    output.write_text(html, encoding="utf-8")
    return output


def print_stats(stats) -> None:
    print(
        "Fetched: {fetched} | Accepted: {accepted} | Rejected: {rejected} | "
        "New: {inserted_new} | Known: {known} | Price drops: {price_drops}".format(
            fetched=stats.fetched,
            accepted=stats.accepted,
            rejected=stats.rejected,
            inserted_new=stats.inserted_new,
            known=stats.known,
            price_drops=stats.price_drops,
        )
    )
    if stats.reject_reasons:
        common = ", ".join(f"{reason} ({count})" for reason, count in stats.reject_reasons.most_common(5))
        print(f"Top reject reasons: {common}")
    if stats.errors:
        print("Source errors:")
        for error in stats.errors:
            print(f"  - {error}")


def print_progress(message: str) -> None:
    print(message, flush=True)


def print_pending(pending: list[dict]) -> None:
    if not pending:
        print("No pending notifications.")
        return
    for item in pending:
        print(
            "{reason}: GBP {price} pcm | {beds} bed | {title} | {url}".format(
                reason=item.get("notification_reason"),
                price=item.get("last_price_pcm"),
                beds=item.get("bedrooms"),
                title=item.get("title"),
                url=item.get("canonical_url"),
            )
        )
