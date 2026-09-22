# © SONGJUNSONG · Jilin Business and Technology College · School of Finance and Economics
"""系统管理、在线更新、一言路由"""
import os
import sys
import shutil
import subprocess
import tempfile
import zipfile
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
# 在线更新走两个源：GitHub 为主（公开仓库的 Release API 允许匿名读，直接拿资产直链），
# Gitee 为备（api/v5 匿名请求 403，只能解析 releases 网页）。任一个拿到就不再问下一个。
GH_OWNER, GH_REPO = 'Kasbuky-sudo', 'wcan'
GITEE_OWNER, GITEE_REPO = 'AZSongguo', 'wcan'
GH_API = f"https://api.github.com/repos/{GH_OWNER}/{GH_REPO}"
GITEE_RELEASES_PAGE = f"https://gitee.com/{GITEE_OWNER}/{GITEE_REPO}/releases"
_ONLINE_UA = {'User-Agent': 'WCAN-Updater/1.0'}


def _is_source_pkg(name: str) -> bool:
    """源码更新包（给源码/Docker 部署用），别和 exe 的 zip 混了"""
    return name.endswith('_update.zip')


def _pick_assets(assets: dict) -> dict:
    """{文件名: 直链} → version.json / exe zip / 源码更新包 三个直链"""
    return {
        'meta_url': next((u for n, u in assets.items() if n == 'version.json'), None),
        'zip_url': next((u for n, u in assets.items() if n.endswith('.zip') and not _is_source_pkg(n)), None),
        'pkg_url': next((u for n, u in assets.items() if _is_source_pkg(n)), None),
    }


def _online_payload(source, version, notes, urls, page_url):
    """把两个源的差异抹平成一个结构，前端只认这几个字段"""
    version = str(version or '').strip().lstrip('vV')
    if not version:
        return None
    has_new = parse_version(version) > parse_version(__version__)
    # exe 部署换 exe，源码/Docker 部署覆盖源码文件——各自需要不同的资产
    need = urls['zip_url'] if is_frozen() else urls['pkg_url']
    return {
        'version': version,
        'notes': notes or '',
        'url': urls['zip_url'] or page_url,
        'zip_url': urls['zip_url'],
        'pkg_url': urls['pkg_url'],
        'source': source,
        'source_name': 'GitHub' if source == 'github' else 'Gitee',
        'page_url': page_url,
        'has_new': has_new,
        'can_self_update': bool(has_new and need),
        'self_update_kind': ('exe' if is_frozen() else 'source') if need else None,
    }


def _check_online_github():
    """读 GitHub 最新 Release（公开仓库匿名可读）。任何失败都返回 None。"""
    import requests as _rq
    try:
        r = _rq.get(f"{GH_API}/releases/latest", timeout=8,
                    headers={**_ONLINE_UA, 'Accept': 'application/vnd.github+json'})
        if r.status_code != 200:
            return None
        rel = r.json() or {}
        tag = str(rel.get('tag_name') or '').strip()
        if not tag:
            return None
        assets = {}
        for a in rel.get('assets') or []:
            name = a.get('name') or ''
            url = a.get('browser_download_url')
            if name and url:
                assets[name] = url
        urls = _pick_assets(assets)
        meta = {}
        if urls['meta_url']:
            m = _rq.get(urls['meta_url'], timeout=8, headers=_ONLINE_UA)
            if m.status_code == 200:
                meta = m.json() or {}
        body = (rel.get('body') or '').strip()
        notes = meta.get('notes') or (body.splitlines()[0] if body else '')
        return _online_payload('github', meta.get('version') or tag, notes, urls,
                               rel.get('html_url') or GITEE_RELEASES_PAGE)
    except Exception:
        return None


