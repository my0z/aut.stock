"""키움 REST API 경량 클라이언트 (Python 3.10+).

공식 저장소 github.com/Kiwoom-Securities/Kiwoom-REST-API 의 사양을 따르되
keyring 등 무거운 의존성 없이 requests + websockets 만 쓴다.
"""
from .client import KiwoomClient, KiwoomError
from .stream import TradeStream

__all__ = ["KiwoomClient", "KiwoomError", "TradeStream"]
