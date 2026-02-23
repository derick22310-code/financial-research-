import json
import logging
import os
from typing import List, Dict
import requests
import google.generativeai as genai
from datetime import datetime, timezone, timedelta

class AIProcessor:
    def __init__(self, config_path: str = 'config.json'):
        with open(config_path, 'r', encoding='utf-8') as f:
            self.config = json.load(f)
        self.keywords = [k.lower() for k in self.config.get('keywords', [])]
        
        # In a real app, API key should come from environment variables
        # Assuming the user has set GOOGLE_API_KEY environment variable.
        # Alternatively we could prompt for it, but for a local script env var is standard.
        # We will attempt to get it from os.environ, if not present initialization might fail during API call.
        api_key = os.environ.get("GOOGLE_API_KEY")
        
        self.tg_token = os.environ.get("TG_TOKEN")
        self.tg_chat_id = os.environ.get("TG_CHAT_ID")
        if not self.tg_token or not self.tg_chat_id:
            logging.info("TG_TOKEN or TG_CHAT_ID not set. Telegram notifications are disabled.")

        if not api_key:
             logging.warning("GOOGLE_API_KEY environment variable not set. API calls will fail.")
        else:
             genai.configure(api_key=api_key)
             
        # Use recommended fast model for text summarization
        self.model = genai.GenerativeModel('gemini-2.5-flash')

    def filter_by_keywords(self, articles: List[Dict]) -> List[Dict]:
        """Filters articles, keeping only those containing at least one keyword in the title."""
        filtered_articles = []
        for article in articles:
            title_lower = article['title'].lower()
            if any(keyword in title_lower for keyword in self.keywords):
                filtered_articles.append(article)
        
        logging.info(f"Filtered {len(articles)} articles down to {len(filtered_articles)} based on keywords.")
        return filtered_articles

    def summarize_article(self, article: Dict) -> Dict:
        """Uses Gemini to summarize the headline/article context."""
        prompt = f"""
        Analyze the following financial news headline and provide a brief summary in Traditional Chinese (繁體中文).
        Title: {article['title']}
        Source: {article['source']}

        Please provide a summary containing:
        1. 核心事件 (Core event)
        2. 潛在市場影響 (Potential market impact)
        3. 關鍵數據 (Key figures/numbers mentioned)
        
        Limit your entire response to under 100 words. Keep it highly concise.
        """
        
        try:
            response = self.model.generate_content(prompt)
            article['summary'] = response.text.strip()
            logging.info(f"Successfully summarized: {article['title'][:30]}...")
        except Exception as e:
            logging.error(f"Failed to summarize article '{article['title'][:30]}...': {e}")
            article['summary'] = "Summary generation failed."
            
        return article

    def send_telegram_message(self, message: str):
        """Sends a message to the configured Telegram chat."""
        if not self.tg_token or not self.tg_chat_id:
            return
            
        url = f"https://api.telegram.org/bot{self.tg_token}/sendMessage"
        payload = {
            "chat_id": self.tg_chat_id,
            "text": message,
            "parse_mode": "HTML"
        }
        try:
            response = requests.post(url, json=payload, timeout=10)
            if response.status_code != 200:
                logging.error(f"Failed to send Telegram message: {response.text}")
            else:
                logging.info("Successfully sent message to Telegram.")
        except Exception as e:
            logging.error(f"Error sending Telegram message: {e}")

    def process(self, articles: List[Dict]) -> List[Dict]:
        """Filters and summarizes the list of articles."""
        filtered = self.filter_by_keywords(articles)
        
        # Limit to the top 5 most important news
        filtered = filtered[:5]
        
        processed = []
        for article in filtered:
            processed_article = self.summarize_article(article)
            processed.append(processed_article)
            
        # Group into a single Telegram message
        valid_articles = [a for a in processed if a.get('summary') and a['summary'] != "Summary generation failed."]
        if valid_articles:
            tz_tpe = timezone(timedelta(hours=8))
            now = datetime.now(tz_tpe).strftime('%Y-%m-%d %H:%M')
            
            msg = f"<b>今日金融重點快訊 ({now})</b>\n\n"
            for a in valid_articles:
                msg += f"<b>{a['title']}</b>\n"
                msg += f"<i>Source: {a['source']}</i>\n\n"
                msg += f"{a['summary']}\n\n"
                msg += f"<a href='{a.get('url', '#')}'>Read more</a>\n\n"
                
            self.send_telegram_message(msg)

        return processed

if __name__ == "__main__":
    # Local test block to send previously saved news to Telegram
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    processor = AIProcessor()
    
    try:
        with open('data/news_20260223.json', 'r', encoding='utf-8') as f:
            saved_articles = json.load(f)
            
        logging.info(f"Loaded {len(saved_articles)} articles from data/news_20260223.json")
        
        # Limit to top 5
        saved_articles = saved_articles[:5]
        
        valid_articles = [a for a in saved_articles if a.get('summary') and a['summary'] != "Summary generation failed."]
        if valid_articles:
            tz_tpe = timezone(timedelta(hours=8))
            now = datetime.now(tz_tpe).strftime('%Y-%m-%d %H:%M')
            
            msg = f"<b>今日金融重點快訊 ({now})</b>\n\n"
            for article in valid_articles:
                msg += f"<b>{article['title']}</b>\n"
                msg += f"<i>Source: {article['source']}</i>\n\n"
                msg += f"{article['summary']}\n\n"
                msg += f"<a href='{article.get('url', '#')}'>Read more</a>\n\n"
                
            processor.send_telegram_message(msg)
                
        logging.info("Telegram message sent successfully!")
    except FileNotFoundError:
        logging.error("File data/news_20260223.json not found.")
