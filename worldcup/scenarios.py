"""한국 32강 진출 경우의 수 분석.

48개팀 체제: 12개 조 × 4팀. 각 조 1·2위(24팀) + 3위 중 상위 8팀 = 32강.

한국이 3위로 마쳤을 때(또는 마칠 가능성이 있을 때) 핵심은
"다른 11개 조의 3위 팀들 중 한국보다 위에 서는 팀이 7팀 이하인가"이다.
각 조의 잔여경기는 서로 독립이므로, 조별로 '한국보다 위가 될 수 있는가/
반드시 위인가'를 따져 진출 확정/탈락/경합을 엄밀히 판정한다.
세부 골득실 경합 구간은 몬테카를로 확률과 what-if 로 보완한다.
"""
from __future__ import annotations

import itertools
import random
from typing import Optional

from . import standings as S

KOREA_KEYS = ("Korea Republic", "Korea DPR", "South Korea", "대한민국", "한국")
QUALIFY_SPOTS_PER_GROUP = 2
THIRD_PLACE_SPOTS = 8

# 잔여경기 가정 점수(전수조사용 대표 스코어라인)
_RESULT_SCORELINES = {
    "home": (2, 0),  # 홈 승
    "draw": (1, 1),  # 무
    "away": (0, 2),  # 원정 승
}


def find_korea(matches: list[dict]) -> Optional[str]:
    names = {m[s]["name"] for m in matches for s in ("home", "away")}
    for nm in names:
        if any(k.lower() in nm.lower() for k in KOREA_KEYS):
            return nm
    return None


def _remaining(matches: list[dict], group: Optional[str] = None) -> list[dict]:
    out = []
    for m in matches:
        if group and m["group"] != group:
            continue
        if not S._is_final(m):
            out.append(m)
    return out


def _with_results(matches: list[dict], assignment: dict[str, str]) -> list[dict]:
    """잔여경기 id->('home'|'draw'|'away') 가정으로 점수를 채운 사본."""
    clone = []
    for m in matches:
        nm = dict(m)
        nm["home"] = dict(m["home"])
        nm["away"] = dict(m["away"])
        if m["id"] in assignment:
            hs, as_ = _RESULT_SCORELINES[assignment[m["id"]]]
            nm["home_score"] = hs
            nm["away_score"] = as_
            nm["status"] = "finished"
        clone.append(nm)
    return clone


# ---- 조별 3위 가능 범위(승점) -------------------------------------------
def _group_third_point_range(matches: list[dict], group: str) -> tuple[int, int, bool]:
    """미완 조의 잔여경기 W/D/L 전수조사로 3위 팀의 (최소승점, 최대승점) 산출.

    반환: (min_pts, max_pts, has_third)
    """
    rem = _remaining(matches, group)
    group_matches = [m for m in matches if m["group"] == group]
    if not rem:
        table = S.compute_group_table(group_matches)
        if len(table) >= 3:
            p = table[2]["points"]
            return p, p, True
        return 0, 0, False

    mn, mx = 99, -1
    found = False
    keys = [m["id"] for m in rem]
    for combo in itertools.product(("home", "draw", "away"), repeat=len(keys)):
        assignment = dict(zip(keys, combo))
        filled = _with_results(group_matches, assignment)
        table = S.compute_group_table(filled)
        if len(table) >= 3:
            found = True
            p = table[2]["points"]
            mn = min(mn, p)
            mx = max(mx, p)
    if not found:
        return 0, 0, False
    return mn, mx, found


