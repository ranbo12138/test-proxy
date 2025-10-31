from flask import Flask, request, jsonify, Response, stream_with_context
import requests
import os
import time
import json

app = Flask(__name__)

# --- 配置 ---
PROXY_URL = os.environ.get("PROXY_URL")
API_KEY = os.environ.get("API_KEY")
MY_ACCESS_KEY = os.environ.get("MY_ACCESS_KEY")
MAX_RETRIES = int(os.environ.get("MAX_RETRIES", "5"))

# --- 智能重试函数（带指数退避） ---
def smart_retry(func, max_retries=MAX_RETRIES):
    for attempt in range(max_retries):
        try:
            result = func()
            # 检查是否是限流错误
            if hasattr(result, 'json'):
                data = result.json()
                if "error" in data and "rate limit" in data["error"].get("message", "").lower():
                    wait_time = 2 ** attempt  # 指数退避: 1s, 2s, 4s, 8s, 16s
                    time.sleep(wait_time)
                    continue
            return result
        except Exception as e:
            if attempt < max_retries - 1:
                wait_time = 2 ** attempt
                time.sleep(wait_time)
                continue
            raise e
    return None

# --- 聊天接口（支持流式和非流式） ---
@app.route('/v1/chat/completions', methods=['POST'])
def proxy_chat():
    # 验证密码
    auth_header = request.headers.get('Authorization')
    if not auth_header or auth_header != f"Bearer {MY_ACCESS_KEY}":
        return jsonify({"error": "Permission Denied"}), 401

    req_data = request.json
    is_stream = req_data.get('stream', False)

    # 流式输出
    if is_stream:
        def generate():
            def make_request():
                return requests.post(
                    f"{PROXY_URL}/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {API_KEY}",
                        "Content-Type": "application/json"
                    },
                    json=req_data,
                    stream=True,
                    timeout=60
                )
            
            try:
                resp = smart_retry(make_request)
                if resp and resp.status_code == 200:
                    for chunk in resp.iter_content(chunk_size=None, decode_unicode=True):
                        if chunk:
                            yield chunk
                else:
                    yield f'data: {json.dumps({"error": "重试失败"})}\n\n'
            except Exception as e:
                yield f'data: {json.dumps({"error": str(e)})}\n\n'

        return Response(stream_with_context(generate()), content_type='text/event-stream')

    # 非流式输出
    else:
        def make_request():
            return requests.post(
                f"{PROXY_URL}/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {API_KEY}",
                    "Content-Type": "application/json"
                },
                json=req_data,
                timeout=60
            )
        
        try:
            resp = smart_retry(make_request)
            if resp:
                return jsonify(resp.json()), resp.status_code
            return jsonify({"error": "重试失败"}), 500
        except Exception as e:
            return jsonify({"error": str(e)}), 500

# --- 获取模型列表 ---
@app.route('/v1/models', methods=['GET'])
def proxy_models():
    auth_header = request.headers.get('Authorization')
    if not auth_header or auth_header != f"Bearer {MY_ACCESS_KEY}":
        return jsonify({"error": "Permission Denied"}), 401

    try:
        resp = requests.get(
            f"{PROXY_URL}/v1/models",
            headers={"Authorization": f"Bearer {API_KEY}"},
            timeout=20
        )
        return jsonify(resp.json()), resp.status_code
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# --- 健康检查接口（新增） ---
@app.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "ok", "service": "llm-proxy"}), 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000)
