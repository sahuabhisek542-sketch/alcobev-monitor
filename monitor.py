#!/usr/bin/env python3
"""
PHASE 3: Core Crawler - monitor.py
Monitors RSS feeds, scrapes articles, deduplicates, and passes to summariser.
Runs every 30 minutes via GitHub Actions.
"""

import os
import json
import time
import logging
import hashlib
import subprocess
from datetime import datetime
from urllib.robotparser import RobotFileParser
from urllib.parse import urljoin, urlparse
from pathlib import Path

import feedparser
import requests
from bs4 import BeautifulSoup
from fuzzywuzzy import fuzz
import pdfplumber
import newspaper
from newspaper import Article

# ============================================================================
# CONFIGURATION
# ============================================================================

DATA_DIR = Path("data")
SEEN_URLS_FILE = DATA_DIR / "seen_urls.json"
ARTICLES_FILE = DATA_DIR / "articles.json"
FEEDS_FILE = "feeds.txt"
KEYWORDS_FILE = "keywords.txt"

FUZZY_THRESHOLD = 85
RETRY_MAX = 3
RETRY_BACKOFF = 2
REQUEST_DELAY = 1
TELEGRAM_DELAY = 3

# Create data directory if it doesn't exist
DATA_DIR.mkdir(exist_ok=True)

# ============================================================================
# LOGGING SETUP
# ============================================================================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def load_json_file(filepath, default=None):
    """Load JSON file safely, return default if not found."""
    if filepath.exists():
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Error loading {filepath}: {e}")
            return default if default is not None else {}
    return default if default is not None else {}

def save_json_file(filepath, data):
    """Save JSON file safely."""
    try:
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        logger.info(f"Saved {filepath}")
    except Exception as e:
        logger.error(f"Error saving {filepath}: {e}")

def compute_url_hash(url):
    """Compute SHA256 hash of URL."""
    return hashlib.sha256(url.encode()).hexdigest()

