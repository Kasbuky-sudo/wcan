import os
import sys
import re
import shutil

BASE = os.path.dirname(os.path.abspath(__file__))

SKIP_PREFIX = [
    "data/", "__pycache__/", ".dbg/", "update/", "x86+arm/",
    "原/", "we-mp-rss-1.5.2/",
    # 开发产物和用户数据不能进更新包（.git 和 dist 动辄上百 MB，文章/ 是用户内容）
    ".git/", "dist/", "build/", "tests/", "文章/", "node_modules/",
    ".venv/", "venv/", ".idea/", ".vscode/", ".pytest_cache/",
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
    skip_dirs = {p.rstrip("/") for p in SKIP_PREFIX}
    for root, dirs, files in os.walk(BASE):
        dirs[:] = [d for d in dirs if d not in skip_dirs and not d.startswith("__pycache__")]
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
    print(f"\n用法:")
    print(f"  A. 在线：把 dist/WCAN_v{ver}_update.zip 传成 Release 附件，应用内「检查更新 → 一键更新」自动拉取覆盖")
    print(f"  B. 手动：把 update/WCAN_v{ver}_update 整个文件夹放进目标的 update/ 目录")
    print(f"     然后 网页后台 → 关于 → 检查更新 → 开始更新 → 重启")
    return out_dir


if __name__ == "__main__":
    build()
