# 🤖 Arduino AI 具體應用範例集

> **搭配文件**：`arduino_ai_trend_report.md`  
> **適用平台**：Arduino Nano 33 BLE Sense / Nicla Vision / ESP32-S3

本文件提供三個完整的 Arduino + AI 實作範例，包含**程式碼** 、**開發流程**與**硬體接線**。

---

## 範例一：IMU 手勢辨識（TensorFlow Lite Micro）

### 📖 說明

利用 Arduino Nano 33 BLE Sense 內建的 **9 軸 IMU（加速度計 + 陀螺儀）**，收集「出拳 Punch」與「彎曲 Flex」兩種動作數據，在 Google Colab 上訓練神經網路模型後，部署回 Arduino 進行**即時手勢推論**。

### 🔧 硬體

- Arduino Nano 33 BLE Sense（內建 LSM9DS1 IMU）
- Micro USB 傳輸線

### 📦 所需函式庫

- `Arduino_LSM9DS1`（IMU 驅動）
- `Arduino_TensorFlowLite`（TFLite Micro 推論引擎）

### 🔄 開發流程

```
┌──────────────┐    ┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│ Step 1       │    │ Step 2       │    │ Step 3       │    │ Step 4       │
│ 收集 IMU 數據 │───►│ Colab 訓練   │───►│ 轉換為 .h    │───►│ 部署推論     │
│ (CSV 輸出)   │    │ 神經網路模型  │    │ C 陣列檔     │    │ (即時分類)   │
└──────────────┘    └──────────────┘    └──────────────┘    └──────────────┘
```

### 💻 程式碼 Step 1：資料收集（IMU_Capture.ino）

```cpp
/*
 * IMU 資料收集程式
 * 偵測到動作（加速度 > 門檻值）後，記錄 119 筆 IMU 數據輸出為 CSV
 * 將 Serial Monitor 的輸出複製貼上為 punch.csv / flex.csv
 */
#include <Arduino_LSM9DS1.h>

const float ACCELERATION_THRESHOLD = 2.5; // 觸發門檻 (G)
const int   NUM_SAMPLES = 119;            // 每次記錄的取樣數
int         samplesRead = NUM_SAMPLES;

void setup() {
  Serial.begin(9600);
  while (!Serial);

  if (!IMU.begin()) {
    Serial.println("IMU 初始化失敗！");
    while (1);
  }

  // 印出 CSV 表頭
  Serial.println("aX,aY,aZ,gX,gY,gZ");
}

void loop() {
  float aX, aY, aZ, gX, gY, gZ;

  // 等待顯著動作觸發
  while (samplesRead == NUM_SAMPLES) {
    if (IMU.accelerationAvailable()) {
      IMU.readAcceleration(aX, aY, aZ);

      float aSum = fabs(aX) + fabs(aY) + fabs(aZ);
      if (aSum >= ACCELERATION_THRESHOLD) {
        samplesRead = 0;
        break;
      }
    }
  }

  // 記錄一組完整動作數據
  while (samplesRead < NUM_SAMPLES) {
    if (IMU.accelerationAvailable() && IMU.gyroscopeAvailable()) {
      IMU.readAcceleration(aX, aY, aZ);
      IMU.readGyroscope(gX, gY, gZ);

      // 正規化到 0~1 範圍
      Serial.print(aX + 4.0, 3); Serial.print(',');
      Serial.print(aY + 4.0, 3); Serial.print(',');
      Serial.print(aZ + 4.0, 3); Serial.print(',');
      Serial.print(gX + 2000.0, 3); Serial.print(',');
      Serial.print(gY + 2000.0, 3); Serial.print(',');
      Serial.print(gZ + 2000.0, 3); Serial.println();

      samplesRead++;

      if (samplesRead == NUM_SAMPLES) {
        Serial.println(); // 空行分隔
      }
    }
  }
}
```

### 💻 程式碼 Step 4：即時推論（IMU_Classifier.ino）

