"""
pytest 配置文件。
将项目根目录加入 sys.path，使测试能直接 import 项目模块。
"""
import sys
import os

# 项目根目录
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)
