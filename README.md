# 電影時刻表查詢系統

查詢台灣**威秀影城**與**秀泰影城**電影場次的 Web 應用程式。
透過爬蟲即時擷取官方網站資料，提供統一的查詢介面。

## 功能

- 查詢威秀影城 / 秀泰影城的電影場次時刻表
- 支援多間影城同時查詢
- 支援依「特定日期」或「日期區間」篩選場次

## 環境需求

- Python 3.11+

## 安裝

```bash
# 建立並啟用虛擬環境
py -3.11 -m venv .venv
.\.venv\Scripts\activate

# 安裝 Python 套件
pip install -r requirements.txt

# 安裝 Playwright 瀏覽器（必要步驟）
playwright install chromium
```

## 啟動

```bash
streamlit run app.py
```

## 技術棧

| 套件 | 用途 |
|------|------|
| Streamlit | Web UI 框架 |
| Playwright | 瀏覽器自動化爬蟲 |
| BeautifulSoup4 | HTML 解析 |

