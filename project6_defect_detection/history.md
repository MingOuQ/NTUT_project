# 開發與試錯紀錄 (Troubleshooting History)

本文件紀錄了在系統整合與測試過程中所遭遇的各項問題，以及最終的解決方案，作為未來維護或重製系統的重要參考。

---

## 1. 韌體編譯錯誤：ESP32 Core API 變更
*   **問題描述**：編譯 `esp32s_controller.ino` 時出現 `ledcSetup` 與 `ledcAttachPin` 等函式未定義的錯誤。
*   **原因分析**：使用者的 Arduino IDE 安裝了較新的 ESP32 Board Manager (Core 3.0.0 以上版本)，該版本全面棄用了舊版的 LEDC PWM API，改用簡化版的 `ledcAttach()` 與 `ledcWrite()`。
*   **解決方案**：修改原始碼，將舊的 3 步驟 PWM 初始化替換為相容 Core 3.x 的寫法。

## 2. 硬體 I2C 死鎖：未連接 OLED 導致當機
*   **問題描述**：在沒有接上 OLED 螢幕的情況下開機，ESP32S 程式會卡死，完全不回應任何 Serial 指令。
*   **原因分析**：`Adafruit_SSD1306` 的 `begin()` 函式在找不到 I2C 設備時，會進入死迴圈或直接掛起系統。
*   **解決方案**：加入 `hasOLED` 運行時偵測標記。在 `setup()` 時若偵測失敗則將標記設為 `false`，後續所有繪圖與更新畫面相關的函式都先判斷此標記，實現了「有螢幕顯示畫面，沒螢幕依然能正常運作」的熱插拔相容性。

## 3. 蜂鳴器無聲：主動式與被動式硬體差異
*   **問題描述**：發送 `BUZZ:ON` 時，蜂鳴器只會發出微弱的「啵」聲或震動，無法發出連續警報音。
*   **原因分析**：程式原本使用的是 `digitalWrite(HIGH)`（針對內建震盪器的「有源蜂鳴器」），但實際連接的硬體是「無源蜂鳴器 (Passive Buzzer)」，需要 PWM 頻率訊號才能發聲。
*   **解決方案**：將程式中控制蜂鳴器腳位的 `digitalWrite()` 全面替換為 `tone(pin, freq)`，並將一般提示音設定為 2000Hz，警報音設定為 2500Hz。

## 4. 相機拍攝失敗：瞬間電壓驟降 (Brownout) 與記憶體不足
*   **問題描述**：ESP32-CAM 發送 `CAPTURE` 指令後，回傳 `CAM_ERROR:Capture failed`，無法抓取畫面。
*   **原因分析**：ESP32-CAM 在啟動相機感測器並以 VGA (640x480) 加上高畫質 (`jpeg_quality=10`) 拍攝瞬間，會抽取極大電流。若電源供應不穩（如接在 3.3V 腳位或 USB 線材耗損），會導致相機模組崩潰。
*   **解決方案**：在通訊連線成功後，立即發送 `SET_RES:1` 指令，將解析度強制降至對供電與記憶體較友善的 QVGA (320x240) 模式，成功解決崩潰問題。

## 5. Python Serial 連線失敗：PermissionError (存取被拒)
*   **問題描述**：執行 Python 腳本時，跳出 `PermissionError(13, '存取被拒。')`。
*   **原因分析**：Arduino IDE 的 Serial Monitor 仍處於開啟狀態，霸佔了 COM Port，導致 Python 的 `pyserial` 無法開啟同一個通訊埠。
*   **解決方案**：執行 Python 程式前，確實關閉 Arduino IDE 的 Serial Monitor。

## 6. Python Serial 超時與相機不回應 PING
*   **問題描述**：Python 端顯示 `[WARN] ESP32-CAM not responding to PING`，隨後在擷取影像時發生 `[ERROR] Image receive timeout (10s)`。
*   **原因分析**：Python 的 `serial.Serial()` 在初始化時，會預設拉低 DTR 與 RTS 腳位。在 ESP32 架構中，這會拉低 `EN` (Reset) 腳位，導致相機板一直處於重開機狀態或進入 Bootloader 模式，無法執行相機初始化與接收 PING。
*   **解決方案**：在 Python 端開啟 Serial Port 的瞬間，立刻執行 `setDTR(False)` 與 `setRTS(False)`，並增加 `time.sleep(2.5)` 確保相機模組有足夠時間完成 I2C/SCCB 初始化與進入準備就緒狀態。

