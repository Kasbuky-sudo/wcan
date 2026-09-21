# Crafted by SONGJUNSONG at the School of Finance and Economics, Jilin Business and Technology College
"""通知系统与WebDAV路由"""
import smtplib
import socket
import email.utils
from email.header import Header
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from flask import Blueprint, request, jsonify
from .core import *
from .core import (
    _atomic_write,
    _load_json,
    _encrypt_secret,
    _decrypt_secret,
    _safe_thread,
    _status_lock,
    __version__,
)

notify_bp = Blueprint('notify', __name__)

# ====================== 通知系统全局变量 ======================
# 通知类型注册表（可扩展）
NOTIFY_TYPES = ['rss_expiry', 'task_reminder', 'error_reminder']

# 插件式通知渠道列表：[(name, sender_func), ...]
# sender_func 签名: (message: str) -> bool
_NOTIFY_CHANNELS = []

# WebDAV 上传状态
webdav_upload_status = {
    'uploading': False,
    'last_result': None,
    'last_time': None,
    'logs': []
}


# ====================== 核心通知函数（被其他模块调用）======================

def send_notification(message, notify_type=None, bypass_filter=False):
    config = _normalize_notify_config(load_notify_config())
    results = []
    notify_type = notify_type or 'task_reminder'
    for webhook in config.get('webhooks', []):
        if webhook.get('url') and (bypass_filter or _is_notification_enabled_for_config(config, 'webhook', notify_type)):
            if send_webhook_notification(webhook['url'], message):
                results.append(f"webhook:{webhook.get('name', '未命名')}")
    for serverchan in config.get('serverchans', []):
        if serverchan.get('key') and (bypass_filter or _is_notification_enabled_for_config(config, 'serverchan', notify_type)):
            if send_serverchan_notification(serverchan['key'], message):
                results.append(f"serverchan:{serverchan.get('name', '未命名')}")
    # 邮件通知
    try:
        if bypass_filter or _is_notification_enabled_for_config(config, 'email', notify_type):
            email_result = send_email_notification(message)
            if email_result:
                results.append("email")
    except Exception:
        pass
    # 插件式通知渠道（通过 register_notify_channel 注册）
    for ch_name, ch_func in _NOTIFY_CHANNELS:
        try:
            if bypass_filter or _is_notification_enabled_for_config(config, ch_name, notify_type):
                if ch_func(message):
                    results.append(ch_name)
        except Exception as e:
            print(f"[Notify] 插件渠道 {ch_name} 异常: {e}")
    return results


# ====================== 通知配置加载/保存 ======================