```cpp
/*
 * TensorFlow Lite Micro 手勢分類推論
 * 使用訓練好的模型即時辨識 Punch / Flex 手勢
 */
#include <Arduino_LSM9DS1.h>
#include <TensorFlowLite.h>
#include <tensorflow/lite/micro/all_ops_resolver.h>
#include <tensorflow/lite/micro/micro_interpreter.h>
#include <tensorflow/lite/schema/schema_generated.h>

// 引入訓練好的模型（由 Colab 產出的 C 陣列）
#include "model.h"

// TFLite Micro 記憶體
constexpr int       kTensorArenaSize = 8 * 1024;
uint8_t             tensorArena[kTensorArenaSize];

// 手勢名稱（須與訓練時一致）
const char* GESTURES[] = { "punch", "flex" };
#define NUM_GESTURES 2

const float ACCELERATION_THRESHOLD = 2.5;
const int   NUM_SAMPLES = 119;
const int   NUM_AXES    = 6;  // aX, aY, aZ, gX, gY, gZ
int         samplesRead = NUM_SAMPLES;

// TFLite 物件
tflite::AllOpsResolver        resolver;
const tflite::Model*          model = nullptr;
tflite::MicroInterpreter*     interpreter = nullptr;
TfLiteTensor*                 inputTensor = nullptr;
TfLiteTensor*                 outputTensor = nullptr;

void setup() {
  Serial.begin(9600);
  while (!Serial);

  if (!IMU.begin()) {
    Serial.println("IMU 初始化失敗！");
    while (1);
  }

  // 載入模型
  model = tflite::GetModel(g_model);  // g_model 來自 model.h
  if (model->version() != TFLITE_SCHEMA_VERSION) {
    Serial.println("模型版本不符！");
    while (1);
  }

  // 建立推論器
  static tflite::MicroInterpreter static_interpreter(
    model, resolver, tensorArena, kTensorArenaSize);
  interpreter = &static_interpreter;
  interpreter->AllocateTensors();

  inputTensor  = interpreter->input(0);
  outputTensor = interpreter->output(0);

  Serial.println("=== TinyML 手勢辨識系統就緒 ===");
  Serial.println("請執行 Punch 或 Flex 動作...");
}

void loop() {
  float aX, aY, aZ, gX, gY, gZ;

  // 等待動作觸發
  while (samplesRead == NUM_SAMPLES) {
    if (IMU.accelerationAvailable()) {
      IMU.readAcceleration(aX, aY, aZ);
      if (fabs(aX) + fabs(aY) + fabs(aZ) >= ACCELERATION_THRESHOLD) {
        samplesRead = 0;
        break;
      }
    }
  }

  // 收集一組數據並寫入模型輸入張量
  while (samplesRead < NUM_SAMPLES) {
    if (IMU.accelerationAvailable() && IMU.gyroscopeAvailable()) {
      IMU.readAcceleration(aX, aY, aZ);
      IMU.readGyroscope(gX, gY, gZ);

      // 正規化後寫入輸入張量
      inputTensor->data.f[samplesRead * NUM_AXES + 0] = (aX + 4.0) / 8.0;
      inputTensor->data.f[samplesRead * NUM_AXES + 1] = (aY + 4.0) / 8.0;
      inputTensor->data.f[samplesRead * NUM_AXES + 2] = (aZ + 4.0) / 8.0;
      inputTensor->data.f[samplesRead * NUM_AXES + 3] = (gX + 2000.0) / 4000.0;
      inputTensor->data.f[samplesRead * NUM_AXES + 4] = (gY + 2000.0) / 4000.0;
      inputTensor->data.f[samplesRead * NUM_AXES + 5] = (gZ + 2000.0) / 4000.0;

      samplesRead++;

      if (samplesRead == NUM_SAMPLES) {
        // ===== 執行推論 =====
        TfLiteStatus invokeStatus = interpreter->Invoke();
        if (invokeStatus != kTfLiteOk) {
          Serial.println("推論失敗！");
          return;
        }

        // 輸出各手勢的信心指數
        Serial.println("--- 辨識結果 ---");
        for (int i = 0; i < NUM_GESTURES; i++) {
          Serial.print("  ");
          Serial.print(GESTURES[i]);
          Serial.print(": ");
          Serial.print(outputTensor->data.f[i] * 100, 1);
          Serial.println("%");
        }
        Serial.println();
      }
    }
  }
}
```

