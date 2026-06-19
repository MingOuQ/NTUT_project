# 基於機器視覺與光電感測之表面瑕疵智慧檢測系統

## 目標

建立一套 Micro LED 螢幕表面瑕疵檢測系統：
- 用 R/G/B LED 分別照射自製 RGB 紙板（模擬 LCD 螢幕）
- ESP32-CAM 拍攝影像，透過 **USB 數據線（Serial）** 傳至 PC
- PC 端 Python + YOLOv8 AI 辨識瑕疵位置座標與類型
- 結果回傳 ESP32S，OLED 顯示 + 蜂鳴器警示
- 先做單面板檢測，成功後擴展至 3×3 拼接面板

## 系統架構

```
ESP32S (控制 R/G/B LED 光源)
    ↓ [UART 連接]
ESP32-CAM (拍攝影像)
    ↓ [USB Serial 傳至 PC]
PC Python (接收影像 → YOLOv8 AI 瑕疵辨識)
    ↓ [USB Serial 回傳結果]
ESP32S (OLED 顯示瑕疵座標+類型 + 蜂鳴器警示)
```

> [!IMPORTANT]
> **通訊方式**：全部使用 USB Serial（數據線），不使用 WiFi。
> - ESP32-CAM 透過 USB Serial 將影像傳至 PC
> - PC 透過另一條 USB Serial 將結果傳至 ESP32S
> - ESP32S 與 ESP32-CAM 之間透過 UART（硬體串口）通訊

## User Review Required

> [!WARNING]
> **接線方式確認**：本方案需要 **兩條 USB 線** 分別連接 ESP32-CAM 和 ESP32S 到 PC。
> ESP32S 與 ESP32-CAM 之間使用 UART 連接（TX/RX 交叉接線）。
> 如果你只有一條 USB 線，可以改成只用 ESP32-CAM（它本身也是 ESP32），一個板子完成所有功能。請確認你的硬體方案。

> [!IMPORTANT]
> **AI 模型**：初期使用 OpenCV 傳統影像處理（顏色閾值 + 輪廓偵測）快速驗證，後期可升級至 YOLOv8。
> 這樣不需要訓練資料集就能先跑起來，確認硬體串接正常後再進階。

---

## Proposed Changes

### Component 1: ESP32-CAM 韌體

負責拍攝影像並透過 Serial 傳送至 PC。

#### [NEW] [esp32_cam_capture.ino](file:///c:/Users/user/Desktop/final/arduino_projects/project6_defect_detection/esp32_cam/esp32_cam_capture.ino)

功能：
- 初始化 OV2640 相機（設定解析度 QVGA/VGA）
- 接收 ESP32S 的 UART 指令（如 `CAPTURE_RED`, `CAPTURE_GREEN`, `CAPTURE_BLUE`）
- 拍攝影像後，透過 USB Serial 以 Base64 編碼傳送至 PC
- 傳輸協議：`IMG_START:<size>\n` → Base64 影像資料 → `IMG_END\n`

---

### Component 2: ESP32S 主控制器韌體

負責控制 LED 光源、OLED 顯示、蜂鳴器警示。

#### [NEW] [esp32s_controller.ino](file:///c:/Users/user/Desktop/final/arduino_projects/project6_defect_detection/esp32s_controller/esp32s_controller.ino)

功能：
- **LED 光源控制**：PWM 控制 R/G/B 三色 LED 依序照射
- **UART 通訊**：向 ESP32-CAM 發送拍照指令
- **Serial 通訊**：接收 PC 回傳的瑕疵辨識結果
- **OLED 顯示**：SSD1306 I2C OLED 顯示瑕疵座標 (x, y)、類型（劃痕/斷裂/異物等）
- **蜂鳴器警示**：檢測到瑕疵時發出警報音
- **檢測流程控制**：按下按鈕啟動完整檢測序列（紅光→拍照→綠光→拍照→藍光→拍照）

