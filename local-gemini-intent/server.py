from __future__ import annotations

import json
import os
import re
import sys
from urllib.parse import quote
from datetime import datetime, timedelta, timezone

import requests
from flask import Flask, jsonify, request


HOST = os.environ.get("GEMINI_INTENT_HOST", "127.0.0.1")
PORT = int(os.environ.get("GEMINI_INTENT_PORT", "5003"))
API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash").strip()
POLLINATIONS_API_KEY = os.environ.get("POLLINATIONS_API_KEY", "").strip()
POLLINATIONS_MODEL = os.environ.get("POLLINATIONS_MODEL", "gpt-5-mini").strip()
TIMEOUT_SECONDS = float(os.environ.get("GEMINI_TIMEOUT_SECONDS", "12"))
LOCAL_ZONE = os.environ.get("VOICE_ASSISTANT_TIMEZONE", "Asia/Kolkata")

app = Flask(__name__)
PENDING_ACTION: dict | None = None
PENDING_FOLLOWUP: dict | None = None

# Easy-to-edit contact alias list. Keep names lowercase or natural case;
# lookup is case-insensitive and ignores simple punctuation.
CONTACT_ALIASES = {
    "Aayush": "20220802333@dypiu.ac.in",
    "Simran": "20220802054@dypiu.ac.in",
    "dhruva": "yandrapu.dhruva@gmail.com",
    "mam": "anju.chaurasia@dypiu.ac.in",
    "vedant": "20220802204@dypiu.ac.in",
}


def _log_event(label: str, payload: dict) -> None:
    try:
        safe_payload = dict(payload)
        action = safe_payload.get("pending_action")
        if isinstance(action, dict):
            tool_input = action.get("tool_input")
            if isinstance(tool_input, dict) and tool_input.get("body"):
                redacted_input = dict(tool_input)
                redacted_input["body"] = "<redacted>"
                safe_action = dict(action)
                safe_action["tool_input"] = redacted_input
                safe_payload["pending_action"] = safe_action
        print(f"[intent] {label}: {json.dumps(safe_payload, ensure_ascii=True, default=str)}", file=sys.stderr, flush=True)
    except Exception:
        pass


INTENT_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "tool_name": {
            "type": "STRING",
            "enum": ["send_email", "set_reminder", "respond"],
        },
        "tool_input": {
            "type": "OBJECT",
            "properties": {
                "to": {"type": "STRING"},
                "subject": {"type": "STRING"},
                "body": {"type": "STRING"},
                "title": {"type": "STRING"},
                "date_time": {"type": "STRING"},
                "message": {"type": "STRING"},
            },
        },
        "corrected_transcript": {"type": "STRING"},
        "confidence": {"type": "NUMBER"},
        "missing_fields": {
            "type": "ARRAY",
            "items": {"type": "STRING"},
        },
    },
    "required": ["tool_name", "tool_input", "corrected_transcript", "confidence", "missing_fields"],
}


def _extract_transcript(payload) -> str:
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            return payload.strip()

    if not isinstance(payload, dict):
        return ""

    if isinstance(payload.get("text"), str):
        return payload["text"].strip()

    messages = payload.get("messages")
    if isinstance(messages, list) and messages:
        for message in reversed(messages):
            if isinstance(message, dict) and message.get("role") == "user":
                return str(message.get("content") or "").strip()
        last = messages[-1]
        if isinstance(last, dict):
            return str(last.get("content") or "").strip()

    return ""


def _current_time() -> str:
    if LOCAL_ZONE in {"Asia/Kolkata", "Asia/Calcutta"}:
        return _local_now().isoformat(timespec="seconds")
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _local_now() -> datetime:
    if LOCAL_ZONE in {"Asia/Kolkata", "Asia/Calcutta"}:
        return datetime.now(timezone(timedelta(hours=5, minutes=30)))
    return datetime.now().astimezone()


def _build_prompt(transcript: str) -> str:
    return "\n".join(
        [
            "You are the context-understanding layer for a local voice assistant.",
            f"Current local date/time is {_current_time()} in {LOCAL_ZONE}.",
            "Input is speech-to-text output, so it may contain mistakes.",
            "Correct obvious speech-to-text mistakes before extracting fields.",
            "Extract one intent only: send_email, set_reminder, or respond.",
            "For email:",
            "- The user may speak a saved contact name instead of an email address.",
            f"- Contact aliases are: {', '.join(CONTACT_ALIASES.keys())}.",
            "- If the contact alias is not found, respond with exactly: contact not found.",
            "- Convert spoken emails into valid addresses for any domain, not just one domain.",
            "- Understand words like at, dot, underscore, dash, hyphen, plus, zero, oh, one, two, three, four, five, six, seven, eight, nine.",
            "- Put the recipient in tool_input.to.",
            "- Put the message content in tool_input.body.",
            "- If no subject is spoken, use subject 'Voice assistant message'.",
            "- Do not invent an email address. If the address or body is unclear, use tool_name respond and ask the user to repeat the missing part.",
            "- Never add non-English characters inside an email address.",
            "For reminders/calendar:",
            "- Use set_reminder for reminders, calendar events, meetings, alarms, and schedules.",
            "- Put title in tool_input.title.",
            "- Put date_time as ISO 8601 with +05:30 if date/time is clear.",
            "- If date or time is unclear, use respond and ask for the missing field.",
            "For normal questions and chat:",
            "- Use respond and put the spoken answer in tool_input.message.",
            "- Answer basic questions directly: spelling, translation, today's date, current time, day, year, math, definitions, short explanations, and simple conversation.",
            "- Keep voice replies concise, usually one or two short sentences.",
            "- For translation, return only the translated sentence unless a short clarification is needed.",
            "- If asked for live weather without a location, ask which city.",
            "- If asked for live data you cannot know, say what detail you need instead of inventing it.",
            "Return only JSON matching the schema.",
            "",
            f"Transcript: {transcript}",
        ]
    )


