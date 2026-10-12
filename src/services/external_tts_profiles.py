from __future__ import annotations

from typing import Any


EXTERNAL_TTS_CHARACTER_VOICES_SETTING = "EXTERNAL_TTS_CHARACTER_VOICES"


def load_external_tts_character_voice_map(settings: Any) -> dict[str, str]:
    """Загружает настройки индивидуальных голосов персонажей."""
    try:
        raw = settings.get(EXTERNAL_TTS_CHARACTER_VOICES_SETTING, {})
    except Exception:
        raw = {}

    if not isinstance(raw, dict):
        return {}

    result: dict[str, str] = {}

    for raw_character_id, raw_voice_id in raw.items():
        character_id = str(raw_character_id or "").strip()

        if not character_id:
            continue

        result[character_id] = str(raw_voice_id or "").strip()

    return result


def resolve_external_tts_voice_id(
    settings: Any,
    character_id: str | None,
    voice_profile: dict | None = None,
) -> str | None:
    """
    Приоритет:
    1. Индивидуальный Voice ID из настроек персонажей.
    2. Старое поле external_voice_id профиля персонажа.
    3. Общий EXTERNAL_TTS_VOICE_ID из настроек сервера.
    """

    character_key = str(character_id or "").strip()
    voice_map = load_external_tts_character_voice_map(settings)

    # Новый индивидуальный Voice ID.
    if character_key:
        configured_voice = str(
            voice_map.get(character_key, "") or ""
        ).strip()

        if configured_voice:
            return configured_voice

    # Совместимость с прежними настройками персонажей.
    if isinstance(voice_profile, dict):
        legacy_voice = str(
            voice_profile.get("external_voice_id") or ""
        ).strip()

        if legacy_voice:
            return legacy_voice

    # None означает, что TTS-клиент должен использовать
    # общий EXTERNAL_TTS_VOICE_ID из конфигурации.
    return None