import re
import time
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

try:
    from duckduckgo_search import DDGS
except ImportError:
    DDGS = None

from src.models.complaint import Authority

EMAIL_PATTERN = re.compile(
    r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}",
    re.IGNORECASE,
)

JUNK_EMAIL_SUFFIXES = (
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp",
    "example.com", "sentry.io", "wixpress.com", "domain.com",
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-IN,en;q=0.9",
}


def _is_valid_email(email: str) -> bool:
    email = email.lower().strip()
    if any(email.endswith(s) or s in email for s in JUNK_EMAIL_SUFFIXES):
        return False
    if email.count("@") != 1:
        return False
    local, domain = email.split("@")
    if len(local) < 2 or "." not in domain:
        return False
    return True


def _extract_emails_from_text(text: str) -> set[str]:
    found = set()
    for match in EMAIL_PATTERN.findall(text):
        if _is_valid_email(match):
            found.add(match.lower())
    # Also catch obfuscated emails like name [at] domain [dot] gov [dot] in
    obfuscated = re.findall(
        r"([a-zA-Z0-9._%+\-]+)\s*(?:\[at\]|@|\(at\))\s*([a-zA-Z0-9.\-]+)\s*(?:\[dot\]|\.|\(dot\))\s*([a-zA-Z]{2,})",
        text,
        re.IGNORECASE,
    )
    for parts in obfuscated:
        email = f"{parts[0]}@{parts[1]}.{parts[2]}".lower()
        if _is_valid_email(email):
            found.add(email)
    return found


def _fetch_page(url: str, timeout: int = 10) -> str | None:
    try:
        resp = requests.get(url, headers=HEADERS, timeout=timeout, allow_redirects=True)
        if resp.status_code == 200 and "text/html" in resp.headers.get("Content-Type", ""):
            return resp.text
    except requests.RequestException:
        pass
    return None


def _scrape_emails_from_url(url: str) -> tuple[set[str], set[str]]:
    """Scrape emails from a page and optionally follow contact/about links."""
    emails: set[str] = set()
    visited: set[str] = set()
    to_visit = [url]

    for _ in range(3):
        if not to_visit:
            break
        current = to_visit.pop(0)
        if current in visited:
            continue
        visited.add(current)

        html = _fetch_page(current)
        if not html:
            continue

        emails.update(_extract_emails_from_text(html))

        soup = BeautifulSoup(html, "lxml")
        for tag in soup.find_all("a", href=True):
            href = tag["href"].lower()
            text = tag.get_text(strip=True).lower()
            if any(kw in href or kw in text for kw in ("contact", "about", "directory", "officer", "email")):
                full = urljoin(current, tag["href"])
                if urlparse(full).netloc == urlparse(url).netloc and full not in visited:
                    to_visit.append(full)

        time.sleep(0.3)

    return emails, visited


def _web_search(query: str, max_results: int = 5) -> list[str]:
    if DDGS is None:
        return []
    urls = []
    try:
        with DDGS() as ddgs:
            for r in ddgs.text(query, region="in-en", max_results=max_results):
                href = r.get("href")
                if href and href.startswith("http"):
                    urls.append(href)
    except Exception:
        pass
    return urls


def find_emails_for_authority(authority: Authority, location: str) -> Authority:
    """Search the web and scrape emails for a given authority."""
    queries = authority.search_queries or [
        f"{authority.name} {location} official email contact",
        f"{authority.name} {location} email address site:gov.in OR site:nic.in",
    ]

    all_emails: set[str] = set()
    source_urls: set[str] = set()

    for query in queries[:3]:
        urls = _web_search(query, max_results=4)
        for url in urls:
            if "gov.in" in url or "nic.in" in url or "police" in url.lower():
                emails, visited = _scrape_emails_from_url(url)
                all_emails.update(emails)
                source_urls.update(visited)
            time.sleep(0.5)

    authority.emails = sorted(all_emails)
    authority.source_urls = sorted(source_urls)
    return authority


def discover_all_emails(authorities: list[Authority], location: str) -> list[Authority]:
    """Run email discovery for all authorities."""
    results = []
    for auth in authorities:
        results.append(find_emails_for_authority(auth, location))
        time.sleep(0.3)
    return results
