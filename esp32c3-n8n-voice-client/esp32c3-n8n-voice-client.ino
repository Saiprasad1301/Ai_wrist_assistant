#include <Arduino.h>
#include <WiFi.h>
#include <WiFiClient.h>
#include <new>
#include "ESP_I2S.h"
#include "HWCDC.h"
#include "voice_config.h"

// INMP441 -> ESP32-C3 wiring
// VCC -> 3.3V, GND -> GND, L/R -> GND
// WS/LRCL -> GPIO 2, SCK/BCLK -> GPIO 3, SD/DOUT -> GPIO 4
static constexpr int I2S_WS = 2;
static constexpr int I2S_BCLK = 3;
static constexpr int I2S_DIN = 4;

static constexpr uint32_t SAMPLE_RATE = 16000;
static constexpr size_t WAKE_RECORD_SECONDS = 2;
static constexpr size_t COMMAND_RECORD_SECONDS = 20;
static constexpr uint32_t COMMAND_MIN_RECORD_MS = 1400;
static constexpr uint32_t COMMAND_SILENCE_CUTOFF_MS = 1300;
static constexpr uint32_t COMMAND_NO_SPEECH_TIMEOUT_MS = 5000;
static constexpr uint16_t COMMAND_SPEECH_RMS = 180;
static constexpr uint16_t COMMAND_SPEECH_PEAK = 1000;
static constexpr uint8_t MAX_FOLLOWUP_TURNS = 2;
static constexpr uint8_t WIFI_JOIN_ATTEMPTS = 2;
static constexpr uint32_t WIFI_TIMEOUT_MS = 20000;
static constexpr uint32_t WIFI_RETRY_COOLDOWN_MS = 5000;
static constexpr uint32_t HTTP_TIMEOUT_MS = 90000;
static constexpr uint32_t WAKE_CHECK_PAUSE_MS = 750;
static constexpr uint32_t MIC_CAPTURE_FAILURE_BACKOFF_MS = 4000;
static constexpr uint32_t COMMAND_START_DELAY_MS = 1500;
static constexpr int MAX_CAPTURED_RESPONSE_BYTES = 2048;
static constexpr int MIN_AUDIO_RESPONSE_BYTES = 1000;
static constexpr size_t MAX_AUDIO_RESPONSE_BYTES = 192 * 1024;
static constexpr uint16_t WAV_BITS_PER_SAMPLE = 16;
static constexpr uint16_t WAV_CHANNELS = 1;
static constexpr size_t STREAM_CHUNK_BYTES = 1024;
static constexpr size_t WAV_HEADER_BYTES = 44;
static constexpr uint32_t SPEAKER_I2S_RATE = 16000;
static constexpr uint32_t TEST_TONE_DURATION_MS = 700;
static constexpr uint32_t TEST_TONE_FREQUENCY = 880;
static constexpr int16_t TEST_TONE_AMPLITUDE = 2400;

struct AudioLevel {
  uint16_t rms;
  uint16_t peak;
};

struct AudioHttpResponse {
  int statusCode;
  String contentType;
  uint8_t *body;
  size_t bodySize;
};

struct HttpResponseHeaders {
  int statusCode;
  String contentType;
  int contentLength;
  bool chunked;
  bool listenAgain;
};

struct HttpBodyReader {
  WiFiClient *client;
  bool chunked;
  bool done;
  size_t chunkRemaining;
};

enum class AudioPath {
  None,
  Mic,
  Speaker,
};

I2SClass i2s;
HWCDC Log;
bool micReady = false;
bool speakerReady = false;
bool wifiReady = false;
bool wakeMonitorEnabled = true;
uint32_t lastWakeCheckAt = 0;
uint32_t lastWifiAttemptAt = 0;
uint32_t micCaptureBackoffUntil = 0;
AudioPath activeAudioPath = AudioPath::None;
uint8_t consecutiveRecordFailures = 0;

static void logLine(const String &message) {
  Log.println(message);
}

static void resetI2SState() {
  i2s.end();
  i2s.~I2SClass();
  new (&i2s) I2SClass();
  activeAudioPath = AudioPath::None;
  micReady = false;
  speakerReady = false;
  delay(120);
}

static const char *wifiStatusName(wl_status_t status) {
  switch (status) {
    case WL_IDLE_STATUS:
      return "idle";
    case WL_NO_SSID_AVAIL:
      return "no_ssid_available";
    case WL_SCAN_COMPLETED:
      return "scan_completed";
    case WL_CONNECTED:
      return "connected";
    case WL_CONNECT_FAILED:
      return "connect_failed";
    case WL_CONNECTION_LOST:
      return "connection_lost";
    case WL_DISCONNECTED:
      return "disconnected";
    default:
      return "unknown";
  }
}

static bool scanForConfiguredWifi() {
  Log.print("Scanning for Wi-Fi SSID: ");
  Log.println(WIFI_SSID);

  const int networkCount = WiFi.scanNetworks(false, true);
  bool found = false;
  int32_t bestRssi = -1000;

  if (networkCount < 0) {
    Log.print("Wi-Fi scan failed. result=");
    Log.println(networkCount);
    return false;
  }

  for (int i = 0; i < networkCount; i++) {
    if (WiFi.SSID(i) == WIFI_SSID) {
      found = true;
      bestRssi = max(bestRssi, WiFi.RSSI(i));
    }
  }

  WiFi.scanDelete();

  if (found) {
    Log.print("Configured Wi-Fi found. Best RSSI=");
    Log.println(bestRssi);
  } else {
    Log.print("Configured Wi-Fi was not found. Networks visible=");
    Log.println(networkCount);
  }

  return found;
}

static bool connectWifi() {
  lastWifiAttemptAt = millis();
  WiFi.persistent(false);
  WiFi.setAutoReconnect(false);
  WiFi.disconnect(true, true);
  delay(500);
  WiFi.mode(WIFI_OFF);
  delay(500);
  WiFi.mode(WIFI_STA);
  delay(250);
  WiFi.setSleep(false);

  scanForConfiguredWifi();

  for (uint8_t attempt = 1; attempt <= WIFI_JOIN_ATTEMPTS; attempt++) {
    Log.print("Connecting to Wi-Fi SSID: ");
    Log.print(WIFI_SSID);
    Log.print(" attempt ");
    Log.print(attempt);
    Log.print("/");
    Log.println(WIFI_JOIN_ATTEMPTS);

    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

    wl_status_t lastStatus = static_cast<wl_status_t>(255);
    const uint32_t startedAt = millis();
    while (WiFi.status() != WL_CONNECTED && millis() - startedAt < WIFI_TIMEOUT_MS) {
      const wl_status_t status = WiFi.status();
      if (status != lastStatus) {
        Log.print("Wi-Fi status=");
        Log.print(status);
        Log.print(" (");
        Log.print(wifiStatusName(status));
        Log.println(")");
        lastStatus = status;
      }
      Log.print(".");
      delay(500);
    }
    Log.println();

    if (WiFi.status() == WL_CONNECTED) {
      WiFi.setAutoReconnect(true);
      Log.print("Wi-Fi connected. ESP32 IP: ");
      Log.println(WiFi.localIP());
      Log.print("Wi-Fi RSSI: ");
      Log.println(WiFi.RSSI());
      return true;
    }

    const wl_status_t failedStatus = WiFi.status();
    Log.print("Wi-Fi failed. status=");
    Log.print(failedStatus);
    Log.print(" (");
    Log.print(wifiStatusName(failedStatus));
    Log.println(")");
    WiFi.disconnect(false, false);
    delay(1200);
  }

  WiFi.setAutoReconnect(false);
  WiFi.disconnect(false, false);
  return false;
}

