# Maintained by SONGJUNSONG — Jilin Business and Technology College, School of Finance and Economics
"""文件替换、轮询聚合、扫雷、文章生成路由"""
from flask import Blueprint, request, jsonify
from .core import *
from .core import _safe_thread, _load_json, _atomic_write, _status_lock, _safe_request

bp = Blueprint('misc', __name__)

# 全局变量
replace_status = {
    'processing': False,
    'total': 0,
    'processed': 0,
    'replaced': 0,
    'failed': 0,
    'logs': []
}
_MS_RECORD_FILE = os.path.join(DATA_DIR, 'data', 'minesweeper_record.json')


def add_replace_log(message):
    timestamp = format_bjt_time()[11:]
    log_entry = f"[{timestamp}] {message}"
    with _status_lock:
        replace_status['logs'].append(log_entry)
        if len(replace_status['logs']) > MAX_REPLACE_LOGS:
            replace_status['logs'] = replace_status['logs'][-MAX_REPLACE_LOGS:]
    print(log_entry)


def find_file_in_dir(directory, target_name):
    if not os.path.exists(directory):
        return None
    for root, dirs, files in os.walk(directory):
        for f in files:
            if f == target_name:
                return os.path.join(root, f)
    return None


@bp.route('/api/replace/upload', methods=['POST'])
def replace_files():
    if 'files' not in request.files:
        return jsonify({'success': False, 'error': '请选择文件'})
    files = request.files.getlist('files')
    if not files or all(f.filename == '' for f in files):
        return jsonify({'success': False, 'error': '没有有效文件'})
    replace_status['processing'] = True
    with _status_lock:
        replace_status['total'] = len(files)
        replace_status['processed'] = 0
        replace_status['replaced'] = 0
        replace_status['failed'] = 0
        replace_status['logs'] = []
    base_path = os.path.abspath(os.path.join(DATA_DIR, '文章'))
    from .routes_notify import load_webdav_config, upload_to_webdav
    webdav_config = load_webdav_config()
    add_replace_log(f'开始处理 {len(files)} 个文件...')
    for uploaded in files:
        if not uploaded.filename:
            continue
        fname = uploaded.filename
        replace_status['processed'] += 1
        add_replace_log(f'正在匹配: {fname}')
        original_path = find_file_in_dir(base_path, fname)
        if not original_path:
            add_replace_log(f'未找到原文件，跳过: {fname}')
            replace_status['failed'] += 1
            continue
        try:
            os.remove(original_path)
            add_replace_log(f'已删除原文件: {os.path.relpath(original_path, DATA_DIR)}')
            save_dir = os.path.dirname(original_path)
            name_no_ext, ext = os.path.splitext(fname)
            if '【改】' not in name_no_ext:
                new_fname = f"【改】{fname}"
            else:
                new_fname = fname
            new_path = os.path.join(save_dir, new_fname)
            uploaded.save(new_path)
            add_replace_log(f'已写入新文件: {os.path.relpath(new_path, DATA_DIR)}')
            from .routes_crawl import add_to_crawl_history
            add_to_crawl_history({
                'title': name_no_ext,
                'link': '',
                'processed_at': format_bjt_time(),
                'feed_name': '文章替换',
                'success': True,
                'is_repost': False,
                'retry_exhausted': False,
                'error': None,
                'modified': True
            })
            if webdav_config.get('enabled'):
                result = upload_to_webdav(new_path, fname)
                if result['success']:
                    add_replace_log(f'WebDAV 上传成功: {fname}')
                else:
                    add_replace_log(f'WebDAV 上传失败: {result.get("error", "未知")}')
            replace_status['replaced'] += 1
        except Exception as e:
            add_replace_log(f'处理失败: {str(e)[:100]}')
            replace_status['failed'] += 1
    replace_status['processing'] = False
    add_replace_log(f'处理完毕: {replace_status["replaced"]} 成功, {replace_status["failed"]} 失败')
    return jsonify({'success': True, 'replaced': replace_status['replaced'], 'failed': replace_status['failed']})


@bp.route('/api/replace/status')
def get_replace_status():
    with _status_lock:
        return jsonify({
            'processing': replace_status['processing'],
            'total': replace_status['total'],
            'processed': replace_status['processed'],
            'replaced': replace_status['replaced'],
            'failed': replace_status['failed'],
            'logs': list(replace_status['logs'])
        })


# ==================== 系统信息 ====================