def load_keywords():
    """Load keywords from keywords.txt, filter comments."""
    if not Path(KEYWORDS_FILE).exists():
        logger.warning(f"{KEYWORDS_FILE} not found")
        return []
    
    keywords = []
    with open(KEYWORDS_FILE, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#'):
                keywords.append(line.lower())
    
    logger.info(f"Loaded {len(keywords)} keywords")
    return keywords

def load_feeds():
    """Load feeds from feeds.txt, filter comments."""
    if not Path(FEEDS_FILE).exists():
        logger.warning(f"{FEEDS_FILE} not found")
        return []
    
    feeds = []
    with open(FEEDS_FILE, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#'):
                feeds.append(line)
    
    logger.info(f"Loaded {len(feeds)} feeds")
    return feeds

def check_robots_txt(url):
    """Check if URL is allowed by robots.txt."""
    try:
        domain = urlparse(url).netloc
        rp = RobotFileParser()
        rp.set_url(f"https://{domain}/robots.txt")
        rp.read()
        allowed = rp.can_fetch("*", url)
        if not allowed:
            logger.debug(f"robots.txt blocks: {url}")
        return allowed
    except Exception as e:
        logger.debug(f"robots.txt check failed for {url}: {e}")
        return True  # Assume allowed if check fails

def fetch_url_with_retry(url, timeout=10):
    """Fetch URL with exponential backoff retry."""
    for attempt in range(RETRY_MAX):
        try:
            time.sleep(REQUEST_DELAY)
            response = requests.get(url, timeout=timeout, allow_redirects=True)
            response.raise_for_status()
            return response
        except requests.exceptions.RequestException as e:
            logger.warning(f"Attempt {attempt+1}/{RETRY_MAX} failed for {url}: {e}")
            if attempt < RETRY_MAX - 1:
                time.sleep(RETRY_BACKOFF ** attempt)
    
    logger.error(f"Failed to fetch {url} after {RETRY_MAX} attempts")
    return None

def extract_article_text(url):
    """Extract article text from URL using newspaper3k."""
    try:
        article = Article(url)
        article.download()
        article.parse()
        return {
            'text': article.text,
            'title': article.title or 'No title',
            'publish_date': article.publish_date,
        }
    except Exception as e:
        logger.warning(f"Failed to extract article text from {url}: {e}")
        return None

def extract_pdf_text(url):
    """Extract text from PDF."""
    try:
        response = fetch_url_with_retry(url)
        if not response:
            return None
        
        with pdfplumber.open(BytesIO(response.content)) as pdf:
            text = "".join([page.extract_text() for page in pdf.pages])
        
        return {
            'text': text,
            'title': 'PDF Document',
            'publish_date': None,
        }
    except Exception as e:
        logger.warning(f"Failed to extract PDF from {url}: {e}")
        return None

def extract_text_fallback(url):
    """Fallback text extraction using BeautifulSoup."""
    try:
        response = fetch_url_with_retry(url)
        if not response:
            return None
        
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Remove scripts and styles
        for script in soup(["script", "style"]):
            script.decompose()
        
        text = soup.get_text(separator='\n', strip=True)
        title = soup.title.string if soup.title else 'No title'
        
        return {
            'text': text[:5000],  # Limit to 5000 chars
            'title': title,
            'publish_date': None,
        }
    except Exception as e:
        logger.warning(f"Fallback extraction failed for {url}: {e}")
        return None

def scrape_article_text(url):
    """Scrape article text, trying multiple methods."""
    if not check_robots_txt(url):
        logger.info(f"Skipping {url} (robots.txt)")
        return None
    
    # Try newspaper3k first
    if not url.endswith('.pdf'):
        result = extract_article_text(url)
        if result:
            return result
    
    # Try PDF extraction if URL is PDF
    if url.endswith('.pdf'):
        result = extract_pdf_text(url)
        if result:
            return result
    
    # Fallback to BeautifulSoup
    result = extract_text_fallback(url)
    if result:
        return result
    
    return None

def is_duplicate_by_title(new_title, existing_titles, threshold=FUZZY_THRESHOLD):
    """Check if title is similar to existing titles using fuzzy matching."""
    for existing_title in existing_titles:
        similarity = fuzz.token_set_ratio(new_title.lower(), existing_title.lower())
        if similarity >= threshold:
            logger.info(f"Duplicate found by title similarity ({similarity}%): {new_title}")
            return True
    return False

def is_already_seen(url_hash, seen_urls):
    """Check if URL has been processed."""
    return url_hash in seen_urls

def parse_feeds(feeds):
    """Parse all RSS feeds and extract entries."""
    entries = []
    
    for feed_url in feeds:
        logger.info(f"Parsing feed: {feed_url}")
        try:
            feed = feedparser.parse(feed_url)
            if feed.bozo:
                logger.warning(f"Feed parsing error for {feed_url}: {feed.bozo_exception}")
            
            for entry in feed.entries[:20]:  # Limit to 20 entries per feed
                entries.append({
                    'title': entry.get('title', 'No title'),
                    'url': entry.get('link', ''),
                    'published': entry.get('published', datetime.utcnow().isoformat()),
                    'summary': entry.get('summary', ''),
                })
        except Exception as e:
            logger.error(f"Error parsing feed {feed_url}: {e}")
        
        time.sleep(REQUEST_DELAY)
    
    logger.info(f"Parsed {len(entries)} entries from feeds")
    return entries

def filter_by_keywords(entry, keywords):
    """Check if entry matches any keyword."""
    text_to_check = (
        entry['title'].lower() + ' ' + 
        entry['summary'].lower()
    ).lower()
    
    for keyword in keywords:
        if keyword.lower() in text_to_check:
            return True
    
    return False

def process_articles(entries, keywords):
    """Process entries: filter, deduplicate, scrape, summarise."""
    seen_urls = load_json_file(SEEN_URLS_FILE, {})
    articles_history = load_json_file(ARTICLES_FILE, [])
    existing_titles = [a['title'] for a in articles_history]
    
    new_articles = []
    
    for entry in entries:
        url = entry['url']
        
        if not url:
            logger.warning(f"Skipping entry with no URL: {entry['title']}")
            continue
        
        # Check if keyword matches
        if not filter_by_keywords(entry, keywords):
            logger.debug(f"Skipping (no keyword match): {entry['title']}")
            continue
        
        # Check if already seen
        url_hash = compute_url_hash(url)
        if is_already_seen(url_hash, seen_urls):
            logger.debug(f"Skipping (already seen): {url}")
            continue
        
        # Check for title duplicates
        if is_duplicate_by_title(entry['title'], existing_titles):
            logger.debug(f"Skipping (duplicate title): {entry['title']}")
            continue
        
        # Scrape article text
        logger.info(f"Scraping: {url}")
        article_data = scrape_article_text(url)
        if not article_data:
            logger.warning(f"Failed to scrape: {url}")
            seen_urls[url_hash] = datetime.utcnow().isoformat()
            save_json_file(SEEN_URLS_FILE, seen_urls)
            continue
        
        # Create article object
        article = {
            'title': article_data['title'],
            'source': urlparse(url).netloc,
            'url': url,
            'published': article_data['publish_date'] or entry['published'],
            'text': article_data['text'],
            'summary_bullets': [],
            'companies_mentioned': [],
            'sector_tags': [],
            'investment_impact': 'Neutral',
            'impact_reason': '',
            'confidence': 'Medium',
            'fetched_at': datetime.utcnow().isoformat(),
        }
        
        new_articles.append(article)
        existing_titles.append(article['title'])
        seen_urls[url_hash] = datetime.utcnow().isoformat()
        
        logger.info(f"✅ New article: {article['title']}")
    
    # Save updated seen_urls
    save_json_file(SEEN_URLS_FILE, seen_urls)
    
    return new_articles

def commit_changes_to_git():
    """Commit updated data files to git."""
    try:
        subprocess.run(["git", "add", "data/"], check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "[bot] Update article data"],
            check=True,
            capture_output=True
        )
        logger.info("✅ Changes committed to git")
    except subprocess.CalledProcessError as e:
        if "nothing to commit" in e.stderr.decode():
            logger.info("No changes to commit")
        else:
            logger.error(f"Git commit failed: {e}")
    except Exception as e:
        logger.error(f"Git operation failed: {e}")

# ============================================================================
# MAIN EXECUTION
# ============================================================================

def main():
    """Main monitoring function."""
    logger.info("=" * 80)
    logger.info("ALCOBEV MONITOR - Starting crawl")
    logger.info("=" * 80)
    
    try:
        # Load configuration
        feeds = load_feeds()
        keywords = load_keywords()
        
        if not feeds:
            logger.error("No feeds loaded. Exiting.")
            return
        
        if not keywords:
            logger.error("No keywords loaded. Exiting.")
            return
        
        # Parse feeds
        entries = parse_feeds(feeds)
        
        # Process articles
        new_articles = process_articles(entries, keywords)
        
        if new_articles:
            logger.info(f"\n📊 Found {len(new_articles)} new articles")
            
            # Import summariser and notifier
            from summariser import summarise_article
            from notifier import send_telegram_alert
            
            articles_history = load_json_file(ARTICLES_FILE, [])
            
            for article in new_articles:
                logger.info(f"\nProcessing: {article['title']}")
                
                # Summarise
                try:
                    summary = summarise_article(article)
                    article.update(summary)
                except Exception as e:
                    logger.error(f"Summarisation failed: {e}")
                    continue
                
                # Send Telegram alert
                try:
                    send_telegram_alert(article)
                    time.sleep(TELEGRAM_DELAY)
                except Exception as e:
                    logger.error(f"Telegram alert failed: {e}")
                
                # Add to history
                articles_history.append(article)
            
            # Save updated articles
            save_json_file(ARTICLES_FILE, articles_history)
            
            # Commit changes
            commit_changes_to_git()
        else:
            logger.info("No new articles found.")
        
        logger.info("\n" + "=" * 80)
        logger.info("ALCOBEV MONITOR - Crawl complete")
        logger.info("=" * 80)
    
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        raise

if __name__ == "__main__":
    main()
