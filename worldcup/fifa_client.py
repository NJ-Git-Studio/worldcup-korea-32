"""경기 데이터 연동 모듈.

우선순위:
  1) FIFA 공식 API (api.fifa.com, idCompetition=17, idSeason=285023 = 2026)
  2) openfootball 공개 JSON (폴백)
  3) 로컬 캐시 스냅샷 (네트워크 실패 시)
  4) 사용자가 넣은 manual_matches.json (있으면 결과를 덮어씀)

모든 소스를 아래 정규화된 Match 구조로 변환한다::

    {
      "id": str,
      "group": "A".."L",          # 그룹스테이지 경기만 사용
      "date": "YYYY-MM-DD",
      "status": "finished" | "live" | "scheduled",
      "home": {"name": str, "code": str},
      "away": {"name": str, "code": str},
      "home_score": int | None,
      "away_score": int | None,
    }
"""
from __future__ import annotations

import json
import os
import ssl
import time
import urllib.request
from typing import Any, Optional

from .teams import to_korean

# ---- 설정 ---------------------------------------------------------------
FIFA_COMPETITION_ID = "17"        # FIFA World Cup (남자 시니어)
FIFA_SEASON_ID = "285023"         # 2026 캐나다/멕시코/미국
FIFA_MATCHES_URL = (
    "https://api.fifa.com/api/v3/calendar/matches"
    "?idCompetition={comp}&idSeason={season}&count=200&language=en"
)
OPENFOOTBALL_URL = (
    "https://raw.githubusercontent.com/openfootball/worldcup.json/master/2026/worldcup.json"
)

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
CACHE_DIR = os.path.join(_ROOT, "cache")
RAW_SNAPSHOT = os.path.join(CACHE_DIR, "fifa_raw_snapshot.json")
NORMALIZED_CACHE = os.path.join(CACHE_DIR, "matches_normalized.json")
MANUAL_OVERRIDE = os.path.join(_ROOT, "manual_matches.json")

_HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
_SSL = ssl.create_default_context()
_SSL.check_hostname = False
_SSL.verify_mode = ssl.CERT_NONE  # 일부 윈도우 환경의 루트인증서 문제 회피


# ---- 유틸 ---------------------------------------------------------------
def _localized(value: Any) -> Optional[str]:
    """FIFA의 [{Locale, Description}] 형태 또는 평문을 문자열로."""
    if isinstance(value, list) and value:
        return value[0].get("Description")
    if isinstance(value, str):
        return value
    return None