static bool initMic(bool forceReinit = false) {
  if (!forceReinit && activeAudioPath == AudioPath::Mic && micReady) {
    return true;
  }

  resetI2SState();
  i2s.setPins(I2S_BCLK, I2S_WS, -1, I2S_DIN);

  if (!i2s.begin(I2S_MODE_STD, SAMPLE_RATE, I2S_DATA_BIT_WIDTH_32BIT, I2S_SLOT_MODE_MONO, I2S_STD_SLOT_LEFT)) {
    Log.print("I2S init failed. lastError=");
    Log.println(i2s.lastError());
    return false;
  }

  if (!i2s.configureRX(SAMPLE_RATE, I2S_DATA_BIT_WIDTH_32BIT, I2S_SLOT_MODE_MONO, I2S_RX_TRANSFORM_32_TO_16)) {
    Log.print("I2S RX transform failed. lastError=");
    Log.println(i2s.lastError());
    return false;
  }

  activeAudioPath = AudioPath::Mic;
  micReady = true;
  speakerReady = false;
  logLine("INMP441 I2S mic initialized as 16 kHz, 16-bit, mono WAV.");
  return true;
}

static bool recoverMicPath(const char *reason) {
  Log.print("Recovering microphone path: ");
  Log.println(reason);
  return initMic(true);
}

static bool initSpeaker() {
  if (activeAudioPath == AudioPath::Speaker && speakerReady) {
    return true;
  }

  resetI2SState();
  i2s.setPins(SPEAKER_I2S_BCLK, SPEAKER_I2S_LRC, SPEAKER_I2S_DIN);

  if (!i2s.begin(I2S_MODE_STD, SPEAKER_I2S_RATE, I2S_DATA_BIT_WIDTH_16BIT, I2S_SLOT_MODE_STEREO)) {
    Log.print("Speaker I2S init failed. lastError=");
    Log.println(i2s.lastError());
    return false;
  }

  activeAudioPath = AudioPath::Speaker;
  speakerReady = true;
  micReady = false;
  logLine("MAX98357A speaker output initialized.");
  return true;
}

static void putLe16(uint8_t *buffer, int offset, uint16_t value) {
  buffer[offset] = value & 0xff;
  buffer[offset + 1] = (value >> 8) & 0xff;
}

static void putLe32(uint8_t *buffer, int offset, uint32_t value) {
  buffer[offset] = value & 0xff;
  buffer[offset + 1] = (value >> 8) & 0xff;
  buffer[offset + 2] = (value >> 16) & 0xff;
  buffer[offset + 3] = (value >> 24) & 0xff;
}

static uint16_t readLe16(const uint8_t *buffer, size_t offset) {
  return static_cast<uint16_t>(buffer[offset]) | (static_cast<uint16_t>(buffer[offset + 1]) << 8);
}

static uint32_t readLe32(const uint8_t *buffer, size_t offset) {
  return static_cast<uint32_t>(buffer[offset]) |
         (static_cast<uint32_t>(buffer[offset + 1]) << 8) |
         (static_cast<uint32_t>(buffer[offset + 2]) << 16) |
         (static_cast<uint32_t>(buffer[offset + 3]) << 24);
}

static void buildWavHeader(uint8_t *header, uint32_t pcmBytes) {
  if (header == nullptr) {
    return;
  }
  memset(header, 0, WAV_HEADER_BYTES);
  memcpy(header, "RIFF", 4);
  putLe32(header, 4, 36 + pcmBytes);
  memcpy(header + 8, "WAVE", 4);
  memcpy(header + 12, "fmt ", 4);
  putLe32(header, 16, 16);
  putLe16(header, 20, 1);
  putLe16(header, 22, WAV_CHANNELS);
  putLe32(header, 24, SAMPLE_RATE);
  putLe32(header, 28, SAMPLE_RATE * WAV_CHANNELS * (WAV_BITS_PER_SAMPLE / 8));
  putLe16(header, 32, WAV_CHANNELS * (WAV_BITS_PER_SAMPLE / 8));
  putLe16(header, 34, WAV_BITS_PER_SAMPLE);
  memcpy(header + 36, "data", 4);
  putLe32(header, 40, pcmBytes);
}

static void writeWavHeader(WiFiClient &client, uint32_t pcmBytes) {
  uint8_t header[44] = {};
  buildWavHeader(header, pcmBytes);
  client.write(header, sizeof(header));
}

static String buildMetadataParts(const String &boundary, const String &mode, bool includeWakeWord) {
  String metadataParts;
  if (mode.length() > 0) {
    metadataParts += "--" + boundary + "\r\n";
    metadataParts += "Content-Disposition: form-data; name=\"mode\"\r\n\r\n";
    metadataParts += mode + "\r\n";
    metadataParts += "--" + boundary + "\r\n";
    metadataParts += "Content-Disposition: form-data; name=\"body[mode]\"\r\n\r\n";
    metadataParts += mode + "\r\n";
  }
  if (includeWakeWord) {
    metadataParts += "--" + boundary + "\r\n";
    metadataParts += "Content-Disposition: form-data; name=\"wake_word\"\r\n\r\n";
    metadataParts += String(WAKE_WORD) + "\r\n";
    metadataParts += "--" + boundary + "\r\n";
    metadataParts += "Content-Disposition: form-data; name=\"body[wake_word]\"\r\n\r\n";
    metadataParts += String(WAKE_WORD) + "\r\n";
  }
  return metadataParts;
}

static uint8_t *recordWav(size_t *wavSize, size_t seconds, const char *label) {
  for (int attempt = 0; attempt < 2; attempt++) {
    Log.print(label);
    Log.print(": ");
    Log.print("Recording ");
    Log.print(seconds);
    Log.println(" seconds...");

    uint8_t *wav = i2s.recordWAV(seconds, wavSize);
    if (wav != nullptr && *wavSize > 0) {
      consecutiveRecordFailures = 0;
      micCaptureBackoffUntil = 0;
      Log.print("Recorded WAV bytes: ");
      Log.println(*wavSize);
      return wav;
    }

    logLine("Recording failed: no WAV data.");
    Log.print("I2S lastError=");
    Log.println(i2s.lastError());

    if (attempt == 0 && recoverMicPath("empty WAV capture")) {
      logLine("Retrying recording after microphone re-init.");
      delay(80);
      continue;
    }

    return nullptr;
  }
  consecutiveRecordFailures++;
  micCaptureBackoffUntil = millis() + MIC_CAPTURE_FAILURE_BACKOFF_MS;
  return nullptr;
}

