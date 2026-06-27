"""남은 경기 전력 예측 (데이터 기반).

각 팀의 Elo형 전력 레이팅으로 경기별 승/무/패 확률을 계산하고
우세/약우세/백중/약열세/열세 등급을 매긴다.

- 월드컵 조별리그는 사실상 중립경기라 홈 이점은 적용하지 않는다
  (개최국 3팀만 소폭 보정).
- 레이팅은 FIFA 랭킹/축구 Elo를 참고한 근사값으로 내장 — 네트워크 불필요.
- 실제 북메이커 배당이 있으면 override_probs 로 대체 가능(The Odds API 등).
"""
from __future__ import annotations

import math

# 개최국(소폭 홈 보정)
HOSTS = {"USA", "CAN", "MEX"}
HOST_BONUS = 30.0

# 팀 전력 레이팅 (FIFA 코드 기준, Elo 근사)
RATING_BY_CODE = {
    "ARG": 2100, "FRA": 2070, "BRA": 2020, "ESP": 2050, "ENG": 2010,
    "POR": 1990, "NED": 1975, "GER": 1965, "BEL": 1945, "CRO": 1900,
    "URU": 1895, "MAR": 1875, "COL": 1860, "SUI": 1850, "JPN": 1840,
    "SEN": 1815, "MEX": 1810, "NOR": 1810, "AUT": 1800, "USA": 1795,
    "KOR": 1785, "ECU": 1775, "SWE": 1775, "CZE": 1765, "ALG": 1755,
    "BIH": 1755, "IRN": 1760, "EGY": 1750, "SCO": 1745, "CAN": 1745,
    "CIV": 1735, "GHA": 1730, "AUS": 1725, "PAR": 1715, "COD": 1705,
    "TUN": 1705, "TUR": 1700, "RSA": 1685, "QAT": 1685, "KSA": 1670,
    "PAN": 1660, "IRQ": 1650, "UZB": 1645, "CPV": 1620, "JOR": 1615,
    "CUW": 1590, "HAI": 1575, "NZL": 1510,
}
RATING_BY_NAME_KO = {
    "아르헨티나": 2100, "프랑스": 2070, "브라질": 2020, "스페인": 2050,
    "잉글랜드": 2010, "포르투갈": 1990, "네덜란드": 1975, "독일": 1965,
    "벨기에": 1945, "크로아티아": 1900, "우루과이": 1895, "모로코": 1875,
    "콜롬비아": 1860, "스위스": 1850, "일본": 1840, "세네갈": 1815,
    "멕시코": 1810, "노르웨이": 1810, "오스트리아": 1800, "미국": 1795,
    "대한민국": 1785, "에콰도르": 1775, "스웨덴": 1775, "체코": 1765,
    "알제리": 1755, "보스니아": 1755, "이란": 1760, "이집트": 1750,
    "스코틀랜드": 1745, "캐나다": 1745, "코트디부아르": 1735, "가나": 1730,
    "호주": 1725, "파라과이": 1715, "콩고민주공화국": 1705, "튀니지": 1705,
    "튀르키예": 1700, "남아공": 1685, "카타르": 1685, "사우디아라비아": 1670,
    "파나마": 1660, "이라크": 1650, "우즈베키스탄": 1645, "카보베르데": 1620,
    "요르단": 1615, "쿠라소": 1590, "아이티": 1575, "뉴질랜드": 1510,
}
DEFAULT_RATING = 1700.0


def rating(name: str, code: str | None = None) -> float:
    if code and code in RATING_BY_CODE:
        r = float(RATING_BY_CODE[code])
    elif name in RATING_BY_NAME_KO:
        r = float(RATING_BY_NAME_KO[name])
    else:
        r = DEFAULT_RATING
    if code in HOSTS:
        r += HOST_BONUS
    return r


def _wdl_from_diff(dr: float) -> tuple[float, float, float]:
    """레이팅 차(dr = 홈-원정)로 (홈승, 무, 원정승) 확률 산출.

    Elo 기대승점 We = 1/(1+10^(-dr/400)) 를 만족하도록 무승부율을 배분.
    무승부율은 두 팀이 비슷할수록 커진다(최대 ~32%).
    """
    we = 1.0 / (1.0 + 10 ** (-dr / 400.0))
    p_draw = 0.32 * math.exp(-((we - 0.5) ** 2) / 0.08)
    p_home = we - 0.5 * p_draw
    p_away = 1.0 - p_home - p_draw
    # 수치 보정
    p_home = max(0.0, p_home)
    p_away = max(0.0, p_away)
    s = p_home + p_draw + p_away
    return p_home / s, p_draw / s, p_away / s


def _tier(edge: float) -> str:
    """우세팀 확률 - 열세팀 확률(edge)로 등급."""
    if edge < 0.08:
        return "백중"
    if edge < 0.20:
        return "약우세"
    if edge < 0.38:
        return "우세"
    return "강세"


def predict_match(home: str, away: str,
                  home_code: str | None = None, away_code: str | None = None,
                  override: tuple | None = None) -> dict:
    """한 경기 예측.

    override: (p_home, p_draw, p_away) — 실제 배당 기반 확률이 있으면 우선 사용.
    """
    if override:
        p_home, p_draw, p_away = override
        rh = ra = None
    else:
        rh = rating(home, home_code)
        ra = rating(away, away_code)
        p_home, p_draw, p_away = _wdl_from_diff(rh - ra)

    if p_home >= p_away:
        fav, fav_side, edge = home, "home", p_home - p_away
    else:
        fav, fav_side, edge = away, "away", p_away - p_home
    tier = _tier(edge)

    # 팀 관점 라벨
    if tier == "백중":
        home_label = away_label = "백중"
    elif fav_side == "home":
        home_label = tier
        away_label = "열세" if tier in ("우세", "강세") else "약열세"
    else:
        away_label = tier
        home_label = "열세" if tier in ("우세", "강세") else "약열세"

    return {
        "home": home, "away": away,
        "home_rating": rh, "away_rating": ra,
        "p_home": p_home, "p_draw": p_draw, "p_away": p_away,
        "favorite": fav, "favorite_side": fav_side,
        "tier": tier, "edge": edge,
        "home_label": home_label, "away_label": away_label,
        "summary": f"{fav} {tier}" if tier != "백중" else "백중(접전)",
    }


def predict_remaining(matches: list[dict], odds_map: dict | None = None) -> list[dict]:
    """미결정(점수 없는) 경기들에 대한 예측 목록 (날짜순).

    odds_map: {match_id: (p_home,p_draw,p_away)} 실제 배당 확률이 있으면 우선 사용.
    """
    from .standings import _is_final

    odds_map = odds_map or {}
    out = []
    for m in sorted(matches, key=lambda x: (x.get("date") or "9999", x["group"])):
        if _is_final(m):
            continue
        override = odds_map.get(m["id"])
        p = predict_match(
            m["home"]["name"], m["away"]["name"],
            m["home"].get("code"), m["away"].get("code"),
            override=override,
        )
        p["id"] = m["id"]
        p["group"] = m["group"]
        p["date"] = m.get("date")
        p["source"] = "odds" if override else "rating"
        out.append(p)
    return out


def outcome_probs(matches: list[dict], odds_map: dict | None = None) -> dict[str, tuple]:
    """경기 id -> (p_home, p_draw, p_away). 진출확률 가중에 사용.

    배당이 있으면 배당 확률, 없으면 전력 레이팅 확률.
    """
    pm = {}
    for p in predict_remaining(matches, odds_map):
        pm[p["id"]] = (p["p_home"], p["p_draw"], p["p_away"])
    return pm