# ---- 한국 진출 판정 (엄밀 + 확률) ---------------------------------------
def analyze(matches: list[dict]) -> dict:
    korea = find_korea(matches)
    tables = S.all_group_tables(matches)
    thirds_now = S.rank_third_places(tables)

    if korea is None:
        return {"error": "데이터에서 한국 팀을 찾지 못했습니다.", "third_table": thirds_now}

    kgroup = next(m["group"] for m in matches if korea in (m["home"]["name"], m["away"]["name"]))
    ktable = tables[kgroup]
    kteam = next(t for t in ktable if t["name"] == korea)
    krank = kteam["rank"]
    kcomplete = S.group_complete(matches, kgroup)

    result = {
        "korea_name": korea,
        "korea_group": kgroup,
        "korea_stats": kteam,
        "korea_rank_in_group": krank,
        "korea_group_complete": kcomplete,
        "third_table": thirds_now,
        "remaining_total": len(_remaining(matches)),
    }

    # 1) 한국 조 잔여경기로 한국이 1·2위(자력) 가능한지
    krem = _remaining(matches, kgroup)
    possible_ranks = set()
    if krem:
        keys = [m["id"] for m in krem]
        gms = [m for m in matches if m["group"] == kgroup]
        for combo in itertools.product(("home", "draw", "away"), repeat=len(keys)):
            filled = _with_results(gms, dict(zip(keys, combo)))
            tb = S.compute_group_table(filled)
            r = next(t["rank"] for t in tb if t["name"] == korea)
            possible_ranks.add(r)
    else:
        possible_ranks = {krank}
    result["possible_group_ranks"] = sorted(possible_ranks)
    result["can_auto_qualify"] = any(r <= QUALIFY_SPOTS_PER_GROUP for r in possible_ranks)
    result["auto_qualified"] = all(r <= QUALIFY_SPOTS_PER_GROUP for r in possible_ranks)
    result["group_eliminated"] = all(r >= 4 for r in possible_ranks)  # 3위도 불가 → 탈락

    # 한국이 3위로 마칠 때의 확정 승점(조 완료 시) 또는 잠정 승점
    kpts = kteam["points"]

    # 2) 3위 와일드카드 판정 (한국이 3위라고 가정)
    #    다른 11개 조의 3위가 한국보다 '승점' 위가 될 수 있는지/반드시인지
    other_groups = [g for g in tables if g != kgroup]
    guaranteed_above = 0   # 어떤 경우에도 한국보다 승점 높음
    possible_above = 0     # 한국보다 승점 높아질 수 있음(동률 GD경합 포함)
    contested = []         # 동률(승점 같음) 가능 → GD 경합 조
    per_group = []
    for g in other_groups:
        mn, mx, has = _group_third_point_range(matches, g)
        if not has:
            continue
        always_higher = mn > kpts
        can_higher = mx > kpts
        can_equal = mn <= kpts <= mx
        if always_higher:
            guaranteed_above += 1
        # '한국보다 위가 될 수 있음' = 승점 더 높거나(>) 동률(GD로 역전 가능)
        if can_higher or can_equal:
            possible_above += 1
        if can_equal and not can_higher:
            contested.append(g)
        per_group.append(
            {
                "group": g,
                "third_min_pts": mn,
                "third_max_pts": mx,
                "always_above_korea": always_higher,
                "can_be_above_korea": can_higher or can_equal,
                "complete": S.group_complete(matches, g),
            }
        )
    result["wildcard_detail"] = per_group
    result["wildcard_contested_groups"] = contested

    # 현재 잠정 3위 랭킹에서 한국 위치 (먼저 계산 — 전부확정 판정에 사용)
    korea_third_rank = None
    korea_cut = None
    for t in thirds_now:
        if t.get("name") == korea:
            korea_third_rank = t["third_rank"]
            korea_cut = t["cut"]
            break
    result["korea_provisional_third_rank"] = korea_third_rank
    result["korea_provisional_cut"] = korea_cut

    fully_decided = result["remaining_total"] == 0

    # 판정
    if result["auto_qualified"]:
        verdict, conf = "QUALIFIED", "한국은 조 1·2위로 32강 진출이 확정되었습니다."
    elif result["group_eliminated"]:
        verdict, conf = "ELIMINATED", "한국은 조에서 3위 안에 들 수 없어 탈락이 확정되었습니다."
    elif fully_decided and krank == 3:
        # 모든 경기가 끝났으면 실제 3위 랭킹으로 정확히 판정
        if korea_cut:
            verdict, conf = "QUALIFIED", (
                f"한국은 3위 와일드카드 {korea_third_rank}위로 32강 진출을 확정했습니다."
            )
        else:
            verdict, conf = "ELIMINATED", (
                f"한국은 3위 와일드카드 경쟁 {korea_third_rank}위(8위 밖)로 탈락했습니다."
            )
    elif guaranteed_above >= THIRD_PLACE_SPOTS:
        verdict, conf = "ELIMINATED", (
            f"한국보다 승점이 높은 3위 팀이 최소 {guaranteed_above}팀이라 "
            f"상위 8(3위 와일드카드)에 들 수 없습니다."
        )
    elif possible_above <= (THIRD_PLACE_SPOTS - 1) and not krem and krank == 3:
        verdict, conf = "CLINCHED", (
            f"한국보다 위가 될 수 있는 3위 팀이 최대 {possible_above}팀뿐이라 "
            f"3위 와일드카드 진출이 확정되었습니다."
        )
    else:
        verdict, conf = "CONTENDING", (
            "자력 진출은 아니며, 다른 조 3위들의 결과에 따라 갈리는 경합 상황입니다."
        )
    result["verdict"] = verdict
    result["verdict_text"] = conf
    result["guaranteed_above"] = guaranteed_above
    result["possible_above"] = possible_above

    return result


