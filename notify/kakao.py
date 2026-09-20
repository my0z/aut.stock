"""카카오톡 '나에게 보내기' 알림.

환경변수
- KAKAO_REST_KEY        카카오 개발자 앱의 REST API 키
- KAKAO_CLIENT_SECRET   플랫폼 키 > 클라이언트 시크릿 (카카오 로그인) 이 활성화돼 있으면 필요
- KAKAO_TOKEN_FILE 토큰 저장 파일 (기본 ~/.kakao_token.json)

최초 1회 인증:
    python -m notify.kakao auth        # 안내대로 브라우저에서 로그인 후 code 붙여넣기
테스트:
    python -m notify.kakao send "테스트"
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
from pathlib import Path

import requests

log = logging.getLogger("kakao")
REDIRECT_URI = "https://localhost/kakao"
TOKEN_FILE = Path(os.environ.get("KAKAO_TOKEN_FILE", Path.home() / ".kakao_token.json"))
MAX_TEXT = 200  # 텍스트 템플릿 글자 제한


def _rest_key() -> str:
    k = os.environ.get("KAKAO_REST_KEY", "")
    if not k:
        raise RuntimeError("KAKAO_REST_KEY 환경변수가 없다")
    return k


def _secret() -> dict:
    sec = os.environ.get("KAKAO_CLIENT_SECRET", "")
    return {"client_secret": sec} if sec else {}


def _load() -> dict:
    if TOKEN_FILE.exists():
        return json.loads(TOKEN_FILE.read_text())
    return {}


def _save(tok: dict) -> None:
    TOKEN_FILE.write_text(json.dumps(tok, ensure_ascii=False))
    TOKEN_FILE.chmod(0o600)


def auth_url() -> str:
    return ("https://kauth.kakao.com/oauth/authorize?response_type=code"
            f"&client_id={_rest_key()}&redirect_uri={REDIRECT_URI}&scope=talk_message")


def exchange_code(code: str) -> dict:
    r = requests.post("https://kauth.kakao.com/oauth/token", data={
        "grant_type": "authorization_code", "client_id": _rest_key(),
        "redirect_uri": REDIRECT_URI, "code": code, **_secret(),
    }, timeout=30)
    data = r.json()
    if "access_token" not in data:
        raise RuntimeError(f"토큰 발급 실패: {data}")
    data["obtained_at"] = time.time()
    _save(data)
    return data


def access_token() -> str:
    tok = _load()
    if not tok:
        raise RuntimeError("카카오 토큰이 없다. python -m notify.kakao auth 를 먼저 실행한다")
    age = time.time() - tok.get("obtained_at", 0)
    if age < tok.get("expires_in", 21600) - 300:
        return tok["access_token"]
    r = requests.post("https://kauth.kakao.com/oauth/token", data={
        "grant_type": "refresh_token", "client_id": _rest_key(), "refresh_token": tok["refresh_token"], **_secret(),
    }, timeout=30)
    data = r.json()
    if "access_token" not in data:
        raise RuntimeError(f"토큰 갱신 실패 (재인증 필요): {data}")
    tok.update(data)  # refresh_token 은 만료 임박 시에만 새로 온다
    tok["obtained_at"] = time.time()
    _save(tok)
    return tok["access_token"]


def unlink() -> None:
    """앱 연결 해제. 동의항목을 다시 받고 싶을 때 쓴다."""
    tok = _load()
    if tok:
        r = requests.post("https://kapi.kakao.com/v1/user/unlink",
                          headers={"Authorization": f"Bearer {tok['access_token']}"}, timeout=30)
        print("unlink:", r.status_code, r.text[:100])
    if TOKEN_FILE.exists():
        TOKEN_FILE.unlink()


def send(text: str, url: str | None = None) -> bool:
    """긴 글은 200자 단위로 나눠 보낸다. 실패해도 예외 대신 False."""
    try:
        token = access_token()
        chunks = _chunk(text)
        for c in chunks:
            tpl = {"object_type": "text", "text": c, "link": {"web_url": url or "https://finance.naver.com"}}
            r = requests.post("https://kapi.kakao.com/v2/api/talk/memo/default/send",
                              headers={"Authorization": f"Bearer {token}"},
                              data={"template_object": json.dumps(tpl, ensure_ascii=False)}, timeout=30)
            if r.status_code != 200 or r.json().get("result_code") != 0:
                log.warning("카톡 전송 실패: %s %s", r.status_code, r.text[:200])
                return False
        return True
    except Exception as e:  # noqa: BLE001
        log.warning("카톡 전송 오류: %s", e)
        return False


def _chunk(text: str) -> list[str]:
    out, cur = [], ""
    for line in text.split("\n"):
        while len(line) > MAX_TEXT:
            out.append(line[:MAX_TEXT]); line = line[MAX_TEXT:]
        if len(cur) + len(line) + 1 > MAX_TEXT:
            out.append(cur); cur = line
        else:
            cur = line if not cur else cur + "\n" + line
    if cur:
        out.append(cur)
    return out or [""]


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    if len(sys.argv) < 2 or sys.argv[1] not in ("auth", "send", "unlink"):
        print(__doc__); sys.exit(1)
    if sys.argv[1] == "unlink":
        unlink()
        return
    if sys.argv[1] == "auth":
        print("1) 아래 주소를 브라우저에서 열고 카카오 로그인 후 '카카오톡 메시지 전송' 체크박스를 켜고 '동의하고 계속하기'\n")
        print(auth_url())
        print(f"\n2) 브라우저가 {REDIRECT_URI}?code=XXXX 로 이동한다 (페이지는 안 열려도 된다)")
        code = input("3) 주소창의 code= 뒤 값을 붙여넣기: ").strip()
        exchange_code(code)
        print(f"저장 완료: {TOKEN_FILE}")
        print("전송 테스트:", send("aut.stock 카톡 알림 연결 완료"))
    else:
        print(send(" ".join(sys.argv[2:]) or "테스트"))


if __name__ == "__main__":
    main()
