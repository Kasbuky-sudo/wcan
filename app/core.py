# © SONGJUNSONG · Jilin Business and Technology College · School of Finance and Economics
"""app/core.py — Flask 实例、全局状态、工具函数、鉴权、加密
从 app.py 分割而来，所有路由模块共享此模块。
"""
import os
import sys
import shutil
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from paths import bundle_dir, user_dir, is_frozen

from flask import Flask, request, jsonify
import json
import time
import threading
import platform
import re
import hashlib
import hmac
import tempfile
import secrets as _secrets
from base64 import b64encode, b64decode
from functools import wraps
from datetime import datetime, timedelta, timezone
import requests

from crawler import WeChatCrawler

# ====================== 版本号 ======================
__version__ = "6.0.3"

# ====================== 路径常量 ======================
# 可写用户数据目录：源码运行时=项目根目录；冻结成 exe 后=exe 所在目录
DATA_DIR = user_dir()
# 只读程序资源目录：冻结成 exe 后指向解包目录（sys._MEIPASS）
_TEMPLATES_DIR = os.path.join(bundle_dir(), 'templates')
_BUNDLE_STATIC_DIR = os.path.join(bundle_dir(), 'static')

# 静态资源目录：运行时文件（如微信扫码二维码 wx_qrcode.png）会写入
# user_dir()/static，而打包资源在 bundle 的 static 里。冻结后二者不在同一目录，
# Flask 的 static_folder 只认一个 → 首次启动把打包资源镜像到 user_dir 旁，
# 之后统一从 user_dir/static 提供（运行时文件与资源文件两全）。
_STATIC_DIR = _BUNDLE_STATIC_DIR
if is_frozen() and os.path.isdir(_BUNDLE_STATIC_DIR):
    _runtime_static = os.path.join(DATA_DIR, 'static')
    try:
        for _root, _dirs, _files in os.walk(_BUNDLE_STATIC_DIR):
            _rel = os.path.relpath(_root, _BUNDLE_STATIC_DIR)
            _dst_root = os.path.normpath(os.path.join(_runtime_static, _rel))
            os.makedirs(_dst_root, exist_ok=True)
            for _f in _files:
                _dst = os.path.join(_dst_root, _f)
                if not os.path.exists(_dst):
                    shutil.copy2(os.path.join(_root, _f), _dst)
        _STATIC_DIR = _runtime_static
    except Exception as _e:
        print(f"[Static] 镜像打包资源失败（非致命，回退到只读目录）: {_e}")

# ====================== Flask 应用实例 ======================
app = Flask(__name__, template_folder=_TEMPLATES_DIR, static_folder=_STATIC_DIR)
crawler = WeChatCrawler()

# ====================== 常量 ======================
BJT = timezone(timedelta(hours=8))
NOTIFY_CONFIG_FILE = os.path.join(DATA_DIR, 'notify_config.json')
NOTIFIED_FAILURES_FILE = os.path.join(DATA_DIR, 'notified_failures.json')
WEBDAV_CONFIG_FILE = os.path.join(DATA_DIR, 'webdav_config.json')
OLD_HISTORY_FILE = os.path.join(DATA_DIR, 'history.json')
CRAWL_HISTORY_FILE = os.path.join(DATA_DIR, 'crawl_history.json')
OLD_RSS_FEEDS_FILE = os.path.join(DATA_DIR, 'rss_feeds.json')

# 国内主流邮箱 SMTP 预设配置
EMAIL_PROVIDERS = {
    "qq": {"host": "smtp.qq.com", "port": 465, "security": "ssl", "desc": "QQ邮箱", "daily_limit": 100},
    "163": {"host": "smtp.163.com", "port": 994, "security": "ssl", "desc": "网易163邮箱", "daily_limit": 50},
    "126": {"host": "smtp.163.com", "port": 994, "security": "ssl", "desc": "网易126邮箱", "daily_limit": 50},
    "yeah": {"host": "smtp.163.com", "port": 994, "security": "ssl", "desc": "网易Yeah邮箱", "daily_limit": 50},
}

# 业务魔法数字
MAX_CRAWL_HISTORY = 2000
MAX_SYNC_LOGS = 500
MAX_CRAWL_LOGS = 100
MAX_WEBDAV_LOGS = 50
MAX_REPLACE_LOGS = 100
RETRY_INTERVAL_SEC = 3
DEFAULT_PAGE_SIZE = 50
DEFAULT_POLL_INTERVAL_SEC = 30
DEFAULT_TASK_POLL_SEC = 3
MAX_DEBUG_LOGS = 200
_AUTH_TOKEN_TTL = 24 * 3600

# ====================== 时间工具 ======================
def get_bjt_now():
    return datetime.now(BJT)

def format_bjt_time(dt=None):
    if dt is None:
        dt = get_bjt_now()
    return dt.strftime('%Y-%m-%d %H:%M:%S')

