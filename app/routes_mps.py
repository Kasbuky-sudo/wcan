# Developer: SONGJUNSONG; Affiliation: School of Finance and Economics, Jilin Business and Technology College
"""公众号管理与同步路由"""
from flask import Blueprint, request, jsonify
from .core import *
from .core import _safe_thread, _load_json, _atomic_write, _status_lock

bp = Blueprint('mps', __name__)


@bp.route('/api/mps', methods=['GET'])
def get_mps_list():
    try:
        from werss.db import DB
        from werss.models.feed import Feed
        with DB.session_scope() as session:
            mps = session.query(Feed).order_by(Feed.created_at.desc()).all()
            result = [{
                'id': mp.id,
                'mp_name': mp.mp_name,
                'mp_cover': mp.mp_cover,
                'mp_intro': mp.mp_intro,
                'status': mp.status,
                'faker_id': mp.faker_id,
                'sync_time': mp.sync_time,
                'created_at': mp.created_at.isoformat() if mp.created_at and hasattr(mp.created_at, 'isoformat') else str(mp.created_at)
            } for mp in mps]
        return jsonify({'success': True, 'mps': result})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@bp.route('/api/mps/search/<kw>', methods=['GET'])
def search_mp(kw):
    try:
        from werss.wx.wx import search_Biz
        result = search_Biz(kw)
        return jsonify({'success': True, 'list': result.get('list', []), 'total': result.get('total', 0)})
    except Exception as e:
        return jsonify({'success': False, 'error': f'搜索失败: {str(e)}。请先扫码登录'})


@bp.route('/api/mps', methods=['POST'])
def add_mp():
    data = request.get_json()
    mp_name = data.get('mp_name', '').strip()
    mp_cover = data.get('mp_cover', '').strip()
    mp_intro = data.get('mp_intro', '').strip()
    faker_id = data.get('faker_id', '').strip()
    if not mp_name or not faker_id:
        return jsonify({'success': False, 'error': '缺少必要参数'})
    try:
        import base64
        from werss.db import DB
        from werss.models.feed import Feed
        with DB.session_scope() as session:
            existing = session.query(Feed).filter(Feed.faker_id == faker_id).first()
            if existing:
                return jsonify({'success': False, 'error': '该公众号已存在'})
            mpx_id = base64.b64decode(faker_id).decode('utf-8')
            feed_id = f"MP_WXS_{mpx_id}"
            now = datetime.now()
            new_feed = Feed(
                id=feed_id,
                mp_name=mp_name,
                mp_cover=mp_cover,
                mp_intro=mp_intro,
                status=1,
                created_at=now,
                updated_at=now,
                faker_id=faker_id,
                sync_time=0,
                update_time=0,
            )
            session.add(new_feed)
            session.commit()
        return jsonify({'success': True, 'message': f'已添加: {mp_name}', 'id': feed_id})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@bp.route('/api/mps/<mp_id>', methods=['DELETE'])
