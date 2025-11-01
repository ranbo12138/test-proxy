from flask import Flask, request, jsonify, Response, render_template_string
import requests
import os
import json
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

def log_request(endpoint, status, error_type=None, retry_count=0, detail=None):
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
            "retries": retry_count,
            "detail": detail or "-"
        })

def smart_retry(func, max_retries=MAX_RETRIES):
    last_error = None
    last_detail = None
    
    for attempt in range(max_retries):
        try:
            result = func()
            if result.status_code == 200:
                return result, None, attempt, None
            try:
                data = result.json()
                error_msg = str(data.get("error", {}))
                
                if "sensitive" in error_msg.lower():
                    last_error = "sensitive_words"
                    last_detail = "上游检测到敏感词"
                    return None, last_error, attempt, last_detail
                
                if "rate limit" in error_msg.lower() or "rate_limit" in error_msg.lower():
                    last_error = "rate_limit"
                    last_detail = error_msg[:200]
                    continue
                else:
                    last_error = f"http_{result.status_code}"
                    last_detail = str(data)[:200]
                    return result, last_error, attempt, last_detail
            except:
                last_error = f"http_{result.status_code}"
                last_detail = result.text[:200] if hasattr(result, 'text') else "无响应内容"
                return result, last_error, attempt, last_detail
        except requests.exceptions.Timeout:
            last_error = "timeout"
            last_detail = "请求超时(60秒)"
            if attempt < max_retries - 1:
                continue
        except Exception as e:
            last_error = type(e).__name__
            last_detail = str(e)[:200]
            if attempt < max_retries - 1:
                continue
    
    return None, last_error or "unknown", max_retries - 1, last_detail or "未知错误"

# --- OpenAI 格式接口 ---
@app.route('/v1/chat/completions', methods=['POST'])
def proxy_chat():
    auth_header = request.headers.get('Authorization')
    if not auth_header or auth_header != f"Bearer {MY_ACCESS_KEY}":
        log_request("/v1/chat/completions", "failed", "auth_error", 0)
        return jsonify({"error": "Permission Denied"}), 401

    try:
        req_data = request.json
    except Exception as e:
        log_request("/v1/chat/completions", "failed", "invalid_json", 0, str(e)[:200])
        return jsonify({"error": "Invalid JSON"}), 400

    is_stream = req_data.get('stream', False)

    if is_stream:
        def generate():
            def make_request():
                return requests.post(
                    f"{PROXY_URL}/v1/chat/completions",
                    headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"},
                    json=req_data, stream=True, timeout=60
                )
            resp, error, retry_count, detail = smart_retry(make_request)
            if resp and resp.status_code == 200:
                log_request("/v1/chat/completions", "success", None, retry_count)
                for line in resp.iter_lines():
                    if line:
                        decoded = line.decode('utf-8')
                        if not decoded.startswith('data: '):
                            decoded = 'data: ' + decoded
                        yield decoded + '\n\n'
            else:
                log_request("/v1/chat/completions", "failed", error, retry_count, detail)
                if error == "rate_limit":
                    yield 'data: {"error":"错误重试全都rate limit,请再次重试."}\n\n'
                elif error == "sensitive_words":
                    yield 'data: {"error":"内容包含敏感词，已被上游拦截"}\n\n'
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
        resp, error, retry_count, detail = smart_retry(make_request)
        if resp:
            try:
                log_request("/v1/chat/completions", "success", None, retry_count)
                return jsonify(resp.json()), resp.status_code
            except Exception as e:
                log_request("/v1/chat/completions", "failed", "parse_error", retry_count, str(e)[:200])
                return jsonify({"error": "Invalid response"}), 500
        
        log_request("/v1/chat/completions", "failed", error, retry_count, detail)
        if error == "rate_limit":
            return jsonify({"error": "错误重试全都rate limit,请再次重试."}), 429
        elif error == "sensitive_words":
            return jsonify({"error": "内容包含敏感词，已被上游拦截"}), 400
        else:
            return jsonify({"error": f"请求失败: {error}", "detail": detail}), 500