# ---- 몬테카를로 확률 ----------------------------------------------------
def _sim_scoreline(rng: random.Random) -> tuple[int, int]:
    """간단한 득점 모델(0~3골, 낮은 점수 가중)."""
    table = [0, 0, 1, 1, 1, 2, 2, 3]
    return rng.choice(table), rng.choice(table)


def monte_carlo(matches: list[dict], trials: int = 20000, seed: int = 0) -> dict:
    """잔여경기를 무작위 시뮬레이션해 한국의 32강 진출 확률을 추정."""
    korea = find_korea(matches)
    if korea is None:
        return {"error": "한국 팀 없음"}
    rem = _remaining(matches)
    rng = random.Random(seed)

    advance = 0
    as_first_second = 0
    as_third = 0
    # 미완 조별: 그 조 3위가 한국보다 위가 된 횟수
    group_above = {m["group"]: 0 for m in rem}

    base = matches
    rem_ids = [m["id"] for m in rem]

    for _ in range(max(1, trials)):
        score_map = {mid: _sim_scoreline(rng) for mid in rem_ids}
        sim = []
        for m in base:
            nm = dict(m)
            if m["id"] in score_map and not S._is_final(m):
                hs, as_ = score_map[m["id"]]
                nm["home_score"], nm["away_score"], nm["status"] = hs, as_, "finished"
            sim.append(nm)
        tables = S.all_group_tables(sim)
        # 한국 순위
        kgroup = next(mm["group"] for mm in sim if korea in (mm["home"]["name"], mm["away"]["name"]))
        krank = next(t["rank"] for t in tables[kgroup] if t["name"] == korea)
        if krank <= 2:
            advance += 1
            as_first_second += 1
            continue
        if krank >= 4:
            continue
        # 3위 → 와일드카드 컷 확인
        thirds = S.rank_third_places(tables)
        kentry = next((t for t in thirds if t.get("name") == korea), None)
        if kentry and kentry["cut"]:
            advance += 1
            as_third += 1
        # 조별 기여 통계
        kpts = next(t["points"] for t in tables[kgroup] if t["name"] == korea)
        for g in group_above:
            if g == kgroup:
                continue
            tb = tables.get(g)
            if tb and len(tb) >= 3:
                third = tb[2]
                if (third["points"], third["gd"], third["gf"]) > (kpts, kentry["gd"] if kentry else -99, kentry["gf"] if kentry else -99):
                    group_above[g] += 1

    return {
        "trials": trials,
        "advance_prob": advance / trials,
        "as_first_second_prob": as_first_second / trials,
        "as_third_prob": as_third / trials,
        "group_above_prob": {g: c / trials for g, c in sorted(group_above.items())},
    }