def load_notify_config():
    try:
        with open(NOTIFY_CONFIG_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            if 'webhooks' not in data:
                data['webhooks'] = []
            if 'serverchans' not in data:
                data['serverchans'] = []
            if data.get('webhook_url') and not data['webhooks']:
                data['webhooks'].append({'name': '默认', 'url': data['webhook_url']})
                del data['webhook_url']
            if data.get('serverchan_key') and not data['serverchans']:
                data['serverchans'].append({'name': '默认', 'key': data['serverchan_key']})
                if 'serverchan_key' in data:
                    del data['serverchan_key']
            if 'last_token_reminder' not in data:
                data['last_token_reminder'] = None
            if 'email' not in data:
                data['email'] = {"enabled": False, "smtp_host": "", "smtp_port": 587, "smtp_user": "", "smtp_password": "", "smtp_from": "", "smtp_to": "", "smtp_use_tls": True}
            _normalize_notify_config(data)
            # 解密邮箱密码（向后兼容明文）
            if isinstance(data.get('email'), dict) and data['email'].get('smtp_password'):
                data['email']['smtp_password'] = _decrypt_secret(data['email']['smtp_password'])
            return data
    except json.JSONDecodeError as e:
        print(f"[CONFIG] notify_config.json 解析失败: {e}，使用默认配置")
    except Exception as e:
        print(f"[CONFIG] load_notify_config 异常: {e}，使用默认配置")
    data = {
        'webhooks': [],
        'serverchans': [],
        'email': {"enabled": False, "smtp_host": "", "smtp_port": 587, "smtp_user": "", "smtp_password": "", "smtp_from": "", "smtp_to": "", "smtp_use_tls": True},
        'last_token_reminder': None
    }
    _normalize_notify_config(data)
    return data


def save_notify_config(config):
    # 加密邮箱密码后再落盘（避免明文存储）
    payload = json.loads(json.dumps(config))  # 深拷贝避免污染调用方
    if isinstance(payload.get('email'), dict) and payload['email'].get('smtp_password'):
        pwd = payload['email']['smtp_password']
        if not pwd.startswith('enc:'):  # 避免重复加密
            payload['email']['smtp_password'] = _encrypt_secret(pwd)
    _atomic_write(NOTIFY_CONFIG_FILE, json.dumps(payload, ensure_ascii=False, indent=2))


# ====================== Webhook / ServerChan 发送 ======================

def send_webhook_notification(webhook_url, message):
    if not webhook_url:
        return False
    try:
        payload = {'msg': message}
        response = requests.post(webhook_url, json=payload, timeout=10)
        return response.status_code == 200
    except Exception as e:
        print(f'Webhook 通知发送失败: {e}')
        return False


def send_serverchan_notification(serverchan_key, message):
    if not serverchan_key:
        return False
    try:
        url = f'https://sctapi.ftqq.com/{serverchan_key}.send'
        payload = {'title': '公众号文章提取通知', 'desp': message}
        response = requests.post(url, data=payload, timeout=10)
        return response.status_code == 200
    except Exception as e:
        print(f'ServerChan 通知发送失败: {e}')
        return False


# ====================== 通知类型与渠道插件注册 ======================

def register_notify_type(name: str):
    """注册新的通知类型（插件扩展用）。
    注册后该类型会出现在前端通知矩阵中，可按渠道开关。
    """
    if name and name not in NOTIFY_TYPES:
        NOTIFY_TYPES.append(name)


def register_notify_channel(name: str, sender_func):
    """注册新的通知渠道（插件扩展用）。
    sender_func(message: str) -> bool，返回是否发送成功。
    渠道名 name 会用于 notify_matrix 配置矩阵。
    """
    if name and callable(sender_func):
        _NOTIFY_CHANNELS.append((name, sender_func))


# ====================== 邮件通知 ======================

def _get_email_config():
    """读取邮件配置，优先 notify_config.json，回退 config.yaml"""
    # 优先从 notify_config.json 读取
    try:
        nc = load_notify_config()
        ec = nc.get("email", {})
        if ec and ec.get("enabled") and ec.get("smtp_host") and ec.get("smtp_user"):
            return _build_email_config(ec)
    except Exception:
        pass
    # 回退到 config.yaml
    try:
        from werss.config import cfg
        ec = cfg.get("notice.email")
        if not ec or not ec.get("smtp_host") or not ec.get("smtp_user"):
            return None
        return _build_email_config(ec)
    except Exception:
        return None


def _build_email_config(ec):
    """将配置字典统一转为标准化结构，兼容旧字段 smtp_use_tls"""
    security = ec.get("smtp_security", "")
    if not security and "smtp_use_tls" in ec:
        security = "starttls" if ec["smtp_use_tls"] else "none"
    if not security:
        security = "ssl"

    return {
        "host": ec.get("smtp_host", ""),
        "port": int(ec.get("smtp_port", 465)),
        "user": ec.get("smtp_user", ""),
        "password": ec.get("smtp_password", ""),
        "from": ec.get("smtp_from", ec.get("smtp_user", "")),
        "to": ec.get("smtp_to", ""),
        "security": security,
        "max_retries": int(ec.get("max_retries", 3)),
        "retry_strategy": ec.get("retry_strategy", "exponential"),
    }


def _build_email_msg(message, ec, subject="公众号文章提取通知"):
    """构建邮件消息（MIMEMultipart），公共逻辑抽取"""
    body_text = (message
        .replace('\u274c', '[失败]')
        .replace('\u26a0', '[警告]')
        .replace('\u2705', '[成功]')
        .replace('\u23f0', '[提醒]')
    )
    body_html = (
        '<html><body style="font-family:Microsoft YaHei,Arial,sans-serif; font-size:14px; color:#333;">'
        + '<pre style="white-space:pre-wrap; font-family:inherit;">'
        + body_text
        + '</pre><br><hr style="border:none;border-top:1px solid #eee;">'
        + '<p style="font-size:12px; color:#999;">此邮件由 公众号文章提取助手 自动发送。</p>'
        + '</body></html>'
    )
    msg = MIMEMultipart("alternative")
    msg["From"] = ec["from"]
    msg["To"] = ec["to"]
    msg["Subject"] = Header(subject, "utf-8")
    msg["Date"] = email.utils.formatdate(localtime=True)
    msg["Message-ID"] = email.utils.make_msgid(domain=ec["host"].replace("smtp.", ""))
    msg["X-Mailer"] = f"编舟文心/{__version__}"
    msg["X-Priority"] = "3"
    msg.attach(MIMEText(body_text, "plain", "utf-8"))
    msg.attach(MIMEText(body_html, "html", "utf-8"))
    return msg


def _smtp_connect(ec, timeout=30):
    """创建 SMTP 连接并登录，返回 server 对象"""
    security = ec["security"]
    if security == "ssl":
        server = smtplib.SMTP_SSL(ec["host"], ec["port"], timeout=timeout)
    elif security == "starttls":
        server = smtplib.SMTP(ec["host"], ec["port"], timeout=timeout)
        server.starttls()
    else:
        server = smtplib.SMTP(ec["host"], ec["port"], timeout=timeout)
    server.login(ec["user"], ec["password"])
    return server


def send_email_notification(message, max_retries=None):
    """发送邮件通知，支持 SSL/STARTTLS/无加密，HTML+plain 双格式，指数退避重试"""
    ec = _get_email_config()
    if not ec:
        return False
    if not ec["to"]:
        return False

    if max_retries is None:
        max_retries = ec.get("max_retries", 3)

    msg = _build_email_msg(message, ec)

    for attempt in range(1, max_retries + 1):
        try:
            server = _smtp_connect(ec, timeout=30)
            server.sendmail(ec["from"], [a.strip() for a in ec["to"].split(",")], msg.as_string())
            server.quit()
            print(f"邮件通知发送成功: {ec['to']}")
            return True

        except smtplib.SMTPAuthenticationError as e:
            print(f"邮件认证失败 (第{attempt}/{max_retries}次): {e}")
            return False
        except smtplib.SMTPResponseException as e:
            code = e.smtp_code
            print(f"SMTP错误 {code} (第{attempt}/{max_retries}次): {e}")
            if 500 <= code < 600 and code not in (550, 554):
                return False
            if attempt < max_retries:
                time.sleep(_retry_delay(attempt, ec))
        except (socket.timeout, smtplib.SMTPConnectError, smtplib.SMTPServerDisconnected) as e:
            print(f"邮件连接失败 (第{attempt}/{max_retries}次): {e}")
            if attempt < max_retries:
                time.sleep(_retry_delay(attempt, ec))
        except Exception as e:
            print(f"邮件发送异常 (第{attempt}/{max_retries}次): {e}")
            if attempt < max_retries:
                time.sleep(_retry_delay(attempt, ec))

    return False


def _retry_delay(attempt, config):
    """重试延迟：指数退避 (3s, 6s, 12s...)"""
    base = 3
    if config.get("retry_strategy", "exponential") == "fixed":
        return base
    return base * (2 ** (attempt - 1))


def _send_single_email(message, ec):
    """单次邮件发送，不带重试，超时15秒"""
    try:
        msg = _build_email_msg(message, ec)
        server = _smtp_connect(ec, timeout=15)
        server.sendmail(ec["from"], [a.strip() for a in ec["to"].split(",")], msg.as_string())
        server.quit()
        print(f"测试邮件发送成功: {ec['to']}")
        return True
    except Exception as e:
        print(f"测试邮件发送失败: {e}")
        return False


# ====================== 通知矩阵辅助 ======================

def _normalize_notify_config(config):
    config = config or {}
    notify_types = list(NOTIFY_TYPES)
    channels = ['email', 'webhook', 'serverchan']
    defaults = {channel: {nt: True for nt in notify_types} for channel in channels}
    matrix = config.get('notify_matrix') if isinstance(config, dict) else None
    if not isinstance(matrix, dict):
        matrix = {}
    for channel in channels:
        channel_cfg = matrix.get(channel)
        if not isinstance(channel_cfg, dict):
            channel_cfg = {}
        for nt in notify_types:
            channel_cfg.setdefault(nt, defaults[channel][nt])
        matrix[channel] = channel_cfg
    config['notify_matrix'] = matrix
    return config


def _is_notification_enabled(channel, notify_type):
    try:
        config = _normalize_notify_config(load_notify_config())
        return _is_notification_enabled_for_config(config, channel, notify_type)
    except Exception:
        return True


def _is_notification_enabled_for_config(config, channel, notify_type):
    """接受已归一化的配置字典，避免重复读文件"""
    try:
        return bool(config.get('notify_matrix', {}).get(channel, {}).get(notify_type, True))
    except Exception:
        return True


# ====================== 每日早报 ======================

def send_daily_report():
    """每日 8AM 早报 —— 查今天爬取的文章，格式化推送到所有渠道"""
    from datetime import datetime, timezone, timedelta
    BJT = timezone(timedelta(hours=8))
    now = datetime.now(BJT)
    today_start = int(now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
    today_end = int(now.replace(hour=23, minute=59, second=59, microsecond=0).timestamp())

    try:
        from werss.db import DB
        from werss.models.article import Article
        session = DB.get_session()
        try:
            articles = session.query(Article).filter(
                Article.status == 1,
                Article.publish_time >= today_start,
                Article.publish_time <= today_end
            ).order_by(Article.publish_time.desc()).all()
        finally:
            session.close()
    except Exception as e:
        print(f"[DailyReport] 数据库查询失败: {e}")
        articles = []

    total = len(articles)
    if total == 0:
        msg = f"【编舟文心】\n这里是今天的公众号，共0期\n今日暂无新文章\n今日通知已送达"
        send_notification(msg, notify_type='task_reminder')
        return

    lines = [f"这里是今天的公众号，共{total}期"]
    for a in articles:
        if not a.title:
            continue
        lines.append(f"{len(lines)}、{a.title}")

    lines.append("今日通知已送达")
    full_msg = '\n'.join(lines)
    print(f"[DailyReport] 推送早报: {total} 期")
    send_notification(full_msg, notify_type='task_reminder')


# ====================== 失败通知去重 ======================

def _load_notified_failures():
    """加载已通知过的失败文章 URL 集合"""
    try:
        if os.path.exists(NOTIFIED_FAILURES_FILE):
            with open(NOTIFIED_FAILURES_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return set(data.get('urls', []))
    except json.JSONDecodeError as e:
        print(f"[CONFIG] notified_failures.json 解析失败: {e}，重置为空集合")
    except Exception as e:
        print(f"[CONFIG] _load_notified_failures 异常: {e}")
    return set()


def _save_notified_failures(urls_set):
    """保存已通知过的失败文章 URL 集合"""
    try:
        with open(NOTIFIED_FAILURES_FILE, 'w', encoding='utf-8') as f:
            json.dump({'urls': sorted(list(urls_set))}, f, ensure_ascii=False)
    except Exception:
        pass


def is_failure_notified(art_url):
    """检查某篇文章的失败通知是否已发送过"""
    urls = _load_notified_failures()
    return art_url in urls


def mark_failure_notified(art_url):
    """标记某篇文章的失败通知已发送"""
    urls = _load_notified_failures()
    urls.add(art_url)
    _save_notified_failures(urls)


# ====================== WebDAV 业务函数 ======================

def load_webdav_config():
    default_item = {
        'id': 'default',
        'name': '默认 WebDAV',
        'enabled': False,
        'url': '',
        'host': '',
        'port': '',
        'protocol': 'https',
        'username': '',
        'password': '',
        'remote_path': '/',
        'auto_upload': False
    }
    default_config = {
        'version': 2,
        'active_id': 'default',
        'items': [default_item]
    }

    try:
        if os.path.isdir(WEBDAV_CONFIG_FILE):
            print(f"[CONFIG] webdav_config.json 是目录而非文件（可能 Docker volume 误挂载），使用默认配置")
            return default_config
        with open(WEBDAV_CONFIG_FILE, 'r', encoding='utf-8') as f:
            raw = json.load(f)
    except FileNotFoundError:
        return default_config
    except json.JSONDecodeError as e:
        print(f"[CONFIG] webdav_config.json 解析失败: {e}，使用默认配置")
        return default_config
    except Exception as e:
        print(f"[CONFIG] load_webdav_config 异常: {e}，使用默认配置")
        return default_config

    # Multi-item format (version 2+)
    if isinstance(raw, dict) and isinstance(raw.get('items'), list):
        items = []
        for idx, item in enumerate(raw.get('items', [])):
            if not isinstance(item, dict):
                continue
            merged = default_item.copy()
            merged.update(item)
            merged['id'] = str(merged.get('id') or f'webdav_{idx + 1}')
            merged['name'] = str(merged.get('name') or f'WebDAV {idx + 1}')
            merged['remote_path'] = merged.get('remote_path') or '/'
            merged['protocol'] = merged.get('protocol') or 'https'
            items.append(merged)
        if not items:
            items = [default_item.copy()]
        active_id = str(raw.get('active_id') or items[0]['id'])
        if not any(item['id'] == active_id for item in items):
            active_id = items[0]['id']
        # 解密 WebDAV 密码（向后兼容明文）
        for it in items:
            if it.get('password'):
                it['password'] = _decrypt_secret(it['password'])
        return {
            'version': 2,
            'active_id': active_id,
            'items': items
        }

    # Legacy single config format
    if isinstance(raw, dict):
        legacy = default_item.copy()
        legacy.update(raw)
        legacy['id'] = 'default'
        legacy['name'] = legacy.get('name') or '默认 WebDAV'
        legacy['remote_path'] = legacy.get('remote_path') or '/'
        legacy['protocol'] = legacy.get('protocol') or ('https' if str(legacy.get('url', '')).startswith('https://') else 'http' if str(legacy.get('url', '')).startswith('http://') else 'https')
        # 解密 WebDAV 密码（向后兼容明文）
        if legacy.get('password'):
            legacy['password'] = _decrypt_secret(legacy['password'])
        return {
            'version': 2,
            'active_id': 'default',
            'items': [legacy]
        }

    return default_config


def save_webdav_config(config):
    normalized = load_webdav_config()
    if isinstance(config, dict) and isinstance(config.get('items'), list):
        normalized = config

    items = []
    for idx, item in enumerate(normalized.get('items', [])):
        if not isinstance(item, dict):
            continue
        # 加密 WebDAV 密码（避免明文落盘）
        pwd = str(item.get('password') or '')
        if pwd and not pwd.startswith('enc:'):
            pwd = _encrypt_secret(pwd)
        clean = {
            'id': str(item.get('id') or f'webdav_{idx + 1}'),
            'name': str(item.get('name') or f'WebDAV {idx + 1}').strip() or f'WebDAV {idx + 1}',
            'enabled': bool(item.get('enabled')),
            'url': str(item.get('url') or '').strip(),
            'host': str(item.get('host') or '').strip(),
            'port': str(item.get('port') or '').strip(),
            'protocol': str(item.get('protocol') or 'https').strip() or 'https',
            'username': str(item.get('username') or '').strip(),
            'password': pwd,
            'remote_path': str(item.get('remote_path') or '/').strip() or '/',
            'auto_upload': bool(item.get('auto_upload'))
        }
        items.append(clean)

    if not items:
        items.append({
            'id': 'default',
            'name': '默认 WebDAV',
            'enabled': False,
            'url': '',
            'host': '',
            'port': '',
            'protocol': 'https',
            'username': '',
            'password': '',
            'remote_path': '/',
            'auto_upload': False
        })

    active_id = str(normalized.get('active_id') or items[0]['id'])
    if not any(item['id'] == active_id for item in items):
        active_id = items[0]['id']

    payload = {
        'version': 2,
        'active_id': active_id,
        'items': items
    }
    _atomic_write(WEBDAV_CONFIG_FILE, json.dumps(payload, ensure_ascii=False, indent=2))


def _get_active_webdav_item(config=None):
    config = config or load_webdav_config()
    items = config.get('items') or []
    active_id = config.get('active_id')
    for item in items:
        if item.get('id') == active_id:
            return item
    return items[0] if items else None


def _get_enabled_webdav_items(config=None, auto_only=False):
    config = config or load_webdav_config()
    items = []
    for item in config.get('items') or []:
        if not item.get('enabled') or not item.get('url'):
            continue
        if auto_only and not item.get('auto_upload'):
            continue
        items.append(item)
    return items


def add_webdav_log(message):
    timestamp = format_bjt_time()[11:]
    log_entry = f"[{timestamp}] {message}"
    with _status_lock:
        webdav_upload_status['logs'].append(log_entry)
        if len(webdav_upload_status['logs']) > MAX_WEBDAV_LOGS:
            webdav_upload_status['logs'] = webdav_upload_status['logs'][-MAX_WEBDAV_LOGS:]
    print(log_entry)


def upload_to_webdav(file_path, file_name):
    config = load_webdav_config()
    targets = _get_enabled_webdav_items(config, auto_only=True)
    if not targets:
        add_webdav_log('WebDAV 未启用或未配置自动上传目标，跳过上传')
        return {'success': False, 'error': 'WebDAV 未启用'}

    webdav_upload_status['uploading'] = True
    results = []
    try:
        for item in targets:
            target_name = item.get('name') or item.get('id') or 'WebDAV'
            add_webdav_log(f'开始上传到 {target_name}: {file_name}')
            try:
                url = item['url'].rstrip('/') + '/' + item.get('remote_path', '/').strip('/')
                if not url.endswith('/'):
                    url += '/'
                url += file_name
                auth = None
                if item.get('username') and item.get('password'):
                    auth = (item['username'], item['password'])
                with open(file_path, 'rb') as f:
                    resp = requests.put(url, data=f, auth=auth, timeout=30)
                if resp.status_code in (200, 201, 204):
                    add_webdav_log(f'{target_name} 上传成功: {file_name}')
                    results.append({'name': target_name, 'success': True})
                else:
                    add_webdav_log(f'{target_name} 上传失败 ({resp.status_code}): {file_name}')
                    results.append({'name': target_name, 'success': False, 'error': f'HTTP {resp.status_code}'})
            except Exception as e:
                add_webdav_log(f'{target_name} 上传异常: {str(e)[:100]}')
                results.append({'name': target_name, 'success': False, 'error': str(e)[:200]})

        success = all(item['success'] for item in results)
        webdav_upload_status['last_result'] = success
        webdav_upload_status['last_time'] = format_bjt_time()
        if success:
            return {'success': True, 'results': results}
        first_error = next((item.get('error') for item in results if not item['success']), '未知错误')
        return {'success': False, 'error': first_error, 'results': results}
    finally:
        webdav_upload_status['uploading'] = False


# ==================== 通知路由 ====================

@notify_bp.route('/api/notify/config', methods=['GET'])
def get_notify_config():
    config = load_notify_config()
    return jsonify({'success': True, 'config': config})

@notify_bp.route('/api/notify/config', methods=['POST'])
def update_notify_config():
    data = request.get_json()
    config = load_notify_config()
    if 'webhooks' in data:
        config['webhooks'] = data['webhooks']
    if 'serverchans' in data:
        config['serverchans'] = data['serverchans']
    save_notify_config(config)
    return jsonify({'success': True, 'message': '通知配置已保存'})

@notify_bp.route('/api/notify/webhook', methods=['POST'])
def add_webhook():
    data = request.get_json()
    config = load_notify_config()
    webhook = {
        'id': get_bjt_now().strftime('%Y%m%d%H%M%S%f'),
        'name': data.get('name', '未命名'),
        'url': data.get('url', '').strip()
    }
    if not webhook['url']:
        return jsonify({'success': False, 'error': 'URL 不能为空'})
    config['webhooks'].append(webhook)
    save_notify_config(config)
    return jsonify({'success': True, 'webhook': webhook})

@notify_bp.route('/api/notify/webhook/<webhook_id>', methods=['DELETE'])
def delete_webhook(webhook_id):
    config = load_notify_config()
    config['webhooks'] = [w for w in config['webhooks'] if w.get('id') != webhook_id]
    save_notify_config(config)
    return jsonify({'success': True})

@notify_bp.route('/api/notify/webhook/<webhook_id>', methods=['PUT'])
def update_webhook(webhook_id):
    data = request.get_json()
    config = load_notify_config()
    for w in config['webhooks']:
        if w.get('id') == webhook_id:
            if 'name' in data:
                w['name'] = data['name'].strip()
            if 'url' in data:
                w['url'] = data['url'].strip()
            save_notify_config(config)
            return jsonify({'success': True})
    return jsonify({'success': False, 'error': 'Webhook not found'})

@notify_bp.route('/api/notify/serverchan', methods=['POST'])
def add_serverchan():
    data = request.get_json()
    config = load_notify_config()
    serverchan = {
        'id': get_bjt_now().strftime('%Y%m%d%H%M%S%f'),
        'name': data.get('name', '未命名'),
        'key': data.get('key', '').strip()
    }
    if not serverchan['key']:
        return jsonify({'success': False, 'error': 'SendKey 不能为空'})
    config['serverchans'].append(serverchan)
    save_notify_config(config)
    return jsonify({'success': True, 'serverchan': serverchan})

@notify_bp.route('/api/notify/serverchan/<serverchan_id>', methods=['DELETE'])
def delete_serverchan(serverchan_id):
    config = load_notify_config()
    config['serverchans'] = [s for s in config['serverchans'] if s.get('id') != serverchan_id]
    save_notify_config(config)
    return jsonify({'success': True})

@notify_bp.route('/api/notify/serverchan/<serverchan_id>', methods=['PUT'])
def update_serverchan(serverchan_id):
    data = request.get_json()
    config = load_notify_config()
    for s in config['serverchans']:
        if s.get('id') == serverchan_id:
            if 'name' in data:
                s['name'] = data['name'].strip()
            if 'key' in data:
                s['key'] = data['key'].strip()
            save_notify_config(config)
            return jsonify({'success': True})
    return jsonify({'success': False, 'error': 'ServerChan not found'})

@notify_bp.route('/api/notify/test', methods=['POST'])
def test_notify():
    results = send_notification('这是一条测试通知，用于验证通知配置是否正确。', bypass_filter=True)
    if results:
        return jsonify({'success': True, 'message': f'通知发送成功: {", ".join(results)}'})
    else:
        return jsonify({'success': False, 'error': '通知发送失败，请检查配置'})

@notify_bp.route('/api/notify/matrix', methods=['GET'])
def get_notify_matrix():
    """获取全渠道通知类型矩阵"""
    config = _normalize_notify_config(load_notify_config())
    return jsonify({'success': True, 'matrix': config.get('notify_matrix', {})})

@notify_bp.route('/api/notify/matrix', methods=['POST'])
def save_notify_matrix():
    """保存全渠道通知类型矩阵"""
    data = request.get_json()
    config = load_notify_config()
    _normalize_notify_config(config)
    channels = ['email', 'webhook', 'serverchan']
    notify_types = list(NOTIFY_TYPES)
    for channel in channels:
        ch_data = data.get(channel)
        if isinstance(ch_data, dict):
            for nt in notify_types:
                if nt in ch_data:
                    config.setdefault('notify_matrix', {}).setdefault(channel, {})[nt] = bool(ch_data[nt])
    save_notify_config(config)
    return jsonify({'success': True})

@notify_bp.route('/api/notify/email', methods=['GET'])
def get_email_config():
    """获取邮件配置，包含该渠道的通知类型开关"""
    config = _normalize_notify_config(load_notify_config())
    ec = config.get('email', {})
    safe = dict(ec)
    safe['has_password'] = bool(ec.get('smtp_password'))
    safe['smtp_password'] = ''
    # 兼容旧字段
    safe.setdefault('smtp_security', ec.get('smtp_use_tls', True) and 'starttls' or 'none')
    safe.setdefault('max_retries', ec.get('max_retries', 3))
    safe.setdefault('retry_strategy', ec.get('retry_strategy', 'exponential'))
    safe.setdefault('provider', ec.get('provider', ''))
    # 邮件渠道的通知类型开关
    safe['notify_types'] = dict(config.get('notify_matrix', {}).get('email', {}))
    return jsonify({'success': True, 'config': safe})

@notify_bp.route('/api/notify/email/providers', methods=['GET'])
def get_email_providers():
    """返回主流邮箱服务商预设"""
    return jsonify({'success': True, 'providers': EMAIL_PROVIDERS})

@notify_bp.route('/api/notify/email', methods=['POST'])
def save_email_config():
    """保存邮件配置，含该渠道的通知类型开关"""
    data = request.get_json()
    config = load_notify_config()
    ec = config.get('email', {})

    str_fields = ['smtp_host', 'smtp_user', 'smtp_from', 'smtp_to',
                  'smtp_security', 'retry_strategy', 'provider']
    for key in str_fields:
        if key in data:
            ec[key] = data[key].strip() if isinstance(data[key], str) else data[key]
    if 'enabled' in data:
        ec['enabled'] = bool(data['enabled'])
    if 'smtp_port' in data:
        try:
            ec['smtp_port'] = int(data['smtp_port'])
        except Exception:
            ec['smtp_port'] = 465
    if 'max_retries' in data:
        try:
            ec['max_retries'] = int(data['max_retries'])
        except Exception:
            ec['max_retries'] = 3
    if 'smtp_password' in data and data['smtp_password'] and data['smtp_password'].strip():
        ec['smtp_password'] = data['smtp_password'].strip()

    # 若指定了 provider 且 host 为空，自动填充预设
    if ec.get('provider') in EMAIL_PROVIDERS and not ec.get('smtp_host'):
        preset = EMAIL_PROVIDERS[ec['provider']]
        ec['smtp_host'] = preset['host']
        ec['smtp_port'] = preset['port']
        ec['smtp_security'] = preset['security']

    config['email'] = ec

    # 保存邮件渠道的通知类型开关
    if 'notify_types' in data and isinstance(data['notify_types'], dict):
        _normalize_notify_config(config)
        nt = data['notify_types']
        for key in NOTIFY_TYPES:
            if key in nt:
                config.setdefault('notify_matrix', {}).setdefault('email', {})[key] = bool(nt[key])

    save_notify_config(config)
    return jsonify({'success': True})

@notify_bp.route('/api/notify/email/test', methods=['POST'])
def test_email():
    """测试邮件发送（不要求 enabled=true，仅1次尝试，超时15秒）"""
    ec = _get_email_config()
    if not ec:
        # 尝试不检查 enabled 标志重新读取
        ec = _get_email_config_for_test()
    if not ec:
        return jsonify({'success': False, 'error': '邮件未配置，请先填写 SMTP 信息'})
    if not ec["to"]:
        return jsonify({'success': False, 'error': '请填写收件人地址'})
    result = _send_single_email('这是一封来自公众号文章提取助手的测试邮件。\n如果您收到此邮件，说明邮件通知配置成功。', ec)
    if result:
        return jsonify({'success': True, 'message': '测试邮件发送成功'})
    else:
        return jsonify({'success': False, 'error': '邮件发送失败，请检查 SMTP 配置'})


# ==================== WebDAV 路由 ====================

@notify_bp.route('/api/webdav/config', methods=['GET'])
def get_webdav_config():
    config = load_webdav_config()
    active = _get_active_webdav_item(config)
    items = []
    for item in config.get('items', []):
        safe_item = dict(item)
        safe_item['has_password'] = bool(safe_item.get('password'))
        safe_item['password'] = ''
        items.append(safe_item)
    return jsonify({
        'success': True,
        'config': active or {},
        'items': items,
        'active_id': config.get('active_id')
    })

@notify_bp.route('/api/webdav/config', methods=['POST'])
def update_webdav_config():
    data = request.get_json() or {}
    config = load_webdav_config()
    if isinstance(data.get('items'), list):
        config['items'] = data.get('items', [])
        config['active_id'] = data.get('active_id') or config.get('active_id')
        save_webdav_config(config)
        return jsonify({'success': True, 'message': 'WebDAV 配置已保存'})

    item_id = data.get('id') or config.get('active_id') or 'default'
    target = None
    for item in config.get('items', []):
        if item.get('id') == item_id:
            target = item
            break
    if target is None:
        target = {
            'id': str(item_id),
            'name': str(data.get('name') or 'WebDAV').strip() or 'WebDAV',
            'enabled': False,
            'url': '',
            'host': '',
            'port': '',
            'protocol': 'https',
            'username': '',
            'password': '',
            'remote_path': '/',
            'auto_upload': False
        }
        config.setdefault('items', []).append(target)

    if 'name' in data:
        target['name'] = data['name'].strip() or target.get('name') or 'WebDAV'
    if 'url' in data:
        target['url'] = data['url'].strip()
    if 'host' in data:
        target['host'] = data['host'].strip()
    if 'port' in data:
        target['port'] = data['port'].strip()
    if 'protocol' in data:
        target['protocol'] = data['protocol'].strip()
    if 'username' in data:
        target['username'] = data['username'].strip()
    if 'password' in data and data['password'].strip():
        target['password'] = data['password'].strip()
    if 'remote_path' in data:
        target['remote_path'] = data['remote_path'].strip() or '/'
    if 'enabled' in data:
        target['enabled'] = bool(data['enabled'])
    if 'auto_upload' in data:
        target['auto_upload'] = bool(data['auto_upload'])
    if data.get('set_active'):
        config['active_id'] = target['id']
    save_webdav_config(config)
    return jsonify({'success': True, 'message': 'WebDAV 配置已保存'})

@notify_bp.route('/api/webdav/test', methods=['POST'])
def test_webdav():
    data = request.get_json() or {}
    config = load_webdav_config()
    active = _get_active_webdav_item(config) or {}
    test_url = data.get('url', '').strip() or active.get('url', '')
    test_path = data.get('remote_path', '').strip() or active.get('remote_path', '/')
    test_user = data.get('username', '').strip() or active.get('username', '')
    test_pass = data.get('password', '') or active.get('password', '')
    if not test_url:
        return jsonify({'success': False, 'error': '请先配置 WebDAV 地址'})
    try:
        url = test_url.rstrip('/') + '/' + test_path.strip('/')
        if not url.endswith('/'):
            url += '/'
        auth = None
        if test_user and test_pass:
            auth = (test_user, test_pass)
        resp = requests.request('PROPFIND', url, auth=auth, timeout=10, headers={'Depth': '0'})
        if resp.status_code in (207, 200, 301, 302):
            return jsonify({'success': True, 'message': f'连接成功 (HTTP {resp.status_code})'})
        else:
            return jsonify({'success': False, 'error': f'HTTP {resp.status_code}'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)[:200]})

@notify_bp.route('/api/webdav/status')
def get_webdav_status():
    with _status_lock:
        return jsonify({
            'uploading': webdav_upload_status['uploading'],
            'last_result': webdav_upload_status['last_result'],
            'last_time': webdav_upload_status['last_time'],
            'logs': list(webdav_upload_status['logs'])
        })
