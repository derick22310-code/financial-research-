import json
import logging
import os
import time
import requests
from typing import List, Dict
from openai import OpenAI
from datetime import datetime
import pytz
import asyncio

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class AIProcessor:
    def __init__(self, config_path: str = 'config.json'):
        with open(config_path, 'r', encoding='utf-8') as f:
            self.config = json.load(f)
        self.keywords = [k.lower() for k in self.config.get('keywords', [])]

        api_key = os.environ.get("OPENROUTER_API_KEY")
        self.tg_token = os.environ.get("TG_TOKEN")
        self.tg_chat_id = os.environ.get("TG_CHAT_ID")

        if not api_key:
            logging.error("CRITICAL: OPENROUTER_API_KEY is NOT set in environment. All API calls will fail.")
        else:
            masked = api_key[:8] + "..." + api_key[-4:] if len(api_key) > 12 else "***"
            logging.info(f"OPENROUTER_API_KEY loaded successfully (masked: {masked})")

        if not self.tg_token:
            logging.error("CRITICAL: TG_TOKEN is NOT set in environment.")
        if not self.tg_chat_id:
            logging.error("CRITICAL: TG_CHAT_ID is NOT set in environment.")

        self.client = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=api_key or "missing"
        )

    def filter_by_keywords(self, articles: List[Dict]) -> List[Dict]:
        filtered = []
        for article in articles:
            title_lower = article['title'].lower()
            if any(k in title_lower for k in self.keywords):
                filtered.append(article)
        logging.info(f"Filtered down to {len(filtered)} articles from {len(articles)}.")
        return filtered

    def process_article(self, article: Dict) -> Dict:
        prompt = f"""你是一位專業的金融分析師。請分析以下新聞標題，並以 JSON 格式回覆。

新聞標題 (Title): {article['title']}
來源 (Source): {article['source']}

你必須全程使用繁體中文進行摘要，否則程式會出錯。

請按照以下步驟進行分析：
1. 針對這則新聞對全球金融市場的重要性進行評分 (1-10分)。
2. 將標題翻譯成繁體中文。
3. 撰寫約 80 字的繁體中文摘要（包含核心事件、市場影響、關鍵數據）。
4. 提供原本的英文摘要 (Original Summary, around 60 words)。

你必須只回傳以下格式的 JSON，不要包含任何其他文字：
{{
    "score": 8,
    "zh_title": "中文標題翻譯",
    "zh_summary": "中文摘要內容",
    "en_summary": "English summary content"
}}"""

        try:
            logging.info(f"Sending request to OpenRouter for: {article['title'][:50]}...")
            response = self.client.chat.completions.create(
                model="google/gemini-2.0-flash-lite-preview-02-05:free",
                messages=[
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
                extra_headers={
                    "HTTP-Referer": "https://github.com/",
                    "X-Title": "Financial Researcher"
                }
            )
            text = response.choices[0].message.content
            if text:
                text = text.replace("```json", "").replace("```", "").strip()
                data = json.loads(text)
                article['score'] = data.get('score', 0)
                article['zh_title'] = data.get('zh_title', article['title'])
                article['zh_summary'] = data.get('zh_summary', 'N/A')
                article['en_summary'] = data.get('en_summary', 'N/A')
                logging.info(f"OK: {article['zh_title']} (Score: {article['score']})")
            else:
                raise ValueError("Empty response from API")
        except json.JSONDecodeError as e:
            logging.error(f"JSON parse error for '{article['title'][:40]}': {e}. Raw text: {text[:200] if text else 'None'}")
            article['score'] = 0
            article['zh_title'] = article.get('title', '')
            article['zh_summary'] = "摘要生成失敗 (JSON 解析錯誤)"
            article['en_summary'] = "N/A"
        except Exception as e:
            error_type = type(e).__name__
            logging.error(f"API ERROR [{error_type}] for '{article['title'][:40]}': {e}")
            article['score'] = 0
            article['zh_title'] = article.get('title', '')
            article['zh_summary'] = f"摘要生成失敗 ({error_type})"
            article['en_summary'] = "N/A"

        # Rate limit: free tier requires delay between requests
        time.sleep(2)
        return article


def send_telegram_bulk(token: str, chat_id: str, text: str):
    if not token or not chat_id:
        logging.error("Missing Telegram credentials.")
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML"
    }
    try:
        resp = requests.post(url, json=payload, timeout=15)
        if resp.status_code == 200:
            logging.info("[SUCCESS] Integrated Chinese report sent.")
        else:
            logging.error(f"Telegram send failed ({resp.status_code}): {resp.text}")
    except Exception as e:
        logging.error(f"Telegram request exception: {e}")


if __name__ == "__main__":
    from scraper import NewsScraper
    from storage import StorageManager

    async def run_all():
        logging.info("=== AI Processor (OpenRouter Edition) Starting ===")
        logging.info(f"Environment check: OPENROUTER_API_KEY={'SET' if os.environ.get('OPENROUTER_API_KEY') else 'MISSING'}")
        logging.info(f"Environment check: TG_TOKEN={'SET' if os.environ.get('TG_TOKEN') else 'MISSING'}")
        logging.info(f"Environment check: TG_CHAT_ID={'SET' if os.environ.get('TG_CHAT_ID') else 'MISSING'}")

        scraper = NewsScraper()
        ai = AIProcessor()
        storage = StorageManager()

        # Phase 1: Scrape
        raw_articles = await scraper.scrape_all()
        logging.info(f"Scraped {len(raw_articles)} raw articles.")

        # Phase 2: Filter by keywords
        filtered = ai.filter_by_keywords(raw_articles)

        # Phase 3: Process each article with AI (score + translate + summarize)
        logging.info("Calling OpenRouter API (Gemini Flash Lite) for processing...")
        processed_list = []
        for a in filtered:
            processed_list.append(ai.process_article(a))

        # Phase 4: Sort by score descending, keep top 5
        processed_list.sort(key=lambda x: x.get('score', 0), reverse=True)
        top_5 = processed_list[:5]
        logging.info(f"Top {len(top_5)} articles selected for Telegram notification.")

        # Phase 5: Save all results
        storage.save_results(processed_list)

        # Phase 6: Build and send integrated Chinese Telegram message
        if top_5:
            taipei_tz = pytz.timezone('Asia/Taipei')
            now_str = datetime.now(taipei_tz).strftime('%Y-%m-%d %H:%M')

            msg = f"📊 <b>今日金融重點快訊 (台北時間: {now_str})</b>\n\n"
            for item in top_5:
                zh_t = item.get('zh_title') or item.get('title', '')
                zh_s = item.get('zh_summary', 'N/A')
                en_s = item.get('en_summary', 'N/A')
                src  = item.get('source', '')
                url  = item.get('url', '#')

                msg += f"<b>【標題】：{zh_t}</b>\n"
                msg += f"摘要：{zh_s}\n\n"
                msg += f"Original Summary：{en_s}\n"
                msg += f"<i>來源: {src}</i> | <a href='{url}'>閱讀原文</a>\n"
                msg += "──────────────\n\n"

            send_telegram_bulk(ai.tg_token, ai.tg_chat_id, msg)
        else:
            logging.info("No articles to send after processing.")

    asyncio.run(run_all())
