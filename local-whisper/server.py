from __future__ import annotations

import os
import re
import tempfile
import wave
from pathlib import Path

import requests
from faster_whisper import WhisperModel
from flask import Flask, jsonify, request


MODEL_NAME = os.environ.get("WHISPER_MODEL", "base")
DEVICE = os.environ.get("WHISPER_DEVICE", "cpu")
COMPUTE_TYPE = os.environ.get("WHISPER_COMPUTE_TYPE", "int8")
LANGUAGE = os.environ.get("WHISPER_LANGUAGE", "en")
WAKE_INITIAL_PROMPT = os.environ.get("WHISPER_WAKE_INITIAL_PROMPT", "assistant").strip()
COMMAND_INITIAL_PROMPT = os.environ.get(
    "WHISPER_COMMAND_INITIAL_PROMPT",
    "voice assistant command send email to at dot dypiu dot ac dot in subject message reminder",
).strip()
WAKE_HOTWORDS = os.environ.get("WHISPER_WAKE_HOTWORDS", "assistant").strip()
COMMAND_HOTWORDS = os.environ.get(
    "WHISPER_COMMAND_HOTWORDS",
    "assistant email reminder subject message at dot dypiu ac in",
).strip()
WAKE_MAX_SECONDS = float(os.environ.get("WHISPER_WAKE_MAX_SECONDS", "3.0"))
TRANSCRIBE_PROVIDER = os.environ.get("TRANSCRIBE_PROVIDER", "").strip().lower() or (
    "deepgram" if os.environ.get("DEEPGRAM_API_KEY") else
    "elevenlabs" if os.environ.get("ELEVENLABS_API_KEY") else "whisper"
)
DEEPGRAM_API_KEY = os.environ.get("DEEPGRAM_API_KEY", "").strip()
DEEPGRAM_MODEL = os.environ.get("DEEPGRAM_MODEL", "nova-3").strip()
DEEPGRAM_LANGUAGE = os.environ.get("DEEPGRAM_LANGUAGE", LANGUAGE).strip()
DEEPGRAM_TIMEOUT_SECONDS = float(os.environ.get("DEEPGRAM_TIMEOUT_SECONDS", "90"))
ELEVENLABS_API_KEY = os.environ.get("ELEVENLABS_API_KEY", "").strip()
ELEVENLABS_MODEL_ID = os.environ.get("ELEVENLABS_MODEL_ID", "scribe_v1").strip()
ELEVENLABS_LANGUAGE = os.environ.get("ELEVENLABS_LANGUAGE", LANGUAGE).strip()
ELEVENLABS_TIMEOUT_SECONDS = float(os.environ.get("ELEVENLABS_TIMEOUT_SECONDS", "90"))
WHISPER_FALLBACK_ENABLED = os.environ.get("WHISPER_FALLBACK_ENABLED", "true").strip().lower() not in {
    "0",
    "false",
    "no",
}

app = Flask(__name__)
model = None
if TRANSCRIBE_PROVIDER == "whisper" or WHISPER_FALLBACK_ENABLED:
    model = WhisperModel(MODEL_NAME, device=DEVICE, compute_type=COMPUTE_TYPE)


def _estimate_duration_seconds(path: str) -> float:
    try:
        with wave.open(path, "rb") as wav_file:
            frame_rate = wav_file.getframerate()
            if frame_rate <= 0:
                return 0.0
            return wav_file.getnframes() / frame_rate
    except wave.Error:
        return 0.0


def _repair_wav_header(path: str) -> None:
    try:
        data = Path(path).read_bytes()
    except OSError:
        return

    if len(data) < 44 or data[:4] != b"RIFF" or data[8:12] != b"WAVE" or data[36:40] != b"data":
        return

    actual_data_size = max(0, len(data) - 44)
    expected_data_size = int.from_bytes(data[40:44], "little", signed=False)
    if expected_data_size == actual_data_size:
        return

    repaired = bytearray(data)
    repaired[4:8] = (36 + actual_data_size).to_bytes(4, "little", signed=False)
    repaired[40:44] = actual_data_size.to_bytes(4, "little", signed=False)
    Path(path).write_bytes(repaired)


