/**
 * 秀泰影城 API 代理 — Cloudflare Worker
 *
 * 用途：將來自 Streamlit Cloud (AWS IP) 的請求，透過 Cloudflare 邊緣網路
 *       轉發到 capi.showtimes.com.tw，繞過 Cloudflare 對雲端 IP 的封鎖。
 *
 * 部署步驟：
 *   1. 安裝 Wrangler CLI:  npm install -g wrangler
 *   2. 登入 Cloudflare:    wrangler login
 *   3. 部署 Worker:        wrangler deploy
 *   4. 部署成功後會取得 URL，例如:
 *      https://showtime-proxy.<your-subdomain>.workers.dev
 *   5. 將此 URL 填入 Streamlit Cloud 的 Secrets 設定：
 *      SHOWTIME_WORKER_URL = "https://showtime-proxy.<your-subdomain>.workers.dev"
 */

const ALLOWED_ORIGIN = "https://capi.showtimes.com.tw";

export default {
  async fetch(request) {
    // ---- CORS preflight ----
    if (request.method === "OPTIONS") {
      return new Response(null, {
        headers: {
          "Access-Control-Allow-Origin": "*",
          "Access-Control-Allow-Methods": "GET, OPTIONS",
          "Access-Control-Allow-Headers": "Content-Type",
        },
      });
    }

    // ---- 解析 target 參數 ----
    const url = new URL(request.url);
    const target = url.searchParams.get("target");

    if (!target) {
      return jsonResponse(400, {
        error: "Missing 'target' query parameter",
        usage: "?target=https://capi.showtimes.com.tw/1/programs",
      });
    }

    // 安全性：只允許代理到秀泰 API
    if (!target.startsWith(ALLOWED_ORIGIN + "/")) {
      return jsonResponse(403, {
        error: "Target URL not allowed. Only capi.showtimes.com.tw is permitted.",
      });
    }

    // ---- 轉發請求 ----
    try {
      const apiResp = await fetch(target, {
        headers: {
          "Accept": "application/json, text/plain, */*",
          "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
          "Origin": "https://www.showtimes.com.tw",
          "Referer": "https://www.showtimes.com.tw/",
          "User-Agent":
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) " +
            "AppleWebKit/537.36 (KHTML, like Gecko) " +
            "Chrome/131.0.0.0 Safari/537.36",
        },
      });

      const body = await apiResp.text();

      return new Response(body, {
        status: apiResp.status,
        headers: {
          "Content-Type": "application/json; charset=utf-8",
          "Access-Control-Allow-Origin": "*",
          "X-Proxy-Status": "ok",
        },
      });
    } catch (err) {
      return jsonResponse(502, {
        error: "Failed to fetch from upstream API",
        detail: err.message,
      });
    }
  },
};

function jsonResponse(status, body) {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Access-Control-Allow-Origin": "*",
    },
  });
}
