"""
核心模块测试 —— 覆盖加密、鉴权、日期解析、关键词提取等关键工具函数。
运行: pytest tests/ -v
"""
import os
import sys
import time
import tempfile
from unittest.mock import patch, MagicMock

import pytest


# ====================== app.py 加密与鉴权 ======================

class TestCryptoSecret:
    """测试敏感字段加密/解密"""

    def test_encrypt_decrypt_roundtrip(self):
        """加密后解密应还原原值"""
        from app.core import _encrypt_secret, _decrypt_secret
        cases = ["", "hello", "P@ssw0rd!", "中文密码", "a" * 100, "secret with spaces"]
        for plaintext in cases:
            if not plaintext:
                assert _encrypt_secret(plaintext) == ''
                assert _decrypt_secret('') == ''
                continue
            encrypted = _encrypt_secret(plaintext)
            assert encrypted.startswith('enc:')
            assert _decrypt_secret(encrypted) == plaintext

    def test_encrypt_not_equal_plaintext(self):
        """加密结果不应等于明文"""
        from app.core import _encrypt_secret
        encrypted = _encrypt_secret("mypassword")
        assert encrypted != "mypassword"
        assert encrypted.startswith('enc:')

    def test_decrypt_invalid_base64_returns_empty(self):
        """解密非法 base64 返回空字符串"""
        from app.core import _decrypt_secret
        assert _decrypt_secret('enc:not-valid-base64!!!') == ''

    def test_decrypt_non_enc_prefix_returns_as_is(self):
        """无 enc: 前缀的字符串视为明文原样返回（向后兼容）"""
        from app.core import _decrypt_secret
        assert _decrypt_secret('plaintext_password') == 'plaintext_password'
        assert _decrypt_secret('') == ''

    def test_encrypt_empty_returns_empty(self):
        """空值加密返回空字符串"""
        from app.core import _encrypt_secret
        assert _encrypt_secret('') == ''
        assert _encrypt_secret(None) == ''


class TestAdminPassword:
    """测试管理员密码验证"""

    def test_correct_password(self):
        """正确密码返回 True"""
        from app.core import _verify_admin_password
        with patch.dict(os.environ, {'WCAN_ADMIN_PWD': 'correct_pwd'}):
            assert _verify_admin_password('correct_pwd') is True

    def test_wrong_password(self):
        """错误密码返回 False"""
        from app.core import _verify_admin_password
        with patch.dict(os.environ, {'WCAN_ADMIN_PWD': 'correct_pwd'}):
            assert _verify_admin_password('wrong_pwd') is False

    def test_empty_password(self):
        """空密码返回 False"""
        from app.core import _verify_admin_password
        with patch.dict(os.environ, {'WCAN_ADMIN_PWD': 'correct_pwd'}):
            assert _verify_admin_password('') is False
            assert _verify_admin_password(None) is False

    def test_no_admin_pwd_configured(self):
        """未配置管理员密码时返回 False"""
        from app.core import _verify_admin_password
        import werss.config
        # 清除环境变量，mock config 返回空
        with patch.dict(os.environ, {}, clear=True):
            with patch.object(werss.config.cfg, 'get', return_value=''):
                assert _verify_admin_password('anything') is False

    def test_compare_digest_used(self):
        """验证使用 hmac.compare_digest（非常量时间差，仅验证功能正确）"""
        from app.core import _verify_admin_password
        with patch.dict(os.environ, {'WCAN_ADMIN_PWD': 'secret123'}):
            # 不同长度的密码都应返回 False，不抛异常
            assert _verify_admin_password('a') is False
            assert _verify_admin_password('a' * 1000) is False