static AudioLevel analyzePcmBuffer(const uint8_t *pcm, size_t pcmSize);

static AudioLevel analyzePcmLevel(const uint8_t *wav, size_t wavSize) {
  AudioLevel level = {0, 0};
  if (wav == nullptr || wavSize <= WAV_HEADER_BYTES) {
    return level;
  }

  return analyzePcmBuffer(wav + WAV_HEADER_BYTES, wavSize - WAV_HEADER_BYTES);
}

static AudioLevel analyzePcmBuffer(const uint8_t *pcm, size_t pcmSize) {
  AudioLevel level = {0, 0};
  if (pcm == nullptr || pcmSize < sizeof(int16_t)) {
    return level;
  }

  const int16_t *samples = reinterpret_cast<const int16_t *>(pcm);
  const size_t sampleCount = pcmSize / sizeof(int16_t);
  uint64_t squareSum = 0;
  uint16_t peak = 0;

  for (size_t i = 0; i < sampleCount; i++) {
    const int32_t sample = samples[i];
    const uint16_t absolute = static_cast<uint16_t>(sample < 0 ? -sample : sample);
    if (absolute > peak) {
      peak = absolute;
    }
    const int64_t signedSample = sample;
    squareSum += static_cast<uint64_t>(signedSample * signedSample);
  }

  level.rms = sampleCount > 0 ? static_cast<uint16_t>(sqrt(static_cast<double>(squareSum) / sampleCount)) : 0;
  level.peak = peak;
  return level;
}

static bool hasEnoughSpeechLevel(const AudioLevel &level) {
  return level.rms >= WAKE_MIN_RMS && level.peak >= WAKE_MIN_PEAK;
}

static bool readHttpResponse(WiFiClient &client, String *capturedBody = nullptr, int *bodyByteCount = nullptr) {
  const uint32_t startedAt = millis();
  bool gotStatus = false;
  int responseBytes = 0;

  while (client.connected() || client.available()) {
    while (client.available()) {
      String line = client.readStringUntil('\n');
      line.trim();
      if (!gotStatus) {
        Log.print("HTTP response: ");
        Log.println(line);
        gotStatus = true;
      }
      if (line.length() == 0) {
        goto body_start;
      }
    }
    if (millis() - startedAt > HTTP_TIMEOUT_MS) {
      logLine("Timed out waiting for HTTP response headers.");
      return false;
    }
    delay(10);
  }

body_start:
  const uint32_t bodyStartedAt = millis();
  while (client.connected() || client.available()) {
    while (client.available()) {
      const char value = static_cast<char>(client.read());
      responseBytes++;
      if (capturedBody != nullptr && capturedBody->length() < MAX_CAPTURED_RESPONSE_BYTES) {
        *capturedBody += value;
      }
    }
    if (millis() - bodyStartedAt > HTTP_TIMEOUT_MS) {
      logLine("Timed out while reading response body.");
      break;
    }
    delay(10);
  }

  Log.print("Response body bytes received: ");
  Log.println(responseBytes);
  if (bodyByteCount != nullptr) {
    *bodyByteCount = responseBytes;
  }
  return gotStatus;
}

static bool readRemainingTextBody(WiFiClient &client, String *capturedBody, int *bodyByteCount = nullptr) {
  if (capturedBody != nullptr) {
    capturedBody->remove(0);
  }

  int responseBytes = 0;
  const uint32_t bodyStartedAt = millis();
  while (client.connected() || client.available()) {
    while (client.available()) {
      const char value = static_cast<char>(client.read());
      responseBytes++;
      if (capturedBody != nullptr && capturedBody->length() < MAX_CAPTURED_RESPONSE_BYTES) {
        *capturedBody += value;
      }
    }
    if (millis() - bodyStartedAt > HTTP_TIMEOUT_MS) {
      logLine("Timed out while reading response body.");
      break;
    }
    delay(10);
  }

  if (bodyByteCount != nullptr) {
    *bodyByteCount = responseBytes;
  }
  Log.print("Response body bytes received: ");
  Log.println(responseBytes);
  return responseBytes > 0;
}

static bool readHttpResponseHeaders(WiFiClient &client, HttpResponseHeaders *headers) {
  if (headers == nullptr) {
    return false;
  }

  headers->statusCode = 0;
  headers->contentType = "";
  headers->contentLength = -1;
  headers->chunked = false;
  headers->listenAgain = false;

  const uint32_t startedAt = millis();
  bool gotStatus = false;

  while (client.connected() || client.available()) {
    while (client.available()) {
      String line = client.readStringUntil('\n');
      line.trim();
      if (!gotStatus) {
        Log.print("HTTP response: ");
        Log.println(line);
        const int firstSpace = line.indexOf(' ');
        if (firstSpace >= 0 && line.length() >= firstSpace + 4) {
          headers->statusCode = line.substring(firstSpace + 1, firstSpace + 4).toInt();
        }
        gotStatus = true;
        continue;
      }

      if (line.length() == 0) {
        if (headers->contentType.length() > 0) {
          headers->contentType.toLowerCase();
        }
        return gotStatus;
      }

      String lowerLine = line;
      lowerLine.toLowerCase();
      if (lowerLine.startsWith("content-type:")) {
        headers->contentType = line.substring(line.indexOf(':') + 1);
        headers->contentType.trim();
      } else if (lowerLine.startsWith("content-length:")) {
        headers->contentLength = line.substring(line.indexOf(':') + 1).toInt();
      } else if (lowerLine.startsWith("transfer-encoding:") && lowerLine.indexOf("chunked") >= 0) {
        headers->chunked = true;
      } else if (lowerLine.startsWith("x-assistant-listen-again:")) {
        const String value = lowerLine.substring(lowerLine.indexOf(':') + 1);
        headers->listenAgain = value.indexOf("true") >= 0 || value.indexOf("1") >= 0 || value.indexOf("yes") >= 0;
      }
    }

    if (millis() - startedAt > HTTP_TIMEOUT_MS) {
      logLine("Timed out waiting for HTTP response headers.");
      return false;
    }
    delay(10);
  }

  if (headers->contentType.length() > 0) {
    headers->contentType.toLowerCase();
  }
  return gotStatus;
}

