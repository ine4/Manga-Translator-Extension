"""Pipeline wrapper — bridges MangaTranslator core to FastAPI endpoints.

Reuses MangaTranslator's detection/translation/rendering pipeline while
accepting base64 images instead of file paths and returning base64 images
instead of saving to disk.
"""
from __future__ import annotations

import base64
import io
import sys
import time
import threading
from pathlib import Path
from typing import Any, Optional

import torch
from PIL import Image

_backend_dir = Path(__file__).resolve().parents[1]
if str(_backend_dir) not in sys.path:
    sys.path.insert(0, str(_backend_dir))

from config import settings

from core.config import (
    CleaningConfig,
    DetectionConfig,
    MangaTranslatorConfig,
    OutsideTextConfig,
    PreprocessingConfig,
    RenderingConfig,
    TranslationConfig,
    OutputConfig,
)

from core.ml.model_manager import get_model_manager
from utils.logging import log_message
from local_ai import LOCAL_BASE_URL, LOCAL_MODEL, page_lease, detect_page_language

_page_lock = threading.Lock()

# Cached device — determined once at module load, reused for all requests
_CACHED_DEVICE: torch.device | None = None


def _normalize_openai_compatible_base_url(base_url: str | None) -> str | None:
    """Normalize OpenAI-compatible base URL to the API root.

    The core endpoint appends /chat/completions, so users may paste either
    https://host/v1 or a full endpoint like https://host/v1/chat/completions.
    """
    if not base_url:
        return None
    normalized = base_url.strip().rstrip("/")
    for suffix in ("/chat/completions", "/models"):
        if normalized.lower().endswith(suffix):
            normalized = normalized[: -len(suffix)].rstrip("/")
    return normalized or None


def _resolve_font_dir(
    fonts_base_dir: Path,
    font_dir: str | None,
    output_language: str,
) -> Path:
    """Resolve a usable font pack directory for rendering."""
    def has_font_files(path: Path) -> bool:
        return path.is_dir() and (any(path.glob("*.ttf")) or any(path.glob("*.otf")))

    language = output_language.strip().lower()
    vietnamese_output = "vietnamese" in language or language in {"vi", "vie"}
    english_output = "english" in language or language in {"en", "eng"}
    cjk_output = (
        "chinese" in language
        or "japanese" in language
        or "korean" in language
        or language in {"zh", "zho", "cn", "ja", "jpn", "ko", "kor"}
    )
    if vietnamese_output or english_output:
        default_font = "Roboto"
    elif cjk_output:
        default_font = "Noto Sans SC"
    else:
        default_font = "Komika Hand"

    preferred = fonts_base_dir / (font_dir or default_font)
    if has_font_files(preferred):
        return preferred

    if vietnamese_output or english_output:
        fallback_names = ("Roboto", "Noto Sans SC", "Komika Hand", "Comicka")
    elif cjk_output:
        fallback_names = ("Noto Sans SC", "Roboto", "Komika Hand", "Comicka")
    else:
        fallback_names = ("Komika Hand", "Comicka", "Roboto", "Noto Sans SC")
    for candidate_name in fallback_names:
        candidate = fonts_base_dir / candidate_name
        if has_font_files(candidate):
            return candidate

    for candidate in fonts_base_dir.iterdir() if fonts_base_dir.exists() else []:
        if has_font_files(candidate):
            return candidate

    return preferred


def _get_device() -> torch.device:
    global _CACHED_DEVICE
    if _CACHED_DEVICE is not None:
        return _CACHED_DEVICE
    if torch.cuda.is_available():
        _CACHED_DEVICE = torch.device("cuda")
    elif torch.backends.mps.is_available():
        _CACHED_DEVICE = torch.device("mps")
    else:
        _CACHED_DEVICE = torch.device("cpu")
    return _CACHED_DEVICE


def warmup_models(models_dir: Path) -> dict[str, bool]:
    """Pre-load all ML models so the first translate request is fast.

    Returns a dict mapping model name to load success status.
    """
    results: dict[str, bool] = {}
    try:
        mm = get_model_manager()
        # Pre-load the key models that every translation needs
        for name, loader in [
            ("yolo_speech_bubble", mm.load_yolo_speech_bubble),
            ("yolo_conjoined_bubble", mm.load_yolo_conjoined_bubble),
            ("upscale_lite", mm.load_upscale_lite),
            ("manga_ocr", mm.get_manga_ocr),
        ]:
            try:
                loader()
                results[name] = True
            except Exception as e:
                log_message(f"[warmup] {name}: {e}", always_print=True)
                results[name] = False
    except Exception as e:
        log_message(f"[warmup] Model manager init failed: {e}", always_print=True)
    return results


