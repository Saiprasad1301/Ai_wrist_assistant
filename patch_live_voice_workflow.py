from __future__ import annotations

import datetime as dt
import json
import sqlite3
import textwrap
from pathlib import Path


DB_PATH = Path(r"C:\Users\Dhruva\.n8n\database.sqlite")
WORKFLOW_ID = "cya4w5XS7Sk4XVnu"
WORKSPACE = Path(r"C:\n8n automation")
BACKUP_PATH = WORKSPACE / "voice-assistant-before-runtime-patch.json"
EXPORT_PATH = WORKSPACE / "voice-assistant-current-export.json"


PARSE_TOOL_CHOICE_CODE = textwrap.dedent(
    """
    const response = $json;
    const message = response.choices?.[0]?.message ?? {};
    const rawContent = String(message.content ?? '').trim();
    const REMINDER_ZONE = 'Asia/Kolkata';

    let parsed = {};
    try {
      parsed = rawContent ? JSON.parse(rawContent) : {};
    } catch (error) {
      const match = rawContent.match(/\\{[\\s\\S]*\\}/);
      if (match) {
        try {
          parsed = JSON.parse(match[0]);
        } catch (innerError) {
          parsed = {};
        }
      }
    }

    const allowedTools = new Set(['send_email', 'set_reminder', 'respond']);
    let toolName = String(parsed.tool_name || parsed.tool || 'respond');
    if (!allowedTools.has(toolName)) {
      toolName = 'respond';
    }

    let toolInput = parsed.tool_input ?? parsed.input ?? {};
    if (typeof toolInput !== 'object' || toolInput === null || Array.isArray(toolInput)) {
      toolInput = {};
    }

    function cleanText(value) {
      return String(value ?? '').replace(/\\s+/g, ' ').trim();
    }

    function normalizeReminderTranscript(value) {
      return cleanText(value)
        .replace(/\\bset remainder\\b/gi, 'set reminder')
        .replace(/\\bcreate (?:a )?remainder\\b/gi, 'create a reminder')
        .replace(/\\bremainder\\b(?=\\s+(for|at|on|today|tomorrow|next|\\d))/gi, 'reminder');
    }

    const transcript = normalizeReminderTranscript($('Whisper - Speech to Text').item.json.text);

    function extractEmailCandidateFromTranscript(value) {
      const rules = [
        /\\b(?:send|write|compose)\\s+(?:an?\\s+)?email\\s+to\\s+(.+?)(?=\\b(?:subject|body|message|say|saying|write|in the email)\\b|$)/i,
        /\\bemail\\s+to\\s+(.+?)(?=\\b(?:subject|body|message|say|saying|write|in the email)\\b|$)/i,
      ];

      for (const rule of rules) {
        const match = cleanText(value).match(rule);
        if (match?.[1]) {
          return cleanText(match[1]);
        }
      }

      return '';
    }

    function extractEmailBodyFromTranscript(value) {
      const rules = [
        /\\bin the email\\s+(?:write|say)?\\s*(.+)$/i,
        /\\b(?:body|message|write|say|saying)\\s+(.+)$/i,
        /\\b(?:send|write|compose)\\s+(?:an?\\s+)?email\\s+to\\s+.+?(?:@|\\bat\\b).+?\\s+(.+)$/i,
        /\\bemail\\s+to\\s+.+?(?:@|\\bat\\b).+?\\s+(.+)$/i,
      ];

      for (const rule of rules) {
        const match = cleanText(value).match(rule);
        if (match?.[1]) {
          return cleanText(match[1]).replace(/^[,:-]+\\s*/, '');
        }
      }

      return '';
    }

    function normalizeSpokenEmail(value) {
      let email = cleanText(value).toLowerCase();
      if (!email) return '';

      email = email
        .replace(/[<>()\",']/g, ' ')
        .replace(/\\bat\\s+the\\s+rate\\b/g, '@')
        .replace(/\\bat\\s+rate\\b/g, '@')
        .replace(/\\battherate\\b/g, '@')
        .replace(/\\bat\\b/g, '@')
        .replace(/\\bdot\\b/g, '.')
        .replace(/\\bpoint\\b/g, '.')
        .replace(/\\bunderscore\\b/g, '_')
        .replace(/\\bhyphen\\b/g, '-')
        .replace(/\\bdash\\b/g, '-')
        .replace(/\\s+/g, '')
        .replace(/-+/g, '');

      email = email
        .replace(/@rate\\./, '@')
        .replace(/@r?dby\\.piu\\./, '@dypiu.')
        .replace(/@r?dbypiu\\./, '@dypiu.')
        .replace(/@r?dby?piu\\./, '@dypiu.')
        .replace(/@dypiu\\.acid\\.in$/, '@dypiu.ac.in')
        .replace(/@dypiu\\.a\\.c\\.in$/, '@dypiu.ac.in')
        .replace(/\\.acid\\.in$/, '.ac.in')
        .replace(/dypiu\\.?ac\\.?in$/, 'dypiu.ac.in');

      if (!email.includes('@') && email.endsWith('dypiu.ac.in')) {
        let localPart = email.slice(0, -'dypiu.ac.in'.length);
        if (localPart.endsWith('8')) {
          localPart = localPart.slice(0, -1);
        }
        email = `${localPart}@dypiu.ac.in`;
      }

      email = email
        .replace(/[^a-z0-9@._+-]/g, '')
        .replace(/\\.{2,}/g, '.')
        .replace(/@{2,}/g, '@')
        .replace(/^[._-]+/, '')
        .replace(/[._-]+$/, '');

      return email;
    }

    function isValidEmail(value) {
      return /^[^\\s@]+@[^\\s@]+\\.[^\\s@]+$/.test(value);
    }

    function isPlaceholderEmail(value) {
      const email = String(value ?? '').toLowerCase();
      if (!email) return true;
      if (/@example\\.(com|org|net)$/.test(email)) return true;

      const [localPart = '', domain = ''] = email.split('@');
      if (['user', 'recipient', 'test', 'email', 'someone'].includes(localPart)) return true;
      if (['example.com', 'example.org', 'example.net'].includes(domain)) return true;

      return false;
    }

    function isGenericReminderTitle(value) {
      return /^reminder$/i.test(cleanText(value));
    }

    function extractReminderTitleFromTranscript(value) {
      const rules = [
        /\\bremind me to\\s+(.+?)(?:\\s+(?:at|on|today|tomorrow|next)\\b|$)/i,
        /\\b(?:set|create)\\s+(?:a\\s+)?reminder\\s+to\\s+(.+?)(?:\\s+(?:at|on|today|tomorrow|next)\\b|$)/i,
      ];

      for (const rule of rules) {
        const match = value.match(rule);
        if (match?.[1]) {
          return cleanText(match[1]).replace(/[.,!?]+$/g, '');
        }
      }

      return '';
    }

    function parseSimpleReminderDate(value) {
      const base = DateTime.now().setZone(REMINDER_ZONE);
      let target = base;

      if (/\\btomorrow\\b/i.test(value)) {
        target = target.plus({ days: 1 });
      }

      const timeMatch = value.match(/\\b(\\d{1,2})(?::(\\d{2}))?\\s*(a\\.?m\\.?|p\\.?m\\.?)\\b/i);
      if (!timeMatch) {
        return null;
      }

      let hour = Number(timeMatch[1]);
      const minute = Number(timeMatch[2] ?? 0);
      const meridiem = timeMatch[3].toLowerCase();

      if (meridiem.startsWith('p') && hour < 12) {
        hour += 12;
      }
      if (meridiem.startsWith('a') && hour === 12) {
        hour = 0;
      }

      target = target.set({ hour, minute, second: 0, millisecond: 0 });
      if (!/\\b(today|tomorrow)\\b/i.test(value) && target <= base) {
        target = target.plus({ days: 1 });
      }

      return target;
    }

    function normalizeReminderDate(dateTime, transcriptValue) {
      const cleanedDate = cleanText(dateTime);
      const transcriptDate = parseSimpleReminderDate(transcriptValue);
      const mentionsExplicitZone = /\\b(?:utc|gmt|ist|pst|est|cst)\\b/i.test(transcriptValue);

      if (cleanedDate) {
        const parsedDate = DateTime.fromISO(cleanedDate, { setZone: true });
        if (parsedDate.isValid) {
          if (transcriptDate && !mentionsExplicitZone && (parsedDate.offset === 0 || parsedDate.zoneName === 'UTC')) {
            return transcriptDate;
          }
          return parsedDate.setZone(REMINDER_ZONE);
        }
      }

      return transcriptDate;
    }

    if (toolName === 'send_email') {
      const transcriptRecipient = extractEmailCandidateFromTranscript(transcript);
      const to = normalizeSpokenEmail(
        toolInput.to ?? toolInput.email ?? toolInput.recipient ?? toolInput.sendTo ?? transcriptRecipient
      );
      const fallbackBody = extractEmailBodyFromTranscript(transcript);
      let subject = cleanText(toolInput.subject);
      let body = cleanText(toolInput.body ?? toolInput.message ?? fallbackBody);

      if (!body && subject) {
        body = subject;
        subject = 'Voice assistant message';
      } else if (!subject && body) {
        subject = 'Voice assistant message';
      }

      if (!to || !isValidEmail(to) || isPlaceholderEmail(to) || !body) {
        toolName = 'respond';
        const missing = [];
        if (!to || !isValidEmail(to) || isPlaceholderEmail(to)) missing.push('a real email address');
        if (!body) missing.push('a message body');
        toolInput = {
          message: 'I heard an email request, but I still need ' + missing.join(' and ') + ' before I can send it.',
          original_tool_input: toolInput,
        };
      } else {
        toolInput = {
          ...toolInput,
          to,
          subject,
          body,
        };
      }
    }

    if (toolName === 'set_reminder') {
      const title = cleanText(toolInput.title ?? toolInput.summary ?? toolInput.message);
      const normalizedTitle = isGenericReminderTitle(title)
        ? extractReminderTitleFromTranscript(transcript) || 'Reminder'
        : title;
      const parsedDate = normalizeReminderDate(
        toolInput.date_time ?? toolInput.datetime ?? toolInput.start,
        transcript
      );

      if (!parsedDate?.isValid) {
        toolName = 'respond';
        toolInput = {
          message: 'I heard a reminder request, but I need a clear date or time before I can create it.',
          original_tool_input: toolInput,
        };
      } else {
        const reminderDate = parsedDate.setZone(REMINDER_ZONE);
        toolInput = {
          ...toolInput,
          title: normalizedTitle || 'Reminder',
          date_time: reminderDate.toISO(),
          response_time: reminderDate.toFormat('h:mm a'),
          response_date: reminderDate.toFormat('d LLL'),
          response_datetime: reminderDate.toFormat("h:mm a 'on' d LLL"),
        };
      }
    }

    if (toolName === 'respond' && !toolInput.message) {
      toolInput.message = parsed.message || rawContent || 'I could not understand the command.';
    }

    return {
      tool_name: toolName,
      tool_input: toolInput,
      transcript,
    };
    """
).strip()