static void freeAudioHttpResponse(AudioHttpResponse *response) {
  if (response == nullptr) {
    return;
  }
  if (response->body != nullptr) {
    free(response->body);
    response->body = nullptr;
  }
  response->bodySize = 0;
  response->contentType = "";
  response->statusCode = 0;
}

static bool readAudioHttpResponse(WiFiClient &client, AudioHttpResponse *response) {
  if (response == nullptr) {
    return false;
  }

  response->statusCode = 0;
  response->contentType = "";
  response->body = nullptr;
  response->bodySize = 0;

  HttpResponseHeaders headers = {};
  if (!readHttpResponseHeaders(client, &headers)) {
    return false;
  }

  response->statusCode = headers.statusCode;
  response->contentType = headers.contentType;

  const int contentLength = headers.contentLength;
  size_t capacity = contentLength > 0 ? static_cast<size_t>(contentLength) : 8192;
  if (capacity > MAX_AUDIO_RESPONSE_BYTES) {
    Log.print("Audio response too large: ");
    Log.println(contentLength);
    return false;
  }

  uint8_t *buffer = static_cast<uint8_t *>(malloc(capacity > 0 ? capacity : 1));
  if (buffer == nullptr) {
    logLine("Failed to allocate buffer for audio response.");
    return false;
  }

  size_t totalRead = 0;
  const uint32_t bodyStartedAt = millis();
  while (client.connected() || client.available()) {
    if (client.available()) {
      if (totalRead == capacity) {
        if (capacity >= MAX_AUDIO_RESPONSE_BYTES) {
          logLine("Audio response exceeded maximum buffer size.");
          free(buffer);
          return false;
        }

        size_t nextCapacity = capacity * 2;
        if (nextCapacity < capacity + 1024) {
          nextCapacity = capacity + 1024;
        }
        if (nextCapacity > MAX_AUDIO_RESPONSE_BYTES) {
          nextCapacity = MAX_AUDIO_RESPONSE_BYTES;
        }

        uint8_t *grown = static_cast<uint8_t *>(realloc(buffer, nextCapacity));
        if (grown == nullptr) {
          logLine("Failed to grow audio response buffer.");
          free(buffer);
          return false;
        }
        buffer = grown;
        capacity = nextCapacity;
      }

      const int bytesRead = client.read(buffer + totalRead, capacity - totalRead);
      if (bytesRead > 0) {
        totalRead += static_cast<size_t>(bytesRead);
      }
      continue;
    }

    if (millis() - bodyStartedAt > HTTP_TIMEOUT_MS) {
      logLine("Timed out while reading audio response body.");
      free(buffer);
      return false;
    }
    delay(10);
  }

  response->body = buffer;
  response->bodySize = totalRead;
  Log.print("Response body bytes received: ");
  Log.println(static_cast<int>(totalRead));
  return response->statusCode == 200 && totalRead > 0;
}

static bool looksLikeMp3(const uint8_t *data, size_t size) {
  if (data == nullptr || size < 3) {
    return false;
  }

  if (memcmp(data, "ID3", 3) == 0) {
    return true;
  }

  if (size >= 2 && data[0] == 0xFF && (data[1] & 0xE0) == 0xE0) {
    return true;
  }

  return false;
}

static bool readChunkSizeLine(HttpBodyReader *reader) {
  if (reader == nullptr || reader->client == nullptr) {
    return false;
  }

  const uint32_t startedAt = millis();
  while (reader->client->connected() || reader->client->available()) {
    if (reader->client->available()) {
      String line = reader->client->readStringUntil('\n');
      line.trim();
      const int extensionStart = line.indexOf(';');
      if (extensionStart >= 0) {
        line = line.substring(0, extensionStart);
        line.trim();
      }

      char *endPtr = nullptr;
      const unsigned long chunkSize = strtoul(line.c_str(), &endPtr, 16);
      if (endPtr == line.c_str()) {
        Log.print("Invalid HTTP chunk size: ");
        Log.println(line);
        return false;
      }

      reader->chunkRemaining = static_cast<size_t>(chunkSize);
      if (reader->chunkRemaining == 0) {
        while (reader->client->connected() || reader->client->available()) {
          String trailer = reader->client->readStringUntil('\n');
          trailer.trim();
          if (trailer.length() == 0) {
            break;
          }
        }
        reader->done = true;
      }
      return true;
    }

    if (millis() - startedAt > HTTP_TIMEOUT_MS) {
      logLine("Timed out while reading HTTP chunk size.");
      return false;
    }
    delay(10);
  }

  reader->done = true;
  return true;
}

static int readHttpBodyBytes(HttpBodyReader *reader, uint8_t *buffer, size_t maxBytes) {
  if (reader == nullptr || reader->client == nullptr || buffer == nullptr || maxBytes == 0 || reader->done) {
    return 0;
  }

  if (!reader->chunked) {
    const uint32_t startedAt = millis();
    while (reader->client->connected() || reader->client->available()) {
      if (reader->client->available()) {
        return reader->client->read(buffer, maxBytes);
      }
      if (millis() - startedAt > HTTP_TIMEOUT_MS) {
        logLine("Timed out while reading HTTP body.");
        return -1;
      }
      delay(10);
    }
    reader->done = true;
    return 0;
  }

  if (reader->chunkRemaining == 0) {
    if (!readChunkSizeLine(reader) || reader->done) {
      return reader->done ? 0 : -1;
    }
  }

  const size_t wanted = min(maxBytes, reader->chunkRemaining);
  const uint32_t startedAt = millis();
  while (reader->client->connected() || reader->client->available()) {
    if (reader->client->available()) {
      const int bytesRead = reader->client->read(buffer, wanted);
      if (bytesRead > 0) {
        reader->chunkRemaining -= static_cast<size_t>(bytesRead);
        if (reader->chunkRemaining == 0) {
          const uint32_t crlfStartedAt = millis();
          while ((reader->client->connected() || reader->client->available()) && reader->client->available() < 2) {
            if (millis() - crlfStartedAt > HTTP_TIMEOUT_MS) {
              logLine("Timed out while reading HTTP chunk terminator.");
              return -1;
            }
            delay(10);
          }
          if (reader->client->available() >= 2) {
            reader->client->read();
            reader->client->read();
          }
        }
        return bytesRead;
      }
    }

    if (millis() - startedAt > HTTP_TIMEOUT_MS) {
      logLine("Timed out while reading HTTP chunk body.");
      return -1;
    }
    delay(10);
  }

  reader->done = true;
  return 0;
}

