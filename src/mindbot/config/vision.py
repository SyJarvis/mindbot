"""Vision model patterns configuration.

This file contains model name patterns that indicate vision capability.
Add new patterns here as new vision models are released.
"""

# Model name patterns that are known to support vision.
# These patterns are matched against lowercase model names.
VISION_PATTERNS = (
    "llava",
    "bakllava",
    "qwen-vl",
    "qwen2-vl",
    "qwen3-vl",  # Added for Qwen3-VL support
    "minicpm-v",
    "moondream",
    "llama3.2-vision",
    "granite3.2-vision",
    "qwen3-vl:8b",
    "kimi-k2.5"
)

__all__ = ["VISION_PATTERNS"]
