import json
import logging
import os
from datetime import datetime
from typing import List, Dict

class StorageManager:
    def __init__(self, data_dir: str = 'data'):
        self.data_dir = data_dir
        if not os.path.exists(self.data_dir):
            os.makedirs(self.data_dir)
            logging.info(f"Created data directory: {self.data_dir}")

    def save_results(self, data: List[Dict]):
        """Saves current data to a daily JSON file."""
        date_str = datetime.now().strftime("%Y%MM%DD")
        filename = f"news_{date_str}.json"
        
        # Original instruction was yyyymmdd, let's fix the date format string
        date_str_fixed = datetime.now().strftime("%Y%m%d")
        filename = f"news_{date_str_fixed}.json"
        filepath = os.path.join(self.data_dir, filename)

        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
            logging.info(f"Successfully saved {len(data)} items to {filepath}")
        except Exception as e:
            logging.error(f"Failed to save data to {filepath}: {e}")
