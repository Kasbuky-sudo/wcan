# Made by SONGJUNSONG, Jilin Business and Technology College (School of Finance and Economics)
import re
import os
import time
import threading
from datetime import datetime, timezone, timedelta

BJT = timezone(timedelta(hours=8))

def _now():
    """返回北京时间 datetime 对象"""
    return datetime.now(BJT)

def _now_str():
    """返回北京时间字符串 YYYY-MM-DD HH:MM:SS"""
    return _now().strftime('%Y-%m-%d %H:%M:%S')

def _extract_body_text(result):
    """从 crawl_article 结果提取纯文本正文"""
    items = result.get('content_items', []) if result else []
    if not items:
        return ''
    parts = []
    for item in items:
        if isinstance(item, str):
            parts.append(item)
        elif isinstance(item, dict):
            t = item.get('text', '') or item.get('content', '') or str(item)
            parts.append(t)
        else:
            parts.append(str(item))
    return '\n'.join(parts).strip()

def _inject_body_to_art(art, result):
    """将爬取正文注入 art['content']，供写入数据库"""
    if art and result and result.get('success'):
        body = _extract_body_text(result)
        if body:
            art['content'] = body
            art['content_html'] = ''  # 暂不存 HTML


from crawler import get_article_base

try:
    from paths import user_dir as _user_dir
except ImportError:
    def _user_dir():
        return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

ARTICLE_BASE = get_article_base()
REPORT_BASE = os.path.join(_user_dir(), "报错文档")
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_LOG_FILE = os.path.join(PROJECT_ROOT, 'data', 'cache_refresh.log')


def _status():
    try:
        from app import sync_status
        return sync_status
    except Exception:
        return {}


def add_sync_log(msg):
    try:
        from app import add_sync_log as _add
        _add(msg)
    except Exception:
        pass


def add_to_history(title, link, mp_name, success, is_repost=False, error=None, publish_time=0):
    try:
        from app import add_to_crawl_history
        item = {
            'title': title,
            'link': link or '',
            'processed_at': _now_str(),
            'feed_name': mp_name,
            'success': success,
            'is_repost': is_repost,
            'retry_exhausted': False,
            'error': error
        }
        if publish_time:
            item['publish_time'] = publish_time
        add_to_crawl_history(item)
    except Exception:
        pass


def add_progress(percent, msg):
    try:
        from app import update_sync_status as _upd
        _upd(percent, msg)
    except Exception:
        pass


def _update_article(idx, **fields):
    s = _status()
    if s and 'articles' in s and idx < len(s['articles']):
        s['articles'][idx].update(fields)


def _push_articles(article_list, mp_name):
    s = _status()
    if not s:
        return
    for art in article_list:
        if not art or not isinstance(art, dict):
            continue
        s['articles'].append({
            'title': art.get('title', '无标题'),
            'mp_name': mp_name,
            'status': 'pending',
            'error': '',
            'progress': 0
        })


class CacheManager:
    """统一磁盘缓存管理器
    单次 os.walk 扫描，同时收集普通文件和【改】版本，
    提供 should_skip() 判定和 register() 更新接口。
    """
    def __init__(self):
        self.existing_files = set()
        self.modified_files = set()
        self.scan_errors = []

    def load(self):
        """扫描文章目录，加载缓存状态"""
        self.existing_files.clear()
        self.modified_files.clear()
        self.scan_errors.clear()

        try:
            if not os.path.exists(ARTICLE_BASE):
                add_sync_log("文章目录不存在，创建...")
                os.makedirs(ARTICLE_BASE, exist_ok=True)
                return
        except OSError as e:
            self.scan_errors.append(f"创建目录失败: {e}")
            add_sync_log(f"⚠ 缓存目录错误: {e}")
            return

        total = 0
        modified_count = 0
        try:
            for root, dirs, files in os.walk(ARTICLE_BASE, onerror=lambda e: self.scan_errors.append(f"遍历错误: {e}")):
                for f in files:
                    if not f.endswith('.docx'):
                        continue
                    total += 1
                    self.existing_files.add(f)
                    if f.startswith('【改】'):
                        original_fn = f[3:]  # 去掉【改】前缀(3字符)
                        self.modified_files.add(original_fn)
                        modified_count += 1
        except PermissionError as e:
            self.scan_errors.append(f"权限不足: {e}")
        except OSError as e:
            self.scan_errors.append(f"磁盘错误: {e}")
        except Exception as e:
            self.scan_errors.append(f"扫描异常: {e}")

        add_sync_log(f"缓存加载完成: {total} 篇普通, {modified_count} 篇已修改" +
                     (f", {len(self.scan_errors)} 个错误" if self.scan_errors else ""))

    def should_skip(self, art):
        """判断文章是否应跳过网络爬取。
        返回 (skip: bool, reason: str)
          - ('cached',)     : 普通文件已存在
          - ('modified',)   : 【改】版本已存在
          - (False, '')     : 需要爬取
        """
        target_fn = _article_key(art)
        if not target_fn:
            return False, ''

        if target_fn in self.existing_files:
            return True, 'cached'

        if target_fn in self.modified_files:
            return True, 'modified'

        return False, ''

    def register(self, file_path):
        """爬取成功后注册新缓存"""
        if file_path:
            fn = os.path.basename(file_path)
            self.existing_files.add(fn)
            if fn.startswith('【改】'):
                self.modified_files.add(fn[3:])  # 去掉【改】前缀(3字符)

    @property
    def is_healthy(self):
        return len(self.scan_errors) == 0


