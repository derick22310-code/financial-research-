import json
import logging
from typing import List, Dict
from playwright.async_api import async_playwright
import urllib.parse

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class NewsScraper:
    def __init__(self, config_path: str = 'config.json'):
        with open(config_path, 'r', encoding='utf-8') as f:
            self.config = json.load(f)

    async def scrape_source(self, source_config: Dict) -> List[Dict]:
        """Scrapes headlines from a single news source."""
        logging.info(f"Scraping source: {source_config['name']}")
        results = []
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page()
                
                # Using wait_until='domcontentloaded' as networkidle can take a long time on news sites
                await page.goto(source_config['url'], wait_until='domcontentloaded', timeout=30000)
                
                # Give dynamic content a moment to load
                await page.wait_for_timeout(3000)

                articles = await page.query_selector_all(source_config['article_selector'])
                logging.info(f"Found {len(articles)} potential articles on {source_config['name']}.")

                for article in articles:
                    try:
                        headline_elem = await article.query_selector(source_config['headline_selector'])
                        
                        if source_config['link_selector'] == 'self':
                            link_elem = article
                        else:
                            link_elem = await article.query_selector(source_config['link_selector'])

                        if headline_elem and link_elem:
                            headline = await headline_elem.text_content()
                            headline = headline.strip() if headline else ""
                            
                            href = await link_elem.get_attribute('href')
                            if href:
                                # Ensure absolute URL
                                href = urllib.parse.urljoin(source_config['url'], href)

                            if headline and href:
                                results.append({
                                    'source': source_config['name'],
                                    'title': headline,
                                    'url': href
                                })
                    except Exception as e:
                        logging.debug(f"Error parsing article from {source_config['name']}: {e}")

                await browser.close()
                logging.info(f"Successfully scraped {len(results)} items from {source_config['name']}")
        except Exception as e:
            logging.error(f"Failed to scrape {source_config['name']}: {e}")
        return results

    async def scrape_all(self) -> List[Dict]:
        """Scrapes all sources defined in config."""
        all_news = []
        # Doing it sequentially for simplicity and to avoid overwhelming resources, 
        # could be parallelized with asyncio.gather if needed in production.
        for source in self.config.get('sources', []):
            news = await self.scrape_source(source)
            all_news.extend(news)
        return all_news