---

## 範例二：語音關鍵字辨識（Edge Impulse）

### 📖 說明

使用 Arduino Nano 33 BLE Sense 的內建 **MEMS 麥克風**，透過 **Edge Impulse** 平台收集語音樣本、訓練分類模型，讓 Arduino 能在裝置端辨識特定關鍵字（如 "yes"、"no"、"stop"）。

### 🔧 硬體

- Arduino Nano 33 BLE Sense（內建 MP34DT05 MEMS 麥克風）
- Micro USB 傳輸線

### 🔄 開發流程

```
┌───────────────┐    ┌───────────────┐    ┌───────────────┐    ┌───────────────┐
│ Step 1        │    │ Step 2        │    │ Step 3        │    │ Step 4        │
│ Edge Impulse  │───►│ 收集語音樣本   │───►│ 設計 Impulse  │───►│ 訓練模型      │
│ 建立專案      │    │ (每字 ~1 分鐘) │    │ MFCC + NN     │    │              │
└───────────────┘    └───────────────┘    └───────────────┘    └───────┬───────┘
                                                                       │
┌───────────────┐    ┌───────────────┐    ┌───────────────┐            │
│ Step 7        │    │ Step 6        │    │ Step 5        │◄───────────┘
│ 即時語音辨識   │◄───│ 上傳至 Arduino │◄───│ 匯出為        │
│ + 控制動作     │    │ (Arduino IDE) │    │ Arduino Library│
└───────────────┘    └───────────────┘    └───────────────┘
```

### 📐 MFCC 語音特徵擷取原理

```
原始音頻波形                  MFCC 頻譜特徵圖
                              (輸入神經網路)
 ╔══════════╗                ┌──────────────┐
 ║ ~~~∿∿~~ ║  ──► 預加重    │ ████  ██     │
 ║ ~∿~~~∿~ ║  ──► 分幀      │ ██ ████ ██   │
 ║ ∿~~∿~~∿ ║  ──► 加窗      │  ██  ██ ████ │
 ╚══════════╝  ──► FFT      │ ████ ██  ██  │
                ──► Mel 濾波  │  ██ ████ ██  │
                ──► 取對數    └──────────────┘
                ──► DCT        13 x T 特徵矩陣
```

### 💻 程式碼：Edge Impulse 部署後的推論範例

