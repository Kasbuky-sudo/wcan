# © SONGJUNSONG · Jilin Business and Technology College · School of Finance and Economics
"""paths.py — 运行时路径解析。

区分两类目录：

- **bundle_dir()**：只读程序资源。源码运行时就是项目根目录；用 PyInstaller
  冻结成 exe 后是解包目录（sys._MEIPASS），里面放着 templates/、static/、
  locales/ 等随程序分发的文件。
- **user_dir()**：可写数据。config.yaml、data/、文章/、日志、几个 json 配置
  都放这里。源码运行时就是项目根目录（与旧行为完全一致）；冻结后是 exe
  所在目录，保证用户数据落在 exe 旁边而不是临时解包目录里。

可用环境变量 WCAN_HOME 覆盖 user_dir()。
"""
import os
import sys


def is_frozen():
    """是否运行在 PyInstaller 冻结的 exe 中"""
    return bool(getattr(sys, 'frozen', False))


def bundle_dir():
    """只读资源目录"""
    if is_frozen():
        return getattr(sys, '_MEIPASS', os.path.dirname(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def user_dir():
    """可写数据目录"""
    env = os.environ.get('WCAN_HOME')
    if env:
        return os.path.abspath(env)
    if is_frozen():
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def ensure_user_dir():
    """确保可写目录存在，返回它"""
    d = user_dir()
    os.makedirs(d, exist_ok=True)
    return d