def _normalize_transcript(text: str, *, is_wake_check: bool, wake_word: str | None = None) -> str:
    normalized = " ".join(str(text).split())

    if is_wake_check:
        wake_word_text = " ".join(str(wake_word or WAKE_INITIAL_PROMPT or "assistant").lower().split())
        cleaned_tokens = re.findall(r"[a-z0-9]+", normalized.lower())
        wake_tokens = re.findall(r"[a-z0-9]+", wake_word_text)

        if cleaned_tokens and wake_tokens:
            if len(wake_tokens) == 1 and all(token == wake_tokens[0] for token in cleaned_tokens):
                return wake_word_text

            repeated_phrase = " ".join(cleaned_tokens)
            target_phrase = " ".join(wake_tokens)
            if repeated_phrase and target_phrase:
                collapsed_phrase = re.sub(
                    rf"(?:{re.escape(target_phrase)}(?:\s+|$))+",
                    target_phrase,
                    repeated_phrase,
                ).strip()
                if collapsed_phrase == target_phrase:
                    return wake_word_text

            # Wake checks are binary for our workflow: preserve only the wake word itself.
            # If the short clip does not contain the wake word, discard the hallucinated text.
            if target_phrase and target_phrase in repeated_phrase:
                return wake_word_text

        return ""

    replacements = (
        (r"\bset remainder\b", "set reminder"),
        (r"\bcreate (?:a )?remainder\b", "create a reminder"),
        (r"\bremind her\b(?=\s+(for|at|on|today|tomorrow|\d))", "reminder"),
        (r"\bremainder\b(?=\s+(for|at|on|today|tomorrow|\d))", "reminder"),
    )
    for pattern, replacement in replacements:
        normalized = re.sub(pattern, replacement, normalized, flags=re.IGNORECASE)

    normalized = re.sub(
        r"(@[a-z0-9.-]+\.)\s+([a-z]{2,})(?=\b)",
        r"\1\2",
        normalized,
        flags=re.IGNORECASE,
    )
    normalized = re.sub(
        r"(@[a-z0-9.-]+\.[a-z]{2,})\b",
        lambda match: match.group(1).lower(),
        normalized,
        flags=re.IGNORECASE,
    )
    normalized = _normalize_spoken_email_fragments(normalized)

    return normalized


def _normalize_spoken_email_fragments(value: str) -> str:
    number_words = {
        "zero": "0",
        "oh": "0",
        "o": "0",
        "one": "1",
        "two": "2",
        "to": "2",
        "too": "2",
        "three": "3",
        "four": "4",
        "for": "4",
        "five": "5",
        "six": "6",
        "seven": "7",
        "eight": "8",
        "ate": "8",
        "nine": "9",
    }

    def compact_number_words(match: re.Match[str]) -> str:
        words = re.findall(r"[a-z]+", match.group(0).lower())
        digits = [number_words[word] for word in words if word in number_words]
        return "".join(digits) if len(digits) >= 3 else match.group(0)

    normalized = re.sub(
        r"\b(?:zero|oh|o|one|two|to|too|three|four|for|five|six|seven|eight|ate|nine)(?:\s+(?:zero|oh|o|one|two|to|too|three|four|for|five|six|seven|eight|ate|nine)){2,}\b",
        compact_number_words,
        value,
        flags=re.IGNORECASE,
    )

    normalized = re.sub(r"\bd\s*y\s*p\s*i\s*u\b", "dypiu", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"\bdypiu\s+dot\s+a\s*c\s+dot\s+in\b", "dypiu.ac.in", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"\bdypiu\s+dot\s+ac\s+dot\s+in\b", "dypiu.ac.in", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"\bdypiu\s+ac\s+in\b", "dypiu.ac.in", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"\bdypiu\.ac\.in\b", "dypiu.ac.in", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"\bdpyu\.ac\.in\b", "dypiu.ac.in", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"@dpyu\.ac\.in\b", "@dypiu.ac.in", normalized, flags=re.IGNORECASE)
    return normalized


