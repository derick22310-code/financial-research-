import json
import logging
import os
import time
import requests
from typing import List, Dict
from google import genai
from google.genai import types
from datetime import datetime
import pytz
import asyncio

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# ── 配額管理常數 ──
PRIMARY_MODEL = "gemini-2.5-flash"
BACKUP_MODEL = "gemini-2.5-flash-lite"
MAX_ARTICLES_PER_RUN = 50

SYSTEM_INSTRUCTION = "你是一位頂級全球金融分析師，精通總經與股市連動。全程使用繁體中文，輸出結構化分析，拒絕廢話。"


class AIProcessor:
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
        self.current_model = PRIMARY_MODEL

        logging.info("📋 配置資訊：")
        logging.info(f"   主模型: {PRIMARY_MODEL}")
        logging.info(f"   備用模型: {BACKUP_MODEL}")
        logging.info(f"   單次處理上限: {MAX_ARTICLES_PER_RUN} 篇")

    def filter_by_keywords(self, articles: List[Dict]) -> List[Dict]:
        filtered = []
        for article in articles:
            title_lower = article['title'].lower()
            if any(k in title_lower for k in self.keywords):
                filtered.append(article)
        logging.info(f"Filtered down to {len(filtered)} articles from {len(articles)}.")
        return filtered

    def batch_analyze(self, articles: List[Dict]) -> str:
        """將所有新聞標題合併成清單，一次性發送給 Gemini 進行全局分析"""

        # 建立新聞清單文本
        article_list_string = ""
        for i, a in enumerate(articles, 1):
            article_list_string += f"標題: {a['title']} | 來源: {a.get('source', '未知')} | 連結: {a.get('url', '#')}\n"

        prompt = f"""
請分析以下今日新聞清單，並嚴格依序輸出以下三個區塊：

【一、全球市場重點摘要 (3-5點)】
提取最具影響力的核心事件（必須優先提取美伊戰爭、中東衝突、原油/黃金波動等重大地緣政治新聞）。每點敘述後必須附上來源連結。
格式：[重點敘述] (來源: [新聞來源] - [連結])

【二、主要指數觀測】
結合新聞評估主要股指走勢與影響（涵蓋 S&P 500、NASDAQ、日經、台灣加權、恆生、中國 A50）。

【三、市場動向分析】
請嚴格使用以下結構條列呈現重點事件：
▪️ 事件：[新聞事件]
▪️ 影響：[影響市場]
▪️ 標的：[涉及指數、期貨或公司]
▪️ 波動：[當日漲跌幅或預估]
▪️ 來源：[來源名稱] | [連結]
──────────────
(重複上述格式 3-5 次)

新聞清單：
{article_list_string}
"""

        # 嘗試主模型，失敗則切換備用
        for model_id in [PRIMARY_MODEL, BACKUP_MODEL]:
            try:
                logging.info(f"📡 發送批次分析請求至 Gemini ({model_id})，共 {len(articles)} 則新聞...")
                response = self.client.models.generate_content(
                    model=model_id,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=SYSTEM_INSTRUCTION,
                    )
                )
                text = response.text
                if not text:
                    raise ValueError("Empty response from Gemini")

                logging.info(f"✅ 批次分析完成！模型: {model_id}，回應長度: {len(text)} 字")
                self.current_model = model_id
                return text

            except Exception as e:
                error_msg = str(e)
                error_type = type(e).__name__
                logging.warning(f"🚨 模型 [{model_id}] 失敗: [{error_type}] {error_msg}")

                if "429" in error_msg or "RESOURCE_EXHAUSTED" in error_msg:
                    logging.info("速率限制，等待 5 秒後嘗試備用模型...")
                    time.sleep(5)
                    continue
                elif model_id == PRIMARY_MODEL:
                    logging.info("嘗試備用模型...")
                    time.sleep(2)
                    continue
                else:
                    break

        logging.error("❌ 所有模型皆失敗，無法生成分析報告。")
        return ""


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
        logging.info("=== AI Processor (Batch Analysis Edition) Starting ===")
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
        if len(filtered) > MAX_ARTICLES_PER_RUN:
            logging.info(f"⚠️ 文章數 {len(filtered)} 超過上限，僅處理前 {MAX_ARTICLES_PER_RUN} 篇")
            filtered = filtered[:MAX_ARTICLES_PER_RUN]

        if not filtered:
            logging.info("No articles matched keywords. Exiting.")
            return

        # Phase 4: Batch analyze with Gemini (single API call)
        analysis_text = ai.batch_analyze(filtered)

        # Phase 5: Save
        storage.save_results(filtered)

        # Phase 6: Build and send Telegram message
        if analysis_text:
            taipei_tz = pytz.timezone('Asia/Taipei')
            now_str = datetime.now(taipei_tz).strftime('%Y-%m-%d %H:%M')

            msg = f"📊 今日金融重點快訊 (台北時間: {now_str})\n\n"
            msg += analysis_text

            send_telegram_bulk(ai.tg_token, ai.tg_chat_id, msg)
        else:
            logging.info("No analysis generated. Skipping Telegram.")

    asyncio.run(run_all())