def _build_general_answer_prompt(transcript: str) -> str:
    return "\n".join(
        [
            "You are Gemini running inside a local voice assistant.",
            f"Current local date/time is {_current_time()} in {LOCAL_ZONE}.",
            "Answer the user's general question directly and naturally.",
            "Keep the reply suitable for text-to-speech: concise, clear, and usually under 60 words.",
            "You can answer general knowledge, definitions, spelling, explanations, translation, math, and casual questions.",
            "If the question depends on very current information and you are not sure, say that briefly.",
            "Do not return JSON. Return only the spoken answer text.",
            "",
            f"User: {transcript}",
        ]
    )


def _clean_text(value) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _normalize_contact_alias(value: str) -> str:
    alias = _clean_text(value).lower()
    alias = re.sub(r"^(?:to|for|mr|mrs|ms|miss|professor|sir|dear)\s+", "", alias)
    alias = re.sub(r"[^\w\s]", "", alias)
    alias = re.sub(r"\s+", " ", alias).strip()
    if alias == "maam":
        alias = "mam"
    return alias


def _lookup_contact_email(value: str) -> str:
    wanted = _normalize_contact_alias(value)
    for alias, email in CONTACT_ALIASES.items():
        if _normalize_contact_alias(alias) == wanted:
            return _normalize_email_candidate(email)
    return ""


def _looks_like_contact_alias(value: str) -> bool:
    cleaned = _normalize_contact_alias(value)
    if not cleaned or "@" in cleaned or "." in cleaned:
        return False
    if len(cleaned.split()) > 3:
        return False
    return bool(re.fullmatch(r"[a-z0-9 ]{2,40}", cleaned))


def _is_yes(value: str) -> bool:
    return bool(re.search(r"\b(yes|yeah|yep|correct|confirm|send it|do it|okay|ok|sure)\b", value, re.I))


def _is_no(value: str) -> bool:
    return bool(re.search(r"\b(no|nope|cancel|stop|don't|do not|wrong|incorrect)\b", value, re.I))


def _is_cancel_command(value: str) -> bool:
    text = _clean_text(value).lower().strip(" .!?,")
    return bool(
        re.fullmatch(
            r"(no|nope|cancel|cancel it|stop|stop it|don't|dont|do not|never mind|nevermind|no cancel|abort)",
            text,
            re.I,
        )
    )


def _confirmation_prompt(action: dict) -> str:
    tool_input = action.get("tool_input") if isinstance(action, dict) else {}
    if not isinstance(tool_input, dict):
        tool_input = {}
    if action.get("tool_name") == "send_email":
        to = _clean_text(tool_input.get("to"))
        subject = _clean_text(tool_input.get("subject"))
        body = _clean_text(tool_input.get("body"))
        if len(body) > 120:
            body = body[:117].rstrip() + "..."
        return f"I heard email to {to}, subject {subject}, message {body}. Should I send it?"
    return "Should I continue?"


def _respond(message: str, *, listen_again: bool = False, missing_fields: list[str] | None = None) -> dict:
    return {
        "tool_name": "respond",
        "tool_input": {
            "message": message,
            "listen_again": listen_again,
        },
        "corrected_transcript": "",
        "confidence": 0.9,
        "missing_fields": missing_fields or [],
        "listen_again": listen_again,
    }


def _extract_language_after(pattern: str, text: str) -> str:
    match = re.search(pattern, text, re.I)
    return _clean_text(match.group(1)).lower() if match else ""


def _extract_translation_followup_request(transcript: str) -> dict | None:
    text = _clean_text(transcript)
    lower = text.lower()
    if "translate" not in lower:
        return None

    language_only = re.fullmatch(
        r"translate(?:\s+(?:this|the)\s+(?:sentence|line|phrase|text|word))?(?:\s+for\s+me)?\s+(?:from\s+([a-zA-Z][a-zA-Z-]*)\s+)?(?:to|into|in)\s+([a-zA-Z][a-zA-Z-]*)\s*(?:for me|please)?[?.!]*",
        text,
        re.I,
    ) or re.fullmatch(
        r"translate(?:\s+(?:this|the)\s+(?:sentence|line|phrase|text|word))?(?:\s+for\s+me)?\s+from\s+([a-zA-Z][a-zA-Z-]*)\s+to\s+([a-zA-Z][a-zA-Z-]*)\s*(?:for me|please)?[?.!]*",
        text,
        re.I,
    )
    if language_only:
        return {
            "type": "translation",
            "source_language": (language_only.group(1) or "auto").lower(),
            "target_language": language_only.group(2).lower(),
            "original_request": transcript,
        }

    source = _extract_language_after(r"\bfrom\s+([a-zA-Z][a-zA-Z\s-]{1,30}?)(?:\s+to|\s+into|\s+in|$)", text)
    target = _extract_language_after(r"\b(?:to|into|in)\s+([a-zA-Z][a-zA-Z\s-]{1,30})\b", text)
    without_languages = re.sub(r"\bfrom\s+[a-zA-Z][a-zA-Z\s-]{1,30}?(?=\s+(?:to|into|in)|$)", "", lower)
    without_languages = re.sub(r"\b(?:to|into|in)\s+[a-zA-Z][a-zA-Z\s-]{1,30}\b", "", without_languages)
    remainder = _clean_text(
        re.sub(
            r"\b(translate|this|sentence|line|phrase|text|word|for me|please|from|to|into|in)\b",
            " ",
            without_languages,
            flags=re.I,
        )
    ).strip(" ?.,")

    if target and len(remainder) <= 2:
        return {
            "type": "translation",
            "source_language": source or "auto",
            "target_language": target,
            "original_request": transcript,
        }

    return None


