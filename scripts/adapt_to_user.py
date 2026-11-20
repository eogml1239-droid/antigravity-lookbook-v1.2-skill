#!/usr/bin/env python3
"""
Antigravity v1.2 Skill Onboarding Scanner & Adapter (0-Token Local Tool)
- Scans a new user's existing workspace to infer domain, folder conventions,
  file types, and existing instruction files.
- Generates a personalized v1.2 SKILL.md and custom_workflow_config.json
  tailored to the user's workflow without modifying original skill files.
"""

import argparse
import collections
import datetime
import json
import os
import re
import sys
import tempfile

IGNORE_DIRS = {
    ".git", "node_modules", "__pycache__", ".venv", "venv", ".idea", ".vscode",
    "dist", "build", ".next", ".cache", "tmp", "temp"
}

DOMAIN_EXTS = {
    "ecommerce_lookbook": {".jpg", ".jpeg", ".png", ".webp", ".psd", ".xlsx", ".csv"},
    "software_dev": {".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".rs", ".java", ".cpp", ".cs", ".sql"},
    "design_media": {".fig", ".ai", ".psd", ".svg", ".mp4", ".mov", ".png", ".jpg", ".webp"},
    "docs_research": {".md", ".docx", ".pdf", ".txt", ".pptx", ".xlsx", ".csv"},
}

INSTRUCTION_NAMES = {"GEMINI.md", "CLAUDE.md", "AGENTS.md", "SKILL.md", "README.md", ".cursorrules"}


def scan_workspace(target_dir: str, max_files: int = 5000) -> dict:
    target_dir = os.path.abspath(target_dir)
    if not os.path.isdir(target_dir):
        raise FileNotFoundError(f"Directory not found: {target_dir}")

    ext_counter = collections.Counter()
    top_dirs = []
    instruction_files = []
    sample_names = []
    total_files = 0
    date_pattern_hits = collections.Counter()

    for item in sorted(os.listdir(target_dir)):
        full = os.path.join(target_dir, item)
        if os.path.isdir(full) and item not in IGNORE_DIRS:
            top_dirs.append(item)

    for dp, dns, fns in os.walk(target_dir):
        dns[:] = [d for d in dns if d not in IGNORE_DIRS]
        for fn in fns:
            total_files += 1
            if total_files > max_files:
                break
            rel = os.path.relpath(os.path.join(dp, fn), target_dir)
            _, ext = os.path.splitext(fn)
            ext = ext.lower()
            if ext:
                ext_counter[ext] += 1
            if fn in INSTRUCTION_NAMES:
                instruction_files.append(rel)
            if len(sample_names) < 25:
                sample_names.append(rel)
            if re.search(r"20\d{2}년\s*\d{1,2}월\s*\d{1,2}일", rel):
                date_pattern_hits["korean_date"] += 1
            elif re.search(r"20\d{2}-\d{2}-\d{2}", rel):
                date_pattern_hits["iso_date"] += 1
            elif re.search(r"20\d{6}", rel):
                date_pattern_hits["compact_yyyymmdd"] += 1
        if total_files > max_files:
            break

    # Score domains
    domain_scores = {}
    for dom, exts in DOMAIN_EXTS.items():
        domain_scores[dom] = sum(ext_counter[e] for e in exts)
    primary_domain = max(domain_scores, key=domain_scores.get) if any(domain_scores.values()) else "general"

    naming_style = date_pattern_hits.most_common(1)[0][0] if date_pattern_hits else "standard"

    return {
        "schema": "v1.2-user-profile/1",
        "scanned_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "workspace_root": target_dir,
        "total_files_scanned": total_files,
        "primary_domain": primary_domain,
        "domain_scores": domain_scores,
        "top_extensions": ext_counter.most_common(12),
        "top_level_folders": top_dirs[:30],
        "existing_instruction_files": instruction_files[:20],
        "naming_convention": naming_style,
        "sample_paths": sample_names[:15],
    }


def generate_personalized_skill(profile: dict, out_dir: str) -> dict:
    os.makedirs(out_dir, exist_ok=True)
    dom = profile.get("primary_domain", "general")
    ws = profile.get("workspace_root", "")
    naming = profile.get("naming_convention", "standard")
    top_folders = profile.get("top_level_folders", [])
    existing_docs = profile.get("existing_instruction_files", [])

    domain_presets = {
        "software_dev": {
            "title": "소프트웨어 개발 맞춤형 v1.2 작업트리",
            "quality_gate": "단위 테스트 통과(exit code 0) · 린트/타입체크 오류 0건 · 변경 diff 증거 확인",
            "tier0_tasks": "파일 검색, 테스트 실행, 포맷터/린터, 빌드 검증, 해시/라인 수 집계",
            "batch_rule": "단일 모듈/3파일 이하는 단일 턴 처리, 4모듈 이상 대규모 리팩토링은 병렬 팬아웃",
        },
        "ecommerce_lookbook": {
            "title": "이커머스·상품·이미지 맞춤형 v1.2 작업트리",
            "quality_gate": "상품 원단·색상·디테일 정확도 최우선 · 규격(해상도/용량) 0오류 검증",
            "tier0_tasks": "폴더 초기화, 이미지 리사이즈/크롭, 워터마크 제거, 파일명 정규화, 엑셀/CSV 집계",
            "batch_rule": "소규모(6건 이하)는 단일 턴 고속 처리, 대규모(7건 이상)는 병렬 팬아웃",
        },
        "design_media": {
            "title": "디자인·미디어 제작 맞춤형 v1.2 작업트리",
            "quality_gate": "해상도·비율·색감 일관성 1순위 게이트 · 육안 비교 시트 확인 후 일괄 적용",
            "tier0_tasks": "에셋 정리, 일괄 포맷/해상도 변환, 썸네일/비교 시트 생성, 메타데이터 검증",
            "batch_rule": "샘플 1~3건 우선 승인 후 전체 에셋 일괄 배치 적용",
        },
        "docs_research": {
            "title": "문서·리서치·데이터 맞춤형 v1.2 작업트리",
            "quality_gate": "원문 근거·수치 100% 대조(추정치 실측 표기 금지) · 포맷 정합성 검증",
            "tier0_tasks": "CSV/JSON/Markdown 파싱, 통계 집계, 목차/인덱스 자동 갱신, 중복 검사",
            "batch_rule": "단일 보고서는 단일 턴 작성, 다수 문서/소스 분석은 병렬 요약 후 JACC 압축",
        },
        "general": {
            "title": "범용 맞춤형 v1.2 작업트리",
            "quality_gate": "요구사항 충족 여부 객관 검증(exit code · 파일 존재 · 용량 확인)",
            "tier0_tasks": "폴더/파일 정리, 반복 변환, 수치 계산 및 결과 검증",
            "batch_rule": "소규모 작업은 단일 턴, 대규모 반복 작업은 스크립트/병렬 처리",
        },
    }
    preset = domain_presets.get(dom, domain_presets["general"])

    config = {
        "schema": "v1.2-personalized-config/1",
        "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "workspace_root": ws,
        "primary_domain": dom,
        "naming_convention": naming,
        "quality_gate_primary": preset["quality_gate"],
        "tier0_zero_token_tasks": preset["tier0_tasks"],
        "scale_branch_rule": preset["batch_rule"],
        "jacc_min_tokens": 2000,
        "detected_folders": top_folders[:15],
        "detected_instruction_files": existing_docs,
    }
    cfg_path = os.path.join(out_dir, "custom_workflow_config.json")
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)

    folders_md = "\n".join(f"- `{d}/`" for d in top_folders[:10]) if top_folders else "- (최상위 폴더 없음)"
    docs_md = "\n".join(f"- `{d}`" for d in existing_docs[:10]) if existing_docs else "- (기존 지침 파일 없음)"

    skill_md = f"""---
name: personalized-v1-2-workflow
description: >-
  사용자 워크스페이스({dom}) 스캔 결과를 바탕으로 자동 변형된 Antigravity v1.2 멀티-엔진 작업트리 스킬.
  Tier 0 0토큰 로컬 처리, 2,000토큰 이상 JACC Verbatim 압축, 이중 검증 게이트를 사용자 작업 형식에 맞게 적용한다.
---

# {preset["title"]}

> 자동 생성 시각: `{config["generated_at"]}`  
> 기준 워크스페이스: `{ws}`  
> 감지된 주 도메인: `{dom}` / 파일명 규칙: `{naming}`

## 1. 궁극적 목표
- 같은 작업을 하더라도 **훨씬 더 적은 토큰으로 평균 이상의 결과값**을 만든다.
- 반복적·결정적 작업은 LLM을 부르지 않고 **Tier 0 로컬 스크립트(0토큰)**로 선제 처리한다.

## 2. 사용자 맞춤 `v1.2` 실행 규칙
- **Tier 0 (0토큰 처리 대상)**: {preset["tier0_tasks"]}
- **규모별 실행 분기**: {preset["batch_rule"]}
- **1순위 품질 게이트**: {preset["quality_gate"]}
- **JACC 컨텍스트 압축 서브모듈**: 대화·전달 컨텍스트가 **2,000토큰 이상**일 때만 `jacc.py`로 원문 스팬(Verbatim) 압축 (2,000토큰 미만은 스킵).
- **이중 검증 의무화**: 객관적 수치·exit code·파일 존재 증거(`truth_verifier.py`) 없는 완료 보고 금지.

## 3. 스캔된 기존 작업 구조
### 주요 상위 폴더
{folders_md}

### 기존 지침·문서 파일 (우선 존중)
{docs_md}

## 4. 사용자 맞춤 수정 안내
- 이 파일은 스캔 결과를 바탕으로 생성된 1차 맞춤 초안입니다.
- 저장 경로, 출력 규격, 금지 사항 등 추가 선호 조건이 있으면 에이전트에게 말씀해 즉시 보완하세요.
"""
    skill_path = os.path.join(out_dir, "PERSONALIZED_SKILL.md")
    with open(skill_path, "w", encoding="utf-8") as f:
        f.write(skill_md)

    return {"config_path": cfg_path, "skill_path": skill_path, "primary_domain": dom}


