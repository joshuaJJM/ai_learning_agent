"""题库加载器。

严格遵循约定的 bank JSON 规范：

    {
      "schema_version": "1.0",
      "bank_id": "...", "bank_name": "...", "language": "zh-CN",
      "source": "...", "version": "1.0.0", "updated_at": "2026-10-01",
      "questions": [
        { "id": "...", "type": "single_choice", "stem": "...",
          "options": {"A": "...", "B": "...", "C": "...", "D": "..."},
          "answer": "B", "explanation": "...",
          "knowledge_point_ids": ["..."], "tags": ["..."],
          "source_ref": "..." }
      ]
    }

本版**只支持单选题**。`difficulty` 是可选扩展字段（1..5）；
缺省时回退到该知识点在 knowledge.py 里登记的典型难度档位。

加载器是宽容的：单条题目不合法只会被丢弃并记入 warnings，
不会让整个服务起不来。warning 会暴露在 /health 与启动日志里。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

from . import knowledge

BANKS_DIR = Path(__file__).resolve().parent / "seed" / "banks"

SUPPORTED_SCHEMA_VERSION = "1.0"
SUPPORTED_QUESTION_TYPES = ("single_choice",)


@dataclass(frozen=True)
class BankQuestion:
    id: str
    bank_id: str
    type: str
    stem: str
    options: dict[str, str]
    answer: str
    explanation: str
    knowledge_point_ids: tuple[str, ...]
    tags: tuple[str, ...]
    source_ref: str
    difficulty: float  # 归一化到 0..1

    @property
    def choice_keys(self) -> tuple[str, ...]:
        return tuple(sorted(self.options.keys()))


@dataclass
class BankMeta:
    bank_id: str
    bank_name: str
    language: str
    source: str
    version: str
    updated_at: str
    file: str
    question_count: int = 0


@dataclass
class LoadReport:
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def _resolve_difficulty(kp_ids: Sequence[str]) -> float:
    """题目难度。

    题库规范**明确禁止**在题里写 `difficulty`，所以难度由服务端按知识点兜底
    （`knowledge.py` 里每个知识点的 `default_difficulty`）。
    如果某个题库文件仍然带了 `difficulty`，加载器会忽略它并告警。
    """
    for kp_id in kp_ids:
        point = knowledge.get_point(kp_id)
        if point is not None:
            return point.default_difficulty
    return 0.5


class QuestionBank:
    def __init__(self) -> None:
        self.questions: dict[str, BankQuestion] = {}
        self.banks: dict[str, BankMeta] = {}
        self.report = LoadReport()

    # -- 查询 ---------------------------------------------------------------
    def get(self, question_id: str) -> BankQuestion | None:
        return self.questions.get(question_id)

    def all(self) -> list[BankQuestion]:
        return list(self.questions.values())

    def by_knowledge_point(self, kp_id: str) -> list[BankQuestion]:
        return [q for q in self.questions.values() if kp_id in q.knowledge_point_ids]

    def by_bank(self, bank_id: str) -> list[BankQuestion]:
        return [q for q in self.questions.values() if q.bank_id == bank_id]

    def stats(self) -> dict[str, int]:
        return {"bank_count": len(self.banks), "question_count": len(self.questions)}

    # -- 加载 ---------------------------------------------------------------
    def load(self, directory: Path | None = None) -> "QuestionBank":
        directory = directory or BANKS_DIR
        self.questions.clear()
        self.banks.clear()
        self.report = LoadReport()

        if not directory.exists():
            self.report.warnings.append(f"题库目录不存在: {directory}")
            return self

        for path in sorted(directory.glob("*.json")):
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                self.report.errors.append(f"{path.name}: 无法解析 JSON ({exc})")
                continue
            self._load_one(path, raw)

        return self

    def _load_one(self, path: Path, raw: dict) -> None:
        name = path.name
        if not isinstance(raw, dict):
            self.report.errors.append(f"{name}: 顶层必须是 JSON 对象")
            return

        schema_version = str(raw.get("schema_version", "")).strip()
        if schema_version != SUPPORTED_SCHEMA_VERSION:
            self.report.warnings.append(
                f"{name}: schema_version={schema_version!r}，本服务按 "
                f"{SUPPORTED_SCHEMA_VERSION} 解析"
            )

        bank_id = str(raw.get("bank_id") or path.stem).strip()
        if bank_id != path.stem:
            self.report.warnings.append(
                f"{name}: bank_id={bank_id!r} 与文件名不一致，以 bank_id 为准"
            )

        questions = raw.get("questions")
        if not isinstance(questions, list):
            self.report.errors.append(f"{name}: questions 必须是数组")
            return

        meta = BankMeta(
            bank_id=bank_id,
            bank_name=str(raw.get("bank_name", bank_id)),
            language=str(raw.get("language", "zh-CN")),
            source=str(raw.get("source", "")),
            version=str(raw.get("version", "")),
            updated_at=str(raw.get("updated_at", "")),
            file=name,
        )

        accepted = 0
        for index, item in enumerate(questions):
            question = self._parse_question(name, bank_id, index, item)
            if question is None:
                continue
            if question.id in self.questions:
                self.report.warnings.append(f"{name}: 题目 id 重复，已跳过 {question.id}")
                continue
            self.questions[question.id] = question
            accepted += 1

        meta.question_count = accepted
        if bank_id in self.banks:
            self.report.warnings.append(f"{name}: bank_id 重复 ({bank_id})")
        self.banks[bank_id] = meta

    def _parse_question(
        self, name: str, bank_id: str, index: int, item: object
    ) -> BankQuestion | None:
        label = f"{name}[{index}]"
        if not isinstance(item, dict):
            self.report.warnings.append(f"{label}: 不是对象，已跳过")
            return None

        qid = str(item.get("id") or "").strip()
        if not qid:
            self.report.warnings.append(f"{label}: 缺少 id，已跳过")
            return None

        qtype = str(item.get("type") or "single_choice").strip()
        if qtype not in SUPPORTED_QUESTION_TYPES:
            self.report.warnings.append(f"{label} ({qid}): 暂不支持题型 {qtype!r}，已跳过")
            return None

        stem = str(item.get("stem") or "").strip()
        if not stem:
            self.report.warnings.append(f"{label} ({qid}): 题干为空，已跳过")
            return None

        raw_options = item.get("options")
        if not isinstance(raw_options, dict) or not (2 <= len(raw_options) <= 8):
            self.report.warnings.append(
                f"{label} ({qid}): options 必须是 2–8 个选项的对象，已跳过"
            )
            return None
        options = {str(k).strip().upper(): str(v).strip() for k, v in raw_options.items()}

        expected_keys = [chr(ord("A") + offset) for offset in range(len(options))]
        if sorted(options) != expected_keys:
            self.report.warnings.append(
                f"{label} ({qid}): 选项键必须从 A 开始连续排列（实际 {sorted(options)}），已跳过"
            )
            return None
        if any(not text for text in options.values()):
            self.report.warnings.append(f"{label} ({qid}): 存在空选项，已跳过")
            return None

        answer = str(item.get("answer") or "").strip().upper()
        if answer not in options:
            self.report.warnings.append(
                f"{label} ({qid}): answer={answer!r} 不在 options 中，已跳过"
            )
            return None

        raw_kps = item.get("knowledge_point_ids") or []
        if not isinstance(raw_kps, list):
            raw_kps = []
        kp_ids: list[str] = []
        for kp_id in raw_kps:
            kp_id = str(kp_id).strip()
            if not kp_id:
                continue
            if not knowledge.is_known(kp_id):
                self.report.warnings.append(
                    f"{label} ({qid}): 未知知识点 {kp_id!r}（不在 knowledge_points 清单里），"
                    f"已忽略该映射"
                )
                continue
            if kp_id in kp_ids:
                self.report.warnings.append(f"{label} ({qid}): 知识点 {kp_id} 重复，已去重")
                continue
            kp_ids.append(kp_id)
        if not kp_ids:
            self.report.warnings.append(f"{label} ({qid}): 没有有效知识点映射")

        # 规范要求 tags 与 knowledge_point_ids 一一对应、顺序相同、逐字等于知识点 name。
        # 这里以知识点名称为准，文件里的 tags 只用来校验。
        expected_tags = [
            knowledge.get_point(kp_id).name  # type: ignore[union-attr]
            for kp_id in kp_ids
        ]
        raw_tags = item.get("tags")
        if isinstance(raw_tags, list):
            actual_tags = [str(t) for t in raw_tags]
            if actual_tags != expected_tags:
                self.report.warnings.append(
                    f"{label} ({qid}): tags 与知识点名称不一致，已按知识点重写"
                )
        else:
            self.report.warnings.append(f"{label} ({qid}): 缺少 tags，已按知识点补全")

        # 规范禁止在题目里写 difficulty / source / source_ref
        for forbidden in ("difficulty", "source", "source_ref"):
            if forbidden in item:
                self.report.warnings.append(
                    f"{label} ({qid}): 题目出现了规范禁止的字段 {forbidden!r}，已忽略"
                )

        return BankQuestion(
            id=qid,
            bank_id=bank_id,
            type=qtype,
            stem=stem,
            options=options,
            answer=answer,
            explanation=str(item.get("explanation") or "").strip(),
            knowledge_point_ids=tuple(kp_ids),
            tags=tuple(expected_tags),
            source_ref="",
            difficulty=_resolve_difficulty(kp_ids),
        )


_bank: QuestionBank | None = None


def get_bank() -> QuestionBank:
    global _bank
    if _bank is None:
        _bank = QuestionBank().load()
    return _bank


def reload_bank(directory: Path | None = None) -> QuestionBank:
    global _bank
    _bank = QuestionBank().load(directory)
    return _bank
