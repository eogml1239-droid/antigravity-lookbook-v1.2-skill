---
name: antigravity-lookbook-v1-2
description: >-
  Antigravity v1.2 멀티-엔진 룩북·자동화 통합 작업트리 스킬. Tier 0 로컬 0토큰 선제 처리,
  Part B 3차(43초 컷) 웹 Gemini 초고속 2장 첨부, 직물 텍스처 최우선 게이트 및 불합격 시
  강력 리셋·자가교정(prompt_patches.json), 이중 검증(truth_verifier.py + 이종 엔진 감시),
  JACC(2,000토큰 이상 Verbatim 컨텍스트 압축) 서브모듈을 통합 제공한다.
---

# Antigravity Lookbook & Multi-Engine Workflow (`v1.2`)

최소 토큰·초고속 처리·평균 이상 품질을 목표로 설계된 **Antigravity `v1.2` 멀티-엔진 통합 작업트리 스킬**입니다.

## 1. 핵심 아키텍처 (`v1.2` 표준)

1. **Tier 0 선제 차단 (0토큰 로컬 처리)**
   - 결정적 작업(폴더 초기화, 모델 로드·SHA-256 검증, OpenCV 별 워터마크 제거, 3대 플랫폼 규격 변환, 수치/해시 검증)은 LLM을 호출하지 않고 `scripts/` 로컬 스크립트로 0토큰 처리한다.
   - 주요 스크립트:
     - `scripts/task_tree_router.py` — 4대 업무(룩북 생성·외부 다운로드 정돈·스킬/도구 제작·의류 홍보 SNS) 자동 라우팅
     - `scripts/lookbook_postprocess.py` — 표준 폴더 초기화(`--init-product`), 워터마크 제거, 3대 플랫폼 규격 변환(스마트스토어 `1000×1000` 패딩 · 카카오스타일 `1080×1296` · 에이블리 `900×1080`)
     - `scripts/truth_verifier.py` — 게이트 1(0토큰 객관적 수치·exit code·파일 증거 검증)
2. **JACC 컨텍스트 압축 서브모듈 (`scripts/jacc.py`, `scripts/ingest_transcript.py`)**
   - 단독 워크플로우가 아닌 **`v1.2` 내장 서브모듈**로 작동한다.
   - 노드 간 전달 컨텍스트가 **2,000토큰 이상**이거나 세션 인수인계·쿼터 스왑 시에만 호출해 원문 스팬(Verbatim 100%)을 추출→판정→조립 방식으로 압축한다. (2,000토큰 미만은 스킵)
   - 상세 스펙: `references/JACC_SUBMODULE_SKILL.md`

## 2. 룩북 생성 표준 프로토콜

### 2.1 사전 확인 및 치수 명시 (필수)
1. 생성 시작 전 `ask_question`으로 ① **모델 성별·번호**(여성 모델 1~4번 / 남성메인모델)와 ② **생성 컷 범위**를 확인한다.
2. 채택된 모델의 신체 스펙(`스펙.json`)과 의류 세부 사이즈 치수를 영문 프롬프트 텍스트에 직접 명시한다. (`references/LOOKBOOK_PROMPTS_EN.md` 참조)
3. 포즈·코디는 `references/룩북_포즈라이브러리.md`, `references/룩북_코디라이브러리.md`의 코드(`P=`, `O=`)로 지정하고, 코드에 해당하는 구도·의상 설명을 영문 프롬프트에 반영한다.
4. 웹 Gemini에는 **정확히 2장(Image 1 모델 사진 + Image 2 상품 행거샷)**만 첨부하고, 나머지 모든 조건은 텍스트 프롬프트로 작성한다.

### 2.2 규모별 실행 분기
- **소규모 (1~2색상 · 총 6컷 이하)**: `swarm` 오버헤드 없이 단일 턴에서 구조화 영문 프롬프트 작성 → `Part B 3차` 고속 첨부 → 1컷 합격 시 같은 채팅에서 재첨부 없이(0초) 2~N컷 연속 생성 → `lookbook_postprocess.py` 0토큰 후처리.
- **대규모 (3색상 이상 또는 총 7컷 이상)**: `swarm` 병렬 팬아웃(색상별 1컷 마스터 + 동일 색상 2~N컷 포즈 변주 독립 쿼터 풀 병렬) → 자동 생성 → 0토큰 후처리.

### 2.3 `Part B 3차` (`43초` 컷) 웹 Gemini 초고속 첨부
- 상세 절차: `references/IMAGE_SEARCH_FAST_ATTACH.md`
- `00_제미나이_첨부용_2장/` 폴더에 확정된 2장을 복사해 Google Drive **최근 문서함(Recent)** 최상단에 노출시킨 뒤, 검색창 입력 없이 0토큰 Python 필터로 스냅샷 `uid`를 추출하여 `dblClick: true`로 즉시 삽입한다.

### 2.4 직물 텍스처 최우선 게이트 & 불합격 강력 리셋
- **1순위 게이트**: 원단의 직물 텍스처(조직·질감·결)가 사실적으로 구현되지 않으면 다음 컷으로 절대 진행하지 않는다.
- **불합격 시 즉시 리셋**: 기존 채팅에서 누적 수정하지 않고 즉시 새 채팅(`https://gemini.google.com/app`, `ignoreCache: true` / `Ctrl+Shift+R`)을 연 뒤, 실패 원인을 `scripts/prompt_patches.json`에 영구 패치로 등록하고 재시도한다.

## 3. 이중 검증 게이트 (필수)
- **게이트 1**: `scripts/truth_verifier.py` 기반 0토큰 객관적 검증(파일 존재, 해상도, 용량, exit code, 해시).
- **게이트 2**: 이종 엔진 교차 감시(증거 없는 완료·정상 보고 금지).

## 4. 참고 문서 (`references/`)
- `references/WORKSPACE_GEMINI_v1.2.md` — 워크스페이스 통합 지침 전문 (`v1.2`)
- `references/IMAGE_SEARCH_FAST_ATTACH.md` — 이미지 서칭 0초화 및 `Part B 3차` 43초 컷 첨부 지침
- `references/LOOKBOOK_PROMPTS_EN.md` — 룩북 생성 표준 영문 프롬프트 템플릿
- `references/JACC_SUBMODULE_SKILL.md` — JACC Verbatim 컨텍스트 압축 서브모듈 스펙
- `references/룩북_포즈라이브러리.md` — 포즈 130종 코드표 (`LB P=W_DN12` 형식으로 호출, 룩북 생성 시 포즈 선택에 사용)
- `references/룩북_코디라이브러리.md` — 체형별 코디 200종 코드표 (`LB O=W_TOP12` 형식, 포즈 코드와 `LB P=W_DN07 O=W_TOP12` 처럼 함께 사용)