BUILD_RESPONSE_CODE = textwrap.dedent(
    """
    const parsed = $('Parse Tool Choice').item.json;
    const toolName = $json.tool_name ?? parsed.tool_name;
    const toolInput = $json.tool_input ?? parsed.tool_input ?? {};
    const REMINDER_ZONE = 'Asia/Kolkata';

    function cleanText(value) {
      return String(value ?? '').replace(/\\s+/g, ' ').trim();
    }

    function isGenericReminderTitle(value) {
      return /^reminder$/i.test(cleanText(value));
    }

    function formatReminderDateTime(value) {
      const parsedDate = value ? DateTime.fromISO(String(value), { setZone: true }) : null;
      if (!parsedDate?.isValid) {
        return '';
      }

      return parsedDate.setZone(REMINDER_ZONE).toFormat("h:mm a 'on' d LLL");
    }

    let message = '';

    if (toolName === 'send_email') {
      message = `Email sent to ${toolInput.to}`;
    } else if (toolName === 'set_reminder') {
      const title = cleanText(toolInput.title);
      const reminderTime = cleanText(toolInput.response_datetime) || formatReminderDateTime(toolInput.date_time);

      if (reminderTime && isGenericReminderTitle(title)) {
        message = `Reminder set for ${reminderTime}`;
      } else if (reminderTime && title) {
        message = `Reminder for ${title} set for ${reminderTime}`;
      } else if (title) {
        message = `Reminder created: ${title}`;
      } else {
        message = 'Reminder created';
      }
    } else {
      message = toolInput.message || 'Task completed';
    }

    return {
      response: message,
      tool_name: toolName,
      tool_input: toolInput,
      transcript: parsed.transcript,
    };
    """
).strip()


