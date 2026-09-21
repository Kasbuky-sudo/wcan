# © SONGJUNSONG · Jilin Business and Technology College · School of Finance and Economics
from werss.config import Config
import os
import json
from werss.print import print_success, print_warning

lic_path = "./data/wx.lic"
os.makedirs(os.path.dirname(lic_path), exist_ok=True)
if not os.path.exists(lic_path):
    with open(lic_path, "w") as f:
        f.write("{}")
wx_cfg = Config(lic_path)


def set_token(data, ext_data=None):
    if data.get("token", "") == "":
        return

    token_data = {
        "token": data.get("token", ""),
        "cookie": data.get("cookies_str", ""),
        "fingerprint": data.get("fingerprint", ""),
        "expiry": data.get("expiry", {}),
    }
    if ext_data is not None:
        token_data["ext_data"] = ext_data

    wx_cfg.set("token_data", token_data)
    wx_cfg.save()
    wx_cfg.reload()

    expiry_info = data.get("expiry", {})
    print_success(f"Token: {data.get('token')}")
    if expiry_info:
        print_success(f"到期时间: {expiry_info.get('expiry_time', '未知')}")


def get(key: str, default: str = "") -> str:
    token_data = wx_cfg.get("token_data", None)
    if token_data is None:
        return default
    value = token_data.get(key, default)
    if isinstance(value, dict):
        return json.dumps(value)
    if value == "None":
        return ''
    return str(value) if value is not None else default


def get_token_data():
    return wx_cfg.get("token_data", None)


def get_token_expiry():
    token_data = wx_cfg.get("token_data", None)
    if not token_data:
        return None
    return token_data.get("expiry", None)
