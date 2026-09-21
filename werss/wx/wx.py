# Developer: SONGJUNSONG; Affiliation: School of Finance and Economics, Jilin Business and Technology College
import requests
import json
import re
from datetime import datetime, timezone
from werss.driver.token import get as get_val
from werss.config import cfg

DEFAULT_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"


def dateformat(timestamp):
    utc_dt = datetime.fromtimestamp(int(timestamp), timezone.utc)
    local_dt = utc_dt.astimezone()
    return local_dt.strftime("%Y-%m-%d %H:%M:%S")


def _check_wx_auth_response(data: dict, api_name: str) -> dict:
    """检测微信 API 返回体中的授权状态。
    微信 API 在 token/cookie 失效时返回 base_resp.ret = -1，但 HTTP 状态码仍是 200。
    """
    if not data or not isinstance(data, dict):
        return data
    base_resp = data.get('base_resp', {})
    ret = base_resp.get('ret', 0) if isinstance(base_resp, dict) else 0
    if ret == -1:
        print(f"[WX-API] {api_name} 返回 ret=-1，授权可能已失效！请重新扫码登录")
        data['_auth_expired'] = True
        try:
            from app.core import debug_log
            debug_log('ERROR', 'rss_auth', f'微信API {api_name} 返回 ret=-1，授权已失效', {"ret": ret})
        except Exception:
            pass
    elif ret != 0 and ret != 200:
        print(f"[WX-API] {api_name} 返回异常 ret={ret}: {base_resp.get('err_msg', '')}")
        try:
            from app.core import debug_log
            debug_log('WARNING', 'rss_auth', f'微信API {api_name} 返回异常 ret={ret}', {"ret": ret, "err_msg": base_resp.get('err_msg', '')})
        except Exception:
            pass
    return data


def search_Biz(kw: str = "", limit: int = 5, offset: int = 0):
    url = "https://mp.weixin.qq.com/cgi-bin/searchbiz"
    params = {
        "action": "search_biz",
        "begin": offset,
        "count": limit,
        "query": kw,
        "token": get_val("token"),
        "lang": "zh_CN",
        "f": "json",
        "ajax": "1"
    }
    headers = {
        "Cookie": get_val("cookie"),
        "User-Agent": get_val("user_agent") or DEFAULT_UA
    }
    data = {}
    try:
        response = requests.get(url, params=params, headers=headers)
        response.raise_for_status()
        data = response.text
        data = json.loads(data)
        data['publish_page'] = _safe_json_loads(data.get('publish_page', ''))
        data = _check_wx_auth_response(data, "search_Biz")
    except Exception as e:
        print(f"search_Biz 请求失败: {e}")
    return data


def get_Articles(faker_id: str, count: int = None, begin: int = 0):
    if count is None:
        count = cfg.get("count", 5) or 5
    params = {
        "sub": "list",
        "sub_action": "list_ex",
        "begin": begin,
        "count": count,
        "fakeid": faker_id,
        "token": get_val("token"),
        "lang": "zh_CN",
        "f": "json",
        "ajax": 1
    }
    url = "https://mp.weixin.qq.com/cgi-bin/appmsgpublish"
    headers = {
        "Cookie": get_val("cookie"),
        "User-Agent": get_val("user_agent") or DEFAULT_UA
    }
    data = {}
    try:
        response = requests.get(url, params=params, headers=headers)
        response.raise_for_status()
        data = response.text
        data = json.loads(data)
        data['publish_page'] = _safe_json_loads(data.get('publish_page', ''))
        data = _check_wx_auth_response(data, "get_Articles")
    except Exception as e:
        print(f"get_Articles 请求失败: {e}", data)
    return data


def get_id(url: str) -> str:
    pattern = r"/([^/]+)$"
    match = re.search(pattern, url)
    if match:
        return match.group(1)
    return ""


def _safe_json_loads(v):
    if isinstance(v, str):
        try:
            return json.loads(v)
        except (json.JSONDecodeError, TypeError):
            return {}
    if isinstance(v, dict):
        return v
    return {}


def get_list(faker_id: str = '', mp_id: str = '', count: int = None):
    import time
    articles = []
    if count is None:
        count = cfg.get("count", 10) or 10
    batch_size = 5
    begin = 0
    max_pages = (count + batch_size - 1) // batch_size

    for page in range(max_pages):
        try:
            data = get_Articles(faker_id, count=batch_size, begin=begin)
        except Exception as e:
            print(f"get_Articles 第{page+1}页请求失败: {e}")
            break

        publish_page = data.get('publish_page', {})
        if not isinstance(publish_page, dict):
            publish_page = {}
        publish_list = publish_page.get('publish_list', [])
        if not publish_list:
            break

        for item in publish_list:
            if not isinstance(item, dict):
                continue

            publish_info = item.get('publish_info', '')
            publish_info = _safe_json_loads(publish_info)
            if not publish_info:
                continue

            appmsgex = publish_info.get('appmsgex', [])
            if not appmsgex:
                continue

            for art in appmsgex:
                if not art or not isinstance(art, dict):
                    continue

                link = art.get('link', '')
                if not link:
                    continue

                article = {
                    'id': get_id(link),
                    'mp_id': mp_id,
                    'title': art.get('title', ''),
                    'pic_url': art.get('cover', ''),
                    'url': link,
                    'publish_time': int(art.get('update_time', 0) or 0),
                    'create_time': int(art.get('create_time', 0) or 0),
                    'description': art.get('digest', ''),
                }
                articles.append(article)
                if len(articles) >= count:
                    break
            if len(articles) >= count:
                break

        if len(publish_list) < batch_size or len(articles) >= count:
            break
        begin += batch_size
        if page < max_pages - 1:
            time.sleep(1)

    return articles
