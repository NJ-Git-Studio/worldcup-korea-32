"""실제 북메이커 배당 연동 (The Odds API).

- h2h(승/무/패) 배당을 여러 북메이커에서 받아 마진 제거(de-vig) 후 평균.
- 무료 키(월 500요청) 보호를 위해 디스크 캐시 + TTL(기본 6시간).
- 키는 환경변수 ODDS_API_KEY 또는 gitignore된 odds_api_key.txt 에서만 읽는다.
  (절대 소스에 하드코딩하지 않음)

get_match_odds(matches) -> {match_id: (p_home, p_draw, p_away)}
배당이 없거나 키가 없으면 빈 dict 반환 → 전력 레이팅 모델로 폴백.
"""
from __future__ import annotations

import json
import os
import ssl
import time
import urllib.request

from .teams import to_korean

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
CACHE = os.path.join(_ROOT, "cache", "odds_cache.json")
KEY_FILE = os.path.join(_ROOT, "odds_api_key.txt")

SPORT_KEY = "soccer_fifa_world_cup"
ODDS_URL = (
    "https://api.the-odds-api.com/v4/sports/{sport}/odds/"
    "?apiKey={key}&regions={regions}&markets=h2h&oddsFormat=decimal"
)
ODDS_TTL = int(os.environ.get("ODDS_TTL", str(6 * 3600)))   # 기본 6시간
REGIONS = os.environ.get("ODDS_REGIONS", "eu,uk")

_SSL = ssl.create_default_context()
_SSL.check_hostname = False
_SSL.verify_mode = ssl.CERT_NONE


def api_key() -> str | None:
    k = os.environ.get("ODDS_API_KEY")
    if k and k.strip():
        return k.strip()
    if os.path.exists(KEY_FILE):
        try:
            v = open(KEY_FILE, encoding="utf-8").read().strip()
            return v or None
        except Exception:
            return None
    return None


def _devig(prices: dict) -> dict | None:
    """{outcome: decimal_price} -> 마진 제거한 확률(합=1)."""
    inv = {k: 1.0 / v for k, v in prices.items() if v and v > 1.0}
    s = sum(inv.values())
    if s <= 0:
        return None
    return {k: v / s for k, v in inv.items()}


def _parse_events(events: list) -> list[dict]:
    """The Odds API 응답 -> [{a, b, pa, pb, pd}] (a/b는 한글 팀명)."""
    out = []
    for ev in events:
        home, away = ev.get("home_team"), ev.get("away_team")
        if not home or not away:
            continue
        acc = {"home": 0.0, "away": 0.0, "draw": 0.0}
        n = 0
        for bm in ev.get("bookmakers", []):
            for mk in bm.get("markets", []):
                if mk.get("key") != "h2h":
                    continue
                prices = {}
                for o in mk.get("outcomes", []):
                    nm, price = o.get("name"), o.get("price")
                    if nm == home:
                        prices["home"] = price
                    elif nm == away:
                        prices["away"] = price
                    elif nm and nm.lower() == "draw":
                        prices["draw"] = price
                if len(prices) == 3:
                    dv = _devig(prices)
                    if dv:
                        acc["home"] += dv["home"]
                        acc["away"] += dv["away"]
                        acc["draw"] += dv["draw"]
                        n += 1
        if n == 0:
            continue
        out.append(
            {
                "a": to_korean(home),
                "b": to_korean(away),
                "pa": acc["home"] / n,
                "pb": acc["away"] / n,
                "pd": acc["draw"] / n,
            }
        )
    return out


def _load_cache() -> dict | None:
    if os.path.exists(CACHE):
        try:
            return json.load(open(CACHE, encoding="utf-8"))
        except Exception:
            return None
    return None


def _save_cache(entries: list[dict]) -> None:
    try:
        os.makedirs(os.path.dirname(CACHE), exist_ok=True)
        json.dump({"fetched": time.time(), "entries": entries},
                  open(CACHE, "w", encoding="utf-8"), ensure_ascii=False)
    except Exception:
        pass


def _fetch_entries(force: bool = False) -> tuple[list[dict], dict]:
    """배당 엔트리 목록과 메타(meta) 반환. 캐시 우선."""
    meta = {"source": "none", "key": bool(api_key()), "remaining": None, "age_sec": None}
    cache = _load_cache()
    now = time.time()
    if cache and not force:
        age = now - cache.get("fetched", 0)
        meta["age_sec"] = int(age)
        if age < ODDS_TTL:
            meta["source"] = "cache"
            return cache.get("entries", []), meta

    key = api_key()
    if not key:
        meta["key"] = False
        if cache:  # 키 없으면 만료됐어도 캐시라도 사용
            meta["source"] = "cache(stale)"
            return cache.get("entries", []), meta
        return [], meta
    meta["key"] = True

    try:
        url = ODDS_URL.format(sport=SPORT_KEY, key=key, regions=REGIONS)
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        r = urllib.request.urlopen(req, context=_SSL, timeout=25)
        meta["remaining"] = r.headers.get("x-requests-remaining")
        events = json.loads(r.read().decode("utf-8", "replace"))
        entries = _parse_events(events)
        _save_cache(entries)
        meta["source"] = "api"
        return entries, meta
    except Exception as e:  # noqa: BLE001
        meta["error"] = f"{type(e).__name__}: {e}"
        if cache:
            meta["source"] = "cache(stale)"
            return cache.get("entries", []), meta
        return [], meta


def get_match_odds(matches: list[dict], force: bool = False) -> tuple[dict, dict]:
    """우리 경기 id -> (p_home, p_draw, p_away) 매핑 + 메타.

    배당 엔트리를 한글 팀명 쌍으로 우리 잔여경기에 매칭한다.
    """
    from .standings import _is_final

    entries, meta = _fetch_entries(force=force)
    by_pair = {}
    for e in entries:
        by_pair[frozenset((e["a"], e["b"]))] = e

    out = {}
    matched = 0
    for m in matches:
        if _is_final(m):
            continue
        home, away = m["home"]["name"], m["away"]["name"]
        e = by_pair.get(frozenset((home, away)))
        if not e:
            continue
        # 엔트리의 a/b 가 우리 home/away 와 같은 방향인지 확인해 정렬
        if e["a"] == home:
            ph, pa = e["pa"], e["pb"]
        else:
            ph, pa = e["pb"], e["pa"]
        out[m["id"]] = (ph, e["pd"], pa)
        matched += 1
    meta["matched"] = matched
    return out, meta