def _build_translation_prompt(sentence: str, followup: dict) -> str:
    source = _clean_text(followup.get("source_language") or "auto")
    target = _clean_text(followup.get("target_language") or "")
    source_instruction = "Detect the source language automatically" if source == "auto" else f"The source language is {source}"
    return "\n".join(
        [
            "Translate the user's sentence.",
            source_instruction + ".",
            f"The target language is {target}.",
            "Return only the translated sentence. Do not explain.",
            "",
            f"Sentence: {sentence}",
        ]
    )


def _call_pollinations_text(prompt: str) -> str:
    if not POLLINATIONS_API_KEY:
        raise RuntimeError("POLLINATIONS_API_KEY is not configured.")

    body = {
        "model": POLLINATIONS_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2,
        "max_tokens": 220,
    }
    response = requests.post(
        "https://gen.pollinations.ai/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {POLLINATIONS_API_KEY}",
            "Content-Type": "application/json",
        },
        json=body,
        timeout=TIMEOUT_SECONDS,
    )
    if not response.ok:
        raise RuntimeError(f"Pollinations {response.status_code}: {response.text[:800]}")
    payload = response.json()
    text = _clean_text(payload.get("choices", [{}])[0].get("message", {}).get("content", ""))
    if not text:
        raise RuntimeError("Pollinations returned an empty response.")
    return text


def _handle_pending_followup(transcript: str) -> dict | None:
    global PENDING_FOLLOWUP
    if not PENDING_FOLLOWUP:
        return None

    followup = PENDING_FOLLOWUP
    PENDING_FOLLOWUP = None

    if _is_cancel_command(transcript):
        _log_event("cancelled_pending_followup", {"transcript": transcript, "followup": followup})
        return _respond("Okay, I cancelled it.")

    if followup.get("type") == "translation":
        try:
            message = _call_pollinations_text(_build_translation_prompt(transcript, followup))
        except Exception as error:
            message = f"I could not translate that right now: {str(error)[:120]}"
        return {
            "tool_name": "respond",
            "tool_input": {"message": message},
            "corrected_transcript": transcript,
            "confidence": 0.9,
            "missing_fields": [],
            "listen_again": False,
        }

    if followup.get("type") == "weather_location":
        return _weather_intent(f"weather in {transcript}")

    if followup.get("type") in {"email_missing_fields", "reminder_missing_fields"}:
        original = _clean_text(followup.get("original_request"))
        combined = _clean_text(f"{original} {transcript}")
        seed = {"tool_name": "set_reminder"} if followup.get("type") == "reminder_missing_fields" else {}
        result = _postprocess_intent(seed, combined)
        result["corrected_transcript"] = combined
        return result

    original = _clean_text(followup.get("original_request"))
    question = _clean_text(followup.get("assistant_question"))
    combined = f"Original request: {original}\nAssistant asked: {question}\nUser follow-up answer: {transcript}"
    try:
        return _call_pollinations_general_answer(combined) if POLLINATIONS_API_KEY else _call_gemini_general_answer(combined)
    except Exception as error:
        result = _fallback_intent(transcript, error)
        result["listen_again"] = False
        return result


def _response_requests_user_input(result: dict, transcript: str) -> dict:
    global PENDING_FOLLOWUP
    if not isinstance(result, dict) or result.get("tool_name") != "respond":
        return result

    tool_input = result.get("tool_input")
    if not isinstance(tool_input, dict):
        tool_input = {}
        result["tool_input"] = tool_input

    message = _clean_text(tool_input.get("message"))
    missing_fields = result.get("missing_fields") if isinstance(result.get("missing_fields"), list) else []
    asks_question = message.endswith("?") or bool(
        re.search(
            r"\b(please repeat|please provide|please share|please paste|please tell|provide the|share the|say yes|say no|send the|should i|do you want me to)\b",
            message,
            re.I,
        )
    )

    if tool_input.get("listen_again") is True or result.get("listen_again") is True:
        return result

    if missing_fields or asks_question:
        result["listen_again"] = True
        tool_input["listen_again"] = True
        if "confirmation" not in missing_fields:
            normalized_missing = [str(v).lower() for v in missing_fields]
            followup_type = "generic"
            if "location" in normalized_missing:
                followup_type = "weather_location"
            elif any(field in normalized_missing for field in ["email address", "message body"]):
                followup_type = "email_missing_fields"
            elif any(field in normalized_missing for field in ["reminder title", "date or time"]):
                followup_type = "reminder_missing_fields"
            PENDING_FOLLOWUP = {
                "type": followup_type,
                "original_request": transcript,
                "assistant_question": message,
            }
        return result

    return result


def _handle_pending_confirmation(transcript: str) -> dict | None:
    global PENDING_ACTION
    if not PENDING_ACTION:
        return None

    if _is_yes(transcript):
        _log_event("confirmed_pending_action", {"transcript": transcript, "pending_action": PENDING_ACTION})
        action = PENDING_ACTION
        PENDING_ACTION = None
        action["confirmed"] = True
        action["listen_again"] = False
        return action

    if _is_no(transcript):
        _log_event("cancelled_pending_action", {"transcript": transcript})
        PENDING_ACTION = None
        return _respond("Okay, I cancelled it.")

    _log_event("unclear_pending_confirmation", {"transcript": transcript})
    result = _respond("Please say yes to send it, or no to cancel.", listen_again=True, missing_fields=["confirmation"])
    result["corrected_transcript"] = transcript
    return result


