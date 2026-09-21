import os
import sys
import re
import shutil

BASE = os.path.dirname(os.path.abspath(__file__))

SKIP_PREFIX = [
    "data/", "__pycache__/", ".dbg/", "update/", "x86+arm/",
    "原/", "we-mp-rss-1.5.2/",
]

SKIP_FILES = {
    "config.yaml", "notify_config.json", "webdav_config.json",
    "crawl_history.json", "history.json", "rss_feeds.json",
    "docker-compose.yml", "build_update.py", "debug-illegal-seek-progress.md",
    "weixin.jpg", "weixin.png", ".dockerignore", "pip.conf",
}


def get_version():
    v = None
    try:
        with open(os.path.join(BASE, "app", "core.py"), encoding="utf-8") as f:
            for line in f:
                m = re.search(r'__version__\s*=\s*"([^"]+)"', line)
                if m:
                    v = m.group(1)
                    break
    except Exception:
        pass
    return v or "0.0.0"


def should_skip(rel):
    rel = rel.replace("\\", "/")
    for p in SKIP_PREFIX:
        if rel.startswith(p + "/") or rel == p.rstrip("/"):
            return True
    name = os.path.basename(rel)
    if name in SKIP_FILES:
        return True
    if name.endswith(".pyc"):
        return True
    return False


def build():
    ver = get_version()
    out_dir = os.path.join(BASE, "update", f"WCAN_v{ver}_update")
    os.makedirs(out_dir, exist_ok=True)

    copied = 0
    for root, dirs, files in os.walk(BASE):
        dirs[:] = [d for d in dirs if not d.startswith("__pycache__") and d not in (".dbg", "update", "x86+arm", "原", "we-mp-rss-1.5.2")]
        for f in files:
            src = os.path.join(root, f)
            rel = os.path.relpath(src, BASE)
            if should_skip(rel):
                continue
            dst = os.path.join(out_dir, rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src, dst)
            copied += 1
            print(f"  ✓ {rel}")

    print(f"\n更新包已生成: {out_dir}")
    print(f"共 {copied} 个文件")
    print(f"\n部署步骤:")
    print(f"  1. 将 update/WCAN_v{ver}_update 整个文件夹复制到 NAS 的 update/ 目录下")
    print(f"  2. 在网页后台 → 关于 → 检查更新 → 一键更新")
    print(f"  3. 更新完成后 docker restart <容器名>")
    return out_dir


if __name__ == "__main__":
    build()
