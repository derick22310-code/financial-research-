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
             
        # 關鍵修正：加入 system_instruction，從根本鎖定語言
        self.model = genai.GenerativeModel(
            model_name='gemini-1.5-flash',
            system_instruction="你是一位專業的金融分析師。你必須『全程』使用『繁體中文』回答，禁止使用英文撰寫摘要內容。輸出格式必須嚴格遵守 JSON。"
        )

    def process_article(self, article: Dict) -> Dict:
        # 簡化 Prompt，讓指令更清晰
        prompt = f"""
        請分析以下新聞並將結果翻譯為繁體中文：
        標題：{article['title']}
        來源：{article['source']}

        JSON 格式要求：
        {{
            "score": 評分(1-10),
            "zh_title": "繁體中文標題",
            "zh_summary": "約 80 字的繁體中文深入摘要",
            "en_summary": "原本的英文摘要"
        }}
        """
        try:
            # 這裡不變，維持 JSON 解析邏輯
            response = self.model.generate_content(prompt)
            text = response.text.replace("```json", "").replace("```", "").strip()
            data = json.loads(text)
            
            # 確保抓到的是中文欄位
            article['score'] = data.get('score', 0)
            article['zh_title'] = data.get('zh_title') or article.get('title')
            article['zh_summary'] = data.get('zh_summary') or "翻譯失敗"
            article['en_summary'] = data.get('en_summary') or "N/A"
            
            logging.info(f"Processed in Chinese: {article['zh_title']}")
        except Exception as e:
            logging.error(f"AI Processing failed: {e}")
            article['score'] = 0
            article['zh_title'] = article.get('title')
            article['zh_summary'] = "自動摘要失敗"
            article['en_summary'] = "N/A"
        return article