# ====================== 敏感字段加密 ======================
def _get_crypto_key():
    from werss.config import cfg
    secret = cfg.get('secret', 'change-me-to-a-random-string') or 'change-me-to-a-random-string'
    return hashlib.sha256(secret.encode('utf-8')).digest()

def _encrypt_secret(plaintext):
    if not plaintext:
        return ''
    key = _get_crypto_key()
    data = plaintext.encode('utf-8')
    result = bytearray()
    counter = 0
    pos = 0
    while pos < len(data):
        block = hmac.new(key, counter.to_bytes(8, 'big'), hashlib.sha256).digest()
        chunk = data[pos:pos + 32]
        result.extend(a ^ b for a, b in zip(chunk, block))
        pos += 32
        counter += 1
    return 'enc:' + b64encode(bytes(result)).decode('ascii')

def _decrypt_secret(ciphertext):
    if not ciphertext:
        return ''
    if not isinstance(ciphertext, str) or not ciphertext.startswith('enc:'):
        return ciphertext
    key = _get_crypto_key()
    try:
        data = b64decode(ciphertext[4:])
    except Exception:
        return ''
    result = bytearray()
    counter = 0
    pos = 0
    while pos < len(data):
        block = hmac.new(key, counter.to_bytes(8, 'big'), hashlib.sha256).digest()
        chunk = data[pos:pos + 32]
        result.extend(a ^ b for a, b in zip(chunk, block))
        pos += 32
        counter += 1
    try:
        return bytes(result).decode('utf-8')
    except Exception:
        return ''

# ====================== 鉴权 ======================
_auth_tokens = {}
_auth_lock = threading.Lock()

def _verify_admin_password(pwd):
    from werss.config import cfg
    admin_pwd = os.environ.get('WCAN_ADMIN_PWD') or cfg.get('admin_password', '')
    if not admin_pwd or not pwd:
        return False
    return hmac.compare_digest(str(pwd), str(admin_pwd))

def _issue_auth_token():
    token = _secrets.token_urlsafe(32)
    now = time.time()
    with _auth_lock:
        _auth_tokens[token] = now + _AUTH_TOKEN_TTL
        for k in [k for k, v in _auth_tokens.items() if v < now]:
            del _auth_tokens[k]
    return token

def _verify_auth_token(token):
    if not token:
        return False
    with _auth_lock:
        expiry = _auth_tokens.get(token)
        if not expiry:
            return False
        if time.time() > expiry:
            del _auth_tokens[token]
            return False
        return True

def _extract_auth_token():
    auth_header = request.headers.get('Authorization', '')
    if auth_header.startswith('Bearer '):
        return auth_header[7:]
    return ''

def require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if _verify_auth_token(_extract_auth_token()):
            return f(*args, **kwargs)
        data = request.get_json(silent=True) or {}
        pwd = data.get('admin_password', '') or data.get('password', '')
        if pwd and _verify_admin_password(pwd):
            return f(*args, **kwargs)
        return jsonify({'success': False, 'message': '未授权，请先登录', 'code': 'UNAUTHORIZED'}), 401
    return decorated