static bool parsePcmWavHeader(
    const uint8_t *data,
    size_t size,
    size_t *dataOffset,
    size_t *dataSize,
    uint16_t *audioFormat,
    uint16_t *channels,
    uint32_t *sampleRate,
    uint16_t *bitsPerSample) {
  if (data == nullptr || size < 44 || memcmp(data, "RIFF", 4) != 0 || memcmp(data + 8, "WAVE", 4) != 0) {
    return false;
  }

  const uint16_t localAudioFormat = readLe16(data, 20);
  const uint16_t localChannels = readLe16(data, 22);
  const uint32_t localSampleRate = readLe32(data, 24);
  const uint16_t localBitsPerSample = readLe16(data, 34);

  size_t chunkOffset = 12;
  size_t localDataOffset = 0;
  size_t localDataSize = 0;
  while (chunkOffset + 8 <= size) {
    const uint32_t chunkSize = readLe32(data, chunkOffset + 4);
    if (memcmp(data + chunkOffset, "data", 4) == 0) {
      localDataOffset = chunkOffset + 8;
      if (localDataOffset > size) {
        return false;
      }
      localDataSize = min(static_cast<size_t>(chunkSize), size - localDataOffset);
      break;
    }
    chunkOffset += 8 + chunkSize + (chunkSize & 1U);
  }

  if (localDataOffset == 0) {
    return false;
  }

  if (dataOffset != nullptr) {
    *dataOffset = localDataOffset;
  }
  if (dataSize != nullptr) {
    *dataSize = localDataSize;
  }
  if (audioFormat != nullptr) {
    *audioFormat = localAudioFormat;
  }
  if (channels != nullptr) {
    *channels = localChannels;
  }
  if (sampleRate != nullptr) {
    *sampleRate = localSampleRate;
  }
  if (bitsPerSample != nullptr) {
    *bitsPerSample = localBitsPerSample;
  }
  return true;
}

static bool playPcmWavOnSpeaker(const uint8_t *data, size_t size) {
  size_t dataOffset = 0;
  size_t dataSize = 0;
  uint16_t audioFormat = 0;
  uint16_t channels = 0;
  uint32_t sampleRate = 0;
  uint16_t bitsPerSample = 0;
  if (!parsePcmWavHeader(data, size, &dataOffset, &dataSize, &audioFormat, &channels, &sampleRate, &bitsPerSample)) {
    return false;
  }

  if (dataOffset == 0 || dataSize == 0) {
    logLine("WAV response had no data chunk.");
    return false;
  }

  if (audioFormat != 1 || bitsPerSample != 16) {
    Log.print("Unsupported WAV format. audioFormat=");
    Log.print(audioFormat);
    Log.print(" bits=");
    Log.println(bitsPerSample);
    return false;
  }

  Log.print("Playing WAV response. sampleRate=");
  Log.print(sampleRate);
  Log.print(" channels=");
  Log.println(channels);

  if (channels == 1) {
    if (!i2s.configureTX(sampleRate, I2S_DATA_BIT_WIDTH_16BIT, I2S_SLOT_MODE_STEREO)) {
      Log.print("Speaker TX configure failed for mono WAV. lastError=");
      Log.println(i2s.lastError());
      return false;
    }

    const int16_t *src = reinterpret_cast<const int16_t *>(data + dataOffset);
    const size_t sampleCount = dataSize / sizeof(int16_t);
    int16_t stereoFrame[256 * 2];

    for (size_t base = 0; base < sampleCount; base += 256) {
      const size_t chunkSamples = min(static_cast<size_t>(256), sampleCount - base);
      for (size_t i = 0; i < chunkSamples; i++) {
        const int16_t sample = src[base + i];
        stereoFrame[i * 2] = sample;
        stereoFrame[i * 2 + 1] = sample;
      }

      const size_t bytesToWrite = chunkSamples * sizeof(int16_t) * 2;
      if (i2s.write(reinterpret_cast<const uint8_t *>(stereoFrame), bytesToWrite) != bytesToWrite) {
        logLine("Short write while playing mono WAV response.");
        return false;
      }
    }
    return true;
  }

  if (channels == 2) {
    if (!i2s.configureTX(sampleRate, I2S_DATA_BIT_WIDTH_16BIT, I2S_SLOT_MODE_STEREO)) {
      Log.print("Speaker TX configure failed for stereo WAV. lastError=");
      Log.println(i2s.lastError());
      return false;
    }
    return i2s.write(data + dataOffset, dataSize) == dataSize;
  }

  Log.print("Unsupported WAV channel count: ");
  Log.println(channels);
  return false;
}

static bool writeMonoPcmBytesToSpeaker(const uint8_t *data, size_t size, uint8_t *pendingBytes, size_t *pendingCount) {
  if (pendingBytes == nullptr || pendingCount == nullptr) {
    return false;
  }

  size_t offset = 0;
  int16_t stereoFrame[256 * 2];

  if (*pendingCount == 1 && size > 0) {
    pendingBytes[1] = data[0];
    const int16_t sample = static_cast<int16_t>(
        static_cast<uint16_t>(pendingBytes[0]) | (static_cast<uint16_t>(pendingBytes[1]) << 8));
    stereoFrame[0] = sample;
    stereoFrame[1] = sample;
    if (i2s.write(reinterpret_cast<const uint8_t *>(stereoFrame), sizeof(int16_t) * 2) != sizeof(int16_t) * 2) {
      logLine("Short write while flushing pending mono PCM sample.");
      return false;
    }
    *pendingCount = 0;
    offset = 1;
  }

  while (offset + 1 < size) {
    const size_t chunkSamples = min(static_cast<size_t>(256), (size - offset) / sizeof(int16_t));
    for (size_t i = 0; i < chunkSamples; i++) {
      const uint8_t low = data[offset + (i * 2)];
      const uint8_t high = data[offset + (i * 2) + 1];
      const int16_t sample = static_cast<int16_t>(static_cast<uint16_t>(low) | (static_cast<uint16_t>(high) << 8));
      stereoFrame[i * 2] = sample;
      stereoFrame[i * 2 + 1] = sample;
    }

    const size_t bytesToWrite = chunkSamples * sizeof(int16_t) * 2;
    if (i2s.write(reinterpret_cast<const uint8_t *>(stereoFrame), bytesToWrite) != bytesToWrite) {
      logLine("Short write while streaming mono WAV response.");
      return false;
    }

    offset += chunkSamples * sizeof(int16_t);
  }

  if (offset < size) {
    pendingBytes[0] = data[offset];
    *pendingCount = 1;
  }

  return true;
}

