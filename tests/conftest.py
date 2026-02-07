"""pytest 設定：將專案根目錄加入 Python path"""
import sys
from pathlib import Path

# 確保可以從 tests/ 目錄匯入專案模組
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