def selftest() -> int:
    with tempfile.TemporaryDirectory() as td:
        os.makedirs(os.path.join(td, "src"), exist_ok=True)
        with open(os.path.join(td, "README.md"), "w", encoding="utf-8") as f:
            f.write("# Sample Project\n")
        with open(os.path.join(td, "src", "app.py"), "w", encoding="utf-8") as f:
            f.write("print('ok')\n")
        prof = scan_workspace(td)
        assert prof["primary_domain"] == "software_dev", prof
        out_sub = os.path.join(td, "_personalized")
        res = generate_personalized_skill(prof, out_sub)
        assert os.path.exists(res["skill_path"]) and os.path.exists(res["config_path"])
    print("SELFTEST_OK")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Antigravity v1.2 Skill Onboarding Scanner & Adapter")
    ap.add_argument("--scan", help="Path to user's existing workspace to scan")
    ap.add_argument("--out", default="user_workflow_profile.json", help="Output profile JSON path")
    ap.add_argument("--profile", help="Existing profile JSON path for generation")
    ap.add_argument("--generate", help="Output folder for personalized v1.2 skill files")
    ap.add_argument("--selftest", action="store_true", help="Run built-in self-test")
    args = ap.parse_args()

    if args.selftest:
        return selftest()

    prof = None
    if args.scan:
        prof = scan_workspace(args.scan)
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(prof, f, ensure_ascii=False, indent=2)
        print(f"SCANNED: {args.scan} -> {args.out} (domain={prof['primary_domain']}, files={prof['total_files_scanned']})")

    if args.generate:
        if prof is None:
            if not args.profile:
                print("ERROR: --generate requires --scan or --profile", file=sys.stderr)
                return 2
            with open(args.profile, encoding="utf-8") as f:
                prof = json.load(f)
        res = generate_personalized_skill(prof, args.generate)
        print(f"GENERATED: {res['skill_path']} | {res['config_path']} (domain={res['primary_domain']})")

    if not args.scan and not args.generate:
        ap.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