```cpp
/*
 * Edge Impulse 語音關鍵字辨識
 * 此程式需搭配 Edge Impulse 匯出的 Arduino Library 使用
 * 安裝方式：Sketch > Include Library > Add .ZIP Library
 */

// Edge Impulse 自動產生的標頭檔（名稱依專案而異）
#include <your_edge_impulse_project_inferencing.h>

// 音頻緩衝區
typedef struct {
    int16_t *buffer;
    uint32_t buf_count;
    uint32_t n_samples;
} inference_t;

static inference_t inference;
static bool record_ready = false;
static bool debug_nn = false;

// LED 腳位（用於展示關鍵字觸發動作）
#define LED_RED     22    // Nano 33 BLE 內建
#define LED_GREEN   23
#define LED_BLUE    24

void setup() {
    Serial.begin(115200);
    while (!Serial);

    Serial.println("=== Edge Impulse 語音辨識系統 ===");
    Serial.println("關鍵字: yes / no / stop");

    // 初始化 LED
    pinMode(LED_RED,   OUTPUT);
    pinMode(LED_GREEN, OUTPUT);
    pinMode(LED_BLUE,  OUTPUT);
    allLEDsOff();

    // 初始化推論引擎（Edge Impulse 自動產生的函式）
    if (microphone_inference_start(EI_CLASSIFIER_SLICE_SIZE) == false) {
        Serial.println("麥克風初始化失敗！");
        return;
    }

    Serial.println("系統就緒，開始聆聽...\n");
}

void loop() {
    // 等待音頻資料就緒
    bool m = microphone_inference_record();
    if (!m) {
        Serial.println("錄音失敗！");
        return;
    }

    // 建立推論訊號
    signal_t signal;
    signal.total_length = EI_CLASSIFIER_SLICE_SIZE;
    signal.get_data = &microphone_audio_signal_get_data;

    // ===== 執行推論 =====
    ei_impulse_result_t result = { 0 };
    EI_IMPULSE_ERROR r = run_classifier_continuous(&signal, &result,
                                                    debug_nn);
    if (r != EI_IMPULSE_OK) {
        Serial.print("推論錯誤: ");
        Serial.println(r);
        return;
    }

    // 輸出辨識結果
    for (size_t ix = 0; ix < EI_CLASSIFIER_LABEL_COUNT; ix++) {
        float confidence = result.classification[ix].value;

        // 信心指數 > 80% 時觸發動作
        if (confidence > 0.8) {
            String label = result.classification[ix].label;
            Serial.print(">>> 偵測到: ");
            Serial.print(label);
            Serial.print(" (");
            Serial.print(confidence * 100, 1);
            Serial.println("%)");

            // 根據關鍵字執行不同動作
            if (label == "yes") {
                flashLED(LED_GREEN, 3);   // 綠燈閃 3 次
            } else if (label == "no") {
                flashLED(LED_RED, 3);     // 紅燈閃 3 次
            } else if (label == "stop") {
                flashLED(LED_BLUE, 5);    // 藍燈閃 5 次
            }
        }
    }
}

// LED 控制輔助函式
void allLEDsOff() {
    digitalWrite(LED_RED,   HIGH);  // Nano 33 BLE LED 低電位亮
    digitalWrite(LED_GREEN, HIGH);
    digitalWrite(LED_BLUE,  HIGH);
}

void flashLED(int pin, int times) {
    for (int i = 0; i < times; i++) {
        digitalWrite(pin, LOW);   // 亮
        delay(150);
        digitalWrite(pin, HIGH);  // 滅
        delay(150);
    }
}
```

---

## 範例三：即時影像物件偵測（Nicla Vision + FOMO）

### 📖 說明

使用 Arduino **Nicla Vision** 內建的 200 萬畫素相機，搭配 Edge Impulse 的 **FOMO（Faster Objects, More Objects）** 輕量化物件偵測演算法，在裝置端即時偵測特定物體（如蘋果、杯子、鑰匙等）。

### 🔧 硬體

- Arduino Nicla Vision（STM32H747 雙核 + 2MP 相機）
- Micro USB 傳輸線

### 🔄 開發流程

```
┌───────────────┐    ┌───────────────┐    ┌───────────────┐
│ Step 1        │    │ Step 2        │    │ Step 3        │
│ OpenMV IDE    │───►│ Dataset Editor│───►│ Edge Impulse  │
│ 連接 Nicla    │    │ 拍攝訓練照片  │    │ 標註 BBox     │
└───────────────┘    └───────────────┘    └──────┬────────┘
                                                  │
┌───────────────┐    ┌───────────────┐            │
│ Step 5        │    │ Step 4        │◄───────────┘
│ 即時物件偵測   │◄───│ 部署為 OpenMV │
│ + 框選顯示     │    │ Library       │
└───────────────┘    └───────────────┘
```

### 📐 FOMO vs 傳統 YOLO 比較

```
┌──────────────┬──────────────────┬──────────────────┐
│              │ YOLO (傳統)       │ FOMO (TinyML)    │
├──────────────┼──────────────────┼──────────────────┤
│ 模型大小     │ 數 MB ~ 數十 MB   │ 30 KB ~ 200 KB   │
│ 推論時間     │ 數百 ms (GPU)     │ ~100 ms (MCU)    │
│ 記憶體需求   │ >1 GB             │ <256 KB          │
│ 輸出         │ 精確 BBox         │ 中心點 + 類別     │
│ 適合平台     │ GPU / 高階 SoC    │ Cortex-M / MCU   │
│ 物件重疊     │ 支援              │ 不支援            │
└──────────────┴──────────────────┴──────────────────┘
```

### 💻 程式碼：Nicla Vision 物件偵測（MicroPython）

