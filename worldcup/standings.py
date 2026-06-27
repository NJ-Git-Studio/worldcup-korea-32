"""그룹 순위표 + 3위 8팀 랭킹 계산 (FIFA 2026 규정 타이브레이커).

그룹 내 순위 결정 순서:
  1) 승점  2) 골득실  3) 다득점
  (동률이면) 4) 승점(맞대결)  5) 골득실(맞대결)  6) 다득점(맞대결)
  7) 페어플레이  8) 추첨   ← 7,8은 모델링하지 않고 팀명으로 안정 정렬

3위 팀 간 순위(조별 1·2위 외 8장):
  1) 승점  2) 골득실  3) 다득점  (이후 징계/추첨은 미모델링)

승점: 승 3 / 무 1 / 패 0
"""
from __future__ import annotations

from typing import Iterable, Optional

WIN, DRAW = 3, 1


def _blank(name: str, code: str) -> dict:
    return {
        "name": name,
        "code": code,
        "played": 0,
        "win": 0,
        "draw": 0,
        "loss": 0,
        "gf": 0,
        "ga": 0,
        "gd": 0,
        "points": 0,
    }


def _apply(stats: dict, gf: int, ga: int) -> None:
    stats["played"] += 1
    stats["gf"] += gf
    stats["ga"] += ga
    stats["gd"] = stats["gf"] - stats["ga"]
    if gf > ga:
        stats["win"] += 1
        stats["points"] += WIN
    elif gf == ga:
        stats["draw"] += 1
        stats["points"] += DRAW
    else:
        stats["loss"] += 1


def _teams_in_group(matches: Iterable[dict]) -> dict[str, dict]:
    teams: dict[str, dict] = {}
    for m in matches:
        for side in ("home", "away"):
            nm = m[side]["name"]
            if nm not in teams:
                teams[nm] = _blank(nm, m[side]["code"])
    return teams


def _is_final(m: dict) -> bool:
    """경기 결과가 '확정'됐는가. 진행 중(live)은 아직 미확정으로 본다.

    (live 경기의 현재 스코어는 바뀔 수 있으므로 순위·완료·경우의 수 계산에서
    제외하고, 잔여경기로 취급한다.)
    """
    return (
        m.get("status") == "finished"
        and m.get("home_score") is not None
        and m.get("away_score") is not None
    )


def _head_to_head_order(tied: list[dict], matches: list[dict]) -> list[dict]:
    """동률 팀들 사이의 맞대결만으로 미니리그를 만들어 정렬."""
    names = {t["name"] for t in tied}
    mini: dict[str, dict] = {t["name"]: _blank(t["name"], t["code"]) for t in tied}
    for m in matches:
        if not _is_final(m):
            continue
        h, a = m["home"]["name"], m["away"]["name"]
        if h in names and a in names:
            _apply(mini[h], m["home_score"], m["away_score"])
            _apply(mini[a], m["away_score"], m["home_score"])
    # 맞대결 기준: 승점 -> 골득실 -> 다득점, 그래도 같으면 팀명
    return sorted(
        tied,
        key=lambda t: (
            -mini[t["name"]]["points"],
            -mini[t["name"]]["gd"],
            -mini[t["name"]]["gf"],
            t["name"],
        ),
    )


def compute_group_table(matches: list[dict]) -> list[dict]:
    """한 그룹의 경기 목록 -> 순위가 매겨진 팀 리스트(1위부터)."""
    teams = _teams_in_group(matches)
    for m in matches:
        if _is_final(m):
            _apply(teams[m["home"]["name"]], m["home_score"], m["away_score"])
            _apply(teams[m["away"]["name"]], m["away_score"], m["home_score"])

    # 1차 정렬: 승점/골득실/다득점
    ordered = sorted(
        teams.values(),
        key=lambda t: (-t["points"], -t["gd"], -t["gf"], t["name"]),
    )

    # 동률 구간을 맞대결로 재정렬
    result: list[dict] = []
    i = 0
    while i < len(ordered):
        j = i + 1
        while (
            j < len(ordered)
            and ordered[j]["points"] == ordered[i]["points"]
            and ordered[j]["gd"] == ordered[i]["gd"]
            and ordered[j]["gf"] == ordered[i]["gf"]
        ):
            j += 1
        block = ordered[i:j]
        if len(block) > 1:
            block = _head_to_head_order(block, matches)
        result.extend(block)
        i = j

    for rank, t in enumerate(result, start=1):
        t["rank"] = rank
    return result


def all_group_tables(matches: list[dict]) -> dict[str, list[dict]]:
    """전체 경기 -> {그룹문자: 순위리스트}."""
    groups: dict[str, list[dict]] = {}
    for m in matches:
        groups.setdefault(m["group"], []).append(m)
    return {g: compute_group_table(ms) for g, ms in sorted(groups.items())}


def group_complete(matches: list[dict], group: str) -> bool:
    return all(_is_final(m) for m in matches if m["group"] == group)


# ---- 3위 팀 랭킹 --------------------------------------------------------
def third_place_key(team: dict) -> tuple:
    """3위 팀 간 비교 키 (클수록 상위). 정렬 시 음수로 사용."""
    return (team["points"], team["gd"], team["gf"])


def rank_third_places(tables: dict[str, list[dict]]) -> list[dict]:
    """각 그룹 3위 팀을 모아 8장 컷 랭킹으로 정렬.

    반환 각 항목에 group, 그리고 cut(True=상위8=진출) 표시.
    그룹이 4팀 미만이거나 3위가 없으면 제외.
    """
    thirds = []
    for g, table in tables.items():
        if len(table) >= 3:
            t = dict(table[2])
            t["group"] = g
            thirds.append(t)
    thirds.sort(key=lambda t: (-t["points"], -t["gd"], -t["gf"], t["group"]))
    for idx, t in enumerate(thirds):
        t["third_rank"] = idx + 1
        t["cut"] = idx < 8  # 상위 8팀 진출
    return thirds


def compare_third(a: dict, b: dict) -> int:
    """3위 비교: a가 b보다 상위면 +1, 하위면 -1, (pts,gd,gf) 동일이면 0."""
    ka, kb = third_place_key(a), third_place_key(b)
    if ka > kb:
        return 1
    if ka < kb:
        return -1
    return 0