def _check_online_gitee():
    """读 Gitee 最新 Release 页面。任何失败都返回 None。"""
    import requests as _rq
    try:
        page = _rq.get(GITEE_RELEASES_PAGE, timeout=8, headers=_ONLINE_UA)
        if page.status_code != 200:
            return None
        links = re.findall(r'href="(/%s/%s/releases/download/[^"]+)"' % (GITEE_OWNER, GITEE_REPO), page.text)
        # 附件按 Release 从新到旧排列，同名只认第一个（最新的那个）
        assets = {}
        for l in links:
            assets.setdefault(l.rsplit('/', 1)[-1], 'https://gitee.com' + l)
        urls = _pick_assets(assets)
        if not urls['meta_url']:
            return None
        meta = _rq.get(urls['meta_url'], timeout=8, headers=_ONLINE_UA)
        if meta.status_code != 200:
            return None
        data = meta.json() or {}
        return _online_payload('gitee', data.get('version'), data.get('notes'), urls, GITEE_RELEASES_PAGE)
    except Exception:
        return None


def _check_online_version():
    """GitHub 优先，失败退回 Gitee；都失败返回 None（静默降级，不影响主流程）"""
    return _check_online_github() or _check_online_gitee()


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

def _apply_source_tree(src, folder='', target_ver='', lo=0, hi=92):
    """把更新包 src 里的文件覆盖到运行目录，进度映射到 [lo, hi] 段。

    data/、config.yaml、notify_config.json、webdav_config.json、文章/ 一律保留（那是用户数据）。
    只负责复制，不管重启；返回 (total, copied, skipped)。
    """
    global update_progress
    dst = DATA_DIR
    all_files = []
    for root, dirs, files in os.walk(src):
        dirs[:] = [d for d in dirs if d != '__pycache__']
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
            old_logs = list(update_progress["logs"])
            update_progress = {"running": False, "pct": 100, "step": "更新完成", "done": True, "result": {"success": True, "total": 0, "copied": 0, "message": "无需更新"}, "logs": old_logs + ["没有需要更新的文件"], "folder": folder, "target_ver": target_ver}
        return 0, 0, 0

    copied = 0
    skipped = 0
    span = max(1, hi - lo)
    with _status_lock:
        update_progress["step"] = "正在复制文件..."
    for i, (src_file, dst_file) in enumerate(all_files):
        pct = int(lo + (i / total) * span)
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
        update_progress["pct"] = hi
        update_progress["step"] = "正在校验完整性..."
        update_progress["logs"].append(f"共 {total} 个文件, 成功 {copied}, 跳过 {skipped}, 已保留 data/、config.yaml、notify_config.json、webdav_config.json")
    return total, copied, skipped


