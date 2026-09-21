# SONGJUNSONG (School of Finance and Economics / Jilin Business and Technology College)
"""run.py — 编舟文心新启动入口（从 app.py 分割而来）
原 app.py 保留为备份，验证功能正常后删除。
"""
import os
import sys
import threading
import secrets as _secrets

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import create_app, __version__


def init_werss():
    """初始化 werss（DB/init_sys）"""
    try:
        import init_sys
        init_sys.init()
        _ensure_db_indexes()
    except Exception as e:
        print(f"Werss 初始化失败: {e}")


def _ensure_db_indexes():
    """确保已有数据库上存在关键索引（create_all 不会为已有表添加新索引）"""
    try:
        from werss.db import DB
        from sqlalchemy import text
        statements = [
            "CREATE INDEX IF NOT EXISTS ix_articles_created_at ON articles (created_at)",
            "CREATE INDEX IF NOT EXISTS ix_articles_mp_id_publish_time ON articles (mp_id, publish_time)",
            "CREATE INDEX IF NOT EXISTS ix_articles_status_publish_time ON articles (status, publish_time)",
        ]
        with DB.session_scope() as session:
            for stmt in statements:
                try:
                    session.execute(text(stmt))
                except Exception as e:
                    print(f"[DB] 创建索引失败（可能已存在）: {e}")
        print("[DB] 索引检查完成")
    except Exception as e:
        print(f"[DB] 索引初始化异常: {e}")


def start_auth():
    """启动微信扫码授权"""
    try:
        qr_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static', 'wx_qrcode.png')
        if os.path.exists(qr_path):
            try:
                os.remove(qr_path)
                print("已清理残留二维码文件")
            except Exception:
                pass
    except Exception:
        pass
    try:
        from werss.driver.auth import start_auth_service
        start_auth_service()
        from werss.driver.wx_api import WeChat_api
        if not WeChat_api.HasLogin():
            def _notify_auth_expired():
                try:
                    from app.routes_notify import send_notification
                    send_notification("RSS授权已失效，请尽快重新扫码登录！", notify_type='rss_expiry')
                except Exception:
                    pass
            threading.Thread(target=_notify_auth_expired, daemon=True).start()
    except Exception as e:
        print(f"授权服务启动失败: {e}")


def start_scheduler():
    """启动定时任务"""
    try:
        from jobs.mps import start_job
        start_job()
    except Exception as e:
        print(f"定时任务启动失败: {e}")


def verify_system_time():
    """启动时校验系统时间偏差"""
    from app.core import get_bjt_now, format_bjt_time
    import time as _time
    import requests
    sys_now = _time.time()
    bjt_local = get_bjt_now()
    print(f"[TIME-CHECK] 本地北京时间: {format_bjt_time(bjt_local)}")

    net_ts = None
    sources = [
        ('http://api.m.taobao.com/rest/api3.do?api=mtop.common.getTimestamp', 'taobao'),
        ('http://www.baidu.com', 'baidu'),
    ]
    for url, name in sources:
        try:
            resp = requests.head(url, timeout=5)
            date_str = resp.headers.get('Date', '')
            if date_str:
                from email.utils import parsedate_to_datetime
                dt_obj = parsedate_to_datetime(date_str)
                net_ts = dt_obj.timestamp()
                print(f"[TIME-CHECK] 网络标准时间 ({name}): {dt_obj.strftime('%Y-%m-%d %H:%M:%S')}")
                break
        except Exception:
            continue

    if net_ts is None:
        print("[TIME-CHECK] 无法获取网络标准时间，跳过偏差检查")
        return

    diff_seconds = abs(sys_now - net_ts)
    diff_minutes = diff_seconds / 60.0
    print(f"[TIME-CHECK] 时间偏差: {diff_seconds:.1f} 秒 ({diff_minutes:.1f} 分钟)")

    if diff_seconds > 300:
        msg = (f"系统时间严重偏差！\n"
               f"本地时间: {format_bjt_time(bjt_local)}\n"
               f"标准时间偏移: {diff_minutes:.1f} 分钟\n"
               f"请检查容器时区配置和NTP服务")
        print(f"[TIME-CHECK] {msg}")
    else:
        print(f"[TIME-CHECK] 时间偏差在允许范围内")


if __name__ == '__main__':
    from werss.logger import init_logging
    init_logging()

    print("=" * 50)
    print(f"编舟文心 v{__version__}（模块化版）")
    print("=" * 50)

    from werss.config import cfg
    _secret = cfg.get('secret', '')
    if not _secret or _secret == 'change-me-to-a-random-string':
        _secret = _secrets.token_urlsafe(32)
        print("[SECURITY] 检测到 config.yaml 使用默认 secret，已生成临时随机 secret")
    app = create_app()
    app.secret_key = _secret

    # 版本一致性校验
    try:
        from app.routes_system import log_version_change, verify_version_consistency
        log_version_change()
        verify_version_consistency()
    except Exception as e:
        print(f"[WARN] 版本校验失败（非致命）: {e}")

    verify_system_time()
    init_werss()
    start_auth()
    start_scheduler()

    _port = int(os.environ.get('PORT', cfg.get('server.port', 10015) or 10015))
    print(f'服务启动于 http://0.0.0.0:{_port}')
    app.run(host='0.0.0.0', port=_port, threaded=True)
