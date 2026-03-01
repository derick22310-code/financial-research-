import json
import logging
import os
import time
import requests
from typing import List, Dict
from google import genai
from datetime import datetime
import pytz
import asyncio

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class AIProcessor:
    # ── 配額管理常數 ──
    PRIMARY_MODEL = "gemini-2.5-flash"          # 主模型（性能好，250 請求/天）
    BACKUP_MODEL = "gemini-2.5-flash-lite"      # 備用模型（額度高，1000 請求/天）
    MAX_ARTICLES_PER_RUN = 50                    # 單次最多處理篇數
    QUOTA_PER_RUN = 62                           # 單次配額上限（250 / 4 時段 ≈ 62）

    def __init__(self, config_path: str = 'config.json'):
        with open(config_path, 'r', encoding='utf-8') as f:
            self.config = json.load(f)
        self.keywords = [k.lower() for k in self.config.get('keywords', [])]

        api_key = os.environ.get("GOOGLE_API_KEY")
        self.tg_token = os.environ.get("TG_TOKEN")
        self.tg_chat_id = os.environ.get("TG_CHAT_ID")

        if not api_key:
            logging.error("CRITICAL: GOOGLE_API_KEY is NOT set.")
        else:
            masked = api_key[:8] + "..." + api_key[-4:] if len(api_key) > 12 else "***"
            logging.info(f"GOOGLE_API_KEY loaded (masked: {masked})")

        self.client = genai.Client(api_key=api_key)

        # 運行時計數器
        self.api_call_count = 0
        self.current_model = self.PRIMARY_MODEL

        # 印出配置資訊
        logging.info("📋 配置資訊：")
        logging.info(f"   主模型: {self.PRIMARY_MODEL} (250 請求/天)")
        logging.info(f"   備用模型: {self.BACKUP_MODEL} (1000 請求/天)")
        logging.info(f"   單次處理上限: {self.MAX_ARTICLES_PER_RUN} 篇")
        logging.info(f"   每次執行配額: {self.QUOTA_PER_RUN} 請求")

    def filter_by_keywords(self, articles: List[Dict]) -> List[Dict]:
        filtered = []
        for article in articles:
            title_lower = article['title'].lower()
            if any(k in title_lower for k in self.keywords):
                filtered.append(article)
        logging.info(f"Filtered down to {len(filtered)} articles from {len(articles)}.")
        return filtered

    def _switch_to_backup(self, reason: str):
        """切換到備用模型"""
        if self.current_model != self.BACKUP_MODEL:
            logging.warning(f"⚠️ 切換到備用模型！原因: {reason}")
            logging.warning(f"   {self.current_model} → {self.BACKUP_MODEL}")
            self.current_model = self.BACKUP_MODEL

    def process_article(self, article: Dict, index: int) -> Dict:
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

        # 情況 A：預防性切換 — 當單次使用超過配額時
        if self.api_call_count >= self.QUOTA_PER_RUN:
            self._switch_to_backup(f"已達單次配額上限 ({self.QUOTA_PER_RUN} 請求)")

        max_retries = 2
        for attempt in range(max_retries):
            try:
                logging.info(f"Calling Gemini ({self.current_model}) [{index}]: {article['title'][:50]}...")
                response = self.client.models.generate_content(
                    model=self.current_model,
                    contents=prompt
                )
                self.api_call_count += 1

                text = response.text
                if not text:
                    raise ValueError("Empty response from Gemini")

                text = text.replace("```json", "").replace("```", "").strip()
                data = json.loads(text)
                article['score'] = data.get('score', 0)
                article['zh_title'] = data.get('zh_title', article['title'])
                article['zh_summary'] = data.get('zh_summary', 'N/A')
                article['en_summary'] = data.get('en_summary', 'N/A')
                logging.info(f"✅ OK [{index}]: {article['zh_title']} (Score: {article['score']})")

                time.sleep(5)
                return article

            except Exception as e:
                error_msg = str(e)
                error_type = type(e).__name__

                # 情況 B：緊急切換 — 遇到 429 錯誤時
                if "429" in error_msg or "RESOURCE_EXHAUSTED" in error_msg:
                    logging.warning(f"🚨 429 速率限制！模型: {self.current_model}")
                    if self.current_model == self.PRIMARY_MODEL:
                        self._switch_to_backup("429 速率限制觸發")
                        time.sleep(3)
                        continue  # 用備用模型重試
                    else:
                        logging.error(f"備用模型也被限速，等待 30 秒後重試...")
                        time.sleep(30)
                        continue
                else:
                    logging.error(f"❌ API ERROR [{error_type}] [{index}]: {e}")
                    break

        # 所有嘗試都失敗
        article['score'] = 0
        article['zh_title'] = article.get('title', '')
        article['zh_summary'] = f"摘要生成失敗 ({error_type}: {str(e)[:80]})"
        article['en_summary'] = "N/A"
        time.sleep(5)
        return article