def _finish_source_update(res, folder='', target_ver='', note='', auto_exit=False):
    """源码覆盖跑完后的收尾：写重启脚本、算重启命令、落最终状态、重启

    auto_exit=True 且被启动器托管（WCAN_SUPERVISED）时，自己退出让启动器用新代码拉起来；
    Docker 走容器重启；其余情况提示用户手动重启。
    """
    global update_progress
    total, copied, skipped = res
    dst = DATA_DIR
    try:
        with open(os.path.join(dst, "_restart.bat"), 'w', encoding='utf-8') as f:
            f.write('@echo off\n')
            f.write(f'cd /d "{dst}"\n')
            f.write('timeout /t 2 /nobreak >nul\n')
            f.write('python run.py\n')
    except Exception:
        pass

    is_docker = os.path.exists('/.dockerenv') or 'docker' in (os.environ.get('container', '') or '').lower()
    container_name = os.environ.get('HOSTNAME', '')
    supervised = bool(os.environ.get('WCAN_SUPERVISED'))
    if is_docker and container_name:
        restart_cmd = f'docker restart {container_name}'
    elif is_docker:
        restart_cmd = 'docker restart <容器名>'
    else:
        restart_cmd = 'python run.py'
    will_auto_exit = auto_exit and not is_docker and supervised

    with _status_lock:
        update_progress["logs"].append(f"重启命令: {restart_cmd}")
        if is_docker and container_name:
            update_progress["logs"].append(f"已计划自动重启容器: {container_name}")
        elif is_docker:
            update_progress["logs"].append("提示: 未识别容器名，无法自动重启，请手动执行 docker restart <容器名>")
        elif will_auto_exit:
            update_progress["logs"].append("已计划自动重启服务")

    msg = note + f'已更新 {copied} 个文件'
    if skipped > 0:
        msg += f'，跳过 {skipped} 项'
    msg += '。data/、config.yaml、notify_config.json、webdav_config.json、文章/ 已保留。'
    if is_docker and container_name:
        msg += f'\n容器 {container_name} 将自动重启'
    elif is_docker:
        msg += '\n未识别容器名，请手动重启 Docker 容器'
    elif will_auto_exit:
        msg += '\n服务正在自动重启，几秒后刷新页面即可'
    else:
        msg += '\n请重启应用'
    with _status_lock:
        old_logs = list(update_progress["logs"])
        update_progress = {"running": False, "pct": 100, "step": "更新完成，准备重启", "done": True, "result": {"success": True, "total": total, "copied": copied, "skipped": skipped, "message": msg, "restart_cmd": restart_cmd, "is_docker": is_docker, "auto_restart": bool((is_docker and container_name) or will_auto_exit)}, "logs": old_logs, "folder": folder, "target_ver": target_ver}

    if is_docker and container_name:
        _schedule_container_restart(container_name)
    elif will_auto_exit:
        def _bye():
            time.sleep(4)   # 留点时间让前端把最终状态取走
            os._exit(0)
        threading.Thread(target=_bye, daemon=True).start()


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
        try:
            res = _apply_source_tree(src, folder=folder)
            _finish_source_update(res, folder=folder)
        except Exception as e:
            with _status_lock:
                update_progress["logs"].append(f"✗ 错误: {e}")
                old_logs = list(update_progress["logs"])
                update_progress = {"running": False, "pct": 0, "step": "更新失败", "done": True, "result": {"success": False, "error": str(e)}, "logs": old_logs, "folder": folder, "target_ver": ""}

    _safe_thread(_run)
    return jsonify({'success': True, 'message': '更新任务已启动'})


# ==================== 一键在线更新 ====================

def _set_progress(pct=None, step=None):
    with _status_lock:
        if pct is not None:
            update_progress["pct"] = pct
        if step is not None:
            update_progress["step"] = step


def _add_log(line):
    with _status_lock:
        update_progress["logs"].append(line)


def _download_file(url, dst, lo=0, hi=50):
    """流式下载文件，把进度映射到 [lo, hi] 段，返回字节数"""
    import requests as _rq
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    got = 0
    with _rq.get(url, stream=True, timeout=(10, 600), headers=_ONLINE_UA) as r:
        r.raise_for_status()
        total = int(r.headers.get('Content-Length') or 0)
        with open(dst, 'wb') as f:
            for chunk in r.iter_content(chunk_size=1 << 20):
                if not chunk:
                    continue
                f.write(chunk)
                got += len(chunk)
                mb = got // 1048576
                if total:
                    _set_progress(pct=int(lo + (hi - lo) * got / total), step=f"正在下载新版本... {mb}/{total // 1048576} MB")
                else:
                    _set_progress(step=f"正在下载新版本... {mb} MB")
    return got


def _extract_exe_from_zip(zip_path, want_name, out_path):
    """从发布 zip 里取出 exe（优先同名，否则取第一个 exe 条目）"""
    with zipfile.ZipFile(zip_path) as z:
        names = [n for n in z.namelist() if n.lower().endswith('.exe')]
        if not names:
            raise RuntimeError('更新包里没有找到 exe')
        target = next((n for n in names if os.path.basename(n).lower() == want_name.lower()), names[0])
        with z.open(target) as s, open(out_path, 'wb') as d:
            shutil.copyfileobj(s, d, 1 << 20)
    return out_path


