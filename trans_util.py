from functools import lru_cache
import requests
from .setup import P, logger


def splittext(text: str, limit: int = 1500):
    splits, acc = [], 0
    for line in text.splitlines():
        cnt = len(line)
        if acc + cnt > limit:
            yield "\n".join(splits)
            splits, acc = [], 0
        acc += cnt
        splits.append(line)
    yield "\n".join(splits)


class TransUtil:
    @classmethod
    def trans_google_web2(cls, text: str, **kwargs):
        try:
            return "\n".join(cls.__trans_google_web2(t, **kwargs) for t in splittext(text))
        except Exception:
            logger.exception("구글 WEB v2를 이용해 번역 중 예외! 원문을 반환합니다:", text)
            return text

    @classmethod
    def __trans_google_web2(cls, text: str, source: str = "ja", target: str = "ko"):
        url = "https://translate.google.com/translate_a/single"
        headers = {"User-Agent": "GoogleTranslate/6.27.0.08.415126308 (Linux; U; Android 7.1.2; PIXEL 2 XL)"}
        params = {
            "q": text,
            "sl": source,
            "tl": target,
            "hl": "ko-KR",
            "ie": "UTF-8",
            "oe": "UTF-8",
            "client": "at",
            "dt": ("t", "ld", "qca", "rm", "bd", "md", "ss", "ex", "sos"),
        }
        res = requests.get(url, params=params, headers=headers, timeout=30).json()
        return "".join(sentences[0] for sentences in res[0][:-1])

    @classmethod
    def __trans(cls, *args, **kwargs):
        """to override SystemLogicTrans"""
        return cls.trans_google_web2(*args, **kwargs)

    @classmethod
    @lru_cache(maxsize=100)
    def __trans_with_cache(cls, text):
        return cls.__trans(text, source="ja", target="ko")

    @classmethod
    def trans(cls, text, **kwargs):
        if kwargs == {"source": "ja", "target": "ko"}:
            return cls.__trans_with_cache(text)
        return cls.__trans(text, **kwargs)
