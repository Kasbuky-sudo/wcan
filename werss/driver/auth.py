# Developer: SONGJUNSONG; Affiliation: School of Finance and Economics, Jilin Business and Technology College
import time
from werss.print import print_warning, print_success
from werss.driver.wx_api import login_with_token, WeChat_api
from werss.driver.token import get_token_data


def start_auth_service():
    try:
        # 优先信任本地缓存的 token（如果未过期），跳过远程验证
        # 远程验证本身可能因网络抖动或服务器敏感导致 token 失效
        token_data = get_token_data()
        if token_data and token_data.get("token"):
            expiry = token_data.get("expiry", {}) or {}
            expiry_ts = expiry.get("expiry_timestamp", 0)

            if expiry_ts and expiry_ts > time.time():
                token = token_data.get("token", "")
                cookies_str = token_data.get("cookie", "")
                fingerprint = token_data.get("fingerprint", "")

                WeChat_api.token = token
                if fingerprint:
                    WeChat_api.fingerprint = fingerprint
                if cookies_str:
                    cookies = WeChat_api._cookie_string_to_dict(cookies_str)
                    for name, value in cookies.items():
                        WeChat_api.session.cookies.set(name, value, domain='.weixin.qq.com')
                    WeChat_api.cookies = cookies
                WeChat_api._islogin = True
                WeChat_api.is_logged_in = True

                expiry_time = expiry.get("expiry_time", "未知")
                remaining_min = int(expiry.get("remaining_seconds", 0)) // 60
                print_success(f"信任本地 Token（到期: {expiry_time}，剩余约 {remaining_min} 分钟），跳过远程验证")
                return

        # 本地 token 不存在或已过期，走远程验证
        login_success = login_with_token()
        if login_success:
            print_success("微信授权自动登录成功")
        else:
            print_warning("未检测到有效Token，请通过扫码登录")
    except Exception as e:
        print_warning(f"自动登录失败: {e}，请通过扫码登录")
