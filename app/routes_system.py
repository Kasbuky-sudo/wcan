# © SONGJUNSONG · Jilin Business and Technology College · School of Finance and Economics
"""系统管理、在线更新、一言路由"""
from flask import Blueprint, request, jsonify
from .core import *
from .core import (
    _safe_thread,
    _load_json,
    _atomic_write,
    _safe_request,
    require_auth,
    rate_limit,
    get_debug_logs,
    clear_debug_logs,
    _debug_logs,
    _debug_lock,
    _status_lock,
    __version__,
)

bp = Blueprint('system', __name__)

# ====================== 全局变量 ======================
VERSION_LOG_FILE = os.path.join(DATA_DIR, 'version.log')

update_progress = {"running": False, "pct": 0, "step": "", "done": False, "result": None, "logs": [], "folder": "", "target_ver": ""}


def _schedule_container_restart(container_name: str, delay_seconds: int = 3):
    """延迟重启 Docker 容器，确保当前 HTTP 响应有机会先返回。"""
    def _restart():
        try:
            time.sleep(max(1, int(delay_seconds)))
            cmd = f"docker restart {container_name}"
            print(f"[Update] 即将执行容器重启: {cmd}")
            os.system(cmd)
        except Exception as e:
            print(f"[Update] 自动重启容器失败: {e}")
    threading.Thread(target=_restart, daemon=True).start()

_yiyan_state = {"normal": [], "normal_idx": 0, "date_cache": {}}

_YIYAN_DISABLE_DATES = {"06.04", "07.01", "08.01", "09.03", "09.18", "10.01", "12.13"}


# ==================== 版本日志与一致性校验 ====================

def log_version_change():
    """记录版本变更日志"""
    try:
        last_version = None
        if os.path.exists(VERSION_LOG_FILE):
            with open(VERSION_LOG_FILE, 'r', encoding='utf-8') as f:
                lines = [l.strip() for l in f.readlines() if l.strip()]
                if lines:
                    last = lines[-1]
                    # 取行内最后一个版本号（即 "->" 右侧的当前版本），
                    # 否则取到的是上一行的起点版本，记录会永远落后一拍
                    found = re.findall(r'v([\d.]+)', last)
                    if found:
                        last_version = found[-1]
        if last_version != __version__:
            ts = format_bjt_time()
            with open(VERSION_LOG_FILE, 'a', encoding='utf-8') as f:
                f.write(f"[{ts}] v{last_version or 'N/A'} -> v{__version__}\n")
            print(f"[VERSION] 版本变更已记录: v{last_version or 'N/A'} -> v{__version__}")
    except Exception as e:
        print(f"[VERSION] 记录版本日志失败: {e}")


