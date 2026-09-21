# SONGJUNSONG (School of Finance and Economics / Jilin Business and Technology College)
"""鉴权路由 — 管理员登录 + 微信扫码授权"""
import os
import time
from flask import Blueprint, request, jsonify
from .core import *
from .core import (
    _verify_admin_password,
    _issue_auth_token,
    _verify_auth_token,
    _extract_auth_token,
    _auth_tokens,
    _AUTH_TOKEN_TTL,
)

bp = Blueprint('auth', __name__)


def get_token_expiry():
    try:
        from werss.driver.token import wx_cfg
        from werss.driver.wx_api import WeChat_api
        token_data = wx_cfg.get("token_data", None)
        if not token_data:
            return None
        expiry = token_data.get("expiry", {})
        expiry_timestamp = expiry.get("expiry_timestamp")
        if not expiry_timestamp:
            return None
        if not WeChat_api.HasLogin():
            return None
        now = time.time()
        remaining = max(0, expiry_timestamp - now)
        return {
            "expiry_timestamp": expiry_timestamp,
            "expiry_time": expiry.get("expiry_time", time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(expiry_timestamp))),
            "remaining_seconds": int(remaining),
        }
    except Exception:
        return None


# ==================== 管理员登录 ====================

@bp.route('/api/auth/login', methods=['POST'])
def auth_login():
    """管理员登录，返回 token"""
    data = request.get_json(silent=True) or {}
    pwd = data.get('password', '')
    if _verify_admin_password(pwd):
        token = _issue_auth_token()
        return jsonify({'success': True, 'token': token, 'expires_in': _AUTH_TOKEN_TTL})
    return jsonify({'success': False, 'message': '密码错误'}), 401

@bp.route('/api/auth/status', methods=['GET'])
def auth_status():
    """检查当前是否已登录"""
    return jsonify({'authenticated': _verify_auth_token(_extract_auth_token())})

@bp.route('/api/auth/logout', methods=['POST'])
def auth_logout():
    """登出，销毁 token"""
    token = _extract_auth_token()
    _auth_tokens.pop(token, None)
    return jsonify({'success': True})


# ==================== 微信扫码授权 ====================

@bp.route('/api/auth/qrcode', methods=['POST'])
def get_auth_qrcode():
    try:
        from werss.driver.wx_api import WeChat_api
        # 用户每点一次按钮都强制拿一张新二维码，不复用磁盘上残留的旧图
        result = WeChat_api.get_qr_code(force=True)
        if result and os.path.exists(WeChat_api.qr_code_path):
            code_url = f"/static/wx_qrcode.png?t={int(time.time())}"
            return jsonify({
                'success': True,
                'code_url': code_url,
                'is_exists': True,
                'msg': result.get('msg', '请使用微信扫描二维码登录')
            })
        return jsonify({'success': True, 'code_url': None, 'is_exists': False, 'msg': result.get('msg', '获取二维码失败') if result else '正在获取二维码...'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@bp.route('/api/wx-auth/status', methods=['GET'])
def get_auth_status():
    try:
        from werss.driver.wx_api import WeChat_api
        has_qr = os.path.exists(WeChat_api.qr_code_path)
        is_login = WeChat_api.HasLogin()
        has_token = bool(WeChat_api.token)
        debug_log('INFO', 'rss_auth', f'授权状态: 登录={is_login}, 有token={has_token}, 有二维码={has_qr}')
        return jsonify({
            'success': True,
            'has_qr': has_qr,
            'is_login': is_login,
            'has_token': has_token
        })
    except Exception as e:
        debug_log('ERROR', 'rss_auth', f'获取授权状态失败: {e}')
        return jsonify({'success': False, 'error': str(e)})

@bp.route('/api/auth/expiry', methods=['GET'])
def get_auth_expiry():
    expiry_info = get_token_expiry()
    if not expiry_info or not expiry_info.get("expiry_timestamp"):
        return jsonify({"authorized": False, "message": "未授权，请扫码登录"})
    now = time.time()
    remaining = max(0, expiry_info["expiry_timestamp"] - now)
    expired = remaining <= 0
    hours = int(remaining // 3600)
    minutes = int((remaining % 3600) // 60)
    return jsonify({
        "authorized": True,
        "expired": expired,
        "expiry_time": expiry_info["expiry_time"],
        "remaining_seconds": int(remaining),
        "remaining_text": f"{hours}小时{minutes}分钟"
    })
