import argparse
import logging
import sys
from datetime import datetime

from config import DEFAULT_MAX_PAGES, DEFAULT_OUTPUT_DIR
from browser import search_google, extract_urls_from_snapshot, open_url, get_page_text, close_browser
from agent import plan_search, summarize_page, generate_review
from report import generate_html_report

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def run_research(topic: str, max_pages: int, output_path: str):
    """Run the full research flow: plan → search → read → summarize → report."""

    # Phase 1: Planning
    logger.info(f"Phase 1: Planning research for: {topic}")
    plan = plan_search(topic)
    logger.info(f"  Keywords: {plan['keywords']}")
    logger.info(f"  Sites: {plan['sites']}")

    # Phase 2: Searching
    logger.info("Phase 2: Searching for relevant pages...")
    all_urls = []

    for keyword in plan["keywords"]:
        logger.info(f"  Searching Google: {keyword}")
        snapshot = search_google(keyword)
        if snapshot:
            urls = extract_urls_from_snapshot(snapshot, max_urls=5)
            logger.info(f"  Found {len(urls)} URLs")
            for url in urls:
                if url not in all_urls:
                    all_urls.append(url)
        else:
            logger.warning(f"  Search failed for: {keyword}")

    # Limit to max_pages
    all_urls = all_urls[:max_pages]
    logger.info(f"  Total unique URLs to read: {len(all_urls)}")

    if not all_urls:
        logger.error("No URLs found. Check your network and agent-browser installation.")
        close_browser()
        sys.exit(1)

    # Phase 3: Reading and summarizing
    logger.info("Phase 3: Reading and summarizing pages...")
    summaries = []
    for i, url in enumerate(all_urls, 1):
        logger.info(f"  [{i}/{len(all_urls)}] Reading: {url}")
        if not open_url(url):
            logger.warning(f"  Failed to open: {url}")
            continue

        content = get_page_text()
        if not content:
            logger.warning(f"  No content extracted: {url}")
            continue

        summary = summarize_page(url, content)
        if summary:
            summaries.append(summary)
            logger.info(f"  Summarized: {summary.get('title', 'Unknown')}")
        else:
            logger.warning(f"  Summary failed or irrelevant: {url}")

    logger.info(f"  Successfully summarized {len(summaries)} pages")

    if not summaries:
        logger.error("No pages were successfully summarized.")
        close_browser()
        sys.exit(1)

    # Phase 4: Generate review
    logger.info("Phase 4: Generating review...")
    review_html = generate_review(topic, summaries)

    # Generate report
    path = generate_html_report(topic, review_html, all_urls, output_path)
    logger.info(f"Report saved to: {path}")

    close_browser()
    return path


def main():
    parser = argparse.ArgumentParser(
        description="Research Flow - Automated technical research assistant"
    )
    parser.add_argument("topic", help="Research topic or question")
    parser.add_argument(
        "--max-pages",
        type=int,
        default=DEFAULT_MAX_PAGES,
        help=f"Maximum pages to read (default: {DEFAULT_MAX_PAGES})",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Output HTML file path (default: output/report_<timestamp>.html)",
    )

    args = parser.parse_args()

    if args.output is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        args.output = f"{DEFAULT_OUTPUT_DIR}/report_{timestamp}.html"

    logger.info(f"Starting research: {args.topic}")
    logger.info(f"Max pages: {args.max_pages}")
    logger.info(f"Output: {args.output}")

    try:
        path = run_research(args.topic, args.max_pages, args.output)
        print(f"\nDone! Report saved to: {path}")
    except KeyboardInterrupt:
        logger.info("Interrupted by user.")
        close_browser()
        sys.exit(1)
    except Exception as e:
        logger.error(f"Research failed: {e}")
        close_browser()
        sys.exit(1)


if __name__ == "__main__":
    main()
