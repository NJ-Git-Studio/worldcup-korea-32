# 무료 클라우드 배포 가이드 (영구 링크)

`https://....onrender.com` 같은 **고정 주소**를 만들어, 내 PC를 켜두지 않아도
누구나 24시간 접속할 수 있게 합니다. 비용·신용카드 불필요.

추천: **Render + GitHub** (가장 쉬움). 아래 순서대로 따라 하세요.

---

## 0. 준비물
- GitHub 계정 (없으면 https://github.com 에서 무료 가입)
- 이 프로젝트 폴더 (이미 git 초기화 + 첫 커밋 완료 상태)

---

## 1. GitHub에 코드 올리기

GitHub에서 새 저장소를 하나 만듭니다 (예: `worldcup-korea-32`, **Public 또는 Private 무관**).
저장소를 만든 뒤, 이 폴더에서 아래 명령을 실행하세요
(`<USERNAME>` 과 저장소 이름은 본인 것으로):

```bash
git remote add origin https://github.com/<USERNAME>/worldcup-korea-32.git
git branch -M main
git push -u origin main
```

> 처음 push 할 때 GitHub 로그인(브라우저 인증)이 뜨면 로그인하면 됩니다.

---

## 2. Render에서 배포

1. https://render.com 접속 → **Get Started** → **GitHub 계정으로 로그인** (Sign in with GitHub)
2. 대시보드에서 **New +** → **Blueprint** 선택
3. 방금 올린 저장소(`worldcup-korea-32`)를 **Connect**
4. Render가 저장소의 `render.yaml` 을 자동으로 읽어 설정을 채웁니다 → **Apply / Create**
5. 빌드가 끝나면(2~4분) 상단에 `https://worldcup-korea-32.onrender.com` 형태의
   **고정 주소**가 생깁니다. 이 주소를 누구에게나 공유하면 됩니다.

> Blueprint 메뉴가 안 보이면: **New + → Web Service** 로 저장소를 연결하고
> - Build Command: `pip install -r requirements.txt`
> - Start Command: `gunicorn app:app --bind 0.0.0.0:$PORT --workers 1 --threads 4 --timeout 120`
> 로 직접 입력해도 됩니다.

---

## 3. 알아둘 점 (무료 플랜)

- **콜드 스타트**: 15분간 접속이 없으면 서버가 잠들고, 다음 첫 접속 시
  깨어나는 데 30초~1분쯤 걸립니다(그 후엔 빠름). 무료 플랜의 정상 동작입니다.
- **데이터 갱신**: 경기 결과는 접속 시 FIFA API에서 자동으로 가져옵니다.
  서버는 60초(`WC_STATE_TTL`) 캐시를 쓰므로, 최신 결과는 페이지의
  **🔄 최신 데이터 갱신** 버튼을 누르면 반영됩니다.
- **설정 변경**: Render 대시보드 → 서비스 → **Environment** 에서
  `WC_PREFER`(데이터 소스) 등을 바꿀 수 있습니다.
- **실제 배당 켜기(선택)**: 같은 **Environment** 화면에서 **Add Environment Variable** →
  Key `ODDS_API_KEY`, Value 에 The Odds API 키를 넣고 저장하면, 배포된 사이트의
  예측·진출확률이 실제 배당 기반으로 바뀝니다. (키는 코드/저장소에 넣지 마세요 —
  반드시 이 환경변수로만 넣습니다.)
- **코드 수정 후 재배포**: 로컬에서 수정 → `git push` 하면 Render가 자동으로 다시 배포합니다.

---

## 다른 플랫폼 (선택)

`Procfile` 이 있어 Heroku 계열과 호환됩니다.

- **Railway** (https://railway.app): New Project → Deploy from GitHub repo →
  자동 감지. (무료 크레딧 소진 후 유료 전환될 수 있음)
- **PythonAnywhere**: 무료지만 Flask 수동 설정이 필요해 위 두 곳보다 번거롭습니다.

배포가 막히면 어느 단계에서 무슨 메시지가 나왔는지 알려주세요. 같이 해결해 드리겠습니다.
