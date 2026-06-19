/*
 * =============================================================
 *  ESP32S 主控制器韌體
 *  Surface Defect Detection System - Controller Module
 * =============================================================
 *
 *  功能：
 *    1. 控制 R/G/B 三色 LED 光源（PWM 調光）
 *    2. 驅動 OLED 顯示器（SSD1306 0.96" I2C）顯示檢測結果
 *    3. 控制蜂鳴器發出瑕疵警報
 *    4. 按鈕觸發檢測流程
 *    5. 透過 USB Serial 與 PC 雙向通訊
 *
 *  通訊協議（USB Serial, 115200 baud）：
 *    接收指令 (PC → ESP32S)：
 *      - "LED:R\n"       → 開啟紅光 LED
 *      - "LED:G\n"       → 開啟綠光 LED
 *      - "LED:B\n"       → 開啟藍光 LED
 *      - "LED:ALL\n"     → 全部開啟
 *      - "LED:OFF\n"     → 全部關閉
 *      - "LED:R,<0-255>\n" → 設定紅光亮度 (PWM)
 *      - "RESULT:DEFECT,<x>,<y>,<w>,<h>,<type>,<conf>\n" → 瑕疵結果
 *      - "RESULT:OK\n"   → 無瑕疵
 *      - "RESULT:DONE\n" → 檢測完成
 *      - "BUZZ:ON\n"     → 蜂鳴器開
 *      - "BUZZ:OFF\n"    → 蜂鳴器關
 *      - "MSG:<text>\n"  → OLED 顯示訊息
 *      - "SCANNING\n"    → 進入掃描狀態
 *
 *    發送指令 (ESP32S → PC)：
 *      - "BTN_PRESSED\n" → 按鈕被按下
 *      - "LED_OK\n"      → LED 已切換
 *      - "CTRL_READY\n"  → 控制器就緒
 *
 *  接線：
 *    GPIO 25 → 紅光 LED（透過 220Ω 限流電阻）
 *    GPIO 26 → 綠光 LED（透過 220Ω 限流電阻）
 *    GPIO 27 → 藍光 LED（透過 220Ω 限流電阻）
 *    GPIO 21 → OLED SDA (I2C)
 *    GPIO 22 → OLED SCL (I2C)
 *    GPIO  4 → 有源蜂鳴器（透過 NPN 電晶體或直接連接）
 *    GPIO 15 → 按鈕（另一端接 GND，使用內部上拉電阻）
 *
 *  OLED: KEYES SSD1306 0.96" 綠色字幕 (I2C, 地址 0x3C)
 *
 *  Board 設定：
 *    Arduino IDE → Tools → Board → ESP32 → ESP32 Dev Module
 * =============================================================
 */

#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#include <WiFi.h>
#include <ESPmDNS.h>
#include <WebSocketsServer.h>

// ==================== OLED 設定 ====================
#define SCREEN_WIDTH  128
#define SCREEN_HEIGHT  64
#define OLED_RESET     -1       // 無重置腳位
#define OLED_ADDR    0x3C       // I2C 地址（多數 SSD1306 為 0x3C）

Adafruit_SSD1306 display(SCREEN_WIDTH, SCREEN_HEIGHT, &Wire, OLED_RESET);
bool hasOLED = false;  // 記錄是否有成功連接 OLED

// ==================== Wi-Fi AP 模式設定 ====================
// ESP32S 將會自己發射一個獨立的 Wi-Fi 熱點，手機直接連入即可，無需外部網路！
const char* ap_ssid     = "Defect_Detector_WiFi"; // 您可以在手機 Wi-Fi 搜尋到這個名稱
const char* ap_password = "password123";          // 連線密碼（至少8個字元）

WiFiServer server(80);                // Port 80 用於手機端 App 網頁託管
WebSocketsServer webSocket = WebSocketsServer(81); // Port 81 用於 WebSocket 即時數據廣播
bool isWiFiConnected = false;

