from flask import Flask, request, jsonify, Response, render_template_string
import requests
import os
from datetime import datetime
from collections import deque
import threading

app = Flask(__name__)

# --- 配置 ---
PROXY_URL = os.environ.get("PROXY_URL")
API_KEY = os.environ.get("API_KEY")
MY_ACCESS_KEY = os.environ.get("MY_ACCESS_KEY")
MAX_RETRIES = int(os.environ.get("MAX_RETRIES", "3"))

# --- 统计数据 ---
stats = {
    "total_requests": 0,
    "success_requests": 0,
    "failed_requests": 0,
    "rate_limit_errors": 0,
    "start_time": datetime.now()
}
recent_logs = deque(maxlen=50)
stats_lock = threading.Lock()

def log_request(endpoint, status, error_type=None, retry_count=0):
    with stats_lock:
        stats["total_requests"] += 1
        if status == "success":
            stats["success_requests"] += 1
        else:
            stats["failed_requests"] += 1
            if error_type == "rate_limit":
                stats["rate_limit_errors"] += 1
        
        recent_logs.appendleft({
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "endpoint": endpoint,
            "status": status,
            "error": error_type or "-",
            "retries": retry_count
        })

def smart_retry(func, max_retries=MAX_RETRIES):
    last_error = None
    for attempt in range(max_retries):
        try:
            result = func()
            if result.status_code == 200:
                return result, None, attempt
            try:
                data = result.json()
                if "error" in data and "rate limit" in str(data.get("error", "")).lower():
                    last_error = "rate_limit"
                    continue
            except:
                pass
            return result, None, attempt
        except Exception as e:
            last_error = str(e)
            if attempt < max_retries - 1:
                continue
    return None, last_error, max_retries - 1

@app.route('/v1/chat/completions', methods=['POST'])
def proxy_chat():
    auth_header = request.headers.get('Authorization')
    if not auth_header or auth_header != f"Bearer {MY_ACCESS_KEY}":
        log_request("/v1/chat/completions", "failed", "auth_error", 0)
        return jsonify({"error": "Permission Denied"}), 401

    req_data = request.json
    is_stream = req_data.get('stream', False)

    if is_stream:
        def generate():
            def make_request():
                return requests.post(
                    f"{PROXY_URL}/v1/chat/completions",
                    headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"},
                    json=req_data, stream=True, timeout=60
                )
            resp, error, retry_count = smart_retry(make_request)
            if resp and resp.status_code == 200:
                log_request("/v1/chat/completions", "success", None, retry_count)
                for line in resp.iter_lines():
                    if line:
                        decoded = line.decode('utf-8')
                        if not decoded.startswith('data: '):
                            decoded = 'data: ' + decoded
                        yield decoded + '\n\n'
            else:
                log_request("/v1/chat/completions", "failed", error, retry_count)
                if error == "rate_limit":
                    yield 'data: {"error":"错误重试全都rate limit,请再次重试."}\n\n'
                else:
                    yield f'data: {{"error":"请求失败: {error}"}}\n\n'
        return Response(generate(), content_type='text/event-stream')
    else:
        def make_request():
            return requests.post(
                f"{PROXY_URL}/v1/chat/completions",
                headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"},
                json=req_data, timeout=60
            )
        resp, error, retry_count = smart_retry(make_request)
        if resp:
            try:
                log_request("/v1/chat/completions", "success", None, retry_count)
                return jsonify(resp.json()), resp.status_code
            except:
                log_request("/v1/chat/completions", "failed", "parse_error", retry_count)
                return jsonify({"error": "Invalid response"}), 500
        log_request("/v1/chat/completions", "failed", error, retry_count)
        if error == "rate_limit":
            return jsonify({"error": "错误重试全都rate limit,请再次重试."}), 429
        else:
            return jsonify({"error": f"请求失败: {error}"}), 500

@app.route('/v1/models', methods=['GET'])
def proxy_models():
    auth_header = request.headers.get('Authorization')
    if not auth_header or auth_header != f"Bearer {MY_ACCESS_KEY}":
        return jsonify({"error": "Permission Denied"}), 401
    try:
        resp = requests.get(f"{PROXY_URL}/v1/models", headers={"Authorization": f"Bearer {API_KEY}"}, timeout=20)
        return jsonify(resp.json()), resp.status_code
    except:
        return jsonify({"error": "Failed to fetch models"}), 500

@app.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "ok"}), 200