def _is_repost(title):
    return any(kw in title for kw in ['【转载】', '[转载]', '转载自', '转载：', '轉載'])


def _article_key(art):
    title = art.get('title', '')
    ts = art.get('publish_time', 0)
    date_str = datetime.fromtimestamp(ts, BJT).strftime("%Y%m%d") if ts else "00000000"
    clean = re.sub(r'[<>:"/\\|?*]', '', title).replace(' ', '_').replace('\n', '_').replace('\r', '_')[:100]
    return f"{date_str}_{clean}.docx"


def _on_batch_progress(progress, message):
    add_sync_log(message)


def _write_cache_log(msg):
    """写缓存刷新日志"""
    try:
        log_dir = os.path.dirname(CACHE_LOG_FILE)
        os.makedirs(log_dir, exist_ok=True)
        timestamp = _now_str()
        with open(CACHE_LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(f"[{timestamp}] {msg}\n")
    except Exception:
        pass


def refresh_cache():
    """定时刷新磁盘缓存，带重试、告警和日志记录"""
    _write_cache_log("===== 缓存刷新开始 =====")
    max_retries = 3
    last_error = None

    for attempt in range(max_retries):
        try:
            cache = CacheManager()
            cache.load()

            if not cache.is_healthy:
                err_detail = "; ".join(cache.scan_errors)
                raise RuntimeError(f"扫描异常: {err_detail}")

            msg = f"✅ 刷新成功: {len(cache.existing_files)} 篇普通, {len(cache.modified_files)} 篇已修改"
            _write_cache_log(msg)
            return True

        except Exception as e:
            last_error = str(e)
            err_msg = f"⚠ 刷新失败 (尝试 {attempt + 1}/{max_retries}): {last_error}"
            _write_cache_log(err_msg)

            if attempt < max_retries - 1:
                time.sleep(5)

    # 全部重试失败 → 告警
    alert_msg = f"❌ 磁盘缓存刷新失败（已重试 {max_retries} 次）\n{last_error}"
    _write_cache_log(alert_msg)
    try:
        from app import send_notification
        threading.Thread(target=lambda: send_notification(alert_msg, notify_type='error_reminder'), daemon=True).start()
    except Exception:
        pass

    return False


_last_auth_notify_time = 0  # 上次发送授权失效通知的时间戳
_batch_abort = False  # 批量任务中止标志（手动触发新任务时设为 True，旧任务检测到后退出）


def request_batch_abort():
    """请求中止当前正在运行的批量任务（供手动触发时调用）"""
    global _batch_abort
    _batch_abort = True
    print("[BatchAbort] 已请求中止当前批量任务")

def _check_auth_and_notify():
    try:
        from werss.driver.wx_api import WeChat_api
        if not WeChat_api.HasLogin():
            import time as _time
            global _last_auth_notify_time
            now = _time.time()
            # 30 分钟内只发一次通知，避免疯狂推送
            if now - _last_auth_notify_time < 1800:
                print("[Auth] Token 已失效，但 30 分钟内已通知过，跳过重复推送")
                return
            _last_auth_notify_time = now
            print("[Auth] Token 已失效，自动刷新二维码...")
            try:
                # 自动生成新二维码
                WeChat_api.get_qr_code()
                # 推通知渠道
                try:
                    from app import send_notification
                    threading.Thread(target=lambda: send_notification("⚠ RSS授权已失效，新二维码已自动生成，请尽快扫码登录！", notify_type='rss_expiry'), daemon=True).start()
                except Exception:
                    pass
            except Exception as e:
                print(f"[Auth] 自动刷新二维码失败: {e}")
                try:
                    from app import send_notification
                    threading.Thread(target=lambda: send_notification(f"⚠ RSS授权已失效且自动刷新失败: {e}，请手动刷新！", notify_type='rss_expiry'), daemon=True).start()
                except Exception:
                    pass
    except Exception:
        pass


def _check_auth_mid_crawl(consecutive_auth_failures: int) -> bool:
    """爬取中途检测到多次 auth 失败时自动刷新二维码，返回是否已刷新"""
    if consecutive_auth_failures < 3:
        return False
    try:
        import time as _time
        global _last_auth_notify_time
        now = _time.time()
        # 30 分钟内只发一次通知
        if now - _last_auth_notify_time < 1800:
            print(f"[Auth] 连续 {consecutive_auth_failures} 次 auth 失败，但 30 分钟内已通知过，跳过")
            return False
        _last_auth_notify_time = now
        from werss.driver.wx_api import WeChat_api
        print(f"[Auth] 连续 {consecutive_auth_failures} 次 auth 失败，自动刷新二维码...")
        WeChat_api.get_qr_code()
        return True
    except Exception as e:
        print(f"[Auth] 中途刷新二维码失败: {e}")
        return False


def _verify_file_exists(file_path, art_title):
    if not file_path:
        return False, "file_path为空"
    if os.path.exists(file_path):
        return True, None
    # 新结构: /app/文章/2026/20260617/file.docx — 日期目录在年份子目录下
    date_dir = os.path.basename(os.path.dirname(file_path)) or ''
    year_dir = os.path.basename(os.path.dirname(os.path.dirname(file_path))) or ''
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(file_path))) or ARTICLE_BASE
    # 优先按新结构查找
    alt_new = os.path.join(base_dir, year_dir, date_dir) if year_dir.isdigit() and len(year_dir) == 4 else ''
    if alt_new and os.path.isdir(alt_new):
        for f in os.listdir(alt_new):
            if f.endswith('.docx') and art_title[:30] in f:
                return True, None
    # 回退旧结构
    alt_old = os.path.join(ARTICLE_BASE, date_dir)
    if os.path.isdir(alt_old):
        for f in os.listdir(alt_old):
            if f.endswith('.docx') and art_title[:30] in f:
                return True, None
    return False, f"文件不存在: {file_path}"