def _require_confirmation_if_needed(result: dict, transcript: str) -> dict:
    global PENDING_ACTION
    if not isinstance(result, dict):
        return result
    if result.get("tool_name") != "send_email":
        return result
    if result.get("confirmed") is True:
        return result

    tool_input = result.get("tool_input")
    if not isinstance(tool_input, dict):
        return result
    if not _is_valid_email(_clean_text(tool_input.get("to"))) or not _clean_text(tool_input.get("body")):
        return result

    PENDING_ACTION = {
        "tool_name": "send_email",
        "tool_input": {
            "to": _clean_text(tool_input.get("to")),
            "subject": _clean_text(tool_input.get("subject") or "Voice assistant message"),
            "body": _clean_text(tool_input.get("body")),
        },
        "corrected_transcript": transcript,
        "confidence": result.get("confidence", 0.9),
        "missing_fields": [],
    }
    _log_event("stored_pending_action", {"transcript": transcript, "pending_action": PENDING_ACTION})
    response = _respond(_confirmation_prompt(PENDING_ACTION), listen_again=True, missing_fields=["confirmation"])
    response["corrected_transcript"] = transcript
    return response


def _join_single_character_runs(value: str) -> str:
    tokens = _clean_text(value).split(" ")
    output: list[str] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if re.fullmatch(r"[a-z0-9]", token, flags=re.IGNORECASE):
            run: list[str] = []
            while index < len(tokens) and re.fullmatch(r"[a-z0-9]", tokens[index], flags=re.IGNORECASE):
                run.append(tokens[index].lower())
                index += 1
            output.append("".join(run) if len(run) >= 2 else run[0])
            continue
        output.append(token)
        index += 1
    return " ".join(output)


def _normalize_email_candidate(value: str) -> str:
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
    email = _join_single_character_runs(value).lower()
    for word, digit in number_words.items():
        email = re.sub(rf"\b{word}\b", digit, email)
    email = (
        email.replace(" at the rate ", " @ ")
        .replace(" at rate ", " @ ")
        .replace(" at ", " @ ")
    )
    email = re.sub(r"\b(dot|point)\b", ".", email)
    email = re.sub(r"\b(underscore)\b", "_", email)
    email = re.sub(r"\b(dash|hyphen)\b", "-", email)
    email = re.sub(r"\bplus\b", "+", email)
    email = re.sub(r"\s*@\s*", "@", email)
    email = re.sub(r"\s*\.\s*", ".", email)
    email = re.sub(r"\s*_\s*", "_", email)
    email = re.sub(r"\s*-\s*", "-", email)
    email = re.sub(r"\s*\+\s*", "+", email)
    email = re.sub(r"\s+", "", email)
    email = re.sub(r"[^a-z0-9@._+-]", "", email)
    email = re.sub(r"\.{2,}", ".", email)
    email = re.sub(r"@{2,}", "@", email)
    return email.strip("._-+")