static bool playStreamingWavResponse(WiFiClient &client, const HttpResponseHeaders &headers) {
  static constexpr size_t PREBUFFER_BYTES = 512;
  uint8_t prebuffer[PREBUFFER_BYTES] = {};
  size_t prebufferSize = 0;
  HttpBodyReader bodyReader = {};
  bodyReader.client = &client;
  bodyReader.chunked = headers.chunked;
  bodyReader.done = false;
  bodyReader.chunkRemaining = 0;

  while (!bodyReader.done && prebufferSize < PREBUFFER_BYTES) {
    const int bytesRead = readHttpBodyBytes(&bodyReader, prebuffer + prebufferSize, PREBUFFER_BYTES - prebufferSize);
    if (bytesRead < 0) {
      return false;
    }
    if (bytesRead == 0) {
      break;
    }
    prebufferSize += static_cast<size_t>(bytesRead);
    if (prebufferSize >= 44) {
      break;
    }
  }

  size_t dataOffset = 0;
  size_t initialDataSize = 0;
  uint16_t audioFormat = 0;
  uint16_t channels = 0;
  uint32_t sampleRate = 0;
  uint16_t bitsPerSample = 0;
  if (!parsePcmWavHeader(
          prebuffer,
          prebufferSize,
          &dataOffset,
          &initialDataSize,
          &audioFormat,
          &channels,
          &sampleRate,
          &bitsPerSample)) {
    logLine("Streaming response was not a valid PCM WAV.");
    return false;
  }

  if (audioFormat != 1 || bitsPerSample != 16 || channels != 1) {
    Log.print("Unsupported streaming WAV format. audioFormat=");
    Log.print(audioFormat);
    Log.print(" bits=");
    Log.print(bitsPerSample);
    Log.print(" channels=");
    Log.println(channels);
    return false;
  }

  if (!initSpeaker()) {
    logLine("Speaker output is not ready.");
    return false;
  }

  if (!i2s.configureTX(sampleRate, I2S_DATA_BIT_WIDTH_16BIT, I2S_SLOT_MODE_STEREO)) {
    Log.print("Speaker TX configure failed for streaming WAV. lastError=");
    Log.println(i2s.lastError());
    return false;
  }

  Log.print("Streaming WAV response. sampleRate=");
  Log.print(sampleRate);
  Log.print(" contentLength=");
  Log.print(headers.contentLength);
  Log.print(" chunked=");
  Log.println(headers.chunked ? "yes" : "no");

  size_t totalBodyBytes = prebufferSize;
  uint8_t pendingSample[2] = {};
  size_t pendingSampleCount = 0;

  if (prebufferSize > dataOffset &&
      !writeMonoPcmBytesToSpeaker(
          prebuffer + dataOffset, prebufferSize - dataOffset, pendingSample, &pendingSampleCount)) {
    return false;
  }

  uint8_t chunkBuffer[STREAM_CHUNK_BYTES];
  while (!bodyReader.done) {
    const int bytesRead = readHttpBodyBytes(&bodyReader, chunkBuffer, sizeof(chunkBuffer));
    if (bytesRead < 0) {
      return false;
    }
    if (bytesRead == 0) {
      break;
    }
    totalBodyBytes += static_cast<size_t>(bytesRead);
    if (!writeMonoPcmBytesToSpeaker(
            chunkBuffer, static_cast<size_t>(bytesRead), pendingSample, &pendingSampleCount)) {
      return false;
    }
  }

  if (pendingSampleCount != 0) {
    logLine("Streaming WAV ended with a partial PCM sample.");
    return false;
  }

  Log.print("Response body bytes received: ");
  Log.println(static_cast<int>(totalBodyBytes));
  logLine("Speaker playback finished.");
  return true;
}

static bool postWavToN8n(
    const uint8_t *wav,
    size_t wavSize,
    const String &mode,
    bool includeWakeWord,
    String *capturedBody = nullptr) {
  WiFiClient client;
  client.setTimeout(HTTP_TIMEOUT_MS / 1000);

  Log.print("Connecting to n8n at ");
  Log.print(N8N_HOST);
  Log.print(":");
  Log.println(N8N_PORT);

  if (!client.connect(N8N_HOST, N8N_PORT)) {
    logLine("Failed to connect to n8n. Check firewall and same Wi-Fi network.");
    return false;
  }

  const String boundary = "----esp32c3-n8n-boundary";
  const String metadataParts = buildMetadataParts(boundary, mode, includeWakeWord);
  const String partHeader =
      "--" + boundary + "\r\n"
      "Content-Disposition: form-data; name=\"audio\"; filename=\"voice.wav\"\r\n"
      "Content-Type: audio/wav\r\n\r\n";
  const String partFooter = "\r\n--" + boundary + "--\r\n";
  const size_t contentLength = metadataParts.length() + partHeader.length() + wavSize + partFooter.length();

  client.print("POST ");
  client.print(N8N_PATH);
  client.println(" HTTP/1.1");
  client.print("Host: ");
  client.print(N8N_HOST);
  client.print(":");
  client.println(N8N_PORT);
  client.println("User-Agent: esp32c3-inmp441");
  client.println("Connection: close");
  client.print("Content-Type: multipart/form-data; boundary=");
  client.println(boundary);
  client.print("Content-Length: ");
  client.println(contentLength);
  client.println();

  client.print(metadataParts);
  client.print(partHeader);

  size_t sent = 0;
  uint32_t lastUploadProgressAt = millis();
  while (sent < wavSize) {
    const size_t chunk = min(static_cast<size_t>(1024), wavSize - sent);
    const size_t written = client.write(wav + sent, chunk);
    if (written == 0) {
      if (millis() - lastUploadProgressAt > 5000) {
        logLine("Upload stalled while writing WAV.");
        client.stop();
        return false;
      }
      delay(20);
      continue;
    }
    sent += written;
    lastUploadProgressAt = millis();
  }

  client.print(partFooter);

  Log.print("Uploaded multipart bytes: ");
  Log.println(contentLength);

  const bool ok = readHttpResponse(client, capturedBody);
  client.stop();
  return ok;
}

static bool writeHttpChunk(WiFiClient &client, const uint8_t *data, size_t size) {
  if (data == nullptr || size == 0) {
    return true;
  }

  client.print(static_cast<unsigned long>(size), HEX);
  client.print("\r\n");
  size_t sent = 0;
  uint32_t lastChunkProgressAt = millis();
  while (sent < size) {
    const size_t written = client.write(data + sent, size - sent);
    if (written == 0) {
      if (millis() - lastChunkProgressAt > 5000) {
        return false;
      }
      delay(20);
      continue;
    }
    sent += written;
    lastChunkProgressAt = millis();
  }
  client.print("\r\n");
  return true;
}

static bool writeHttpChunkString(WiFiClient &client, const String &value) {
  return writeHttpChunk(client, reinterpret_cast<const uint8_t *>(value.c_str()), value.length());
}

static bool finishHttpChunks(WiFiClient &client) {
  client.print("0\r\n\r\n");
  return true;
}

static bool commandChunkHasSpeech(const uint8_t *buffer, size_t size) {
  const AudioLevel level = analyzePcmBuffer(buffer, size);
  return level.rms >= COMMAND_SPEECH_RMS || level.peak >= COMMAND_SPEECH_PEAK;
}

