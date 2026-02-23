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
        """Uses Gemini to summarize the headline/article context and score importance."""
        prompt = f"""
        Analyze the following financial news headline.
        Title: {article['title']}
        Source: {article['source']}

        1. Assess its importance to the financial market on a scale of 1 to 10.
        2. Translate the title into Traditional Chinese (繁體中文).
        3. Write a brief summary in Traditional Chinese (around 60 words).
        4. Write a brief summary in English (around 60 words).

        You MUST respond ONLY with a valid JSON object strictly matching this format:
        {{
            "score": 8,
            "zh_title": "中文標題翻譯",
            "zh_summary": "中文摘要內容",
            "en_summary": "English summary content"
        }}
        """
        
        try:
            response = self.model.generate_content(prompt)
            text = response.text.replace("```json", "").replace("```", "").strip()
            data = json.loads(text)
            
            article['score'] = data.get('score', 0)
            article['summary'] = f"<b>【標題】：{data.get('zh_title', article['title'])}</b>\n\n摘要：{data.get('zh_summary', 'N/A')}\n\nOriginal Summary：{data.get('en_summary', 'N/A')}"
            
            logging.info(f"Successfully summarized: {article['title'][:30]}... (Score: {article['score']})")
        except Exception as e:
            logging.error(f"Failed to summarize article '{article['title'][:30]}...': {e}")
            article['score'] = 0
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
        
        processed = []
        for article in filtered:
            processed_article = self.summarize_article(article)
            processed.append(processed_article)
            
        # Sort by importance score descending and limit to top 5
        processed.sort(key=lambda x: x.get('score', 0), reverse=True)
        top_5 = processed[:5]
            
        # Group into Telegram message(s)
        valid_articles = [a for a in top_5 if a.get('summary') and a['summary'] != "Summary generation failed."]
        if valid_articles:
            tz_tpe = timezone(timedelta(hours=8))
            now = datetime.now(tz_tpe).strftime('%Y-%m-%d %H:%M')
            
            header = f"📊 <b>今日金融重點快訊 ({now})</b>\n\n"
            messages = []
            current_msg = header
            
            for a in valid_articles:
                article_block = f"<i>Source: {a['source']}</i>\n\n{a['summary']}\n\n<a href='{a.get('url', '#')}'>閱讀原文 (Read more)</a>\n\n──────────────\n\n"
                
                # Check length limit (Telegram max is 4096 chars)
                if len(current_msg) + len(article_block) > 4000:
                    messages.append(current_msg)
                    current_msg = article_block
                else:
                    current_msg += article_block
                    
            if current_msg:
                messages.append(current_msg)
                
            for m in messages:
                self.send_telegram_message(m)

        return processed

if __name__ == "__main__":
    # Local test block to send previously saved news to Telegram
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    processor = AIProcessor()
    
    try:
        with open('data/news_20260223.json', 'r', encoding='utf-8') as f:
            saved_articles = json.load(f)
            
        logging.info(f"Loaded {len(saved_articles)} articles from data/news_20260223.json")
        
        # Sort by importance score descending and limit to top 5
        saved_articles.sort(key=lambda x: x.get('score', 0), reverse=True)
        top_5 = saved_articles[:5]
        
        valid_articles = [a for a in top_5 if a.get('summary') and a['summary'] != "Summary generation failed."]
        if valid_articles:
            tz_tpe = timezone(timedelta(hours=8))
            now = datetime.now(tz_tpe).strftime('%Y-%m-%d %H:%M')
            
            header = f"📊 <b>今日金融重點快訊 ({now})</b>\n\n"
            messages = []
            current_msg = header
            
            for a in valid_articles:
                # If reading old formatted jsons without zh_title, we gracefully just print the title.
                title_line = "" if "【標題】" in a['summary'] else f"<b>{a['title']}</b>\n"
                
                article_block = f"{title_line}<i>Source: {a['source']}</i>\n\n{a['summary']}\n\n<a href='{a.get('url', '#')}'>閱讀原文 (Read more)</a>\n\n──────────────\n\n"
                
                if len(current_msg) + len(article_block) > 4000:
                    messages.append(current_msg)
                    current_msg = article_block
                else:
                    current_msg += article_block
                    
            if current_msg:
                messages.append(current_msg)
                
            for m in messages:
                processor.send_telegram_message(m)
                
        logging.info("Telegram message sent successfully!")
    except FileNotFoundError:
        logging.error("File data/news_20260223.json not found.")
