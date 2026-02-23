import json
import logging
import os
import requests
from typing import List, Dict
import google.generativeai as genai
from datetime import datetime
import pytz
import asyncio

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class AIProcessor:
    def __init__(self, config_path: str = 'config.json'):
        with open(config_path, 'r', encoding='utf-8') as f:
            self.config = json.load(f)
        self.keywords = [k.lower() for k in self.config.get('keywords', [])]
        
        api_key = os.environ.get("GOOGLE_API_KEY")
        self.tg_token = os.environ.get("TG_TOKEN")
        self.tg_chat_id = os.environ.get("TG_CHAT_ID")
        
        if not api_key:
             logging.warning("GOOGLE_API_KEY is missing.")
        else:
             genai.configure(api_key=api_key)
             
        self.model = genai.GenerativeModel('gemini-1.5-flash')

    def filter_by_keywords(self, articles: List[Dict]) -> List[Dict]:
        filtered = []
        for article in articles:
            title_lower = article['title'].lower()
            if any(k in title_lower for k in self.keywords):
                filtered.append(article)
        return filtered

    def process_article(self, article: Dict) -> Dict:
        prompt = f"""
        Analyze the following financial news.
        Title: {article['title']}
        Source: {article['source']}

        你必須全程使用繁體中文進行摘要，否則程式會出錯。
        1. 針對這則新聞對金融市場的重要性進行評分 (1-10分)。
        2. 將標題翻譯成繁體中文。
        3. 撰寫約 80 字的繁體中文摘要。
        4. 提供原本的英文摘要 (Original Summary)。

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
            article['zh_title'] = data.get('zh_title', article['title'])
            article['zh_summary'] = data.get('zh_summary', 'N/A')
            article['en_summary'] = data.get('en_summary', 'N/A')
            logging.info(f"Processed: {article['zh_title']} (Score: {article['score']})")
        except Exception as e:
            logging.error(f"Error processing article: {e}")
            article['score'] = 0
            article['zh_title'] = article.get('title', '')
            article['zh_summary'] = "摘要生成失敗"
            article['en_summary'] = "N/A"
        return article

def send_telegram_bulk(token: str, chat_id: str, text: str):
    if not token or not chat_id:
        logging.error("Missing TG credentials.")
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML"
    }
    resp = requests.post(url, json=payload, timeout=10)
    if resp.status_code == 200:
        logging.info("[SUCCESS] Integrated Chinese report sent.")
    else:
        logging.error(f"TG send failed: {resp.text}")

if __name__ == "__main__":
    from scraper import NewsScraper
    from storage import StorageManager

    async def run_all():
        logging.info("Starting AI Processor run...")
        scraper = NewsScraper()
        ai = AIProcessor()
        storage = StorageManager()
        
        raw_articles = await scraper.scrape_all()
        logging.info(f"Scraped {len(raw_articles)} raw articles.")
        
        filtered = ai.filter_by_keywords(raw_articles)
        logging.info(f"Filtered down to {len(filtered)} articles.")
        
        processed_list = []
        for a in filtered:
            processed_list.append(ai.process_article(a))
            
        # 關鍵修正：在 if __name__ == "__main__": 區塊中，必須先將所有新聞按分數排序，僅取前 5 名。
        processed_list.sort(key=lambda x: x.get('score', 0), reverse=True)
        top_5 = processed_list[:5]
        
        # 儲存
        storage.save_results(processed_list)
        
        # 訊息整合：將這 5 則中文摘要結合成一條長訊息，標題要有台北時間。
        if top_5:
            taipei_tz = pytz.timezone('Asia/Taipei')
            now_str = datetime.now(taipei_tz).strftime('%Y-%m-%d %H:%M')
            
            msg = f"📊 <b>今日金融重點快訊 (台北時間: {now_str})</b>\n\n"
            for item in top_5:
                zh_t = item.get('zh_title') or item.get('title')
                zh_s = item.get('zh_summary', 'N/A')
                en_s = item.get('en_summary', 'N/A')
                
                msg += f"<b>【標題】：{zh_t}</b>\n"
                msg += f"摘要：{zh_s}\n\n"
                msg += f"Original Summary：{en_s}\n"
                msg += f"<i>來源: {item.get('source')}</i> | <a href='{item.get('url', '#')}'>閱讀原文</a>\n"
                msg += "──────────────\n\n"
                
            send_telegram_bulk(ai.tg_token, ai.tg_chat_id, msg)
        else:
            logging.info("No articles to send.")

    asyncio.run(run_all())
