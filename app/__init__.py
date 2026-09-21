# Crafted by SONGJUNSONG at the School of Finance and Economics, Jilin Business and Technology College
"""编舟文心 — Flask 应用包（从 app.py 分割而来）"""
from .core import (
    app, crawler, create_app, __version__,
    # 状态对象
    sync_status, crawl_status, _status_lock, DATA_DIR,
    # 工具函数
    debug_log, get_bjt_now, format_bjt_time, add_sync_log, update_sync_status,
    reset_sync_status, _atomic_write, _load_json, _safe_thread, _safe_request,
    rate_limit, _encrypt_secret, _decrypt_secret, _verify_admin_password,
    _issue_auth_token, _verify_auth_token, _extract_auth_token, require_auth,
    # 常量
    MAX_CRAWL_HISTORY, MAX_CRAWL_LOGS,
)

# 从 routes_crawl 重新导出（jobs/mps.py 等通过 from app import 使用）
from .routes_crawl import add_to_crawl_history, add_log, check_token_expiry_and_notify, get_token_expiry

# 从 routes_notify 重新导出
from .routes_notify import (
    send_notification, send_daily_report, is_failure_notified, mark_failure_notified,
    load_notify_config, send_webhook_notification, send_serverchan_notification,
    send_email_notification, _get_enabled_webdav_items, load_webdav_config, upload_to_webdav,
)

# 从 routes_misc 重新导出
from .routes_misc import find_file_in_dir

__all__ = [
    'app', 'crawler', 'create_app', '__version__',
    'sync_status', 'crawl_status', '_status_lock', 'DATA_DIR',
    'debug_log', 'get_bjt_now', 'format_bjt_time', 'add_sync_log', 'update_sync_status',
    'reset_sync_status', 'add_to_crawl_history', 'add_log',
    'check_token_expiry_and_notify', 'get_token_expiry',
    'send_notification', 'send_daily_report', 'is_failure_notified', 'mark_failure_notified',
    'load_notify_config', 'send_webhook_notification', 'send_serverchan_notification',
    'send_email_notification', '_get_enabled_webdav_items', 'load_webdav_config', 'upload_to_webdav',
    'find_file_in_dir',
    '_atomic_write', '_load_json', '_safe_thread', '_safe_request', 'rate_limit',
    '_encrypt_secret', '_decrypt_secret', '_verify_admin_password',
    '_issue_auth_token', '_verify_auth_token', '_extract_auth_token', 'require_auth',
    'MAX_CRAWL_HISTORY', 'MAX_CRAWL_LOGS',
]
