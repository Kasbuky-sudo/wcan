#!/bin/bash
# ============================================
#  编舟文心 容器启动脚本
#  每次启动自动检查并安装缺失的 pip 依赖，
#  改 requirements.txt 后只需重启容器无需 rebuild。
# ============================================
set -e

echo "[Entrypoint] 检查 Python 依赖..."

# pip 镜像加速（阿里云 → 清华 → 华为 → 官方）
pip install --no-cache-dir \
    -i https://mirrors.aliyun.com/pypi/simple/ \
    --extra-index-url https://pypi.tuna.tsinghua.edu.cn/simple/ \
    -r /app/requirements.txt 2>/dev/null || \
pip install --no-cache-dir \
    -i https://pypi.tuna.tsinghua.edu.cn/simple/ \
    -r /app/requirements.txt 2>/dev/null || \
pip install --no-cache-dir \
    -i https://mirrors.huaweicloud.com/pypi/simple/ \
    -r /app/requirements.txt 2>/dev/null || \
pip install --no-cache-dir \
    -r /app/requirements.txt

echo "[Entrypoint] 依赖就绪"

# 自动同步 config.yaml 中的 version 字段为 app/core.py 中的 __version__
# 这样用户升级后无需手动修改 config.yaml
python -c "
import re, os, sys
sys.path.insert(0, '/app')
try:
    from app.core import __version__
    cfg_path = '/app/config.yaml'
    if os.path.exists(cfg_path):
        with open(cfg_path, 'r', encoding='utf-8') as f:
            content = f.read()
        new_content = re.sub(r'^version:\s*[\"\x27]?[\d.]+[\"\x27]?', f'version: \"{__version__}\"', content, count=1, flags=re.MULTILINE)
        if new_content != content:
            with open(cfg_path, 'w', encoding='utf-8') as f:
                f.write(new_content)
            print(f'[Config] config.yaml 版本号已自动同步为 {__version__}')
        else:
            print(f'[Config] config.yaml 版本号已是 {__version__}，无需更新')
except Exception as e:
    print(f'[Config] 版本号同步跳过（非致命）: {e}')
" 2>/dev/null || true

# 数据库迁移：自动升级到最新版本
# 对于已有数据库（通过 create_all 创建过表但无 alembic_version 表），
# 先 stamp 标记当前版本，再 upgrade 应用增量迁移。
echo "[Entrypoint] 检查数据库迁移..."
python -c "
import sqlite3, os, sys
db_path = 'data/articles.db'
if not os.path.exists(db_path):
    print('[Migrate] 数据库不存在，将由应用自动创建')
    sys.exit(0)
try:
    conn = sqlite3.connect(db_path)
    tables = [r[0] for r in conn.execute(\"SELECT name FROM sqlite_master WHERE type='table'\").fetchall()]
    conn.close()
    if 'articles' in tables and 'alembic_version' not in tables:
        print('[Migrate] 检测到已有数据库但无迁移版本表，执行 stamp head')
        os.system('alembic stamp head')
except Exception as e:
    print(f'[Migrate] 检查失败（非致命）: {e}')
" 2>/dev/null || true
alembic upgrade head 2>/dev/null && echo "[Entrypoint] 数据库迁移完成" || echo "[Entrypoint] 数据库迁移跳过（非致命）"

# 启动应用
exec python /app/run.py
