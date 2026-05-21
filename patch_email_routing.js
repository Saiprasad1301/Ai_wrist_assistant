const fs = require('fs');
const path = require('path');

const root = 'C:/n8n automation';
const inputPath = path.join(root, 'voice-assistant-current-export.json');
const outputPath = path.join(root, 'voice-assistant-email-routing-fixed.json');

const exported = JSON.parse(fs.readFileSync(inputPath, 'utf8'));
const workflow = Array.isArray(exported) ? exported[0] : exported;

const parseNode = workflow.nodes.find((node) => node.name === 'Parse Tool Choice');
if (!parseNode) {
  throw new Error('Missing Parse Tool Choice node');
}

parseNode.parameters.jsCode = `const response = $json;
const message = response.choices?.[0]?.message ?? {};
const rawContent = String(message.content ?? '').trim();

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

function normalizeSpokenEmail(value) {
  let email = cleanText(value).toLowerCase();
  if (!email) return '';

  email = email
    .replace(/\\bat\\s+the\\s+rate\\b/g, '@')
    .replace(/\\bat\\s+rate\\b/g, '@')
    .replace(/\\battherate\\b/g, '@')
    .replace(/\\bat\\b/g, '@')
    .replace(/\\bdot\\b/g, '.')
    .replace(/\\bpoint\\b/g, '.')
    .replace(/\\s+/g, '');

  email = email
    .replace(/@rate\\./, '@')
    .replace(/@r?dby\\.piu\\./, '@dypiu.')
    .replace(/@r?dbypiu\\./, '@dypiu.')
    .replace(/@r?dby?piu\\./, '@dypiu.')
    .replace(/@dypiu\\.acid\\.in$/, '@dypiu.ac.in')
    .replace(/@dypiu\\.a\\.c\\.in$/, '@dypiu.ac.in')
    .replace(/\\.acid\\.in$/, '.ac.in');

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

if (toolName === 'send_email') {
  const to = normalizeSpokenEmail(
    toolInput.to ?? toolInput.email ?? toolInput.recipient ?? toolInput.sendTo ?? ''
  );
  const subject = cleanText(toolInput.subject);
  const body = cleanText(toolInput.body ?? toolInput.message);

  if (!to || !isValidEmail(to) || isPlaceholderEmail(to) || !subject || !body) {
    toolName = 'respond';
    const missing = [];
    if (!to || !isValidEmail(to) || isPlaceholderEmail(to)) missing.push('a real email address');
    if (!subject) missing.push('a subject');
    if (!body) missing.push('a message body');
    toolInput = {
      message: 'I heard an email request, but I still need ' + missing.join(', ') + ' before I can send it.',
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
  const dateTime = cleanText(toolInput.date_time ?? toolInput.datetime ?? toolInput.start);
  const parsedDate = dateTime ? DateTime.fromISO(dateTime) : null;

  if (!title || !dateTime || !parsedDate?.isValid) {
    toolName = 'respond';
    toolInput = {
      message: 'I heard a reminder request, but I need a clear title and date or time before I can create it.',
      original_tool_input: toolInput,
    };
  } else {
    toolInput = {
      ...toolInput,
      title,
      date_time: parsedDate.toISO(),
    };
  }
}

if (toolName === 'respond' && !toolInput.message) {
  toolInput.message = parsed.message || rawContent || 'I could not understand the command.';
}

return {
  tool_name: toolName,
  tool_input: toolInput,
  transcript: $('Whisper - Speech to Text').item.json.text
};`;

const groqBuilder = workflow.nodes.find((node) => node.name === 'Build Groq Request');
if (groqBuilder) {
  groqBuilder.parameters.jsCode = groqBuilder.parameters.jsCode.replace(
    'Use send_email only when the user clearly asks to send an email and provides recipient, subject, and body.',
    'Use send_email only when the user clearly asks to send an email and provides tool_input.to, tool_input.subject, and tool_input.body. If any of those are missing, return respond instead. Never invent placeholder emails like user@example.com.'
  );
  groqBuilder.parameters.jsCode = groqBuilder.parameters.jsCode.replace(
    'Use send_email only when the user clearly asks to send an email and provides tool_input.to, tool_input.subject, and tool_input.body.',
    'Use send_email only when the user clearly asks to send an email and provides tool_input.to, tool_input.subject, and tool_input.body. If any of those are missing, return respond instead. Never invent placeholder emails like user@example.com.'
  );
}

fs.writeFileSync(outputPath, JSON.stringify(Array.isArray(exported) ? [workflow] : workflow, null, 2));
console.log(`Patched workflow written to ${outputPath}`);
