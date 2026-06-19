/*
 * =============================================================
 *  ESP32-CAM 影像擷取韌體
 *  Surface Defect Detection System - Camera Module
 * =============================================================
 *
 *  功能：
 *    1. 初始化 OV2640 相機模組
 *    2. 等待 PC 端透過 USB Serial 發送拍照指令
 *    3. 拍攝 JPEG 影像並透過 USB Serial 傳送至 PC
 *
 *  通訊協議（USB Serial, 115200 baud）：
 *    接收指令：
 *      - "CAPTURE\n"   → 拍攝一張照片並傳送
 *      - "STATUS\n"    → 回報相機狀態
 *      - "SET_RES:X\n" → 設定解析度 (0=QQVGA, 1=QVGA, 2=VGA)
 *
 *    傳送格式：
 *      - "IMG:<size>\n" + <raw JPEG bytes>  → 影像資料
 *      - "CAM_READY\n"   → 相機就緒
 *      - "CAM_ERROR:<msg>\n" → 錯誤訊息
 *
 *  硬體：AI-Thinker ESP32-CAM (OV2640)
 *  注意：GPIO 4 是內建閃光燈，本程式預設關閉
 *
 *  Board 設定：
 *    Arduino IDE → Tools → Board → ESP32 → AI Thinker ESP32-CAM
 * =============================================================
 */

#include "esp_camera.h"

// ==================== AI-Thinker ESP32-CAM 腳位定義 ====================
#define PWDN_GPIO_NUM 32  // 電源控制
#define RESET_GPIO_NUM -1 // 重置（未使用）
#define XCLK_GPIO_NUM 0   // 外部時脈
#define SIOD_GPIO_NUM 26  // SCCB 資料線 (I2C SDA)
#define SIOC_GPIO_NUM 27  // SCCB 時脈線 (I2C SCL)

// 影像資料匯流排 (Y2-Y9)
#define Y9_GPIO_NUM 35
#define Y8_GPIO_NUM 34
#define Y7_GPIO_NUM 39
#define Y6_GPIO_NUM 36
#define Y5_GPIO_NUM 21
#define Y4_GPIO_NUM 19
#define Y3_GPIO_NUM 18
#define Y2_GPIO_NUM 5

// 同步信號
#define VSYNC_GPIO_NUM 25 // 垂直同步
#define HREF_GPIO_NUM 23  // 水平參考
#define PCLK_GPIO_NUM 22  // 像素時脈

// 內建閃光燈
#define FLASH_LED_PIN 4

// ==================== 全域變數 ====================
String inputBuffer = "";  // Serial 輸入緩衝
bool cameraReady = false; // 相機是否就緒

// ==================== 相機初始化 ====================
bool initCamera() {
  camera_config_t config;
  config.ledc_channel = LEDC_CHANNEL_0;
  config.ledc_timer = LEDC_TIMER_0;
  config.pin_d0 = Y2_GPIO_NUM;
  config.pin_d1 = Y3_GPIO_NUM;
  config.pin_d2 = Y4_GPIO_NUM;
  config.pin_d3 = Y5_GPIO_NUM;
  config.pin_d4 = Y6_GPIO_NUM;
  config.pin_d5 = Y7_GPIO_NUM;
  config.pin_d6 = Y8_GPIO_NUM;
  config.pin_d7 = Y9_GPIO_NUM;
  config.pin_xclk = XCLK_GPIO_NUM;
  config.pin_pclk = PCLK_GPIO_NUM;
  config.pin_vsync = VSYNC_GPIO_NUM;
  config.pin_href = HREF_GPIO_NUM;
  config.pin_sccb_sda = SIOD_GPIO_NUM;
  config.pin_sccb_scl = SIOC_GPIO_NUM;
  config.pin_pwdn = PWDN_GPIO_NUM;
  config.pin_reset = RESET_GPIO_NUM;

  config.xclk_freq_hz = 20000000;       // XCLK 20MHz
  config.pixel_format = PIXFORMAT_JPEG; // JPEG 格式

  // 根據 PSRAM 可用性設定解析度
  if (psramFound()) {
    config.frame_size = FRAMESIZE_VGA; // 640x480（有 PSRAM）
    config.jpeg_quality = 10;          // 品質 0-63（越低越好）
    config.fb_count = 2;               // 雙緩衝
    Serial.println("INFO:PSRAM found, using VGA resolution");
  } else {
    config.frame_size = FRAMESIZE_QVGA; // 320x240（無 PSRAM）
    config.jpeg_quality = 12;
    config.fb_count = 1;
    Serial.println("INFO:No PSRAM, using QVGA resolution");
  }

  // 初始化相機
  esp_err_t err = esp_camera_init(&config);
  if (err != ESP_OK) {
    Serial.print("CAM_ERROR:Init failed, code 0x");
    Serial.println(err, HEX);
    return false;
  }

  // 調整相機參數以獲得更好的瑕疵檢測效果
  sensor_t *s = esp_camera_sensor_get();
  if (s != NULL) {
    s->set_brightness(s, 1);    // 亮度稍微提高 (-2 to 2)
    s->set_contrast(s, 1);      // 對比度提高 (-2 to 2)
    s->set_saturation(s, 0);    // 飽和度適中 (-2 to 2)
    s->set_whitebal(s, 1);      // 白平衡開啟
    s->set_awb_gain(s, 1);      // AWB 增益開啟
    s->set_wb_mode(s, 0);       // 白平衡模式：自動
    s->set_exposure_ctrl(s, 1); // 自動曝光
    s->set_aec2(s, 0);          // AEC DSP 關閉（手動控制效果更穩定）
    s->set_gainceiling(s, (gainceiling_t)2); // 增益上限中等
  }

  return true;
}

