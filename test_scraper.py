import asyncio
import logging
from scraper import NewsScraper

async def test():
    logging.getLogger().setLevel(logging.INFO)
    scraper = NewsScraper()
    
    # Filter config to only include 2 sites
    sites_to_test = ["Reuters", "CNBC"]
    scraper.config['sources'] = [s for s in scraper.config['sources'] if s['name'] in sites_to_test]
    
    print(f"Testing sources: {[s['name'] for s in scraper.config['sources']]}")
    
    results = await scraper.scrape_all()
    
    print(f"\nTotal articles scraped: {len(results)}")
    if results:
        print("\nFirst 3 articles:")
        for r in results[:3]:
            print(f"- {r['source']}: {r['title']} ({r['url']})")
    
if __name__ == "__main__":
    asyncio.run(test())
