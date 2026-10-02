"""端到端联调脚本（**打真实模型**）。

与 pytest 不同，这个脚本不 mock 任何东西：
真的起 HTTP 请求、真的调 VLM、真的跑后台分析任务、真的轮询。

用法：
    # 先起服务
    .venv\\Scripts\\python.exe -m uvicorn app.main:app --port 8000
    # 再跑脚本
    .venv\\Scripts\\python.exe tools\\e2e_live.py --base http://127.0.0.1:8000
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import httpx

# Windows 控制台默认 cp936，直接 print 中文/emoji 会 UnicodeEncodeError
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):  # pragma: no cover
    pass

BACKEND_ROOT = Path(__file__).resolve().parent.parent
FIXTURE = BACKEND_ROOT / "tests" / "fixtures" / "demo_question_17.png"


def show(title: str, payload: object) -> None:
    print(f"\n{'=' * 70}\n{title}\n{'=' * 70}")
    print(json.dumps(payload, ensure_ascii=False, indent=2)[:2500])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:8000")
    parser.add_argument("--timeout", type=float, default=180.0)
    args = parser.parse_args()

    client = httpx.Client(base_url=args.base, timeout=args.timeout)
    failures: list[str] = []

    def check(name: str, condition: bool, detail: str = "") -> None:
        status = "PASS" if condition else "FAIL"
        print(f"[{status}] {name}" + (f" — {detail}" if detail else ""))
        if not condition:
            failures.append(name)

    # 1) 健康检查
    health = client.get("/health").json()
    show("1. /health", health)
    check("health.ok", health["status"] == "ok", f"llm_mode={health['llm_mode']}")
    check("模型已接入", health["llm_mode"] == "live", "未配 key 或开了 Mock")
    check("题库已加载", health["question_count"] == 32, f"{health['question_count']} 题")
    check("存储后端", "mysql" in health["database"] or "sqlite" in health["database"],
          health["database"])

    # 2) Demo 用户
    demo = client.get("/api/v1/auth/demo-user").json()
    headers = {"Authorization": f"Bearer {demo['access_token']}"}
    check("demo 用户", demo["user_id"].startswith("user_"))

    # 3) 播种历史 → 确认综合应用落在 43% 附近
    seeded = client.post("/api/v1/demo/seed", headers=headers).json()
    show("3. Demo 种子后的掌握度", seeded["mastery"])
    comp = seeded["mastery"]["math.derivative.monotonicity_applications"]["mastery"]
    check("综合应用 ≈ 43%", 0.40 <= comp <= 0.47, f"实际 {comp:.1%}")

    # 4) 首页
    home = client.get("/api/v1/home", headers=headers).json()
    show("4. 首页 Next Action", home["next_action"])
    check(
        "首页指向薄弱点",
        home["next_action"]["knowledge_point_id"] == "math.derivative.monotonicity_applications",
        home["next_action"]["title"],
    )

    # 5) 真实上传 + 真实 VLM + 轮询
    print(f"\n上传 {FIXTURE.name}（真实 VLM 调用）...")
    started = time.time()
    with FIXTURE.open("rb") as handle:
        created = client.post(
            "/api/v1/homework/analyses",
            headers=headers,
            files={"images": (FIXTURE.name, handle, "image/png")},
            data={"subject": "mathematics", "source_name": "数学月考·第17题"},
        ).json()
    analysis_id = created["analysis_id"]
    check("分析任务已创建", created["status"] in ("queued", "processing"))

    detail = {}
    for _ in range(120):
        detail = client.get(
            f"/api/v1/homework/analyses/{analysis_id}", headers=headers
        ).json()
        if detail["status"] in ("completed", "failed"):
            break
        time.sleep(1.0)

    elapsed = time.time() - started
    show(f"5. 分析结果（耗时 {elapsed:.1f}s, generated_by={detail.get('generated_by')}）", {
        "status": detail.get("status"),
        "counts": {
            "correct": detail.get("correct_count"),
            "wrong": detail.get("wrong_count"),
        },
        "question_results": detail.get("question_results"),
        "knowledge_changes": detail.get("knowledge_changes"),
        "error": detail.get("error"),
        "warnings": detail.get("warnings"),
    })

    check("分析完成", detail["status"] == "completed", str(detail.get("error")))
    if detail["status"] == "completed":
        results = detail["question_results"]
        check("识别出题目", len(results) >= 1, f"{len(results)} 道")
        if results:
            first = results[0]
            check("读到学生作答", first["student_answer"] == "A", str(first["student_answer"]))
            check("判出正确答案", first["correct_answer"] == "C", str(first["correct_answer"]))
            check("判定为错误", first["correctness"] == "wrong", first["correctness"])
            check(
                "映射到知识点",
                any(
                    kp["knowledge_point_id"] == "math.derivative.monotonicity"
                    for kp in first["knowledge_points"]
                ),
                str([kp["knowledge_point_id"] for kp in first["knowledge_points"]]),
            )
        check("产生了掌握度变化", len(detail["knowledge_changes"]) > 0)
        check("错题已入库", len(detail["new_wrong_questions"]) > 0)

    # 6) Tutor 一轮（真模型只用于题目理解，问答走状态机）
    session = client.post(
        "/api/v1/tutor/sessions",
        headers=headers,
        json={
            "source_type": "knowledge_point",
            "knowledge_point_id": "math.derivative.monotonicity_applications",
        },
    ).json()
    show("6. Tutor 首轮", {
        "phase": session["phase"],
        "turn_type": session["turn"]["turn_type"],
        "text": session["turn"]["text"],
        "choices": session["turn"]["choices"],
    })
    check("Tutor 已创建", bool(session.get("tutor_session_id")))
    check("首轮是概念题", session["turn"]["turn_type"] == "concept_question")
    check("选项已结构化", len(session["turn"]["choices"]) == 4)

    # 故意答错 → 验证 Agent 改变策略
    expected = "A"
    wrong_key = next(k for k in "ABCD" if k != expected)
    turn = client.post(
        f"/api/v1/tutor/sessions/{session['tutor_session_id']}/turns",
        headers=headers,
        json={"selected_key": wrong_key},
    ).json()
    show("7. 故意答错后的 Agent 反应", {
        "evaluation": turn["evaluation"],
        "turn_type": turn["turn"]["turn_type"],
    })
    check("答错被识别", turn["evaluation"]["is_correct"] is False)
    check(
        "Agent 降级教学",
        turn["evaluation"]["strategy"] in ("simplify", "hint"),
        turn["evaluation"]["strategy"],
    )

    # 8) 练习推荐（纯算法）
    practice = client.post(
        "/api/v1/practice/sessions",
        headers=headers,
        json={"knowledge_point_id": "math.derivative.monotonicity_applications", "count": 3},
    ).json()
    show("8. 练习推荐", {
        "knowledge_point_name": practice["knowledge_point_name"],
        "total": practice["total"],
        "next_question": practice["next_question"],
    })
    check("推荐出题目", practice["next_question"] is not None)
    if practice["next_question"]:
        check(
            "未泄漏答案",
            "answer" not in practice["next_question"]
            and "explanation" not in practice["next_question"],
        )

    # 9) AI 直连接口
    ai = client.post(
        "/api/v1/ai/chat",
        headers=headers,
        json={"prompt": "用一句话解释：为什么 f'(x) > 0 说明函数单调递增？"},
    ).json()
    show("9. AI 直连", ai)
    check("AI 接口可用", bool(ai.get("reply")) and ai.get("provider") != "mock")

    print(f"\n{'=' * 70}")
    if failures:
        print(f"结果：{len(failures)} 项失败 -> {failures}")
        return 1
    print("结果：全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