BUILD_GROQ_REQUEST_CODE = textwrap.dedent(
    """
    const REMINDER_ZONE = 'Asia/Kolkata';

    function normalizeTranscript(value) {
      return String(value ?? '')
        .trim()
        .replace(/\\bset remainder\\b/gi, 'set reminder')
        .replace(/\\bcreate (?:a )?remainder\\b/gi, 'create a reminder')
        .replace(/\\bremainder\\b(?=\\s+(for|at|on|today|tomorrow|next|\\d))/gi, 'reminder');
    }

    const transcript = normalizeTranscript($json.text);

    const systemPrompt = [
      'You are an intent router for a local voice assistant.',
      'Current local date/time in Asia/Kolkata is ' + DateTime.now().setZone(REMINDER_ZONE).toISO() + '.',
      'Return ONLY valid minified JSON. Do not use markdown. Do not request or emit external tool calls.',
      'Allowed tool_name values are exactly send_email, set_reminder, respond.',
      'Use send_email whenever the user clearly asks to send an email. Extract the recipient into tool_input.to whenever possible from spoken text. Unless the user explicitly says subject, treat the spoken content after the recipient as the email body. If the body is present but the subject is missing, still return send_email and leave tool_input.subject empty. Only return respond when there is no recipient or no message content to send. Never invent placeholder emails like user@example.com.',
      'Use set_reminder only when the user asks for a reminder or calendar event.',
      'Interpret natural-language dates and times like "2 pm", "today", and "tomorrow" in Asia/Kolkata unless the speaker explicitly says another timezone.',
      'For set_reminder, return tool_input.date_time as ISO 8601 with an explicit +05:30 offset whenever the timezone is not specified.',
      'For set_reminder, title should be the thing being remembered. If the user gives only a date or time and no reminder content, set title to "Reminder".',
      'For weather, search, current news, latest facts, or anything requiring live internet, use respond and explain that live data is not available in this local assistant yet.',
      'Never invent tools such as brave_search.',
      'Return this schema: {"tool_name":"respond","tool_input":{"message":"..."}}',
    ].join(' ');

    return {
      ...$json,
      text: transcript,
      groqBody: JSON.stringify({
        model: 'llama-3.1-8b-instant',
        messages: [
          { role: 'system', content: systemPrompt },
          { role: 'user', content: transcript || 'No speech was detected.' },
        ],
        temperature: 0,
        response_format: { type: 'json_object' },
      }),
    };
    """
).strip()