// ==================== 拍攝並傳送影像 ====================
void captureAndSend() {
  if (!cameraReady) {
    Serial.println("CAM_ERROR:Camera not initialized");
    return;
  }

  // 先丟棄一幀舊影像（確保拿到最新畫面）
  camera_fb_t *fb_old = esp_camera_fb_get();
  if (fb_old) {
    esp_camera_fb_return(fb_old);
  }
  delay(100); // 等待新曝光

  // 拍攝新影像
  camera_fb_t *fb = esp_camera_fb_get();
  if (!fb) {
    Serial.println("CAM_ERROR:Capture failed");
    return;
  }

  // 確認是 JPEG 格式
  if (fb->format != PIXFORMAT_JPEG) {
    Serial.println("CAM_ERROR:Not JPEG format");
    esp_camera_fb_return(fb);
    return;
  }

  // 傳送影像標頭：IMG:<size>\n
  Serial.print("IMG:");
  Serial.println(fb->len);

  // 傳送原始 JPEG 資料
  // 分塊傳送避免緩衝區溢出
  size_t sent = 0;
  const size_t CHUNK_SIZE = 1024;
  while (sent < fb->len) {
    size_t toSend = min(CHUNK_SIZE, fb->len - sent);
    Serial.write(fb->buf + sent, toSend);
    sent += toSend;
    // 小延遲讓 Serial 緩衝區有時間清空
    delayMicroseconds(100);
  }

  // 傳送結束標記
  Serial.println(); // 確保有換行
  Serial.println("IMG_OK");

  // 釋放影像緩衝區
  esp_camera_fb_return(fb);
}

// ==================== 設定解析度 ====================
void setResolution(int res) {
  sensor_t *s = esp_camera_sensor_get();
  if (s == NULL) {
    Serial.println("CAM_ERROR:Sensor not found");
    return;
  }

  switch (res) {
  case 0:
    s->set_framesize(s, FRAMESIZE_QQVGA); // 160x120
    Serial.println("RES_OK:QQVGA(160x120)");
    break;
  case 1:
    s->set_framesize(s, FRAMESIZE_QVGA); // 320x240
    Serial.println("RES_OK:QVGA(320x240)");
    break;
  case 2:
    s->set_framesize(s, FRAMESIZE_VGA); // 640x480
    Serial.println("RES_OK:VGA(640x480)");
    break;
  case 3:
    s->set_framesize(s, FRAMESIZE_SVGA); // 800x600
    Serial.println("RES_OK:SVGA(800x600)");
    break;
  default:
    Serial.println("CAM_ERROR:Invalid resolution (0-3)");
    break;
  }
}

// ==================== 處理 Serial 指令 ====================
void processCommand(String cmd) {
  cmd.trim(); // 移除前後空白與換行

  if (cmd == "CAPTURE") {
    captureAndSend();
  } else if (cmd == "STATUS") {
    if (cameraReady) {
      sensor_t *s = esp_camera_sensor_get();
      Serial.print("STATUS:OK,PID=0x");
      Serial.println(s ? s->id.PID : 0, HEX);
    } else {
      Serial.println("STATUS:NOT_READY");
    }
  } else if (cmd.startsWith("SET_RES:")) {
    int res = cmd.substring(8).toInt();
    setResolution(res);
  } else if (cmd == "PING") {
    Serial.println("PONG"); // 連線測試
  } else {
    Serial.print("CAM_ERROR:Unknown command: ");
    Serial.println(cmd);
  }
}

// ==================== Arduino Setup ====================
void setup() {
  // 初始化 USB Serial（與 PC 通訊）
  Serial.begin(115200);
  Serial.setRxBufferSize(256);
  delay(1000); // 等待 Serial 穩定

  Serial.println();
  Serial.println("================================");
  Serial.println("  ESP32-CAM Defect Detection");
  Serial.println("  Camera Module v1.0");
  Serial.println("================================");

  // 關閉內建閃光燈（避免干擾拍攝）
  pinMode(FLASH_LED_PIN, OUTPUT);
  digitalWrite(FLASH_LED_PIN, LOW);

  // 初始化相機
  Serial.println("INFO:Initializing camera...");
  cameraReady = initCamera();

  if (cameraReady) {
    Serial.println("CAM_READY");
  } else {
    Serial.println("CAM_ERROR:Initialization failed!");
    Serial.println("INFO:Please check camera connection and restart");
  }
}

// ==================== Arduino Loop ====================
void loop() {
  // 讀取 Serial 指令
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n' || c == '\r') {
      if (inputBuffer.length() > 0) {
        processCommand(inputBuffer);
        inputBuffer = "";
      }
    } else {
      inputBuffer += c;
      // 防止緩衝區溢出
      if (inputBuffer.length() > 64) {
        inputBuffer = "";
        Serial.println("CAM_ERROR:Command too long");
      }
    }
  }

  delay(10); // 小延遲減少 CPU 負載
}