# ---- 빠른 정확 확률 (몬테카를로 대체) -----------------------------------
# 잔여경기 1경기당 대표 스코어라인. 홈승/무/원정승 버킷으로 묶어두고,
# 전력 예측이 있으면 각 버킷 합을 예측 확률(p_home/p_draw/p_away)로 맞춘다.
_HOME_SL = [(1, 0, 0.18), (2, 0, 0.10), (2, 1, 0.10)]   # 합 0.38
_DRAW_SL = [(0, 0, 0.12), (1, 1, 0.12)]                  # 합 0.24
_AWAY_SL = [(0, 1, 0.18), (0, 2, 0.10), (1, 2, 0.10)]   # 합 0.38
# 예측 없을 때의 중립 가중(기존과 동일): 홈38/무24/원정38
_SCORELINES_W = _HOME_SL + _DRAW_SL + _AWAY_SL


def _scorelines_for(probs: Optional[tuple]) -> list[tuple]:
    """(p_home,p_draw,p_away) -> 버킷 합이 그 확률이 되도록 가중한 스코어라인.

    probs 가 None 이면 중립 가중(_SCORELINES_W)을 그대로 사용.
    """
    if not probs:
        return _SCORELINES_W
    out = []
    for bucket, target in ((_HOME_SL, probs[0]), (_DRAW_SL, probs[1]), (_AWAY_SL, probs[2])):
        base = sum(w for *_, w in bucket) or 1.0
        for hs, as_, w in bucket:
            out.append((hs, as_, w / base * target))
    return out


def _with_scores(group_matches: list[dict], assignment: dict[str, tuple]) -> list[dict]:
    """잔여경기 id->(home_score, away_score) 로 점수를 채운 사본."""
    clone = []
    for m in group_matches:
        nm = dict(m)
        nm["home"] = dict(m["home"])
        nm["away"] = dict(m["away"])
        if m["id"] in assignment:
            nm["home_score"], nm["away_score"] = assignment[m["id"]]
            nm["status"] = "finished"
        clone.append(nm)
    return clone


def _group_third_key_dist(matches: list[dict], group: str,
                          pred_map: Optional[dict] = None) -> list[tuple]:
    """그 조 3위의 (승점,골득실,다득점) 키에 대한 [(key, weight)] 분포.

    pred_map: {match_id: (p_home,p_draw,p_away)} 가 있으면 전력 예측으로 가중.
    """
    gms = [m for m in matches if m["group"] == group]
    rem = [m for m in gms if not S._is_final(m)]
    if not rem:
        t = _third_of(S.compute_group_table(gms))
        key = (t["points"], t["gd"], t["gf"]) if t else (-99, -99, -99)
        return [(key, 1.0)]
    keys = [m["id"] for m in rem]
    per_match = [_scorelines_for((pred_map or {}).get(mid)) for mid in keys]
    out = []
    for combo in itertools.product(*per_match):
        weight = 1.0
        assign = {}
        for mid, (hs, as_, w) in zip(keys, combo):
            assign[mid] = (hs, as_)
            weight *= w
        t = _third_of(S.compute_group_table(_with_scores(gms, assign)))
        key = (t["points"], t["gd"], t["gf"]) if t else (-99, -99, -99)
        out.append((key, weight))
    return out


def _p_above(dist: list[tuple], korea_key: tuple) -> float:
    """분포에서 3위 키가 한국보다 엄밀히 위일 확률."""
    tot = sum(w for _, w in dist) or 1.0
    return sum(w for key, w in dist if key > korea_key) / tot


def _poisson_binomial_leq(ps: list[float], k: int) -> float:
    """독립 베르누이(ps)의 합이 k 이하일 확률 (DP)."""
    dist = [1.0]
    for p in ps:
        nxt = [0.0] * (len(dist) + 1)
        for i, v in enumerate(dist):
            nxt[i] += v * (1 - p)
            nxt[i + 1] += v * p
        dist = nxt
    return sum(dist[: k + 1])