static bool streamCommandClipToN8n(size_t seconds, bool *listenAgain, const char *sessionLabel = "Command") {
  if (listenAgain != nullptr) {
    *listenAgain = false;
  }

  WiFiClient client;
  client.setTimeout(HTTP_TIMEOUT_MS / 1000);

  Log.print("Connecting to n8n at ");
  Log.print(N8N_HOST);
  Log.print(":");
  Log.println(N8N_PORT);

  if (!client.connect(N8N_HOST, N8N_PORT)) {
    logLine("Failed to connect to n8n. Check firewall and same Wi-Fi network.");
    return false;
  }

  const String boundary = "----esp32c3-n8n-boundary";
  const String metadataParts = buildMetadataParts(boundary, "command", false);
  const String partHeader =
      "--" + boundary + "\r\n"
      "Content-Disposition: form-data; name=\"audio\"; filename=\"voice.wav\"\r\n"
      "Content-Type: audio/wav\r\n\r\n";
  const String partFooter = "\r\n--" + boundary + "--\r\n";
  const uint32_t pcmBytes = seconds * SAMPLE_RATE * WAV_CHANNELS * (WAV_BITS_PER_SAMPLE / 8);

  client.print("POST ");
  client.print(N8N_PATH);
  client.println(" HTTP/1.1");
  client.print("Host: ");
  client.print(N8N_HOST);
  client.print(":");
  client.println(N8N_PORT);
  client.println("User-Agent: esp32c3-inmp441");
  client.println("Connection: close");
  client.print("Content-Type: multipart/form-data; boundary=");
  client.println(boundary);
  client.println("Transfer-Encoding: chunked");
  client.println();

  if (!writeHttpChunkString(client, metadataParts) || !writeHttpChunkString(client, partHeader)) {
    logLine("Upload stalled while writing command metadata.");
    client.stop();
    return false;
  }

  uint8_t wavHeader[WAV_HEADER_BYTES] = {};
  buildWavHeader(wavHeader, pcmBytes);
  if (!writeHttpChunk(client, wavHeader, sizeof(wavHeader))) {
    logLine("Upload stalled while writing WAV header.");
    client.stop();
    return false;
  }

  Log.print(sessionLabel);
  Log.print(": Recording up to ");
  Log.print(seconds);
  Log.println(" seconds. Auto-stop after silence is enabled.");

  uint8_t buffer[STREAM_CHUNK_BYTES];
  uint32_t streamed = 0;
  bool heardSpeech = false;
  bool stoppedForSilence = false;
  bool stoppedForNoSpeech = false;
  const uint32_t startedAt = millis();
  uint32_t lastSpeechAt = startedAt;

  while (streamed < pcmBytes) {
    const size_t requested = min(static_cast<size_t>(STREAM_CHUNK_BYTES), static_cast<size_t>(pcmBytes - streamed));
    const size_t read = i2s.readBytes(reinterpret_cast<char *>(buffer), requested);
    if (read == 0) {
      logLine("I2S stream read failed.");
      client.stop();
      return false;
    }

    if (commandChunkHasSpeech(buffer, read)) {
      heardSpeech = true;
      lastSpeechAt = millis();
    }

    if (!writeHttpChunk(client, buffer, read)) {
      logLine("Upload stalled while streaming command audio.");
      client.stop();
      return false;
    }

    streamed += read;

    const uint32_t now = millis();
    const uint32_t elapsed = now - startedAt;
    if (heardSpeech && elapsed >= COMMAND_MIN_RECORD_MS && now - lastSpeechAt >= COMMAND_SILENCE_CUTOFF_MS) {
      stoppedForSilence = true;
      break;
    }
    if (!heardSpeech && elapsed >= COMMAND_NO_SPEECH_TIMEOUT_MS) {
      stoppedForNoSpeech = true;
      break;
    }
  }

  if (!writeHttpChunkString(client, partFooter) || !finishHttpChunks(client)) {
    logLine("Upload stalled while finishing command audio.");
    client.stop();
    return false;
  }

  Log.print("Streamed command PCM bytes: ");
  Log.println(streamed);
  if (stoppedForSilence) {
    logLine("Auto-stopped command recording after silence.");
  } else if (stoppedForNoSpeech) {
    logLine("Auto-stopped command recording because no speech was detected.");
  } else {
    logLine("Reached maximum command recording time.");
  }

  HttpResponseHeaders headers = {};
  if (!readHttpResponseHeaders(client, &headers)) {
    client.stop();
    return false;
  }

  if (headers.statusCode != 200) {
    Log.print("Unexpected audio response status: ");
    Log.println(headers.statusCode);
    client.stop();
    return false;
  }

  if (listenAgain != nullptr) {
    *listenAgain = headers.listenAgain;
  }

  const bool looksLikeWav = headers.contentType.length() == 0 || headers.contentType.indexOf("audio/wav") >= 0;
  bool ok = false;
  if (looksLikeWav) {
    ok = playStreamingWavResponse(client, headers);
  } else {
    Log.print("Unsupported streaming response content type: ");
    Log.println(headers.contentType);
    String errorBody;
    readRemainingTextBody(client, &errorBody);
    if (errorBody.length() > 0) {
      Log.print("Workflow returned text body: ");
      Log.println(errorBody);
    }
  }
  client.stop();
  return ok;
}

static bool playAudioResponse(const AudioHttpResponse &response) {
  if (response.body == nullptr || response.bodySize == 0) {
    logLine("No audio response data to play.");
    return false;
  }

  if (!initSpeaker()) {
    logLine("Speaker output is not ready.");
    return false;
  }

  bool played = false;
  const bool headerSaysMp3 = response.contentType.indexOf("audio/mpeg") >= 0 || response.contentType.indexOf("audio/mp3") >= 0;
  const bool bodyLooksMp3 = looksLikeMp3(response.body, response.bodySize);
#if ARDUINO_HAS_MP3_DECODER
  if (headerSaysMp3 || bodyLooksMp3) {
    played = i2s.playMP3(response.body, response.bodySize);
  }
#endif

  if (!played && response.bodySize >= 4 && memcmp(response.body, "RIFF", 4) == 0) {
    played = playPcmWavOnSpeaker(response.body, response.bodySize);
  }

  if (!played && response.contentType.indexOf("audio/wav") >= 0) {
    played = playPcmWavOnSpeaker(response.body, response.bodySize);
  }

  if (!played) {
    Log.print("Unsupported audio response type: ");
    Log.println(response.contentType);
    Log.print("Audio signature bytes: ");
    for (size_t i = 0; i < min(static_cast<size_t>(8), response.bodySize); i++) {
      if (response.body[i] < 16) {
        Log.print('0');
      }
      Log.print(response.body[i], HEX);
      Log.print(' ');
    }
    Log.println();
    return false;
  }

  logLine("Speaker playback finished.");
  return true;
}

