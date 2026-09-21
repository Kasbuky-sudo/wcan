"""手动冒烟脚本：验证每次点击「获取登录二维码」都会拿到一张全新的二维码，
并且被顶替的旧扫码轮询会自动退出。需要联网（要访问 mp.weixin.qq.com）。

    python tests/smoke_qr_refresh.py

用临时目录做 CWD + WCAN_HOME，不会污染真实的 static/ 和 data/。
不是 pytest 测试（文件名不符合 test_*.py），只手动跑。
"""
import os
import sys
import time
import hashlib
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

tmp = tempfile.mkdtemp(prefix="wcan_qr_smoke_")
os.environ["WCAN_HOME"] = tmp
os.chdir(tmp)
os.makedirs("static", exist_ok=True)
os.makedirs("data", exist_ok=True)

from app import create_app  # noqa: E402

app = create_app()
client = app.test_client()
QR = os.path.join(tmp, "static", "wx_qrcode.png")
LOCK = os.path.join(tmp, "data", "lock.lock")


def snapshot():
    if not os.path.exists(QR):
        return None, 0, None
    with open(QR, "rb") as f:
        raw = f.read()
    return hashlib.md5(raw).hexdigest()[:12], len(raw), raw[:4]


def click(tag):
    r = client.post("/api/auth/qrcode")
    body = r.get_json(silent=True) or {}
    md5, size, magic = snapshot()
    print(f"[{tag}] http={r.status_code} success={body.get('success')} "
          f"code_url={body.get('code_url')} msg={body.get('msg') or body.get('error')}")
    print(f"[{tag}] qr file: md5={md5} size={size} magic={magic} lock={os.path.exists(LOCK)}")
    return md5


import threading  # noqa: E402

from werss.driver.wx_api import WeChat_api  # noqa: E402

# 记录每次轮询用的是哪一代 uuid，用来确认旧轮询有没有自己退出
poll_calls = []
_orig_check = WeChat_api._check_login_status


def _spy_check(uuid):
    poll_calls.append(uuid)
    return _orig_check(uuid)


WeChat_api._check_login_status = _spy_check

print("=== 连续点击 3 次，每次都必须是一张新二维码 ===")
seen = []
gens = []
for i in (1, 2, 3):
    seen.append(click(f"click-{i}"))
    gens.append(WeChat_api._login_check_uuid)
    time.sleep(3)

distinct = len({m for m in seen if m})
print(f"\n结果: {distinct} 张不同二维码 / 3 次点击（本次实际给了这 3 张码）")

poll_calls.clear()
time.sleep(6)
still_polling = set(poll_calls)
print(f"最后一次点击后仍在轮询的代次: {len(still_polling)} 个")
print(f"  最新代次 uuid : {gens[-1]}")
print(f"  仍在轮询的 uuid: {sorted(still_polling)}")
print(f"  存活线程: {[t.name for t in threading.enumerate()]}")

ok = distinct == 3
if ok and still_polling and still_polling <= {gens[-1]}:
    print("PASS — 每次点击都拿到新码；旧轮询已自动退出，只剩最新一代在等扫码")
else:
    if not ok:
        print(f"FAIL — 出现了重复二维码: {seen}")
    else:
        print("FAIL — 旧代次轮询没有退出，或最新代次已停止轮询")
    sys.exit(1)
