from __future__ import annotations

import os
import shutil
import tempfile
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, request, send_file
from gtts import gTTS
import miniaudio


HOST = os.environ.get("GTTS_HOST", "127.0.0.1")
PORT = int(os.environ.get("GTTS_PORT", "5001"))
LANGUAGE = os.environ.get("GTTS_LANGUAGE", "en")
SAVE_DIR = Path(os.environ.get("GTTS_SAVE_DIR", str(Path.home() / "Downloads")))
SAVE_MODE = os.environ.get("GTTS_SAVE_MODE", "latest").strip().lower()
LATEST_AUDIO_NAME = "n8n_voice_response_latest.wav"
LATEST_TEXT_NAME = "n8n_voice_response_latest.txt"

app = Flask(__name__)


def _extract_text(path_text: str | None = None) -> str:
    if path_text:
        return path_text.strip()

    if request.is_json:
        data = request.get_json(silent=True) or {}
        return str(data.get("text") or data.get("response") or "").strip()

    return str(
        request.form.get("text")
        or request.form.get("response")
        or request.args.get("text")
        or request.args.get("response")
        or ""
    ).strip()


@app.get("/health")
def health():
    return jsonify(
        {
            "status": "ok",
            "language": LANGUAGE,
            "save_dir": str(SAVE_DIR),
            "save_mode": SAVE_MODE,
        }
    )


@app.route("/tts", methods=["GET", "POST"])
@app.route("/tts/<path:path_text>", methods=["GET"])
def text_to_speech(path_text: str | None = None):
    text = _extract_text(path_text)
    if not text:
        return jsonify({"error": "Missing text. Send JSON/form field 'text' or call /tts/<text>."}), 400

    tmp_mp3 = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
    tmp_mp3_path = Path(tmp_mp3.name)
    tmp_mp3.close()
    tmp_wav = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
    tmp_wav_path = Path(tmp_wav.name)
    tmp_wav.close()

    try:
        gTTS(text=text, lang=LANGUAGE).save(str(tmp_mp3_path))
        decoded = miniaudio.decode_file(
            str(tmp_mp3_path),
            output_format=miniaudio.SampleFormat.SIGNED16,
            nchannels=1,
            sample_rate=8000,
        )
        miniaudio.wav_write_file(str(tmp_wav_path), decoded)
        SAVE_DIR.mkdir(parents=True, exist_ok=True)
        if SAVE_MODE in {"timestamped", "both"}:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            audio_path = SAVE_DIR / f"n8n_voice_response_{timestamp}.wav"
            text_path = SAVE_DIR / f"n8n_voice_response_{timestamp}.txt"
            shutil.copyfile(tmp_wav_path, audio_path)
            text_path.write_text(text, encoding="utf-8")

        if SAVE_MODE in {"latest", "both"}:
            shutil.copyfile(tmp_wav_path, SAVE_DIR / LATEST_AUDIO_NAME)
            (SAVE_DIR / LATEST_TEXT_NAME).write_text(text, encoding="utf-8")

        return send_file(
            tmp_wav_path,
            mimetype="audio/wav",
            as_attachment=True,
            download_name="response.wav",
        )
    finally:
        try:
            tmp_mp3_path.unlink(missing_ok=True)
        except PermissionError:
            pass
        try:
            tmp_wav_path.unlink(missing_ok=True)
        except PermissionError:
            pass


if __name__ == "__main__":
    app.run(host=HOST, port=PORT)

