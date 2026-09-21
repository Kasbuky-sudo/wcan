# Made by SONGJUNSONG, Jilin Business and Technology College (School of Finance and Economics)
"""爬取与历史记录路由"""
import os
import json
import time
import threading
from datetime import datetime, date, timedelta
from flask import Blueprint, request, jsonify, render_template, send_from_directory
from .core import *
from .core import _atomic_write, _load_json, _safe_thread, _status_lock, __version__

bp = Blueprint('crawl', __name__)

# 全局变量
crawl_history = None  # 惰性加载
_ip_region_cache = {}  # IP 归属地缓存 {ip: (region_code, timestamp)}
_IP_CACHE_TTL = 3600  # 缓存 1 小时
_last_ip_debug_time = 0  # IP 诊断日志节流（5 分钟一次）
_IP_DEBUG_INTERVAL = 300  # 诊断日志最小间隔（秒）


def _is_private_ip(ip):
    """判断是否为内网 IP"""
    if not ip or ip == '未知':
        return True
    parts = ip.split('.')
    if len(parts) != 4:
        return True
    try:
        a, b = int(parts[0]), int(parts[1])
        if a == 10:
            return True
        if a == 172 and 16 <= b <= 31:
            return True
        if a == 192 and b == 168:
            return True
        if a == 127:
            return True
        return False
    except (ValueError, IndexError):
        return True


_BLOCKED_COUNTRIES = {
    'TW': '中国台湾地区',
    'JP': '日本',
    'US': '美国',
    'KR': '韩国',
    'SG': '新加坡',
    'GB': '英国',
    'DE': '德国',
    'FR': '法国',
    'AU': '澳大利亚',
    'CA': '加拿大',
}

_HARD_BLOCK_TIMEZONES = {
    'Asia/Taipei': 'TW',
    'Asia/Tokyo': 'JP',
    'America/New_York': 'US',
    'America/Chicago': 'US',
    'America/Denver': 'US',
    'America/Los_Angeles': 'US',
    'America/Anchorage': 'US',
    'Pacific/Honolulu': 'US',
    'Asia/Seoul': 'KR',
    'Asia/Singapore': 'SG',
    'Europe/London': 'GB',
    'Europe/Berlin': 'DE',
    'Europe/Paris': 'FR',
    'Australia/Sydney': 'AU',
    'Australia/Melbourne': 'AU',
    'Australia/Brisbane': 'AU',
    'Australia/Perth': 'AU',
    'America/Toronto': 'CA',
    'America/Vancouver': 'CA',
    'America/Winnipeg': 'CA',
    'America/Edmonton': 'CA',
    'America/Halifax': 'CA',
}

_HARD_BLOCK_LANG_PREFIXES = {
    'zh-tw': 'TW', 'ja': 'JP', 'en-us': 'US', 'ko': 'KR', 'en-sg': 'SG',
    'en-gb': 'GB', 'de': 'DE', 'fr': 'FR', 'en-au': 'AU', 'en-ca': 'CA', 'fr-ca': 'CA',
}


def _normalize_langs(value):
    langs = []
    if isinstance(value, str):
        raw = value.replace(';', ',').split(',')
    elif isinstance(value, (list, tuple)):
        raw = value
    else:
        raw = []
    for item in raw:
        lang = str(item).strip().split(';')[0].split('q=')[0].lower().replace('_', '-')
        if lang:
            langs.append(lang)
    return langs


def _detect_region_from_locale(timezone=None, languages=None):
    """按浏览器时区/语言推断限制区域，返回 (region, source)。"""
    tz = (timezone or '').strip()
    if tz in _HARD_BLOCK_TIMEZONES:
        return _HARD_BLOCK_TIMEZONES[tz], 'timezone'
    primary_langs = _normalize_langs(languages)
    if primary_langs:
        lang = primary_langs[0]
        for prefix, region in _HARD_BLOCK_LANG_PREFIXES.items():
            if lang == prefix or lang.startswith(prefix + '-'):
                return region, 'language'
    return None, None


def _get_request_locale_region():
    tz = request.cookies.get('client_timezone', '')
    langs = request.cookies.get('client_languages') or request.headers.get('Accept-Language', '')
    return _detect_region_from_locale(tz, langs)


def _get_ip_region(ip):
    """查询 IP 归属地，返回区域代码字符串。
    返回值: 'PRIVATE'(内网), 'CN'(中国大陆), 国家代码(TW/JP/US/...), 'OVERSEAS'(其他海外), 'UNKNOWN'(查询失败)
    """
    if _is_private_ip(ip):
        return 'PRIVATE'
    import time as _time
    now = _time.time()
    cached = _ip_region_cache.get(ip)
    if cached and (now - cached[1]) < _IP_CACHE_TTL:
        return cached[0]
    try:
        import urllib.request
        url = f"http://ip-api.com/json/{ip}?fields=countryCode&lang=zh"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            code = data.get('countryCode', '')
            if code == 'CN':
                region = 'CN'
            elif code in _BLOCKED_COUNTRIES:
                region = code
                print(f"[IP-Check] {ip} 来自 {_BLOCKED_COUNTRIES[code]} ({code})，应用将完全封锁")
            else:
                region = 'OVERSEAS'
                print(f"[IP-Check] {ip} 来自 {code}，不在封锁名单内，放行")
            _ip_region_cache[ip] = (region, now)
            return region
    except Exception as e:
        print(f"[IP-Check] 查询 {ip} 归属地失败: {e}，默认放行")
        _ip_region_cache[ip] = ('UNKNOWN', now)
        return 'UNKNOWN'


