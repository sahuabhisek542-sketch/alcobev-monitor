#!/usr/bin/env python3
"""
PHASE 5: Notifier - notifier.py
Sends formatted alerts to Telegram for each new article.
Includes rate limiting and daily digest mode.
"""

import os
import json
import logging
import time
from datetime import datetime, timedelta
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

# ============================================================================
# CONFIGURATION
# ============================================================================

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
    raise ValueError("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID environment variables must be set")

TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
RATE_LIMIT_DELAY = 3  # seconds between messages
DIGEST_FILE = Path("data/digest.json")

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def load_digest():
    """Load digest from file."""
    if DIGEST_FILE.exists():
        try:
            with open(DIGEST_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Error loading digest: {e}")
            return {"articles": [], "last_sent": None}
    return {"articles": [], "last_sent": None}

def save_digest(digest):
    """Save digest to file."""
    try:
        DIGEST_FILE.parent.mkdir(exist_ok=True)
        with open(DIGEST_FILE, 'w', encoding='utf-8') as f:
            json.dump(digest, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Error saving digest: {e}")

def send_telegram_message(text, parse_mode="HTML"):
    """
    Send message to Telegram.
    
    Args:
        text (str): Message text (HTML formatted)
        parse_mode (str): "HTML" or "Markdown"
    
    Returns:
        bool: True if successful
    """
    try:
        url = f"{TELEGRAM_API_URL}/sendMessage"
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": False
        }
        
        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()
        
        logger.info("✅ Telegram message sent")
        return True
    
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to send Telegram message: {e}")
        return False

def format_impact_emoji(impact):
    """Get emoji for investment impact."""
    emojis = {
        "Bullish": "📈",
        "Bearish": "📉",
        "Neutral": "➡️",
        "Watch": "👁️"
    }
    return emojis.get(impact, "❓")

def format_confidence_emoji(confidence):
    """Get emoji for confidence level."""
    emojis = {
        "High": "🟢",
        "Medium": "🟡",
        "Low": "🔴"
    }
    return emojis.get(confidence, "⚪")

# ============================================================================
# ALERT FORMATTING
# ============================================================================

def format_alert_html(article):
    """
    Format article as HTML Telegram message.
    
    Args:
        article (dict): Article with summary data
    
    Returns:
        str: HTML-formatted message
    """
    
    title = article.get('title', 'Unknown')[:100]
    source = article.get('source', 'Unknown')
    published = article.get('published', 'Unknown')
    url = article.get('url', '')
    
    summary_bullets = article.get('summary_bullets', [])
    companies = article.get('companies_mentioned', [])
    tags = article.get('sector_tags', [])
    impact = article.get('investment_impact', 'Neutral')
    reason = article.get('impact_reason', '')
    confidence = article.get('confidence', 'Low')
    
    # Build message
    lines = [
        "🚨 <b>ALCOBEV ALERT</b>",
        "",
        f"📰 <b>{title}</b>",
        f"🏢 {source} | {published}",
        ""
    ]
    
    # Summary bullets
    if summary_bullets:
        lines.append("📋 <b>Summary:</b>")
        for bullet in summary_bullets[:5]:
            lines.append(f"• {bullet}")
        lines.append("")
    
    # Tags
    if tags:
        tags_str = ", ".join(tags)
        lines.append(f"🏷 <b>Tags:</b> {tags_str}")
    
    # Companies
    if companies:
        companies_str = ", ".join(companies[:5])
        lines.append(f"🏦 <b>Companies:</b> {companies_str}")
    
    lines.append("")
    
    # Investment impact
    impact_emoji = format_impact_emoji(impact)
    confidence_emoji = format_confidence_emoji(confidence)
    lines.append(f"{impact_emoji} <b>Impact:</b> {impact}")
    lines.append(f"💡 {reason}")
    lines.append(f"{confidence_emoji} <b>Confidence:</b> {confidence}")
    
    lines.append("")
    
    # URL
    if url:
        lines.append(f'🔗 <a href="{url}">Read Article</a>')
    
    return "\n".join(lines)

def format_digest_html(articles):
    """
    Format digest of multiple articles as HTML.
    
    Args:
        articles (list): List of articles
    
    Returns:
        str: HTML-formatted digest message
    """
    
    if not articles:
        return "📭 No new articles in the past 24 hours."
    
    lines = [
        "📊 <b>ALCOBEV DAILY DIGEST</b>",
        f"📅 {datetime.now().strftime('%Y-%m-%d')}",
        f"📝 {len(articles)} new articles",
        ""
    ]
    
    # Group by impact
    bullish = [a for a in articles if a.get('investment_impact') == 'Bullish']
    bearish = [a for a in articles if a.get('investment_impact') == 'Bearish']
    neutral = [a for a in articles if a.get('investment_impact') == 'Neutral']
    watch = [a for a in articles if a.get('investment_impact') == 'Watch']
    
    # Bullish
    if bullish:
        lines.append("📈 <b>BULLISH</b> ({})".format(len(bullish)))
        for article in bullish[:3]:
            title = article.get('title', 'Unknown')[:50]
            lines.append(f"  • {title}")
        lines.append("")
    
    # Bearish
    if bearish:
        lines.append("📉 <b>BEARISH</b> ({})".format(len(bearish)))
        for article in bearish[:3]:
            title = article.get('title', 'Unknown')[:50]
            lines.append(f"  • {title}")
        lines.append("")
    
    # Watch
    if watch:
        lines.append("👁️ <b>WATCH</b> ({})".format(len(watch)))
        for article in watch[:3]:
            title = article.get('title', 'Unknown')[:50]
            lines.append(f"  • {title}")
        lines.append("")
    
    # Top companies
    all_companies = []
    for article in articles:
        all_companies.extend(article.get('companies_mentioned', []))
    
    if all_companies:
        from collections import Counter
        top_companies = Counter(all_companies).most_common(5)
        lines.append("🏢 <b>Top Companies:</b>")
        for company, count in top_companies:
            lines.append(f"  • {company} ({count})")
        lines.append("")
    
    # Top tags
    all_tags = []
    for article in articles:
        all_tags.extend(article.get('sector_tags', []))
    
    if all_tags:
        from collections import Counter
        top_tags = Counter(all_tags).most_common(5)
        lines.append("🏷 <b>Top Tags:</b>")
        for tag, count in top_tags:
            lines.append(f"  • {tag} ({count})")
    
    return "\n".join(lines)

# ============================================================================
# ALERT SENDING
# ============================================================================

def send_telegram_alert(article):
    """
    Send individual article alert to Telegram.
    
    Args:
        article (dict): Article with summary data
    
    Returns:
        bool: True if successful
    """
    
    logger.info(f"Sending alert for: {article.get('title', 'Unknown')}")
    
    message = format_alert_html(article)
    success = send_telegram_message(message, parse_mode="HTML")
    
    time.sleep(RATE_LIMIT_DELAY)
    
    return success

def send_daily_digest():
    """
    Send daily digest of articles from past 24 hours.
    
    Returns:
        bool: True if successful
    """
    
    logger.info("Preparing daily digest...")
    
    # Load articles
    articles_file = Path("data/articles.json")
    if not articles_file.exists():
        logger.warning("No articles file found")
        return False
    
    try:
        with open(articles_file, 'r', encoding='utf-8') as f:
            all_articles = json.load(f)
    except Exception as e:
        logger.error(f"Failed to load articles: {e}")
        return False
    
    # Filter articles from past 24 hours
    now = datetime.utcnow()
    cutoff = now - timedelta(hours=24)
    
    recent_articles = []
    for article in all_articles:
        try:
            published = datetime.fromisoformat(article.get('published', '').replace('Z', '+00:00'))
            if published > cutoff:
                recent_articles.append(article)
        except Exception as e:
            logger.debug(f"Error parsing date: {e}")
    
    logger.info(f"Found {len(recent_articles)} articles from past 24 hours")
    
    if not recent_articles:
        logger.info("No recent articles for digest")
        return True
    
    # Format and send digest
    message = format_digest_html(recent_articles)
    success = send_telegram_message(message, parse_mode="HTML")
    
    return success

# ============================================================================
# FAILURE NOTIFICATIONS
# ============================================================================

def send_failure_notification(error_message):
    """
    Send failure alert to Telegram.
    
    Args:
        error_message (str): Error description
    """
    
    logger.error(f"Sending failure notification: {error_message}")
    
    message = f"""⚠️ <b>ALCOBEV MONITOR - FAILURE</b>

❌ <b>Error:</b>
{error_message}

🕐 <b>Time:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

Please check the GitHub Actions logs."""
    
    send_telegram_message(message, parse_mode="HTML")

# ============================================================================
# TEST FUNCTION
# ============================================================================

def test_notifier():
    """Test notifier with sample article."""
    
    sample_article = {
        'title': 'United Spirits Reports Strong Q4 Results',
        'source': 'business-standard.com',
        'published': datetime.now().isoformat(),
        'url': 'https://example.com/article',
        'summary_bullets': [
            'Q4 revenue grew 15% YoY driven by premium segment',
            'Excise duty reductions in key states boost margins',
            'Management guides 20% growth in FY25'
        ],
        'companies_mentioned': ['United Spirits', 'Diageo', 'Johnnie Walker'],
        'sector_tags': ['Earnings', 'Premiumisation', 'IMFL'],
        'investment_impact': 'Bullish',
        'impact_reason': 'Strong premiumisation trend and duty benefits support volume growth',
        'confidence': 'High'
    }
    
    logger.info("Testing notifier...")
    success = send_telegram_alert(sample_article)
    
    if success:
        logger.info("✅ Test message sent successfully")
    else:
        logger.error("❌ Test message failed")
    
    return success

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    test_notifier()