def _build_config(
    input_language: str,
    output_language: str,
    provider: str,
    model_name: str | None,
    api_key: str | None,
    temperature: float,
    top_p: float,
    top_k: int,
    max_tokens: int | None,
    translation_mode: str,
    ocr_method: str,
    reasoning_effort: str | None,
    special_instructions: str | None,
    font_dir: str | None,
    max_font_size: int,
    min_font_size: int,
    supersampling_factor: int,
    send_full_page_context: bool,
    image_detail: str,
    outside_text_enabled: bool,
    models_dir: Path,
    fonts_base_dir: Path,
    base_url: str | None = None,
) -> MangaTranslatorConfig:
    """Build a MangaTranslatorConfig from request parameters."""

    local_managed = provider == "Local"
    if local_managed:
        # Never use a user-configured remote endpoint, key or cloud fallback.
        provider = "OpenAI-Compatible"
        base_url = LOCAL_BASE_URL
        api_key = "manga-local"
        model_name = model_name or LOCAL_MODEL
        translation_mode = "one-step"
        ocr_method = "LLM"
    normalized_base_url = _normalize_openai_compatible_base_url(base_url)
    if provider == "OpenAI-Compatible":
        if not normalized_base_url:
            raise ValueError("OpenAI-Compatible Base URL is required.")
        if not model_name:
            raise ValueError("OpenAI-Compatible model name is required.")
        base_url = normalized_base_url

    # Build API key map — the config expects all keys
    all_keys = {}
    if api_key:
        all_keys[provider] = api_key

    detection = DetectionConfig(
        confidence=0.35,
        conjoined_confidence=0.25,
        panel_confidence=0.15,
        seg_model="yolo",
        bubble_detector_model="yolo_1",
        conjoined_detection=True,
        use_panel_sorting=True,
    )

    cleaning = CleaningConfig(
        thresholding_value=200,
        use_otsu_threshold=False,
        roi_shrink_px=5,
        inpaint_colored_bubbles=False,
    )

    translation = TranslationConfig(
        provider=provider,
        local_managed=local_managed,
        model_name=model_name or _get_default_model(provider),
        temperature=temperature,
        top_p=top_p,
        top_k=top_k,
        max_tokens=max_tokens,
        input_language=input_language,
        output_language=output_language,
        reading_direction="ltr" if local_managed and input_language not in ("Japanese", "Auto") else "rtl",
        translation_mode=translation_mode,
        reasoning_effort=reasoning_effort,
        special_instructions=special_instructions,
        ocr_method=ocr_method,
        send_full_page_context=send_full_page_context,
        whiteout_conjoined_bubbles=True,
        upscale_method="lanczos",
        bubble_min_side_pixels=96,
        context_image_max_side_pixels=1536,
        media_resolution="high",
        media_resolution_bubbles="high",
        media_resolution_context="high",
        image_detail="high" if image_detail == "auto" else image_detail,
        enable_web_search=False,
        enable_code_execution=False,
    )

    # Inject API keys into the config's internal env map
    # Override OpenAI-Compatible URL if provided (e.g. from extension settings)
    if base_url:
        translation.openai_compatible_url = base_url
    if api_key:
        translation.openai_compatible_api_key = api_key

    _inject_api_keys(translation, provider, api_key)

    rendering = RenderingConfig(
        font_dir=str(_resolve_font_dir(fonts_base_dir, font_dir, output_language)),
        max_font_size=max_font_size,
        min_font_size=min_font_size,
        line_spacing_mult=1.0,
        use_subpixel_rendering=True,
        font_hinting="none",
        use_ligatures=False,
        supersampling_factor=supersampling_factor,
        hyphenate_before_scaling=True,
        hyphen_penalty=1000.0,
        hyphenation_min_word_length=8,
        badness_exponent=3.0,
        padding_pixels=5.0,
        detach_trailing_ellipsis=True,
    )

    output = OutputConfig(
        output_format="png",
        jpeg_quality=95,
        png_compression=2,
        upscale_final_image=False,
        image_upscale_factor=2.0,
    )

    outside_text = OutsideTextConfig(
        enabled=outside_text_enabled,
        inpainting_method="auto",
        osb_confidence=0.45,
        osb_outline_width=0.0,
        osb_text_background_enabled=False,
        enable_page_number_filtering=True,
    )

    preprocessing = PreprocessingConfig(enabled=False)

    target_device = _get_device()

    config = MangaTranslatorConfig(
        yolo_model_path=str(models_dir / "yolo" / "yolov8m_seg-speech-bubble.pt"),
        verbose=False,
        device=target_device,
        detection=detection,
        cleaning=cleaning,
        translation=translation,
        rendering=rendering,
        output=output,
        outside_text=outside_text,
        preprocessing=preprocessing,
    )

    config.__post_init__()
    return config