def _build_error_summary(all_dup, all_repost, all_fail, all_no_link, all_verify_fail):
    parts = []
    if all_dup:
        parts.append(f"重复跳过 ({len(all_dup)}篇)")
        for d in all_dup[-50:]:
            parts.append(f"  [{d['mp']}] {d['title']} -> {d['key']}")
    if all_repost:
        parts.append(f"转载跳过 ({len(all_repost)}篇)")
        for r in all_repost[-50:]:
            parts.append(f"  [{r['mp']}] {r['title']}")
    if all_no_link:
        parts.append(f"无链接跳过 ({len(all_no_link)}篇)")
        for n in all_no_link[-50:]:
            parts.append(f"  [{n['mp']}] {n['title']}")
    if all_fail:
        parts.append(f"爬取失败 ({len(all_fail)}篇)")
        for f in all_fail[-50:]:
            parts.append(f"  [{f['mp']}] {f['title']}\n    错误：{f['error']}")
    if all_verify_fail:
        parts.append(f"保存验证失败 ({len(all_verify_fail)}篇)")
        for v in all_verify_fail[-50:]:
            parts.append(f"  [{v['mp']}] {v['title']}\n    错误：{v['error']}")
    if not parts:
        parts.append("（无跳过项）")
    return "\n".join(parts)


