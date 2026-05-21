#include <Arduino.h>
#include "ESP_I2S.h"
#include "HWCDC.h"

// INMP441 -> ESP32-C3 wiring
// VCC -> 3.3V, GND -> GND, L/R -> GND
// WS/LRCL -> GPIO 2, SCK/BCLK -> GPIO 3, SD/DOUT -> GPIO 4
static constexpr int I2S_WS = 2;
static constexpr int I2S_BCLK = 3;
static constexpr int I2S_DIN = 4;

static constexpr uint32_t SAMPLE_RATE = 16000;
static constexpr size_t SAMPLE_COUNT = 512;

I2SClass i2s;
int32_t samples[SAMPLE_COUNT];
HWCDC Log;

void setup() {
  Log.begin(115200);
  delay(1500);

  Log.println();
  Log.println("ESP32-C3 INMP441 smoke test");
  Log.println("Pins: WS=GPIO2, BCLK=GPIO3, DIN=GPIO4, L/R=GND");
  Log.println("Speak near the mic. RMS and peak should change.");

  i2s.setPins(I2S_BCLK, I2S_WS, -1, I2S_DIN);

  if (!i2s.begin(I2S_MODE_STD, SAMPLE_RATE, I2S_DATA_BIT_WIDTH_32BIT, I2S_SLOT_MODE_MONO, I2S_STD_SLOT_LEFT)) {
    Log.print("I2S init failed. lastError=");
    Log.println(i2s.lastError());
    while (true) {
      delay(1000);
    }
  }

  Log.println("I2S initialized.");
}

void loop() {
  const size_t requestedBytes = sizeof(samples);
  const size_t bytesRead = i2s.readBytes(reinterpret_cast<char *>(samples), requestedBytes);
  const size_t count = bytesRead / sizeof(samples[0]);

  if (count == 0) {
    Log.println("No I2S samples read.");
    delay(500);
    return;
  }

  int64_t sumSquares = 0;
  int32_t peak = 0;
  int64_t dcSum = 0;

  for (size_t i = 0; i < count; i++) {
    // INMP441 gives useful audio in the upper bits of the 32-bit sample.
    const int32_t sample = samples[i] >> 14;
    const int32_t magnitude = abs(sample);
    dcSum += sample;
    sumSquares += static_cast<int64_t>(sample) * sample;
    if (magnitude > peak) {
      peak = magnitude;
    }
  }

  const float rms = sqrt(static_cast<float>(sumSquares) / static_cast<float>(count));
  const int32_t dc = static_cast<int32_t>(dcSum / static_cast<int64_t>(count));
  const int bars = constrain(static_cast<int>(rms / 80.0f), 0, 40);

  Log.print("samples=");
  Log.print(count);
  Log.print(" rms=");
  Log.print(rms, 1);
  Log.print(" peak=");
  Log.print(peak);
  Log.print(" dc=");
  Log.print(dc);
  Log.print(" |");
  for (int i = 0; i < bars; i++) {
    Log.print('#');
  }
  Log.println();

  delay(200);
}