@bp.route('/api/poll')
def poll_aggregate():
    """聚合轮询端点：一次请求返回前端 30 秒轮询所需的全部状态数据，
    替代原先的 8 个独立请求（dailyStats/webdav/replace/auth/yiyan/mps×2）。
    """
    result = {'success': True, 'time': int(time.time())}

    # 1. 每日统计
    try:
        from werss.db import DB
        from werss.models.article import Article
        with DB.session_scope() as session:
            today_start = get_bjt_now().replace(hour=0, minute=0, second=0, microsecond=0)
            today_total = session.query(Article).filter(Article.created_at >= today_start).count()
        result['daily_stats'] = {
            'success': True,
            'today_total': today_total,
            'today_success': today_total,
            'today_failed': 0
        }
    except Exception as e:
        result['daily_stats'] = {'success': False, 'error': str(e), 'today_total': 0, 'today_success': 0, 'today_failed': 0}

    # 2. WebDAV 上传状态
    from .routes_notify import webdav_upload_status
    with _status_lock:
        result['webdav_status'] = {
            'uploading': webdav_upload_status['uploading'],
            'last_result': webdav_upload_status['last_result'],
            'last_time': webdav_upload_status['last_time'],
            'logs': list(webdav_upload_status['logs'])
        }

    # 3. 文件替换状态
    with _status_lock:
        result['replace_status'] = {
            'processing': replace_status['processing'],
            'total': replace_status['total'],
            'processed': replace_status['processed'],
            'replaced': replace_status['replaced'],
            'failed': replace_status['failed'],
            'logs': list(replace_status['logs'])
        }

    # 4. 授权状态
    try:
        from .routes_auth import get_token_expiry
        expiry_info = get_token_expiry()
        if not expiry_info or not expiry_info.get("expiry_timestamp"):
            result['auth_status'] = {"authorized": False, "message": "未授权，请扫码登录"}
        else:
            now = time.time()
            remaining = max(0, expiry_info["expiry_timestamp"] - now)
            expired = remaining <= 0
            hours = int(remaining // 3600)
            minutes = int((remaining % 3600) // 60)
            result['auth_status'] = {
                "authorized": True,
                "expired": expired,
                "expiry_time": expiry_info["expiry_time"],
                "remaining_seconds": int(remaining),
                "remaining_text": f"{hours}小时{minutes}分钟"
            }
    except Exception as e:
        result['auth_status'] = {"authorized": False, "error": str(e)}

    # 5. 一言
    try:
        from .routes_system import _compute_yiyan
        result['yiyan'] = _compute_yiyan()
    except Exception:
        result['yiyan'] = {'text': '今日无事', 'disabled': False}

    # 6. 公众号列表
    try:
        from werss.db import DB
        from werss.models.feed import Feed
        with DB.session_scope() as session:
            mps = session.query(Feed).order_by(Feed.created_at.desc()).all()
            result['mps'] = [{
                'id': mp.id,
                'mp_name': mp.mp_name,
                'mp_cover': mp.mp_cover,
                'mp_intro': mp.mp_intro,
                'status': mp.status,
                'faker_id': mp.faker_id,
                'sync_time': mp.sync_time,
                'created_at': mp.created_at.isoformat() if mp.created_at and hasattr(mp.created_at, "isoformat") else str(mp.created_at)
            } for mp in mps]
    except Exception as e:
        result['mps'] = []

    return jsonify(result)


# ==================== 扫雷游戏通关记录 ====================
# 存放到 data 子目录（docker-compose 已挂载 ./data:/app/data:rw），避免容器重启数据丢失


@bp.route('/api/minesweeper/record', methods=['GET'])
def get_minesweeper_record():
    """获取扫雷通关排行榜（按用时升序，取前 10）"""
    try:
        records = []
        if os.path.exists(_MS_RECORD_FILE):
            with open(_MS_RECORD_FILE, 'r', encoding='utf-8') as f:
                records = json.load(f)
        if not isinstance(records, list):
            records = []
        records.sort(key=lambda r: r.get('elapsed', 999999))
        return jsonify({"success": True, "records": records[:10]})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@bp.route('/api/minesweeper/record', methods=['POST'])
def save_minesweeper_record():
    """保存扫雷通关记录（追加到排行榜）"""
    try:
        data = request.get_json() or {}
        elapsed = data.get('elapsed', 0)
        # 获取真实 IP（支持反向代理）
        ip = request.headers.get('X-Forwarded-For', '').split(',')[0].strip()
        if not ip:
            ip = request.headers.get('X-Real-IP', '')
        if not ip:
            ip = request.remote_addr or 'unknown'
        new_record = {
            "ip": ip,
            "completed_at": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            "elapsed": elapsed
        }
        # 读取已有记录
        records = []
        if os.path.exists(_MS_RECORD_FILE):
            with open(_MS_RECORD_FILE, 'r', encoding='utf-8') as f:
                records = json.load(f)
        if not isinstance(records, list):
            records = []
        records.append(new_record)
        # 按用时升序排序，只保留前 50 条
        records.sort(key=lambda r: r.get('elapsed', 999999))
        records = records[:50]
        os.makedirs(os.path.dirname(_MS_RECORD_FILE), exist_ok=True)
        with open(_MS_RECORD_FILE, 'w', encoding='utf-8') as f:
            json.dump(records, f, ensure_ascii=False, indent=2)
        return jsonify({"success": True, "record": new_record, "rank": next(i for i, r in enumerate(records) if r is new_record) + 1})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