def _join_single_character_runs(value: str) -> str:
    tokens = str(value).split()
    joined: list[str] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if re.fullmatch(r"[A-Za-z0-9]", token):
            run: list[str] = []
            while index < len(tokens) and re.fullmatch(r"[A-Za-z0-9]", tokens[index]):
                run.append(tokens[index].lower())
                index += 1
            if len(run) >= 2:
                joined.append("".join(run))
            else:
                joined.extend(run)
            continue
        joined.append(token)
        index += 1
    return " ".join(joined)


def _transcribe_with_whisper(path: str, *, is_wake_check: bool):
    if model is None:
        raise RuntimeError("Whisper model is not available.")

    transcribe_kwargs = {
        "language": LANGUAGE,
        "condition_on_previous_text": False,
        "beam_size": 5,
        "best_of": 5,
        "temperature": 0,
    }
    initial_prompt = WAKE_INITIAL_PROMPT if is_wake_check else COMMAND_INITIAL_PROMPT
    if initial_prompt:
        transcribe_kwargs["initial_prompt"] = initial_prompt
    hotwords = WAKE_HOTWORDS if is_wake_check else COMMAND_HOTWORDS
    if hotwords:
        transcribe_kwargs["hotwords"] = hotwords
    if is_wake_check:
        transcribe_kwargs["vad_filter"] = True

    segments, info = model.transcribe(path, **transcribe_kwargs)
    text = " ".join(segment.text.strip() for segment in segments).strip()
    return {
        "text": text,
        "language": info.language,
        "language_probability": info.language_probability,
        "duration": info.duration,
        "provider": "whisper",
    }


def _transcribe_with_elevenlabs(path: str):
    if not ELEVENLABS_API_KEY:
        raise RuntimeError("ELEVENLABS_API_KEY is not configured.")

    with open(path, "rb") as audio_file:
        response = requests.post(
            "https://api.elevenlabs.io/v1/speech-to-text",
            headers={"xi-api-key": ELEVENLABS_API_KEY},
            data={
                "model_id": ELEVENLABS_MODEL_ID,
                "language_code": ELEVENLABS_LANGUAGE,
            },
            files={"file": (Path(path).name, audio_file, "audio/wav")},
            timeout=ELEVENLABS_TIMEOUT_SECONDS,
        )

    response.raise_for_status()
    payload = response.json()
    return {
        "text": str(payload.get("text") or "").strip(),
        "language": payload.get("language_code") or ELEVENLABS_LANGUAGE,
        "language_probability": payload.get("language_probability"),
        "duration": payload.get("audio_duration"),
        "provider": "elevenlabs",
        "raw": payload,
    }


def _transcribe_with_deepgram(path: str, *, is_wake_check: bool):
    if not DEEPGRAM_API_KEY:
        raise RuntimeError("DEEPGRAM_API_KEY is not configured.")

    params: list[tuple[str, str]] = [
        ("model", DEEPGRAM_MODEL),
        ("language", DEEPGRAM_LANGUAGE),
        ("smart_format", "true"),
        ("punctuate", "true"),
    ]
    keyterms = ["assistant"] if is_wake_check else [
        "assistant",
        "send email",
        "email address",
        "message",
        "subject",
        "D Y P I U",
        "dypiu",
        "dypiu.ac.in",
        "2022080233",
        "2022080233@dypiu.ac.in",
    ]
    params.extend(("keyterm", keyterm) for keyterm in keyterms)

    with open(path, "rb") as audio_file:
        response = requests.post(
            "https://api.deepgram.com/v1/listen",
            headers={
                "Authorization": f"Token {DEEPGRAM_API_KEY}",
                "Content-Type": "audio/wav",
            },
            params=params,
            data=audio_file,
            timeout=DEEPGRAM_TIMEOUT_SECONDS,
        )

    if not response.ok:
        raise RuntimeError(f"Deepgram {response.status_code}: {response.text[:500]}")
    payload = response.json()
    alternatives = (
        payload.get("results", {})
        .get("channels", [{}])[0]
        .get("alternatives", [{}])
    )
    best = alternatives[0] if alternatives else {}
    metadata = payload.get("metadata", {})
    return {
        "text": str(best.get("transcript") or "").strip(),
        "language": DEEPGRAM_LANGUAGE,
        "language_probability": best.get("confidence"),
        "duration": metadata.get("duration"),
        "provider": "deepgram",
        "raw": payload,
    }