```python
# ============================================================
#  Nicla Vision + FOMO 物件偵測
#  使用 OpenMV IDE 上傳執行
#  需先從 Edge Impulse 部署 trained.tflite + labels.txt
# ============================================================

import sensor, image, time, os, tf, math, uos, gc

# ==================== 相機初始化 ====================
sensor.reset()
sensor.set_pixformat(sensor.RGB565)    # RGB 色彩
sensor.set_framesize(sensor.QVGA)      # 320x240
sensor.set_windowing((240, 240))       # 裁切為正方形
sensor.skip_frames(time=2000)          # 等待相機穩定

# ==================== 載入模型與標籤 ====================
net = None
labels = None

try:
    labels = [line.rstrip('\n') for line in open("labels.txt")]
    net = tf.load("trained.tflite",
                  load_to_fb=uos.stat('trained.tflite')[6] > (gc.mem_free() - (64*1024)))
except Exception as e:
    print("模型載入錯誤:", e)
    raise(e)

print("標籤:", labels)

# ==================== 色彩定義 (用於框選不同物件) ====================
colors = [
    (255,   0,   0),   # 紅色 - 類別 1
    (  0, 255,   0),   # 綠色 - 類別 2
    (  0,   0, 255),   # 藍色 - 類別 3
    (255, 255,   0),   # 黃色 - 類別 4
    (255,   0, 255),   # 紫色 - 類別 5
]

clock = time.clock()

# ==================== 主迴圈：即時物件偵測 ====================
while True:
    clock.tick()
    img = sensor.snapshot()

    # FOMO 推論：偵測物件中心點
    for i, detection_list in enumerate(net.classify(img,
                                       min_scale=1.0,
                                       scale_mul=0.8,
                                       x_overlap=0.0,
                                       y_overlap=0.0)):
        if i == 0:
            continue  # 跳過背景類別

        # 信心指數 > 60% 才標記
        if len(detection_list) == 0:
            continue

        for d in detection_list:
            # 取得偵測區域
            [x, y, w, h] = d.rect()
            center_x = x + w // 2
            center_y = y + h // 2

            # 畫圓標記偵測位置
            color = colors[i % len(colors)]
            img.draw_circle((center_x, center_y, 12),
                           color=color,
                           thickness=2,
                           fill=False)

            # 標註類別名稱
            img.draw_string(center_x - 20, center_y - 20,
                           labels[i],
                           color=color,
                           scale=1,
                           mono_space=False)

            print("偵測到: %s  位置: (%d, %d)  信心: %.1f%%" %
                  (labels[i], center_x, center_y,
                   d.output() * 100))

    # 左上角顯示 FPS
    img.draw_string(5, 5,
                   "FPS: %.1f" % clock.fps(),
                   color=(255, 255, 255),
                   scale=1)
```

---

## 範例四：振動異常偵測（工業預測性維護）

### 📖 說明

使用 Arduino Nano 33 BLE Sense 的 **加速度計**，監測馬達或機械設備的振動模式。透過 **自編碼器（Autoencoder）** 神經網路學習「正常」振動模式，當偵測到異常振動時發出警報。這是典型的**工業 4.0 預測性維護**應用。

### 🔧 硬體

- Arduino Nano 33 BLE Sense
- LED 紅/綠（外接或使用內建）
- 蜂鳴器（警報用）
- 固定夾（將 Arduino 固定在被監測設備上）

### 💻 程式碼：振動異常偵測

