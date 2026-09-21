# © SONGJUNSONG · Jilin Business and Technology College · School of Finance and Economics
"""launcher.py — 桌面启动器（原生窗口 + 服务托管）。

两种运行模式：
  * 无参数        → GUI 模式：起一个原生窗口（pywebview / WebView2），
                    并在子进程里托管 Flask 服务，窗口关闭时结束服务。
  * 带 --serve    → 服务模式：直接把 Flask 跑起来（被 GUI 模式以子进程方式拉起）。

之所以把服务放在子进程，是因为网页上的「重启应用」会调用 os._exit(0)；
跑在子进程里只会重启服务，不会把窗口一起带走。
"""
import os
import sys
import time
import socket
import threading
import subprocess

# 打包成窗口程序（--noconsole）后 stdout/stderr 是 None，
# loguru 挂 sink、print 都会炸，这里先兜住
for _name in ("stdout", "stderr"):
    if getattr(sys, _name, None) is None:
        try:
            setattr(sys, _name, open(os.devnull, "w", encoding="utf-8"))
        except Exception:
            pass

# 项目根目录（冻结后为解包目录）加入 sys.path
_BASE = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
if _BASE not in sys.path:
    sys.path.insert(0, _BASE)

from paths import bundle_dir, user_dir, is_frozen, ensure_user_dir

APP_NAME = "编舟文心"
PORT = int(os.environ.get("PORT", "10015"))
URL = f"http://127.0.0.1:{PORT}"
_LOG_LOCK = threading.Lock()


def log(msg: str):
    """写启动器日志到 <user_dir>/data/launcher.log，避免 GUI 模式下无处输出"""
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    with _LOG_LOCK:
        try:
            d = os.path.join(ensure_user_dir(), "data")
            os.makedirs(d, exist_ok=True)
            with open(os.path.join(d, "launcher.log"), "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception:
            pass


def lan_ip() -> str:
    """尽力取本机局域网 IP，用于把地址告诉部员"""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("223.5.5.5", 80))
        return s.getsockname()[0]
    except Exception:
        return ""
    finally:
        s.close()


def ensure_user_files():
    """首次运行时，把随程序分发的配置模板复制到可写目录"""
    u = ensure_user_dir()
    os.makedirs(os.path.join(u, "data"), exist_ok=True)
    for name in ("config.yaml", "notify_config.json", "webdav_config.json"):
        dst = os.path.join(u, name)
        if os.path.exists(dst):
            continue
        for src_name in (name, name.replace(".json", ".example.json")):
            src = os.path.join(bundle_dir(), src_name)
            if os.path.exists(src):
                with open(src, "rb") as fi, open(dst, "wb") as fo:
                    fo.write(fi.read())
                log(f"已生成 {name}")
                break


def port_busy() -> bool:
    s = socket.socket()
    try:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", PORT)) == 0
    finally:
        s.close()


def wait_healthy(timeout=90.0) -> bool:
    """轮询 /api/health，等服务就绪（首次启动要跑数据库初始化，可能较慢）"""
    import urllib.request
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"{URL}/api/health", timeout=3) as r:
                if r.status == 200:
                    return True
        except Exception:
            time.sleep(0.6)
    return False


# ====================== 服务模式 ======================

def run_server():
    """在子进程里跑 Flask 服务"""
    os.chdir(user_dir())          # 让 data/、wx.lic 等相对路径落在可写目录
    from app.core import create_app, __version__
    from werss.logger import init_logging

    init_logging()
    print(f"{APP_NAME} v{__version__} 服务启动中 ...")

    # 复用 run.py 的启动流程（数据库、定时任务、微信授权）
    try:
        import init_sys
        init_sys.init()
    except Exception as e:
        print(f"Werss 初始化失败: {e}")
    try:
        from jobs.mps import start_job
        start_job()
    except Exception as e:
        print(f"定时任务启动失败: {e}")
    try:
        from werss.driver.auth import start_auth_service
        start_auth_service()
    except Exception as e:
        print(f"授权服务启动失败: {e}")

    app = create_app()
    from werss.config import cfg
    _secret = cfg.get('secret', '') or __import__('secrets').token_urlsafe(32)
    app.secret_key = _secret
    app.run(host="0.0.0.0", port=PORT, threaded=True, debug=False, use_reloader=False)


# ====================== GUI 模式 ======================

