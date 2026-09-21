import os
import sys
import asyncio

if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from werss.config import cfg

if bool(cfg.get("server.auth_web", False)) == True:
    from werss.driver.wx import WX_API
    from werss.driver.wx import Wx as WX_InterFace
else:
    from werss.driver.wx_api import WeChat_api as WX_API
    from werss.driver.wx_api import WeChatAPI as WX_InterFace
