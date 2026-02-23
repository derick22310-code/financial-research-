import json
import logging
import os
import requests
from typing import List, Dict
import google.generativeai as genai
from datetime import datetime
import pytz

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class AIProcessor:
    def __init__(self, config_path: str = 'config.json'):
        with open(config_path, 'r', encoding='utf-8') as f:
            self.config = json.load(f)
        self.keywords = [k.lower() for k in self.config.get('keywords', [])]
        
        api_key = os.environ.get("GOOGLE_API_KEY")
        self.tg_token = os.environ.get("TG_TOKEN")
        self.tg_chat_id = os.environ.get("TG_CHAT_ID")
        
        if not self.tg_token or not self.tg_chat_id:
            logging.info("TG_TOKEN or TG_CHAT_ID not set. Telegram notifications are disabled.")

        if not api_key:
             logging.warning("GOOGLE_API_KEY environment variable not set. API calls will fail.")
        else:
             genai.configure(api_key=api_key)
             
        # Using Gemini 1.5 Flash as requested (or standard flash mapping)
        self.model = genai.GenerativeModel('gemini-1.5-flash')

    def filter_by_keywords(self, articles: List[Dict]) -> List[Dict]:
        """Filters articles by keywords."""
        filtered_articles = []
        for article in articles:
            title_lower = article['title'].lower()
            if any(keyword in title_lower for keyword in self.keywords):
                filtered_articles.append(article)
        
        logging.info(f"Filtered {len(articles)} articles down to {len(filtered_articles)} based on keywords.")
        return filtered_articles

    def summarize_and_score(self, article: Dict) -> Dict:
        """Uses Gemini to summarize, translate, and score the article."""
        prompt = f"""
        Analyze the following financial news headline.
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
            
            # Requested format
            article['summary'] = f"【標題】：{data.get('zh_title', article['title'])}\n\n摘要：{data.get('zh_summary', 'N/A')}\n\nOriginal Summary：{data.get('en_summary', 'N/A')}"
            
            logging.info(f"Successfully processed: {article['title'][:30]}... (Score: {article['score']})")
        except Exception as e:
            logging.error(f"Failed to process article '{article['title'][:30]}...': {e}")
            article['score'] = 0
            article['summary'] = ""
            
        return article

    def send_telegram_message(self, message: str):
        """Sends a message to the configured Telegram chat."""
        if not self.tg_token or not self.tg_chat_id:
            logging.error("Telegram credentials missing, cannot send.")
            return False
            
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
                return False
            else:
                return True
        except Exception as e:
            logging.error(f"Error sending Telegram message: {e}")
            return False

def read_latest_json(data_dir='data'):
    import glob
    # Find the latest json file matched by pattern
    list_of_files = glob.glob(f'{data_dir}/news_*.json')
    if not list_of_files:
        return []
    latest_file = max(list_of_files, key=os.path.getctime)
    logging.info(f"Reading data from: {latest_file}")
    with open(latest_file, 'r', encoding='utf-8') as f:
        return json.load(f)

if __name__ == "__main__":
    logging.info("Starting Nuclear Fix AI Processor...")
    processor = AIProcessor()
    
    # 1. Read raw JSON data
    articles = read_latest_json()
    if not articles:
        logging.info("No articles found in data directory.")
        exit(0)
        
    logging.info(f"Read {len(articles)} raw articles.")
    
    # 2. Filter
    filtered = processor.filter_by_keywords(articles)
    
    # 3. Process (Score and Summarize)
    logging.info("Calling Gemini API for processing...")
    processed = []
    for article in filtered:
        processed_article = processor.summarize_and_score(article)
        processed.append(processed_article)
        
    # 4. Sort and Top 5
    processed.sort(key=lambda x: x.get('score', 0), reverse=True)
    top_5 = processed[:5]
    
    valid_articles = [a for a in top_5 if a.get('summary')]
    
    # 5. Integrate and Send
    if valid_articles:
        taipei_tz = pytz.timezone('Asia/Taipei')
        now_str = datetime.now(taipei_tz).strftime('%Y-%m-%d %H:%M')
        
        final_message = f"📊 <b>今日金融重點快訊 (台北時間: {now_str})</b>\n\n"
        
        for a in valid_articles:
            final_message += f"<b>{a['summary']}</b>\n"
            final_message += f"<i>來源: {a['source']}</i> | <a href='{a.get('url', '#')}'>閱讀原文</a>\n"
            final_message += "──────────────\n\n"
            
        success = processor.send_telegram_message(final_message)
        if success:
            logging.info("FINAL_SUCCESS: Message sent to Telegram")
    else:
        logging.info("No valid articles to send after processing.")
