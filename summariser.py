#!/usr/bin/env python3
"""
PHASE 4: Summariser - summariser.py
Uses Claude (Anthropic API) to generate structured article summaries.
"""

import os
import json
import logging
from anthropic import Anthropic

logger = logging.getLogger(__name__)

# ============================================================================
# CONFIGURATION
# ============================================================================

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
if not ANTHROPIC_API_KEY:
    raise ValueError("ANTHROPIC_API_KEY environment variable not set")

client = Anthropic()

SECTOR_TAGS = [
    "IMFL", "Beer", "Wine", "Spirits", "Excise", "Regulation",
    "M&A", "Earnings", "Capex", "IPO", "Distribution", "ENA", "Premiumisation"
]

SYSTEM_PROMPT = """You are an expert financial analyst specializing in the Indian alcoholic beverages (alcobev) sector. 
Your task is to analyze news articles and generate structured investment insights.

For each article provided, you must extract and return a JSON object with the following structure:
{
  "summary_bullets": ["bullet 1", "bullet 2", "bullet 3", "bullet 4", "bullet 5"],
  "companies_mentioned": ["Company 1", "Company 2"],
  "sector_tags": ["tag1", "tag2"],
  "investment_impact": "Bullish|Bearish|Neutral|Watch",
  "impact_reason": "One sentence explaining the investment impact",
  "confidence": "High|Medium|Low"
}

Guidelines:
1. Summary bullets should be concise, factual, and investment-focused (3-5 bullets max)
2. Extract exact company names mentioned in the article
3. Sector tags must ONLY be from this list: IMFL, Beer, Wine, Spirits, Excise, Regulation, M&A, Earnings, Capex, IPO, Distribution, ENA, Premiumisation
4. Investment impact categories:
   - Bullish: Positive for sector/company valuations or growth
   - Bearish: Negative for sector/company valuations or growth
   - Neutral: No clear investment implications
   - Watch: Uncertain impact requiring monitoring
5. Confidence reflects how clear the investment signal is (High/Medium/Low)
6. Return ONLY valid JSON, no other text

For articles about:
- Excise duty reductions → likely Bullish (improves margins/volumes)
- Premium segment growth → likely Bullish (higher margins)
- Regulatory restrictions → likely Bearish (volume constraints)
- Acquisitions/M&A → likely Bullish (scale/consolidation)
- Export opportunities → likely Bullish (revenue expansion)
- Import restrictions → context-dependent (Bearish for open market, Bullish for domestic players)
- Industry consolidation → Bullish (market share gains for acquirers)
- Capacity expansion → Bullish (revenue growth potential)
- Price increases → Neutral to Bullish (margin improvement)
- Volume declines → Bearish (revenue risk)

Always maintain objectivity and base analysis on facts presented in the article."""

# ============================================================================
# SUMMARISATION FUNCTION
# ============================================================================

def summarise_article(article):
    """
    Summarise article using Claude API.
    
    Args:
        article (dict): Article data with 'title', 'text', 'url', 'source', 'published'
    
    Returns:
        dict: Summary with keys: summary_bullets, companies_mentioned, sector_tags,
              investment_impact, impact_reason, confidence
    """
    
    try:
        title = article.get('title', 'Unknown')
        text = article.get('text', '')
        url = article.get('url', '')
        source = article.get('source', '')
        
        if not text or len(text.strip()) < 50:
            logger.warning(f"Article text too short: {title}")
            return _default_summary()
        
        # Prepare prompt
        user_message = f"""Analyze this alcobev sector article and return structured JSON:

ARTICLE METADATA:
Title: {title}
Source: {source}
URL: {url}

ARTICLE TEXT:
{text[:3000]}

Provide JSON response with: summary_bullets, companies_mentioned, sector_tags, investment_impact, impact_reason, confidence"""
        
        logger.info(f"Calling Claude API for: {title}")
        
        # Call Claude API
        message = client.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            messages=[
                {"role": "user", "content": user_message}
            ]
        )
        
        # Extract response
        response_text = message.content[0].text
        logger.debug(f"Claude response: {response_text}")
        
        # Parse JSON
        try:
            summary = json.loads(response_text)
        except json.JSONDecodeError:
            # Try to extract JSON from response
            import re
            json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
            if json_match:
                summary = json.loads(json_match.group())
            else:
                logger.error(f"Failed to parse Claude response: {response_text}")
                return _default_summary()
        
        # Validate and clean summary
        summary = _validate_summary(summary)
        logger.info(f"✅ Summary generated - Impact: {summary['investment_impact']}")
        
        return summary
    
    except Exception as e:
        logger.error(f"Summarisation error: {e}", exc_info=True)
        return _default_summary()

