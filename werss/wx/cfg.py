from werss.driver.token import wx_cfg


def set_config(key: str, value: str):
    wx_cfg.set(key, value)


def save_config():
    wx_cfg.save_config()