def _write_error_report(scope_name, summary, all_fail, all_no_link, all_verify_fail):
    if not all_fail and not all_no_link and not all_verify_fail:
        return ''
    os.makedirs(REPORT_BASE, exist_ok=True)
    date_dir = os.path.join(REPORT_BASE, _now().strftime('%Y%m%d'))
    os.makedirs(date_dir, exist_ok=True)
    safe_scope = re.sub(r'[<>:"/\\|?*]', '_', scope_name)[:40] or '任务'
    filename = f"{_now().strftime('%H%M%S')}_{safe_scope}_报错文档.txt"
    file_path = os.path.join(date_dir, filename)

    lines = [
        f"任务范围：{scope_name}",
        f"生成时间：{_now_str()}",
        f"任务摘要：{summary}",
        "",
    ]
    if all_no_link:
        lines.append(f"无链接 ({len(all_no_link)}篇)")
        for item in all_no_link:
            lines.append(f"- [{item['mp']}] {item['title']}")
        lines.append("")
    if all_fail:
        lines.append(f"爬取失败 ({len(all_fail)}篇)")
        for item in all_fail:
            lines.append(f"- [{item['mp']}] {item['title']}")
            lines.append(f"  错误：{item['error']}")
        lines.append("")
    if all_verify_fail:
        lines.append(f"保存验证失败 ({len(all_verify_fail)}篇)")
        for item in all_verify_fail:
            lines.append(f"- [{item['mp']}] {item['title']}")
            lines.append(f"  错误：{item['error']}")
        lines.append("")

    with open(file_path, 'w', encoding='utf-8') as f:
        f.write("\n".join(lines).strip() + "\n")

    rel_path = os.path.relpath(file_path, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return rel_path.replace('\\', '/')


def process_all_mps(force=False):
    try:
        from werss.wx.wx import get_list
        from crawler import WeChatCrawler
        from werss.db import DB
        from werss.models.feed import Feed
        from jobs.article import add_article_to_db, update_mps_sync
        from app import sync_status, send_notification, is_failure_notified, mark_failure_notified
    except Exception as e:
        import traceback
        print(f"[process_all_mps] 导入模块失败: {e}")
        print(traceback.format_exc())
        try:
            from app.core import debug_log
            debug_log('ERROR', 'sync', f'process_all_mps 导入失败: {e}\n{traceback.format_exc()[:500]}')
        except Exception:
            pass
        return

    add_sync_log = _status().get('add_sync_log', lambda x: None)
    global _batch_abort
    if force:
        # 手动触发：中止旧任务，从头开始
        if sync_status.get('running'):
            print("[process_all_mps] 手动触发，中止旧任务...")
            add_sync_log("手动触发，中止旧任务，从头开始")
            _batch_abort = True
            import time as _time
            _time.sleep(1)  # 等待旧任务退出
        _batch_abort = False  # 清除中止标志，开始新任务
    else:
        # 定时任务：重入保护
        if sync_status.get('running'):
            print("[process_all_mps] 已有任务正在运行，跳过本次执行")
            add_sync_log("已有任务正在运行，跳过")
            return
    sync_status.update({
        'running': True, 'mode': 'batch', 'phase': 'listing',
        'progress': 0, 'message': '读取公众号列表...',
        'articles': [], 'logs': [], 'error_summary': '', 'error_report_path': ''
    })

    add_sync_log("批量更新开始...")
    cache = CacheManager()
    cache.load()
    crawler = WeChatCrawler()
    _check_auth_and_notify()

    try:
        session = DB.get_session()
        mps = session.query(Feed).filter(Feed.status == 1).all()
        session.close()
    except Exception as e:
        add_sync_log(f"读取公众号列表失败: {e}")
        sync_status['running'] = False
        sync_status['message'] = f"读取失败: {e}"
        return

    if not mps:
        add_sync_log("没有订阅任何公众号")
        sync_status['running'] = False
        sync_status['message'] = "无订阅"
        return

    add_sync_log(f"共 {len(mps)} 个公众号待处理")

    all_articles_flat = []
    for idx, mp in enumerate(mps):
        mp_name = getattr(mp, 'mp_name', '') or getattr(mp, 'mp_id', '') or ''
        mp_faker = getattr(mp, 'faker_id', '') or getattr(mp, 'mp_id', '') or ''
        try:
            arts = get_list(faker_id=mp_faker, mp_id=mp_faker)
        except Exception as e:
            add_sync_log(f"获取 {mp_name} 文章列表失败: {e}")
            continue
        if arts:
            add_sync_log(f"  {mp_name}: {len(arts)} 篇")
            for a in arts:
                if a and isinstance(a, dict):
                    a['_mp_name'] = mp_name
                    a['_mp_id'] = mp_faker
                    all_articles_flat.append(a)

    if not all_articles_flat:
        add_sync_log("所有公众号均无新文章")
        sync_status['running'] = False
        sync_status['message'] = "无新文章"
        sync_status['phase'] = 'done'
        return

    _push_articles(all_articles_flat, '')
    sync_status['phase'] = 'processing'
    add_sync_log(f"共计 {len(all_articles_flat)} 篇文章待处理")

    total_word = 0
    total_skip_dup = 0
    total_skip_repost = 0
    total_fail = 0
    newly_notified = 0
    all_dup = []
    all_repost = []
    all_fail = []
    all_no_link = []
    all_verify_fail = []
    success_mps = []
    skipped_mps = []
    failed_mps = []
    article_idx = -1
    consecutive_fails = 0  # 连续失败计数，用于检测 auth 失效

    for art in all_articles_flat:
        article_idx += 1
        # 中止检查：手动触发新任务时退出
        if _batch_abort:
            print("[process_all_mps] 检测到中止标志，退出当前任务")
            add_sync_log("任务已被手动中止")
            sync_status['running'] = False
            sync_status['phase'] = 'aborted'
            sync_status['message'] = '已被新任务中止'
            return
        if not art or not isinstance(art, dict):
            continue
        mp_name = art.get('_mp_name', art.get('mp_name', ''))
        art_title = art.get('title', '无标题')
        art_url = art.get('url', '')
        art_ts = art.get('publish_time', 0)

        art_pct = int(article_idx / len(all_articles_flat) * 95)
        add_progress(art_pct, f"({article_idx+1}/{len(all_articles_flat)}) {art_title[:30]}")
        _update_article(article_idx, status='checking', progress=art_pct)

        # 每 30 篇主动验证一次授权状态，防止中途过期
        if article_idx > 0 and article_idx % 30 == 0:
            try:
                from werss.driver.wx_api import WeChat_api
                if not WeChat_api.HasLogin():
                    import time as _time
                    global _last_auth_notify_time
                    _now_t = _time.time()
                    if _now_t - _last_auth_notify_time >= 1800:
                        _last_auth_notify_time = _now_t
                        print(f"[Auth] 第 {article_idx} 篇时检测到授权失效，自动刷新二维码...")
                        WeChat_api.get_qr_code()
                    else:
                        print(f"[Auth] 第 {article_idx} 篇时检测到授权失效，但 30 分钟内已通知过，跳过")
            except Exception:
                pass

        if not art_url:
            add_sync_log(f"  ⛔ 无链接: {art_title}")
            all_no_link.append({'title': art_title, 'mp': mp_name})
            if mp_name:
                failed_mps.append(mp_name)
            add_to_history(art_title, '', mp_name, False, error='无链接', publish_time=art_ts)
            total_fail += 1
            _update_article(article_idx, status='error', error='无链接', progress=100)
            continue

        if _is_repost(art_title):
            add_sync_log(f"  ⏭ 转载: {art_title}")
            total_skip_repost += 1
            all_repost.append({'title': art_title, 'mp': mp_name})
            if mp_name:
                skipped_mps.append(mp_name)
            add_article_to_db(art)
            add_to_history(art_title, art_url, mp_name, False, is_repost=True, publish_time=art_ts)
            _update_article(article_idx, status='skip_repost', progress=100)
            continue

        skip, reason = cache.should_skip(art)
        if skip:
            if mp_name:
                skipped_mps.append(mp_name)
            if reason == 'modified':
                add_sync_log(f"  ✏️ 已修改，跳过: {art_title[:60]}")
            else:
                target_fn = _article_key(art)
                all_dup.append({'title': art_title, 'key': target_fn, 'mp': mp_name})
                add_to_history(art_title, art_url, mp_name, True, publish_time=art_ts)
            total_skip_dup += 1
            _update_article(article_idx, status='skip_dup', progress=100)
            continue

        _update_article(article_idx, status='crawling', progress=10)
        add_sync_log(f"  🕷 爬取: {art_title[:60]}")

        crawler.new_session()
        try:
            result = crawler.crawl_article(art_url, publish_time=art_ts,
                                           progress_callback=_on_batch_progress)
        except Exception as e:
            err_msg = str(e)[:200]
            add_sync_log(f"  ❌ 异常: {art_title[:40]} - {str(e)[:80]}")
            total_fail += 1
            consecutive_fails += 1
            # 检测是否为 auth 类错误并自动恢复
            auth_keywords = ['login', 'token', 'auth', 'cookie', 'session', 'unauthorized', '403', '401', '请重新登录', '登录超时', '扫码']
            if any(kw in err_msg.lower() for kw in auth_keywords):
                _check_auth_mid_crawl(consecutive_fails)
            all_fail.append({'title': art_title, 'mp': mp_name, 'error': err_msg})
            if mp_name:
                failed_mps.append(mp_name)
            add_to_history(art_title, art_url, mp_name, False, error=err_msg, publish_time=art_ts)
            _update_article(article_idx, status='error', error=err_msg, progress=100)
            try:
                if not is_failure_notified(art_url):
                    send_notification(f"❌ 爬取失败 [{mp_name}]\n{art_title}\n{err_msg}", notify_type='error_reminder')
                    mark_failure_notified(art_url)
                    newly_notified += 1
            except Exception:
                pass
            continue

        if result.get("success"):
            consecutive_fails = 0  # 成功后重置 auth 失败计数（batch）或无害赋值（single）
            fp = result.get("file_path", "")
            verified, verify_err = _verify_file_exists(fp, art_title)
            if verified:
                cache.register(fp)
                total_word += 1
                if mp_name:
                    success_mps.append(mp_name)
                add_article_to_db(art)
                add_to_history(art_title, art_url, mp_name, True, publish_time=art_ts)
                add_sync_log(f"  ✅ 保存: {os.path.basename(fp)}")
                _update_article(article_idx, status='done', progress=100)
            else:
                total_fail += 1
                all_verify_fail.append({'title': art_title, 'mp': mp_name, 'error': verify_err})
                if mp_name:
                    failed_mps.append(mp_name)
                add_to_history(art_title, art_url, mp_name, False, error=verify_err, publish_time=art_ts)
                add_sync_log(f"  ❌ 验证失败: {art_title[:40]} - {verify_err}")
                _update_article(article_idx, status='error', error=verify_err, progress=100)
                try:
                    if not is_failure_notified(art_url):
                        send_notification(f"❌ Word验证失败 [{mp_name}]\n{art_title}\n{verify_err}", notify_type='error_reminder')
                        mark_failure_notified(art_url)
                        newly_notified += 1
                except Exception:
                    pass
        elif result.get("is_repost"):
            total_skip_repost += 1
            all_repost.append({'title': art_title, 'mp': mp_name})
            if mp_name:
                skipped_mps.append(mp_name)
            add_article_to_db(art)
            add_to_history(art_title, art_url, mp_name, False, is_repost=True, publish_time=art_ts)
            _update_article(article_idx, status='skip_repost', progress=100)
            add_sync_log(f"  ⏭ 页内转载: {art_title[:60]}")
        elif result.get("is_404"):
            err = result.get('error', '文章已删除')
            add_sync_log(f"  🗑 404: {art_title[:40]}")
            all_fail.append({'title': art_title, 'mp': mp_name, 'error': err[:200]})
            if mp_name:
                failed_mps.append(mp_name)
            add_to_history(art_title, art_url, mp_name, False, error=err[:200], publish_time=art_ts)
            _update_article(article_idx, status='error', error=err[:200], progress=100)
        elif result.get("is_403"):
            err = result.get('error', '访问被拒绝')
            add_sync_log(f"  🚫 403: {art_title[:40]}")
            all_fail.append({'title': art_title, 'mp': mp_name, 'error': err[:200]})
            if mp_name:
                failed_mps.append(mp_name)
            add_to_history(art_title, art_url, mp_name, False, error=err[:200], publish_time=art_ts)
            _update_article(article_idx, status='error', error=err[:200], progress=100)
            # 403 可能是授权失效，递增计数并检测是否需要刷新二维码
            consecutive_fails += 1
            _check_auth_mid_crawl(consecutive_fails)
        elif result.get("is_redirect"):
            err = result.get('error', '重定向到外部')
            add_sync_log(f"  🔀 重定向: {art_title[:40]}")
            all_fail.append({'title': art_title, 'mp': mp_name, 'error': err[:200]})
            if mp_name:
                failed_mps.append(mp_name)
            add_to_history(art_title, art_url, mp_name, False, error=err[:200], publish_time=art_ts)
            _update_article(article_idx, status='error', error=err[:200], progress=100)
        elif result.get("is_http_error"):
            err = result.get('error', 'HTTP错误')
            add_sync_log(f"  ⚠ HTTP错误: {art_title[:40]}")
            all_fail.append({'title': art_title, 'mp': mp_name, 'error': err[:200]})
            if mp_name:
                failed_mps.append(mp_name)
            add_to_history(art_title, art_url, mp_name, False, error=err[:200], publish_time=art_ts)
            _update_article(article_idx, status='error', error=err[:200], progress=100)
        else:
            err = result.get('error', '未知错误')
            add_sync_log(f"  ❌ 失败: {art_title[:40]} - {err[:60]}")
            total_fail += 1
            all_fail.append({'title': art_title, 'mp': mp_name, 'error': err[:200]})
            if mp_name:
                failed_mps.append(mp_name)
            add_to_history(art_title, art_url, mp_name, False, error=err[:200], publish_time=art_ts)
            _update_article(article_idx, status='error', error=err[:200], progress=100)
            try:
                if not is_failure_notified(art_url):
                    send_notification(f"❌ 爬取失败 [{mp_name}]\n{art_title}\n{err}", notify_type='error_reminder')
                    mark_failure_notified(art_url)
                    newly_notified += 1
            except Exception:
                pass

    for mp in mps:
        try:
            update_mps_sync(getattr(mp, 'mp_id', ''))
        except Exception:
            pass

    error_summary = _build_error_summary(all_dup, all_repost, all_fail, all_no_link, all_verify_fail)
    add_progress(100, "批量更新完成")
    summary = f"批量更新完成: 共处理 {len(all_articles_flat)} 篇 → 产出 {total_word}Word, 重复 {total_skip_dup}, 转载 {total_skip_repost}, 失败 {total_fail}"
    report_path = _write_error_report("批量更新", summary, all_fail, all_no_link, all_verify_fail)
    if report_path:
        add_sync_log(f"报错文档已生成: {report_path}")
    add_sync_log(error_summary)
    add_sync_log(summary)
    sync_status['error_summary'] = error_summary
    sync_status['error_report_path'] = report_path
    sync_status['phase'] = 'done'
    sync_status['running'] = False
    sync_status['message'] = summary
    sync_status['task_done_time'] = _now().isoformat()
    sync_status['task_done_summary'] = summary
    if newly_notified > 0:
        try:
            send_notification(f"{summary}\n{error_summary[:800]}", notify_type='error_reminder')
        except Exception:
            pass



def update_single_mp(mp_id: str, force=False):
    try:
        from werss.wx.wx import get_list
        from crawler import WeChatCrawler
        from jobs.article import add_article_to_db, update_mps_sync
        from app import sync_status, send_notification, is_failure_notified, mark_failure_notified
    except Exception as e:
        add_sync_log(f"导入模块失败: {e}")
        return

    global _batch_abort
    if force:
        # 手动触发：中止旧任务，从头开始
        if sync_status.get('running'):
            print("[update_single_mp] 手动触发，中止旧任务...")
            add_sync_log("手动触发，中止旧任务，从头开始")
            _batch_abort = True
            import time as _time
            _time.sleep(1)
        _batch_abort = False
    else:
        # 重入保护
        if sync_status.get('running'):
            print("[update_single_mp] 已有任务正在运行，跳过")
            return
    sync_status.update({
        'running': True, 'mode': 'single', 'phase': 'listing',
        'progress': 0, 'message': f"开始更新: {mp_id}",
        'articles': [], 'logs': [], 'error_summary': '', 'error_report_path': ''
    })
    cache = CacheManager()
    cache.load()
    crawler = WeChatCrawler()
    _check_auth_and_notify()

    add_sync_log(f"开始单篇更新: {mp_id}")
    try:
        articles = get_list(faker_id=mp_id, mp_id=mp_id, count=30)
    except Exception as e:
        add_sync_log(f"获取文章列表失败: {e}")
        sync_status['running'] = False
        sync_status['message'] = f"失败: {e}"
        sync_status['phase'] = 'done'
        return

    if not articles:
        add_sync_log(f"{mp_id} 没有文章")
        sync_status['running'] = False
        sync_status['message'] = "没有新文章"
        sync_status['phase'] = 'done'
        return

    add_sync_log(f"获取到 {len(articles)} 篇文章")
    _push_articles(articles, mp_id)
    sync_status['phase'] = 'processing'

    word_count = 0
    skipped_dup = 0
    skipped_repost = 0
    failed = 0
    newly_notified = 0
    all_dup = []
    all_repost = []
    all_fail = []
    all_no_link = []
    all_verify_fail = []
    success_mps = []
    skipped_mps = []
    failed_mps = []

    for i, art in enumerate(articles):
        # 中止检查
        if _batch_abort:
            print("[update_single_mp] 检测到中止标志，退出当前任务")
            add_sync_log("任务已被手动中止")
            sync_status['running'] = False
            sync_status['phase'] = 'aborted'
            sync_status['message'] = '已被新任务中止'
            return
        if not art or not isinstance(art, dict):
            continue
        art_title = art.get('title', '无标题')
        art_url = art.get('url', '')
        art_ts = art.get('publish_time', 0)
        pct = int(i / len(articles) * 95)
        add_progress(pct, f"({i+1}/{len(articles)}) {art_title[:40]}")
        _update_article(i, status='checking', progress=pct)

        if not art_url:
            add_sync_log(f"  ⛔ 无链接: {art_title}")
            all_no_link.append({'title': art_title, 'mp': mp_id})
            failed_mps.append(mp_id)
            add_to_history(art_title, '', mp_id, False, error='无链接', publish_time=art_ts)
            failed += 1
            _update_article(i, status='error', error='无链接', progress=100)
            continue

        if _is_repost(art_title):
            add_sync_log(f"  ⏭ 转载: {art_title}")
            skipped_repost += 1
            all_repost.append({'title': art_title, 'mp': mp_id})
            skipped_mps.append(mp_id)
            add_article_to_db(art)
            add_to_history(art_title, art_url, mp_id, False, is_repost=True, publish_time=art_ts)
            _update_article(i, status='skip_repost', progress=100)
            continue

        skip, reason = cache.should_skip(art)
        if skip:
            skipped_mps.append(mp_id)
            if reason == 'modified':
                add_sync_log(f"  ✏️ 已修改，跳过: {art_title[:60]}")
            else:
                target_fn = _article_key(art)
                all_dup.append({'title': art_title, 'key': target_fn, 'mp': mp_id})
                add_to_history(art_title, art_url, mp_id, True, publish_time=art_ts)
            skipped_dup += 1
            _update_article(i, status='skip_dup', progress=100)
            continue

        _update_article(i, status='crawling', progress=10)
        add_sync_log(f"  🕷 爬取: {art_title[:60]}")

        crawler.new_session()
        try:
            result = crawler.crawl_article(art_url, publish_time=art_ts,
                                           progress_callback=_on_batch_progress)
        except Exception as e:
            err_msg = str(e)[:200]
            add_sync_log(f"  ❌ 异常: {art_title[:40]} - {str(e)[:80]}")
            failed += 1
            all_fail.append({'title': art_title, 'mp': mp_id, 'error': err_msg})
            failed_mps.append(mp_id)
            add_to_history(art_title, art_url, mp_id, False, error=err_msg, publish_time=art_ts)
            _update_article(i, status='error', error=err_msg, progress=100)
            try:
                if not is_failure_notified(art_url):
                    send_notification(f"❌ 单篇爬取失败\n{art_title}\n{err_msg}", notify_type='error_reminder')
                    mark_failure_notified(art_url)
                    newly_notified += 1
            except Exception:
                pass
            continue

        if result.get("success"):
            consecutive_fails = 0  # 成功后重置 auth 失败计数（batch）或无害赋值（single）
            fp = result.get("file_path", "")
            verified, verify_err = _verify_file_exists(fp, art_title)
            if verified:
                cache.register(fp)
                word_count += 1
                success_mps.append(mp_id)
                _inject_body_to_art(art, result)
                add_article_to_db(art)
                add_to_history(art_title, art_url, mp_id, True, publish_time=art_ts)
                add_sync_log(f"  ✅ 保存: {os.path.basename(fp)}")
                _update_article(i, status='done', progress=100)
            else:
                failed += 1
                all_verify_fail.append({'title': art_title, 'mp': mp_id, 'error': verify_err})
                failed_mps.append(mp_id)
                add_to_history(art_title, art_url, mp_id, False, error=verify_err, publish_time=art_ts)
                add_sync_log(f"  ❌ 验证失败: {art_title[:40]} - {verify_err}")
                _update_article(i, status='error', error=verify_err, progress=100)
                try:
                    if not is_failure_notified(art_url):
                        send_notification(f"❌ Word验证失败\n{art_title}\n{verify_err}", notify_type='error_reminder')
                        mark_failure_notified(art_url)
                        newly_notified += 1
                except Exception:
                    pass
        elif result.get("is_repost"):
            skipped_repost += 1
            all_repost.append({'title': art_title, 'mp': mp_id})
            skipped_mps.append(mp_id)
            add_article_to_db(art)
            add_to_history(art_title, art_url, mp_id, False, is_repost=True, publish_time=art_ts)
            _update_article(i, status='skip_repost', progress=100)
            add_sync_log(f"  ⏭ 页内转载: {art_title[:60]}")
        elif result.get("is_404"):
            err = result.get('error', '文章已删除')
            add_sync_log(f"  🗑 404: {art_title[:40]}")
            failed += 1
            all_fail.append({'title': art_title, 'mp': mp_id, 'error': err[:200]})
            failed_mps.append(mp_id)
            add_to_history(art_title, art_url, mp_id, False, error=err[:200], publish_time=art_ts)
            _update_article(i, status='error', error=err[:200], progress=100)
        elif result.get("is_403"):
            err = result.get('error', '访问被拒绝')
            add_sync_log(f"  🚫 403: {art_title[:40]}")
            failed += 1
            all_fail.append({'title': art_title, 'mp': mp_id, 'error': err[:200]})
            failed_mps.append(mp_id)
            add_to_history(art_title, art_url, mp_id, False, error=err[:200], publish_time=art_ts)
            _update_article(i, status='error', error=err[:200], progress=100)
        elif result.get("is_redirect"):
            err = result.get('error', '重定向到外部')
            add_sync_log(f"  🔀 重定向: {art_title[:40]}")
            failed += 1
            all_fail.append({'title': art_title, 'mp': mp_id, 'error': err[:200]})
            failed_mps.append(mp_id)
            add_to_history(art_title, art_url, mp_id, False, error=err[:200], publish_time=art_ts)
            _update_article(i, status='error', error=err[:200], progress=100)
        elif result.get("is_http_error"):
            err = result.get('error', 'HTTP错误')
            add_sync_log(f"  ⚠ HTTP错误: {art_title[:40]}")
            failed += 1
            all_fail.append({'title': art_title, 'mp': mp_id, 'error': err[:200]})
            failed_mps.append(mp_id)
            add_to_history(art_title, art_url, mp_id, False, error=err[:200], publish_time=art_ts)
            _update_article(i, status='error', error=err[:200], progress=100)
        else:
            err = result.get('error', '未知错误')
            add_sync_log(f"  ❌ 失败: {art_title[:40]} - {err[:60]}")
            failed += 1
            all_fail.append({'title': art_title, 'mp': mp_id, 'error': err[:200]})
            failed_mps.append(mp_id)
            add_to_history(art_title, art_url, mp_id, False, error=err[:200], publish_time=art_ts)
            _update_article(i, status='error', error=err[:200], progress=100)
            try:
                if not is_failure_notified(art_url):
                    send_notification(f"❌ 单篇爬取失败\n{art_title}\n{err}", notify_type='error_reminder')
                    mark_failure_notified(art_url)
                    newly_notified += 1
            except Exception:
                pass

    error_summary = _build_error_summary(all_dup, all_repost, all_fail, all_no_link, all_verify_fail)
    summary = f"[{mp_id}] 产出 {word_count}Word, 重复 {skipped_dup}, 转载 {skipped_repost}, 失败 {failed}"
    report_path = _write_error_report(mp_id, summary, all_fail, all_no_link, all_verify_fail)
    if report_path:
        add_sync_log(f"报错文档已生成: {report_path}")
    add_sync_log(error_summary)
    add_sync_log(summary)
    sync_status['error_summary'] = error_summary
    sync_status['error_report_path'] = report_path
    sync_status['phase'] = 'done'
    sync_status['running'] = False
    sync_status['message'] = summary
    sync_status['task_done_time'] = _now().isoformat()
    sync_status['task_done_summary'] = summary
    if newly_notified > 0:
        try:
            send_notification(f"{summary}\n{error_summary[:800]}", notify_type='error_reminder')
        except Exception:
            pass
    try:
        update_mps_sync(mp_id)
    except Exception:
        pass


_scheduler = None


def start_job():
    global _scheduler
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from werss.config import cfg

        def _auto_batch():
            """定时任务：若当前无手动任务运行才执行"""
            try:
                from app import sync_status
                if sync_status.get('running'):
                    print("定时任务: 检测到手动任务正在运行，跳过本次自动执行")
                    return
            except Exception:
                pass
            # RSS 未登录时跳过，避免疯狂执行 + 疯狂推送通知
            try:
                from werss.driver.wx_api import WeChat_api
                if not WeChat_api.HasLogin():
                    print("定时任务: RSS 未登录，跳过本次自动执行")
                    return
            except Exception as e:
                print(f"定时任务: 检查登录状态异常: {e}")
            process_all_mps()

        def _daily_report():
            """每日 8AM 推送早报"""
            try:
                from app import send_daily_report
                from datetime import datetime, timezone, timedelta
                BJT = timezone(timedelta(hours=8))
                now = datetime.now(BJT)
                print(f"[DailyJob] {now.strftime('%H:%M')} 触发每日早报")
                send_daily_report()
            except Exception as e:
                print(f"[DailyJob] 早报异常: {e}")

        def _daily_backup():
            """每日 3AM 备份 SQLite 数据库到 data/backups/，保留最近 7 份"""
            import sqlite3
            try:
                db_url = cfg.get("db", "sqlite:///data/articles.db")
                if not db_url.startswith('sqlite:///'):
                    print("[Backup] 非 SQLite 数据库，跳过备份")
                    return
                db_path = db_url[10:]
                if not os.path.exists(db_path):
                    print(f"[Backup] 数据库文件不存在: {db_path}")
                    return
                backup_dir = os.path.join(os.path.dirname(db_path) or '.', 'backups')
                os.makedirs(backup_dir, exist_ok=True)
                stamp = _now().strftime('%Y%m%d_%H%M%S')
                backup_path = os.path.join(backup_dir, f"articles_{stamp}.db")
                # 使用 sqlite3 backup API 保证一致性（即使在写入中）
                src = sqlite3.connect(db_path)
                dst = sqlite3.connect(backup_path)
                try:
                    src.backup(dst)
                finally:
                    dst.close()
                    src.close()
                print(f"[Backup] 已备份至 {backup_path}")
                # 清理旧备份，保留最近 7 份
                backups = sorted(
                    [f for f in os.listdir(backup_dir) if f.startswith('articles_') and f.endswith('.db')],
                    reverse=True,
                )
                for old in backups[7:]:
                    try:
                        os.remove(os.path.join(backup_dir, old))
                        print(f"[Backup] 清理旧备份: {old}")
                    except Exception as e:
                        print(f"[Backup] 清理失败 {old}: {e}")
            except Exception as e:
                print(f"[Backup] 备份异常: {e}")

        _scheduler = BackgroundScheduler()
        interval = int(cfg.get("sync_interval", 60))
        if interval < 1:
            print(f"[Scheduler] 配置的同步间隔为 {interval} 分钟，过小，已重置为 60 分钟")
            interval = 60
        _scheduler.add_job(_auto_batch, 'interval', minutes=interval, id='batch_update')
        _scheduler.add_job(refresh_cache, 'interval', minutes=30, id='cache_refresh')
        _scheduler.add_job(_daily_report, 'cron', hour=8, minute=0, id='daily_report')
        _scheduler.add_job(_daily_backup, 'cron', hour=3, minute=0, id='daily_backup')
        _scheduler.start()
        print(f"定时任务已启动: 每{interval}分钟批量更新 + 每30分钟缓存刷新 + 每日8AM早报 + 每日3AM备份")
    except Exception as e:
        print(f"定时任务调度器启动失败: {e}")


def stop_job():
    """暂停定时任务，手动操作时调用"""
    global _scheduler
    if _scheduler:
        try:
            _scheduler.pause_job('batch_update')
        except Exception:
            pass


def resume_job():
    """恢复定时任务，手动操作完成后调用"""
    global _scheduler
    if _scheduler:
        try:
            _scheduler.resume_job('batch_update')
        except Exception:
            pass


def reschedule_batch_job(new_interval_minutes):
    """用户修改同步间隔后，动态更新 scheduler 中的 batch_update 间隔"""
    global _scheduler
    if new_interval_minutes < 1:
        new_interval_minutes = 60
        print(f"[Scheduler] 间隔值过小({new_interval_minutes})，已重置为 60 分钟")
    if _scheduler:
        try:
            _scheduler.reschedule_job('batch_update', trigger='interval', minutes=new_interval_minutes)
            print(f"定时任务已重新调度: 批量更新间隔更新为每{new_interval_minutes}分钟")
        except Exception as e:
            print(f"重新调度定时任务失败: {e}")


def status_job():
    try:
        from app import sync_status
        return {
            'running': sync_status.get('running', False),
            'mode': sync_status.get('mode', ''),
            'phase': sync_status.get('phase', 'idle'),
            'progress': sync_status.get('progress', 0),
            'message': sync_status.get('message', ''),
            'articles': sync_status.get('articles', []),
            'error_summary': sync_status.get('error_summary', ''),
            'error_report_path': sync_status.get('error_report_path', '')
        }
    except Exception:
        return {'running': False, 'message': '状态获取失败'}