# --- Anthropic (Claude) 格式接口 ---
@app.route('/v1/messages', methods=['POST'])
def proxy_anthropic():
    auth_header = request.headers.get('x-api-key') or request.headers.get('Authorization')
    
    # 支持两种认证方式
    if auth_header:
        if auth_header.startswith('Bearer '):
            auth_header = auth_header[7:]
        if auth_header != MY_ACCESS_KEY:
            log_request("/v1/messages", "failed", "auth_error", 0)
            return jsonify({"error": {"type": "authentication_error", "message": "Invalid API Key"}}), 401
    else:
        log_request("/v1/messages", "failed", "auth_error", 0)
        return jsonify({"error": {"type": "authentication_error", "message": "Missing API Key"}}), 401

    try:
        req_data = request.json
    except Exception as e:
        log_request("/v1/messages", "failed", "invalid_json", 0, str(e)[:200])
        return jsonify({"error": {"type": "invalid_request_error", "message": "Invalid JSON"}}), 400

    is_stream = req_data.get('stream', False)

    if is_stream:
        def generate():
            def make_request():
                headers = {
                    "x-api-key": API_KEY,
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json"
                }
                return requests.post(
                    f"{PROXY_URL}/v1/messages",
                    headers=headers,
                    json=req_data, stream=True, timeout=60
                )
            resp, error, retry_count, detail = smart_retry(make_request)
            if resp and resp.status_code == 200:
                log_request("/v1/messages", "success", None, retry_count)
                for line in resp.iter_lines():
                    if line:
                        yield line.decode('utf-8') + '\n'
            else:
                log_request("/v1/messages", "failed", error, retry_count, detail)
                error_response = {
                    "type": "error",
                    "error": {
                        "type": "rate_limit_error" if error == "rate_limit" else "api_error",
                        "message": detail or "请求失败"
                    }
                }
                yield f"data: {json.dumps(error_response)}\n\n"
        return Response(generate(), content_type='text/event-stream')
    else:
        def make_request():
            headers = {
                "x-api-key": API_KEY,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json"
            }
            return requests.post(
                f"{PROXY_URL}/v1/messages",
                headers=headers,
                json=req_data, timeout=60
            )
        resp, error, retry_count, detail = smart_retry(make_request)
        if resp:
            try:
                log_request("/v1/messages", "success", None, retry_count)
                return jsonify(resp.json()), resp.status_code
            except Exception as e:
                log_request("/v1/messages", "failed", "parse_error", retry_count, str(e)[:200])
                return jsonify({"error": {"type": "api_error", "message": "Invalid response"}}), 500
        
        log_request("/v1/messages", "failed", error, retry_count, detail)
        return jsonify({
            "error": {
                "type": "rate_limit_error" if error == "rate_limit" else "api_error",
                "message": detail or "请求失败"
            }
        }), 429 if error == "rate_limit" else 500

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
        .container { max-width: 1400px; margin: 0 auto; }
        h1 { color: #333; margin-bottom: 30px; }
        .stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 20px; margin-bottom: 30px; }
        .stat-card { background: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
        .stat-card h3 { color: #666; font-size: 14px; margin-bottom: 10px; }
        .stat-card .value { font-size: 32px; font-weight: bold; color: #333; }
        .stat-card.success .value { color: #4caf50; }
        .stat-card.error .value { color: #f44336; }
        .logs { background: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); overflow-x: auto; }
        .logs h2 { margin-bottom: 15px; color: #333; }
        table { width: 100%; border-collapse: collapse; min-width: 1000px; }
        th { background: #f5f5f5; padding: 12px; text-align: left; font-weight: 600; color: #666; white-space: nowrap; }
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
        .detail-cell { max-width: 300px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 12px; color: #666; cursor: help; }
        .refresh { background: #2196f3; color: white; border: none; padding: 10px 20px; border-radius: 4px; cursor: pointer; margin-bottom: 20px; }
        .refresh:hover { background: #1976d2; }
        .info { background: #e3f2fd; padding: 15px; border-radius: 8px; margin-bottom: 20px; border-left: 4px solid #2196f3; }
        .info strong { color: #1976d2; }
    </style>
</head>
<body>
    <div class="container">
        <h1>🚀 LLM Proxy 管理面板</h1>
        
        <div class="info">
            <strong>OpenAI 格式：</strong> https://你的域名/v1/chat/completions<br>
            <strong>Anthropic 格式：</strong> https://你的域名/v1/messages<br>
            <strong>模型列表：</strong> https://你的域名/v1/models<br>
            <strong>最大重试次数：</strong> {{ max_retries }} 次（快速重试，无延迟）
        </div>
        
        <button class="refresh" onclick="location.reload()">🔄 刷新数据</button>
        
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
                        <th>详细信息</th>
                    </tr>
                </thead>
                <tbody>
                    {% for log in logs %}
                    <tr>
                        <td style="white-space: nowrap;">{{ log.time }}</td>
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
                        <td class="detail-cell" title="{{ log.detail }}">{{ log.detail }}</td>
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