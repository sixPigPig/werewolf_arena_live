from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.routes.games import get_tts_config
from app.core.config import settings
from app.werewolf.judge_voice_assets import (
    DEFAULT_JUDGE_VOICE_ASSET_DIR,
    JudgeVoiceAsset,
    JudgeVoiceGenerationResult,
    generate_judge_voice_assets,
    list_judge_voice_assets,
)
from app.werewolf.volcengine_tts import VolcengineTtsClient, VolcengineTtsConfig


router = APIRouter()


class JudgeVoiceAssetResponse(BaseModel):
    id: str
    text: str
    category: str
    filename: str
    public_url: str
    exists: bool
    byte_size: int | None
    template_id: str | None = None
    template_text: str | None = None
    seat_number: int | None = None


class JudgeVoiceLineListResponse(BaseModel):
    audio_format: str
    sample_rate: int
    lines: list[JudgeVoiceAssetResponse]


class GenerateJudgeVoiceLinesRequest(BaseModel):
    force: bool = False
    line_ids: list[str] | None = Field(default=None, min_length=1)


class GenerateJudgeVoiceLinesResponse(JudgeVoiceLineListResponse):
    generated_ids: list[str]
    skipped_ids: list[str]
    manifest_path: str


def get_judge_voice_asset_dir() -> Path:
    return DEFAULT_JUDGE_VOICE_ASSET_DIR


def get_judge_voice_tts_config(
    config: Annotated[VolcengineTtsConfig, Depends(get_tts_config)],
) -> VolcengineTtsConfig:
    return replace(
        config,
        audio_format=settings.ark_tts_judge_asset_audio_format,
        sample_rate=settings.ark_tts_judge_asset_sample_rate,
    )


def get_judge_voice_client_factory() -> Callable[[VolcengineTtsConfig], VolcengineTtsClient]:
    return VolcengineTtsClient


@router.get("", response_model=JudgeVoiceLineListResponse)
def list_judge_voice_lines(
    asset_dir: Annotated[Path, Depends(get_judge_voice_asset_dir)],
    config: Annotated[VolcengineTtsConfig, Depends(get_judge_voice_tts_config)],
) -> JudgeVoiceLineListResponse:
    return JudgeVoiceLineListResponse(
        audio_format=config.audio_format,
        sample_rate=config.sample_rate,
        lines=[
            _asset_response(asset)
            for asset in list_judge_voice_assets(
                asset_dir=asset_dir,
                audio_format=config.audio_format,
            )
        ],
    )


@router.post("/generate", response_model=GenerateJudgeVoiceLinesResponse)
async def generate_judge_voice_lines(
    request: GenerateJudgeVoiceLinesRequest,
    asset_dir: Annotated[Path, Depends(get_judge_voice_asset_dir)],
    config: Annotated[VolcengineTtsConfig, Depends(get_judge_voice_tts_config)],
    client_factory: Annotated[
        Callable[[VolcengineTtsConfig], VolcengineTtsClient],
        Depends(get_judge_voice_client_factory),
    ],
) -> GenerateJudgeVoiceLinesResponse:
    if not config.available:
        raise HTTPException(
            status_code=503,
            detail=config.unavailable_message or "语音服务暂不可用，请稍后重试。",
        )

    try:
        result = await generate_judge_voice_assets(
            config=config,
            asset_dir=asset_dir,
            line_ids=request.line_ids,
            force=request.force,
            client_factory=client_factory,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return _generation_response(result, config=config)


def _generation_response(
    result: JudgeVoiceGenerationResult,
    *,
    config: VolcengineTtsConfig,
) -> GenerateJudgeVoiceLinesResponse:
    return GenerateJudgeVoiceLinesResponse(
        audio_format=config.audio_format,
        sample_rate=config.sample_rate,
        generated_ids=result.generated_ids,
        skipped_ids=result.skipped_ids,
        manifest_path=result.manifest_path,
        lines=[_asset_response(asset) for asset in result.lines],
    )


def _asset_response(asset: JudgeVoiceAsset) -> JudgeVoiceAssetResponse:
    return JudgeVoiceAssetResponse(
        id=asset.id,
        text=asset.text,
        category=asset.category,
        filename=asset.filename,
        public_url=asset.public_url,
        exists=asset.exists,
        byte_size=asset.byte_size,
        template_id=asset.template_id,
        template_text=asset.template_text,
        seat_number=asset.seat_number,
    )
