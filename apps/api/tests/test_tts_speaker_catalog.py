from __future__ import annotations

import httpx
import pytest

from app.shared.tts_speaker_catalog import (
    TtsSpeakerCatalogUnavailable,
    VolcengineTtsSpeakerCatalog,
    parse_supported_tts_speakers,
)


SPEAKER_DOCUMENT = """
## "豆包语音合成模型2.0" 音色列表
|场景|音色名称|voice_type|语种/方言|备注|
|通用|Vivi 2.0|zh_female_vv_uranus_bigtts|语种：中文、日文|指令遵循|
||||方言：四川、陕西、东北||
|通用|云舟|zh_male_m191_uranus_bigtts|语种：中文|指令遵循|
|通用|单向音色|zh_female_one_way_uranus_bigtts|语种：中文|仅限单向流使用，不支持双向流|
|通用|旧模型格式|zh_female_legacy_bigtts|语种：中文|指令遵循|
## "豆包语音合成模型2.0" 多语种音色列表
|场景|音色名称|voice_type|语种/方言|备注|
|英语|Tim|en_male_tim_uranus_bigtts|语种：英语|指令遵循|
|英语|Tim 重复|en_male_tim_uranus_bigtts|语种：英语|指令遵循|
## "豆包语音合成模型1.0" 音色列表
|场景|音色名称|voice_type|语种/方言|备注|
|通用|旧 Vivi|zh_female_old_uranus_bigtts|语种：中文|指令遵循|
"""


def test_parse_supported_tts_speakers_keeps_compatible_bidirectional_2_0_rows() -> None:
    options = parse_supported_tts_speakers(
        SPEAKER_DOCUMENT,
        resource_id="seed-tts-2.0",
    )

    assert [(option.voice_type, option.name, option.gender) for option in options] == [
        ("zh_female_vv_uranus_bigtts", "Vivi 2.0", "female"),
        ("zh_male_m191_uranus_bigtts", "云舟", "male"),
    ]
    assert [(item.id, item.label) for item in options[0].dialects] == [
        ("sichuan", "四川话"),
        ("shaanxi", "陕西话"),
        ("northeast", "东北话"),
    ]
    assert options[1].dialects == ()


def test_parse_supported_tts_speakers_rejects_incompatible_resource() -> None:
    with pytest.raises(TtsSpeakerCatalogUnavailable):
        parse_supported_tts_speakers(
            SPEAKER_DOCUMENT,
            resource_id="seed-tts-1.0",
        )


def test_catalog_reuses_stale_cache_when_refresh_fails() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(
                200,
                request=request,
                json={"Result": {"Content": SPEAKER_DOCUMENT}},
            )
        return httpx.Response(503, request=request)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        catalog = VolcengineTtsSpeakerCatalog(client=client, ttl_seconds=0)
        first = catalog.list_supported(resource_id="seed-tts-2.0")
        second = catalog.list_supported(resource_id="seed-tts-2.0")

    assert second == first
    assert calls == 2