# ====================== 健壮性工具 ======================
def _atomic_write(file_path, data, mode='w', encoding='utf-8'):
    dir_path = os.path.dirname(os.path.abspath(file_path))
    os.makedirs(dir_path, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=dir_path, suffix='.tmp')
    try:
        if 'b' in mode:
            with os.fdopen(fd, mode) as f:
                f.write(data)
        else:
            with os.fdopen(fd, mode, encoding=encoding) as f:
                f.write(data)
        os.replace(tmp_path, file_path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise

def _safe_thread(target, args=(), kwargs=None, daemon=True):
    if kwargs is None:
        kwargs = {}
    def _wrapper():
        try:
            target(*args, **kwargs)
        except Exception as e:
            import traceback as _tb
            print(f"[THREAD] 线程异常: {e}\n{_tb.format_exc()}")
    t = threading.Thread(target=_wrapper, daemon=daemon)
    t.start()
    return t

def _safe_request(method, url, timeout=15, **kwargs):
    kwargs.setdefault('timeout', timeout)
    return requests.request(method, url, **kwargs)

def _load_json(file_path, default=None, log_tag=''):
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return default
    except json.JSONDecodeError as e:
        print(f"[JSON] {log_tag or file_path} 解析失败: {e}，使用默认值")
        return default
    except Exception as e:
        print(f"[JSON] {log_tag or file_path} 加载异常: {e}，使用默认值")
        return default

# ====================== API 限流 ======================
_rate_limit_store = {}
_rate_limit_lock = threading.Lock()

def rate_limit(max_calls=60, window=60, key_func=None):
    def decorator(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            if key_func:
                k = key_func()
            else:
                k = request.remote_addr or 'unknown'
            k = f"{f.__name__}:{k}"
            now = time.time()
            with _rate_limit_lock:
                timestamps = _rate_limit_store.get(k, [])
                timestamps = [t for t in timestamps if now - t < window]
                if len(timestamps) >= max_calls:
                    retry_after = int(window - (now - timestamps[0]))
                    return jsonify({
                        'success': False,
                        'error': f'请求过于频繁，请 {retry_after} 秒后重试',
                        'code': 'RATE_LIMITED'
                    }), 429
                timestamps.append(now)
                _rate_limit_store[k] = timestamps
            return f(*args, **kwargs)
        return wrapped
    return decorator

# ====================== Debug 日志 ======================
_debug_logs = []
_debug_lock = threading.Lock()

def debug_log(level, source, message, extra=None):
    entry = {
        'time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'level': level,
        'source': source,
        'message': str(message)[:500],
        'extra': extra or {}
    }
    with _debug_lock:
        _debug_logs.append(entry)
        if len(_debug_logs) > MAX_DEBUG_LOGS:
            _debug_logs.pop(0)

def get_debug_logs():
    with _debug_lock:
        return list(_debug_logs)

def clear_debug_logs():
    with _debug_lock:
        _debug_logs.clear()

# ====================== 全局业务状态 ======================
crawl_status = {
    'progress': 0, 'status': 'idle', 'message': '等待开始...',
    'logs': [], 'preview_data': None, 'document_data': None
}

sync_status = {
    'running': False, 'mode': '', 'phase': 'idle', 'progress': 0,
    'message': '', 'articles': [], 'logs': [], 'error_summary': '',
    'error_report_path': '', 'task_done_time': None, 'task_done_summary': '',
}

# 状态锁：保护 crawl_status / sync_status 等复合操作
_status_lock = threading.RLock()

def add_sync_log(msg):
    timestamp = format_bjt_time()[11:]
    log_entry = f"[{timestamp}] {msg}"
    with _status_lock:
        sync_status['logs'].append(log_entry)
        if len(sync_status['logs']) > MAX_SYNC_LOGS:
            sync_status['logs'] = sync_status['logs'][-MAX_SYNC_LOGS:]
    print(f"[SYNC] {log_entry}")

def update_sync_status(percent, msg):
    with _status_lock:
        sync_status['progress'] = percent
        sync_status['message'] = msg

def reset_sync_status(message, mode=''):
    with _status_lock:
        sync_status.update({
            'running': False, 'mode': mode, 'phase': 'idle',
            'progress': 0, 'message': message,
            'articles': [], 'logs': [],
            'error_summary': '', 'error_report_path': '',
            'task_done_time': None, 'task_done_summary': '',
        })

# ====================== 应用工厂 ======================
def create_app():
    """应用工厂：创建 Flask app 并注册所有 Blueprint"""
    # 注册各路由 Blueprint（统一用 bp 别名导入）
    from .routes_auth import bp as auth_bp
    from .routes_crawl import bp as crawl_bp
    from .routes_mps import bp as mps_bp
    from .routes_notify import notify_bp
    from .routes_system import bp as system_bp
    from .routes_misc import bp as misc_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(crawl_bp)
    app.register_blueprint(mps_bp)
    app.register_blueprint(notify_bp)
    app.register_blueprint(system_bp)
    app.register_blueprint(misc_bp)

    # 全局拦截：封锁国家 IP 列表；IP 不可靠时补充检查浏览器时区/语言
    @app.before_request
    def _block_region_global():
        from .routes_crawl import _get_client_ip, _get_ip_region, _get_request_locale_region, _build_block_page, _BLOCKED_COUNTRIES
        ip = _get_client_ip()
        region = _get_ip_region(ip)
        locale_region, locale_source = _get_request_locale_region()
        # region/locale_region 返回国家代码（TW/JP/US/KR/SG/GB/DE/FR/AU/CA），或 PRIVATE/CN/OVERSEAS/UNKNOWN
        block_region = region if region in _BLOCKED_COUNTRIES else locale_region
        if block_region in _BLOCKED_COUNTRIES:
            if locale_source:
                print(f"[Locale-Check] 命中 {locale_source}={block_region}，应用将完全封锁")
            page = _build_block_page(block_region)
            if page:
                return page, 403
        return None

    # 注册 /api/v1/ 别名（基于 url_map 反射）
    _register_api_v1_aliases()

    return app

def _register_api_v1_aliases():
    """为所有 /api/ 开头的路由注册 /api/v1/ 别名"""
    for rule in list(app.url_map.iter_rules()):
        if rule.endpoint == 'static':
            continue
        if rule.rule.startswith('/api/') and not rule.rule.startswith('/api/v1/'):
            v1_rule = '/api/v1' + rule.rule[4:]
            try:
                app.add_url_rule(v1_rule, endpoint=rule.endpoint + '_v1',
                                 view_func=app.view_functions[rule.endpoint],
                                 methods=rule.methods - {'HEAD', 'OPTIONS'})
            except Exception:
                pass
