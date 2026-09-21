"""
基础测试用例 —— 验证核心工具函数的正确性。
运行: pytest tests/ -v
"""
import json
import os
import tempfile
import pytest


class TestLoadJson:
    """测试 JSON 安全加载工具函数"""

    def test_load_valid_json(self):
        from app.core import _load_json
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False, encoding='utf-8') as f:
            json.dump({"key": "value"}, f)
            f.flush()
            path = f.name
        try:
            result = _load_json(path, default={})
            assert result == {"key": "value"}
        finally:
            os.unlink(path)

    def test_load_missing_file_returns_default(self):
        from app.core import _load_json
        result = _load_json("/nonexistent/path/file.json", default={"default": True})
        assert result == {"default": True}

    def test_load_invalid_json_returns_default(self):
        from app.core import _load_json
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False, encoding='utf-8') as f:
            f.write("{invalid json content")
            f.flush()
            path = f.name
        try:
            result = _load_json(path, default=None)
            assert result is None
        finally:
            os.unlink(path)


class TestNotifyTypes:
    """测试通知类型插件注册"""

    def test_default_notify_types_exist(self):
        from app.routes_notify import NOTIFY_TYPES
        assert 'rss_expiry' in NOTIFY_TYPES
        assert 'task_reminder' in NOTIFY_TYPES
        assert 'error_reminder' in NOTIFY_TYPES

    def test_register_notify_type(self):
        from app.routes_notify import NOTIFY_TYPES, register_notify_type
        original = list(NOTIFY_TYPES)
        try:
            register_notify_type('test_type')
            assert 'test_type' in NOTIFY_TYPES
        finally:
            # 清理：恢复原状
            if 'test_type' in NOTIFY_TYPES:
                NOTIFY_TYPES.remove('test_type')

    def test_register_duplicate_noop(self):
        from app.routes_notify import NOTIFY_TYPES, register_notify_type
        original_len = len(NOTIFY_TYPES)
        register_notify_type('rss_expiry')  # 已存在
        assert len(NOTIFY_TYPES) == original_len
