/**
 * 秀泰影城 API 代理 — Cloudflare Worker
 *
 * 用途：將來自 Streamlit Cloud (AWS IP) 的請求，透過 Cloudflare 邊緣網路
 *       轉發到 capi.showtimes.com.tw，繞過 Cloudflare 對雲端 IP 的封鎖。
 *
 * 安全機制：
 *   - 僅允許代理到 capi.showtimes.com.tw
 *   - 可選的 Bearer Token 認證（透過 WORKER_AUTH_SECRET 環境變數）
 *   - IP 級別的速率限制（每分鐘 60 次請求）
 *   - 不洩漏內部錯誤細節
 *
 * 部署步驟：
 *   1. 安裝 Wrangler CLI:  npm install -g wrangler
 *   2. 登入 Cloudflare:    wrangler login
 *   3. (選填) 設定認證密鑰: wrangler secret put WORKER_AUTH_SECRET
 *   4. 部署 Worker:        wrangler deploy
 *   5. 部署成功後會取得 URL，例如:
 *      https://showtime-proxy.<your-subdomain>.workers.dev
 *   6. 將此 URL 填入 Streamlit Cloud 的 Secrets 設定：
 *      SHOWTIME_WORKER_URL = "https://showtime-proxy.<your-subdomain>.workers.dev"
 *      SHOWTIME_WORKER_SECRET = "<你設定的密鑰>"  (若有設定步驟 3)
 */

const ALLOWED_ORIGIN = "https://capi.showtimes.com.tw";

// --- 速率限制設定 ---
const RATE_LIMIT = {
  MAX_REQUESTS: 60,       // 每個時間窗口最大請求數
  WINDOW_MS: 60 * 1000,   // 時間窗口（1 分鐘）
};

// 簡易 IP 級別速率限制（記憶體內，Worker 實例回收時重置）
const rateLimitMap = new Map();

/**
 * 檢查 IP 是否超過速率限制
 * @param {string} ip - 客戶端 IP
 * @returns {boolean} 是否被限制
 */
function isRateLimited(ip) {
  const now = Date.now();
  const record = rateLimitMap.get(ip);

  if (!record || now - record.windowStart > RATE_LIMIT.WINDOW_MS) {
    rateLimitMap.set(ip, { windowStart: now, count: 1 });
    return false;
  }

  record.count++;
  return record.count > RATE_LIMIT.MAX_REQUESTS;
}

/**
 * 清理過期的速率限制記錄（避免記憶體洩漏）
 */
function cleanupRateLimits() {
  const now = Date.now();
  for (const [ip, record] of rateLimitMap) {
    if (now - record.windowStart > RATE_LIMIT.WINDOW_MS) {
      rateLimitMap.delete(ip);
    }
  }
}

/**
 * 產生 CORS 標頭
 * TODO: 正式環境應將 Access-Control-Allow-Origin 限制為你的 Streamlit Cloud 網域
 */
function corsHeaders() {
  return {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, X-Worker-Auth",
  };
}

/**
 * 產生 JSON 回應
 */
function jsonResponse(status, body) {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      ...corsHeaders(),
    },
  });
}

export default {
  async fetch(request, env) {
    // ---- CORS preflight ----
    if (request.method === "OPTIONS") {
      return new Response(null, {
        headers: corsHeaders(),
      });
    }

    // ---- 速率限制 ----
    const clientIP = request.headers.get("CF-Connecting-IP") || "unknown";
    cleanupRateLimits();
    if (isRateLimited(clientIP)) {
      return jsonResponse(429, {
        error: "Too many requests. Please try again later.",
      });
    }

    // ---- 認證（若有設定 WORKER_AUTH_SECRET）----
    if (env.WORKER_AUTH_SECRET) {
      const authHeader = request.headers.get("X-Worker-Auth") || "";
      if (authHeader !== env.WORKER_AUTH_SECRET) {
        return jsonResponse(401, { error: "Unauthorized" });
      }
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
          ...corsHeaders(),
          "X-Proxy-Status": "ok",
        },
      });
    } catch (err) {
      // 不洩漏內部錯誤細節，僅回傳通用錯誤訊息
      console.error("Upstream API error:", err.message);
      return jsonResponse(502, {
        error: "Upstream API request failed",
      });
    }
  },
};