```cpp
/*
 * 工業震動異常偵測系統
 * 使用 TFLite Micro Autoencoder 模型
 *
 * 原理：Autoencoder 訓練時只看「正常」資料，
 * 當輸入異常振動時，重建誤差（MSE）會升高，超過閾值即判定異常。
 */
#include <Arduino_LSM9DS1.h>
#include <TensorFlowLite.h>
#include <tensorflow/lite/micro/all_ops_resolver.h>
#include <tensorflow/lite/micro/micro_interpreter.h>
#include <tensorflow/lite/schema/schema_generated.h>

#include "anomaly_model.h"  // 訓練好的 Autoencoder 模型

// TFLite 設定
constexpr int kTensorArenaSize = 4 * 1024;
uint8_t tensorArena[kTensorArenaSize];

tflite::AllOpsResolver        resolver;
const tflite::Model*          model = nullptr;
tflite::MicroInterpreter*     interpreter = nullptr;
TfLiteTensor*                 input = nullptr;
TfLiteTensor*                 output = nullptr;

// 系統參數
#define SAMPLE_SIZE   64          // 輸入特徵維度
#define BUZZER_PIN    3
#define LED_NORMAL    4           // 綠 LED
#define LED_ALARM     5           // 紅 LED
#define ANOMALY_THRESHOLD  0.05   // MSE 異常閾值（需根據實際調整）

float inputBuffer[SAMPLE_SIZE];
int   sampleIndex = 0;

// 狀態追蹤
enum SystemState { NORMAL, WARNING, ALARM };
SystemState state = NORMAL;
int anomalyCount = 0;

void setup() {
    Serial.begin(115200);
    while (!Serial);

    // GPIO
    pinMode(BUZZER_PIN, OUTPUT);
    pinMode(LED_NORMAL, OUTPUT);
    pinMode(LED_ALARM,  OUTPUT);
    digitalWrite(LED_NORMAL, HIGH);  // 預設綠燈
    digitalWrite(LED_ALARM,  LOW);

    // IMU
    if (!IMU.begin()) {
        Serial.println("IMU 初始化失敗！");
        while (1);
    }

    // 載入 Autoencoder 模型
    model = tflite::GetModel(g_anomaly_model);
    static tflite::MicroInterpreter static_interpreter(
        model, resolver, tensorArena, kTensorArenaSize);
    interpreter = &static_interpreter;
    interpreter->AllocateTensors();
    input  = interpreter->input(0);
    output = interpreter->output(0);

    Serial.println("=== 工業振動異常偵測系統 ===");
    Serial.println("監測中...\n");
}

void loop() {
    float aX, aY, aZ;

    // 收集振動數據
    if (IMU.accelerationAvailable()) {
        IMU.readAcceleration(aX, aY, aZ);

        // 取振動強度的向量和
        float magnitude = sqrt(aX*aX + aY*aY + aZ*aZ);
        inputBuffer[sampleIndex++] = magnitude;

        // 收滿一組數據後進行推論
        if (sampleIndex >= SAMPLE_SIZE) {
            sampleIndex = 0;

            // 寫入模型輸入
            for (int i = 0; i < SAMPLE_SIZE; i++) {
                input->data.f[i] = inputBuffer[i];
            }

            // 執行推論
            interpreter->Invoke();

            // 計算重建誤差 (MSE)
            float mse = 0.0;
            for (int i = 0; i < SAMPLE_SIZE; i++) {
                float diff = inputBuffer[i] - output->data.f[i];
                mse += diff * diff;
            }
            mse /= SAMPLE_SIZE;

            // 判定狀態
            if (mse < ANOMALY_THRESHOLD) {
                state = NORMAL;
                anomalyCount = 0;
                digitalWrite(LED_NORMAL, HIGH);
                digitalWrite(LED_ALARM,  LOW);
                noTone(BUZZER_PIN);
            } else {
                anomalyCount++;
                if (anomalyCount >= 3) {
                    state = ALARM;
                    digitalWrite(LED_NORMAL, LOW);
                    digitalWrite(LED_ALARM,  HIGH);
                    tone(BUZZER_PIN, 2000);
                    Serial.println("!!! 警報：偵測到持續異常振動 !!!");
                } else {
                    state = WARNING;
                    Serial.println(">>> 警告：偵測到異常振動模式");
                }
            }

            // 輸出監測數據
            Serial.print("MSE: ");
            Serial.print(mse, 6);
            Serial.print("  閾值: ");
            Serial.print(ANOMALY_THRESHOLD, 6);
            Serial.print("  狀態: ");
            switch (state) {
                case NORMAL:  Serial.println("正常 ✓"); break;
                case WARNING: Serial.println("警告 ⚠"); break;
                case ALARM:   Serial.println("警報 ✕"); break;
            }
        }
    }

    delay(10); // ~100 Hz 取樣率
}
```