def _is_valid_email(value: str) -> bool:
    return bool(re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", value or ""))


def _looks_like_email_request(value: str) -> bool:
    return bool(
        re.search(
            r"\b(send|write|compose)\b(?:\s+\w+){0,4}\s+(?:email|mail)\b|\b(?:email|mail)\s+(?:to\s+)?\w+",
            value,
            re.I,
        )
    )


def _looks_like_reminder_request(value: str) -> bool:
    return bool(
        re.search(
            r"\b(remind|reminder|schedule|calendar|meeting|appointment|alarm)\b",
            value,
            re.I,
        )
    )


def _looks_like_weather_request(value: str) -> bool:
    return bool(re.search(r"\b(weather|temperature|forecast|rain|raining)\b", value, re.I))


def _basic_question_intent(transcript: str) -> dict | None:
    text = _clean_text(transcript)
    lower = text.lower()
    now = _local_now()

    if re.search(r"\b(date|day|time|year)\b", lower) and re.search(r"\b(today|now|current|what|tell)\b", lower):
        parts = []
        if "day" in lower:
            parts.append(now.strftime("Today is %A"))
        if "date" in lower or "today" in lower:
            parts.append(now.strftime("the date is %d %B %Y"))
        if "time" in lower or "now" in lower or "current" in lower:
            parts.append(now.strftime("the time is %I:%M %p"))
        if "year" in lower and "date" not in lower:
            parts.append(now.strftime("the year is %Y"))
        message = ", and ".join(parts) + "."
        message = message[0].upper() + message[1:]
        return {
            "tool_name": "respond",
            "tool_input": {"message": message},
            "corrected_transcript": transcript,
            "confidence": 0.95,
            "missing_fields": [],
        }

    spell_match = re.search(r"\bspell(?:\s+the\s+word)?\s+([a-zA-Z][a-zA-Z'-]*)\b", text, re.I)
    if spell_match:
        word = spell_match.group(1)
        letters = " ".join(word.upper())
        return {
            "tool_name": "respond",
            "tool_input": {"message": f"{word} is spelled {letters}."},
            "corrected_transcript": transcript,
            "confidence": 0.95,
            "missing_fields": [],
        }

    return None


def _extract_weather_location(value: str) -> str:
    cleaned = _clean_text(value)
    patterns = [
        r"\bweather\s+(?:today\s+)?(?:in|at|for)\s+(.+)$",
        r"\btemperature\s+(?:today\s+)?(?:in|at|for)\s+(.+)$",
        r"\bforecast\s+(?:today\s+)?(?:in|at|for)\s+(.+)$",
        r"\bis\s+it\s+raining\s+(?:in|at)\s+(.+)$",
    ]
    for pattern in patterns:
        match = re.search(pattern, cleaned, re.I)
        if match:
            location = re.sub(r"\b(today|now|right now|currently)\b", "", match.group(1), flags=re.I)
            return _clean_text(location).strip(" ?.,")
    return ""


def _weather_intent(transcript: str) -> dict | None:
    if not _looks_like_weather_request(transcript):
        return None

    location = _extract_weather_location(transcript)
    if not location:
        return {
            "tool_name": "respond",
            "tool_input": {"message": "Which city should I check the weather for?"},
            "corrected_transcript": transcript,
            "confidence": 0.9,
            "missing_fields": ["location"],
        }

    try:
        response = requests.get(
            f"https://wttr.in/{quote(location)}",
            params={"format": "j1"},
            timeout=8,
            headers={"User-Agent": "n8n-voice-assistant"},
        )
        response.raise_for_status()
        payload = response.json()
        current = payload.get("current_condition", [{}])[0]
        area = (
            payload.get("nearest_area", [{}])[0]
            .get("areaName", [{}])[0]
            .get("value", location)
        )
        temp_c = current.get("temp_C")
        feels_c = current.get("FeelsLikeC")
        description = current.get("weatherDesc", [{}])[0].get("value", "current conditions")
        humidity = current.get("humidity")
        message = f"Weather in {area}: {description}, {temp_c} degrees Celsius"
        if feels_c:
            message += f", feels like {feels_c}"
        if humidity:
            message += f", humidity {humidity} percent"
        message += "."
    except Exception:
        message = f"I could not fetch live weather for {location} right now."

    return {
        "tool_name": "respond",
        "tool_input": {"message": message},
        "corrected_transcript": transcript,
        "confidence": 0.9,
        "missing_fields": [],
    }


def _wiki_summary_intent(transcript: str) -> dict | None:
    match = re.search(
        r"\b(?:who|what)\s+(?:is|was|are|were)\s+(.+?)\??$|\btell\s+me\s+about\s+(.+?)\??$",
        _clean_text(transcript),
        re.I,
    )
    if not match:
        return None

    topic = _clean_text(match.group(1) or match.group(2)).strip(" ?.,")
    if not topic or len(topic) > 80:
        return None

    try:
        search = requests.get(
            "https://en.wikipedia.org/w/api.php",
            params={
                "action": "query",
                "list": "search",
                "srsearch": topic,
                "format": "json",
                "srlimit": 1,
            },
            timeout=8,
            headers={"User-Agent": "n8n-voice-assistant"},
        )
        search.raise_for_status()
        results = search.json().get("query", {}).get("search", [])
        if not results:
            return None
        title = results[0].get("title")
        summary = requests.get(
            f"https://en.wikipedia.org/api/rest_v1/page/summary/{quote(title)}",
            timeout=8,
            headers={"User-Agent": "n8n-voice-assistant"},
        )
        summary.raise_for_status()
        extract = _clean_text(summary.json().get("extract"))
        if not extract:
            return None
        sentences = re.split(r"(?<=[.!?])\s+", extract)
        message = " ".join(sentences[:2]).strip()
        return {
            "tool_name": "respond",
            "tool_input": {"message": message},
            "corrected_transcript": transcript,
            "confidence": 0.75,
            "missing_fields": [],
            "fallback_source": "wikipedia",
        }
    except Exception:
        return None


def _extract_email_parts(transcript: str) -> dict:
    cleaned = _clean_text(transcript)
    match = re.search(r"\b(?:send|write|compose)\s+(?:an?\s+)?(?:email|mail)\s+(?:to\s+)?(.+)$", cleaned, re.I)
    if not match:
        match = re.search(r"\b(?:email|mail)\s+(?:to\s+)?(.+)$", cleaned, re.I)
    if not match:
        return {}

    tail = _clean_text(match.group(1))
    subject = ""
    body = ""
    recipient_segment = tail

    subject_body = re.search(r"\bsubject\s+(.+?)\s+\b(?:message|body|write|say|saying|in the email)\b\s+(.+)$", tail, re.I)
    if subject_body:
        subject = _clean_text(subject_body.group(1)).strip(" ,.-:")
        body = _clean_text(subject_body.group(2)).strip(" ,.-:")
        recipient_segment = tail[: subject_body.start()]
    else:
        body_match = re.search(r"\b(?:message|body|write|say|saying|in the email)\b\s+(.+)$", tail, re.I)
        if body_match:
            body = _clean_text(body_match.group(1)).strip(" ,.-:")
            recipient_segment = tail[: body_match.start()]

    direct = re.search(r"[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}", tail, re.I)
    if direct:
        recipient_segment = direct.group(0)
        if not body:
            body = _clean_text(tail[direct.end():]).strip(" ,.-:")

    contact_email = _lookup_contact_email(recipient_segment)
    email = contact_email or _normalize_email_candidate(recipient_segment)
    contact_not_found = not contact_email and _looks_like_contact_alias(recipient_segment) and not _is_valid_email(email)

    if not subject and body:
        subject = "Voice assistant message"

    return {
        "to": email,
        "subject": subject,
        "body": body,
        "contact_alias": _normalize_contact_alias(recipient_segment),
        "contact_found": bool(contact_email),
        "contact_not_found": contact_not_found,
    }


def _spoken_number_to_int(value: str) -> int | None:
    words = {
        "zero": 0,
        "oh": 0,
        "one": 1,
        "two": 2,
        "three": 3,
        "four": 4,
        "five": 5,
        "six": 6,
        "seven": 7,
        "eight": 8,
        "nine": 9,
        "ten": 10,
        "eleven": 11,
        "twelve": 12,
    }
    value = value.lower().strip()
    if value.isdigit():
        return int(value)
    return words.get(value)


def _parse_spoken_datetime(transcript: str) -> str:
    now = _local_now()
    text = _clean_text(transcript).lower()

    relative = re.search(r"\bin\s+(\d+|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)\s+(minute|minutes|hour|hours)\b", text)
    if relative:
        amount = _spoken_number_to_int(relative.group(1))
        if amount is not None:
            delta = timedelta(hours=amount) if relative.group(2).startswith("hour") else timedelta(minutes=amount)
            return (now + delta).isoformat(timespec="seconds")

    target_date = now.date()
    if re.search(r"\btomorrow\b", text):
        target_date = (now + timedelta(days=1)).date()

    weekdays = {
        "monday": 0,
        "tuesday": 1,
        "wednesday": 2,
        "thursday": 3,
        "friday": 4,
        "saturday": 5,
        "sunday": 6,
    }
    weekday_match = re.search(r"\bnext\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b|\b(on\s+)?(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", text)
    if weekday_match:
        weekday_name = weekday_match.group(1) or weekday_match.group(3)
        target_weekday = weekdays[weekday_name]
        days_ahead = (target_weekday - now.weekday()) % 7
        if days_ahead == 0 or weekday_match.group(1):
            days_ahead += 7
        target_date = (now + timedelta(days=days_ahead)).date()

    time_match = re.search(
        r"\bat\s+(\d{1,2}|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)(?:[:\s](\d{2}|fifteen|thirty|forty\s+five))?\s*(am|pm|a\.m\.|p\.m\.)?\b",
        text,
    )
    if not time_match:
        return ""

    hour = _spoken_number_to_int(time_match.group(1))
    if hour is None:
        return ""
    minute_text = (time_match.group(2) or "0").replace(" ", "")
    minute_words = {"fifteen": 15, "thirty": 30, "fortyfive": 45}
    minute = int(minute_text) if minute_text.isdigit() else minute_words.get(minute_text, 0)
    meridiem = (time_match.group(3) or "").replace(".", "")
    if meridiem == "pm" and hour < 12:
        hour += 12
    if meridiem == "am" and hour == 12:
        hour = 0

    target = datetime.combine(target_date, datetime.min.time(), tzinfo=now.tzinfo).replace(hour=hour, minute=minute)
    if not re.search(r"\b(today|tomorrow|next\s+\w+|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", text) and target <= now:
        target += timedelta(days=1)
    return target.isoformat(timespec="seconds")


def _extract_reminder_title(transcript: str) -> str:
    text = _clean_text(transcript)
    patterns = [
        r"\bremind\s+me\s+to\s+(.+)$",
        r"\bset\s+(?:a\s+)?reminder\s+to\s+(.+)$",
        r"\breminder\s+to\s+(.+)$",
        r"\bschedule\s+(.+)$",
        r"\badd\s+(.+?)\s+to\s+(?:my\s+)?calendar\b",
    ]
    title = text
    for pattern in patterns:
        match = re.search(pattern, text, re.I)
        if match:
            title = match.group(1)
            break
    title = re.sub(r"\b(?:today|tomorrow|next\s+\w+|on\s+\w+day)\b", "", title, flags=re.I)
    title = re.sub(r"\bat\s+(\d{1,2}|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)(?:[:\s](\d{2}|fifteen|thirty|forty\s+five))?\s*(am|pm|a\.m\.|p\.m\.)?\b", "", title, flags=re.I)
    title = re.sub(r"\bin\s+(\d+|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)\s+(minute|minutes|hour|hours)\b", "", title, flags=re.I)
    return _clean_text(title).strip(" ,.-:") or "Reminder"


def _postprocess_intent(result: dict, transcript: str) -> dict:
    if not isinstance(result, dict):
        result = {}

    tool_name = str(result.get("tool_name") or "respond")
    tool_input = result.get("tool_input")
    if not isinstance(tool_input, dict):
        tool_input = {}

    basic = _basic_question_intent(transcript)
    if basic is not None:
        return basic

    weather = _weather_intent(transcript)
    if weather is not None:
        return weather

    if _looks_like_email_request(transcript):
        extracted = _extract_email_parts(transcript)
        if extracted.get("contact_not_found"):
            result["tool_name"] = "respond"
            result["tool_input"] = {"message": "contact not found"}
            result["missing_fields"] = []
            result["confidence"] = 0
            result["corrected_transcript"] = transcript
            return result

        extracted_to = extracted.get("to", "")
        gemini_raw_to = _clean_text(tool_input.get("to") or tool_input.get("email") or tool_input.get("recipient") or "")
        gemini_contact_to = _lookup_contact_email(gemini_raw_to)
        gemini_to = gemini_contact_to or _normalize_email_candidate(gemini_raw_to)
        to = extracted_to if _is_valid_email(extracted_to) else gemini_to
        body = _clean_text(extracted.get("body") or tool_input.get("body") or tool_input.get("message"))
        subject = _clean_text(extracted.get("subject") or tool_input.get("subject") or "Voice assistant message")

        if not _is_valid_email(to) and _looks_like_contact_alias(gemini_raw_to or extracted.get("contact_alias", "")):
            result["tool_name"] = "respond"
            result["tool_input"] = {"message": "contact not found"}
            result["missing_fields"] = []
            result["confidence"] = 0
            result["corrected_transcript"] = transcript
            return result

        if _is_valid_email(to) and body:
            result["tool_name"] = "send_email"
            result["tool_input"] = {
                "to": to,
                "subject": subject or "Voice assistant message",
                "body": body,
            }
            result["missing_fields"] = []
            result["confidence"] = max(float(result.get("confidence") or 0), 0.9)
            return result

        missing = []
        if not _is_valid_email(to):
            missing.append("email address")
        if not body:
            missing.append("message body")
        result["tool_name"] = "respond"
        result["tool_input"] = {
            "message": "Please repeat the " + " and ".join(missing) + " clearly.",
        }
        result["missing_fields"] = missing
        result["confidence"] = 0
        return result

    if tool_name == "set_reminder" or _looks_like_reminder_request(transcript):
        date_time = _clean_text(tool_input.get("date_time") or tool_input.get("datetime") or "")
        if not date_time:
            date_time = _parse_spoken_datetime(transcript)
        title = _clean_text(tool_input.get("title") or tool_input.get("summary") or "")
        if not title or title.lower() in {"reminder", "meeting", "event"}:
            title = _extract_reminder_title(transcript)

        missing = []
        if not title:
            missing.append("reminder title")
        if not date_time:
            missing.append("date or time")

        if not missing:
            result["tool_name"] = "set_reminder"
            result["tool_input"] = {
                "title": title,
                "date_time": date_time,
            }
            result["missing_fields"] = []
            result["confidence"] = max(float(result.get("confidence") or 0), 0.9)
            return result

        result["tool_name"] = "respond"
        result["tool_input"] = {
            "message": "Please repeat the " + " and ".join(missing) + " clearly.",
        }
        result["missing_fields"] = missing
        result["confidence"] = 0
        return result

    result["tool_name"] = tool_name if tool_name in {"send_email", "set_reminder", "respond"} else "respond"
    result["tool_input"] = tool_input
    result.setdefault("missing_fields", [])
    result.setdefault("confidence", 0)
    result.setdefault("corrected_transcript", transcript)
    return result


def _call_gemini(transcript: str) -> dict:
    if not API_KEY:
        raise RuntimeError("GEMINI_API_KEY is not configured.")

    body = {
        "contents": [
            {
                "role": "user",
                "parts": [{"text": _build_prompt(transcript)}],
            }
        ],
        "generationConfig": {
            "temperature": 0,
            "maxOutputTokens": 512,
            "thinkingConfig": {"thinkingBudget": 0},
            "responseMimeType": "application/json",
            "responseSchema": INTENT_SCHEMA,
        },
    }

    response = requests.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent",
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": API_KEY,
        },
        json=body,
        timeout=TIMEOUT_SECONDS,
    )
    if not response.ok:
        raise RuntimeError(f"Gemini {response.status_code}: {response.text[:800]}")

    payload = response.json()
    parts = (
        payload.get("candidates", [{}])[0]
        .get("content", {})
        .get("parts", [])
    )
    text = "".join(str(part.get("text") or "") for part in parts if isinstance(part, dict)).strip()
    if not text:
        raise RuntimeError("Gemini returned an empty response.")

    return _postprocess_intent(json.loads(text), transcript)


