from __future__ import annotations

import logging
import struct
import zlib
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal

from backend.app.advanced.harness import (
    PolicyViolation,
    SafetyBudget,
    SafetyLimits,
    content_digest,
)


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_VALID_BIT_DEPTHS = {
    0: frozenset({1, 2, 4, 8, 16}),
    2: frozenset({8, 16}),
    3: frozenset({1, 2, 4, 8}),
    4: frozenset({8, 16}),
    6: frozenset({8, 16}),
}


@dataclass(frozen=True)
class PngLimits:
    max_bytes: int = 5_000_000
    max_width: int = 4096
    max_height: int = 4096
    max_pixels: int = 12_000_000
    max_visual_text_bytes: int = 100_000

    def __post_init__(self) -> None:
        for field_name in (
            "max_bytes",
            "max_width",
            "max_height",
            "max_pixels",
            "max_visual_text_bytes",
        ):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{field_name} must be a positive integer")


@dataclass(frozen=True)
class PngMetadata:
    width: int
    height: int
    bit_depth: int
    color_type: int
    interlaced: bool
    byte_length: int
    sha256: str


@dataclass(frozen=True)
class UntrustedVisualText:
    """OCR or vision output that must remain data, never authority."""

    value: str = field(repr=False)
    sha256: str
    byte_length: int
    trust: Literal["untrusted_visual_data"] = "untrusted_visual_data"
    can_authorize_actions: Literal[False] = False


@dataclass(frozen=True)
class MultimodalInspection:
    image: PngMetadata
    visual_text: UntrustedVisualText
    offline: Literal[True] = True


@dataclass(frozen=True)
class MultimodalEvent:
    type: str
    data: dict[str, object]


MultimodalObserver = Callable[[MultimodalEvent], None]


class OfflineMultimodalAgent:
    """Inspect a PNG locally without treating extracted text as instructions."""

    def __init__(
        self,
        *,
        limits: PngLimits | None = None,
        observer: MultimodalObserver | None = None,
    ) -> None:
        self._limits = limits or PngLimits()
        self._observer = observer

    @property
    def offline(self) -> bool:
        return True

    def inspect_png(
        self,
        image: bytes,
        *,
        extracted_text: str = "",
    ) -> MultimodalInspection:
        if not isinstance(image, bytes):
            raise TypeError("image must be bytes")
        if not isinstance(extracted_text, str):
            raise TypeError("extracted_text must be a string")

        text_bytes = extracted_text.encode("utf-8")
        budget = SafetyBudget(
            SafetyLimits(
                max_actions=1,
                max_input_bytes=self._limits.max_bytes,
                max_output_bytes=self._limits.max_visual_text_bytes,
            )
        )
        budget.consume(input_bytes=len(image), output_bytes=len(text_bytes))
        metadata = _read_png_metadata(image, self._limits)
        visual_text = UntrustedVisualText(
            value=extracted_text,
            sha256=content_digest(text_bytes),
            byte_length=len(text_bytes),
        )
        inspection = MultimodalInspection(
            image=metadata,
            visual_text=visual_text,
        )
        self._publish(
            MultimodalEvent(
                type="multimodal.inspected",
                data={
                    "image_sha256": metadata.sha256,
                    "image_bytes": metadata.byte_length,
                    "width": metadata.width,
                    "height": metadata.height,
                    "visual_text_sha256": visual_text.sha256,
                    "visual_text_bytes": visual_text.byte_length,
                    "visual_text_trust": visual_text.trust,
                    "offline": True,
                },
            )
        )
        return inspection

    def _publish(self, event: MultimodalEvent) -> None:
        if self._observer is None:
            return
        try:
            self._observer(event)
        except Exception as error:
            logging.getLogger("ai_agent.advanced.multimodal").warning(
                "Multimodal observer failed with %s",
                type(error).__name__,
            )


def _read_png_metadata(image: bytes, limits: PngLimits) -> PngMetadata:
    if len(image) < 33 or image[:8] != PNG_SIGNATURE:
        raise PolicyViolation("invalid_png_signature", "invalid PNG signature")

    ihdr_length = int.from_bytes(image[8:12], "big")
    if ihdr_length != 13 or image[12:16] != b"IHDR":
        raise PolicyViolation("invalid_png_ihdr", "PNG must start with IHDR")

    ihdr = image[16:29]
    expected_crc = int.from_bytes(image[29:33], "big")
    actual_crc = zlib.crc32(b"IHDR" + ihdr) & 0xFFFFFFFF
    if expected_crc != actual_crc:
        raise PolicyViolation("invalid_png_ihdr", "PNG IHDR checksum is invalid")

    width, height, bit_depth, color_type, compression, filtering, interlace = (
        struct.unpack(">IIBBBBB", ihdr)
    )
    if width == 0 or height == 0:
        raise PolicyViolation("invalid_png_ihdr", "PNG dimensions must be positive")
    if bit_depth not in _VALID_BIT_DEPTHS.get(color_type, frozenset()):
        raise PolicyViolation("invalid_png_ihdr", "PNG color settings are invalid")
    if compression != 0 or filtering != 0 or interlace not in (0, 1):
        raise PolicyViolation("invalid_png_ihdr", "PNG encoding settings are invalid")
    if width > limits.max_width or height > limits.max_height:
        raise PolicyViolation(
            "image_dimensions_exceeded",
            "PNG dimensions exceed the configured limit",
        )
    if width * height > limits.max_pixels:
        raise PolicyViolation(
            "image_pixels_exceeded",
            "PNG pixel count exceeds the configured limit",
        )

    return PngMetadata(
        width=width,
        height=height,
        bit_depth=bit_depth,
        color_type=color_type,
        interlaced=bool(interlace),
        byte_length=len(image),
        sha256=content_digest(image),
    )