def advance_probability(matches: list[dict], use_prediction: bool = True,
                        odds_map: Optional[dict] = None) -> dict:
    """한국 32강 진출 확률을 정확히(해석적으로) 계산.

    조별 독립성을 이용: 다른 각 조 3위가 한국보다 위일 확률을 구한 뒤,
    푸아송-이항 분포로 '한국보다 위인 3위 ≤ 7팀'일 확률을 합산.
    몬테카를로보다 빠르고(샘플링 오차 0) 결정적.

    use_prediction: True면 전력 예측(predictor)으로 경기 결과를 가중,
    False면 중립(홈38/무24/원정38) 가중.
    """
    korea = find_korea(matches)
    if korea is None:
        return {"error": "한국 팀 없음"}
    pred_map = None
    if use_prediction:
        from . import predictor as PR
        pred_map = PR.outcome_probs(matches, odds_map)
    tables = S.all_group_tables(matches)
    kgroup = next(m["group"] for m in matches if korea in (m["home"]["name"], m["away"]["name"]))
    others = [g for g in tables if g != kgroup]
    other_dists = {g: _group_third_key_dist(matches, g, pred_map) for g in others}

    # 한국 조 시나리오(승점/골득실/다득점 + 가중치)
    kgms = [m for m in matches if m["group"] == kgroup]
    krem = [m for m in kgms if not S._is_final(m)]
    scenarios = []  # (korea_rank, korea_key, weight)
    if not krem:
        tb = S.compute_group_table(kgms)
        kt = next(t for t in tb if t["name"] == korea)
        scenarios.append((kt["rank"], (kt["points"], kt["gd"], kt["gf"]), 1.0))
    else:
        keys = [m["id"] for m in krem]
        per_match = [_scorelines_for((pred_map or {}).get(mid)) for mid in keys]
        for combo in itertools.product(*per_match):
            weight = 1.0
            assign = {}
            for mid, (hs, as_, w) in zip(keys, combo):
                assign[mid] = (hs, as_)
                weight *= w
            tb = S.compute_group_table(_with_scores(kgms, assign))
            kt = next(t for t in tb if t["name"] == korea)
            scenarios.append((kt["rank"], (kt["points"], kt["gd"], kt["gf"]), weight))

    total_w = sum(w for _, _, w in scenarios) or 1.0
    advance = as12 = as3 = 0.0
    group_above = {g: 0.0 for g in others}
    cut_k = THIRD_PLACE_SPOTS - 1  # 한국보다 위가 7팀 이하면 진출

    for rank, kkey, w in scenarios:
        ps = [_p_above(other_dists[g], kkey) for g in others]
        for g, p in zip(others, ps):
            group_above[g] += w * p
        if rank <= QUALIFY_SPOTS_PER_GROUP:
            advance += w
            as12 += w
        elif rank >= 4:
            pass  # 탈락
        else:
            p_adv = _poisson_binomial_leq(ps, cut_k)
            advance += w * p_adv
            as3 += w * p_adv

    return {
        "method": "exact+prediction" if use_prediction else "exact",
        "trials": None,
        "advance_prob": advance / total_w,
        "as_first_second_prob": as12 / total_w,
        "as_third_prob": as3 / total_w,
        "group_above_prob": {g: group_above[g] / total_w for g in sorted(group_above)},
    }


# ---- what-if: 사용자가 잔여경기 결과를 지정 -----------------------------
def what_if(matches: list[dict], outcomes: dict[str, str]) -> dict:
    """outcomes: {match_id: 'home'|'draw'|'away'} (또는 'A:B' 점수문자열).

    지정되지 않은 잔여경기는 현재 상태(미정)로 둔 채,
    지정된 결과만 반영해 한국 진출 여부를 다시 판정.
    """
    sim = []
    for m in matches:
        nm = dict(m)
        nm["home"] = dict(m["home"])
        nm["away"] = dict(m["away"])
        if m["id"] in outcomes and not S._is_final(m):
            val = outcomes[m["id"]]
            if isinstance(val, str) and ":" in val:
                hs, as_ = (int(x) for x in val.split(":"))
            else:
                hs, as_ = _RESULT_SCORELINES[val]
            nm["home_score"], nm["away_score"], nm["status"] = hs, as_, "finished"
        sim.append(nm)
    return analyze(sim)