def verify_version_consistency():
    """校验版本号在 app.py / config.yaml / index.html 中是否一致"""
    mismatches = []

    # 1) 检查 config.yaml
    try:
        from werss.config import cfg
        cfg_version = str(cfg.get("version", "")).strip()
        if cfg_version and cfg_version != __version__:
            mismatches.append(f"config.yaml: {cfg_version} != app/core.py: {__version__}")
    except Exception as e:
        mismatches.append(f"config.yaml 读取失败: {e}")

    # 2) 检查 index.html — 确保不含硬编码版本号
    INDEX_HTML = os.path.join(bundle_dir(), "templates", "index.html")
    try:
        if os.path.exists(INDEX_HTML):
            with open(INDEX_HTML, 'r', encoding='utf-8') as f:
                html = f.read()
            # 检查 meta version 标签使用了 Jinja2 变量
            if 'meta name="version"' in html and 'content="{{ version }}"' not in html:
                mismatches.append("index.html: meta version 标签未使用 Jinja2 变量 {{ version }}")
            # 检查 about-version 使用了 Jinja2 变量
            if 'about-version' in html and '{{ version }}' not in html:
                mismatches.append("index.html: about-version 未使用 Jinja2 变量 {{ version }}")
            # 检查是否残留硬编码版本号 (排除 changelog 引用)
            import re as _re
            hardcoded = _re.findall(r'(?<!\{)\bv(\d+\.\d+\.\d+)\b(?![\s]*\})', html)
            if hardcoded:
                mismatches.append(f"index.html: 疑似残留硬编码版本号 {hardcoded}")
    except Exception as e:
        mismatches.append(f"index.html 读取失败: {e}")

    # 3) 记录结果
    if mismatches:
        ts = format_bjt_time()
        with open(VERSION_LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(f"[{ts}] VERSION MISMATCH: v{__version__}\n")
            for m in mismatches:
                f.write(f"  - {m}\n")
        print(f"[VERSION] 版本不一致警告:")
        for m in mismatches:
            print(f"  ! {m}")
    else:
        print(f"[VERSION] 版本一致性校验通过: v{__version__} (app/core.py == config.yaml == index.html)")


# ==================== 更新与一言辅助函数 ====================

def get_update_dir():
    env_dir = os.environ.get("WCAN_UPDATE_DIR", "")
    if env_dir:
        return env_dir
    try:
        from werss.config import cfg
        cfg_dir = cfg.get("update_dir", "")
        if cfg_dir:
            return cfg_dir
    except Exception:
        pass
    return os.path.join(DATA_DIR, "update")


def get_yiyan_path():
    env_path = os.environ.get("YIYAN_PATH", "")
    if env_path:
        return env_path
    try:
        from werss.config import cfg
        cfg_path = cfg.get("yiyan_path", "")
        if cfg_path:
            return cfg_path
    except Exception:
        pass
    return os.path.join(DATA_DIR, "data", "yiyan.html")


def parse_version(v_str):
    v = v_str.strip()
    if v.startswith("v") or v.startswith("V"):
        v = v[1:]
    parts = v.split(".")
    nums = []
    for p in parts:
        n = re.sub(r"[^0-9]", "", p)
        nums.append(int(n) if n else 0)
    while len(nums) < 3:
        nums.append(0)
    return tuple(nums)


# ==================== Debug 日志 API ====================

@bp.route('/api/debug/logs', methods=['GET'])
def get_debug_logs():
    """获取最近的 debug 日志，供前端 debug 面板查看"""
    level = request.args.get('level', '')  # INFO/WARNING/ERROR
    source = request.args.get('source', '')
    limit = min(int(request.args.get('limit', 50)), 200)

    with _debug_lock:
        logs = list(_debug_logs)

    # 过滤
    if level:
        logs = [l for l in logs if l['level'] == level]
    if source:
        logs = [l for l in logs if source in l['source']]

    # 最新的在前
    logs = logs[-limit:][::-1]

    return jsonify({
        'success': True,
        'total': len(logs),
        'logs': logs
    })

@bp.route('/api/debug/logs/clear', methods=['POST'])
def clear_debug_logs():
    """清空 debug 日志"""
    with _debug_lock:
        _debug_logs.clear()
    return jsonify({'success': True})


# ==================== 健康检查与 API 文档 ====================

@bp.route('/api/health')
def health_check():
    """健康检查端点，供 Docker HEALTHCHECK / K8s liveness/readiness 探针使用。
    返回服务版本、DB 连接、scheduler 等关键组件状态。
    """
    from werss.config import cfg
    from sqlalchemy import text
    status = {
        'status': 'ok',
        'version': __version__,
        'time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'components': {}
    }
    http_status = 200

    # 1. 数据库连通性
    try:
        from werss.db import DB
        with DB.session_scope() as session:
            session.execute(text('SELECT 1'))
        status['components']['database'] = 'ok'
    except Exception as e:
        status['components']['database'] = f'error: {e}'
        status['status'] = 'degraded'
        http_status = 503

    # 2. 定时任务调度器
    try:
        from jobs.mps import _scheduler
        if _scheduler and _scheduler.running:
            status['components']['scheduler'] = 'running'
        else:
            status['components']['scheduler'] = 'stopped'
            status['status'] = 'degraded'
    except Exception as e:
        status['components']['scheduler'] = f'error: {e}'

    return jsonify(status), http_status

@bp.route('/api/docs')
def api_docs():
    """自动生成 API 文档列表，从 Flask 路由表提取。
    所有 /api/xxx 路由均支持 /api/v1/xxx 别名。
    """
    docs = []
    for rule in app.url_map.iter_rules():
        if rule.endpoint == 'static':
            continue
        methods = sorted(rule.methods - {'HEAD', 'OPTIONS'})
        if not methods:
            continue
        docs.append({
            'path': rule.rule,
            'methods': methods,
            'endpoint': rule.endpoint,
        })
    docs.sort(key=lambda x: x['path'])
    return jsonify({
        'success': True,
        'count': len(docs),
        'version': __version__,
        'note': '所有 /api/xxx 路由均支持 /api/v1/xxx 别名前缀',
        'apis': docs,
    })


# ==================== 系统信息 API ====================

@bp.route('/api/system/info')
def get_system_info():
    def get_mem():
        try:
            with open('/proc/meminfo') as f:
                for line in f:
                    if 'MemTotal' in line:
                        kb = int(line.split()[1])
                        return f'{round(kb / (1024**2), 1)} GB'
        except Exception:
            pass
        try:
            import subprocess
            out = subprocess.check_output('wmic computersystem get totalphysicalmemory', shell=True, stderr=subprocess.DEVNULL).decode()
            lines = [l.strip() for l in out.splitlines() if l.strip() and l.strip().isdigit()]
            if lines:
                return f'{round(int(lines[0]) / (1024**3), 1)} GB'
        except Exception:
            pass
        try:
            mem_bytes = os.sysconf('SC_PAGE_SIZE') * os.sysconf('SC_PHYS_PAGES')
            return f'{round(mem_bytes / (1024**3), 1)} GB'
        except Exception:
            pass
        return '未知'

    def get_cpu_info():
        """获取 CPU 型号、核心数"""
        cpu_model = '未知'
        cpu_cores = os.cpu_count() or 1  # 逻辑核心数（Python 内置，跨平台）

        # 获取 CPU 型号
        # Linux: /proc/cpuinfo，ARM 设备常见字段是 Hardware / Processor / Model
        try:
            cpuinfo = {}
            with open('/proc/cpuinfo') as f:
                for line in f:
                    if ':' not in line:
                        continue
                    key, value = line.split(':', 1)
                    key = key.strip().lower()
                    value = value.strip()
                    if value and key not in cpuinfo:
                        cpuinfo[key] = value
            for key in ('model name', 'hardware', 'processor', 'cpu model', 'model'):
                if cpuinfo.get(key):
                    cpu_model = cpuinfo[key]
                    break
        except Exception:
            pass

        # ARM 设备树里常能拿到板卡 / SoC 线索
        if cpu_model == '未知':
            for path in ('/proc/device-tree/model', '/sys/firmware/devicetree/base/model'):
                try:
                    with open(path, 'rb') as f:
                        value = f.read().decode('utf-8', errors='ignore').replace('\x00', '').strip()
                    if value:
                        cpu_model = value
                        break
                except Exception:
                    pass

        # lscpu 可补充 Vendor ID / Model name / BIOS Model name
        if cpu_model == '未知':
            try:
                import subprocess
                out = subprocess.check_output('lscpu', shell=True, stderr=subprocess.DEVNULL).decode()
                lscpu = {}
                for line in out.splitlines():
                    if ':' not in line:
                        continue
                    key, value = line.split(':', 1)
                    lscpu[key.strip().lower()] = value.strip()
                for key in ('model name', 'bios model name', 'vendor id'):
                    if lscpu.get(key):
                        cpu_model = lscpu[key]
                        break
            except Exception:
                pass

        # Windows: wmic
        if cpu_model == '未知':
            try:
                import subprocess
                out = subprocess.check_output('wmic cpu get Name', shell=True, stderr=subprocess.DEVNULL).decode()
                lines = [l.strip() for l in out.splitlines() if l.strip() and l.strip() != 'Name']
                if lines:
                    cpu_model = lines[0]
            except Exception:
                pass

        # 获取物理核心数（更准确）
        physical_cores = None
        try:
            import subprocess
            if platform.system() == 'Windows':
                out = subprocess.check_output('wmic cpu get NumberOfCores', shell=True, stderr=subprocess.DEVNULL).decode()
                lines = [int(l.strip()) for l in out.splitlines() if l.strip().isdigit()]
                if lines:
                    physical_cores = sum(lines)
            else:
                # Linux: lscpu
                out = subprocess.check_output('lscpu', shell=True, stderr=subprocess.DEVNULL).decode()
                for line in out.splitlines():
                    if line.startswith('Core(s) per socket:'):
                        per_socket = int(line.split(':')[1].strip())
                        sockets = 1
                        for l2 in out.splitlines():
                            if l2.startswith('Socket(s):'):
                                sockets = int(l2.split(':')[1].strip())
                        physical_cores = per_socket * sockets
                        break
        except Exception:
            pass

        if cpu_model == '未知' and (platform.machine() or '').lower() in ('arm64', 'aarch64', 'armv7l', 'armv8l'):
            cpu_model = f'ARM Platform ({platform.machine()})'

        return {
            'model': cpu_model,
            'logical_cores': cpu_cores,
            'physical_cores': physical_cores or cpu_cores,
        }

    def assess_performance(cpu_info, mem_str):
        """评估运行此应用是否吃力"""
        cores = cpu_info.get('logical_cores', 1)
        cpu_model = (cpu_info.get('model') or '').lower()
        # 解析内存（如 "3.7 GB" → 3.7）
        try:
            mem_gb = float(''.join(c for c in (mem_str or '0') if c.isdigit() or c == '.'))
        except Exception:
            mem_gb = 0

        legacy_cpu_keywords = (
            'athlon(tm) ii', 'athlon ii', 'phenom', 'sempron', 'turion',
            'core(tm)2', 'core 2', 'pentium(r) dual', 'pentium dual',
            'celeron(r) j1', 'celeron(r) n2', 'atom(tm)', 'atom ',
            'xeon(r) cpu e5-26', 'xeon(r) cpu e3-12'
        )
        is_legacy_cpu = any(k in cpu_model for k in legacy_cpu_keywords)
        arm_vendor_keywords = (
            'snapdragon', 'qualcomm', 'qcom', 'kryo', '骁龙',
            'amlogic', 'meson', '晶晨', 'mtk', 'mediatek', '联发科',
            'hisilicon', 'kirin', 'kunpeng', '海思', '麒麟', '鲲鹏',
            'phytium', '飞腾', 'unisoc', '紫光', '展锐', 'spreadtrum',
            'thead', 'xuantie', '平头哥', '玄铁',
            'rockchip', 'rk3', 'rk35', '瑞芯微', 'allwinner', 'sunxi', '全志'
        )
        strong_arm_keywords = ('kunpeng', '鲲鹏', 'phytium', '飞腾')
        mid_arm_keywords = ('snapdragon', 'qualcomm', 'qcom', 'kryo', '骁龙', 'kunpeng', '鲲鹏', 'phytium', '飞腾')
        weak_arm_keywords = (
            'amlogic', 'meson', '晶晨', 'allwinner', 'sunxi', '全志', 'rk3', 'rk35', 'rockchip', '瑞芯微',
            'mtk', 'mediatek', '联发科', 'hisilicon', 'kirin', '海思', '麒麟', 'unisoc', '紫光', '展锐', 'spreadtrum',
            'thead', 'xuantie', '平头哥', '玄铁'
        )
        machine = (platform.machine() or '').lower()
        is_arm = machine in ('arm64', 'aarch64', 'armv7l', 'armv8l') or any(k in cpu_model for k in arm_vendor_keywords)
        is_strong_arm = any(k in cpu_model for k in strong_arm_keywords)
        is_mid_arm = any(k in cpu_model for k in mid_arm_keywords)
        is_weak_arm = any(k in cpu_model for k in weak_arm_keywords)

        if is_legacy_cpu:
            if cores >= 4 and mem_gb >= 4:
                return {'level': '吃力', 'color': '#ef4444', 'desc': 'CPU 架构较老，基础功能可用，高并发任务会明显吃力'}
            return {'level': '吃力', 'color': '#ef4444', 'desc': 'CPU 与内存资源偏旧，建议减少并发任务'}

        if is_arm:
            if is_strong_arm and cores >= 8 and mem_gb >= 8:
                return {'level': '极速', 'color': '#10b981', 'desc': 'ARM 平台资源充足，多任务运行压力较小'}
            if is_mid_arm and cores >= 8 and mem_gb >= 6:
                return {'level': '流畅', 'color': '#3b82f6', 'desc': '中高端 ARM 平台可正常运行，并发任务建议适度控制'}
            if is_weak_arm:
                if cores >= 8 and mem_gb >= 4:
                    return {'level': '流畅', 'color': '#3b82f6', 'desc': 'ARM SoC 可正常运行，建议控制并发与后台任务'}
                return {'level': '吃力', 'color': '#ef4444', 'desc': '低功耗 ARM SoC 性能有限，建议减少并发任务'}
            if cores >= 8 and mem_gb >= 6:
                return {'level': '流畅', 'color': '#3b82f6', 'desc': 'ARM 平台可正常运行，并发任务建议适度控制'}
            return {'level': '吃力', 'color': '#ef4444', 'desc': 'ARM 平台资源偏紧，建议减少并发任务'}

        if cores >= 4 and mem_gb >= 4:
            return {'level': '极速', 'color': '#10b981', 'desc': '资源充足，多任务无压力'}
        elif cores >= 2 and mem_gb >= 2:
            return {'level': '流畅', 'color': '#3b82f6', 'desc': '可正常运行，并发任务稍慢'}
        else:
            return {'level': '吃力', 'color': '#ef4444', 'desc': '资源紧张，建议减少并发任务'}

    mem = get_mem()
    cpu_info = get_cpu_info()
    perf = assess_performance(cpu_info, mem)

    try:
        kernel = platform.release()
    except Exception:
        kernel = '未知'
    system_name = platform.system()
    if system_name == 'Linux' and '-trim' in (kernel or '').lower():
        os_version = '飞牛操作系统 fnOS'
    else:
        os_version = platform.version() if system_name == 'Windows' else f'{system_name} {kernel}'
    return jsonify({
        'success': True,
        'system': system_name,
        'architecture': platform.machine(),
        'os_version': os_version,
        'kernel': kernel,
        'memory': mem,
        'cpu': cpu_info,
        'performance': perf,
        'version': __version__
    })


# ==================== 存储年份 API ====================

@bp.route('/api/storage/scan', methods=['GET'])
def scan_storage_years():
    """扫描 文章/ 下所有年份子目录"""
    from crawler import get_article_base
    article_base = get_article_base()
    years = []
    try:
        print(f"[Storage Scan] 扫描目录: {article_base}")
        print(f"[Storage Scan] 目录存在: {os.path.isdir(article_base)}")
        if os.path.isdir(article_base):
            all_entries = os.listdir(article_base)
            print(f"[Storage Scan] 目录下共 {len(all_entries)} 个条目: {all_entries}")
            for name in all_entries:
                full = os.path.join(article_base, name)
                is_dir = os.path.isdir(full)
                # 支持纯数字年份 "2026" 也支持带"年"字 "2026年"
                year_val = name.rstrip('年')
                is_year_dir = is_dir and year_val.isdigit() and len(year_val) == 4
                print(f"[Storage Scan]   {name} | isdir={is_dir} | is_year={is_year_dir}")
                if is_year_dir:
                    sub_entries = os.listdir(full)
                    count = sum(1 for f in sub_entries if os.path.isdir(os.path.join(full, f)))
                    print(f"[Storage Scan]   年份 {year_val} → {len(sub_entries)} 条目, {count} 个子目录")
                    years.append({'year': year_val, 'month_count': count})
        years.sort(key=lambda y: y['year'], reverse=True)
        print(f"[Storage Scan] 结果: {years}")
    except Exception as e:
        import traceback
        print(f"[Storage Scan] 扫描年份失败: {e}")
        traceback.print_exc()
    from werss.config import cfg
    return jsonify({'success': True, 'years': years, 'current': cfg.get('storage_year', '')})

@bp.route('/api/storage/save', methods=['POST'])
def save_storage_year():
    """保存存储年份"""
    from werss.config import cfg
    data = request.get_json()
    year = str(data.get('year', '')).strip()
    cfg.set('storage_year', year)
    cfg.save()
    return jsonify({'success': True, 'year': year})


@bp.route('/api/storage/base_dir', methods=['GET'])
def get_storage_base_dir():
    """读取自定义存储位置（storage.base_dir，空 = 默认「exe 旁/文章」）"""
    from werss.config import cfg
    return jsonify({'success': True, 'base_dir': cfg.get('storage.base_dir', '') or ''})


@bp.route('/api/storage/base_dir', methods=['POST'])
def save_storage_base_dir():
    """保存自定义存储位置。传入的路径留空则回到默认；目录不存在会自动创建。"""
    from werss.config import cfg
    from crawler import get_article_base
    data = request.get_json() or {}
    custom = str(data.get('base_dir', '')).strip()
    if custom:
        if not os.path.isabs(custom):
            return jsonify({'success': False, 'error': '请填写完整路径（如 D:\\文章库）'}), 400
        try:
            test_root = os.path.abspath(os.path.join(custom, '文章'))
            os.makedirs(test_root, exist_ok=True)
            if not os.path.isdir(test_root):
                raise OSError('目录无法创建')
        except Exception as e:
            return jsonify({'success': False, 'error': f'路径不可用: {e}'}), 400
    cfg.set('storage.base_dir', custom)
    cfg.save()
    return jsonify({'success': True, 'base_dir': custom,
                    'article_base': get_article_base()})


# ==================== 在线更新 API ====================

# Gitee 在线更新源（只读检查：只提示新版本并给出下载地址，不执行任何拉取/覆盖）
# 采用公开 Release 附件方案：release.bat 把 version.json 和 exe zip 传成附件。
# 注意：Gitee 对 api/v5 的匿名请求有限制（403），因此解析 releases 网页拿附件直链。
GITEE_RELEASES_PAGE = "https://gitee.com/AZSongguo/wcan/releases"


def _check_online_version():
    """读 Gitee 最新 Release 页面的 version.json 附件，与当前版本比较。

    任何失败（网络、无 Release、无附件）都静默降级为 None，不影响主流程。
    """
    import requests as _rq
    try:
        H = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        page = _rq.get(GITEE_RELEASES_PAGE, timeout=8, headers=H)
        if page.status_code != 200:
            return None
        # 取第一个（最新）Release 的 version.json 附件直链
        links = re.findall(r'href="(/AZSongguo/wcan/releases/download/[^"]+)"', page.text)
        meta_path = next((l for l in links if l.endswith('/version.json')), None)
        zip_path = next((l for l in links if l.endswith('.zip')), None)
        if not meta_path:
            return None
        meta = _rq.get('https://gitee.com' + meta_path, timeout=8, headers=H)
        if meta.status_code != 200:
            return None
        data = meta.json()
        latest = str(data.get('version', '')).strip()
        if not latest:
            return None
        has_new = parse_version(latest.lstrip('vV')) > parse_version(__version__)
        return {
            'version': latest,
            'notes': data.get('notes') or '',
            'url': ('https://gitee.com' + zip_path) if zip_path else GITEE_RELEASES_PAGE,
            'has_new': has_new,
        }
    except Exception:
        return None


@bp.route('/api/update/check', methods=['GET'])
def check_update():
    update_dir = get_update_dir()
    current_ver = parse_version(__version__)
    available = []
    message = ''
    # 1) 本地离线更新包（原有机制）
    if os.path.isdir(update_dir):
        try:
            for entry in os.listdir(update_dir):
                entry_path = os.path.join(update_dir, entry)
                if not os.path.isdir(entry_path):
                    continue
                m = re.match(r'WCAN[_\-\s]*v([\d]+[\.\d]*(?:[a-zA-Z]*[\d]*))\s*[_\-\s]*update', entry, re.IGNORECASE)
                if not m:
                    continue
                ver_str = m.group(1)
                ver = parse_version(ver_str)
                if ver > current_ver:
                    available.append({
                        'version': 'v' + ver_str,
                        'folder': entry,
                        'path': entry_path
                    })
            available.sort(key=lambda x: parse_version(x['version']), reverse=True)
        except Exception as e:
            return jsonify({'success': False, 'error': str(e), 'current_version': __version__})
    else:
        message = '未配置离线更新目录'

    # 2) Gitee 在线源（只读：仅提示新版本并给出下载地址）
    online = _check_online_version()
    return jsonify({
        'success': True,
        'current_version': __version__,
        'available': available,
        'message': message,
        'online': online,
    })

@bp.route('/api/update/do', methods=['POST'])
@require_auth
def do_update():
    global update_progress
    if update_progress.get("running"):
        return jsonify({'success': False, 'error': '已有更新任务正在进行'})
    data = request.get_json() or {}
    folder = data.get('folder', '')
    update_dir = get_update_dir()
    if not folder:
        return jsonify({'success': False, 'error': '未指定更新包'})
    src = os.path.join(update_dir, folder)
    if not os.path.isdir(src):
        return jsonify({'success': False, 'error': f'更新包不存在: {folder}'})

    update_progress = {"running": True, "pct": 0, "step": "正在校验更新包...", "done": False, "result": None, "logs": [], "folder": folder, "target_ver": ""}

    def _run():
        global update_progress
        base_dir = DATA_DIR
        dst = base_dir
        try:
            all_files = []
            for root, dirs, files in os.walk(src):
                rel = os.path.relpath(root, src)
                if rel == ".":
                    rel = ""
                for f in files:
                    rel_path = (rel + "/" + f).lstrip("/").replace("\\", "/")
                    if rel_path.startswith("data/") or rel_path == "config.yaml" or rel_path == "notify_config.json" or rel_path == "webdav_config.json" or rel_path.startswith("文章/"):
                        continue
                    all_files.append((os.path.join(root, f), os.path.join(dst, rel, f) if rel else os.path.join(dst, f)))
            total = len(all_files)
            if total == 0:
                with _status_lock:
                    update_progress = {"running": False, "pct": 100, "step": "更新完成", "done": True, "result": {"success": True, "total": 0, "copied": 0, "message": "无需更新"}, "logs": ["没有需要更新的文件"], "folder": folder, "target_ver": ""}
                return

            copied = 0
            skipped = 0
            with _status_lock:
                update_progress["step"] = "正在复制文件..."
            for i, (src_file, dst_file) in enumerate(all_files):
                pct = int((i / total) * 92)
                fname = os.path.basename(src_file)
                os.makedirs(os.path.dirname(dst_file), exist_ok=True)
                try:
                    with open(src_file, 'rb') as s:
                        with open(dst_file, 'wb') as d:
                            d.write(s.read())
                    copied += 1
                    with _status_lock:
                        update_progress["logs"].append(f"✓ {fname}")
                except Exception:
                    skipped += 1
                    with _status_lock:
                        update_progress["logs"].append(f"✗ 跳过 {fname}")
                with _status_lock:
                    update_progress["pct"] = pct
                    update_progress["step"] = f"正在复制文件... ({i+1}/{total})"

            with _status_lock:
                update_progress["pct"] = 95
                update_progress["step"] = "正在校验完整性..."
                update_progress["logs"].append(f"共 {total} 个文件, 成功 {copied}, 跳过 {skipped}, 已保留 data/、config.yaml、notify_config.json、webdav_config.json")

            restart_script = os.path.join(dst, "_restart.bat")
            with open(restart_script, 'w', encoding='utf-8') as f:
                f.write('@echo off\n')
                f.write(f'cd /d "{dst}"\n')
                f.write('timeout /t 2 /nobreak >nul\n')
                f.write('python run.py\n')

            is_docker = os.path.exists('/.dockerenv') or 'docker' in (os.environ.get('container', '') or '').lower()
            container_name = os.environ.get('HOSTNAME', '')
            if is_docker and container_name:
                restart_cmd = f'docker restart {container_name}'
            elif is_docker:
                restart_cmd = 'docker restart <容器名>'
            else:
                restart_cmd = 'python run.py'

            with _status_lock:
                update_progress["logs"].append(f"重启命令: {restart_cmd}")
                if is_docker and container_name:
                    update_progress["logs"].append(f"已计划自动重启容器: {container_name}")
                elif is_docker:
                    update_progress["logs"].append("提示: 未识别容器名，无法自动重启，请手动执行 docker restart <容器名>")

            msg = f'已更新 {copied} 个文件'
            if skipped > 0:
                msg += f'，跳过 {skipped} 项'
            msg += '。data/、config.yaml、notify_config.json、webdav_config.json、文章/ 已保留。'
            if is_docker and container_name:
                msg += f'\n容器 {container_name} 将自动重启'
            elif is_docker:
                msg += '\n未识别容器名，请手动重启 Docker 容器'
            else:
                msg += '\n请重启应用'
            with _status_lock:
                old_logs = list(update_progress["logs"])
                update_progress = {"running": False, "pct": 100, "step": "更新完成，准备重启", "done": True, "result": {"success": True, "total": total, "copied": copied, "skipped": skipped, "message": msg, "restart_cmd": restart_cmd, "is_docker": is_docker, "auto_restart": bool(is_docker and container_name)}, "logs": old_logs, "folder": folder, "target_ver": ""}

            if is_docker and container_name:
                _schedule_container_restart(container_name)
        except Exception as e:
            with _status_lock:
                update_progress["logs"].append(f"✗ 错误: {e}")
                old_logs = list(update_progress["logs"])
                update_progress = {"running": False, "pct": 0, "step": "更新失败", "done": True, "result": {"success": False, "error": str(e)}, "logs": old_logs, "folder": folder, "target_ver": ""}

    _safe_thread(_run)
    return jsonify({'success': True, 'message': '更新任务已启动'})

@bp.route('/api/update/progress', methods=['GET'])
def update_progress_status():
    with _status_lock:
        result = {'success': True}
        result.update(update_progress)
    return jsonify(result)

@bp.route('/api/restart', methods=['POST'])
@require_auth
def restart_app():
    def _exit():
        time.sleep(1)
        os._exit(0)
    threading.Thread(target=_exit, daemon=True).start()
    return jsonify({'success': True, 'message': '应用正在退出...'})


@bp.route('/api/changelog', methods=['GET'])
def api_changelog():
    folder = request.args.get('folder', '')
    if folder:
        update_dir = get_update_dir()
        changelog_path = os.path.join(update_dir, folder, 'templates', 'changelog.html')
    else:
        changelog_path = os.path.join(bundle_dir(), 'templates', 'changelog.html')
    try:
        with open(changelog_path, 'r', encoding='utf-8') as f:
            html = f.read()
        return jsonify({'success': True, 'html': html})
    except FileNotFoundError:
        return jsonify({'success': False, 'html': '<p style="color:var(--wc-text-secondary);text-align:center;padding:20px;">暂无更新日志</p>'})
    except Exception as e:
        return jsonify({'success': False, 'html': f'<p style="color:#fa5151;">读取更新日志失败: {e}</p>'})


@bp.route('/api/future-plan', methods=['GET'])
def api_future_plan():
    plan_path = os.path.join(bundle_dir(), 'templates', 'future_plan.html')
    try:
        with open(plan_path, 'r', encoding='utf-8') as f:
            html = f.read()
        return jsonify({'success': True, 'html': html})
    except FileNotFoundError:
        return jsonify({'success': False, 'html': '<p style="color:var(--wc-text-secondary);text-align:center;padding:20px;">暂无未来更新计划</p>'})
    except Exception as e:
        return jsonify({'success': False, 'html': f'<p style="color:#fa5151;">读取未来更新计划失败: {e}</p>'})


# ==================== 一言 API ====================

@bp.route('/api/yiyan', methods=['GET'])
def api_yiyan():
    result = jsonify(_compute_yiyan())
    result.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    return result


def _compute_yiyan():
    """计算今日一言，返回 dict（供 /api/yiyan 和 /api/poll 复用）"""
    today_md = get_bjt_now().strftime('%m.%d')
    if today_md in _YIYAN_DISABLE_DATES:
        return {'success': True, 'text': '', 'disabled': True}

    yiyan_path = get_yiyan_path()
    try:
        with open(yiyan_path, 'r', encoding='utf-8') as f:
            raw = [l.strip() for l in f.readlines() if l.strip()]
    except FileNotFoundError:
        return {'success': True, 'text': '今日无事'}
    except Exception as e:
        return {'success': False, 'text': f'读取失败: {e}'}

    if not raw:
        return {'success': True, 'text': '今日无事'}

    import random

    announcements = []
    date_items = {}
    normal = []

    for line in raw:
        m = re.match(r'^\[公告\]\s*(.+)', line)
        if m:
            announcements.append(m.group(1).strip())
            continue
        m = re.match(r'^\[(\d{2})\.(\d{2})\]\s*(.+)', line)
        if m:
            key = f'{m.group(1)}.{m.group(2)}'
            text = m.group(3).strip()
            if key not in date_items:
                date_items[key] = []
            date_items[key].append(text)
            continue
        normal.append(line)

    if announcements:
        idx = int(time.time() / 86400) % len(announcements)
        return {'success': True, 'text': announcements[idx], 'source': 'announcement'}

    today = get_bjt_now().strftime('%m.%d')
    if today in date_items:
        items = date_items[today]
        if len(items) == 1:
            text = items[0]
        else:
            with _status_lock:
                if today not in _yiyan_state["date_cache"] or not _yiyan_state["date_cache"][today]:
                    shuffled = list(items)
                    random.shuffle(shuffled)
                    _yiyan_state["date_cache"][today] = shuffled
                pool = _yiyan_state["date_cache"][today]
                text = pool.pop(0)
        return {'success': True, 'text': text, 'source': 'date'}

    if normal:
        with _status_lock:
            if not _yiyan_state["normal"]:
                _yiyan_state["normal"] = list(normal)
                random.shuffle(_yiyan_state["normal"])
                _yiyan_state["normal_idx"] = 0
            text = _yiyan_state["normal"][_yiyan_state["normal_idx"]]
            _yiyan_state["normal_idx"] += 1
            if _yiyan_state["normal_idx"] >= len(_yiyan_state["normal"]):
                _yiyan_state["normal"] = list(normal)
                random.shuffle(_yiyan_state["normal"])
                _yiyan_state["normal_idx"] = 0
        return {'success': True, 'text': text, 'source': 'normal'}

    return {'success': True, 'text': '今日无事'}