def _verify_new_exe(path):
    """下载完整性兜底：体积和 PE 文件头都对得上才允许替换"""
    size = os.path.getsize(path)
    if size < 20 * 1024 * 1024:
        raise RuntimeError(f'下载的程序体积异常（{size} 字节），已中止替换')
    with open(path, 'rb') as f:
        if f.read(2) != b'MZ':
            raise RuntimeError('下载的文件不是 Windows 可执行文件，已中止替换')
    return size


def _write_swap_script(app_exe, new_exe, log_path):
    """生成替换脚本：结束旧进程 → 用新文件覆盖 → 重新启动。

    本进程自己也占着 exe 文件句柄，不退出就换不掉，所以必须交给独立脚本做。
    exe 名和路径都是中文，按 GBK + CRLF 写，cmd 才认得。
    """
    exe_name = os.path.basename(app_exe)
    lines = [
        '@echo off',
        'chcp 936 >nul',
        f'set "APP={app_exe}"',
        f'set "NEW={new_exe}"',
        f'set "LOG={log_path}"',
        'echo [%date% %time%] 开始应用更新 >>"%LOG%"',
        'set /a N=0',
        ':swap',
        'set /a N+=1',
        'if %N% GTR 60 goto fail',
        f'taskkill /F /IM "{exe_name}" >nul 2>&1',
        'ping -n 2 127.0.0.1 >nul',
        'move /y "%NEW%" "%APP%" >nul 2>&1',
        'if errorlevel 1 goto swap',
        'echo [%date% %time%] 替换成功 >>"%LOG%"',
        'start "" "%APP%"',
        'exit /b 0',
        ':fail',
        'echo [%date% %time%] 替换失败：文件仍被占用 >>"%LOG%"',
        'exit /b 1',
    ]
    path = os.path.join(tempfile.gettempdir(), f'wcan_swap_{int(time.time())}.bat')
    with open(path, 'w', encoding='gbk', newline='\r\n') as f:
        f.write('\n'.join(lines) + '\n')
    return path


def _spawn_detached(bat_path):
    """脱离父进程启动替换脚本，本进程退出后它照样跑"""
    flags = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    return subprocess.Popen(['cmd', '/c', bat_path], creationflags=flags,
                            close_fds=True, cwd=tempfile.gettempdir())


def _run_online_exe(info):
    """exe 部署：下载 → 解出 exe → 生成替换脚本 → 本进程退出，由脚本换文件并重启"""
    global update_progress
    app_exe = sys.executable
    work = os.path.join(tempfile.gettempdir(), 'wcan_update')
    os.makedirs(work, exist_ok=True)
    zip_path = os.path.join(work, 'new_release.zip')
    new_exe = app_exe + '.new'
    if os.path.exists(new_exe):
        try:
            os.remove(new_exe)
        except Exception:
            pass

    got = _download_file(info['zip_url'], zip_path, 1, 80)
    _add_log(f"已下载 {got // 1048576} MB")
    _set_progress(step="正在解压新版本...", pct=85)
    _extract_exe_from_zip(zip_path, os.path.basename(app_exe), new_exe)
    size = _verify_new_exe(new_exe)
    _add_log(f"新版本程序校验通过（{size // 1048576} MB）")

    _set_progress(step="正在准备替换程序...", pct=92)
    log_path = os.path.join(DATA_DIR, 'data', 'update_apply.log')
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    bat = _write_swap_script(app_exe, new_exe, log_path)
    _add_log(f"替换脚本已生成: {bat}")
    _spawn_detached(bat)
    _add_log("程序即将退出，由替换脚本接管")

    with _status_lock:
        old_logs = list(update_progress["logs"])
        update_progress = {"running": False, "pct": 100, "step": "正在自动替换并重启", "done": True,
                           "result": {"success": True, "total": 0, "copied": 0, "skipped": 0,
                                      "message": f"v{info['version']} 已下载完成，程序会自动关闭，几秒后以新版本重新打开。\n若没有自动打开，手动双击一次程序即可。",
                                      "restart_cmd": "自动替换并重启", "is_docker": False, "auto_restart": True},
                           "logs": old_logs, "folder": "", "target_ver": info['version']}
    time.sleep(3)   # 留点时间让前端把最后状态取走
    os._exit(0)


