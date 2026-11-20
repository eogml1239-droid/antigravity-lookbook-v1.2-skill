#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""task_tree_router.py - Tier 0 (0-token) deterministic multi-engine task tree router for Antigravity + JACC.

Zero external dependencies. Python 3.10+.
Routes tasks across Antigravity engines (Opus 5.5, Sonnet 5.5, Argon, Neon, Hydrogen, 3.8 Flash, GPT-OSS 120B)
with JACC >=2000 token compression gate, DAG parallel fan-out, and mandatory dual verification gates.

Usage:
  py -3 task_tree_router.py --selftest
  py -3 task_tree_router.py --domain lookbook --tokens 3200 --cuts 3 --colors 2
  py -3 task_tree_router.py --domain files --tokens 400
  py -3 task_tree_router.py --domain skill --tokens 4500
  py -3 task_tree_router.py --domain sns --tokens 1800 --platforms naver,insta,kakao,ably
"""
from __future__ import annotations
import argparse
import json
import os
import sys
import time

JACC_DIR = os.path.dirname(os.path.abspath(__file__))
JACC_ENGINE = os.path.join(JACC_DIR, "jacc.py")
MIN_JACC_TOKENS = 2000

ENGINE_CATALOG = {
    "tier0": {"id": "local-python", "group": "LOCAL", "cost_tier": 0},
    "flash_low": {"id": "gemini-3.8-flash-low", "group": "C", "cost_tier": 1},
    "flash_med": {"id": "gemini-3.8-flash-medium", "group": "C", "cost_tier": 1},
    "hydrogen_med": {"id": "gemini-4-hydrogen-medium", "group": "C", "cost_tier": 2},
    "neon_med": {"id": "gemini-4-neon-medium", "group": "C", "cost_tier": 2},
    "argon_med": {"id": "gemini-4-argon-medium", "group": "B", "cost_tier": 2},
    "argon_high": {"id": "gemini-4-argon-high", "group": "B", "cost_tier": 3},
    "sonnet_med": {"id": "claude-sonnet-5-5-medium", "group": "A", "cost_tier": 2},
    "sonnet_high": {"id": "claude-sonnet-5-5-high", "group": "A", "cost_tier": 3},
    "opus_high": {"id": "claude-opus-5-5-high", "group": "A", "cost_tier": 3},
    "gpt_oss": {"id": "gpt-oss-120b-medium", "group": "A", "cost_tier": 2},
    "browser_flash": {"id": "subagent:browser(flash)", "group": "C", "cost_tier": 1},
}

FALLBACK_MAP = {
    "claude-opus-5-5-high": "gemini-4-argon-high",
    "claude-sonnet-5-5-high": "gemini-4-neon-high",
    "claude-sonnet-5-5-medium": "gemini-4-hydrogen-medium",
    "gemini-4-argon-medium": "claude-sonnet-5-5-medium",
    "gemini-4-argon-high": "claude-opus-5-5-high",
    "gemini-4-neon-medium": "gemini-4-argon-medium",
    "gemini-4-hydrogen-medium": "gemini-4-argon-medium",
    "gemini-3.8-flash-low": "gemini-4-argon-low",
    "gpt-oss-120b-medium": "gemini-4-argon-medium",
}


def node(nid: str, role: str, engine_key: str, task: str, parallel: bool = False) -> dict:
    eng = ENGINE_CATALOG[engine_key]
    return {
        "id": nid,
        "role": role,
        "engine": eng["id"],
        "quota_group": eng["group"],
        "cost_tier": eng["cost_tier"],
        "fallback": FALLBACK_MAP.get(eng["id"], "none"),
        "parallel": parallel,
        "task": task,
    }


def build_plan(
    domain: str,
    tokens: int,
    cuts: int = 3,
    colors: int = 1,
    platforms: list[str] | None = None,
    ambiguous_files: bool = False,
) -> dict:
    t0 = time.perf_counter()
    use_jacc = tokens >= MIN_JACC_TOKENS
    waves: list[dict] = []

    # Wave 0: Zero-token local gate + optional JACC compression
    w0_nodes = [
        node("W0_LOCAL", "Tier 0 Local Gate", "tier0", "입력 검증·파일/수치 로드·캐시/토큰 체크")
    ]
    if use_jacc:
        w0_nodes.append(
            node(
                "W0_JACC",
                "JACC Verbatim Compressor",
                "tier0",
                f'py -3 "{JACC_ENGINE}" --input window.md (원문 스팬 100% 압축 패킷 생성)',
            )
        )
    waves.append({"wave": 0, "mode": "sequential", "nodes": w0_nodes})

    bypass_llm = False

    if domain == "lookbook":
        total_cuts = max(1, colors) * max(1, cuts)
        use_swarm = (colors >= 3) or (total_cuts >= 7)
        if not use_swarm:
            # v1.2 A/B benchmark confirmed: small batch (1-2 colors, <=6 cuts) avoids swarm overhead
            waves.append({
                "wave": 1,
                "mode": "sequential",
                "nodes": [
                    node(
                        "A1_SINGLE_TURN_BATCH",
                        "Single-Turn Batch Prompt (v1.2 Optimal)",
                        "opus_high",
                        f"{colors}색상 × {cuts}컷(총 {total_cuts}컷) 영문 프롬프트 단일 턴 일괄 작성(스웜 오버헤드 제거, 직물 텍스처 1순위·치수 텍스트 명시)",
                    )
                ],
            })
            waves.append({
                "wave": 2,
                "mode": "sequential",
                "nodes": [
                    node(
                        "A2_STAGE_AND_USER_PASTE",
                        "Zero-Token 2-Image Folder Staging",
                        "tier0",
                        "00_제미나이_첨부용_2장 폴더 생성 → 사용자 사이드바 웹 Gemini 2장 첨부 & 원클릭 복붙 → 육안 합격 판정(합격 시 AI 검수 0토큰)",
                    ),
                    node(
                        "A3_ZERO_TOKEN_POSTPROCESS",
                        "Zero-Token Approved Postprocess",
                        "tier0",
                        "합격본만 lookbook_postprocess.py 실행 (OpenCV 워터마크 제거 + 네이버/카카오스타일/에이블리 3종 규격 변환)",
                    ),
                ],
            })
            gate2_engine = None
        else:
            # Large batch (3+ colors or 7+ cuts): parallel swarm fan-out justifies coordination cost
            waves.append({
                "wave": 1,
                "mode": "parallel",
                "nodes": [
                    node(
                        f"A1_MASTER_C{c}",
                        "Lookbook Master Prompt (Cut 1)",
                        "opus_high",
                        f"색상 {c} 1컷 마스터 영어 프롬프트 설계(직물 텍스처 1순위·모델/사이즈 수치·중력·호리존·윗입술 크롭)",
                        parallel=True,
                    )
                    for c in range(1, max(1, colors) + 1)
                ],
            })
            if cuts > 1:
                waves.append({
                    "wave": 2,
                    "mode": "parallel",
                    "nodes": [
                        node(
                            f"A2_VARIANT_C{c}_P2_{cuts}",
                            f"Pose Variants (Cut 2~{cuts})",
                            "argon_med",
                            f"색상 {c} 2~{cuts}컷 포즈·시선·손 위치 변주 프롬프트 병렬 생성(독립 Group B 쿼터)",
                            parallel=True,
                        )
                        for c in range(1, max(1, colors) + 1)
                    ],
                })
            waves.append({
                "wave": 3,
                "mode": "sequential",
                "nodes": [
                    node(
                        "A3_POSTPROCESS_BATCH",
                        "Zero-Token Batch Postprocess",
                        "tier0",
                        "00_제미나이_첨부용_2장 스테이징 + 합격본 일괄 lookbook_postprocess.py 0토큰 후처리",
                    )
                ],
            })
            gate2_engine = "argon_med"

    elif domain == "files":
        if not ambiguous_files:
            bypass_llm = True
            waves.append({
                "wave": 1,
                "mode": "sequential",
                "nodes": [
                    node(
                        "B0_AUTO_SORT",
                        "Zero-Token File Organizer",
                        "tier0",
                        "다운로드 파일 자동 분류·표준 폴더 생성·리네임·_INDEX.md 등록 (0토큰 고속 우회)",
                    )
                ],
            })
            gate2_engine = None
        else:
            waves.append({
                "wave": 1,
                "mode": "sequential",
                "nodes": [
                    node(
                        "B1_TRIAGE",
                        "Ambiguous File Classifier",
                        "flash_low",
                        "모호한 파일명만 상품명·색상 1줄 경량 분류",
                    )
                ],
            })
            gate2_engine = None

    elif domain == "skill":
        waves.append({
            "wave": 1,
            "mode": "sequential",
            "nodes": [
                node(
                    "C1_ARCH",
                    "Skill Architecture & KPI",
                    "argon_high",
                    "스킬 아키텍처·실패 모드·객관적 검증 기준(KPI) 설계",
                )
            ],
        })
        waves.append({
            "wave": 2,
            "mode": "sequential",
            "nodes": [
                node(
                    "C2_IMPL",
                    "Skill & Verifier Implementation",
                    "sonnet_high",
                    "SKILL.md, 실행 스크립트, 전용 객관적 검증 툴(verify_*.py) 동시 구현",
                )
            ],
        })
        gate2_engine = "gpt_oss"

    elif domain == "sns":
        plats = platforms or ["naver", "insta", "kakao", "ably"]
        waves.append({
            "wave": 1,
            "mode": "sequential",
            "nodes": [
                node(
                    "D1_BRIEF",
                    "Product Fact Brief",
                    "neon_med",
                    "Tier 0 팩트 시트 기반 핵심 소구점·금지어 브리프 1회 정리",
                )
            ],
        })
        plat_nodes = []
        for p in plats:
            pl = p.strip().lower()
            if pl in ("naver", "blog", "smartstore"):
                ek = "sonnet_med"
            elif pl in ("insta", "instagram", "threads", "x"):
                ek = "flash_med"
            else:
                ek = "hydrogen_med"
            plat_nodes.append(
                node(
                    f"D2_COPY_{pl.upper()}",
                    f"SNS Copy ({pl})",
                    ek,
                    f"{pl} 플랫폼 가이드라인·분위기 맞춤 홍보 게시글 병렬 작성",
                    parallel=True,
                )
            )
        waves.append({"wave": 2, "mode": "parallel", "nodes": plat_nodes})
        waves.append({
            "wave": 3,
            "mode": "sequential",
            "nodes": [
                node(
                    "D3_DEPLOY",
                    "Browser SNS Publisher",
                    "browser_flash",
                    "사용자 승인본 에고브라우저(내장 브라우저)로 플랫폼별 입력·배포",
                )
            ],
        })
        gate2_engine = "gpt_oss"
    else:
        raise ValueError(f"Unsupported domain: {domain}")

    # Mandatory Gate 1 (Deterministic Verifier - Tier 0)
    gate_nodes = [
        node(
            "GATE1_VERIFIER",
            "Gate 1: Deterministic Verifier",
            "tier0",
            "truth_verifier.py 실행 (파일·바이트·SHA256·exit code·Verbatim 100%·미증빙 보고 차단)",
        )
    ]
    waves.append({"wave": len(waves), "mode": "sequential", "nodes": gate_nodes})

    # Mandatory Gate 2 (Cross-Family Truth Watcher) for LLM tasks
    if gate2_engine:
        waves.append({
            "wave": len(waves),
            "mode": "sequential",
            "nodes": [
                node(
                    "GATE2_TRUTH_WATCHER",
                    "Gate 2: Cross-Family Truth Watcher",
                    gate2_engine,
                    "작성 엔진과 다른 패밀리가 주장(Claim) vs 실측 증거(Evidence) 교차 감사 (실패 시 반려)",
                )
            ],
        })

    # Metrics summary (structural, measured deterministically)
    all_nodes = [n for w in waves for n in w["nodes"]]
    total_nodes = len(all_nodes)
    tier0_nodes = sum(1 for n in all_nodes if n["cost_tier"] == 0)
    parallel_nodes = sum(1 for n in all_nodes if n["parallel"])
    quota_groups = sorted({n["quota_group"] for n in all_nodes if n["quota_group"] != "LOCAL"})
    elapsed_ms = round((time.perf_counter() - t0) * 1000, 3)

    return {
        "schema": "antigravity-task-tree/1.2",
        "domain": domain,
        "input_tokens": tokens,
        "jacc_compress_required": use_jacc,
        "zero_token_bypass": bypass_llm,
        "waves": waves,
        "metrics": {
            "total_waves": len(waves),
            "total_nodes": total_nodes,
            "tier0_zero_token_nodes": tier0_nodes,
            "parallel_fanout_nodes": parallel_nodes,
            "active_quota_groups": quota_groups,
            "router_latency_ms": elapsed_ms,
        },
    }


def selftest() -> int:
    cases = [
        ("lookbook", 1800, 3, 1, None, False),  # small batch -> single-turn optimal (v1.2)
        ("lookbook", 3200, 3, 3, None, False),  # large batch -> parallel swarm (v1.2)
        ("files", 400, 1, 1, None, False),
        ("skill", 4500, 1, 1, None, False),
        ("sns", 1800, 1, 1, ["naver", "insta", "kakao", "ably"], False),
    ]
    results = []
    for dom, tok, cuts, cols, plats, amb in cases:
        plan = build_plan(dom, tok, cuts=cuts, colors=cols, platforms=plats, ambiguous_files=amb)
        assert plan["metrics"]["total_nodes"] >= 3
        assert any(n["id"] == "GATE1_VERIFIER" for w in plan["waves"] for n in w["nodes"])
        if dom == "files":
            assert plan["zero_token_bypass"] is True
            assert plan["metrics"]["active_quota_groups"] == []
        if dom == "lookbook" and cols == 1:
            ids = {n["id"] for w in plan["waves"] for n in w["nodes"]}
            assert "A1_SINGLE_TURN_BATCH" in ids
            assert plan["metrics"]["parallel_fanout_nodes"] == 0
        if dom == "lookbook" and cols == 3:
            engines = {n["engine"] for w in plan["waves"] for n in w["nodes"]}
            assert "claude-opus-5-5-high" in engines
            assert "gemini-4-argon-medium" in engines
            assert plan["metrics"]["parallel_fanout_nodes"] == 6
        if dom == "sns":
            assert plan["metrics"]["parallel_fanout_nodes"] == 4
        results.append({
            "domain": f"{dom}({cols}c×{cuts})" if dom == "lookbook" else dom,
            "jacc": plan["jacc_compress_required"],
            "bypass": plan["zero_token_bypass"],
            "waves": plan["metrics"]["total_waves"],
            "nodes": plan["metrics"]["total_nodes"],
            "tier0_nodes": plan["metrics"]["tier0_zero_token_nodes"],
            "parallel_nodes": plan["metrics"]["parallel_fanout_nodes"],
            "groups": plan["metrics"]["active_quota_groups"],
            "latency_ms": plan["metrics"]["router_latency_ms"],
        })
    print(json.dumps({"selftest": "PASS", "schema": "antigravity-task-tree/1.2", "cases": results}, ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Antigravity JACC Multi-Engine Task Tree Router (Tier 0)")
    ap.add_argument("--selftest", action="store_true", help="Run built-in deterministic self-test")
    ap.add_argument("--domain", choices=["lookbook", "files", "skill", "sns"], help="Task domain")
    ap.add_argument("--tokens", type=int, default=0, help="Estimated input token count")
    ap.add_argument("--cuts", type=int, default=3, help="Number of cuts per color (lookbook)")
    ap.add_argument("--colors", type=int, default=1, help="Number of colors (lookbook)")
    ap.add_argument("--platforms", type=str, default="", help="Comma-separated SNS platforms")
    ap.add_argument("--ambiguous-files", action="store_true", help="Enable L1 fallback for ambiguous filenames")
    args = ap.parse_args()

    if args.selftest:
        return selftest()
    if not args.domain:
        ap.error("--domain is required unless --selftest is specified")

    plats = [p.strip() for p in args.platforms.split(",") if p.strip()] or None
    plan = build_plan(
        args.domain,
        args.tokens,
        cuts=args.cuts,
        colors=args.colors,
        platforms=plats,
        ambiguous_files=args.ambiguous_files,
    )
    print(json.dumps(plan, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
