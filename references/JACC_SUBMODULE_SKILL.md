---
name: jacc
description: >-
  Jev-Anchored Context Compression(JACC) 스킬. 긴 대화 및 작업 컨텍스트(2,000토큰 이상)를
  Jev(TypeSafe System One)의 원자적 판정으로 추출(Extract)→판정(Judge)→조립(Assemble)하여
  구조화된 레코드(jacc-record.json)로 압축할 때 사용한다.
---

# JACC — Jev-Anchored Context Compression

## 1. 개요

긴 대화 및 작업 컨텍스트를 `Jev`(TypeSafe System One)의 원자적 판정으로 압축하여 구조화된 레코드(JSON)로 변환하는 스킬.

압축의 본질은 **"요약(생성)"이 아니라 "추출(Extract) → 판정(Judge) → 조립(Assemble)"** 이다.

* **핵심 원칙**: 산문을 생성하지 않는다. 레코드의 모든 `text`는 원문(verbatim)에서 잘라낸 스팬이어야 한다.

## 2. 실행 환경 및 모드

- **실행 파일**: `jacc.py` (Python 3.10+, 외부 패키지 의존성 없음)
- **설치 위치(고정)**: `G:\내 드라이브\Antigravity_산출물\JACC\jacc.py` (기록: `G:\내 드라이브\Antigravity_산출물\JACC\records\`, 원장: `G:\내 드라이브\Antigravity_산출물\JACC\ledger.jsonl`). 실행: `py -3 "G:\내 드라이브\Antigravity_산출물\JACC\jacc.py" --input window.md --turn N` / 자체시험: `--selftest` / API 모드: `--mode api`. 스킬 폴더에는 실행 파일이 없다. 검색하지 말고 이 경로를 쓴다.
- **작동 범위 (`v1.2` 통합)**: `JACC`는 단독 이미지 생성/업무 매커니즘이 아니라 **`v1.2` 멀티-엔진 작업트리 내부의 2,000토큰 이상 컨텍스트 압축·인수인계 전용 서브모듈**로만 작동한다.
- **입력**: 텍스트 파일 (`window.md` 등), `--turn` (현재 대화 턴 수)
- **모드**:
  - `api`: `TYPESAFE_API_KEY` 존재 시 실제 `jev-latest` 호출. `confidence`와 `choice`를 신뢰함.
  - `sim`: 키가 없을 때의 시뮬레이션. 정규식/키워드 휴리스틱 사용. `band`(high/mid/low)로만 기록.

## 3. 파이프라인

1. **윈도우 조립**: `state={digest, window(마지막 N턴), unit_map}`. 원장(ledger) 본체는 포함하지 않고 `ledger_pointer`만 유지.
2. **후보 분해(Extract)**: 코드가 정규식(`RE_PATH`, `RE_ERR`)과 키워드로 후보를 `u1..uN`으로 쪼갬. 섹션별 최대 40개 제한, 잘린 후보는 `parked`에 보존.
3. **배치 판정(Judge)**: 카탈로그의 모든 질문을 Jev에 **단일 요청**으로 병렬 전송 (네트워크 왕복 최소화).
4. **라우팅 및 조립(Assemble)**: 임계값에 따라 포함/제외/`[미확정]` 마커 부착 후 JSON 생성.
5. **프로브(Probe)**: `compression_sufficient` 및 아티팩트 검증 질문으로 자체 품질 검사. 실패 시 `parked` 승격 후 재시도.
6. **증분 병합**: 해시 중복 제거, 삭제 대신 `superseded` 배열로 이동.

## 4. 예산 및 트리거 (중요)

- **최소 크기**: 소스가 2,000토큰 미만이면 압축을 거부(`skipped`)한다. (구조 오버헤드가 원본보다 커짐)
- **예산 공식**: `budget = OVERHEAD_FLOOR(450) + 10% of source_tokens`.
- **예산 집행**: 예산 초과 시 다음 순서로 자름.
  1. `misc` → 2. `parked` → 3. `evidence` 1개로 축소 → 4. `root_cause`/`next_actions`/`decisions` 1개로 축소 → 5. `artifacts` 최소 1개.
  - 단, `intent`와 `redactions`는 절대 삭제하지 않음.
- **메타데이터**: 실제 API 호출 시 `usage.input_tokens`는 `rec["cost"]`에만 기록하고 예산 계산에는 사용하지 않는다(질문 중복 때문에 부풀려져 있음).

## 5. Jev 질문 카탈로그 (핵심)

| 섹션 | 질문 ID | 타입 | 내용 및 포커스 |
|---|---|---|---|
| **의도** | `intent_present` | noul | `window`에 목표 진술이 있는가 |
| | `intent_unit` | choice | 의도를 진술하는 단위 선택 |
| **원인** | `cause_present` | noul | 원인을 지목하는가 |
| | `cause_unit` | choice | 원인을 진술하는 단위 선택 (intent와 중복 배제) |
| | `cause_is_hypothesis` | noul | 확정된 사실인가, 가설인가 |
| **아티팩트** | `path_is_artifact__*` | noul | 의존하는 파일/키인가 (단순 언급 제외) |
| | `artifact_change__*` | choice | read/created/modified/deleted/failed |
| **결정** | `decision_present` | noul | 향후 행동을 바꾸는 선택인가 |
| | `decision_unit` | choice | 결정 단위 선택 |
| **다음 할 일** | `next_action_present` | noul | 구체적 다음 행동이 있는가 |
| **안전** | `contains_secret__*` | noul | 비밀번호/키/개인정보 포함 여부 (0.3 이상이면 무조건 삭제) |

## 6. 융합(임계값) 규칙

- **Noul**: `≥ 0.7` 포함 / `≤ 0.3` 제외 / 그 사이는 `[미확정]` 마커 부착.
- **Choice**: `confidence ≥ 0.80` 자동 선택 / `0.60 ~ 0.80` 미확정 / `< 0.60` 드롭.
- **신뢰도의 의미**: confidence는 '정답 확률'이 아니라 '분포 집중도'이므로, 단독으로 삭제 결정을 내리지 않고 코드 규칙을 병행한다.

## 7. 레코드 스키마 (jacc-record.json)

```json
{
  "schema": "jacc/1",
  "mode": "api",
  "compressed_at": {"turn": 12, "unit_count": 240, "event_range": ["e1", "e99"]},
  "intent": [{"text": "...", "unit": "u1", "noul": 0.91, "state": "confirmed"}],
  "root_cause": [{"text": "...", "unit": "u2", "state": "hypothesis", "marker": "[미확정]"}],
  "artifacts": [
    {"path": "src/auth.py", "change": "modified", "unit": "u4", "anchor": "<uuid>", "confidence": 0.85, "evidence": [{"unit": "u5", "text": "..."}]}
  ],
  "decisions": [{"text": "...", "unit": "u8", "confidence": 0.88, "scope": "module"}],
  "open": {"next_actions": [...], "blocked_on_user": false, "questions": []},
  "redactions": ["u10"],
  "parked": ["u11"],
  "budget": {"record_tokens": 625, "budget_tokens": 920, "over": false},
  "cost": {"request_input_tokens": 19917, "request_output_tokens": 2832},
  "emulated": false
}
```