# ---- 빙고판: 조별 '한국에 유리한 조건' 자동 생성/평가 -------------------
def _third_of(table: list[dict]) -> Optional[dict]:
    return table[2] if len(table) >= 3 else None


def _is_above(third: Optional[dict], korea_key: tuple) -> bool:
    """그 조 3위가 한국보다 (승점,골득실,다득점) 엄밀히 위면 True = 한국에 불리."""
    if third is None:
        return False
    return (third["points"], third["gd"], third["gf"]) > korea_key


def _match_conditions(group_matches: list[dict], rem: list[dict], korea_key: tuple,
                      pred_map: Optional[dict] = None) -> list[dict]:
    """미정 조의 잔여경기별 '한국에 유리한 결과 + 그 결과 확률 + 유리 확률'.

    각 잔여경기 target 에 대해:
      - 결과별(승/무/패) '이 조가 한국에 유리할 조건부 확률'을 다른 잔여경기를
        전력/배당으로 가중해 계산
      - 가장 유리한 결과(fav_result)와, 그 결과가 실제로 나올 확률(result_prob),
        그 결과가 났을 때 조가 유리할 확률(fav_prob_if)을 함께 제공
    """
    pred_map = pred_map or {}
    conditions = []
    for target in rem:
        others = [m for m in rem if m["id"] != target["id"]]
        okeys = [m["id"] for m in others]
        per_other = [_scorelines_for(pred_map.get(k)) for k in okeys]
        cond_fav: dict[str, float] = {}
        for res in ("home", "draw", "away"):
            ts = _RESULT_SCORELINES[res]
            favw = totw = 0.0
            for combo in itertools.product(*per_other) if per_other else [()]:
                assign = {target["id"]: ts}
                w = 1.0
                for k, (hs, as_, ww) in zip(okeys, combo):
                    assign[k] = (hs, as_)
                    w *= ww
                table = S.compute_group_table(_with_scores(group_matches, assign))
                totw += w
                if not _is_above(_third_of(table), korea_key):
                    favw += w
            cond_fav[res] = favw / totw if totw else 0.0

        probs = pred_map.get(target["id"]) or (0.38, 0.24, 0.38)
        p_by_res = {"home": probs[0], "draw": probs[1], "away": probs[2]}
        desc = {
            "home": f"{target['home']['name']} 승",
            "draw": "무승부",
            "away": f"{target['away']['name']} 승",
        }
        hi = max(cond_fav.values())
        lo = min(cond_fav.values())
        swing = hi - lo
        best = max(cond_fav, key=lambda r: cond_fav[r])
        # 결과에 따라 유불리가 갈리는 결정적(swing) 경기인가?
        pivotal = swing >= 0.05
        if pivotal:
            fav_results = [r for r in ("home", "draw", "away") if cond_fav[r] >= hi - 0.05]
        else:
            fav_results = []  # 이 경기는 결과와 무관(영향 적음)

        hn, an = target["home"]["name"], target["away"]["name"]
        if len(fav_results) == 1:
            fav_label = {"home": f"{hn} 승이면", "draw": "무승부면",
                         "away": f"{an} 승이면"}[fav_results[0]]
        elif len(fav_results) == 2:
            excl = next(r for r in ("home", "draw", "away") if r not in fav_results)
            fav_label = {"home": f"{hn} 승이 아니면", "draw": "무승부가 아니면",
                         "away": f"{an} 승이 아니면"}[excl]
        else:
            fav_label = ""

        # 확정 판정: 이 유리한 결과가 나면, 나머지 잔여경기의 모든 결과에서
        # 이 조 3위가 한국보다 아래로 '확정'되는가? (조 단위 자력 보장)
        def _guarantees(res_label: str) -> bool:
            for combo in (itertools.product(("home", "draw", "away"), repeat=len(okeys))
                          if okeys else [()]):
                assign = dict(zip(okeys, combo))
                assign[target["id"]] = res_label
                table = S.compute_group_table(_with_results(group_matches, assign))
                if _is_above(_third_of(table), korea_key):
                    return False
            return True

        clinch_group = bool(fav_results) and all(_guarantees(r) for r in fav_results)

        conditions.append(
            {
                "match": f"{target['home']['name']} vs {target['away']['name']}",
                "home": target["home"]["name"],
                "away": target["away"]["name"],
                "pivotal": pivotal,
                "fav_result": best,
                "fav_label": fav_label,
                "clinch_group": clinch_group,   # True=확정, False=유리
                "level": "확정" if clinch_group else "유리",
                "result_prob": round(sum(p_by_res[r] for r in fav_results), 4),
                "fav_prob_if": round(hi, 4),
                "swing": round(swing, 4),
            }
        )
    return conditions