接線規劃：
| ESP32S Pin | 連接元件 | 說明 |
|-----------|---------|------|
| GPIO 25 | 紅光 LED (透過電阻) | PWM 控制紅光亮度 |
| GPIO 26 | 綠光 LED (透過電阻) | PWM 控制綠光亮度 |
| GPIO 27 | 藍光 LED (透過電阻) | PWM 控制藍光亮度 |
| GPIO 16 (RX2) | ESP32-CAM TX | UART 接收 |
| GPIO 17 (TX2) | ESP32-CAM RX | UART 發送 |
| GPIO 21 (SDA) | OLED SDA | I2C 資料線 |
| GPIO 22 (SCL) | OLED SCL | I2C 時脈線 |
| GPIO 4 | 蜂鳴器 | 警報輸出 |
| GPIO 15 | 按鈕 | 啟動檢測 (INPUT_PULLUP) |

---

### Component 3: PC 端 Python AI 處理程式

負責接收影像、執行瑕疵檢測、回傳結果。

#### [NEW] [defect_detector.py](file:///c:/Users/user/Desktop/final/arduino_projects/project6_defect_detection/pc_python/defect_detector.py)

功能：
- 透過 Serial 接收 ESP32-CAM 傳來的影像（Base64 解碼）
- **階段一（OpenCV）**：使用顏色閾值 + 輪廓偵測找出黑色瑕疵線條
- **階段二（YOLOv8）**：訓練自定義模型偵測瑕疵類型
- 計算瑕疵位置座標（像素座標轉換為面板座標）
- 透過 Serial 將結果回傳至 ESP32S
- 結果格式：`DEFECT:<x>,<y>,<type>,<confidence>\n` 或 `NO_DEFECT\n`
- 支援單面板與 3×3 拼接面板模式
- 即時顯示檢測影像（OpenCV 視窗標記瑕疵位置）

#### [NEW] [requirements.txt](file:///c:/Users/user/Desktop/final/arduino_projects/project6_defect_detection/pc_python/requirements.txt)

Python 依賴：
- `pyserial` — Serial 通訊
- `opencv-python` — 影像處理
- `numpy` — 數值運算
- `ultralytics` — YOLOv8（階段二）

---

### Component 4: 專案文件

#### [NEW] [README.md](file:///c:/Users/user/Desktop/final/arduino_projects/project6_defect_detection/README.md)

包含：
- 系統架構說明
- 硬體接線圖
- 軟體安裝步驟
- 使用說明
- 瑕疵類型定義

---

## 檔案結構

```
project6_defect_detection/
├── README.md                          # 專案說明文件
├── esp32_cam/
│   └── esp32_cam_capture.ino          # ESP32-CAM 拍攝韌體
├── esp32s_controller/
│   └── esp32s_controller.ino          # ESP32S 主控韌體
└── pc_python/
    ├── defect_detector.py             # PC 端 AI 瑕疵檢測
    └── requirements.txt               # Python 依賴
```

---

## Open Questions

> [!IMPORTANT]
> 1. **硬體方案**：你是要用 **兩塊板子**（ESP32S + ESP32-CAM）還是 **只用一塊 ESP32-CAM**（它本身也有 GPIO 可以控制 LED 和 OLED）？
>    - 兩塊板子：功能分離更清楚，但需要兩條 USB 線 + UART 互連
>    - 一塊 ESP32-CAM：接線更簡單，但 GPIO 有限（需仔細規劃腳位）

> [!IMPORTANT]
> 2. **OLED 型號確認**：你手邊的 OLED 顯示器是 SSD1306 0.96" I2C 版本嗎？還是其他型號（如 SH1106 或 LCD 1602）？

> [!NOTE]
> 3. **初期方案建議**：先用 OpenCV 傳統影像處理（不需訓練模型、不需 GPU），確認硬體串接正常後再升級 YOLOv8。你同意這個策略嗎？

---

## Verification Plan

### Automated Tests
1. 分別燒錄 ESP32-CAM 和 ESP32S 韌體，確認編譯成功
2. 執行 PC Python 腳本，驗證 Serial 通訊建立
3. 測試影像拍攝 → 傳輸 → 接收流程
4. 在紙板上畫黑線測試瑕疵檢測效果

### Manual Verification
1. 實際接線並通電測試
2. R/G/B LED 依序照射，觀察 ESP32-CAM 拍攝效果
3. OLED 顯示瑕疵座標與類型
4. 蜂鳴器在檢測到瑕疵時正確觸發
5. 擴展至 3×3 拼接面板測試
