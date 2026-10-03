"""大图压缩：识别耗时的大头。

线上实测一张 4548×7067 / 6.4 MB 的试卷照片，原图直送视觉模型，
**光识别就 162.6 秒**（占整次分析 78%）。而印在纸上的题目根本不需要
4500 px 宽 —— 压到长边 2000 px 足以看清，视觉 token 数降一个数量级。

Pillow 是**可选依赖**：装不上就原样发送 + 告警，不能因为少一个库
就让整条链路不可用。
"""

from __future__ import annotations

from io import BytesIO

import pytest

from app.services import vlm_service


def _make_png(width: int, height: int) -> bytes:
    """造一张纯色 PNG（不依赖 Pillow）。"""
    import struct
    import zlib

    raw = b"".join(b"\x00" + bytes([120, 130, 140]) * width for _ in range(height))

    def chunk(tag: bytes, data: bytes) -> bytes:
        body = tag + data
        return (
            struct.pack(">I", len(data))
            + body
            + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)
        )

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(raw, 6))
        + chunk(b"IEND", b"")
    )


def test_small_image_is_passed_through_untouched() -> None:
    """已经在限制内的图不该被重新编码（白白损失质量）。"""
    raw = _make_png(400, 300)
    out, mime = vlm_service.prepare_image(raw, "image/png")
    assert out == raw, "小图应当原样返回"
    assert mime == "image/png"


def test_missing_pillow_degrades_gracefully(monkeypatch: pytest.MonkeyPatch) -> None:
    """★ Pillow 缺失时必须原样发送，而不是抛异常。

    少一个可选依赖不该让整条识别链路不可用 —— 只是会慢一些。
    """
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "PIL" or name.startswith("PIL."):
            raise ImportError("模拟 Pillow 未安装")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    raw = _make_png(3000, 4000)
    out, mime = vlm_service.prepare_image(raw, "image/png")
    assert out == raw, "没有 Pillow 时要原样发送"
    assert mime == "image/png"


def test_large_image_is_downscaled_when_pillow_is_available() -> None:
    """装了 Pillow 时，超限的图必须被压到长边以内。"""
    PIL = pytest.importorskip("PIL", reason="本地没装 Pillow，跳过实际压缩验证")
    from PIL import Image

    raw = _make_png(3000, 4000)
    out, mime = vlm_service.prepare_image(raw, "image/png")

    assert mime == "image/jpeg", "压缩后统一转成 JPEG"
    assert len(out) < len(raw), "压缩后应当更小"

    with Image.open(BytesIO(out)) as image:
        width, height = image.size
    assert max(width, height) == vlm_service.MAX_IMAGE_EDGE
    # 宽高比不能变
    assert abs(width / height - 3000 / 4000) < 0.01


def test_threshold_is_sane() -> None:
    """阈值要够大能看清题目，又要够小压得住耗时。"""
    assert 1200 <= vlm_service.MAX_IMAGE_EDGE <= 3000
    assert 70 <= vlm_service.IMAGE_JPEG_QUALITY <= 95