---

## 範例五：ESP32-S3 AI 攝影機 — 智慧門鈴（臉部偵測）

### 📖 說明

使用 **ESP32-S3 AI Camera** 模組，結合內建相機與 WiFi，實作一個能偵測人臉並拍照上傳的**智慧門鈴**系統。偵測到人臉時自動拍照、發送通知。

### 🔧 硬體

- ESP32-S3 AI Camera 模組（如 DFRobot FireBeetle 2）
- 按鈕（門鈴按鍵）
- 蜂鳴器
- LED 指示燈

### 💻 程式碼：ESP32-S3 人臉偵測

```cpp
/*
 * ESP32-S3 智慧門鈴 - 人臉偵測版
 * 使用 ESP-WHO 人臉偵測功能
 */
#include "esp_camera.h"
#include "esp_http_server.h"
#include <WiFi.h>

// WiFi 設定
const char* ssid     = "YOUR_WIFI_SSID";
const char* password = "YOUR_WIFI_PASS";

// 相機腳位（依模組不同調整）
#define PWDN_GPIO_NUM    -1
#define RESET_GPIO_NUM   -1
#define XCLK_GPIO_NUM    15
#define SIOD_GPIO_NUM    4
#define SIOC_GPIO_NUM    5
#define Y9_GPIO_NUM      16
#define Y8_GPIO_NUM      17
#define Y7_GPIO_NUM      18
#define Y6_GPIO_NUM      12
#define Y5_GPIO_NUM      10
#define Y4_GPIO_NUM      8
#define Y3_GPIO_NUM      9
#define Y2_GPIO_NUM      11
#define VSYNC_GPIO_NUM   6
#define HREF_GPIO_NUM    7
#define PCLK_GPIO_NUM    13

#define DOORBELL_PIN    2     // 門鈴按鈕
#define BUZZER_PIN      3     // 蜂鳴器
#define LED_PIN         14    // LED 指示

bool faceDetected = false;
int  faceCount = 0;

void setup() {
    Serial.begin(115200);
    Serial.println("=== ESP32-S3 智慧門鈴系統 ===");

    // GPIO
    pinMode(DOORBELL_PIN, INPUT_PULLUP);
    pinMode(BUZZER_PIN, OUTPUT);
    pinMode(LED_PIN, OUTPUT);

    // 相機初始化
    camera_config_t config;
    config.ledc_channel = LEDC_CHANNEL_0;
    config.ledc_timer   = LEDC_TIMER_0;
    config.pin_d0       = Y2_GPIO_NUM;
    config.pin_d1       = Y3_GPIO_NUM;
    config.pin_d2       = Y4_GPIO_NUM;
    config.pin_d3       = Y5_GPIO_NUM;
    config.pin_d4       = Y6_GPIO_NUM;
    config.pin_d5       = Y7_GPIO_NUM;
    config.pin_d6       = Y8_GPIO_NUM;
    config.pin_d7       = Y9_GPIO_NUM;
    config.pin_xclk     = XCLK_GPIO_NUM;
    config.pin_pclk     = PCLK_GPIO_NUM;
    config.pin_vsync    = VSYNC_GPIO_NUM;
    config.pin_href     = HREF_GPIO_NUM;
    config.pin_sccb_sda = SIOD_GPIO_NUM;
    config.pin_sccb_scl = SIOC_GPIO_NUM;
    config.pin_pwdn     = PWDN_GPIO_NUM;
    config.pin_reset    = RESET_GPIO_NUM;
    config.xclk_freq_hz = 20000000;
    config.pixel_format = PIXFORMAT_JPEG;
    config.frame_size   = FRAMESIZE_QVGA;  // 320x240
    config.jpeg_quality = 12;
    config.fb_count     = 1;
    config.grab_mode    = CAMERA_GRAB_WHEN_EMPTY;

    esp_err_t err = esp_camera_init(&config);
    if (err != ESP_OK) {
        Serial.printf("相機初始化失敗: 0x%x\n", err);
        return;
    }
    Serial.println("相機初始化成功！");

    // WiFi 連線
    WiFi.begin(ssid, password);
    Serial.print("連接 WiFi");
    while (WiFi.status() != WL_CONNECTED) {
        delay(500);
        Serial.print(".");
    }
    Serial.println();
    Serial.print("WiFi 已連線！IP: ");
    Serial.println(WiFi.localIP());

    Serial.println("\n系統就緒，等待訪客...");
}

void loop() {
    // 偵測門鈴按鈕
    if (digitalRead(DOORBELL_PIN) == LOW) {
        Serial.println(">>> 門鈴響了！<<<");
        tone(BUZZER_PIN, 1500, 500);
        delay(200);
        tone(BUZZER_PIN, 2000, 500);

        captureAndAnalyze();
        delay(3000);  // 防止重複觸發
    }

    // 定時人臉偵測（每 2 秒掃描一次）
    static unsigned long lastScan = 0;
    if (millis() - lastScan >= 2000) {
        lastScan = millis();
        scanForFaces();
    }
}

void captureAndAnalyze() {
    // 拍照
    camera_fb_t* fb = esp_camera_fb_get();
    if (!fb) {
        Serial.println("拍照失敗！");
        return;
    }

    Serial.printf("已拍攝照片: %d x %d, 大小: %d bytes\n",
                  fb->width, fb->height, fb->len);

    // 閃爍 LED 表示拍照成功
    for (int i = 0; i < 3; i++) {
        digitalWrite(LED_PIN, HIGH);
        delay(100);
        digitalWrite(LED_PIN, LOW);
        delay(100);
    }

    // 此處可加入：
    // 1. HTTP POST 將影像發送至伺服器
    // 2. 透過 LINE Notify / Telegram Bot 推播通知
    // 3. 存入 SD 卡

    esp_camera_fb_return(fb);
}

void scanForFaces() {
    camera_fb_t* fb = esp_camera_fb_get();
    if (!fb) return;

    // ESP-WHO 人臉偵測 API (需安裝 ESP-WHO 元件)
    // 這裡展示概念流程，實際需根據 ESP-WHO 版本調整
    //
    // face_detection_result_t result;
    // bool detected = face_detect(fb, &result);
    //
    // if (detected) {
    //     faceCount++;
    //     Serial.printf("偵測到 %d 張人臉！\n", result.num_faces);
    //     captureAndAnalyze();
    // }

    // 以下為簡化的示範輸出
    Serial.print(".");  // 掃描中指示

    esp_camera_fb_return(fb);
}
```

