# SONGJUNSONG (School of Finance and Economics / Jilin Business and Technology College)
import os
import re
import time
import json
import urllib.parse
import requests
from typing import Optional, Dict, Any, Callable
from threading import Lock, Timer
from PIL import Image
from io import BytesIO

from werss.print import print_warning, print_success, print_error
from werss.driver.token import get as get_token, set_token
from werss.driver.cookies import expire
from werss.driver.store import Store


class WeChatAPI:
    def __init__(self):
        self.base_url = "https://mp.weixin.qq.com"
        self.login_url = f"{self.base_url}/"
        self.home_url = f"{self.base_url}/cgi-bin/home"
        self._islogin = False
        self.is_logged_in = False
        self.fingerprint = self._generate_uuid()
        self.session = requests.Session()
        self.token = None
        self.cookies_dict = []
        self.cookies: Optional[Dict[str, str]] = {}
        self.qr_code_path = os.path.abspath("static/wx_qrcode.png")
        self.lock_file_path = "data/lock.lock"
        self._lock = Lock()
        self.login_callback: Optional[Callable] = None
        self.notice_callback = None
        os.makedirs(os.path.dirname(self.qr_code_path), exist_ok=True)

        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Referer': 'https://mp.weixin.qq.com/'
        })

    def get_qr_code(self, callback: Optional[Callable] = None, notice: Optional[Callable] = None) -> Dict[str, Any]:
        self.__init__()
        if self.check_lock():
            print_warning("微信公众平台登录脚本正在运行，请勿重复运行")
            return {
                'code': None,
                'is_exists': False,
                'msg': '微信公众平台登录脚本正在运行，请勿重复运行'
            }
        with self._lock:
            self.login_callback = callback
            self.notice_callback = notice
            try:
                response = self.session.get(self.login_url)
                response.raise_for_status()
                print_success(f"登录页响应: HTTP {response.status_code}")

                qr_info = self._extract_qr_info(response.text)

                if qr_info:
                    self._generate_qr_image(qr_info['qr_url'])
                    self.set_lock()
                    self._start_login_check(qr_info['uuid'])
                    if self.notice_callback is not None:
                        self.notice_callback()
                    return {
                        'code': f"/static/wx_qrcode.png?t={int(time.time())}",
                        'is_exists': os.path.exists(self.qr_code_path),
                        'uuid': qr_info['uuid'],
                        'msg': '请使用微信扫描二维码登录'
                    }
                else:
                    return {
                        'code': None,
                        'is_exists': False,
                        'msg': '获取二维码失败'
                    }
            except requests.exceptions.ConnectionError as e:
                msg = f'网络连接失败: {str(e)[:100]}'
                print_error(msg)
                return {'code': None, 'is_exists': False, 'msg': msg}
            except requests.exceptions.Timeout:
                msg = '请求超时'
                print_error(msg)
                return {'code': None, 'is_exists': False, 'msg': msg}
            except Exception as e:
                msg = f'获取二维码失败: {str(e)[:150]}'
                print_error(msg)
                return {'code': None, 'is_exists': False, 'msg': msg}

    def _extract_qr_info(self, html_content: str) -> Optional[Dict[str, str]]:
        try:
            qr_patterns = [
                r'(https?:\/\/mp\.weixin\.qq\.com\/cgi-bin\/loginqrcode\?action=getqrcode&param=[^"\'\&\s\<\>]+)',
                r'(https?:\/\/mp\.weixin\.qq\.com\/cgi-bin\/?\w*\?action=getqrcode[^"\'\&\s\<\>]*)',
                r'data-src=["\']((?:https?:)?\/\/mp\.weixin\.qq\.com\/cgi-bin\/loginqrcode[^"\']*)["\']',
                r'(?:"|\')(https?:\/\/mp\.weixin\.qq\.com\/cgi-bin\/loginqrcode[^"\']*)(?:"|\')',
            ]
            qr_match = None
            for pattern in qr_patterns:
                qr_match = re.search(pattern, html_content)
                if qr_match:
                    print_success(f"二维码URL匹配: pattern={pattern.partition('(')[2][:50]}...")
                    break

            if qr_match is None:
                match_count = len(re.findall(r'loginqrcode', html_content))
                print_warning(f"HTML中loginqrcode出现次数: {match_count}")
                if match_count > 0:
                    idx = html_content.find('loginqrcode')
                    surrounding = html_content[max(0,idx-100):idx+300]
                    print_warning(f"loginqrcode附近HTML: ...{surrounding}...")
                else:
                    print_warning("HTML中完全未找到loginqrcode，微信可能改版")
                    title_match = re.search(r'<title>([^<]*)</title>', html_content)
                    if title_match:
                        print_warning(f"页面标题: {title_match.group(1)}")

            uuid_patterns = [
                r'(?:"|\')uuid(?:"|\')\s*:\s*(?:"|\')([^"\']+)(?:"|\')',
                r'uuid[=:]\s*["\']?([a-f0-9]{32})["\']?',
            ]
            uuid_match = None
            for pattern in uuid_patterns:
                uuid_match = re.search(pattern, html_content)
                if uuid_match:
                    break

            if qr_match and uuid_match:
                qr_url = qr_match.group(1)
                uuid_val = uuid_match.group(1) if uuid_match else None
                print_success(f"从登录页HTML提取到二维码URL和UUID: {uuid_val}")
                return {
                    'qr_url': qr_url,
                    'uuid': uuid_val
                }

            if qr_match and not uuid_match:
                new_uuid = self._generate_uuid()
                print_warning(f"从HTML提取到二维码URL但未找到UUID，生成新UUID: {new_uuid}")
                return {
                    'qr_url': qr_match.group(1),
                    'uuid': new_uuid
                }

            print_warning("从HTML提取二维码失败，尝试API获取")
            return self._get_qr_info_api()
        except Exception as e:
            print_error(f"解析二维码信息失败: {str(e)[:100]}")
            return None

    def _get_qr_info_api(self) -> Optional[Dict[str, str]]:
        try:
            saved_headers = dict(self.session.headers)
            try:
                print_success("模拟浏览器访问登录页面...")
                login_response = self.session.get(self.login_url)
                login_response.raise_for_status()

                uuid = self.start_login()
                if not uuid:
                    uuid = self._generate_uuid()

                timestamp = int(time.time() * 1000)
                qr_api_url = f"{self.base_url}/cgi-bin/scanloginqrcode?action=getqrcode&uuid={uuid}&random={timestamp}"

                qr_headers = {
                    'Accept': 'image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8',
                    'Accept-Encoding': 'gzip, deflate, br',
                    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
                    'Cache-Control': 'no-cache',
                    'Pragma': 'no-cache',
                    'Referer': self.login_url,
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                }

                print_success(f"请求二维码: {qr_api_url}")
                print_success(f"使用UUID: {uuid}")

                response = self.session.get(qr_api_url, headers=qr_headers, allow_redirects=False, timeout=15)
                print_success(f"二维码API响应: HTTP {response.status_code}")

                if response.status_code == 200:
                    content_type = response.headers.get('Content-Type', '')
                    if 'image/' in content_type:
                        try:
                            Image.open(BytesIO(response.content))
                            with open(self.qr_code_path, 'wb') as f:
                                f.write(response.content)
                            print_success(f"二维码获取成功，已保存到: {self.qr_code_path}")
                            return {
                                'qr_url': qr_api_url,
                                'uuid': uuid
                            }
                        except Exception as e:
                            print_error(f"二维码图片数据无效: {str(e)[:100]}")
                    else:
                        body_preview = response.text[:500] if response.text else "(empty)"
                        print_error(f"响应不是图片格式: Content-Type={content_type}, body={body_preview[:300]}")
                elif response.status_code == 302:
                    redirect_url = response.headers.get('Location', '')
                    print_success(f"收到重定向: {redirect_url}")
                    if redirect_url:
                        redirect_response = self.session.get(redirect_url, timeout=15)
                        if redirect_response.status_code == 200 and 'image/' in redirect_response.headers.get('Content-Type', ''):
                            with open(self.qr_code_path, 'wb') as f:
                                f.write(redirect_response.content)
                            return {
                                'qr_url': redirect_url,
                                'uuid': uuid
                            }
                else:
                    body_preview = response.text[:500] if response.text else "(empty)"
                    print_error(f"请求失败: HTTP {response.status_code}, body={body_preview[:300]}")
            finally:
                self.session.headers.update(saved_headers)
                self.session.headers.pop('Sec-Fetch-Dest', None)
                self.session.headers.pop('Sec-Fetch-Mode', None)
                self.session.headers.pop('Sec-Fetch-Site', None)
                self.session.headers.pop('Cache-Control', None)
                self.session.headers.pop('Pragma', None)
        except Exception as e:
            print_error(f"API获取二维码失败: {str(e)[:150]}")
        return None

    def start_login(self):
        uuid = self._generate_uuid()
        token = self.session.cookies.get("token", "")
        url = f"{self.base_url}/cgi-bin/bizlogin?action=startlogin"
        fingerprint = self._generate_uuid()
        data = {
            "fingerprint": fingerprint,
            "token": token,
            "lang": "zh_CN",
            "f": "json",
            "ajax": "1",
            "redirect_url": f"/cgi-bin/settingpage?t=setting/index&amp;action=index&amp;token={token}&amp;lang=zh_CN",
            "login_type": "3",
        }
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'application/json, text/javascript, */*; q=0.01',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
            'X-Requested-With': 'XMLHttpRequest',
            'Origin': 'https://mp.weixin.qq.com',
            'Referer': self.login_url,
        }
        response = self.session.post(url, data=data, headers=headers, timeout=15)
        uuid = response.cookies.get('uuid') or response.headers.get('X-UUID')
        return uuid

    def _generate_uuid(self) -> str:
        import uuid
        return str(uuid.uuid4()).replace('-', '')

    def _generate_qr_image(self, qr_url: str):
        try:
            os.makedirs(os.path.dirname(self.qr_code_path), exist_ok=True)

            if qr_url.startswith('http'):
                response = self.session.get(qr_url, timeout=15)
                response.raise_for_status()
                with open(self.qr_code_path, 'wb') as f:
                    f.write(response.content)
            else:
                api_url = f"https://api.qrserver.com/v1/create-qr-code/?size=200x200&data={urllib.parse.quote(qr_url)}"
                response = self.session.get(api_url, timeout=15)
                response.raise_for_status()
                if not self.qr_code_path.lower().endswith('.png'):
                    self.qr_code_path = os.path.splitext(self.qr_code_path)[0] + '.png'
                with open(self.qr_code_path, 'wb') as f:
                    f.write(response.content)

            print_success(f"二维码已保存到: {self.qr_code_path}")
        except Exception as e:
            print_error(f"生成二维码图片失败: {str(e)[:100]}")

    def _start_login_check(self, uuid: str):
        def check_login():
            try:
                status = self._check_login_status(uuid)
                if status == 'success':
                    self._islogin = True
                    self._handle_login_success()
                elif status == 'waiting':
                    timer = Timer(2.0, check_login)
                    timer.daemon = True
                    timer.start()
                elif status == 'scanned':
                    if self.notice_callback:
                        self.notice_callback('已扫描，请在手机上确认登录')
                    timer = Timer(2.0, check_login)
                    timer.daemon = True
                    timer.start()
                elif status == 'expired':
                    if self.notice_callback:
                        self.notice_callback('二维码已过期，请重新获取')
                    return
                elif status == 'exists':
                    return
                else:
                    timer = Timer(2.0, check_login)
                    timer.daemon = True
                    timer.start()
            except Exception as e:
                print_error(f"检查登录状态失败: {str(e)[:100]}")
                if self.notice_callback:
                    self.notice_callback('检查登录状态失败,请重试')
            finally:
                self.release_lock()

        timer = Timer(2.0, check_login)
        timer.daemon = True
        timer.start()

    def _check_login_status(self, uuid: str) -> str:
        try:
            if not os.path.exists(self.qr_code_path):
                return "exists"
            check_url = f"{self.base_url}/cgi-bin/scanloginqrcode"
            self.fingerprint = self.cookies.get("fingerprint") or self._generate_uuid()
            params = {
                "action": "ask",
                "fingerprint": self.fingerprint,
                "lang": "zh_CN",
                "f": "json",
                "ajax": 1
            }
            response = self.session.get(check_url, params=params, timeout=10)
            response.raise_for_status()
            if response.headers.get('content-type', '').startswith('application/json'):
                data = response.json()
                status = data.get('status', 0)
                if "invalid session" in str(data):
                    return 'invalid session'
                if status in (1, 3):
                    with self._lock:
                        self.cookies = requests.utils.dict_from_cookiejar(self.session.cookies) if self.session.cookies else {}
                    return 'success'
                elif status in (2, 4):
                    return 'scanned'
                else:
                    return 'waiting'
            return 'waiting'
        except Exception as e:
            print_error(f"检查登录状态失败: {str(e)[:100]}")
            return 'error'

    def _handle_login_success(self):
        try:
            self._islogin = True
            self.is_logged_in = True
            if not self.token:
                self._extract_login_info()
            if os.path.exists(self.qr_code_path):
                os.remove(self.qr_code_path)
            if self._get_account_info() is not None:
                print_success("登录成功！")
                return True
        except Exception as e:
            print_error(f"处理登录失败: {str(e)[:100]}")
        return False

    def _extract_login_info(self):
        try:
            login_data = {
                "userlang": "zh_CN",
                "redirect_url": "",
                "cookie_forbidden": "0",
                "cookie_cleaned": "0",
                "plugin_used": "0",
                "login_type": "3",
                "fingerprint": self.fingerprint,
                "token": "",
                "lang": "zh_CN",
                "f": "json",
                "ajax": "1"
            }
            response = self.session.post(
                "https://mp.weixin.qq.com/cgi-bin/bizlogin?action=login",
                data=login_data, timeout=15
            )
            response.raise_for_status()
            self.cookies = requests.utils.dict_from_cookiejar(self.session.cookies) if self.session.cookies else {}
            token_match = re.search(r'token=([^&\s"\']+)', response.text)
            if token_match:
                self.token = token_match.group(1)
        except Exception as e:
            print_error(f"提取登录信息失败: {str(e)[:100]}")

    def _convert_cookies_to_list(self) -> list:
        cookies_list = []
        for cookie in self.session.cookies:
            cookie_item = {
                'name': cookie.name,
                'value': cookie.value,
                'domain': cookie.domain if cookie.domain else '.weixin.qq.com',
                'path': cookie.path if cookie.path else '/',
            }
            if cookie.expires:
                cookie_item['expires'] = cookie.expires
            cookies_list.append(cookie_item)
        return cookies_list

    def _format_cookies_string(self) -> str:
        return '; '.join([f"{k}={v}" for k, v in self.cookies.items()])

    def _cookie_string_to_dict(self, cookie_string: str) -> Dict[str, str]:
        cookie_dict = {}
        if not cookie_string or not isinstance(cookie_string, str):
            return cookie_dict
        for pair in cookie_string.split(';'):
            pair = pair.strip()
            if not pair:
                continue
            if '=' in pair:
                key, value = pair.split('=', 1)
                cookie_dict[key.strip()] = value.strip()
        return cookie_dict

    def _get_account_info(self) -> Optional[Dict[str, Any]]:
        try:
            response = self.session.get(self.home_url, timeout=15)
            response.raise_for_status()
            account_list = self._get_account_list()
            if account_list is None:
                print_error("获取账号列表失败")
                return None
            biz_list = account_list.get('biz_list', {}).get('list', [])
            first_biz_item = biz_list[0] if len(biz_list) > 0 else {}
            account_info = {
                'wx_app_name': first_biz_item.get('username', ''),
                'wx_logo': first_biz_item.get('headimgurl', ''),
                'wx_read_yesterday': 0,
                'wx_share_yesterday': 0,
                'wx_watch_yesterday': 0,
                'wx_yuan_count': 0,
                'wx_user_count': 0
            }
            cookies_list = self._convert_cookies_to_list()
            login_data = {
                'cookies': self.cookies,
                'cookies_str': self._format_cookies_string(),
                'token': self.token,
                'fingerprint': self.fingerprint,
                'expiry': expire(cookies_list if cookies_list else self.cookies_dict)
            }
            Store.save(cookies_list)
            set_token(login_data, account_info)
            if self.login_callback:
                self.login_callback(login_data, account_info)
            return account_info
        except Exception as e:
            print_error(f"获取账号信息失败: {str(e)[:100]}")
            return None

    def _get_account_list(self) -> Optional[Dict[str, Any]]:
        try:
            if not self.token:
                print_error("未获取到token，无法获取账号列表")
                return None
            url = f"{self.base_url}/cgi-bin/switchacct"
            params = {
                'action': 'get_acct_list',
                'fingerprint': self.fingerprint,
                'token': self.token,
                'lang': 'zh_CN',
                'f': 'json',
                'ajax': '1'
            }
            headers = {
                'accept': '*/*',
                'accept-language': 'zh-CN,zh;q=0.9,en;q=0.8',
                'x-requested-with': 'XMLHttpRequest',
                'Referer': f"{self.base_url}/cgi-bin/home?t=home/index&lang=zh_CN&token={self.token}"
            }
            response = self.session.get(url, params=params, headers=headers, timeout=15)
            response.raise_for_status()
            result = response.json()
            if 'base_resp' in result and result['base_resp']['ret'] == 0:
                return result
            return None
        except Exception as e:
            print_error(f"获取账号列表失败: {str(e)[:100]}")
            return None

    def login_with_token(self, token: str = "", cookies: Any = None) -> bool:
        try:
            token = token or get_token("token")
            cookies = cookies or self._cookie_string_to_dict(get_token("cookie"))
            self.token = token
            if cookies:
                for name, value in cookies.items():
                    self.session.cookies.set(name, value, domain='.weixin.qq.com')
                self.cookies = cookies

            if not token or token == "":
                print_warning("Token为空，请先登录")
                return False

            response = self.session.get(f"{self.home_url}?token={token}", timeout=15)
            response.raise_for_status()

            if response.status_code != 200:
                print_warning(f"登录验证失败，HTTP状态码: {response.status_code}")
                return False

            if 'home' not in response.url:
                print_warning(f"Token登录失败，重定向到: {response.url}")
                return False

            content = response.text
            login_indicators = ['wx_app_name', 'user_name', 'nick_name', 'head_img', 'account_list', 'data_ticket']
            fail_indicators = ['请重新登录', '登录超时', 'session过期', 'invalid session', '请扫码登录', 'loginpage']

            for indicator in fail_indicators:
                if indicator in content:
                    print_warning("检测到登录失败标识，Token已失效")
                    return False

            has_login = any(indicator in content for indicator in login_indicators)
            if not has_login:
                print_warning("未检测到登录成功标识，Token可能已失效")
                return False

            self.is_logged_in = True
            print_success("Token登录成功")
            return self._handle_login_success()
        except Exception as e:
            print_error(f"Token登录失败: {str(e)[:100]}")
            return False

    def check_lock(self, timeout: int = 300) -> bool:
        return os.path.exists(self.lock_file_path) or os.path.exists(self.qr_code_path)

    def set_lock(self):
        os.makedirs(os.path.dirname(self.lock_file_path), exist_ok=True)
        current_pid = os.getpid()
        with open(self.lock_file_path, 'w') as f:
            f.write(f"{current_pid}|{time.time()}")

    def release_lock(self):
        try:
            if os.path.exists(self.lock_file_path):
                with open(self.lock_file_path, 'r') as f:
                    content = f.read().strip()
                parts = content.split('|')
                if parts and int(parts[0]) == os.getpid():
                    os.remove(self.lock_file_path)
            return True
        except Exception:
            return False

    def HasLogin(self):
        if not self._islogin:
            return False
        if os.path.exists(self.qr_code_path):
            return False
        if not self.token:
            return False
        return True

    def HasCode(self):
        return os.path.exists(self.qr_code_path)


WeChat_api = WeChatAPI()
WX_API = WeChat_api


def get_qr_code(callback=None, notice=None):
    return WeChat_api.get_qr_code(callback, notice)


def login_with_token(token: str = "", cookies=None, login_callback=None):
    WeChat_api.login_callback = login_callback
    return WeChat_api.login_with_token(token, cookies)