def _bucket_norm(bucket: list[tuple]) -> list[tuple]:
    s = sum(w for *_, w in bucket) or 1.0
    return [(hs, as_, w / s) for hs, as_, w in bucket]


def _group_breakdown(matches: list[dict], group: str, korea_key: tuple,
                     pred_map: Optional[dict]) -> Optional[dict]:
    """그 조 유리 확률이 어떻게 나오는지 — 잔여경기 결과 조합(승/무/패)별
    발생확률과 한국 유불리(골득실까지 반영한 유리 비율)를 분해."""
    pred_map = pred_map or {}
    gms = [m for m in matches if m["group"] == group]
    rem = [m for m in gms if not S._is_final(m)]
    if not rem:
        return None
    buckets = {"home": _bucket_norm(_HOME_SL), "draw": _bucket_norm(_DRAW_SL),
               "away": _bucket_norm(_AWAY_SL)}
    idx = {"home": 0, "draw": 1, "away": 2}
    keys = [m["id"] for m in rem]
    bprobs = [pred_map.get(m["id"]) or (0.38, 0.24, 0.38) for m in rem]
    rows = []
    for combo in itertools.product(("home", "draw", "away"), repeat=len(rem)):
        prob = 1.0
        for i, r in enumerate(combo):
            prob *= bprobs[i][idx[r]]
        per = [buckets[r] for r in combo]
        favw = totw = 0.0
        for sl in itertools.product(*per):
            w = 1.0
            assign = {}
            for k, (hs, as_, ww) in zip(keys, sl):
                assign[k] = (hs, as_)
                w *= ww
            table = S.compute_group_table(_with_scores(gms, assign))
            totw += w
            if not _is_above(_third_of(table), korea_key):
                favw += w
        fav = favw / totw if totw else 0.0
        results = []
        for m, r in zip(rem, combo):
            results.append({"home": f"{m['home']['name']} 승", "draw": "무승부",
                            "away": f"{m['away']['name']} 승"}[r])
        rows.append({"results": results, "prob": round(prob, 4), "fav": round(fav, 4)})
    rows.sort(key=lambda x: -x["prob"])
    return {
        "matches": [{"home": m["home"]["name"], "away": m["away"]["name"]} for m in rem],
        "rows": rows,
        "total": round(sum(r["prob"] * r["fav"] for r in rows), 4),
    }