def send_telegram_bulk(token, chat_id, text):
    if not token or not chat_id:
        logging.error("Missing Telegram credentials.")
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
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
        logging.info("=== AI Processor (Smart Quota Edition) Starting ===")
        logging.info(f"Env: GOOGLE_API_KEY={'SET' if os.environ.get('GOOGLE_API_KEY') else 'MISSING'}")
        logging.info(f"Env: TG_TOKEN={'SET' if os.environ.get('TG_TOKEN') else 'MISSING'}")
        logging.info(f"Env: TG_CHAT_ID={'SET' if os.environ.get('TG_CHAT_ID') else 'MISSING'}")

        scraper = NewsScraper()
        ai = AIProcessor()
        storage = StorageManager()

        # Phase 1: Scrape
        raw_articles = await scraper.scrape_all()
        logging.info(f"Scraped {len(raw_articles)} raw articles.")

        # Phase 2: Filter
        filtered = ai.filter_by_keywords(raw_articles)

        # Phase 3: Cap at MAX_ARTICLES_PER_RUN
        if len(filtered) > ai.MAX_ARTICLES_PER_RUN:
            logging.info(f"⚠️ 文章數 {len(filtered)} 超過上限，僅處理前 {ai.MAX_ARTICLES_PER_RUN} 篇")
            filtered = filtered[:ai.MAX_ARTICLES_PER_RUN]

        # API 使用預估
        estimated_daily = len(filtered) * 4  # 4 time slots per day
        logging.info(f"📊 API 使用預估：本次 {len(filtered)} 請求 | 今日預估 {estimated_daily}/250 請求")

        # Phase 4: Process with Gemini (score + translate + summarize)
        logging.info("Calling Gemini API for processing...")
        processed_list = []
        for idx, a in enumerate(filtered, 1):
            processed_list.append(ai.process_article(a, idx))

        # Phase 5: Sort by score, keep top 5
        processed_list.sort(key=lambda x: x.get('score', 0), reverse=True)
        top_5 = processed_list[:5]
        logging.info(f"Top {len(top_5)} articles selected.")

        # Phase 6: Save
        storage.save_results(processed_list)

        logging.info(f"✅ 處理完成！本次共使用 {ai.api_call_count} 次 API 請求")

        # Phase 7: Build and send Telegram message
        if top_5:
            taipei_tz = pytz.timezone('Asia/Taipei')
            now_str = datetime.now(taipei_tz).strftime('%Y-%m-%d %H:%M')

            msg = f"📊 <b>今日金融重點快訊 (台北時間: {now_str})</b>\n\n"
            for item in top_5:
                zh_t = item.get('zh_title') or item.get('title', '')
                zh_s = item.get('zh_summary', 'N/A')
                en_s = item.get('en_summary', 'N/A')
                src = item.get('source', '')
                url = item.get('url', '#')

                msg += f"<b>【標題】：{zh_t}</b>\n"
                msg += f"摘要：{zh_s}\n\n"
                msg += f"Original Summary：{en_s}\n"
                msg += f"<i>來源: {src}</i> | <a href='{url}'>閱讀原文</a>\n"
                msg += "──────────────\n\n"

            send_telegram_bulk(ai.tg_token, ai.tg_chat_id, msg)
        else:
            logging.info("No articles to send.")

    asyncio.run(run_all())
