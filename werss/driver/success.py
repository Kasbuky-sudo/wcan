import threading
from werss.print import print_warning, print_success

WX_LOGIN_ED = False
WX_LOGIN_INFO = None
login_lock = threading.Lock()


def setStatus(status: bool):
    global WX_LOGIN_ED
    with login_lock:
        WX_LOGIN_ED = status


def getStatus() -> bool:
    return WX_LOGIN_ED


def getInfo():
    return WX_LOGIN_INFO


def setInfo(info):
    global WX_LOGIN_INFO
    with login_lock:
        WX_LOGIN_INFO = info


class Success:
    @staticmethod
    def login_success(cookie, info):
        setStatus(True)
        setInfo(info)
        print_success("登录状态已更新")
