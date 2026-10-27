"""토큰 캐시와 발급 한도 재시도를 가짜 응답으로 검증한다 (키움 접속 없음). python -m kiwoom.test_token"""
import json
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from kiwoom.client import KST, KiwoomClient, KiwoomError

OK = {"return_code": 0, "return_msg": "정상", "token": "T1", "expires_dt": "20991231235959"}
OK2 = {**OK, "token": "T2"}
RATE = {"return_code": 5, "return_msg": "허용된 요청 개수를 초과하였습니다[1700:허용된 API 요청 개수를 초과하였습니다. 유량=au10001, API ID={1}]"}
BAD = {"return_code": 3, "return_msg": "인증에 실패했습니다[8001:App Key와 Secret Key 검증에 실패했습니다]"}


class Resp:
    def __init__(self, data, status=200):
        self.status_code, self._d, self.content = status, data, json.dumps(data).encode()

    def json(self):
        return self._d


class Sess:
    def __init__(self, *responses):
        self.left, self.calls = [Resp(r) if isinstance(r, dict) else r for r in responses], 0

    def post(self, *a, **k):
        self.calls += 1
        return self.left.pop(0)


def client(tmp, sess, appkey="a"):
    KiwoomClient.TOKEN_DIR = Path(tmp)
    c = KiwoomClient(mode="demo", appkey=appkey, secret="b")
    c.sess = sess
    return c


def sleeps():
    rec = []
    return rec, patch("kiwoom.client.time.sleep", lambda s: rec.append(s))


# 1) 한 번 발급하면 새 프로세스 (새 클라이언트) 는 디스크 캐시를 써서 발급 API 를 부르지 않는다
with tempfile.TemporaryDirectory() as t:
    c1 = client(t, Sess(OK))
    assert c1.token() == "T1" and c1.sess.calls == 1
    c2 = client(t, Sess())
    assert c2.token() == "T1" and c2.sess.calls == 0
    assert (Path(t) / ".kiwoom_token_demo.json").stat().st_mode & 0o077 == 0  # 본인만 읽는다

# 2) 발급 한도 (1700) 에 두 번 걸린 뒤 성공 -> 2초 4초 기다리고 3번째에 받는다
with tempfile.TemporaryDirectory() as t:
    rec, p = sleeps()
    with p:
        c = client(t, Sess(RATE, RATE, OK))
        assert c.token() == "T1" and c.sess.calls == 3
    assert rec == [2, 4], rec

# 3) 끝까지 한도면 1700 으로 실패한다 (6번 시도 5번 대기)
with tempfile.TemporaryDirectory() as t:
    rec, p = sleeps()
    with p:
        c = client(t, Sess(*[RATE] * 6))
        try:
            c.token()
            raise AssertionError("실패해야 한다")
        except KiwoomError as e:
            assert e.code == 1700, e.code
    assert rec == [2, 4, 8, 16, 30] and c.sess.calls == 6

# 4) 키 오류 (8001) 는 재시도 없이 바로 실패하고 캐시를 만들지 않는다
with tempfile.TemporaryDirectory() as t:
    c = client(t, Sess(Resp(BAD, 400)))
    try:
        c.token()
        raise AssertionError("실패해야 한다")
    except KiwoomError as e:
        assert "8001" in str(e) and c.sess.calls == 1
    assert not (Path(t) / ".kiwoom_token_demo.json").exists()

# 5) 키가 바뀌면 예전 캐시를 쓰지 않는다
with tempfile.TemporaryDirectory() as t:
    client(t, Sess(OK)).token()
    c = client(t, Sess(OK2), appkey="other")
    assert c.token() == "T2" and c.sess.calls == 1

# 6) 만료 10분 전 캐시는 버리고 새로 발급한다
with tempfile.TemporaryDirectory() as t:
    c = client(t, Sess(OK2))
    c._write_cache("OLD", datetime.now(KST) + timedelta(minutes=5))
    assert c.token() == "T2" and c.sess.calls == 1

# 7) 인증 오류로 토큰을 버리면 디스크 캐시도 같이 지워진다
with tempfile.TemporaryDirectory() as t:
    c = client(t, Sess(OK))
    c.token()
    c._drop_cache()
    assert c._token is None and not (Path(t) / ".kiwoom_token_demo.json").exists()

print("모든 테스트 통과")