## 7. Python 影像存檔靜默失敗
*   **問題描述**：按下 `S` 鍵進行影像截圖儲存時，終端機顯示儲存成功，但資料夾內沒有檔案。
*   **原因分析**：OpenCV 的 `cv2.imwrite()` 若目標資料夾不存在，不會拋出錯誤而是直接默默失敗。
*   **解決方案**：在 `save_images()` 函式中加入 `os.makedirs(SAVE_DIR, exist_ok=True)`，確保 `captured_images` 資料夾在存檔前必定存在。

## 8. 實際檢測遇到 Domain Gap (領域落差)
*   **問題描述**：原本僅用 OpenCV 或合成資料集訓練的 YOLO 模型，在面對真實的彩色紙張、不均勻打光與斜角透視變形時，出現大量漏判與誤判。
*   **原因分析**：電腦模擬的平整完美光影與實際相機拍出來的照片有巨大的 Domain Gap。且 OpenCV 的自適應閾值容易受到彩色列印條紋的干擾。
*   **解決方案**：在系統內建「一鍵拍照收集 (S鍵)」功能，實際收集幾十張真實環境照片，透過手動標註後，使用 `train_yolo.py` 進行模型微調 (Fine-tuning)，成功解決真實場景的辨識問題。

## 9. 標註工具 labelImg 在新版環境頻繁崩潰 (TypeError: float)
*   **問題描述**：使用 `labelImg` 進行資料標註時，畫框、寫字、捲動滾輪或縮放時，會一直引發 `TypeError` 導致軟體閃退。
*   **原因分析**：`labelImg` 是一個較舊的專案，而新版的 PyQt5/6 在處理座標與數值時回傳 `float`，但 PyQt 內部的繪圖函數 (如 `drawLine`, `drawRect`, `drawText`) 嚴格要求輸入型態為 `int`。
*   **解決方案**：直接修改虛擬環境中 `labelImg` 相關的原始碼 (`canvas.py`, `shape.py`, `labelImg.py`)，將所有發生報錯的座標點與設定值強制轉型為 `int()`，徹底解決了相容性 Bug。

## 10. 自動化報表產出：整合 Excel 匯出功能
*   **功能描述**：為了方便後續追蹤與良率統計，系統新增了將瑕疵檢測結果匯出至 Excel 的功能。
*   **實作細節**：引入 `openpyxl` 套件，在每次完成檢測 (包含全流程 `SPACE` 或單色快照 `R/G/B`) 後，若有偵測到瑕疵，會自動在 `inspection_reports/` 資料夾下生成帶有時間戳記的 `.xlsx` 檔案。
*   **報表內容**：包含瑕疵座標、外接矩形大小、瑕疵類型、AI 信心度 (≥80% 會有高亮底色)，若是處於 3x3 拼接模式下，還會自動換算並記錄該瑕疵屬於哪一個子面板 (Panel 1~9)。

## 11. Arduino IDE 編譯錯誤：標頭檔找不到 `<WebSocketsServer.h>`
*   **問題描述**：燒錄支援 Wi-Fi 手機警報的新韌體時，編譯報出 `WebSocketsServer.h: No such file or directory` 錯誤。
*   **原因分析**：在 Arduino 程式庫管理員中搜尋並錯誤地安裝了 `WebSockets_Generic`（由 Khoi Hoang 改寫的版本），這與官方標準的 `WebSockets` 標頭檔結構不同。
*   **解決方案**：在程式庫管理員中搜尋並安裝由 **Markus Sattler** 開發的官方 **`WebSockets`** 標準庫（並將 Generic 版本移除），即可編譯通過。

## 12. Arduino 燒錄錯誤：`Could not open COM8, the port is busy or doesn't exist`
*   **問題描述**：在將新韌體上傳至 ESP32S 時，出現序列埠被佔用或不存在的錯誤。
*   **原因分析**：PC 端的 Python 檢測程式 (`defect_detector.py`) 仍在背景運行，一直佔用著連接 ESP32S 的 USB 串列通訊埠 (`COM8`)。
*   **解決方案**：先將執行中的 Python 視窗或 IDE 終端機關閉，釋放 `COM8` 埠後，再重新燒錄即可。

## 13. Wi-Fi 連線受阻：工業/公司現場共用網路不便與驗證問題
*   **問題描述**：在公司或實驗室等沒有開放 Wi-Fi 路由器，或者具有嚴格企業級網路驗證 (802.1X) 的場所，ESP32S 無法連上共用 Wi-Fi。
*   **原因分析**：傳統 Station 模式 (STA) 必須依賴外部路由器。
*   **解決方案**：將 ESP32S 升級為 **「AP 熱點模式 (Access Point Mode)」**，由晶片自己發射 `Defect_Detector_WiFi` 熱點。手機直接連入熱點後即可存取預設 IP `http://192.168.4.1` 的伺服器，擺脫了任何外部路由器的依賴，達到 100% 離線本地運作。