def _call_gemini_general_answer(transcript: str) -> dict:
    if not API_KEY:
        raise RuntimeError("GEMINI_API_KEY is not configured.")

    body = {
        "contents": [
            {
                "role": "user",
                "parts": [{"text": _build_general_answer_prompt(transcript)}],
            }
        ],
        "generationConfig": {
            "temperature": 0.4,
            "maxOutputTokens": 512,
            "thinkingConfig": {"thinkingBudget": 0},
        },
    }

    response = requests.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent",
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": API_KEY,
        },
        json=body,
        timeout=TIMEOUT_SECONDS,
    )
    if not response.ok:
        raise RuntimeError(f"Gemini {response.status_code}: {response.text[:800]}")

    payload = response.json()
    parts = (
        payload.get("candidates", [{}])[0]
        .get("content", {})
        .get("parts", [])
    )
    text = _clean_text("".join(str(part.get("text") or "") for part in parts if isinstance(part, dict)))
    if not text:
        raise RuntimeError("Gemini returned an empty response.")

    return {
        "tool_name": "respond",
        "tool_input": {"message": text},
        "corrected_transcript": transcript,
        "confidence": 0.9,
        "missing_fields": [],
    }


def _call_pollinations_general_answer(transcript: str) -> dict:
    if not POLLINATIONS_API_KEY:
        raise RuntimeError("POLLINATIONS_API_KEY is not configured.")

    body = {
        "model": POLLINATIONS_MODEL,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a helpful voice assistant. Answer general questions directly. "
                    "Keep replies concise and suitable for text-to-speech, usually under 60 words. "
                    f"Current local date/time is {_current_time()} in {LOCAL_ZONE}."
                ),
            },
            {"role": "user", "content": transcript},
        ],
        "temperature": 0.4,
        "max_tokens": 220,
    }

    response = requests.post(
        "https://gen.pollinations.ai/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {POLLINATIONS_API_KEY}",
            "Content-Type": "application/json",
        },
        json=body,
        timeout=TIMEOUT_SECONDS,
    )
    if not response.ok:
        raise RuntimeError(f"Pollinations {response.status_code}: {response.text[:800]}")

    payload = response.json()
    text = _clean_text(
        payload.get("choices", [{}])[0]
        .get("message", {})
        .get("content", "")
    )
    if not text:
        raise RuntimeError("Pollinations returned an empty response.")

    return {
        "tool_name": "respond",
        "tool_input": {"message": text},
        "corrected_transcript": transcript,
        "confidence": 0.9,
        "missing_fields": [],
        "llm_provider": "pollinations",
        "llm_model": POLLINATIONS_MODEL,
    }