def _get_client_ip():
    """获取客户端真实 IP（支持多种反向代理和内网穿透服务）。

    依次检查主流代理/穿透服务使用的 IP 转发头，返回第一个公网 IP。
    若所有头都只有内网/回环 IP（说明代理未传递真实 IP），回退到 remote_addr。

    注意：若内网穿透服务完全不传递任何 IP 头，则此处只能拿到代理服务器 IP，
    无法获取真实客户端 IP——这是网络层限制，应用代码无法解决。
    """
    # 候选头列表，按优先级排序（覆盖主流反向代理与内网穿透服务）
    candidate_headers = [
        'CF-Connecting-IP',      # Cloudflare Tunnel
        'True-Client-IP',        # Cloudflare / Akamai
        'X-Real-IP',             # Nginx / frp / ngrok
        'X-Forwarded-For',       # 标准反向代理（可能含多 IP，取第一个）
        'X-Client-IP',           # 部分代理
        'X-Forwarded',           # 旧版写法
        'Forwarded-For',         # RFC 7239
        'X-Originating-IP',      # 部分企业代理
    ]
    for header in candidate_headers:
        value = request.headers.get(header, '')
        if not value:
            continue
        # X-Forwarded-For 可能是 "client, proxy1, proxy2" 格式，取第一个非空非 unknown
        for part in value.split(','):
            ip = part.strip()
            if not ip or ip.lower() == 'unknown':
                continue
            # 跳过内网/回环 IP（说明该值是代理链中的某一跳，非真实客户端）
            if not _is_private_ip(ip):
                return ip
    # 所有头都没有公网 IP，回退到连接对端地址（通常是代理服务器 IP）
    fallback_ip = request.remote_addr or '未知'
    # 诊断日志：5 分钟打印一次，帮助排查内网穿透服务到底传递了什么
    global _last_ip_debug_time
    now = time.time()
    if now - _last_ip_debug_time > _IP_DEBUG_INTERVAL:
        _last_ip_debug_time = now
        headers_dump = {h: request.headers.get(h, '') for h in candidate_headers if request.headers.get(h, '')}
        print(f"[IP-DEBUG] 未从转发头拿到公网 IP，回退到 remote_addr={fallback_ip}")
        print(f"[IP-DEBUG] 已存在的 IP 相关头: {headers_dump if headers_dump else '（全部为空，代理未传递真实 IP）'}")
        print(f"[IP-DEBUG] 全部请求头 keys: {list(request.headers.keys())}")
    return fallback_ip


_BLOCK_STYLE = '''
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
    min-height: 100vh;
    background: #050505;
}
.block-page {
    min-height: 100vh;
    display: flex;
    flex-direction: column;
    background: #121212;
    border-top: 4px solid #c41e3a;
}
.block-header {
    background: #000;
    padding: 18px 40px;
    text-align: center;
    border-bottom: 1px solid #1a1a1a;
}
.block-header .header-text {
    font-size: 28px;
    font-weight: 900;
    color: #c41e3a;
    letter-spacing: 8px;
}
.block-body {
    flex: 1;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    padding: 70px 50px 50px;
}
.metal-lock { width: 72px; height: 72px; margin-bottom: 36px; }
.block-title {
    font-size: 22px;
    font-weight: 900;
    color: #fff;
    text-align: center;
    line-height: 2;
    margin-bottom: 24px;
    letter-spacing: 1px;
}
.block-title .law-ref { color: #e8e8e8; font-weight: 700; }
.block-divider {
    width: 100%;
    max-width: 420px;
    height: 1px;
    background: #333;
    margin-bottom: 24px;
}
.block-desc {
    font-size: 14px;
    color: #888;
    text-align: center;
    line-height: 2;
    max-width: 440px;
    margin-bottom: 32px;
}
.block-warning {
    font-size: 11px;
    color: #444;
    text-align: center;
    line-height: 1.8;
    max-width: 400px;
    padding: 12px 20px;
    border: 1px solid #2a2a2a;
}
.block-footer {
    padding: 14px 40px;
    background: #0a0a0a;
    text-align: center;
    color: #333;
    font-size: 11px;
    letter-spacing: 2px;
    border-top: 1px solid #1a1a1a;
}
'''

_LOCK_SVG = '''<svg viewBox="0 0 64 64" fill="none" xmlns="http://www.w3.org/2000/svg">
<path d="M20 28V20C20 13.4 25.4 8 32 8C38.6 8 44 13.4 44 20V28" stroke="#555" stroke-width="4" stroke-linecap="square"/>
<rect x="12" y="28" width="40" height="30" fill="#2a2a2a" stroke="#555" stroke-width="2"/>
<rect x="12" y="28" width="40" height="4" fill="#1a1a1a"/>
<rect x="28" y="40" width="8" height="10" fill="#666"/>
<rect x="29" y="41" width="6" height="8" fill="#1a1a1a"/>
<circle cx="32" cy="40" r="1.5" fill="#888"/>
</svg>'''


