"""Wire types live outside ignored model-weight directories."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

class TranslationOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    input_language: str = "Japanese"
    output_language: str = "English"
    provider: str = "Google"
    base_url: str | None = None
    model_name: str | None = None
    api_key: str | None = None
    temperature: float = Field(default=0.1, ge=0, le=2)
    top_p: float = Field(default=0.95, ge=0, le=1)
    top_k: int = Field(default=1, ge=0)
    max_tokens: int | None = None
    translation_mode: Literal["one-step", "two-step"] = "one-step"
    ocr_method: Literal["LLM", "manga-ocr", "paddleocr-vl"] = "LLM"
    reasoning_effort: str | None = None
    special_instructions: str | None = None
    font_dir: str | None = None
    max_font_size: int = 16
    min_font_size: int = 8
    supersampling_factor: int = 4
    send_full_page_context: bool = True
    image_detail: str = "auto"
    outside_text_enabled: bool = False

class TranslateRequest(TranslationOptions):
    image: str

class TranslateBatchItem(BaseModel):
    image: str
    id: str | None = None

class TranslateBatchRequest(TranslationOptions):
    images: list[TranslateBatchItem]

class BubbleInfo(BaseModel):
    bbox: list[float]
    confidence: float
    original_text: str | None = None
    translated_text: str = ""

class TranslateResponse(BaseModel):
    translated_image: str
    bubbles: list[BubbleInfo]
    processing_time_seconds: float
    source_language: str
    target_language: str
    provider: str

class TranslateBatchItemResponse(BaseModel):
    id: str | None = None
    translated_image: str | None = None
    bubbles: list[BubbleInfo]
    error: str | None = None
    processing_time_seconds: float

class TranslateBatchResponse(BaseModel):
    results: list[TranslateBatchItemResponse]
    total_time_seconds: float
    success_count: int
    error_count: int