def _fallback_intent(transcript: str, error: Exception) -> dict:
    error_text = str(error)
    if _looks_like_email_request(transcript) or _looks_like_reminder_request(transcript):
        result = _postprocess_intent(
            {
                "tool_name": "respond",
                "tool_input": {
                    "message": "I had trouble understanding that. Please repeat the command clearly.",
                },
                "corrected_transcript": transcript,
                "confidence": 0,
                "missing_fields": ["intent"],
            },
            transcript,
        )
        result["intent_error"] = error_text[:300]
        return result

    wiki = _wiki_summary_intent(transcript)
    if wiki is not None:
        wiki["intent_error"] = error_text[:300]
        return wiki

    if "PAYMENT_REQUIRED" in error_text or "Insufficient balance" in error_text:
        return {
            "tool_name": "respond",
            "tool_input": {
                "message": "Pollinations LLM is connected, but this model needs more balance. Add balance on Pollinations or switch to a lower cost model.",
            },
            "corrected_transcript": transcript,
            "confidence": 0,
            "missing_fields": ["pollinations_balance"],
            "intent_error": error_text[:300],
        }

    if "429" in error_text or "quota" in error_text.lower():
        return {
            "tool_name": "respond",
            "tool_input": {
                "message": "Gemini API quota is exceeded right now. I can still do email, reminders, weather with a city, date, time, and spelling, but general LLM questions need Gemini quota or billing fixed.",
            },
            "corrected_transcript": transcript,
            "confidence": 0,
            "missing_fields": ["gemini_quota"],
            "intent_error": error_text[:300],
        }

    result = _postprocess_intent(
        {
            "tool_name": "respond",
            "tool_input": {
                "message": "I had trouble understanding that. Please repeat the command clearly.",
            },
            "corrected_transcript": transcript,
            "confidence": 0,
            "missing_fields": ["intent"],
        },
        transcript,
    )
    result["intent_error"] = error_text[:300]
    return result