def _inject_api_keys(translation: TranslationConfig, provider: str, api_key: str | None) -> None:
    """Inject the provided API key into the appropriate TranslationConfig field."""
    key = api_key or ""
    mapping = {
        "Google": "google_api_key",
        "OpenAI": "openai_api_key",
        "Anthropic": "anthropic_api_key",
        "xAI": "xai_api_key",
        "DeepSeek": "deepseek_api_key",
        "Z.ai": "zai_api_key",
        "Moonshot AI": "moonshot_api_key",
        "OpenRouter": "openrouter_api_key",
        "OpenAI-Compatible": "openai_compatible_api_key",
    }
    attr = mapping.get(provider)
    if attr and hasattr(translation, attr):
        setattr(translation, attr, key)


def _get_default_model(provider: str) -> str:
    defaults = {
        "Google": "gemini-3.1-flash-lite-preview",
        "OpenAI": "gpt-5.4-nano-2026-03-17",
        "Anthropic": "claude-sonnet-4-6",
        "xAI": "grok-4.3",
        "DeepSeek": "deepseek-v4-flash",
        "Z.ai": "glm-5v-turbo",
        "Moonshot AI": "kimi-k2.6",
        "OpenRouter": "google/gemini-3.1-flash-lite-preview",
        "OpenAI-Compatible": "default",
    }
    return defaults.get(provider, "gemini-3.1-flash-lite-preview")


def base64_to_image(data: str) -> Image.Image:
    """Decode a base64 string to a PIL Image."""
    raw = base64.b64decode(data)
    return Image.open(io.BytesIO(raw))


def image_to_base64(image: Image.Image, fmt: str = "PNG") -> str:
    """Encode a PIL Image to a base64 string."""
    buf = io.BytesIO()
    if fmt.upper() == "JPEG":
        if image.mode in ("RGBA", "LA", "P"):
            rgb = Image.new("RGB", image.size, (255, 255, 255))
            if image.mode == "P":
                image = image.convert("RGBA")
            if image.mode in ("RGBA", "LA"):
                rgb.paste(image, mask=image.split()[-1])
                image = rgb
        image.save(buf, format="JPEG", quality=95)
        mime = "image/jpeg"
    else:
        if image.mode not in ("RGB", "RGBA"):
            image = image.convert("RGBA")
        image.save(buf, format="PNG", optimize=False)
        mime = "image/png"
    return f"data:{mime};base64,{base64.b64encode(buf.getvalue()).decode('ascii')}"


def image_to_base64_raw(image: Image.Image, fmt: str = "PNG") -> str:
    """Encode a PIL Image to raw base64 (no data URL prefix)."""
    buf = io.BytesIO()
    if fmt.upper() == "JPEG":
        if image.mode in ("RGBA", "LA", "P"):
            rgb = Image.new("RGB", image.size, (255, 255, 255))
            if image.mode == "P":
                image = image.convert("RGBA")
            if image.mode in ("RGBA", "LA"):
                rgb.paste(image, mask=image.split()[-1])
                image = rgb
        image.save(buf, format="JPEG", quality=95)
    else:
        if image.mode not in ("RGB", "RGBA"):
            image = image.convert("RGBA")
        image.save(buf, format="PNG", optimize=False)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def translate_image_base64(
    image_b64: str,
    config: MangaTranslatorConfig,
    progress=None,
) -> tuple[Image.Image, list[dict[str, Any]], float]:
    """Process the entire API page in RAM; never create a page or crop file."""
    from contextlib import nullcontext
    from core.caching import get_cache
    from core.pipeline import translate_and_render

    start = time.monotonic()
    def report(completed, stage):
        if progress is not None:
            progress(completed, stage)
    report(0, "Waiting for page queue")
    with _page_lock:
        try:
            with base64_to_image(image_b64) as pil_image:
                pil_image.load()
                bubbles: list[dict[str, Any]] = []
                managed = config.translation.local_managed
                lease = page_lease(config.translation.model_name) if managed else nullcontext()
                report(0, "Loading model" if managed else "Preparing page")
                with lease:
                    report(1, "Identifying language" if managed and config.translation.input_language == "Auto" else "Preparing detection")
                    if managed and config.translation.input_language == "Auto":
                        language, direction = detect_page_language(pil_image, config.translation.model_name)
                        config.translation.input_language = language
                        config.translation.reading_direction = direction
                    report(2, "Detecting text regions")
                    result = translate_and_render(
                        image_path=None, config=config, output_path=None,
                        image_override=pil_image,
                        bubble_results_out=bubbles,
                        progress=report,
                    )
                    if not isinstance(result, Image.Image):
                        raise RuntimeError("Translation did not return an image")
                    translated_image = result.copy()
                    report(6, "Encoding result")
            return translated_image, bubbles, time.monotonic() - start
        finally:
            # Global pipeline caches are request-scoped for the HTTP API.
            get_cache().clear_all()