_BLOCK_PAGE_DATA = {
    'TW': {
        'lang': 'zh-TW',
        'font': '"Microsoft JhengHei", "PingFang TC", "Noto Sans TC", sans-serif',
        'header': '您已被封鎖',
        'law_ref': '依據《中華人民共和國網絡安全法》《生成式人工智能服務管理暫行辦法》等規定',
        'title': '本應用依法暫停向中國台灣地區用戶提供服務',
        'desc': '若需正常使用本軟件，請透過中國大陸網路環境進行訪問。',
        'warning': '任何繞開網路限制的存取行為，均違反相關網路管理條例。',
    },
    'JP': {
        'lang': 'ja',
        'font': '"Hiragino Kaku Gothic ProN", "Yu Gothic", "Meiryo", "Noto Sans JP", sans-serif',
        'header': 'アクセスがブロックされました',
        'law_ref': '中華人民共和国網絡安全法及び生成式人工知能サービス管理暫定弁法等の規定に基づき',
        'title': '本アプリは依法じて日本国内のユーザーに対する<br>サービス提供を停止しております',
        'desc': '本アプリを正常にご利用いただくには、<br>中国大陸のネットワーク環境からアクセスしてください。',
        'warning': 'ネットワーク制限を回避するいかなるアクセス行為も、<br>関連ネットワーク管理条例に違反します。',
    },
    'KR': {
        'lang': 'ko',
        'font': '"Malgun Gothic", "Noto Sans KR", sans-serif',
        'header': '접근이 차단되었습니다',
        'law_ref': '중화인민공화국 사이버보안법 및 생성형 인공지능 서비스 관리 잠정 조치 등에 따라',
        'title': '본 애플리케이션은 한국 사용자에게<br>서비스를 제공하지 않습니다',
        'desc': '본 애플리케이션을 이용하려면<br>중국 대륙 네트워크 환경에서 접속하십시오.',
        'warning': '네트워크 제한을 우회하는 모든 접근 행위는<br>관련 규정에 위배됩니다.',
    },
    'DE': {
        'lang': 'de',
        'font': '"Segoe UI", "Arial", sans-serif',
        'header': 'ZUGRIFF VERWEIGERT',
        'law_ref': 'Gemäß dem Cybersicherheitsgesetz der VR China und den Interimsmaßnahmen zur Verwaltung generativer KI-Dienste',
        'title': 'Diese Anwendung ist für Benutzer in Deutschland nicht verfügbar',
        'desc': 'Um diese Anwendung zu nutzen, greifen Sie bitte aus dem chinesischen Festland zu.',
        'warning': 'Jeder Versuch, Netzwerkbeschränkungen zu umgehen, verstößt gegen relevante Verordnungen.',
    },
    'FR': {
        'lang': 'fr',
        'font': '"Segoe UI", "Arial", sans-serif',
        'header': 'ACCÈS REFUSÉ',
        'law_ref': "Conformément à la loi sur la cybersécurité de la RPC et aux mesures provisoires de gestion des services d'IA générative",
        'title': "Cette application n'est pas disponible pour les utilisateurs en France",
        'desc': "Pour utiliser cette application, veuillez y accéder depuis la Chine continentale.",
        'warning': 'Toute tentative de contournement des restrictions réseau viole les réglementations pertinentes.',
    },
}


_EN_BLOCK_TEMPLATE = {
    'lang': 'en',
    'font': '"Segoe UI", "Arial", sans-serif',
    'header': 'ACCESS DENIED',
    'law_ref': 'In accordance with the Cybersecurity Law of the PRC and the Interim Measures for the Management of Generative AI Services',
    'title': None,
    'desc': 'To use this application, please access it from within mainland China.',
    'warning': 'Any attempt to bypass network restrictions may violate relevant regulations.',
}

_EN_TITLES = {
    'US': 'This application is not available to users in the United States',
    'SG': 'This application is not available to users in Singapore',
    'GB': 'This application is not available to users in the United Kingdom',
    'AU': 'This application is not available to users in Australia',
    'CA': 'This application is not available to users in Canada',
}

for _code in _EN_TITLES:
    _data = dict(_EN_BLOCK_TEMPLATE)
    _data['title'] = _EN_TITLES[_code]
    _BLOCK_PAGE_DATA[_code] = _data


def _build_block_page(country_code):
    d = _BLOCK_PAGE_DATA.get(country_code)
    if not d:
        return None
    title_html = d['title'].replace('\n', '<br>')
    return '''<!DOCTYPE html>
<html lang="''' + d['lang'] + '''">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>ACCESS DENIED</title>
<style>''' + _BLOCK_STYLE + '''.block-body { font-family: ''' + d['font'] + '''; }</style>
</head>
<body>
<div class="block-page">
    <div class="block-header"><div class="header-text">''' + d['header'] + '''</div></div>
    <div class="block-body">
        <div class="metal-lock">''' + _LOCK_SVG + '''</div>
        <div class="block-title">
            <span class="law-ref">''' + d['law_ref'] + '''</span><br>
            ''' + title_html + '''
        </div>
        <div class="block-divider"></div>
        <div class="block-desc">''' + d['desc'] + '''</div>
        <div class="block-warning">''' + d['warning'] + '''</div>
    </div>
    <div class="block-footer">HTTP 403 · ACCESS DENIED · GEO-RESTRICTED</div>
</div>
</body>
</html>'''


HISTORY_HTML_FILE = os.path.join(DATA_DIR, 'data', 'history.html')


# ==================== 历史记录业务函数 ====================

def _load_crawl_history():
    global crawl_history
    if crawl_history is not None:
        return
    try:
        with open(CRAWL_HISTORY_FILE, 'r', encoding='utf-8') as f:
            crawl_history = json.load(f)
    except json.JSONDecodeError as e:
        print(f"[CONFIG] crawl_history.json 解析失败: {e}，重置为空列表")
        crawl_history = []
    except Exception as e:
        print(f"[CONFIG] _load_crawl_history 异常: {e}")
        crawl_history = []

def _save_crawl_history():
    global crawl_history
    if crawl_history is None:
        return
    try:
        with open(CRAWL_HISTORY_FILE, 'w', encoding='utf-8') as f:
            json.dump(crawl_history[-MAX_CRAWL_HISTORY:], f, ensure_ascii=False, indent=2)
        _save_history_html()
    except Exception:
        pass