@app.get("/health")
def health():
    return jsonify(
        {
            "status": "ok",
            "provider": TRANSCRIBE_PROVIDER,
            "model": MODEL_NAME,
            "device": DEVICE,
            "compute_type": COMPUTE_TYPE,
            "language": LANGUAGE,
            "wake_max_seconds": WAKE_MAX_SECONDS,
            "whisper_fallback_enabled": WHISPER_FALLBACK_ENABLED,
            "deepgram_model": DEEPGRAM_MODEL if DEEPGRAM_API_KEY else None,
            "elevenlabs_model_id": ELEVENLABS_MODEL_ID if ELEVENLABS_API_KEY else None,
        }
    )


@app.post("/transcribe")
def transcribe():
    audio = request.files.get("audio")
    if audio is None:
        return (
            jsonify(
                {
                    "error": "Missing audio file. Send multipart/form-data with field name 'audio'."
                }
            ),
            400,
        )

    suffix = Path(audio.filename or "audio.wav").suffix or ".wav"
    tmp_path = ""

    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            audio.save(tmp.name)
            tmp_path = tmp.name

        requested_mode = str(request.form.get("mode") or "").strip().lower()
        requested_wake_word = str(request.form.get("wake_word") or WAKE_INITIAL_PROMPT or "assistant").strip()
        _repair_wav_header(tmp_path)
        duration_seconds = _estimate_duration_seconds(tmp_path)
        is_wake_check = requested_mode == "wake_check" or duration_seconds <= WAKE_MAX_SECONDS

        transcription = None
        provider_error = None
        if TRANSCRIBE_PROVIDER == "deepgram":
            try:
                transcription = _transcribe_with_deepgram(tmp_path, is_wake_check=is_wake_check)
            except Exception as error:
                provider_error = error
                if not WHISPER_FALLBACK_ENABLED:
                    raise
                transcription = _transcribe_with_whisper(tmp_path, is_wake_check=is_wake_check)
                transcription["fallback_from"] = "deepgram"
                transcription["fallback_reason"] = str(error)
        elif TRANSCRIBE_PROVIDER == "elevenlabs":
            try:
                transcription = _transcribe_with_elevenlabs(tmp_path)
            except Exception as error:
                provider_error = error
                if not WHISPER_FALLBACK_ENABLED:
                    raise
                transcription = _transcribe_with_whisper(tmp_path, is_wake_check=is_wake_check)
                transcription["fallback_from"] = "elevenlabs"
                transcription["fallback_reason"] = str(error)
        else:
            transcription = _transcribe_with_whisper(tmp_path, is_wake_check=is_wake_check)

        text = transcription["text"]
        text = _join_single_character_runs(text)
        text = _normalize_transcript(text, is_wake_check=is_wake_check, wake_word=requested_wake_word)

        return jsonify(
            {
                "text": text,
                "language": transcription.get("language"),
                "language_probability": transcription.get("language_probability"),
                "duration": transcription.get("duration"),
                "mode": "wake_check" if is_wake_check else "command",
                "provider": transcription.get("provider"),
                "fallback_from": transcription.get("fallback_from"),
                "fallback_reason": transcription.get("fallback_reason"),
                "provider_error": str(provider_error) if provider_error and not transcription.get("fallback_from") else None,
            }
        )
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.remove(tmp_path)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5002)