def _load_row(cursor: sqlite3.Cursor) -> sqlite3.Row:
    cursor.execute(
        """
        SELECT id, name, versionId, nodes, connections
        FROM workflow_entity
        WHERE id = ?
        """,
        (WORKFLOW_ID,),
    )
    row = cursor.fetchone()
    if row is None:
        raise RuntimeError(f"Workflow {WORKFLOW_ID} not found in {DB_PATH}")
    return row


def _patch_nodes(nodes: list[dict]) -> list[dict]:
    replaced = set()

    for node in nodes:
        if node.get("name") == "Parse Tool Choice":
            node.setdefault("parameters", {})["jsCode"] = PARSE_TOOL_CHOICE_CODE
            replaced.add("Parse Tool Choice")
        elif node.get("name") == "Build Response":
            node.setdefault("parameters", {})["jsCode"] = BUILD_RESPONSE_CODE
            replaced.add("Build Response")
        elif node.get("name") == "Build Groq Request":
            node.setdefault("parameters", {})["jsCode"] = BUILD_GROQ_REQUEST_CODE
            replaced.add("Build Groq Request")

    missing = {"Parse Tool Choice", "Build Response", "Build Groq Request"} - replaced
    if missing:
        raise RuntimeError(f"Missing expected nodes: {', '.join(sorted(missing))}")

    return nodes


def main() -> None:
    WORKSPACE.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    cursor = connection.cursor()

    row = _load_row(cursor)
    original_nodes = json.loads(row["nodes"])
    original_connections = json.loads(row["connections"])

    backup_payload = [
        {
            "id": row["id"],
            "name": row["name"],
            "nodes": original_nodes,
            "connections": original_connections,
        }
    ]
    BACKUP_PATH.write_text(json.dumps(backup_payload, indent=2), encoding="utf-8")

    patched_nodes = _patch_nodes(json.loads(row["nodes"]))
    nodes_json = json.dumps(patched_nodes, separators=(",", ":"))
    timestamp = dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

    cursor.execute(
        """
        UPDATE workflow_entity
        SET nodes = ?, updatedAt = ?
        WHERE id = ?
        """,
        (nodes_json, timestamp, WORKFLOW_ID),
    )
    cursor.execute(
        """
        UPDATE workflow_history
        SET nodes = ?, updatedAt = ?
        WHERE versionId = ?
        """,
        (nodes_json, timestamp, row["versionId"]),
    )
    connection.commit()
    connection.close()

    export_payload = [
        {
            "id": row["id"],
            "name": row["name"],
            "nodes": patched_nodes,
            "connections": original_connections,
        }
    ]
    EXPORT_PATH.write_text(json.dumps(export_payload, indent=2), encoding="utf-8")

    print(f"Backed up workflow to {BACKUP_PATH}")
    print(f"Patched workflow {WORKFLOW_ID} in {DB_PATH}")


if __name__ == "__main__":
    main()
