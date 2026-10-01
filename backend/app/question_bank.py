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
from typing import Iterable

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


def _normalize_difficulty(raw: object, kp_ids: Iterable[str]) -> float:
    """接受 1..5 的整数或 0..1 的小数；缺省回退知识点难度档位。"""
    if isinstance(raw, bool):
        raw = None
    if isinstance(raw, (int, float)):
        value = float(raw)
        if 0.0 <= value <= 1.0 and not float(value).is_integer():
            return value
        if 1.0 <= value <= 5.0:
            return (value - 1.0) / 4.0
        return min(1.0, max(0.0, value))
    # 回退：用第一个已知知识点的难度档位
    for kp_id in kp_ids:
        point = knowledge.get_point(kp_id)
        if point is not None:
            return (point.difficulty_band - 1) / 4.0
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
        if not isinstance(raw_options, dict) or len(raw_options) < 2:
            self.report.warnings.append(f"{label} ({qid}): options 必须是非空对象，已跳过")
            return None
        options = {str(k).strip(): str(v).strip() for k, v in raw_options.items()}

        answer = str(item.get("answer") or "").strip()
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
                    f"{label} ({qid}): 未知知识点 {kp_id!r}，已忽略该映射"
                )
                continue
            kp_ids.append(kp_id)
        if not kp_ids:
            self.report.warnings.append(f"{label} ({qid}): 没有有效知识点映射")

        tags = item.get("tags") or []
        if not isinstance(tags, list):
            tags = []

        return BankQuestion(
            id=qid,
            bank_id=bank_id,
            type=qtype,
            stem=stem,
            options=options,
            answer=answer,
            explanation=str(item.get("explanation") or "").strip(),
            knowledge_point_ids=tuple(kp_ids),
            tags=tuple(str(t) for t in tags),
            source_ref=str(item.get("source_ref") or ""),
            difficulty=_normalize_difficulty(item.get("difficulty"), kp_ids),
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
