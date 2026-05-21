from __future__ import annotations

import datetime as dt
import json
import sqlite3
import textwrap
from pathlib import Path


DB_PATH = Path(r"C:\Users\Dhruva\.n8n\database.sqlite")
WORKFLOW_ID = "cya4w5XS7Sk4XVnu"
WORKSPACE = Path(r"C:\n8n automation")
BACKUP_PATH = WORKSPACE / "voice-assistant-before-intent-patch.json"
EXPORT_PATH = WORKSPACE / "voice-assistant-intent-export.json"

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

    function joinSingleCharacterRuns(value) {
      const tokens = cleanText(value).split(' ').filter(Boolean);
      const joined = [];

      for (let index = 0; index < tokens.length; ) {
        if (/^[a-z0-9]$/i.test(tokens[index])) {
          const run = [];
          while (index < tokens.length && /^[a-z0-9]$/i.test(tokens[index])) {
            run.push(tokens[index].toLowerCase());
            index += 1;
          }
          if (run.length >= 2) {
            joined.push(run.join(''));
          } else {
            joined.push(...run);
          }
          continue;
        }

        joined.push(tokens[index]);
        index += 1;
      }

      return joined.join(' ');
    }

    function normalizeReminderTranscript(value) {
      return cleanText(value)
        .replace(/\\bset remainder\\b/gi, 'set reminder')
        .replace(/\\bcreate (?:a )?remainder\\b/gi, 'create a reminder')
        .replace(/\\bremind her\\b(?=\\s+(for|at|on|today|tomorrow|\\d))/gi, 'reminder')
        .replace(/\\bremainder\\b(?=\\s+(for|at|on|today|tomorrow|next|\\d))/gi, 'reminder');
    }

    const transcript = normalizeReminderTranscript(joinSingleCharacterRuns($('Whisper - Speech to Text').item.json.text));

    function transcriptLooksLikeEmailRequest(value) {
      return /\\b(?:send|write|compose)\\b(?:\\s+\\w+){0,4}\\s+email\\b/i.test(value) || /\\bemail\\s+to\\b/i.test(value);
    }

    function transcriptLooksLikeReminderRequest(value) {
      return /\\b(remind me|set (?:a )?reminder|create (?:a )?reminder|create an event|schedule)\\b/i.test(value);
    }

    function extractEmailCommandTail(value) {
      const cleaned = cleanText(value);
      const match =
        cleaned.match(/\\b(?:send|write|compose)\\s+(?:an?\\s+)?email\\s+to\\s+(.+)$/i) ||
        cleaned.match(/\\bemail\\s+to\\s+(.+)$/i);
      return cleanText(match?.[1] ?? '');
    }

    function extractEmailCandidateFromTranscript(value) {
      const tail = extractEmailCommandTail(value);
      if (!tail) {
        return '';
      }

      const directEmail = tail.match(/^([^\\s,;:]+@[^\\s,;:]+\\.[^\\s,;:]+)/i);
      if (directEmail?.[1]) {
        return cleanText(directEmail[1]);
      }

      const spokenDomain = tail.match(
        /^(.+?\\b(?:dypiu\\s+dot\\s+ac\\s+dot\\s+in|dypiu\\s+ac\\s+in|dot\\s+co\\s+dot\\s+in|dot\\s+ac\\s+dot\\s+in|dot\\s+com|dot\\s+org|dot\\s+net|dot\\s+edu|dot\\s+in)\\b)/i
      );
      if (spokenDomain?.[1]) {
        return cleanText(spokenDomain[1]);
      }

      const stop = tail.search(/\\b(?:subject|body|message|write|say|saying|in the email)\\b/i);
      return cleanText(stop >= 0 ? tail.slice(0, stop) : tail);
    }

    function extractEmailBodyFromTranscript(value, recipientCandidate = '') {
      const cleaned = cleanText(value);
      const rules = [
        /\\bin the email\\s+(?:write|say)?\\s*(.+)$/i,
        /\\b(?:body|message|write|say|saying)\\s+(.+)$/i,
      ];

      for (const rule of rules) {
        const match = cleaned.match(rule);
        if (match?.[1]) {
          return cleanText(match[1]).replace(/^[,:-]+\\s*/, '');
        }
      }

      const tail = extractEmailCommandTail(cleaned);
      if (!tail) {
        return '';
      }

      let remainder = tail;
      const cleanedRecipient = cleanText(recipientCandidate);
      if (cleanedRecipient) {
        const lowerTail = tail.toLowerCase();
        const lowerRecipient = cleanedRecipient.toLowerCase();
        const recipientIndex = lowerTail.indexOf(lowerRecipient);
        if (recipientIndex >= 0) {
          remainder = tail.slice(recipientIndex + cleanedRecipient.length);
        }
      }

      remainder = remainder.replace(/^(?:subject|body|message|write|say|saying|in the email)\\b[:\\s-]*/i, '');
      return cleanText(remainder);
    }

    function normalizeSpokenEmail(value) {
      let email = joinSingleCharacterRuns(cleanText(value)).toLowerCase();
      if (!email) return '';

      email = email
        .replace(/[<>()\\",']/g, ' ')
        .replace(/\\bat\\s+the\\s+rate\\b/g, '@')
        .replace(/\\bat\\s+rate\\b/g, '@')
        .replace(/\\battherate\\b/g, '@')
        .replace(/\\bat\\b/g, '@')
        .replace(/\\bdot\\b/g, '.')
        .replace(/\\bpoint\\b/g, '.')
        .replace(/\\bunderscore\\b/g, '_')
        .replace(/\\bhyphen\\b/g, '-')
        .replace(/\\bdash\\b/g, '-')
        .replace(/\\bplus\\b/g, '+')
        .replace(/\\s+/g, '')
        .replace(/-+/g, '');

      email = email
        .replace(/@rate\\./g, '@')
        .replace(/@r?dby\\.piu\\./g, '@dypiu.')
        .replace(/@r?dbypiu\\./g, '@dypiu.')
        .replace(/@r?dby?piu\\./g, '@dypiu.')
        .replace(/@dypiu\\.acid\\.in$/g, '@dypiu.ac.in')
        .replace(/@dypiu\\.a\\.c\\.in$/g, '@dypiu.ac.in')
        .replace(/\\.acid\\.in$/g, '.ac.in')
        .replace(/dypiu\\.?ac\\.?in$/g, 'dypiu.ac.in');

      if (!email.includes('@') && email.endsWith('dypiu.ac.in')) {
        const localPart = email
          .slice(0, -'dypiu.ac.in'.length)
          .replace(/[^a-z0-9._+-]/g, '')
          .replace(/[._-]+$/g, '');
        if (localPart) {
          email = `${localPart}@dypiu.ac.in`;
        }
      }

      email = email
        .replace(/[^a-z0-9@._+-]/g, '')
        .replace(/\\.{2,}/g, '.')
        .replace(/@{2,}/g, '@')
        .replace(/^[._-]+/g, '')
        .replace(/[._-]+$/g, '');

      return email;
    }

    function isValidEmail(value) {
      return /^[^\\s@]+@[^\\s@]+\\.[^\\s@]+$/.test(value);
    }

    function isPlaceholderEmail(value) {
      const email = String(value ?? '').toLowerCase();
      if (!email) return true;
      if (/@example\\.(com|org|net)$/i.test(email)) return true;

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

    const transcriptRequestsEmail = transcriptLooksLikeEmailRequest(transcript);
    const transcriptRequestsReminder = !transcriptRequestsEmail && transcriptLooksLikeReminderRequest(transcript);

    if (transcriptRequestsEmail) {
      toolName = 'send_email';
    } else if (transcriptRequestsReminder) {
      toolName = 'set_reminder';
    }

    if (toolName === 'send_email') {
      const transcriptRecipient = extractEmailCandidateFromTranscript(transcript);
      const to = normalizeSpokenEmail(
        transcriptRecipient || toolInput.to || toolInput.email || toolInput.recipient || toolInput.sendTo
      );
      const fallbackBody = extractEmailBodyFromTranscript(transcript, transcriptRecipient);
      let subject = cleanText(toolInput.subject);
      let body = cleanText(
        transcriptRequestsEmail
          ? (fallbackBody || toolInput.body || toolInput.message)
          : (toolInput.body ?? toolInput.message ?? fallbackBody)
      );

      if (!body && subject) {
        body = subject;
        subject = 'Voice assistant message';
      } else if (!subject && body) {
        subject = 'Voice assistant message';
      } else if (transcriptRequestsEmail && fallbackBody && cleanText(subject) === cleanText(body)) {
        subject = 'Voice assistant message';
      }

      if (!to || !isValidEmail(to) || isPlaceholderEmail(to) || !body) {
        toolName = 'respond';
        toolInput = {
          message: 'Please repeat the email address and message clearly.',
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
      message = 'Email sent.';
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


def load_workflow(cursor: sqlite3.Cursor) -> sqlite3.Row:
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
        raise RuntimeError(f"Workflow {WORKFLOW_ID} not found")
    return row


def patch_nodes(nodes: list[dict]) -> list[dict]:
    seen = set()
    for node in nodes:
        if node.get("name") == "Parse Tool Choice":
            node.setdefault("parameters", {})["jsCode"] = PARSE_TOOL_CHOICE_CODE
            seen.add("Parse Tool Choice")
        elif node.get("name") == "Build Response":
            node.setdefault("parameters", {})["jsCode"] = BUILD_RESPONSE_CODE
            seen.add("Build Response")

    missing = {"Parse Tool Choice", "Build Response"} - seen
    if missing:
        raise RuntimeError(f"Missing expected nodes: {', '.join(sorted(missing))}")
    return nodes


def main() -> None:
    WORKSPACE.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    cursor = connection.cursor()

    row = load_workflow(cursor)
    original_nodes = json.loads(row["nodes"])
    original_connections = json.loads(row["connections"])

    BACKUP_PATH.write_text(
        json.dumps(
            [
                {
                    "id": row["id"],
                    "name": row["name"],
                    "nodes": original_nodes,
                    "connections": original_connections,
                }
            ],
            indent=2,
        ),
        encoding="utf-8",
    )

    patched_nodes = patch_nodes(json.loads(row["nodes"]))
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

    EXPORT_PATH.write_text(
        json.dumps(
            [
                {
                    "id": row["id"],
                    "name": row["name"],
                    "nodes": patched_nodes,
                    "connections": original_connections,
                }
            ],
            indent=2,
        ),
        encoding="utf-8",
    )

    print(f"Backed up workflow to {BACKUP_PATH}")
    print(f"Patched workflow {WORKFLOW_ID} with deterministic email intent parsing")
    print(f"Exported patched workflow to {EXPORT_PATH}")


if __name__ == "__main__":
    main()
