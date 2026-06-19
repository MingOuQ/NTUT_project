# Surface Defect Detection System (表面瑕疵檢測系統)

## 專案大綱
本專案是一個基於 **多光譜影像 (Multi-spectral Imaging)** 與 **邊緣運算 (Edge Computing)** 架構的自動化表面瑕疵檢測系統。
系統透過切換不同顏色的光源（紅、綠、藍）來突顯待測物表面的不同特徵（如刮痕、髒污或凹陷），並由 PC 端的電腦視覺演算法進行自動化辨識。

系統硬體架構分為三個主要節點：
1. **ESP32S 控制節點 (Controller)**：負責控制 RGB 光源切換、觸發檢測按鈕、發出蜂鳴器警報，以及透過 OLED 顯示當前系統狀態。
2. **ESP32-CAM 影像擷取節點**：負責高畫質影像的拍攝，並將 JPEG 二進位資料流傳送給 PC 端。
3. **PC 運算中樞 (Python/YOLOv8)**：協調上述兩個微控制器，執行影像擷取流程，並利用 YOLOv8 深度學習進行精準瑕疵辨識 (或輔以 OpenCV 混合檢測)，最終將結果回饋給控制節點。

---

## 技術棧 (Technology Stack)

### 硬體層 (Hardware)
*   **微控制器**：ESP32 Dev Module, AI-Thinker ESP32-CAM
*   **感測器/輸出**：OV2640 鏡頭模組, 共陰極 RGB LED, 有源/無源蜂鳴器, 0.96吋 I2C OLED (SSD1306)

### 韌體層 (Firmware - C++/Arduino)
*   **框架**：Arduino IDE (ESP32 Core 3.x 核心)
*   **影像處理**：`esp_camera` 框架 (支援 PSRAM)
*   **通訊協議**：USB UART (Baud Rate: 115200) 自定義 ASCII 指令與二進位資料流傳輸
*   **其他驅動與通訊庫**：`Adafruit_GFX`, `Adafruit_SSD1306`, ESP32 `ledc` PWM 控制, `tone()` 頻率控制, **`WiFi`** (無線網路 AP 熱點模式), **`WebSocketsServer`** (極低延遲雙向通訊), **`ESPmDNS`** (區域網域名稱解析)

### 軟體層與行動端 (Software & Mobile Dashboard)
*   **核心語言**：Python 3.x
*   **機器視覺**：`ultralytics` (YOLOv8), `opencv-python` (cv2), `numpy`
*   **資料匯出**：`openpyxl` (自動化產生 Excel 瑕疵報告)
*   **硬體通訊**：`pyserial`
*   **行動端前端**：HTML5, Vanilla CSS (暗黑科技霓虹設計), JavaScript (ES6+), **Web Audio API** (手機音效合成器), **WebSocket Client** (秒級即時更新)
*   **PWA 獨立運行**：支援「新增至主畫面」以全螢幕原生 App 模式運作。

---

## 系統資料流 (Data Flow)
1. **連線與就緒**：
   * ESP32S 開機後自動啟動獨立 Wi-Fi 熱點 `Defect_Detector_WiFi` (IP: `192.168.4.1`)。
   * 手機連上熱點並在瀏覽器輸入 `http://192.168.4.1` 下載網頁 App，並透過 WebSocket (Port 81) 與 ESP32S 保持連線。
2. **檢測啟動**：使用者按下機台實體按鈕，或在 PC 介面按下空白鍵。
3. **光源控制**：PC 透過 Serial 發送 `LED:R` 指令給 ESP32S。此時 ESP32S 會透過 WebSocket 向手機廣播 `SCANNING` 狀態（手機背景同步呈現藍色掃描跑馬燈）。
4. **影像擷取**：PC 發送 `CAPTURE` 給 ESP32-CAM，CAM 回傳 `IMG:<size>` 與二進位 JPEG 資料。
5. **多光譜循環**：重複上述流程完成 R, G, B 三色光譜擷取。
6. **分析**：PC 端使用 YOLOv8 模型對影像進行物件偵測（如 spot, scratch, crack 等），並可彈性切換純 AI 或 OpenCV 混合檢測模式。
7. **結果回報與存檔**：
   * **PC 端**：將瑕疵座標與警報指令 (`RESULT:DEFECT...`) 傳送給 ESP32S，並自動將瑕疵數據匯出為 Excel (`.xlsx`) 報告存放於 `inspection_reports/` 資料夾。
   * **機台端 (OLED)**：OLED 螢幕上立刻顯示檢測到的總瑕疵個數、主要瑕疵類型與詳細座標，同時蜂鳴器發出警報。
   * **手機端 (HTML Dashboard)**：**在一瞬間 (延遲 < 0.05 秒) 收到 WebSocket 推播**，全螢幕霓虹紅光劇烈閃爍警告、響起高頻「嗶-嗶-嗶」合成警報音，並列出詳細的瑕疵分析與歷史日誌。