## 14. 虛擬環境損壞與執行路徑錯誤：專案搬遷至新電腦後無法啟動
*   **問題描述**：將專案資料夾從原始開發機複製到另一台電腦後，發生兩個致命錯誤：
    1.  執行 `pip install` 時跳出 `Fatal error in launcher: Unable to create process using '"D:\Other_program\Intelligent\pc_server\venv\Scripts\python.exe"'`，pip 完全無法運作。
    2.  在 `Intelligent/` 根目錄執行 `python defect_detector.py` 時跳出 `No such file or directory` 錯誤。
*   **原因分析**：
    1.  **虛擬環境路徑硬編碼**：原始的 `pc_server/venv` 是在另一台電腦的 `D:\Other_program\Intelligent\` 路徑下、使用 Anaconda (`C:\Users\YI-HSIANG LU\anaconda3`) 建立的。虛擬環境的 `pyvenv.cfg` 與所有 Scripts (pip.exe 等) 內部都硬編碼了原始路徑，搬遷後這些路徑全部失效，導致 pip launcher 找不到對應的 `python.exe` 而崩潰。
    2.  **工作目錄錯誤**：`defect_detector.py` 位於 `project6_defect_detection/pc_python/` 子目錄中，而非專案根目錄。
*   **解決方案**：
    1.  **重建虛擬環境**：在正確的工作目錄 (`pc_python/`) 下使用 `python -m venv venv` 重新建立全新的虛擬環境，並透過 `pip install -r requirements.txt` 安裝所有依賴套件（含 `ultralytics` 等 AI 相關套件）。
    2.  **修正 Usage.md 文件**：更新操作手冊中的虛擬環境路徑與啟動指令，明確標示必須先 `cd` 至 `pc_python/` 目錄、啟動本地 venv 後再執行 `defect_detector.py`。
    3.  **經驗教訓**：Python 虛擬環境 (`venv`) **不可跨機器複製搬遷**，因為內部路徑為絕對路徑且硬編碼於多個二進位檔中。正確做法是只攜帶 `requirements.txt`，在新機器上重新建立 venv。

## 15. 單色快照 vs 完整 RGB 掃描的差異分析與報告紀錄不足
*   **問題描述**：使用者發現鍵盤按 `R`/`G`/`B` 與按 Arduino 實體按鈕（或 `SPACE`）的檢測結果差異很大，希望從歷史報告中找出同角度、不同檢測方式的報告來對比，但無法區分。
*   **原因分析**：
    1.  **流程差異**：鍵盤 `R`/`G`/`B` 呼叫 `_capture_and_display()`，只開啟**單一顏色** LED、拍攝**一張**影像、僅分析**對應的單一通道**。而實體按鈕 / `SPACE` 呼叫 `run_inspection()`，會**依序執行紅→綠→藍三色拍攝**，每張影像各自用對應通道檢測後，再進行**多通道融合分析** (`detect_multi_channel`)，最後**去重合併** (`_merge_nearby_defects`) 相鄰瑕疵，輸出最終結果。
    2.  **單色檢測的問題**：例如只按 `R` 時，僅提取紅色通道分析。對於綠色或藍色面板上的瑕疵，在紅色通道中的對比度很低，容易造成**漏檢**或**大量誤判**（如 `20260523_161527` 報告出現 57 個瑕疵，全部為 circle 類型，疑似即為單色掃描的誤判案例）。
    3.  **Excel 報告缺陷**：`export_defects_to_excel()` 函式在兩條觸發路徑（`_capture_and_display` 與 `run_inspection`）中都被呼叫，但**均未記錄檢測方式**（單色 R/G/B 或完整 RGB）與**使用的 LED 顏色**，導致產出的 24 份歷史報告格式完全相同，事後無法回溯判斷。
*   **驗證過程**：使用 `openpyxl` 批次讀取了 `inspection_reports/` 中全部 24 份 `.xlsx` 報告，列出時間戳、模式、瑕疵數量與類型，確認所有報告中皆無檢測方式欄位，無法找到可對比的配對。
*   **建議解決方案**：
    1.  **改進 Excel 報表**：在 `export_defects_to_excel()` 中新增「檢測方式」欄位（`single_red` / `single_green` / `single_blue` / `full_rgb`），以便未來追蹤與比對。
    2.  **實際對比測試**：在相同角度下，先按 `R` 再按 `SPACE`，即可立即產生兩份可直接對比的報告，驗證單色與全色掃描的檢測差異。
