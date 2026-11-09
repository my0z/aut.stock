"""카톡 끔 스위치 검증 (네트워크 없음). python -m notify.test_kakao"""
import os
from unittest.mock import patch

from notify import kakao


class Resp:
    status_code = 200

    def json(self):
        return {"result_code": 0}


def run(mute, **kw):
    """KAKAO_MUTE 를 mute 로 두고 send 를 부른다. 반환: (send 결과, 실제 post 횟수)."""
    posts = []
    with patch.dict(os.environ):
        os.environ.pop("KAKAO_MUTE", None)
        if mute is not None:
            os.environ["KAKAO_MUTE"] = mute
        with patch.object(kakao, "access_token", lambda: "tok"), \
                patch.object(kakao.requests, "post", lambda *a, **k: posts.append(a) or Resp()):
            ok = kakao.send("[daytrade] 11/09 매수\n인벤테라 5380", **kw)
    return ok, len(posts)


assert run(None) == (False, 0), "기본은 꺼짐이어야 한다"
for v in ("1", "true", "", " ON ", "garbage"):
    assert run(v) == (False, 0), v
for v in ("0", "false", "No", " off "):
    assert run(v) == (True, 1), v
assert run(None, force=True) == (True, 1), "수동 테스트 (force) 는 항상 보낸다"
print("카톡 스위치 테스트 통과")