---

## ⚡ 快速對照表：哪個範例適合哪種學習目標？

| 範例 | AI 技術 | 通訊協定 | 感測器 | 適合學習 |
|------|--------|---------|--------|---------|
| 手勢辨識 | TFLite Micro (分類) | — | IMU 加速度+陀螺儀 | 神經網路推論基礎 |
| 語音辨識 | Edge Impulse (MFCC+NN) | — | MEMS 麥克風 | 語音特徵擷取、模型部署 |
| 影像偵測 | FOMO 物件偵測 | I2C | 2MP 相機 | 輕量化影像 AI |
| 振動異常 | Autoencoder 異常偵測 | — | 加速度計 | 工業 4.0、非監督學習 |
| 智慧門鈴 | ESP-WHO 人臉偵測 | WiFi | 相機 | IoT + AI 整合 |

---

## 📚 參考資源

- [Arduino TensorFlow Lite 官方教學](https://docs.arduino.cc/tutorials/nano-33-ble-sense/get-started-with-machine-learning/)
- [Edge Impulse 官方文件](https://docs.edgeimpulse.com/)
- [OpenMV + Nicla Vision 教學](https://docs.arduino.cc/tutorials/nicla-vision/image-classification/)
- [FOMO 物件偵測論文](https://arxiv.org/abs/2206.07994)
- [ESP-WHO 人臉偵測](https://github.com/espressif/esp-who)
- [GitHub: gesture-tinyml](https://github.com/devnithw/gesture-tinyml)