SPLASH = """<!DOCTYPE html><html><head><meta charset="utf-8"><style>
body{margin:0;height:100vh;display:flex;flex-direction:column;align-items:center;
justify-content:center;font-family:'Microsoft YaHei',sans-serif;background:#f3f3f3;color:#333}
h1{font-size:20px;font-weight:600;margin:0 0 10px}
p{font-size:13px;color:#666;margin:6px 0}
.dot{width:26px;height:26px;border:3px solid #d0d0d0;border-top-color:#2B6DE5;border-radius:50%;
animation:spin .8s linear infinite;margin-bottom:18px}
@keyframes spin{to{transform:rotate(360deg)}}
</style></head><body>
<div class="dot"></div><h1>编舟文心</h1>
<p id="s">正在启动服务，请稍候...</p>
<p style="font-size:11px;color:#999">首次启动需要初始化数据库，可能要几十秒</p>
</body></html>"""


def gui():
    ensure_user_files()

    if port_busy():
        log(f"端口 {PORT} 已被占用，直接连接现有服务")
        _show_window()
        return

    child = _spawn_server()
    if child is None:
        _error_box(f"无法启动服务进程。\n\n请查看日志：\n{os.path.join(user_dir(), 'data', 'launcher.log')}")
        return

    _show_window(child)


def _spawn_server():
    """拉起服务子进程；冻结后是自己带 --serve 重跑，否则用当前解释器跑 run.py"""
    try:
        if is_frozen():
            cmd = [sys.executable, "--serve"]
        else:
            cmd = [sys.executable, os.path.join(_BASE, "launcher.py"), "--serve"]
        log(f"启动服务进程: {cmd}")
        flags = 0x08000000 if os.name == "nt" else 0  # CREATE_NO_WINDOW：不弹黑框
        return subprocess.Popen(cmd, cwd=user_dir(), creationflags=flags)
    except Exception as e:
        log(f"启动服务进程失败: {e}")
        return None


def _show_window(child=None):
    import webview

    ip = lan_ip()
    title = f"{APP_NAME}  ·  本机 {URL}"
    if ip:
        title += f"  /  局域网 http://{ip}:{PORT}"

    window = webview.create_window(title, html=SPLASH, width=1280, height=820,
                                  min_size=(900, 600))

    state = {"closed": False}
    try:
        window.events.closed += lambda: state.update(closed=True)
    except Exception:
        pass

    def _boot():
        if child is not None and not wait_healthy():
            log("服务未在超时时间内就绪")
            try:
                window.load_html(
                    "<body style='font-family:Microsoft YaHei;padding:40px'>"
                    "<h2>服务启动超时</h2><p>请查看日志：</p>"
                    f"<code>{os.path.join(user_dir(), 'data', 'launcher.log')}</code>"
                    "<p>以及 data/logs/ 下的日志文件。</p></body>")
            except Exception:
                pass
            return
        try:
            window.load_url(URL)
            log(f"窗口已加载 {URL}")
        except Exception as e:
            log(f"加载页面失败: {e}")

    threading.Thread(target=_boot, daemon=True).start()

    if child is not None:
        def _supervise():
            """服务退出后自动重启（网页上的「重启应用」靠这里生效）"""
            nonlocal child
            while not state["closed"]:
                code = child.wait()
                log(f"服务进程退出，代码 {code}")
                if state["closed"]:
                    return
                time.sleep(5)
                if state["closed"] or port_busy():
                    continue
                child = _spawn_server()
                if child is None:
                    return
                wait_healthy(120)
                log("服务已重新拉起")
        threading.Thread(target=_supervise, daemon=True).start()

    try:
        webview.start()
    finally:
        if child is not None and child.poll() is None:
            log("窗口关闭，结束服务进程")
            child.terminate()
            try:
                child.wait(timeout=10)
            except Exception:
                child.kill()


def _error_box(msg: str):
    """弹一个原生错误提示（GUI 模式下没有控制台）"""
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, msg, APP_NAME, 0x10)
    except Exception:
        log("错误: " + msg.replace("\n", " "))


if __name__ == "__main__":
    if "--serve" in sys.argv:
        run_server()
    else:
        try:
            gui()
        except Exception:
            import traceback
            log("启动器异常:\n" + traceback.format_exc())
            _error_box("启动失败：\n\n" + traceback.format_exc()[-800:])
            sys.exit(1)