def _validate_summary(summary):
    """Validate and clean summary structure."""
    
    # Ensure required keys exist
    required_keys = [
        'summary_bullets', 'companies_mentioned', 'sector_tags',
        'investment_impact', 'impact_reason', 'confidence'
    ]
    
    for key in required_keys:
        if key not in summary:
            summary[key] = _get_default_for_key(key)
    
    # Validate summary_bullets
    if not isinstance(summary['summary_bullets'], list):
        summary['summary_bullets'] = []
    summary['summary_bullets'] = summary['summary_bullets'][:5]  # Max 5
    
    # Validate companies_mentioned
    if not isinstance(summary['companies_mentioned'], list):
        summary['companies_mentioned'] = []
    
    # Validate sector_tags
    if not isinstance(summary['sector_tags'], list):
        summary['sector_tags'] = []
    summary['sector_tags'] = [tag for tag in summary['sector_tags'] if tag in SECTOR_TAGS]
    
    # Validate investment_impact
    valid_impacts = ["Bullish", "Bearish", "Neutral", "Watch"]
    if summary['investment_impact'] not in valid_impacts:
        summary['investment_impact'] = "Neutral"
    
    # Validate impact_reason (string)
    if not isinstance(summary['impact_reason'], str):
        summary['impact_reason'] = "Article contains sector-relevant information."
    
    # Validate confidence
    valid_confidence = ["High", "Medium", "Low"]
    if summary['confidence'] not in valid_confidence:
        summary['confidence'] = "Medium"
    
    return summary

def _default_summary():
    """Return default summary structure."""
    return {
        'summary_bullets': ["Unable to extract key insights from article"],
        'companies_mentioned': [],
        'sector_tags': [],
        'investment_impact': 'Neutral',
        'impact_reason': 'Insufficient data for analysis',
        'confidence': 'Low'
    }

def _get_default_for_key(key):
    """Get default value for a summary key."""
    defaults = {
        'summary_bullets': [],
        'companies_mentioned': [],
        'sector_tags': [],
        'investment_impact': 'Neutral',
        'impact_reason': '',
        'confidence': 'Low'
    }
    return defaults.get(key, None)

# ============================================================================
# TEST FUNCTION
# ============================================================================

def test_summariser():
    """Test summariser with sample article."""
    sample_article = {
        'title': 'United Spirits Q4 Results: Strong Premium Growth',
        'text': """United Spirits reported strong Q4 results with 15% growth in premium segment sales.
        The company benefited from excise duty reductions in several states.
        Management guided for 20% growth in FY25 driven by premiumisation.
        Diageo's focus on India continues with continued investment in brands like Johnnie Walker and Royal Challenge.
        The IMFL sector is witnessing consolidation as larger players acquire regional brands.""",
        'url': 'https://example.com/article',
        'source': 'business-standard.com',
        'published': '2024-06-20T10:00:00Z'
    }
    
    logger.info("Testing summariser...")
    result = summarise_article(sample_article)
    logger.info(f"Result: {json.dumps(result, indent=2)}")
    return result

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    test_summariser()