class TestAuthToken:
    """测试 auth token 签发与验证"""

    def test_issue_and_verify_token(self):
        """签发的 token 能通过验证"""
        from app.core import _issue_auth_token, _verify_auth_token, _auth_tokens
        # 清空已有 token
        with patch.dict(_auth_tokens, {}, clear=True):
            token = _issue_auth_token()
            assert token
            assert isinstance(token, str)
            assert _verify_auth_token(token) is True

    def test_verify_empty_token(self):
        """空 token 验证失败"""
        from app.core import _verify_auth_token
        assert _verify_auth_token('') is False
        assert _verify_auth_token(None) is False

    def test_verify_invalid_token(self):
        """随机字符串无法通过验证"""
        from app.core import _verify_auth_token, _auth_tokens
        with patch.dict(_auth_tokens, {}, clear=True):
            assert _verify_auth_token('invalid_token_xyz') is False

    def test_expired_token_rejected(self):
        """过期 token 验证失败并被清理"""
        from app.core import _issue_auth_token, _verify_auth_token, _auth_tokens, _AUTH_TOKEN_TTL
        with patch.dict(_auth_tokens, {}, clear=True):
            token = _issue_auth_token()
            # 模拟过期：将 expiry 设为过去
            with patch.dict(_auth_tokens, {token: time.time() - 1}):
                assert _verify_auth_token(token) is False
                # 过期 token 应被删除
                assert token not in _auth_tokens

    def test_issue_token_cleans_expired(self):
        """签发新 token 时清理过期 token"""
        from app.core import _issue_auth_token, _auth_tokens
        # 预置一个过期 token
        expired_token = 'expired_token_xxx'
        with patch.dict(_auth_tokens, {expired_token: time.time() - 100}, clear=True):
            new_token = _issue_auth_token()
            # 过期 token 应被清理
            assert expired_token not in _auth_tokens
            # 新 token 应存在
            assert new_token in _auth_tokens


# ====================== crawler.py 日期解析 ======================

class TestParseDateFromText:
    """测试日期文本解析"""

    def setup_method(self):
        from crawler import WeChatCrawler
        self.crawler = WeChatCrawler()

    def test_empty_input(self):
        """空输入返回 None"""
        assert self.crawler.parse_date_from_text('') is None
        assert self.crawler.parse_date_from_text(None) is None

    def test_chinese_date_format(self):
        """中文日期格式"""
        result = self.crawler.parse_date_from_text('2026年6月15日')
        assert result is not None
        assert result.year == 2026
        assert result.month == 6
        assert result.day == 15

    def test_iso_date_format(self):
        """ISO 日期格式"""
        result = self.crawler.parse_date_from_text('2026-06-15')
        assert result is not None
        assert result.year == 2026
        assert result.month == 6
        assert result.day == 15

    def test_slash_date_format(self):
        """斜杠日期格式"""
        result = self.crawler.parse_date_from_text('2026/06/15')
        assert result is not None
        assert result.year == 2026

    def test_dot_date_format(self):
        """点号日期格式"""
        result = self.crawler.parse_date_from_text('2026.06.15')
        assert result is not None
        assert result.year == 2026

    def test_datetime_format(self):
        """日期时间格式"""
        result = self.crawler.parse_date_from_text('2026-06-15 10:30:00')
        assert result is not None
        assert result.hour == 10
        assert result.minute == 30

    def test_timestamp_seconds(self):
        """秒级时间戳"""
        # 2026-06-15 00:00:00 UTC 的时间戳
        result = self.crawler.parse_date_from_text('1750032000')
        assert result is not None

    def test_timestamp_milliseconds(self):
        """毫秒级时间戳"""
        result = self.crawler.parse_date_from_text('1750032000000')
        assert result is not None

    def test_invalid_input(self):
        """无效输入返回 None"""
        assert self.crawler.parse_date_from_text('not a date') is None
        assert self.crawler.parse_date_from_text('abc123') is None


# ====================== app.py 状态锁线程安全 ======================

class TestThreadSafety:
    """测试全局状态锁的基本功能"""

    def test_status_lock_is_reentrant(self):
        """_status_lock 是 RLock，可重入"""
        from app.core import _status_lock
        import threading
        assert isinstance(_status_lock, type(threading.RLock()))

    def test_auth_lock_exists(self):
        """_auth_lock 存在且为 Lock 类型"""
        from app.core import _auth_lock
        import threading
        assert isinstance(_auth_lock, type(threading.Lock()))

    def test_auth_token_concurrent_issue(self):
        """并发签发 token 不冲突"""
        from app.core import _issue_auth_token, _verify_auth_token, _auth_tokens
        import threading

        tokens = []
        with patch.dict(_auth_tokens, {}, clear=True):
            def issue_one():
                t = _issue_auth_token()
                tokens.append(t)

            threads = [threading.Thread(target=issue_one) for _ in range(5)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            # 5 个 token 都应唯一且有效
            assert len(tokens) == 5
            assert len(set(tokens)) == 5
            for token in tokens:
                assert _verify_auth_token(token) is True
