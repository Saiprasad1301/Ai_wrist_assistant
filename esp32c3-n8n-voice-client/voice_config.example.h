#pragma once

// Copy this file to voice_config.h and fill in your local values.
// ESP32-C3 supports 2.4 GHz Wi-Fi only.
static const char *WIFI_SSID = "YOUR_WIFI_SSID";
static const char *WIFI_PASSWORD = "YOUR_WIFI_PASSWORD";

// Use your PC LAN IP address. Do not use localhost from ESP32.
static const char *N8N_HOST = "YOUR_PC_LAN_IP";
static const uint16_t N8N_PORT = 5678;
static const char *N8N_PATH = "/webhook/voice";

// MAX98357A speaker output pins.
static constexpr int8_t SPEAKER_I2S_BCLK = 8;
static constexpr int8_t SPEAKER_I2S_LRC = 9;
static constexpr int8_t SPEAKER_I2S_DIN = 10;

static const char *WAKE_WORD = "assistant";
static const uint16_t WAKE_MIN_RMS = 110;
static const uint16_t WAKE_MIN_PEAK = 900;
