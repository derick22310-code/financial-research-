import asyncio
import logging
from scraper import NewsScraper
from ai_processor import AIProcessor
from storage import StorageManager

async def main():
    logging.info("Starting Multi-source Financial News Monitoring System...")
    
    # 1. Initialize components
    scraper = NewsScraper()
    ai = AIProcessor()
    storage = StorageManager()
    
    # 2. Scrape News
    logging.info("Phase 1: Scraping...")
    all_articles = await scraper.scrape_all()
    logging.info(f"Total articles scraped: {len(all_articles)}")
    
    # 3. Process with AI (Filter and Summarize)
    logging.info("Phase 2: AI Processing & Filtering...")
    processed_articles = ai.process(all_articles)
    logging.info(f"Total articles after filtering and summarization: {len(processed_articles)}")
    
    # 4. Save results
    logging.info("Phase 3: Saving data...")
    if processed_articles:
         storage.save_results(processed_articles)
    else:
         logging.info("No articles matched keywords. Nothing to save.")
         
    logging.info("Done.")

if __name__ == "__main__":
    asyncio.run(main())