def _run_online_source(info):
    """源码/Docker 部署：下载源码更新包 → 覆盖文件 → 重启"""
    update_dir = get_update_dir()
    os.makedirs(update_dir, exist_ok=True)
    ver = str(info['version']).lstrip('vV')
    folder = f"WCAN_v{ver}_update"
    dst_dir = os.path.join(update_dir, folder)
    zip_path = os.path.join(update_dir, folder + '.zip')

    got = _download_file(info['pkg_url'], zip_path, 1, 35)
    _add_log(f"更新包已下载（{max(1, got // 1024)} KB）")
    _set_progress(step="正在解压更新包...", pct=40)

    if os.path.isdir(dst_dir):
        shutil.rmtree(dst_dir, ignore_errors=True)
    with zipfile.ZipFile(zip_path) as z:
        z.extractall(update_dir)
    if not os.path.isdir(dst_dir):
        # 压缩包多套一层目录时兜一下
        for d in sorted(os.listdir(update_dir)):
            cand = os.path.join(update_dir, d)
            if os.path.isdir(cand) and os.path.exists(os.path.join(cand, 'app', 'core.py')):
                dst_dir = cand
                break
    if not os.path.isdir(dst_dir):
        raise RuntimeError('更新包解压后没有找到有效的目录结构')

    name = os.path.basename(dst_dir)
    with _status_lock:
        update_progress["folder"] = name
    res = _apply_source_tree(dst_dir, folder=name, target_ver=ver, lo=42, hi=92)
    _finish_source_update(res, folder=name, target_ver=ver, note='已从线上下载更新包。', auto_exit=True)


def _run_online_update(info):
    try:
        if info.get('self_update_kind') == 'exe':
            _run_online_exe(info)
        else:
            _run_online_source(info)
    except Exception as e:
        with _status_lock:
            update_progress["logs"].append(f"✗ 错误: {e}")
            old_logs = list(update_progress["logs"])
            update_progress = {"running": False, "pct": 0, "step": "更新失败", "done": True, "result": {"success": False, "error": str(e)}, "logs": old_logs, "folder": "", "target_ver": ""}


@bp.route('/api/update/online', methods=['POST'])
@require_auth
def do_online_update():
    """一键在线更新：exe 部署自动替换重启，源码/Docker 部署下载更新包覆盖"""
    global update_progress
    if update_progress.get("running"):
        return jsonify({'success': False, 'error': '已有更新任务正在进行'})
    info = _check_online_version()
    if not info:
        return jsonify({'success': False, 'error': '获取在线版本失败，请检查网络'})
    if not info.get('has_new'):
        return jsonify({'success': False, 'error': f"当前已是最新版本（v{__version__}）"})
    if not info.get('can_self_update'):
        return jsonify({'success': False, 'error': f"v{info['version']} 没有适用于当前部署方式的更新包，请手动下载"})

    update_progress = {"running": True, "pct": 0, "step": f"正在准备更新到 v{info['version']}...", "done": False,
                       "result": None, "logs": [f"来源: {info.get('source_name')}", f"目标版本: v{info['version']}"],
                       "folder": "", "target_ver": info['version']}
    _safe_thread(_run_online_update, (info,))
    return jsonify({'success': True, 'version': info['version'], 'source': info.get('source_name'),
                    'kind': info.get('self_update_kind'), 'message': '更新任务已启动'})

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