def _http_json(url: str, timeout: int = 30) -> Any:
    req = urllib.request.Request(url, headers=_HEADERS)
    with urllib.request.urlopen(req, context=_SSL, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


def _group_letter(group_name: Optional[str]) -> Optional[str]:
    """'Group A' -> 'A'. 그룹스테이지가 아니면 None."""
    if not group_name:
        return None
    name = group_name.strip()
    if name.lower().startswith("group") and len(name) >= 7:
        return name[-1].upper()
    # 일부 소스는 그냥 'A' 처럼 줄 수 있음
    if len(name) == 1 and name.isalpha():
        return name.upper()
    return None


# ---- FIFA 공식 API ------------------------------------------------------
def _fifa_match_status(raw: dict) -> str:
    """FIFA MatchStatus 코드를 finished/live/scheduled 로 변환."""
    code = raw.get("MatchStatus")
    # 0 = 종료, 3/12 = 진행중(라이브), 1 = 예정. 코드가 애매하면 점수로 판단.
    if code == 0:
        return "finished"
    if code in (3, 12, 4):
        return "live"
    if code == 1:
        return "scheduled"
    home, away = raw.get("Home"), raw.get("Away")
    if home and away and home.get("Score") is not None and away.get("Score") is not None:
        return "finished"
    return "scheduled"


def parse_fifa(payload: dict) -> list[dict]:
    """FIFA calendar/matches 응답 -> 정규화 그룹스테이지 경기 목록."""
    out: list[dict] = []
    for m in payload.get("Results", []) or []:
        group = _group_letter(_localized(m.get("GroupName")))
        if group is None:
            continue  # 결선토너먼트 제외
        home, away = m.get("Home"), m.get("Away")
        if not home or not away:
            continue
        hname = _localized(home.get("TeamName")) or home.get("ShortClubName")
        aname = _localized(away.get("TeamName")) or away.get("ShortClubName")
        if not hname or not aname:
            continue  # 아직 팀 미정(플레이스홀더)
        status = _fifa_match_status(m)
        hs = home.get("Score")
        as_ = away.get("Score")
        if status == "scheduled":
            hs = as_ = None
        hcode = home.get("IdCountry") or _abbr(hname)
        acode = away.get("IdCountry") or _abbr(aname)
        out.append(
            {
                "id": str(m.get("IdMatch") or f"{group}-{hname}-{aname}"),
                "group": group,
                "date": (m.get("Date") or "")[:10],
                "status": status,
                "home": {"name": to_korean(hname, hcode), "code": hcode},
                "away": {"name": to_korean(aname, acode), "code": acode},
                "home_score": hs,
                "away_score": as_,
            }
        )
    return out


# ---- openfootball 폴백 --------------------------------------------------
def parse_openfootball(payload: dict) -> list[dict]:
    out: list[dict] = []
    for m in payload.get("matches", []) or []:
        group = _group_letter(m.get("group"))
        if group is None:
            continue
        hname, aname = m.get("team1"), m.get("team2")
        if isinstance(hname, dict):
            hname = hname.get("name")
        if isinstance(aname, dict):
            aname = aname.get("name")
        if not hname or not aname:
            continue
        score = m.get("score") or {}
        ft = score.get("ft")
        if isinstance(ft, list) and len(ft) == 2:
            hs, as_, status = ft[0], ft[1], "finished"
        else:
            hs = as_ = None
            status = "scheduled"
        out.append(
            {
                "id": str(m.get("num") or f"{group}-{hname}-{aname}"),
                "group": group,
                "date": str(m.get("date") or "")[:10],
                "status": status,
                "home": {"name": to_korean(hname), "code": _abbr(hname)},
                "away": {"name": to_korean(aname), "code": _abbr(aname)},
                "home_score": hs,
                "away_score": as_,
            }
        )
    return out


def _abbr(name: str) -> str:
    """국가 코드가 없을 때 임시 약어(앞 3글자 대문자)."""
    cleaned = "".join(ch for ch in name if ch.isalpha())
    return cleaned[:3].upper() if cleaned else "???"


# ---- manual override ----------------------------------------------------
def _apply_manual_override(matches: list[dict]) -> list[dict]:
    """manual_matches.json 이 있으면 같은 id 의 점수/상태를 덮어쓴다.

    형식 예::
        [{"id": "...", "home_score": 2, "away_score": 1}]
    또는 팀명으로 매칭::
        [{"group": "A", "home": "Mexico", "away": "Korea Republic",
          "home_score": 1, "away_score": 0}]
    """
    if not os.path.exists(MANUAL_OVERRIDE):
        return matches
    try:
        overrides = json.load(open(MANUAL_OVERRIDE, encoding="utf-8"))
    except Exception:
        return matches
    by_id = {m["id"]: m for m in matches}
    for ov in overrides:
        target = None
        if ov.get("id") and ov["id"] in by_id:
            target = by_id[ov["id"]]
        else:
            for m in matches:
                if (
                    m["group"] == ov.get("group")
                    and m["home"]["name"] == ov.get("home")
                    and m["away"]["name"] == ov.get("away")
                ):
                    target = m
                    break
        if target is None:
            continue
        if ov.get("home_score") is not None and ov.get("away_score") is not None:
            target["home_score"] = ov["home_score"]
            target["away_score"] = ov["away_score"]
            target["status"] = ov.get("status", "finished")
    return matches


# ---- 공개 진입점 --------------------------------------------------------
def load_matches(prefer: str = "fifa", use_cache_ttl: int = 0) -> dict:
    """경기 데이터를 불러온다.

    Returns: {"matches": [...], "source": str, "fetched_at": iso}
    prefer: "fifa" | "openfootball" | "cache"
    use_cache_ttl: 정규화 캐시가 이 초(secs) 이내면 네트워크 생략(0=항상 새로)
    """
    # 캐시 우선 사용 옵션
    if use_cache_ttl and os.path.exists(NORMALIZED_CACHE):
        age = time.time() - os.path.getmtime(NORMALIZED_CACHE)
        if age <= use_cache_ttl:
            cached = json.load(open(NORMALIZED_CACHE, encoding="utf-8"))
            cached["matches"] = _apply_manual_override(cached["matches"])
            cached["from_cache"] = True
            return cached

    order = (
        ["fifa", "openfootball", "cache"]
        if prefer == "fifa"
        else (["openfootball", "fifa", "cache"] if prefer == "openfootball" else ["cache", "fifa", "openfootball"])
    )

    matches: list[dict] = []
    source = "none"
    errors: list[str] = []

    for src in order:
        try:
            if src == "fifa":
                payload = _http_json(
                    FIFA_MATCHES_URL.format(comp=FIFA_COMPETITION_ID, season=FIFA_SEASON_ID)
                )
                matches = parse_fifa(payload)
                # 성공 시 원본 스냅샷도 저장
                _safe_write(RAW_SNAPSHOT, payload)
            elif src == "openfootball":
                payload = _http_json(OPENFOOTBALL_URL)
                matches = parse_openfootball(payload)
            elif src == "cache":
                if os.path.exists(RAW_SNAPSHOT):
                    payload = json.load(open(RAW_SNAPSHOT, encoding="utf-8"))
                    matches = parse_fifa(payload)
                else:
                    continue
            if matches:
                source = src
                break
        except Exception as e:  # noqa: BLE001
            errors.append(f"{src}: {type(e).__name__}: {e}")
            continue

    matches = _apply_manual_override(matches)
    result = {
        "matches": matches,
        "source": source,
        "fetched_at": _now_iso(),
        "errors": errors,
        "from_cache": False,
    }
    if matches:
        _safe_write(NORMALIZED_CACHE, result)
    return result


def _safe_write(path: str, obj: Any) -> None:
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False)
    except Exception:
        pass


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())


if __name__ == "__main__":  # 빠른 점검
    data = load_matches()
    ms = data["matches"]
    fin = sum(1 for m in ms if m["status"] == "finished")
    print(f"source={data['source']} matches={len(ms)} finished={fin}")
    print("errors:", data["errors"])