# --- 主页管理面板 ---
@app.route('/')
def dashboard():
    with stats_lock:
        success_rate = (stats["success_requests"] / stats["total_requests"] * 100) if stats["total_requests"] > 0 else 0
        uptime = str(datetime.now() - stats["start_time"]).split('.')[0]
        
    html = '''
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>LLM Proxy 管理面板</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #f5f5f5; padding: 20px; }
        .container { max-width: 1200px; margin: 0 auto; }
        h1 { color: #333; margin-bottom: 30px; }
        .stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 20px; margin-bottom: 30px; }
        .stat-card { background: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
        .stat-card h3 { color: #666; font-size: 14px; margin-bottom: 10px; }
        .stat-card .value { font-size: 32px; font-weight: bold; color: #333; }
        .stat-card.success .value { color: #4caf50; }
        .stat-card.error .value { color: #f44336; }
        .logs { background: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
        .logs h2 { margin-bottom: 15px; color: #333; }
        table { width: 100%; border-collapse: collapse; }
        th { background: #f5f5f5; padding: 12px; text-align: left; font-weight: 600; color: #666; }
        td { padding: 12px; border-bottom: 1px solid #eee; }
        .status-success { color: #4caf50; font-weight: 600; }
        .status-failed { color: #f44336; font-weight: 600; }
        .retry-badge { 
            display: inline-block; 
            padding: 2px 8px; 
            border-radius: 12px; 
            font-size: 12px; 
            font-weight: 600;
            background: #e3f2fd;
            color: #1976d2;
        }
        .retry-badge.high { background: #fff3e0; color: #f57c00; }
        .refresh { background: #2196f3; color: white; border: none; padding: 10px 20px; border-radius: 4px; cursor: pointer; margin-bottom: 20px; margin-right: 10px; }
        .refresh:hover { background: #1976d2; }
        .auto-refresh-toggle { background: #4caf50; color: white; border: none; padding: 10px 20px; border-radius: 4px; cursor: pointer; margin-bottom: 20px; }
        .auto-refresh-toggle.off { background: #9e9e9e; }
        .info { background: #e3f2fd; padding: 15px; border-radius: 8px; margin-bottom: 20px; border-left: 4px solid #2196f3; }
        .info strong { color: #1976d2; }
        .auto-refresh-status { display: inline-block; margin-left: 10px; color: #666; font-size: 14px; }
    </style>
    <script>
        let autoRefreshEnabled = true;
        let countdown = 5;
        let intervalId;
        let countdownId;

        function toggleAutoRefresh() {
            autoRefreshEnabled = !autoRefreshEnabled;
            const btn = document.getElementById('autoRefreshBtn');
            const status = document.getElementById('refreshStatus');
            
            if (autoRefreshEnabled) {
                btn.textContent = '⏸️ 暂停自动刷新';
                btn.classList.remove('off');
                startCountdown();
            } else {
                btn.textContent = '▶️ 启动自动刷新';
                btn.classList.add('off');
                status.textContent = '已暂停';
                clearInterval(countdownId);
            }
        }

        function startCountdown() {
            countdown = 5;
            const status = document.getElementById('refreshStatus');
            
            countdownId = setInterval(() => {
                if (autoRefreshEnabled) {
                    countdown--;
                    status.textContent = `${countdown} 秒后刷新`;
                    if (countdown <= 0) {
                        location.reload();
                    }
                }
            }, 1000);
        }

        window.onload = function() {
            startCountdown();
        };
    </script>
</head>
<body>
    <div class="container">
        <h1>🚀 LLM Proxy 管理面板</h1>
        
        <div class="info">
            <strong>API 接入地址：</strong> https://你的域名/v1/chat/completions<br>
            <strong>模型列表：</strong> https://你的域名/v1/models<br>
            <strong>最大重试次数：</strong> {{ max_retries }} 次（快速重试，无延迟）
        </div>
        
        <button class="refresh" onclick="location.reload()">🔄 立即刷新</button>
        <button id="autoRefreshBtn" class="auto-refresh-toggle" onclick="toggleAutoRefresh()">⏸️ 暂停自动刷新</button>
        <span id="refreshStatus" class="auto-refresh-status">5 秒后刷新</span>
        
        <div class="stats">
            <div class="stat-card">
                <h3>总请求数</h3>
                <div class="value">{{ stats.total_requests }}</div>
            </div>
            <div class="stat-card success">
                <h3>成功请求</h3>
                <div class="value">{{ stats.success_requests }}</div>
            </div>
            <div class="stat-card error">
                <h3>失败请求</h3>
                <div class="value">{{ stats.failed_requests }}</div>
            </div>
            <div class="stat-card">
                <h3>成功率</h3>
                <div class="value">{{ "%.1f"|format(success_rate) }}%</div>
            </div>
            <div class="stat-card error">
                <h3>限流错误</h3>
                <div class="value">{{ stats.rate_limit_errors }}</div>
            </div>
            <div class="stat-card">
                <h3>运行时间</h3>
                <div class="value" style="font-size: 20px;">{{ uptime }}</div>
            </div>
        </div>
        
        <div class="logs">
            <h2>📋 最近请求日志 (最新 50 条)</h2>
            <table>
                <thead>
                    <tr>
                        <th>时间</th>
                        <th>接口</th>
                        <th>状态</th>
                        <th>重试次数</th>
                        <th>错误类型</th>
                    </tr>
                </thead>
                <tbody>
                    {% for log in logs %}
                    <tr>
                        <td>{{ log.time }}</td>
                        <td>{{ log.endpoint }}</td>
                        <td class="status-{{ log.status }}">{{ log.status }}</td>
                        <td>
                            {% if log.retries == 0 %}
                                <span class="retry-badge">首次成功</span>
                            {% elif log.retries < 3 %}
                                <span class="retry-badge">重试 {{ log.retries }} 次</span>
                            {% else %}
                                <span class="retry-badge high">重试 {{ log.retries }} 次</span>
                            {% endif %}
                        </td>
                        <td>{{ log.error }}</td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
    </div>
</body>
</html>
    '''
    return render_template_string(html, stats=stats, success_rate=success_rate, uptime=uptime, logs=list(recent_logs), max_retries=MAX_RETRIES)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000)