def delete_mp(mp_id):
    try:
        from werss.db import DB
        from werss.models.feed import Feed
        with DB.session_scope() as session:
            mp = session.query(Feed).filter(Feed.id == mp_id).first()
            if not mp:
                return jsonify({'success': False, 'error': '公众号不存在'})
            session.delete(mp)
            session.commit()
        return jsonify({'success': True, 'message': '已删除'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@bp.route('/api/mps/<mp_id>/fetch', methods=['POST'])
@rate_limit(max_calls=10, window=60)
def fetch_single_mp(mp_id):
    # 手动操作：重置状态后立即启动新任务
    crawl_status['status'] = 'idle'
    crawl_status['preview_data'] = None
    crawl_status['document_data'] = None
    reset_sync_status(f"开始更新: {mp_id}")
    def _do_fetch():
        try:
            from jobs.mps import update_single_mp as do_fetch
            do_fetch(mp_id, force=True)
            from .routes_crawl import check_token_expiry_and_notify
            check_token_expiry_and_notify()
        except Exception as e:
            print(f"提取失败: {e}")
            sync_status['running'] = False
            sync_status['phase'] = 'done'
            sync_status['message'] = f"提取异常: {str(e)[:60]}"
    thread = threading.Thread(target=_do_fetch, daemon=True)
    thread.start()
    return jsonify({'success': True, 'message': '任务已提交'})


@bp.route('/api/mps/fetch-all', methods=['POST'])
def fetch_all_mps():
    # 手动操作：重置状态后立即启动新任务
    print("[FetchAll] 收到'更新全部'请求，启动批量更新任务...")
    debug_log('INFO', 'sync', '收到"更新全部"请求，启动批量更新任务')
    crawl_status['status'] = 'idle'
    crawl_status['preview_data'] = None
    crawl_status['document_data'] = None
    reset_sync_status("开始批量更新...")
    with _status_lock:
        sync_status['running'] = True
        sync_status['phase'] = 'processing'
    def _do_fetch_all():
        try:
            print("[FetchAll] 开始执行 process_all_mps(force=True)...")
            debug_log('INFO', 'sync', '开始执行 process_all_mps(force=True)')
            from jobs.mps import process_all_mps
            process_all_mps(force=True)
            print("[FetchAll] process_all_mps() 执行完成")
            debug_log('INFO', 'sync', 'process_all_mps() 执行完成')
            from .routes_crawl import check_token_expiry_and_notify
            check_token_expiry_and_notify()
            print("[FetchAll] Token 过期检查完成")
        except Exception as e:
            import traceback
            err_detail = traceback.format_exc()
            print(f"[FetchAll] 全部更新失败: {e}")
            print(f"[FetchAll] 异常详情:\n{err_detail}")
            debug_log('ERROR', 'sync', f'全部更新失败: {e}\n{err_detail[:500]}')
            with _status_lock:
                sync_status['running'] = False
                sync_status['phase'] = 'done'
                sync_status['message'] = f"批量更新异常: {str(e)[:60]}"
    thread = threading.Thread(target=_do_fetch_all, daemon=True)
    thread.start()
    return jsonify({'success': True, 'message': '全部更新任务已提交'})


@bp.route('/api/task-status', methods=['GET'])
def get_task_status():
    """轻量级任务状态端点，供前端轮询检测任务完成"""
    with _status_lock:
        return jsonify({
            'running': sync_status.get('running', False),
            'phase': sync_status.get('phase', 'idle'),
            'task_done_time': sync_status.get('task_done_time'),
            'task_done_summary': sync_status.get('task_done_summary', ''),
        })


@bp.route('/api/sync-folder', methods=['POST'])
def sync_folder():
    from crawler import get_article_base
    article_base = get_article_base()
    if not os.path.exists(article_base):
        return jsonify({'success': True, 'synced': 0, 'message': '文章目录不存在'})
    from . import routes_crawl
    routes_crawl._load_crawl_history()
    existing_titles = {h.get('title', '') for h in routes_crawl.crawl_history}
    synced = 0
    for root, dirs, files in os.walk(article_base):
        for f in files:
            if not f.endswith('.docx'):
                continue
            filepath = os.path.join(root, f)
            try:
                stat = os.stat(filepath)
                modified_at = datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M:%S')
            except Exception:
                modified_at = '未知'
            name_no_ext = f.replace('.docx', '')
            is_modified = '【改】' in name_no_ext
            display_title = name_no_ext
            publish_time = 0
            clean_name = name_no_ext.replace('【改】', '', 1) if is_modified else name_no_ext
            if len(clean_name) >= 9 and clean_name[:8].isdigit() and clean_name[8] == '_':
                try:
                    dt_naive = datetime.strptime(clean_name[:8], "%Y%m%d")
                    publish_time = int(dt_naive.timestamp())
                except Exception:
                    pass
            if len(display_title) > 8:
                parts = display_title.split('_', 1)
                if len(parts) == 2 and len(parts[0]) == 8 and parts[0].isdigit():
                    display_title = parts[1]
            if display_title in existing_titles:
                continue
            existing_titles.add(display_title)
            routes_crawl.add_to_crawl_history({
                'title': display_title,
                'link': '',
                'processed_at': modified_at,
                'publish_time': publish_time,
                'feed_name': '本地文件',
                'success': True,
                'is_repost': False,
                'retry_exhausted': False,
                'error': None,
                'modified': is_modified,
                'local_file': True
            })
            synced += 1
    routes_crawl._save_crawl_history()
    try:
        routes_crawl._save_history_html()
    except Exception as e:
        print(f"[SYNC] 重新生成历史 HTML 失败: {e}")
    debug_log('INFO', 'sync', f'本地文件夹同步完成: {synced}篇')
    return jsonify({'success': True, 'synced': synced, 'message': f'同步完成，共{synced}篇'})


@bp.route('/api/stats/daily')
def get_daily_stats():
    try:
        from werss.db import DB
        from werss.models.article import Article
        with DB.session_scope() as session:
            today_start = get_bjt_now().replace(hour=0, minute=0, second=0, microsecond=0)
            today_total = session.query(Article).filter(Article.created_at >= today_start).count()
        return jsonify({'success': True, 'today_total': today_total, 'today_success': today_total, 'today_failed': 0})
    except Exception:
        return jsonify({'success': True, 'today_total': 0, 'today_success': 0, 'today_failed': 0})


@bp.route('/api/sync/config', methods=['GET'])
def get_sync_config():
    from werss.config import cfg
    return jsonify({
        'success': True,
        'sync_interval': int(cfg.get("sync_interval", 60)),
        'sync_enabled': bool(cfg.get("server.enable_job", True)),
        'token_reminder_hours': int(cfg.get("token_reminder_hours", 12)),
        'fetch_count': int(cfg.get("count", 10))
    })


@bp.route('/api/sync/config', methods=['POST'])
def update_sync_config():
    from werss.config import cfg
    data = request.get_json()
    if 'sync_interval' in data:
        val = int(data['sync_interval'])
        if val < 1:
            val = 60  # 最小 1 分钟，防止 0 或负数导致 APScheduler 疯狂执行
        cfg.set("sync_interval", val)
    if 'sync_enabled' in data:
        cfg.set("server.enable_job", bool(data['sync_enabled']))
    if 'token_reminder_hours' in data:
        cfg.set("token_reminder_hours", int(data['token_reminder_hours']))
    if 'fetch_count' in data:
        cfg.set("count", int(data['fetch_count']))
    cfg.save()
    # 动态更新 scheduler 中的同步间隔
    if 'sync_interval' in data:
        try:
            from jobs.mps import reschedule_batch_job
            reschedule_batch_job(int(data['sync_interval']))
        except Exception as e:
            print(f"动态更新同步间隔失败: {e}")
    return jsonify({'success': True, 'message': '配置已保存'})
