"""월드컵 2026 한국 32강 진출 경우의 수 대시보드 (Flask).

실행:
    pip install -r requirements.txt
    python app.py
    브라우저에서 http://127.0.0.1:5000 접속
"""
from __future__ import annotations

import os
import time

from flask import Flask, jsonify, render_template, request

from worldcup import odds_client as OC
from worldcup import predictor as PR
from worldcup import scenarios as SC
from worldcup import standings as ST
from worldcup.fifa_client import load_matches
from worldcup.standings import all_group_tables, group_complete

app = Flask(__name__)

# 데이터 우선순위: FIFA 공식 API -> openfootball -> 캐시
DATA_PREFER = os.environ.get("WC_PREFER", "fifa")
MC_TRIALS = int(os.environ.get("WC_TRIALS", "10000"))
# 공개 배포 시 다수 접속자가 매번 몬테카를로를 돌리지 않도록 상태 캐시(초)
STATE_TTL = int(os.environ.get("WC_STATE_TTL", "60"))
# 원본 데이터 재요청 최소 간격(초) — FIFA API 과도호출 방지
DATA_TTL = int(os.environ.get("WC_DATA_TTL", "120"))

_STATE: dict = {"data": None}
_CACHE: dict = {"payload": None, "ts": 0.0}


def _load(force: bool = False) -> dict:
    if force or _STATE["data"] is None:
        _STATE["data"] = load_matches(prefer=DATA_PREFER, use_cache_ttl=0 if force else DATA_TTL)
    return _STATE["data"]


def _build_state(data: dict, run_mc: bool = True) -> dict:
    matches = data["matches"]
    tables = all_group_tables(matches)
    analysis = SC.analyze(matches)
    odds_map, odds_meta = OC.get_match_odds(matches)
    payload = {
        "meta": {
            "source": data.get("source"),
            "fetched_at": data.get("fetched_at"),
            "from_cache": data.get("from_cache", False),
            "errors": data.get("errors", []),
            "total_matches": len(matches),
            "finished": sum(1 for m in matches if m["status"] == "finished"),
        },
        "groups": {
            g: {
                "table": tb,
                "complete": group_complete(matches, g),
            }
            for g, tb in tables.items()
        },
        "analysis": analysis,
        "bingo": SC.bingo_board(matches, odds_map),
        "predictions": PR.predict_remaining(matches, odds_map),
        "odds_meta": {
            "source": odds_meta.get("source"),
            "matched": odds_meta.get("matched"),
            "remaining": odds_meta.get("remaining"),
            "has_key": odds_meta.get("key"),
        },
        # What-if 대상 = 아직 '결과가 확정되지 않은' 경기만 (엔진의 미결정 정의와 일치).
        # 종료 경기는 물론, 점수가 들어간 진행중(live) 경기도 제외 → 잔여경기만 남음.
        "remaining_matches": [
            {
                "id": m["id"],
                "group": m["group"],
                "date": m["date"],
                "home": m["home"]["name"],
                "away": m["away"]["name"],
                "status": m["status"],
                "live": m["status"] == "live",
                "score": (f"{m['home_score']}-{m['away_score']}"
                          if m["status"] == "live" and m["home_score"] is not None else None),
            }
            for m in sorted(matches, key=lambda x: (x["date"] or "9999", x["group"]))
            if not ST._is_final(m)
        ],
    }
    if run_mc:
        # 몬테카를로 대신 조별 독립성을 이용한 정확(해석적) 확률 — 빠르고 결정적
        # 배당(odds_map)이 있으면 전력 가중에 배당 확률을 우선 반영
        payload["probability"] = SC.advance_probability(matches, odds_map=odds_map)
    return payload


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/state")
def api_state():
    force = request.args.get("refresh") == "1"
    now = time.time()
    if not force and _CACHE["payload"] is not None and (now - _CACHE["ts"]) < STATE_TTL:
        return jsonify(_CACHE["payload"])
    data = _load(force=force)
    payload = _build_state(data, run_mc=True)
    _CACHE["payload"] = payload
    _CACHE["ts"] = now
    return jsonify(payload)


@app.route("/api/whatif", methods=["POST"])
def api_whatif():
    body = request.get_json(force=True) or {}
    outcomes = body.get("outcomes", {})
    data = _load(force=False)
    # what-if 결과를 반영한 가상 경기로 분석 + 빙고판 재구성
    sim = []
    for m in data["matches"]:
        nm = dict(m)
        nm["home"] = dict(m["home"])
        nm["away"] = dict(m["away"])
        if m["id"] in outcomes and m["status"] != "finished":
            val = outcomes[m["id"]]
            if isinstance(val, str) and ":" in val:
                hs, as_ = (int(x) for x in val.split(":"))
            else:
                hs, as_ = SC._RESULT_SCORELINES[val]
            nm["home_score"], nm["away_score"], nm["status"] = hs, as_, "finished"
        sim.append(nm)
    return jsonify({"analysis": SC.analyze(sim), "bingo": SC.bingo_board(sim)})


if __name__ == "__main__":
    print(">> 데이터 로딩 중...", flush=True)
    d = _load(force=True)
    print(f">> source={d.get('source')} matches={len(d['matches'])} "
          f"errors={d.get('errors')}", flush=True)
    port = int(os.environ.get("PORT", "5000"))
    print(f">> http://127.0.0.1:{port} 에서 대시보드를 여세요.", flush=True)
    app.run(host="0.0.0.0", port=port, debug=False)