@app.get("/health")
def health():
    return jsonify(
        {
            "status": "ok",
            "provider": "gemini",
            "model": MODEL,
            "pollinations_model": POLLINATIONS_MODEL,
            "has_pollinations_api_key": bool(POLLINATIONS_API_KEY),
            "has_api_key": bool(API_KEY),
            "timezone": LOCAL_ZONE,
        }
    )


@app.post("/intent")
def intent():
    global PENDING_FOLLOWUP
    payload = request.get_json(silent=True)
    transcript = _extract_transcript(payload)
    _log_event(
        "request",
        {
            "transcript": transcript,
            "has_pending_action": bool(PENDING_ACTION),
            "has_pending_followup": bool(PENDING_FOLLOWUP),
        },
    )
    if not transcript:
        result = {
            "tool_name": "respond",
            "tool_input": {"message": "I could not hear the command clearly."},
            "corrected_transcript": "",
            "confidence": 0,
            "missing_fields": ["transcript"],
        }
    else:
        try:
            pending_result = _handle_pending_confirmation(transcript)
            if pending_result is not None:
                result = pending_result
            else:
                followup_result = _handle_pending_followup(transcript)
                if followup_result is not None:
                    result = followup_result
                else:
                    translation_followup = _extract_translation_followup_request(transcript)
                    if translation_followup is not None:
                        PENDING_FOLLOWUP = translation_followup
                        result = _respond(
                            "What sentence should I translate?",
                            listen_again=True,
                            missing_fields=["translation sentence"],
                        )
                        result["corrected_transcript"] = transcript
                    else:
                        direct = _basic_question_intent(transcript) or _weather_intent(transcript)
                        if direct is not None:
                            result = direct
                        elif _looks_like_email_request(transcript):
                            local_email_result = _postprocess_intent({}, transcript)
                            local_message = _clean_text(
                                local_email_result.get("tool_input", {}).get("message")
                                if isinstance(local_email_result.get("tool_input"), dict)
                                else ""
                            ).lower()
                            if local_email_result.get("tool_name") == "send_email" or local_message == "contact not found":
                                result = local_email_result
                            else:
                                result = _call_gemini(transcript)
                        elif _looks_like_reminder_request(transcript):
                            result = _call_gemini(transcript)
                        else:
                            if POLLINATIONS_API_KEY:
                                result = _call_pollinations_general_answer(transcript)
                            else:
                                result = _call_gemini_general_answer(transcript)
                    result = _require_confirmation_if_needed(result, transcript)
                    result = _response_requests_user_input(result, transcript)
        except Exception as exc:
            result = _fallback_intent(transcript, exc)
            result = _require_confirmation_if_needed(result, transcript)
            result = _response_requests_user_input(result, transcript)

    _log_event(
        "result",
        {
            "transcript": transcript,
            "tool_name": result.get("tool_name") if isinstance(result, dict) else None,
            "listen_again": result.get("listen_again") if isinstance(result, dict) else None,
            "has_pending_action": bool(PENDING_ACTION),
            "has_pending_followup": bool(PENDING_FOLLOWUP),
        },
    )
    content = json.dumps(result, separators=(",", ":"))
    return jsonify(
        {
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": content,
                    },
                    "finish_reason": "stop",
                }
            ],
            "model": MODEL,
            "provider": "gemini",
        }
    )


if __name__ == "__main__":
    app.run(host=HOST, port=PORT)