def _escape_html(s):
    if not s:
        return ''
    return str(s).replace('&', '&amp;').replace('"', '&quot;').replace('<', '&lt;').replace('>', '&gt;').replace("'", '&#39;')

def _format_ts(ts):
    """将时间戳转为 'YYYY-MM-DD' 格式，0 返回空"""
    if not ts or ts == 0:
        return ''
    try:
        return time.strftime('%Y-%m-%d', time.localtime(int(ts)))
    except Exception:
        return ''

def _history_sort_key(item: dict) -> float:
    """历史记录排序键：优先用 publish_time（时间戳），回退到 processed_at（字符串日期）。
    确保本地同步文件（无 publish_time）也能按时间正确排序，而不是全部沉底。
    """
    # 1. 优先使用 publish_time
    pt = item.get('publish_time', 0)
    if pt and isinstance(pt, (int, float)) and pt > 0:
        return float(pt)
    # 2. 回退到 processed_at 字符串解析
    pa = item.get('processed_at', '') or ''
    if pa and pa != '未知':
        try:
            # 格式 "YYYY-MM-DD HH:MM:SS" 或 "YYYY-MM-DD"
            dt = datetime.strptime(pa.split('.')[0][:19], '%Y-%m-%d %H:%M:%S')
            return dt.timestamp()
        except Exception:
            try:
                dt = datetime.strptime(pa[:10], '%Y-%m-%d')
                return dt.timestamp()
            except Exception:
                pass
    # 3. 最终回退到 0（最旧）
    return 0.0

def _save_history_html():
    global crawl_history
    if crawl_history is None:
        _load_crawl_history()
    if not crawl_history:
        html = '<div class="empty-state"><div class="empty-icon"><svg class="ico" width="14" height="14" viewBox="0 0 24 24"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg></div><div>暂无历史记录</div></div>'
        try:
            with open(HISTORY_HTML_FILE, 'w', encoding='utf-8') as f:
                f.write(html)
        except Exception:
            pass
        return

    sorted_history = sorted(crawl_history, key=lambda x: _history_sort_key(x), reverse=True)
    parts = []
    last_date = ''

    for item in sorted_history:
        # 日期分隔：优先使用发表时间，回退到处理时间
        publish_date = _format_ts(item.get('publish_time', 0))
        if publish_date:
            date_label = publish_date
        else:
            date_label = (item.get('processed_at', '') or '').split(' ')[0] if item.get('processed_at') else ''
        if date_label and date_label != last_date:
            parts.append(f'<div class="history-date-divider">{date_label}</div>')
            last_date = date_label

        title = _escape_html(item.get('title', '无标题'))
        link = _escape_html(item.get('link', ''))
        feed_name = _escape_html(item.get('feed_name', '单篇抓取'))
        error = _escape_html(item.get('error', ''))
        processed_at = item.get('processed_at', '')
        publish_time = _format_ts(item.get('publish_time', 0))

        # ===== 状态判定 =====
        is_failed = not item.get('success') and not item.get('is_repost')
        is_repost = item.get('is_repost', False)
        is_modified = item.get('modified', False)
        is_dup = item.get('success') and not item.get('is_repost') and not is_modified and not link and item.get('local_file', False)
        exhausted = item.get('retry_exhausted', False)

        # 状态类 + 图标 + 徽章
        state_class = 'h-normal'
        icon_svg = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="var(--wc-green)" stroke-width="3"><polyline points="20 6 9 17 4 12"/></svg>'
        badge = ''

        if is_modified:
            state_class = 'h-modified'
            icon_svg = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="var(--wc-green)" stroke-width="2.2"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>'
            badge = '<span class="history-badge b-modified">已修改</span>'
        elif is_repost:
            state_class = 'h-repost'
            icon_svg = '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="var(--wc-text-tertiary)" stroke-width="2.5"><path d="M21.5 2v6h-6M2.5 22v-6h6M2 11.5a10 10 0 0 1 18.8-4.3M22 12.5a10 10 0 0 1-18.8 4.2"/></svg>'
            badge = '<span class="history-badge b-repost">转载</span>'
        elif is_failed:
            state_class = 'h-failed'
            icon_svg = '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="var(--wc-red)" stroke-width="3"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>'
            if exhausted:
                badge = '<span class="history-badge b-exhausted">重试耗尽</span>'
            else:
                badge = '<span class="history-badge b-failed">失败</span>'
        elif is_dup:
            state_class = 'h-dup'
            icon_svg = '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#10aeff" stroke-width="2.2"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>'
            badge = '<span class="history-badge b-dup">本地</span>'

        # 元信息行
        meta_parts_list = []
        if publish_time:
            meta_parts_list.append(f'<span>发表 {publish_time}</span>')
        if processed_at:
            meta_parts_list.append(f'<span>处理 {processed_at}</span>')
        meta_parts_list.append(f'<span>{feed_name}</span>')
        if link:
            meta_parts_list.append(f'<span><a href="{link}" target="_blank" onclick="event.stopPropagation()">原文</a></span>')
        if is_failed and error:
            meta_parts_list.append(f'<span class="meta-error">{error}</span>')
        meta_html = ''.join(meta_parts_list)

        title_attr = f' data-title="{_escape_html(title)}"' if title else ''

        parts.append(f'''<div class="history-item {state_class}" data-link="{link}"{title_attr}>
            <div class="history-title-row">
                <span class="history-title-icon">{icon_svg}</span>
                <span class="history-title">{title}</span>
                {badge}
            </div>
            <div class="history-meta">{meta_html}</div>
        </div>''')

    html = ''.join(parts)
    try:
        os.makedirs(os.path.dirname(HISTORY_HTML_FILE), exist_ok=True)
        with open(HISTORY_HTML_FILE, 'w', encoding='utf-8') as f:
            f.write(html)
    except Exception:
        pass

