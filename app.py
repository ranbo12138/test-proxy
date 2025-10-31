from flask import Flask, request, jsonify, Response
import requests
import os
import time

app = Flask(__name__)

PROXY_URL = os.environ.get("PROXY_URL")
API_KEY = os.environ.get("API_KEY")
MY_ACCESS_KEY = os.environ.get("MY_ACCESS_KEY")
MAX_RETRIES = int(os.environ.get("MAX_RETRIES", "5"))

def smart_retry(func, max_retries=MAX_RETRIES):
    last_error = None
    
    for attempt in range(max_retries):
        try:
            result = func()
            if result.status_code == 200:
                return result, None
            
            try:
                data = result.json()
                if "error" in data and "rate limit" in str(data.get("error", "")).lower():
                    last_error = "rate_limit"
                    wait_time = 2 ** attempt
                    time.sleep(wait_time)
                    continue
            except:
                pass
            
            return result, None
            
        except Exception as e:
            last_error = str(e)
            if attempt < max_retries - 1:
                wait_time = 2 ** attempt
                time.sleep(wait_time)
                continue
    
    return None, last_error

@app.route('/v1/chat/completions', methods=['POST'])
def proxy_chat():
    auth_header = request.headers.get('Authorization')
    if not auth_header or auth_header != f"Bearer {MY_ACCESS_KEY}":
        return jsonify({"error": "Permission Denied"}), 401

    req_data = request.json
    is_stream = req_data.get('stream', False)

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
            
            resp, error = smart_retry(make_request)
            if resp and resp.status_code == 200:
                for line in resp.iter_lines():
                    if line:
                        decoded = line.decode('utf-8')
                        if not decoded.startswith('data: '):
                            decoded = 'data: ' + decoded
                        yield decoded + '\n\n'
            else:
                if error == "rate_limit":
                    yield 'data: {"error":"错误重试全都rate limit,请再次重试."}\n\n'
                else:
                    yield f'data: {{"error":"请求失败: {error}"}}\n\n'

        return Response(generate(), content_type='text/event-stream')

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
        
        resp, error = smart_retry(make_request)
        if resp:
            try:
                return jsonify(resp.json()), resp.status_code
            except:
                return jsonify({"error": "Invalid response"}), 500
        
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
        resp = requests.get(
            f"{PROXY_URL}/v1/models",
            headers={"Authorization": f"Bearer {API_KEY}"},
            timeout=20
        )
        return jsonify(resp.json()), resp.status_code
    except:
        return jsonify({"error": "Failed to fetch models"}), 500

@app.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "ok"}), 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000)