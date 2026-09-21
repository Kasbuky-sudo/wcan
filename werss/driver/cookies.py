# Crafted by SONGJUNSONG at the School of Finance and Economics, Jilin Business and Technology College
import time
def expire(cookies):
    if not isinstance(cookies, list) and not isinstance(cookies, dict):
        raise TypeError("cookies参数必须是列表类型")

    cookie_expiry = None
    priority_cookies = ['slave_sid', 'slave_user', 'bizuin', 'uin', 'pass_ticket']

    for priority_name in priority_cookies:
        for cookie in cookies:
            if not isinstance(cookie, dict):
                continue
            if cookie.get('name') == priority_name:
                expiry = _extract_expiry_from_cookie(cookie)
                if expiry:
                    return expiry

    for cookie in cookies:
        if not isinstance(cookie, dict):
            continue
        expiry = _extract_expiry_from_cookie(cookie)
        if expiry:
            return expiry

    from werss.print import print_warning
    # 读取配置的 token 过期时间（分钟），默认 72 小时（4320 分钟）
    # 与 config.yaml 的 token_expire_minutes 保持一致
    try:
        from werss.config import cfg
        default_minutes = int(cfg.get("token_expire_minutes", 4320))
    except Exception:
        default_minutes = 4320
    default_expiry = time.time() + default_minutes * 60
    print_warning(f"未能从 cookies 中提取有效过期时间，使用默认 {default_minutes} 分钟有效期")
    return {
        'expiry_timestamp': default_expiry,
        'remaining_seconds': default_minutes * 60,
        'expiry_time': time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(default_expiry))
    }


def _extract_expiry_from_cookie(cookie: dict):
    expiry_fields = ['expires', 'expiry', 'expire']
    expiry_time = None

    for field in expiry_fields:
        if field in cookie:
            try:
                val = cookie[field]
                if isinstance(val, (int, float)):
                    expiry_time = float(val)
                elif isinstance(val, str):
                    if val.isdigit():
                        expiry_time = float(val)
                    else:
                        import datetime
                        try:
                            for fmt in ['%Y-%m-%d %H:%M:%S', '%a, %d-%b-%Y %H:%M:%S %Z', '%a, %d %b %Y %H:%M:%S %Z']:
                                try:
                                    dt = datetime.datetime.strptime(val, fmt)
                                    expiry_time = dt.timestamp()
                                    break
                                except ValueError:
                                    continue
                        except Exception:
                            pass
                break
            except (ValueError, TypeError) as e:
                continue

    if expiry_time:
        remaining_time = expiry_time - time.time()
        if remaining_time > 0:
            return {
                'expiry_timestamp': expiry_time,
                'remaining_seconds': int(remaining_time),
                'expiry_time': time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(expiry_time))
            }

    return None