static void playTestTone() {
  if (!initSpeaker()) {
    logLine("Cannot play test tone: speaker output is not ready.");
    return;
  }

  if (!i2s.configureTX(SPEAKER_I2S_RATE, I2S_DATA_BIT_WIDTH_16BIT, I2S_SLOT_MODE_STEREO)) {
    Log.print("Speaker TX configure failed. lastError=");
    Log.println(i2s.lastError());
    return;
  }

  logLine("Playing test tone...");
  const uint32_t halfWaveLength = max<uint32_t>(1, SPEAKER_I2S_RATE / TEST_TONE_FREQUENCY / 2);
  const uint32_t frameCount = (SPEAKER_I2S_RATE * TEST_TONE_DURATION_MS) / 1000;
  int16_t sample = TEST_TONE_AMPLITUDE;

  for (uint32_t i = 0; i < frameCount; i++) {
    if (i % halfWaveLength == 0) {
      sample = -sample;
    }

    uint8_t frame[4] = {
      static_cast<uint8_t>(sample & 0xff),
      static_cast<uint8_t>((sample >> 8) & 0xff),
      static_cast<uint8_t>(sample & 0xff),
      static_cast<uint8_t>((sample >> 8) & 0xff),
    };
    i2s.write(frame, sizeof(frame));
  }

  logLine("Test tone finished.");
}

static bool ensureWifi() {
  if (WiFi.status() == WL_CONNECTED) {
    return true;
  }

  if (millis() - lastWifiAttemptAt < WIFI_RETRY_COOLDOWN_MS) {
    return false;
  }

  logLine("Wi-Fi disconnected. Reconnecting...");
  wifiReady = connectWifi();
  return wifiReady;
}

static bool checkWakeWord() {
  if (!micReady) {
    logLine("Cannot record: mic is not ready.");
    return false;
  }

  if (millis() < micCaptureBackoffUntil) {
    return false;
  }

  if (!ensureWifi()) {
    logLine("Stopped: Wi-Fi connection failed.");
    return false;
  }

  size_t wavSize = 0;
  uint8_t *wav = recordWav(&wavSize, WAKE_RECORD_SECONDS, "Wake check");
  if (wav == nullptr) {
    if (consecutiveRecordFailures >= 3) {
      logLine("Pausing wake checks briefly after repeated microphone capture failures.");
    }
    return false;
  }

  const AudioLevel level = analyzePcmLevel(wav, wavSize);
  Log.print("Wake audio level rms=");
  Log.print(level.rms);
  Log.print(" peak=");
  Log.println(level.peak);

  if (!hasEnoughSpeechLevel(level)) {
    Log.print("Wake check skipped: too quiet. Need rms>=");
    Log.print(WAKE_MIN_RMS);
    Log.print(" and peak>=");
    Log.println(WAKE_MIN_PEAK);
    free(wav);
    return false;
  }

  String responseBody;
  const bool posted = postWavToN8n(wav, wavSize, "wake_check", true, &responseBody);
  free(wav);

  if (!posted) {
    logLine("Wake check upload failed.");
    return false;
  }

  Log.print("Wake check response: ");
  Log.println(responseBody);

  return responseBody.indexOf("\"detected\":true") >= 0;
}

static void runCommandClip() {
  if (!micReady) {
    logLine("Cannot record: mic is not ready.");
    return;
  }

  if (!ensureWifi()) {
    logLine("Stopped: Wi-Fi connection failed.");
    return;
  }

  bool keepListening = false;
  for (uint8_t turn = 0; turn <= MAX_FOLLOWUP_TURNS; turn++) {
    const bool isFollowUpTurn = turn > 0;
    const bool posted = streamCommandClipToN8n(
        COMMAND_RECORD_SECONDS,
        &keepListening,
        isFollowUpTurn ? "Follow-up" : "Command");

    if (posted) {
      logLine("Done. The command reached n8n and the reply was handled.");
    } else {
      logLine("Upload failed.");
      if (!initMic(true)) {
        logLine("Failed to restore microphone after upload failure.");
      }
      break;
    }

    if (!initMic(true)) {
      logLine("Failed to restore microphone after playback.");
      break;
    }
    delay(150);

    if (!keepListening) {
      break;
    }

    logLine("Assistant requested follow-up input.");
    logLine("Next mic window is a 20-second command recorder with silence auto-stop, not a 2-second wake check.");
    Log.print("Follow-up recording starts in ");
    Log.print(COMMAND_START_DELAY_MS / 1000.0, 1);
    Log.println(" seconds...");
    delay(COMMAND_START_DELAY_MS);
  }

  logLine("");
  logLine("Wake monitor is listening again in short wake-word checks.");
}

void setup() {
  Log.begin(115200);
  delay(1500);

  logLine("");
  logLine("ESP32-C3 n8n voice client");
  Log.print("n8n URL: http://");
  Log.print(N8N_HOST);
  Log.print(":");
  Log.print(N8N_PORT);
  Log.println(N8N_PATH);

  micReady = initMic();
  if (!micReady) {
    logLine("Stopped: mic init failed.");
    return;
  }

  wifiReady = connectWifi();
  if (!wifiReady) {
    logLine("Stopped: Wi-Fi connection failed.");
    return;
  }

  logLine("");
  logLine("");
  Log.print("Wake monitor ready. Wake word: ");
  Log.println(WAKE_WORD);
  logLine("Say the wake word, then wait for detection and speak the command.");
  logLine("Serial controls: r = force one auto-stop command, w = one wake check, p = pause/resume wake monitor, t = speaker tone test.");
}

void loop() {
  while (Log.available() > 0) {
    const char command = static_cast<char>(Log.read());
    if (command == 'r' || command == 'R') {
      runCommandClip();
    } else if (command == 'w' || command == 'W') {
      if (checkWakeWord()) {
        logLine("Wake word detected. Speak your command now.");
        Log.print("Command recording starts in ");
        Log.print(COMMAND_START_DELAY_MS / 1000.0, 1);
        Log.println(" seconds...");
        delay(COMMAND_START_DELAY_MS);
        runCommandClip();
      } else {
        logLine("Wake word not detected.");
      }
    } else if (command == 'p' || command == 'P') {
      wakeMonitorEnabled = !wakeMonitorEnabled;
      Log.print("Wake monitor ");
      Log.println(wakeMonitorEnabled ? "enabled." : "paused.");
    } else if (command == 't' || command == 'T') {
      playTestTone();
      if (!initMic(true)) {
        logLine("Failed to restore microphone after tone test.");
      }
    }
  }

  if (wakeMonitorEnabled && millis() - lastWakeCheckAt >= WAKE_CHECK_PAUSE_MS) {
    lastWakeCheckAt = millis();
    if (checkWakeWord()) {
      logLine("Wake word detected. Speak your command now.");
      Log.print("Command recording starts in ");
      Log.print(COMMAND_START_DELAY_MS / 1000.0, 1);
      Log.println(" seconds...");
      delay(COMMAND_START_DELAY_MS);
      runCommandClip();
    }
  }

  delay(50);
}