def bingo_board(matches: list[dict], odds_map: Optional[dict] = None) -> dict:
    """이미지 같은 빙고판 데이터.

    각 '다른 조'를 한 칸으로:
      status = favorable(○) | unfavorable(X) | pending(?)
      locked = 더 이상 바뀌지 않음(확정)
    미정 칸은 경기별 유리 결과 + 그 결과 확률 + 조가 유리할 확률(배당/전력 가중)을 담는다.
    상단엔 진출에 필요한 '한국보다 아래 3위' 팀 수와 현재 확보 수.
    """
    korea = find_korea(matches)
    tables = S.all_group_tables(matches)
    if korea is None:
        return {"available": False, "reason": "한국 팀을 찾지 못했습니다."}

    pred_map = None
    try:
        from . import predictor as PR
        pred_map = PR.outcome_probs(matches, odds_map)
    except Exception:
        pred_map = {}

    kgroup = next(m["group"] for m in matches if korea in (m["home"]["name"], m["away"]["name"]))
    ktable = tables[kgroup]
    kteam = next(t for t in ktable if t["name"] == korea)
    krank = kteam["rank"]
    korea_key = (kteam["points"], kteam["gd"], kteam["gf"])

    board = {
        "available": True,
        "korea_name": korea,
        "korea_group": kgroup,
        "korea_rank": krank,
        "korea_stats": kteam,
    }

    if krank <= QUALIFY_SPOTS_PER_GROUP and S.group_complete(matches, kgroup):
        board["status"] = "QUALIFIED"
        board["headline"] = "한국은 조 1·2위로 이미 32강 진출!"
        board["cells"] = []
        return board
    if krank >= 4 and S.group_complete(matches, kgroup):
        board["status"] = "ELIMINATED"
        board["headline"] = "한국은 조 4위로 탈락이 확정되었습니다."
        board["cells"] = []
        return board

    others = [g for g in tables if g != kgroup]
    favorable_needed = len(others) - (THIRD_PLACE_SPOTS - 1)  # 11 - 7 = 4

    cells = []
    fav_locked = unfav_locked = pending = 0
    for g in others:
        gms = [m for m in matches if m["group"] == g]
        rem = [m for m in gms if not S._is_final(m)]
        third_now = _third_of(tables[g])
        cell = {
            "group": g,
            "complete": not rem,
            "third_now": third_now["name"] if third_now else None,
            "third_now_pts": third_now["points"] if third_now else None,
            "third_now_gd": third_now["gd"] if third_now else None,
            "conditions": [],
        }
        if not rem:
            above = _is_above(third_now, korea_key)
            cell["status"] = "unfavorable" if above else "favorable"
            cell["locked"] = True
        else:
            keys = [m["id"] for m in rem]
            flags = []
            for combo in itertools.product(("home", "draw", "away"), repeat=len(keys)):
                table = S.compute_group_table(_with_results(gms, dict(zip(keys, combo))))
                flags.append(not _is_above(_third_of(table), korea_key))
            if all(flags):
                cell["status"], cell["locked"] = "favorable", True
            elif not any(flags):
                cell["status"], cell["locked"] = "unfavorable", True
            else:
                cell["status"], cell["locked"] = "pending", False
                cell["conditions"] = _match_conditions(gms, rem, korea_key, pred_map)
                # 이 조가 한국에 유리할 확률(3위가 한국보다 위가 아닐 확률)
                dist = _group_third_key_dist(matches, g, pred_map)
                cell["favorable_prob"] = round(1.0 - _p_above(dist, korea_key), 4)
                # 호버 창용 조합 분해표
                cell["breakdown"] = _group_breakdown(matches, g, korea_key, pred_map)
        if cell["status"] == "favorable":
            fav_locked += 1
        elif cell["status"] == "unfavorable":
            unfav_locked += 1
        else:
            pending += 1
        cells.append(cell)

    # 정렬: 미정 -> 유리 -> 불리, 같은 묶음은 조명 순
    order = {"pending": 0, "favorable": 1, "unfavorable": 2}
    cells.sort(key=lambda c: (order[c["status"]], c["group"]))

    secured = fav_locked
    need_more = max(0, favorable_needed - secured)
    max_possible = secured + pending

    if secured >= favorable_needed:
        status = "CLINCHED"
        headline = f"한국보다 아래 3위 {secured}팀 확보 → 32강 진출 확정!"
    elif max_possible < favorable_needed:
        status = "ELIMINATED"
        headline = f"필요 {favorable_needed}팀 중 최대 {max_possible}팀만 가능 → 탈락"
    else:
        status = "CONTENDING"
        headline = (
            f"진출하려면 한국보다 아래인 3위가 총 {favorable_needed}팀 필요 "
            f"(확보 {secured}팀, 미정 칸에서 {need_more}팀 더 ○ 필요)"
        )

    board.update(
        {
            "status": status,
            "headline": headline,
            "favorable_needed": favorable_needed,
            "secured": secured,
            "need_more": need_more,
            "pending": pending,
            "unfavorable_locked": unfav_locked,
            "max_possible": max_possible,
            "cells": cells,
        }
    )
    return board