// 託管在 ESP32 內部的 HTML 網頁程式碼 (PWA Dashboard)
const char HTML_PAGE[] PROGMEM = R"rawhtml(
<!DOCTYPE html>
<html lang="zh-TW">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta name="apple-mobile-web-app-capable" content="yes">
  <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
  <title>表面瑕疵監控 App</title>
  <style>
    :root {
      --bg-color: #0f1016;
      --panel-bg: rgba(22, 24, 35, 0.7);
      --border-color: rgba(255, 255, 255, 0.08);
      
      --color-ready: #00ff87;
      --color-scan: #00d2ff;
      --color-defect: #ff0055;
      --color-text: #e2e8f0;
      --color-subtext: #94a3b8;
      
      --glow-ready: 0 0 20px rgba(0, 255, 135, 0.4);
      --glow-scan: 0 0 20px rgba(0, 210, 255, 0.4);
      --glow-defect: 0 0 25px rgba(255, 0, 85, 0.6);
    }

    * {
      box-sizing: border-box;
      margin: 0;
      padding: 0;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
      -webkit-tap-highlight-color: transparent;
    }

    body {
      background-color: var(--bg-color);
      color: var(--color-text);
      display: flex;
      flex-direction: column;
      min-height: 100vh;
      overflow-x: hidden;
      padding-bottom: 20px;
    }

    /* 頂部導航列 */
    header {
      background-color: rgba(15, 16, 22, 0.8);
      backdrop-filter: blur(10px);
      border-bottom: 1px solid var(--border-color);
      padding: 15px 20px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      position: sticky;
      top: 0;
      z-index: 100;
    }

    h1 {
      font-size: 1.1rem;
      font-weight: 600;
      letter-spacing: 0.5px;
      background: linear-gradient(45deg, #fff, #a5b4fc);
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
    }

    /* 連線狀態標籤 */
    .status-badge {
      display: flex;
      align-items: center;
      gap: 6px;
      font-size: 0.75rem;
      font-weight: 500;
      padding: 5px 10px;
      border-radius: 20px;
      background: rgba(255, 255, 255, 0.05);
      border: 1px solid var(--border-color);
      transition: all 0.3s ease;
    }

    .status-dot {
      width: 8px;
      height: 8px;
      border-radius: 50%;
      background-color: #ffaa00;
      box-shadow: 0 0 8px #ffaa00;
    }

    .connected .status-dot {
      background-color: var(--color-ready);
      box-shadow: 0 0 8px var(--color-ready);
    }

    .disconnected .status-dot {
      background-color: var(--color-defect);
      box-shadow: 0 0 8px var(--color-defect);
    }

    /* 主容器 */
    main {
      flex: 1;
      padding: 20px;
      display: flex;
      flex-direction: column;
      gap: 20px;
      max-width: 500px;
      margin: 0 auto;
      width: 100%;
    }

    /* 主狀態展示卡片 */
    .hero-card {
      background: var(--panel-bg);
      backdrop-filter: blur(10px);
      border: 1px solid var(--border-color);
      border-radius: 24px;
      padding: 30px 20px;
      text-align: center;
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: 15px;
      position: relative;
      overflow: hidden;
      box-shadow: 0 10px 30px rgba(0, 0, 0, 0.3);
      transition: all 0.5s cubic-bezier(0.16, 1, 0.3, 1);
    }

    /* 光譜掃描線動畫 */
    .hero-card::after {
      content: '';
      position: absolute;
      top: -10%;
      left: 0;
      width: 100%;
      height: 6px;
      background: linear-gradient(90deg, transparent, var(--color-scan), transparent);
      box-shadow: 0 0 10px var(--color-scan);
      opacity: 0;
      transition: opacity 0.3s;
    }

    .scanning::after {
      opacity: 1;
      animation: scan 2s linear infinite;
    }

    @keyframes scan {
      0% { top: -10%; }
      100% { top: 110%; }
    }

    .status-orb {
      width: 90px;
      height: 90px;
      border-radius: 50%;
      background: radial-gradient(circle at 30% 30%, rgba(255,255,255,0.2) 0%, rgba(0,0,0,0.4) 100%);
      background-color: #ffaa00;
      box-shadow: 0 0 30px rgba(255, 170, 0, 0.3);
      transition: all 0.5s ease;
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 2.2rem;
    }

    /* 三種狀態的卡片與 Orb 樣式 */
    .ready .status-orb {
      background-color: var(--color-ready);
      box-shadow: var(--glow-ready);
    }
    
    .scanning .status-orb {
      background-color: var(--color-scan);
      box-shadow: var(--glow-scan);
      animation: pulse 1.5s infinite alternate;
    }

    .defect .status-orb {
      background-color: var(--color-defect);
      box-shadow: var(--glow-defect);
      animation: rapid-pulse 0.4s infinite alternate;
    }

    .defect.hero-card {
      border-color: rgba(255, 0, 85, 0.4);
      background: linear-gradient(180deg, rgba(255, 0, 85, 0.1) 0%, rgba(22, 24, 35, 0.8) 100%);
    }

    @keyframes pulse {
      0% { transform: scale(1); opacity: 0.9; }
      100% { transform: scale(1.08); opacity: 1; }
    }

    @keyframes rapid-pulse {
      0% { transform: scale(1); filter: brightness(1); }
      100% { transform: scale(1.1); filter: brightness(1.3); }
    }

    .status-title {
      font-size: 1.4rem;
      font-weight: 700;
      margin-top: 5px;
      letter-spacing: 0.5px;
    }

    .status-desc {
      font-size: 0.9rem;
      color: var(--color-subtext);
      max-width: 80%;
      line-height: 1.4;
    }

    /* 瑕疵細節卡片 */
    .detail-card {
      background: var(--panel-bg);
      backdrop-filter: blur(10px);
      border: 1px solid var(--border-color);
      border-radius: 20px;
      padding: 20px;
      display: flex;
      flex-direction: column;
      gap: 15px;
      box-shadow: 0 8px 20px rgba(0, 0, 0, 0.2);
    }

    .card-title {
      font-size: 0.95rem;
      font-weight: 600;
      color: var(--color-subtext);
      border-bottom: 1px solid var(--border-color);
      padding-bottom: 8px;
      display: flex;
      justify-content: space-between;
      align-items: center;
    }

    .detail-grid {
      display: grid;
      grid-template-columns: repeat(2, 1fr);
      gap: 15px;
    }

    .detail-item {
      display: flex;
      flex-direction: column;
      gap: 4px;
    }

    .detail-label {
      font-size: 0.75rem;
      color: var(--color-subtext);
    }

    .detail-val {
      font-size: 1.1rem;
      font-weight: 600;
    }

    .defect-type-tag {
      background: rgba(255, 0, 85, 0.15);
      color: #ff3377;
      border: 1px solid rgba(255, 0, 85, 0.25);
      padding: 2px 8px;
      border-radius: 6px;
      font-size: 0.8rem;
      font-weight: 600;
      display: inline-block;
      text-transform: uppercase;
    }

    /* 歷史記錄列表 */
    .history-card {
      background: var(--panel-bg);
      backdrop-filter: blur(10px);
      border: 1px solid var(--border-color);
      border-radius: 20px;
      padding: 20px;
      box-shadow: 0 8px 20px rgba(0, 0, 0, 0.2);
      flex: 1;
      display: flex;
      flex-direction: column;
      min-height: 250px;
    }

    .history-list {
      display: flex;
      flex-direction: column;
      gap: 10px;
      overflow-y: auto;
      max-height: 250px;
      margin-top: 10px;
      padding-right: 2px;
    }

    /* 自訂滾動條 */
    .history-list::-webkit-scrollbar {
      width: 4px;
    }
    .history-list::-webkit-scrollbar-thumb {
      background: rgba(255, 255, 255, 0.1);
      border-radius: 2px;
    }

    .history-item {
      background: rgba(255, 255, 255, 0.02);
      border: 1px solid var(--border-color);
      border-radius: 12px;
      padding: 12px 15px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      transition: background-color 0.2s;
    }

    .history-item.has-defect {
      border-left: 3px solid var(--color-defect);
      background: rgba(255, 0, 85, 0.02);
    }

    .history-item.is-pass {
      border-left: 3px solid var(--color-ready);
      background: rgba(0, 255, 135, 0.02);
    }

    .item-meta {
      display: flex;
      flex-direction: column;
      gap: 3px;
    }

    .item-time {
      font-size: 0.75rem;
      color: var(--color-subtext);
    }

    .item-title {
      font-size: 0.9rem;
      font-weight: 600;
    }

    .item-result {
      font-size: 0.95rem;
      font-weight: 700;
    }

    .item-result.fail {
      color: var(--color-defect);
    }

    .item-result.pass {
      color: var(--color-ready);
    }

    /* 懸浮音效授權按鈕 */
    .audio-banner {
      background: linear-gradient(135deg, #3b82f6 0%, #1d4ed8 100%);
      color: white;
      padding: 12px 20px;
      border-radius: 16px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      box-shadow: 0 10px 20px rgba(59, 130, 246, 0.3);
      animation: slideUp 0.5s ease-out;
      border: 1px solid rgba(255,255,255,0.1);
      margin-top: auto;
    }

    .audio-btn {
      background: white;
      color: #1d4ed8;
      border: none;
      padding: 6px 14px;
      border-radius: 8px;
      font-weight: 600;
      font-size: 0.8rem;
      cursor: pointer;
      box-shadow: 0 4px 8px rgba(0,0,0,0.1);
      transition: all 0.2s;
    }

    .audio-btn:active {
      transform: scale(0.95);
    }

    @keyframes slideUp {
      from { transform: translateY(30px); opacity: 0; }
      to { transform: translateY(0); opacity: 1; }
    }
  </style>
</head>
<body>

  <!-- 頂部導航列 -->
  <header>
    <h1>表面瑕疵即時監控</h1>
    <div id="connBadge" class="status-badge disconnected">
      <div class="status-dot"></div>
      <span id="connText">已中斷</span>
    </div>
  </header>

  <!-- 主內容區 -->
  <main>
    <!-- 主狀態展示卡片 -->
    <div id="heroCard" class="hero-card ready">
      <div id="statusOrb" class="status-orb">🟢</div>
      <div id="statusTitle" class="status-title">系統就緒</div>
      <div id="statusDesc" class="status-desc">待機中，按下機台按鈕或 PC 空白鍵啟動全自動多光譜檢測。</div>
    </div>

    <!-- 瑕疵詳細資訊 -->
    <div class="detail-card">
      <div class="card-title">
        <span>最新檢測數據</span>
        <span id="timestampVal" style="font-size: 0.8rem; font-weight: normal;">-</span>
      </div>
      <div class="detail-grid">
        <div class="detail-item">
          <span class="detail-label">缺陷數量</span>
          <span id="countVal" class="detail-val">-</span>
        </div>
        <div class="detail-item">
          <span class="detail-label">主要瑕疵類型</span>
          <span id="typeVal" class="detail-val">-</span>
        </div>
        <div class="detail-item">
          <span class="detail-label">最大信心度</span>
          <span id="confVal" class="detail-val">-</span>
        </div>
        <div class="detail-item">
          <span class="detail-label">最新座標 (X, Y)</span>
          <span id="posVal" class="detail-val">-</span>
        </div>
      </div>
    </div>

    <!-- 檢測歷史紀錄 -->
    <div class="history-card">
      <div class="card-title">檢測歷史日誌</div>
      <div id="historyList" class="history-list">
        <!-- 歷史項目會在這裡動態插入 -->
        <div id="emptyLog" style="text-align: center; color: var(--color-subtext); padding: 40px 0; font-size: 0.85rem;">
          尚無檢測紀錄
        </div>
      </div>
    </div>

    <!-- 音效啟用橫幅 -->
    <div id="audioBanner" class="audio-banner">
      <span style="font-size: 0.85rem; font-weight: 500;">啟用警報音效，接收瑕疵聲音提醒</span>
      <button class="audio-btn" onclick="enableAudio()">立刻啟用</button>
    </div>
  </main>

  <script>
    // ==================== WebSocket 設定 ====================
    const espIp = window.location.hostname || "192.168.4.1";
    const wsUrl = `ws://${espIp}:81`;
    let ws = null;
    let reconnectInterval = null;

    // ==================== 音效合成器 (Web Audio API) ====================
    let audioCtx = null;
    let audioEnabled = false;

    function enableAudio() {
      if (audioEnabled) return;
      audioCtx = new (window.AudioContext || window.webkitAudioContext)();
      audioEnabled = true;
      document.getElementById('audioBanner').style.display = 'none';
      
      // 播放一個簡短的確認音
      playTone(600, 'sine', 0.1);
      setTimeout(() => playTone(800, 'sine', 0.15), 100);
      console.log("Audio Context Enabled!");
    }

    function playTone(freq, type, duration) {
      if (!audioCtx || !audioEnabled) return;
      
      const osc = audioCtx.createOscillator();
      const gainNode = audioCtx.createGain();
      
      osc.type = type;
      osc.frequency.setValueAtTime(freq, audioCtx.currentTime);
      
      gainNode.gain.setValueAtTime(0.15, audioCtx.currentTime);
      gainNode.gain.exponentialRampToValueAtTime(0.001, audioCtx.currentTime + duration);
      
      osc.connect(gainNode);
      gainNode.connect(audioCtx.destination);
      
      osc.start();
      osc.stop(audioCtx.currentTime + duration);
    }

    // 瑕疵警報：急促嗶嗶聲
    function triggerAlertSound() {
      if (!audioEnabled) return;
      let count = 0;
      const beep = () => {
        if (count >= 5) return; // 響 5 聲
        playTone(2200, 'sawtooth', 0.18);
        count++;
        setTimeout(beep, 300);
      };
      beep();
    }

    // ==================== 畫面 UI 更新控制 ====================
    const heroCard = document.getElementById('heroCard');
    const statusOrb = document.getElementById('statusOrb');
    const statusTitle = document.getElementById('statusTitle');
    const statusDesc = document.getElementById('statusDesc');

    const countVal = document.getElementById('countVal');
    const typeVal = document.getElementById('typeVal');
    const confVal = document.getElementById('confVal');
    const posVal = document.getElementById('posVal');
    const timestampVal = document.getElementById('timestampVal');
    const historyList = document.getElementById('historyList');
    const emptyLog = document.getElementById('emptyLog');

    function updateState(state, data = null) {
      heroCard.className = 'hero-card';
      const timeStr = new Date().toLocaleTimeString();

      if (state === 'READY') {
        heroCard.classList.add('ready');
        statusOrb.innerHTML = '🟢';
        statusTitle.innerText = '系統就緒';
        statusDesc.innerText = '機台待機中。等待按下實體按鈕或 PC 空白鍵啟動全自動檢測。';
      }
      else if (state === 'SCANNING') {
        heroCard.classList.add('scanning');
        statusOrb.innerHTML = '🔵';
        statusTitle.innerText = '正在掃描中';
        let ledColor = data ? data.color : "...";
        statusDesc.innerText = `多光譜相機拍攝中！當前光源顏色：[${ledColor.toUpperCase()}]`;
      }
      else if (state === 'DEFECT') {
        heroCard.classList.add('defect');
        statusOrb.innerHTML = '🚨';
        statusTitle.innerText = `發現瑕疵！`;
        
        let defectNum = data ? data.count : 1;
        let typeStr = data ? translateType(data.type) : "表面瑕疵";
        statusDesc.innerText = `警告！檢測出 ${defectNum} 個缺陷物件。主瑕疵為：[${typeStr}]。`;

        countVal.innerText = `${defectNum} 個`;
        countVal.style.color = 'var(--color-defect)';
        
        typeVal.innerHTML = `<span class="defect-type-tag">${data ? data.type : "UNKNOWN"}</span>`;
        confVal.innerText = data ? `${Math.round(data.conf * 100)}%` : "-";
        posVal.innerText = data ? `(${data.x}, ${data.y})` : "-";
        timestampVal.innerText = timeStr;

        triggerAlertSound();
        addHistoryItem(true, defectNum, data ? data.type : "defect", timeStr);
      }
      else if (state === 'PASS') {
        heroCard.classList.add('ready');
        statusOrb.innerHTML = '✅';
        statusTitle.innerText = '表面優良 (PASS)';
        statusDesc.innerText = '完成全流程 R+G+B 光譜檢測，表面未發現 any 異常瑕疵。';

        countVal.innerText = '0 個';
        countVal.style.color = 'var(--color-ready)';
        typeVal.innerText = '無缺陷';
        confVal.innerText = '100%';
        posVal.innerText = 'N/A';
        timestampVal.innerText = timeStr;

        playTone(523.25, 'sine', 0.12); // C5
        setTimeout(() => playTone(659.25, 'sine', 0.2), 120); // E5

        addHistoryItem(false, 0, '無缺陷', timeStr);
      }
    }

    function translateType(type) {
      const dict = {
        'point': '細微斑點',
        'square': '方塊突起',
        'circle': '圓形凹陷',
        'line_h': '水平割傷',
        'line_v': '垂直刮痕',
        'scratch': '刮磨痕',
        'crack': '表面裂紋',
        'stain': '液體污漬',
        'spot': '點狀雜質'
      };
      return dict[type.toLowerCase()] || type;
    }

    function addHistoryItem(isDefect, count, type, timeStr) {
      if (emptyLog) {
        emptyLog.style.display = 'none';
      }

      const item = document.createElement('div');
      item.className = `history-item ${isDefect ? 'has-defect' : 'is-pass'}`;
      const typeLabel = isDefect ? translateType(type) : '檢測通過';

      item.innerHTML = `
        <div class="item-meta">
          <span class="item-title">${typeLabel}</span>
          <span class="item-time">${timeStr}</span>
        </div>
        <div class="item-result ${isDefect ? 'fail' : 'pass'}">
          ${isDefect ? `${count} 個缺陷` : 'PASS'}
        </div>
      `;

      historyList.insertBefore(item, historyList.firstChild);
      if (historyList.children.length > 10) {
        historyList.removeChild(historyList.lastChild);
      }
    }

    // ==================== WebSocket 連線與通訊協定 ====================
    const connBadge = document.getElementById('connBadge');
    const connText = document.getElementById('connText');

    function connectWs() {
      console.log(`Trying to connect: ${wsUrl}`);
      ws = new WebSocket(wsUrl);

      ws.onopen = () => {
        console.log("WebSocket Connected!");
        connBadge.className = 'status-badge connected';
        connText.innerText = '已連線';
        clearInterval(reconnectInterval);
        reconnectInterval = null;
      };

      ws.onmessage = (event) => {
        console.log("WS Data Received: ", event.data);
        try {
          const msg = JSON.parse(event.data);
          if (msg.status === 'SCANNING') {
            updateState('SCANNING', msg);
          } 
          else if (msg.status === 'DEFECT') {
            updateState('DEFECT', msg);
          } 
          else if (msg.status === 'OK') {
            updateState('PASS');
          } 
          else if (msg.status === 'READY') {
            updateState('READY');
          }
        } catch (e) {
          console.error("Parse message error: ", e);
        }
      };

      ws.onclose = () => {
        console.log("WebSocket Disconnected.");
        connBadge.className = 'status-badge disconnected';
        connText.innerText = '已中斷';
        if (!reconnectInterval) {
          reconnectInterval = setInterval(connectWs, 2000);
        }
      };

      ws.onerror = (err) => {
        console.error("WS Error: ", err);
        ws.close();
      };
    }

    window.onload = () => {
      connectWs();
    };
  </script>
</body>
</html>
)rawhtml";

// ==================== 腳位定義 ====================
// LED 光源
#define LED_RED_PIN    25       // 紅光 LED
#define LED_GREEN_PIN  26       // 綠光 LED
#define LED_BLUE_PIN   27       // 藍光 LED

// 蜂鳴器
#define BUZZER_PIN      4       // 有源蜂鳴器

// 按鈕
#define BUTTON_PIN     15       // 啟動檢測按鈕

// ==================== PWM 設定 (ESP32 LEDC) ====================
// ESP32 Arduino Core 2.x API
#define PWM_FREQ       5000    // PWM 頻率 5kHz
#define PWM_RESOLUTION    8    // 8-bit 解析度 (0-255)
#define PWM_CH_RED        0    // LEDC 通道 0
#define PWM_CH_GREEN      1    // LEDC 通道 1
#define PWM_CH_BLUE       2    // LEDC 通道 2

// ==================== 系統狀態 ====================
enum SystemState {
  STATE_IDLE,        // 閒置
  STATE_SCANNING,    // 掃描中
  STATE_DEFECT,      // 發現瑕疵
  STATE_PASS,        // 通過（無瑕疵）
  STATE_ERROR        // 錯誤
};

SystemState currentState = STATE_IDLE;

// ==================== 瑕疵資訊 ====================
struct DefectInfo {
  int x;             // 瑕疵中心 X 座標
  int y;             // 瑕疵中心 Y 座標
  int w;             // 瑕疵寬度
  int h;             // 瑕疵高度
  String type;       // 瑕疵類型 (scratch/spot/crack)
  float confidence;  // 信心度 (0.0 - 1.0)
};

#define MAX_DEFECTS 10
DefectInfo defects[MAX_DEFECTS];
int defectCount = 0;

// ==================== 按鈕防彈跳 ====================
unsigned long lastButtonPress = 0;
const unsigned long DEBOUNCE_MS = 300;

// ==================== Serial 輸入緩衝 ====================
String inputBuffer = "";

// ==================== 蜂鳴器控制 ====================
bool buzzerActive = false;
unsigned long buzzerStartTime = 0;
int buzzerPattern = 0;    // 0=off, 1=short beep, 2=alarm pattern
unsigned long buzzerToggleTime = 0;
bool buzzerState = false;

// ==================== 初始化 LED PWM ====================
void initLEDs() {
  // 使用 ESP32 Core 3.x API 設定 PWM
  ledcAttach(LED_RED_PIN, PWM_FREQ, PWM_RESOLUTION);
  ledcAttach(LED_GREEN_PIN, PWM_FREQ, PWM_RESOLUTION);
  ledcAttach(LED_BLUE_PIN, PWM_FREQ, PWM_RESOLUTION);

  // 初始全部關閉
  ledcWrite(LED_RED_PIN,   0);
  ledcWrite(LED_GREEN_PIN, 0);
  ledcWrite(LED_BLUE_PIN,  0);
}

// ==================== LED 控制函數 ====================
void setLED(int red, int green, int blue) {
  ledcWrite(LED_RED_PIN,   red);
  ledcWrite(LED_GREEN_PIN, green);
  ledcWrite(LED_BLUE_PIN,  blue);
}

void ledOff() {
  setLED(0, 0, 0);
}

void ledRed(int brightness = 255) {
  setLED(brightness, 0, 0);
}

void ledGreen(int brightness = 255) {
  setLED(0, brightness, 0);
}

void ledBlue(int brightness = 255) {
  setLED(0, 0, brightness);
}

void ledAll(int brightness = 255) {
  setLED(brightness, brightness, brightness);
}

// ==================== 蜂鳴器控制 ====================
void buzzerBeep(int durationMs = 200) {
  // 短促嗶聲 (無源蜂鳴器需要用 tone 產生頻率)
  tone(BUZZER_PIN, 2000); // 發出 2000Hz 的聲音
  delay(durationMs);
  noTone(BUZZER_PIN);     // 停止發聲
}

void startAlarm() {
  buzzerActive = true;
  buzzerPattern = 2;   // 警報模式
  buzzerStartTime = millis();
  buzzerToggleTime = millis();
  buzzerState = false;
}

void stopAlarm() {
  buzzerActive = false;
  buzzerPattern = 0;
  noTone(BUZZER_PIN);
}

void updateBuzzer() {
  if (!buzzerActive) return;

  unsigned long elapsed = millis() - buzzerStartTime;

  // 警報最多響 5 秒
  if (elapsed > 5000) {
    stopAlarm();
    return;
  }

  if (buzzerPattern == 2) {
    // 警報模式：急促嗶嗶嗶 (200ms ON, 100ms OFF)
    if (millis() - buzzerToggleTime > (buzzerState ? 200 : 100)) {
      buzzerState = !buzzerState;
      if (buzzerState) {
        tone(BUZZER_PIN, 2500); // 警報聲用高一點的音頻 2500Hz
      } else {
        noTone(BUZZER_PIN);
      }
      buzzerToggleTime = millis();
    }
  }
}

// ==================== OLED 顯示函數 ====================
void displayInit() {
  if (!hasOLED) return;
  display.clearDisplay();
  display.setTextSize(1);
  display.setTextColor(SSD1306_WHITE);
  display.setCursor(0, 0);
  display.println(F("================"));
  display.println(F(" Defect Detector"));
  display.println(F("   System v1.0  "));
  display.println(F("================"));
  display.println();
  display.println(F("Initializing..."));
  display.display();
}

void displayReady() {
  if (!hasOLED) return;
  display.clearDisplay();
  display.setTextSize(1);
  display.setTextColor(SSD1306_WHITE);

  // 標題列
  display.setCursor(0, 0);
  display.println(F("=Defect Detector="));

  // 分隔線
  display.drawLine(0, 10, 127, 10, SSD1306_WHITE);

  // 狀態
  display.setCursor(0, 14);
  display.setTextSize(2);
  display.println(F("READY"));

  // 提示
  display.setTextSize(1);
  display.setCursor(0, 40);
  display.println(F("Press BTN to"));
  display.println(F("start inspection"));

  display.display();
}

void displayScanning(String ledColor) {
  if (!hasOLED) return;
  display.clearDisplay();
  display.setTextSize(1);
  display.setTextColor(SSD1306_WHITE);

  display.setCursor(0, 0);
  display.println(F("=Defect Detector="));
  display.drawLine(0, 10, 127, 10, SSD1306_WHITE);

  display.setCursor(0, 14);
  display.setTextSize(2);
  display.println(F("SCAN..."));

  display.setTextSize(1);
  display.setCursor(0, 40);
  display.print(F("LED: "));
  display.println(ledColor);
  display.println(F("Capturing image..."));

  display.display();
}

void displayDefectResult() {
  if (!hasOLED) return;
  display.clearDisplay();
  display.setTextSize(1);
  display.setTextColor(SSD1306_WHITE);

  display.setCursor(0, 0);
  display.println(F("=Defect Detector="));
  display.drawLine(0, 10, 127, 10, SSD1306_WHITE);

  // 大字顯示 DEFECT
  display.setCursor(6, 14);
  display.setTextSize(2);
  display.println(F("!!DEFECT!!"));

  display.setTextSize(1);

  if (defectCount > 0) {
    // 顯示總瑕疵數與第一個瑕疵的詳細資訊
    display.setCursor(0, 34);
    display.print(F("Defects Count: "));
    display.println(defectCount);

    display.print(F("Primary: "));
    display.print(defects[0].type);
    display.print(F(" ("));
    display.print((int)(defects[0].confidence * 100));
    display.println(F("%)"));

    display.print(F("Pos: ("));
    display.print(defects[0].x);
    display.print(F(", "));
    display.print(defects[0].y);
    display.println(F(")"));
  }

  display.display();
}

void displayPass() {
  if (!hasOLED) return;
  display.clearDisplay();
  display.setTextSize(1);
  display.setTextColor(SSD1306_WHITE);

  display.setCursor(0, 0);
  display.println(F("=Defect Detector="));
  display.drawLine(0, 10, 127, 10, SSD1306_WHITE);

  // 大字顯示 PASS
  display.setCursor(22, 14);
  display.setTextSize(2);
  display.println(F("PASS!"));

  display.setTextSize(1);
  display.setCursor(0, 40);
  display.println(F("No defects found"));
  display.println(F("Surface is OK"));

  display.display();
}

void displayMessage(String msg) {
  if (!hasOLED) return;
  display.clearDisplay();
  display.setTextSize(1);
  display.setTextColor(SSD1306_WHITE);

  display.setCursor(0, 0);
  display.println(F("=Defect Detector="));
  display.drawLine(0, 10, 127, 10, SSD1306_WHITE);

  display.setCursor(0, 16);
  // 自動換行顯示訊息
  display.println(msg);

  display.display();
}

// ==================== 解析瑕疵結果 ====================
// 格式: RESULT:DEFECT,<x>,<y>,<w>,<h>,<type>,<conf>
bool parseDefectResult(String data) {
  // 解析逗號分隔的資料
  int idx = 0;
  int commaPos;
  String parts[7];

  String remaining = data;
  for (int i = 0; i < 7 && remaining.length() > 0; i++) {
    commaPos = remaining.indexOf(',');
    if (commaPos == -1) {
      parts[idx++] = remaining;
      break;
    } else {
      parts[idx++] = remaining.substring(0, commaPos);
      remaining = remaining.substring(commaPos + 1);
    }
  }

  if (idx < 6) return false;  // 至少需要 x,y,w,h,type,conf

  if (defectCount < MAX_DEFECTS) {
    defects[defectCount].x          = parts[0].toInt();
    defects[defectCount].y          = parts[1].toInt();
    defects[defectCount].w          = parts[2].toInt();
    defects[defectCount].h          = parts[3].toInt();
    defects[defectCount].type       = parts[4];
    defects[defectCount].confidence = parts[5].toFloat();
    defectCount++;
    return true;
  }
  return false;
}

// ==================== WebSocket 事件處理 ====================
void webSocketEvent(uint8_t num, WStype_t type, uint8_t * payload, size_t length) {
  switch(type) {
    case WStype_DISCONNECTED:
      Serial.printf("WS [%u] Disconnected!\n", num);
      break;
    case WStype_CONNECTED: {
      IPAddress ip = webSocket.remoteIP(num);
      Serial.printf("WS [%u] Connected from %s\n", num, ip.toString().c_str());
      // 當手機新連入時，主動發送當前系統狀態，讓手機同步
      String json = "{\"status\":\"READY\"}";
      if (currentState == STATE_SCANNING) {
        json = "{\"status\":\"SCANNING\",\"color\":\"...\"}";
      } else if (currentState == STATE_DEFECT && defectCount > 0) {
        int lastIdx = defectCount - 1;
        json = "{\"status\":\"DEFECT\",\"count\":" + String(defectCount) + 
               ",\"type\":\"" + defects[lastIdx].type + 
               "\",\"conf\":" + String(defects[lastIdx].confidence) + 
               ",\"x\":" + String(defects[lastIdx].x) + 
               ",\"y\":" + String(defects[lastIdx].y) + "}";
      } else if (currentState == STATE_PASS) {
        json = "{\"status\":\"OK\"}";
      }
      webSocket.sendTXT(num, json);
      break;
    }
    case WStype_TEXT:
      Serial.printf("WS [%u] get Text: %s\n", num, payload);
      break;
    default:
      break;
  }
}

// ==================== HTTP Web 伺服器處理 ====================
void handleHTTPServer() {
  if (!isWiFiConnected) return;

  WiFiClient client = server.available();
  if (client) {
    Serial.println("INFO: New HTTP Client");
    String currentLine = "";
    while (client.connected()) {
      if (client.available()) {
        char c = client.read();
        if (c == '\n') {
          if (currentLine.length() == 0) {
            // HTTP 請求結束，回傳 HTML 網頁
            client.println("HTTP/1.1 200 OK");
            client.println("Content-type:text/html; charset=utf-8");
            client.println("Connection: close");
            client.println();
            client.print(HTML_PAGE);
            break;
          } else {
            currentLine = "";
          }
        } else if (c != '\r') {
          currentLine += c;
        }
      }
    }
    delay(1);
    client.stop();
    Serial.println("INFO: HTTP Client disconnected");
  }
}

// ==================== 處理 Serial 指令 ====================
void processCommand(String cmd) {
  cmd.trim();

  // ----- LED 控制 -----
  if (cmd == "LED:R") {
    ledRed();
    currentState = STATE_SCANNING;
    displayScanning("RED");
    if (isWiFiConnected) {
      webSocket.broadcastTXT("{\"status\":\"SCANNING\",\"color\":\"RED\"}");
    }
    Serial.println("LED_OK");
  }
  else if (cmd == "LED:G") {
    ledGreen();
    currentState = STATE_SCANNING;
    displayScanning("GREEN");
    if (isWiFiConnected) {
      webSocket.broadcastTXT("{\"status\":\"SCANNING\",\"color\":\"GREEN\"}");
    }
    Serial.println("LED_OK");
  }
  else if (cmd == "LED:B") {
    ledBlue();
    currentState = STATE_SCANNING;
    displayScanning("BLUE");
    if (isWiFiConnected) {
      webSocket.broadcastTXT("{\"status\":\"SCANNING\",\"color\":\"BLUE\"}");
    }
    Serial.println("LED_OK");
  }
  else if (cmd == "LED:ALL") {
    ledAll();
    currentState = STATE_SCANNING;
    displayScanning("ALL(WHITE)");
    if (isWiFiConnected) {
      webSocket.broadcastTXT("{\"status\":\"SCANNING\",\"color\":\"WHITE\"}");
    }
    Serial.println("LED_OK");
  }
  else if (cmd == "LED:OFF") {
    ledOff();
    Serial.println("LED_OK");
  }
  // 自訂亮度: LED:R,128
  else if (cmd.startsWith("LED:R,")) {
    int val = cmd.substring(6).toInt();
    ledRed(constrain(val, 0, 255));
    displayScanning("RED");
    if (isWiFiConnected) {
      webSocket.broadcastTXT("{\"status\":\"SCANNING\",\"color\":\"RED\"}");
    }
    Serial.println("LED_OK");
  }
  else if (cmd.startsWith("LED:G,")) {
    int val = cmd.substring(6).toInt();
    ledGreen(constrain(val, 0, 255));
    displayScanning("GREEN");
    if (isWiFiConnected) {
      webSocket.broadcastTXT("{\"status\":\"SCANNING\",\"color\":\"GREEN\"}");
    }
    Serial.println("LED_OK");
  }
  else if (cmd.startsWith("LED:B,")) {
    int val = cmd.substring(6).toInt();
    ledBlue(constrain(val, 0, 255));
    displayScanning("BLUE");
    if (isWiFiConnected) {
      webSocket.broadcastTXT("{\"status\":\"SCANNING\",\"color\":\"BLUE\"}");
    }
    Serial.println("LED_OK");
  }

  // ----- 檢測結果 -----
  else if (cmd.startsWith("RESULT:DEFECT,")) {
    String data = cmd.substring(14);
    if (parseDefectResult(data)) {
      currentState = STATE_DEFECT;
      displayDefectResult();
      startAlarm();
      if (isWiFiConnected && defectCount > 0) {
        int lastIdx = defectCount - 1;
        String json = "{\"status\":\"DEFECT\",\"count\":" + String(defectCount) + 
                       ",\"type\":\"" + defects[lastIdx].type + 
                       "\",\"conf\":" + String(defects[lastIdx].confidence) + 
                       ",\"x\":" + String(defects[lastIdx].x) + 
                       ",\"y\":" + String(defects[lastIdx].y) + "}";
        webSocket.broadcastTXT(json);
      }
    }
    Serial.println("RESULT_ACK");
  }
  else if (cmd == "RESULT:OK") {
    currentState = STATE_PASS;
    defectCount = 0;
    displayPass();
    buzzerBeep(100);   // 短嗶表示完成
    if (isWiFiConnected) {
      webSocket.broadcastTXT("{\"status\":\"OK\"}");
    }
    Serial.println("RESULT_ACK");
  }
  else if (cmd == "RESULT:DONE") {
    // 檢測序列完成
    if (currentState == STATE_DEFECT) {
      displayDefectResult();
    } else {
      displayPass();
    }
    ledOff();
    Serial.println("DONE_ACK");

    // 5 秒後回到 READY 畫面
    delay(5000);
    stopAlarm();
    currentState = STATE_IDLE;
    defectCount = 0;
    displayReady();
    if (isWiFiConnected) {
      webSocket.broadcastTXT("{\"status\":\"READY\"}");
    }
  }

  // ----- 蜂鳴器控制 -----
  else if (cmd == "BUZZ:ON") {
    tone(BUZZER_PIN, 2000);
    Serial.println("BUZZ_OK");
  }
  else if (cmd == "BUZZ:OFF") {
    stopAlarm();
    Serial.println("BUZZ_OK");
  }

  // ----- 掃描狀態 -----
  else if (cmd == "SCANNING") {
    currentState = STATE_SCANNING;
    defectCount = 0;
    displayScanning("...");
    if (isWiFiConnected) {
      webSocket.broadcastTXT("{\"status\":\"SCANNING\",\"color\":\"...\"}");
    }
    Serial.println("SCAN_ACK");
  }

  // ----- OLED 訊息 -----
  else if (cmd.startsWith("MSG:")) {
    String msg = cmd.substring(4);
    displayMessage(msg);
    Serial.println("MSG_OK");
  }

  // ----- 連線測試 -----
  else if (cmd == "PING") {
    Serial.println("PONG");
  }
  else if (cmd == "STATUS") {
    Serial.print("STATUS:OK,STATE=");
    Serial.println(currentState);
  }

  else {
    Serial.print("CTRL_ERROR:Unknown cmd: ");
    Serial.println(cmd);
  }
}

// ==================== Arduino Setup ====================
void setup() {
  // 初始化 USB Serial（與 PC 通訊）
  Serial.begin(115200);
  delay(500);

  Serial.println();
  Serial.println("================================");
  Serial.println("  ESP32S Defect Detection");
  Serial.println("  Controller Module v1.0");
  Serial.println("================================");

  // 初始化按鈕（內部上拉）
  pinMode(BUTTON_PIN, INPUT_PULLUP);

  // 初始化蜂鳴器
  pinMode(BUZZER_PIN, OUTPUT);
  digitalWrite(BUZZER_PIN, LOW);

  // 初始化 LED PWM
  initLEDs();
  Serial.println("INFO:LEDs initialized");

  // 初始化 OLED
  Wire.begin(21, 22);   // SDA=21, SCL=22
  if (!display.begin(SSD1306_SWITCHCAPVCC, OLED_ADDR)) {
    Serial.println("CTRL_WARNING:OLED not found, running without OLED.");
    hasOLED = false;
  } else {
    Serial.println("INFO:OLED initialized");
    hasOLED = true;
    displayInit();
    delay(1000);
  }

  // ----- 啟動 Wi-Fi AP 熱點模式 -----
  if (hasOLED) {
    display.clearDisplay();
    display.setTextSize(1);
    display.setTextColor(SSD1306_WHITE);
    display.setCursor(0, 0);
    display.println(F("= Starting Wi-Fi AP ="));
    display.drawLine(0, 10, 127, 10, SSD1306_WHITE);
    display.setCursor(0, 16);
    display.print(F("SSID: "));
    display.println(ap_ssid);
    display.println(F("Creating hotspot..."));
    display.display();
  }

  Serial.print("INFO:Starting SoftAP: ");
  Serial.println(ap_ssid);
  
  // 啟動 AP 模式 (自建熱點)
  WiFi.softAP(ap_ssid, ap_password);
  isWiFiConnected = true; // 在 AP 模式下，服務視同隨時啟用
  
  IPAddress apIP = WiFi.softAPIP();
  Serial.print("INFO:AP IP address: ");
  Serial.println(apIP);

  // 啟動 mDNS (defect-detector.local)
  if (MDNS.begin("defect-detector")) {
    Serial.println("INFO:mDNS responder started (defect-detector.local)");
  }

  // 啟動 HTTP 伺服器
  server.begin();
  Serial.println("INFO:HTTP server started on port 80");

  // 啟動 WebSocket 伺服器
  webSocket.begin();
  webSocket.onEvent(webSocketEvent);
  Serial.println("INFO:WebSocket server started on port 81");

  if (hasOLED) {
    display.clearDisplay();
    display.setCursor(0, 0);
    display.println(F("= Wi-Fi Hotspot OK ="));
    display.drawLine(0, 10, 127, 10, SSD1306_WHITE);
    display.setTextSize(1);
    display.setCursor(0, 16);
    display.print(F("Connect to:"));
    display.println(ap_ssid);
    display.print(F("PWD:"));
    display.println(ap_password);
    display.println(F("URL:http://"));
    display.println(apIP.toString());
    display.display();
    delay(4000); // 讓使用者看清連線資訊
  }

  // 開機自檢：LED 依序亮滅
  Serial.println("INFO:Running self-test...");
  ledRed();   delay(300);
  ledGreen(); delay(300);
  ledBlue();  delay(300);
  ledAll();   delay(300);
  ledOff();

  // 蜂鳴器自檢
  buzzerBeep(100);
  delay(100);
  buzzerBeep(100);

  Serial.println("INFO:Self-test complete");
  Serial.println("CTRL_READY");

  // 顯示就緒畫面
  displayReady();
}

// ==================== Arduino Loop ====================
void loop() {
  // --- 1. 檢查按鈕 ---
  if (digitalRead(BUTTON_PIN) == LOW) {
    unsigned long now = millis();
    if (now - lastButtonPress > DEBOUNCE_MS) {
      lastButtonPress = now;
      Serial.println("BTN_PRESSED");
      buzzerBeep(50);   // 按鈕回饋音

      // OLED 顯示等待中
      displayMessage("Button pressed!\nWaiting for PC...");
    }
  }

  // --- 2. 處理 Serial 指令 ---
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n' || c == '\r') {
      if (inputBuffer.length() > 0) {
        processCommand(inputBuffer);
        inputBuffer = "";
      }
    } else {
      inputBuffer += c;
      if (inputBuffer.length() > 128) {
        inputBuffer = "";
        Serial.println("CTRL_ERROR:Command too long");
      }
    }
  }

  // --- 3. 更新蜂鳴器 ---
  updateBuzzer();

  // --- 4. WiFi/WebSocket 更新 ---
  if (isWiFiConnected) {
    webSocket.loop();
    handleHTTPServer();
  }

  delay(10);
}