def add_to_crawl_history(item: dict):
    global crawl_history
    _load_crawl_history()
    title = item.get('title', '')
    link = item.get('link', '')
    for existing in crawl_history:
        if existing.get('title') == title and existing.get('link') == link:
            existing['success'] = item.get('success', existing.get('success'))
            existing['is_repost'] = item.get('is_repost', existing.get('is_repost'))
            existing['error'] = item.get('error', existing.get('error'))
            existing['retry_exhausted'] = item.get('retry_exhausted', existing.get('retry_exhausted'))
            existing['processed_at'] = item.get('processed_at', existing.get('processed_at'))
            existing['feed_name'] = item.get('feed_name', existing.get('feed_name'))
            existing['modified'] = item.get('modified', existing.get('modified', False))
            if item.get('publish_time'):
                existing['publish_time'] = item['publish_time']
            _save_crawl_history()
            return
    crawl_history.insert(0, item)
    if len(crawl_history) > MAX_CRAWL_HISTORY:
        crawl_history = crawl_history[:MAX_CRAWL_HISTORY]
    _save_crawl_history()


# ==================== Token 过期检测 ====================

def get_token_expiry():
    try:
        from werss.driver.token import wx_cfg
        from werss.driver.wx_api import WeChat_api
        token_data = wx_cfg.get("token_data", None)
        if not token_data:
            return None
        expiry = token_data.get("expiry", {})
        expiry_timestamp = expiry.get("expiry_timestamp")
        if not expiry_timestamp:
            return None
        if not WeChat_api.HasLogin():
            return None
        now = time.time()
        remaining = max(0, expiry_timestamp - now)
        return {
            "expiry_timestamp": expiry_timestamp,
            "expiry_time": expiry.get("expiry_time", time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(expiry_timestamp))),
            "remaining_seconds": int(remaining),
        }
    except Exception:
        return None

def check_token_expiry_and_notify():
    from .routes_notify import load_notify_config, save_notify_config, send_notification
    expiry_info = get_token_expiry()
    if not expiry_info or not expiry_info.get("expiry_timestamp"):
        return False
    now = time.time()
    remaining = expiry_info["expiry_timestamp"] - now
    from werss.config import cfg
    threshold_hours = int(cfg.get("token_reminder_hours", 12))
    threshold_seconds = threshold_hours * 3600
    if remaining > threshold_seconds:
        return False
    config = load_notify_config()
    today = get_bjt_now().strftime("%Y-%m-%d")
    if config.get("last_token_reminder") == today:
        return False
    if remaining <= 0:
        message = "❌ 微信公众平台授权已过期！请立即重新扫码授权。"
    else:
        hours = int(remaining // 3600)
        message = f"⚠️ 微信公众平台授权将在 {hours} 小时后过期，请及时重新扫码。"
    send_notification(message, notify_type='rss_expiry')
    config["last_token_reminder"] = today
    save_notify_config(config)
    return True

def add_log(message):
    timestamp = format_bjt_time()[11:]
    log_entry = f"[{timestamp}] {message}"
    with _status_lock:
        crawl_status['logs'].append(log_entry)
        if len(crawl_status['logs']) > MAX_CRAWL_LOGS:
            crawl_status['logs'] = crawl_status['logs'][-MAX_CRAWL_LOGS:]
    print(log_entry)

def crawl_article_thread(url):
    global crawl_status
    try:
        with _status_lock:
            crawl_status['status'] = 'running'
            crawl_status['progress'] = 0
            crawl_status['message'] = '开始爬取文章...'
            crawl_status['last_url'] = url
        add_log('开始爬取微信公众号文章')
        with _status_lock:
            sync_status['articles'] = [{'title': '加载中...', 'status': 'crawling', 'mp_name': '', 'error': '', 'progress': 0}]
            sync_status['phase'] = 'processing'
            crawl_status['progress'] = 10
            crawl_status['message'] = '正在解析网页...'
        add_log(f'目标URL: {url}')
        with _status_lock:
            sync_status['articles'][0] = {'title': '解析网页...', 'status': 'crawling', 'mp_name': '', 'error': '', 'progress': 10}
            sync_status['progress'] = 10
        result = crawler.crawl_article(url, progress_callback=on_crawl_progress, auto_save=False)
        if result['success']:
            add_log(f"标题: {result['title']}")
            add_log(f"日期: {result['publish_date'].strftime('%Y年%m月%d日')}")
            text_count = sum(1 for c in result['content_items'] if c['type'] == 'text')
            img_count = sum(1 for c in result['content_items'] if c['type'] == 'image')
            add_log(f"内容: {text_count}段文字, {img_count}张图片")
            add_log('生成文档预览')
            with _status_lock:
                crawl_status['progress'] = 90
                crawl_status['message'] = '生成预览中...'
                sync_status['articles'][0] = {'title': result['title'], 'status': 'building', 'mp_name': '', 'error': '', 'progress': 90}
                sync_status['progress'] = 90
                sync_status['message'] = '正在生成Word文档...'
            preview_html = crawler.generate_preview_html(
                result['title'], result['publish_date'], result['content_items']
            )
            doc = crawler.create_word_document(
                result['title'], result['publish_date'], result['content_items'], save_file=False
            )
            with _status_lock:
                crawl_status['preview_data'] = {
                    'html': preview_html,
                    'title': result['title'],
                    'publish_date': result['publish_date']
                }
                crawl_status['document_data'] = {
                    'doc': doc,
                    'title': result['title'],
                    'publish_date': result['publish_date'],
                    'content_items': result['content_items']
                }
                crawl_status['progress'] = 100
                crawl_status['status'] = 'preview_ready'
                crawl_status['message'] = '预览已生成，请确认后保存'
                sync_status['articles'][0] = {'title': result['title'], 'status': 'done', 'mp_name': '', 'error': '', 'progress': 100}
                sync_status['progress'] = 100
                sync_status['message'] = '预览生成完成，请确认保存'
                sync_status['phase'] = 'done'
                sync_status['running'] = False
            add_log('文档预览生成完成，等待用户确认')
            debug_log('INFO', 'crawl', f'爬取成功: {result["title"]}')
        else:
            if result.get('is_repost'):
                msg = f'转载文章，已跳过'
                with _status_lock:
                    crawl_status['status'] = 'error'
                    crawl_status['message'] = msg
                    sync_status['articles'][0] = {'title': result.get('title', '?'), 'status': 'skip_repost', 'mp_name': '', 'error': '', 'progress': 100}
                add_log(f'跳过转载: {result.get("error", "转载文章")}')
                debug_log('WARNING', 'crawl', f'跳过转载文章: {result.get("title", "?")}')
            else:
                err = result.get('error', '未知错误')
                with _status_lock:
                    crawl_status['status'] = 'error'
                    crawl_status['message'] = f'爬取失败: {err}'
                    sync_status['articles'][0] = {'title': result.get('title', '?'), 'status': 'error', 'mp_name': '', 'error': err, 'progress': 100}
                add_log(f'爬取失败: {err}')
                debug_log('ERROR', 'crawl', f'爬取失败: {err}', {'url': url, 'title': result.get('title', '?')})
                # 单篇爬取失败通知
                try:
                    from .routes_notify import send_notification
                    title = result.get('title', '未知标题')
                    send_notification(f"❌ 单篇文章提取失败\n完成时间：{format_bjt_time()}\n文章：{title}\n原因：{err[:200]}", notify_type='error_reminder')
                except Exception:
                    pass
            with _status_lock:
                sync_status['progress'] = 100
                sync_status['phase'] = 'done'
                sync_status['running'] = False
    except Exception as e:
        with _status_lock:
            crawl_status['status'] = 'error'
            crawl_status['message'] = f'发生错误: {str(e)}'
            sync_status['articles'] = [{'title': '未知', 'status': 'error', 'mp_name': '', 'error': str(e), 'progress': 100}]
            sync_status['progress'] = 100
            sync_status['phase'] = 'done'
            sync_status['running'] = False
        add_log(f'发生错误: {str(e)}')
        # 异常通知
        try:
            from .routes_notify import send_notification
            send_notification(f"❌ 单篇文章提取异常\n完成时间：{format_bjt_time()}\nURL：{url[:80]}\n异常：{str(e)[:200]}", notify_type='error_reminder')
        except Exception:
            pass

def on_crawl_progress(progress, message):
    with _status_lock:
        crawl_status['progress'] = progress
        crawl_status['message'] = message
    add_log(message)


# ==================== 页面与静态资源路由 ====================

@bp.route('/')
def index():
    lunar_red = is_lunar_red_date()
    from werss.config import cfg
    storage_year = cfg.get('storage_year', '')
    # 获取客户端 IP（支持反向代理）
    client_ip = _get_client_ip()
    return render_template('index.html', lunar_red=lunar_red, version=__version__, storage_year=storage_year, client_ip=client_ip)

@bp.route('/<path:filename>')
def static_files(filename):
    # 安全检查：禁止路径遍历
    if filename.startswith('.') or '..' in filename:
        return jsonify({'error': 'Forbidden'}), 403
    # 禁止访问敏感扩展名（配置/数据库/源码/日志等）
    sensitive_exts = {'.yaml', '.yml', '.json', '.db', '.py', '.pyc', '.env', '.lic', '.log', '.md', '.txt', '.sh', '.bat', '.ps1'}
    _, ext = os.path.splitext(filename)
    if ext.lower() in sensitive_exts:
        return jsonify({'error': 'Forbidden'}), 403
    # 禁止访问敏感目录
    sensitive_dirs = {'data', 'update', '__pycache__', '.git', 'node_modules', 'venv', '.venv'}
    parts = filename.replace('\\', '/').split('/')
    if any(p in sensitive_dirs for p in parts):
        return jsonify({'error': 'Forbidden'}), 403
    # 运行时生成的文件（如微信扫码二维码 wx_qrcode.png）落在可写目录的 static/ 下，
    # 优先于打包资源提供：冻结成 exe 后二者不在同一个目录
    runtime_path = os.path.join(user_dir(), filename)
    if os.path.isfile(runtime_path):
        return send_from_directory(os.path.dirname(runtime_path), os.path.basename(runtime_path))
    return send_from_directory(bundle_dir(), filename)

def is_lunar_red_date():
    bjt_now = get_bjt_now()
    today = bjt_now.date()
    lunar_new_years = {
        2025: (1, 29), 2026: (2, 17), 2027: (2, 6),
        2028: (1, 26), 2029: (2, 13), 2030: (2, 3),
    }
    for year, (m, d) in lunar_new_years.items():
        chunjie = date(year, m, d)
        chuxi = chunjie - timedelta(days=1)
        yuanxiao = chunjie + timedelta(days=14)
        if today in (chuxi, chunjie, yuanxiao):
            return True
    return False

@bp.route('/api/lunar-theme')
def api_lunar_theme():
    bjt_now = get_bjt_now()
    return jsonify({
        'is_lunar_red': is_lunar_red_date(),
        'bjt_date': bjt_now.strftime('%Y-%m-%d %H:%M:%S'),
    })


# ==================== 文章提取 ====================

@bp.route('/crawl', methods=['POST'])
@rate_limit(max_calls=10, window=60)
def crawl():
    data = request.get_json()
    url = data.get('url', '').strip()
    if not url:
        return jsonify({'success': False, 'error': '请输入有效的URL'})
    if not url.startswith('https://mp.weixin.qq.com/'):
        return jsonify({'success': False, 'error': '请输入有效的微信公众号文章链接'})
    # 手动操作：重置状态后立即启动新任务
    with _status_lock:
        crawl_status['progress'] = 0
        crawl_status['status'] = 'idle'
        crawl_status['message'] = '准备开始...'
        crawl_status['logs'] = []
        crawl_status['preview_data'] = None
        crawl_status['document_data'] = None
    reset_sync_status('开始爬取...', mode='single')
    thread = threading.Thread(target=crawl_article_thread, args=(url,))
    thread.daemon = True
    thread.start()
    return jsonify({'success': True, 'message': '开始爬取'})

@bp.route('/status')
def status():
    with _status_lock:
        return jsonify({
            'progress': crawl_status['progress'],
            'status': crawl_status['status'],
            'message': crawl_status['message'],
            'logs': list(crawl_status['logs'])
        })

@bp.route('/preview')
def preview():
    with _status_lock:
        preview_data = crawl_status['preview_data']
    if preview_data:
        return jsonify({
            'success': True,
            'html': preview_data['html'],
            'title': preview_data['title'],
            'date': preview_data['publish_date'].strftime('%Y年%m月%d日')
        })
    else:
        return jsonify({'success': False, 'error': '没有可预览的内容'})

@bp.route('/save_document', methods=['POST'])
def save_document():
    with _status_lock:
        doc_data = crawl_status['document_data']
        last_url = crawl_status.get('last_url', '')
    if not doc_data:
        return jsonify({'success': False, 'error': '没有可保存的文档'})
    try:
        file_path = crawler.save_document(doc_data['doc'], doc_data['title'], doc_data['publish_date'], last_url)
        temp_files = getattr(doc_data['doc'], '_temp_image_files', [])
        for tmp in temp_files:
            try:
                os.remove(tmp)
            except Exception:
                pass
        crawl_status['preview_data'] = None
        crawl_status['document_data'] = None
        crawl_status['status'] = 'completed'
        crawl_status['message'] = f'文档已保存至: {file_path}'
        add_log(f'文档保存成功: {file_path}')

        try:
            from werss.db import DB
            import hashlib
            url = crawl_status.get('last_url', '')
            art_id = hashlib.md5(url.encode()).hexdigest() if url else get_bjt_now().strftime('%Y%m%d%H%M%S%f')
            article_data = {
                'id': art_id,
                'title': doc_data['title'],
                'url': url,
                'mp_id': '单篇抓取',
                'publish_time': int(doc_data['publish_date'].timestamp()) if doc_data.get('publish_date') else 0,
            }
            DB.add_article(article_data)
            add_log(f'已记录到历史: {doc_data["title"]}')

            # 写入 crawl_history 并生成 HTML
            add_to_crawl_history({
                'title': doc_data['title'],
                'link': url,
                'processed_at': get_bjt_now().strftime('%Y-%m-%d %H:%M:%S'),
                'feed_name': '单篇抓取',
                'success': True,
                'is_repost': False,
                'retry_exhausted': False,
                'error': None,
                'publish_time': int(doc_data['publish_date'].timestamp()) if doc_data.get('publish_date') else 0,
            })
        except Exception as he:
            add_log(f'历史记录写入失败: {he}')

        from .routes_notify import load_webdav_config, upload_to_webdav
        webdav_config = load_webdav_config()
        if webdav_config.get('enabled') and webdav_config.get('auto_upload'):
            file_name = os.path.basename(file_path)
            _safe_thread(upload_to_webdav, args=(file_path, file_name))

        completion_time = format_bjt_time()
        print(f"[Extract] 文章已保存: {doc_data['title']}")

        return jsonify({'success': True, 'message': '文档保存成功', 'file_path': file_path})
    except Exception as e:
        add_log(f'保存文档失败: {str(e)}')
        return jsonify({'success': False, 'error': f'保存失败: {str(e)}'})

@bp.route('/cancel_preview', methods=['POST'])
def cancel_preview():
    with _status_lock:
        crawl_status['preview_data'] = None
        crawl_status['document_data'] = None
        crawl_status['status'] = 'idle'
        crawl_status['message'] = '已取消，可以重新开始'
        crawl_status['progress'] = 0
    add_log('用户取消了预览')
    return jsonify({'success': True, 'message': '已取消预览'})


# ==================== 历史记录路由 ====================

@bp.route('/api/history', methods=['GET'])
def get_history():
    page = request.args.get('page', 1, type=int)
    page_size = request.args.get('page_size', 50, type=int)
    keyword = request.args.get('keyword', '', type=str).strip()
    if page < 1:
        page = 1
    if page_size < 1 or page_size > 500:
        page_size = DEFAULT_PAGE_SIZE
    limit = page_size  # 兼容 DB 回退逻辑
    _load_crawl_history()
    if crawl_history:
        sorted_history = sorted(crawl_history, key=lambda x: _history_sort_key(x), reverse=True)
        # 关键词过滤（匹配标题或公众号名）
        if keyword:
            kw_lower = keyword.lower()
            sorted_history = [h for h in sorted_history
                              if kw_lower in (h.get('title', '') or '').lower()
                              or kw_lower in (h.get('feed_name', '') or '').lower()]
        total = len(sorted_history)
        start = (page - 1) * page_size
        end = start + page_size
        return jsonify({
            'success': True,
            'history': sorted_history[start:end],
            'total': total,
            'page': page,
            'page_size': page_size,
            'total_pages': (total + page_size - 1) // page_size
        })
    try:
        from werss.db import DB
        from werss.models.article import Article
        with DB.session_scope() as session:
            query = session.query(Article)
            if keyword:
                # 转义 LIKE 通配符，防止用户输入 % 或 _ 引发非预期匹配
                kw = keyword.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
                query = query.filter(Article.title.like(f'%{kw}%', escape='\\'))
            total = query.count()
            articles = query.order_by(Article.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()
            result = []
            for a in articles:
                result.append({
                    'link': a.url or '',
                    'title': a.title or '',
                    'processed_at': a.created_at.isoformat() if a.created_at and hasattr(a.created_at, 'isoformat') else str(a.created_at or ''),
                    'feed_name': a.mp_id or '单篇抓取',
                    'success': True,
                    'is_repost': False,
                    'retry_exhausted': False,
                    'error': None
                })
        return jsonify({
            'success': True,
            'history': result,
            'total': total,
            'page': page,
            'page_size': page_size,
            'total_pages': (total + page_size - 1) // page_size
        })
    except Exception:
        try:
            with open(OLD_HISTORY_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if keyword:
                kw_lower = keyword.lower()
                data = [h for h in data if kw_lower in (h.get('title', '') or '').lower()]
            total = len(data)
            start = (page - 1) * page_size
            return jsonify({
                'success': True,
                'history': data[start:start + page_size],
                'total': total,
                'page': page,
                'page_size': page_size,
                'total_pages': (total + page_size - 1) // page_size
            })
        except json.JSONDecodeError as e:
            print(f"[CONFIG] old history.json 解析失败: {e}")
            return jsonify({'success': True, 'history': [], 'total': 0, 'page': page, 'page_size': page_size, 'total_pages': 0})
        except Exception as e:
            print(f"[API] /api/history 旧格式回退异常: {e}")
            return jsonify({'success': True, 'history': [], 'total': 0, 'page': page, 'page_size': page_size, 'total_pages': 0})

@bp.route('/api/history-html', methods=['GET'])
def get_history_html():
    """返回服务端预渲染的历史记录 HTML"""
    global crawl_history
    _load_crawl_history()
    # 确保 HTML 文件存在且是最新的
    if not os.path.exists(HISTORY_HTML_FILE) or not crawl_history:
        _save_history_html()
    try:
        with open(HISTORY_HTML_FILE, 'r', encoding='utf-8') as f:
            html = f.read()
        return jsonify({'success': True, 'html': html})
    except Exception:
        return jsonify({'success': False, 'html': '<div class="empty-state"><div class="empty-icon">⚠️</div><div>加载失败，请刷新重试</div></div>'})

@bp.route('/api/history/clear', methods=['POST'])
def clear_history():
    """清空全部历史记录（需密码验证，操作日志埋点）"""
    import datetime as dt
    now = dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    data = request.get_json(silent=True) or {}
    pwd = data.get('password', '')
    from werss.config import cfg
    admin_pwd = os.environ.get('WCAN_ADMIN_PWD') or cfg.get('admin_password', '')
    if not admin_pwd or pwd != admin_pwd:
        # 记录失败尝试
        try:
            with open(os.path.join(DATA_DIR, 'clear_history.log'), 'a', encoding='utf-8') as f:
                f.write(f'[{now}] 清空尝试 | 结果: 密码错误\n')
        except Exception:
            pass
        return jsonify({'success': False, 'message': '密码错误，请重新输入'})

    errors = []
    cleared_items = 0

    # 1. 清空新架构 crawl_history.json
    try:
        with open(CRAWL_HISTORY_FILE, 'w', encoding='utf-8') as f:
            json.dump([], f)
    except Exception as e:
        errors.append(f'crawl_history.json: {e}')

    # 2. 清空旧架构 history.json
    if os.path.exists(OLD_HISTORY_FILE):
        try:
            with open(OLD_HISTORY_FILE, 'w', encoding='utf-8') as f:
                json.dump([], f)
        except Exception:
            pass

    # 3. 清空内存 + 新架构 history.html
    global crawl_history
    crawl_history = []
    _save_history_html()

    # 4. 清空 DB Article 表
    try:
        from werss.db import DB
        from werss.models.article import Article
        with DB.session_scope() as session:
            cleared_items = session.query(Article).count()
            session.query(Article).delete()
            session.commit()
    except Exception as e:
        errors.append(f'DB: {e}')

    # 5. 日志埋点
    log_entry = f'[{now}] 清空操作 | DB记录: {cleared_items}条 | 结果: {"成功" if not errors else "部分失败: " + "; ".join(errors)}'
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(os.path.join(DATA_DIR, 'clear_history.log'), 'a', encoding='utf-8') as f:
            f.write(log_entry + '\n')
    except Exception:
        pass

    return jsonify({
        'success': not errors,
        'message': '历史记录已全部清空' if not errors else '清空完成，但部分数据清理失败: ' + '; '.join(errors)
    })
