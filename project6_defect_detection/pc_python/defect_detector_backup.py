"""
=============================================================
 PC 端瑕疵檢測程式
 Surface Defect Detection System - PC AI Module
=============================================================

 功能：
   1. 透過 USB Serial 與 ESP32-CAM 和 ESP32S 通訊
   2. 控制 ESP32S 切換 R/G/B LED 光源
   3. 指揮 ESP32-CAM 拍照並接收影像
   4. 使用 OpenCV 進行瑕疵檢測（顏色閾值 + 輪廓偵測）
   5. 將檢測結果回傳 ESP32S 顯示
   6. 支援單面板與 3×3 拼接面板模式

 使用方式：
   python defect_detector.py --cam COM3 --ctrl COM4
   python defect_detector.py --cam COM3 --ctrl COM4 --mode 9panel

 快捷鍵（OpenCV 視窗）：
   SPACE / Enter：啟動檢測
   1：單面板模式
   9：3×3 拼接模式
   S：儲存當前影像
   R：僅切換紅光拍照
   G：僅切換綠光拍照
   B：僅切換藍光拍照
   Q / ESC：退出

 通訊協議：見 ESP32-CAM 及 ESP32S 韌體說明
=============================================================
"""

import serial
import serial.tools.list_ports
import cv2
import numpy as np
import time
import argparse
import os
import sys
from datetime import datetime

# YOLOv8 AI 模型（可選，若未安裝則使用傳統 OpenCV 檢測）
try:
    from ultralytics import YOLO
    HAS_YOLO = True
except ImportError:
    HAS_YOLO = False


# ==================== 設定常數 ====================
BAUD_RATE = 115200
SERIAL_TIMEOUT = 5        # Serial 讀取超時（秒）
IMAGE_READ_TIMEOUT = 10   # 影像接收超時（秒）
LED_SETTLE_TIME = 0.3     # LED 切換後等待穩定時間（秒）

# 瑕疵檢測參數
MIN_DEFECT_AREA = 10       # 最小瑕疵面積（下修，增加靈敏度）
MAX_DEFECT_AREA = 50000    # 最大瑕疵面積
BLUR_KERNEL_SIZE = 3       # 模糊核大小（下修，保留更多細節）
THRESH_BLOCK_SIZE = 11     # 區塊大小（縮小，提高局部敏感度）
THRESH_C = 2               # 閾值補償（從 8 大幅下修，更容易抓到暗點）

# 3×3 面板網格設定
GRID_ROWS = 3
GRID_COLS = 3

# 儲存路徑
SAVE_DIR = "captured_images"

# AI 模型權重路徑（由 train_yolo.py 訓練後自動產生）
MODEL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "best.pt")

# YOLOv8 類別名稱對照（與 dataset.yaml 中的定義一致）
YOLO_CLASS_NAMES = {0: "point", 1: "square", 2: "circle", 3: "line_h", 4: "line_v"}

# AI 推論信心度閾值（極度下修至 0.02，強迫 AI 顯示所有懷疑的目標）
AI_CONFIDENCE_THRESHOLD = 0.02


class SerialConnection:
    """Serial 連線管理器"""

    def __init__(self, port, baud=BAUD_RATE, name="Device"):
        self.port = port
        self.baud = baud
        self.name = name
        self.ser = None

    def connect(self):
        """建立串列連線"""
        try:
            self.ser = serial.Serial(
                port=self.port,
                baudrate=self.baud,
                timeout=SERIAL_TIMEOUT,
                write_timeout=SERIAL_TIMEOUT
            )
            # 確保 DTR/RTS 狀態正確，避免 ESP32 卡在 Reset 或 Bootloader 模式
            self.ser.setDTR(False)
            self.ser.setRTS(False)
            
            time.sleep(2.5)  # 等待 ESP32 完整開機 (相機模組需要較長的時間)
            self.flush()
            print(f"[OK] {self.name} connected on {self.port}")
            return True
        except serial.SerialException as e:
            print(f"[ERROR] Cannot connect to {self.name} on {self.port}: {e}")
            return False

    def disconnect(self):
        """關閉串列連線"""
        if self.ser and self.ser.is_open:
            self.ser.close()
            print(f"[INFO] {self.name} disconnected")

    def send(self, cmd):
        """發送指令"""
        if self.ser and self.ser.is_open:
            self.ser.write(f"{cmd}\n".encode('ascii'))
            self.ser.flush()

    def readline(self, timeout=None):
        """讀取一行回應"""
        if self.ser and self.ser.is_open:
            if timeout:
                old_timeout = self.ser.timeout
                self.ser.timeout = timeout
            try:
                line = self.ser.readline().decode('ascii', errors='ignore').strip()
                return line
            except Exception:
                return ""
            finally:
                if timeout:
                    self.ser.timeout = old_timeout
        return ""

    def read_bytes(self, count):
        """讀取指定數量的位元組"""
        if self.ser and self.ser.is_open:
            return self.ser.read(count)
        return b""

    def flush(self):
        """清空緩衝區"""
        if self.ser and self.ser.is_open:
            self.ser.reset_input_buffer()
            self.ser.reset_output_buffer()

    def wait_for(self, expected, timeout=5):
        """等待特定回應"""
        start = time.time()
        while time.time() - start < timeout:
            line = self.readline(timeout=0.5)
            if line:
                print(f"  [{self.name}] {line}")
                if expected in line:
                    return line
        return None

    @property
    def is_connected(self):
        return self.ser and self.ser.is_open


class DefectDetector:
    """瑕疵檢測器（支援 AI 模型 + 傳統 OpenCV 雙模式）"""

    def __init__(self, model_path=None):
        self.min_area = MIN_DEFECT_AREA
        self.max_area = MAX_DEFECT_AREA

        # 嘗試載入 YOLOv8 AI 模型
        self.ai_model = None
        self.use_ai = False
        _model_path = model_path or MODEL_PATH

        if HAS_YOLO and os.path.exists(_model_path):
            try:
                self.ai_model = YOLO(_model_path)
                self.use_ai = True
                print(f"[AI] YOLOv8 model loaded: {_model_path}")
                print(f"[AI] AI-based detection ENABLED")
            except Exception as e:
                print(f"[WARN] Failed to load YOLO model: {e}")
                print(f"[INFO] Falling back to OpenCV detection")
        elif HAS_YOLO:
            print(f"[INFO] No AI model found at {_model_path}")
            print(f"[INFO] Run 'python train_yolo.py' to train a model")
            print(f"[INFO] Using OpenCV-based detection")
        else:
            print(f"[INFO] ultralytics not installed, using OpenCV-based detection")

    def detect(self, image, led_color="white"):
        """
        在影像中檢測瑕疵（自動選擇 AI 或 OpenCV 模式）

        Args:
            image: BGR 格式的 OpenCV 影像
            led_color: 當前 LED 顏色 ("red", "green", "blue", "white")

        Returns:
            defects: 瑕疵列表 [{'x', 'y', 'w', 'h', 'type', 'confidence'}]
            debug_img: 除錯用影像（標記了檢測過程）
        """
        if image is None:
            return [], None

        if self.use_ai and self.ai_model is not None:
            return self._detect_ai(image, led_color)
        else:
            return self._detect_opencv(image, led_color)

    def _detect_ai(self, image, led_color="white"):
        """
        使用 YOLOv8 AI 模型進行瑕疵檢測

        Args:
            image: BGR 格式的 OpenCV 影像
            led_color: 當前 LED 顏色

        Returns:
            defects: 瑕疵列表
            debug_img: 除錯用影像
        """
        h, w = image.shape[:2]

        # 執行 YOLO 推論（移除 imgsz=256 限制，讓它用更高解析度看細節）
        results = self.ai_model.predict(
            source=image,
            conf=AI_CONFIDENCE_THRESHOLD,
            verbose=False,
        )

        defects = []

        if results and len(results) > 0:
            result = results[0]
            boxes = result.boxes

            if boxes is not None and len(boxes) > 0:
                for box in boxes:
                    # 取得 bounding box 座標（xyxy 格式）
                    x1, y1, x2, y2 = box.xyxy[0].cpu().numpy().astype(int)
                    conf = float(box.conf[0].cpu().numpy())
                    cls_id = int(box.cls[0].cpu().numpy())

                    # 類別名稱對照
                    defect_type = YOLO_CLASS_NAMES.get(cls_id, f"unknown_{cls_id}")

                    # 計算中心座標和寬高
                    cx = (x1 + x2) // 2
                    cy = (y1 + y2) // 2
                    bw = x2 - x1
                    bh = y2 - y1

                    defects.append({
                        'x': cx,
                        'y': cy,
                        'w': bw,
                        'h': bh,
                        'type': defect_type,
                        'confidence': round(conf, 2),
                        'area': bw * bh,
                    })

        # 依信心度排序
        defects.sort(key=lambda d: d['confidence'], reverse=True)

        # 建立除錯影像（AI 模式）
        debug_img = self._create_ai_debug_image(image.copy(), defects, led_color)

        return defects, debug_img

    def _create_ai_debug_image(self, image, defects, led_color="white"):
        """建立 AI 檢測模式的除錯視覺化影像"""
        h, w = image.shape[:2]
        result_img = image.copy()

        # 為每種瑕疵類型分配不同顏色
        type_colors = {
            'point':  (0, 255, 255),   # 黃色
            'square': (0, 0, 255),     # 紅色
            'circle': (255, 0, 255),   # 洋紅
            'line_h': (0, 255, 0),     # 綠色
            'line_v': (255, 165, 0),   # 橘色
        }

        for d in defects:
            color = type_colors.get(d['type'], (0, 0, 255))

            # 繪製外接矩形
            x1 = d['x'] - d['w'] // 2
            y1 = d['y'] - d['h'] // 2
            cv2.rectangle(result_img, (x1, y1), (x1 + d['w'], y1 + d['h']), color, 2)

            # 繪製中心十字
            cv2.drawMarker(result_img, (d['x'], d['y']), (0, 255, 255),
                          cv2.MARKER_CROSS, 10, 1)

            # 標記類型和信心度
            label = f"{d['type']} {d['confidence']:.0%}"
            # 文字背景
            (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.45, 1)
            cv2.rectangle(result_img, (x1, y1 - th - 6), (x1 + tw + 4, y1), color, -1)
            cv2.putText(result_img, label, (x1 + 2, y1 - 4),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1)

        # 左上角統計資訊
        mode_label = "[AI] YOLOv8"
        cv2.putText(result_img, mode_label, (10, 20),
                   cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 0), 2)
        status = f"Defects: {len(defects)} | LED: {led_color.upper()}"
        cv2.putText(result_img, status, (10, 42),
                   cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)

        # 圖例（右下角）
        legend_y = h - 10 - len(type_colors) * 18
        for name, clr in type_colors.items():
            cv2.rectangle(result_img, (w - 100, legend_y), (w - 88, legend_y + 12), clr, -1)
            cv2.putText(result_img, name, (w - 84, legend_y + 11),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.35, (200, 200, 200), 1)
            legend_y += 18

        return result_img

    def _detect_opencv(self, image, led_color="white"):
        """
        使用傳統 OpenCV 演算法進行瑕疵檢測（備用模式）

        Args:
            image: BGR 格式的 OpenCV 影像
            led_color: 當前 LED 顏色 ("red", "green", "blue", "white")

        Returns:
            defects: 瑕疵列表 [{'x', 'y', 'w', 'h', 'type', 'confidence', 'contour'}]
            debug_img: 除錯用影像（標記了檢測過程）
        """
        h, w = image.shape[:2]

        # 1. 根據 LED 顏色提取對應通道
        if led_color == "red":
            # 紅光照射 → 提取紅色通道（瑕疵在此通道最明顯）
            channel = image[:, :, 2]   # BGR 中的 R 通道
        elif led_color == "green":
            channel = image[:, :, 1]   # G 通道
        elif led_color == "blue":
            channel = image[:, :, 0]   # B 通道
        else:
            # 白光或預設：轉灰階
            channel = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

        # 2. 高斯模糊去雜訊
        blurred = cv2.GaussianBlur(channel, (BLUR_KERNEL_SIZE, BLUR_KERNEL_SIZE), 0)

        # 3. 自適應閾值二值化（找出暗色瑕疵）
        # THRESH_BINARY_INV：暗色區域變白（前景），亮色變黑（背景）
        binary = cv2.adaptiveThreshold(
            blurred, 255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY_INV,
            THRESH_BLOCK_SIZE, THRESH_C
        )

        # 4. 形態學操作：去除小雜訊，連接相近的瑕疵
        kernel = np.ones((3, 3), np.uint8)
        binary = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel, iterations=1)   # 開運算去雜訊
        binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel, iterations=2)  # 閉運算連接

        # 5. 尋找輪廓
        contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        # 6. 篩選並分類瑕疵
        defects = []
        for contour in contours:
            area = cv2.contourArea(contour)

            # 面積過濾
            if area < self.min_area or area > self.max_area:
                continue

            # 取得外接矩形（提前取得，用於邊界過濾）
            bx, by, bw, bh = cv2.boundingRect(contour)

            # 過濾貼邊的輪廓（通常是 RGB 子像素邊界線，不是瑕疵）
            # 如果輪廓跨越整張影像的高度或寬度的 90% 以上，視為邊界線
            if bh > h * 0.9 or bw > w * 0.9:
                continue

            # 過濾完全貼在影像邊緣的輪廓
            if bx <= 1 or by <= 1 or (bx + bw) >= w - 1 or (by + bh) >= h - 1:
                # 只有在輪廓面積佔外接矩形比例很低時才跳過（細線）
                rect_area = bw * bh
                if area / (rect_area + 1) < 0.3:
                    continue

            # 使用上面已計算的外接矩形 (bx, by, bw, bh)
            x, y = bx, by
            aspect_ratio = max(bw, bh) / (min(bw, bh) + 1)

            # 根據形狀分類瑕疵類型
            if aspect_ratio > 4.0:
                defect_type = "scratch"    # 劃痕（長條形）
            elif aspect_ratio > 2.0:
                defect_type = "crack"      # 裂痕（中等長寬比）
            elif area > 500:
                defect_type = "stain"      # 污漬（大面積）
            else:
                defect_type = "spot"       # 斑點（小面積、接近正方形）

            # 計算信心度（基於面積和對比度）
            mask = np.zeros(channel.shape, dtype=np.uint8)
            cv2.drawContours(mask, [contour], -1, 255, -1)
            mean_val = cv2.mean(channel, mask=mask)[0]
            bg_mean = cv2.mean(channel)[0]
            contrast = abs(bg_mean - mean_val) / (bg_mean + 1)
            confidence = min(0.99, max(0.5, contrast * 2 + area / 5000))

            defects.append({
                'x': x + bw // 2,      # 中心 X
                'y': y + bh // 2,      # 中心 Y
                'w': bw,
                'h': bh,
                'type': defect_type,
                'confidence': round(confidence, 2),
                'area': area,
                'contour': contour
            })

        # 依面積排序（大的瑕疵優先）
        defects.sort(key=lambda d: d['area'], reverse=True)

        # 建立除錯影像
        debug_img = self._create_debug_image(image.copy(), binary, defects)

        return defects, debug_img

    def detect_multi_channel(self, red_img, green_img, blue_img):
        """
        多通道融合檢測（使用 R/G/B 三張影像）
        比單通道更準確，可以減少誤判

        Args:
            red_img, green_img, blue_img: 分別在紅/綠/藍光下拍攝的影像

        Returns:
            defects: 瑕疵列表
            combined_img: 融合後的影像
        """
        # 從各自影像中提取對應通道
        r_channel = red_img[:, :, 2] if red_img is not None else None
        g_channel = green_img[:, :, 1] if green_img is not None else None
        b_channel = blue_img[:, :, 0] if blue_img is not None else None

        # 至少需要一個通道
        channels = [c for c in [r_channel, g_channel, b_channel] if c is not None]
        if not channels:
            return [], None

        # 融合：取各通道的最小值（瑕疵在所有通道都是暗的）
        combined_gray = channels[0].copy()
        for c in channels[1:]:
            # 確保尺寸一致
            if c.shape != combined_gray.shape:
                c = cv2.resize(c, (combined_gray.shape[1], combined_gray.shape[0]))
            combined_gray = cv2.min(combined_gray, c)

        # 組合成彩色影像用於視覺化
        if len(channels) == 3:
            combined_img = cv2.merge([b_channel, g_channel, r_channel])
        else:
            combined_img = cv2.cvtColor(combined_gray, cv2.COLOR_GRAY2BGR)

        # 在融合灰階上做瑕疵檢測
        fake_bgr = cv2.cvtColor(combined_gray, cv2.COLOR_GRAY2BGR)
        defects, debug_img = self.detect(fake_bgr, led_color="white")

        return defects, combined_img

    def detect_9panel(self, image, defects_single):
        """
        3×3 拼接面板模式：將影像分成 9 個區域，標記每個區域的瑕疵

        Args:
            image: 完整影像
            defects_single: 已偵測到的瑕疵列表

        Returns:
            panel_defects: {panel_id: [defects]} 字典
        """
        h, w = image.shape[:2]
        cell_h = h // GRID_ROWS
        cell_w = w // GRID_COLS

        panel_defects = {}
        for i in range(GRID_ROWS):
            for j in range(GRID_COLS):
                panel_id = i * GRID_COLS + j + 1  # 1-9
                panel_defects[panel_id] = []

        for d in defects_single:
            # 判斷瑕疵位於哪個面板
            col = min(d['x'] // cell_w, GRID_COLS - 1)
            row = min(d['y'] // cell_h, GRID_ROWS - 1)
            panel_id = row * GRID_COLS + col + 1

            # 轉換為面板內座標
            local_defect = d.copy()
            local_defect['x'] = d['x'] - col * cell_w
            local_defect['y'] = d['y'] - row * cell_h
            local_defect['panel'] = panel_id
            panel_defects[panel_id].append(local_defect)

        return panel_defects

    def _create_debug_image(self, image, binary, defects):
        """建立除錯視覺化影像"""
        h, w = image.shape[:2]

        # 建立組合影像：原圖 + 二值化 + 標記結果
        binary_bgr = cv2.cvtColor(binary, cv2.COLOR_GRAY2BGR)
        result_img = image.copy()

        for d in defects:
            # 繪製外接矩形
            x, y = d['x'] - d['w']//2, d['y'] - d['h']//2
            color = (0, 0, 255)  # 紅色框

            cv2.rectangle(result_img, (x, y), (x + d['w'], y + d['h']), color, 2)

            # 繪製中心十字
            cv2.drawMarker(result_img, (d['x'], d['y']), (0, 255, 255),
                          cv2.MARKER_CROSS, 15, 2)

            # 標記類型和信心度
            label = f"{d['type']} {d['confidence']:.0%}"
            cv2.putText(result_img, label, (x, y - 8),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)

            # 繪製輪廓
            if 'contour' in d:
                cv2.drawContours(result_img, [d['contour']], -1, (0, 255, 0), 1)

        # 在左上角顯示統計
        status = f"Defects: {len(defects)}"
        cv2.putText(result_img, status, (10, 25),
                   cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)

        # 組合三張影像
        binary_bgr_resized = cv2.resize(binary_bgr, (w // 2, h // 2))
        result_resized = cv2.resize(result_img, (w // 2, h // 2))
        original_resized = cv2.resize(image, (w // 2, h // 2))

        top_row = np.hstack([original_resized, binary_bgr_resized])
        # 結果圖置中放在下排
        bottom_row = np.hstack([
            result_resized,
            np.zeros_like(result_resized, dtype=np.uint8)
        ])

        debug = np.vstack([top_row, bottom_row])
        return debug


class DefectDetectionSystem:
    """瑕疵檢測系統主控制類"""

    def __init__(self, cam_port, ctrl_port, mode="single"):
        self.cam = SerialConnection(cam_port, name="ESP32-CAM")
        self.ctrl = SerialConnection(ctrl_port, name="ESP32S-Ctrl")
        self.detector = DefectDetector()
        self.mode = mode    # "single" 或 "9panel"

        # 影像快取
        self.images = {
            'red': None,
            'green': None,
            'blue': None,
            'white': None
        }

        # 確保儲存目錄存在
        os.makedirs(SAVE_DIR, exist_ok=True)

    def connect(self):
        """連接兩個 ESP32"""
        print("\n" + "=" * 50)
        print("  Surface Defect Detection System")
        print("  PC AI Module v1.0")
        print("=" * 50)

        print(f"\n[INFO] Connecting to ESP32-CAM on {self.cam.port}...")
        if not self.cam.connect():
            return False

        print(f"[INFO] Connecting to ESP32S Controller on {self.ctrl.port}...")
        if not self.ctrl.connect():
            self.cam.disconnect()
            return False

        # 等待裝置就緒
        print("[INFO] Waiting for devices to be ready...")
        time.sleep(1)

        # 讀取啟動訊息
        self._drain_serial(self.cam)
        self._drain_serial(self.ctrl)

        # 測試連線
        self.cam.send("PING")
        resp = self.cam.wait_for("PONG", timeout=3)
        if not resp:
            print("[WARN] ESP32-CAM not responding to PING")
            
        # 強制設定為 QVGA 解析度 (避免供電不足導致相機崩潰)
        print("[INFO] Setting camera resolution to QVGA...")
        self.cam.send("SET_RES:1")
        time.sleep(0.5)
        self._drain_serial(self.cam)

        self.ctrl.send("PING")
        resp = self.ctrl.wait_for("PONG", timeout=3)
        if not resp:
            print("[WARN] ESP32S Controller not responding to PING")

        print("\n[OK] System ready!")
        print("[INFO] Press SPACE in the OpenCV window to start inspection")
        print("[INFO] Press Q to quit\n")
        return True

    def _drain_serial(self, conn):
        """讀取並顯示所有待讀取的訊息"""
        while True:
            line = conn.readline(timeout=0.2)
            if not line:
                break
            print(f"  [{conn.name}] {line}")

    def capture_image(self, led_color="white"):
        """
        控制 LED 並拍攝影像

        Args:
            led_color: "red", "green", "blue", "white", "off"

        Returns:
            image: OpenCV BGR 影像 or None
        """
        # 1. 切換 LED
        led_cmd = {
            "red": "LED:R",
            "green": "LED:G",
            "blue": "LED:B",
            "white": "LED:ALL",
            "off": "LED:OFF"
        }.get(led_color, "LED:OFF")

        print(f"  [LED] Switching to {led_color.upper()}...")
        self.ctrl.send(led_cmd)
        resp = self.ctrl.wait_for("LED_OK", timeout=3)
        if not resp:
            print(f"  [WARN] No LED_OK response")

        # 等待 LED 穩定（重要！LED 亮度需要時間穩定）
        time.sleep(LED_SETTLE_TIME)

        # 2. 拍攝影像
        print(f"  [CAM] Capturing image...")
        self.cam.flush()   # 清空舊資料
        self.cam.send("CAPTURE")

        # 3. 接收影像
        image = self._receive_image()

        if image is not None:
            self.images[led_color] = image.copy()
            print(f"  [CAM] Image received: {image.shape[1]}x{image.shape[0]}")
        else:
            print(f"  [CAM] Failed to receive image!")

        return image

    def _receive_image(self):
        """
        從 ESP32-CAM 接收 JPEG 影像

        Protocol: "IMG:<size>\n" + <raw JPEG bytes> + "\nIMG_OK\n"
        """
        start_time = time.time()

        # 等待影像標頭
        while time.time() - start_time < IMAGE_READ_TIMEOUT:
            line = self.cam.readline(timeout=2)
            if not line:
                continue

            if line.startswith("IMG:"):
                try:
                    img_size = int(line.split(':')[1])
                    print(f"  [CAM] Expecting {img_size} bytes...")

                    # 讀取影像資料
                    img_data = self._read_exact(self.cam, img_size)

                    if img_data is None or len(img_data) != img_size:
                        print(f"  [ERROR] Received {len(img_data) if img_data else 0}/{img_size} bytes")
                        return None

                    # 讀取結束確認
                    self.cam.readline(timeout=1)  # 可能的換行
                    end_line = self.cam.readline(timeout=1)

                    # 解碼 JPEG
                    nparr = np.frombuffer(img_data, np.uint8)
                    image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

                    if image is None:
                        print(f"  [ERROR] JPEG decode failed")
                        return None

                    return image

                except ValueError:
                    print(f"  [ERROR] Invalid image size: {line}")
                    continue

            elif line.startswith("CAM_ERROR"):
                print(f"  [ERROR] Camera error: {line}")
                return None

            elif line.startswith("INFO:"):
                print(f"  [{self.cam.name}] {line}")

        print(f"  [ERROR] Image receive timeout ({IMAGE_READ_TIMEOUT}s)")
        return None

    def _read_exact(self, conn, count):
        """準確讀取指定數量的位元組"""
        data = b""
        remaining = count
        start_time = time.time()

        while remaining > 0 and time.time() - start_time < IMAGE_READ_TIMEOUT:
            chunk = conn.read_bytes(min(remaining, 4096))
            if chunk:
                data += chunk
                remaining -= len(chunk)
            else:
                time.sleep(0.01)

        return data if len(data) == count else None

    def run_inspection(self):
        """
        執行完整檢測序列：紅光 → 綠光 → 藍光 → 分析

        Returns:
            defects: 瑕疵列表
        """
        print("\n" + "=" * 40)
        print("  Starting Inspection Sequence")
        print("=" * 40)

        # 通知 ESP32S 開始掃描
        self.ctrl.send("SCANNING")
        self._drain_serial(self.ctrl)

        all_defects = []

        # 依序用三色 LED 拍攝
        for color in ["red", "green", "blue"]:
            print(f"\n--- {color.upper()} Light ---")
            img = self.capture_image(color)
            if img is not None:
                defects, _ = self.detector.detect(img, led_color=color)
                all_defects.extend(defects)
                print(f"  Defects in {color}: {len(defects)}")

        # 關閉 LED
        self.ctrl.send("LED:OFF")

        # 多通道融合分析（如果三張都有的話）
        if all([self.images.get(c) is not None for c in ['red', 'green', 'blue']]):
            print(f"\n--- Multi-channel Analysis ---")
            fused_defects, combined = self.detector.detect_multi_channel(
                self.images['red'],
                self.images['green'],
                self.images['blue']
            )
            print(f"  Fused defects: {len(fused_defects)}")

            # 使用融合結果（通常更準確）
            if fused_defects:
                all_defects = fused_defects

        # 去重（相鄰位置的瑕疵合併）
        all_defects = self._merge_nearby_defects(all_defects)

        # 3×3 面板模式
        if self.mode == "9panel" and all_defects:
            img_for_grid = self.images.get('red') or self.images.get('green') or self.images.get('blue')
            if img_for_grid is not None:
                panel_defects = self.detector.detect_9panel(img_for_grid, all_defects)
                print(f"\n--- 3x3 Panel Results ---")
                for pid, pdefects in panel_defects.items():
                    status = f"DEFECT ({len(pdefects)})" if pdefects else "OK"
                    print(f"  Panel {pid}: {status}")

        # 傳送結果至 ESP32S
        self._send_results(all_defects)

        print(f"\n{'=' * 40}")
        print(f"  Inspection Complete: {len(all_defects)} defect(s)")
        print(f"{'=' * 40}\n")

        return all_defects

    def _merge_nearby_defects(self, defects, distance_threshold=30):
        """合併相鄰的瑕疵偵測結果"""
        if len(defects) <= 1:
            return defects

        merged = []
        used = set()

        for i, d1 in enumerate(defects):
            if i in used:
                continue
            merged_defect = d1.copy()
            for j, d2 in enumerate(defects):
                if j <= i or j in used:
                    continue
                dist = np.sqrt((d1['x'] - d2['x'])**2 + (d1['y'] - d2['y'])**2)
                if dist < distance_threshold:
                    # 合併：擴展邊界
                    x1 = min(d1['x'] - d1['w']//2, d2['x'] - d2['w']//2)
                    y1 = min(d1['y'] - d1['h']//2, d2['y'] - d2['h']//2)
                    x2 = max(d1['x'] + d1['w']//2, d2['x'] + d2['w']//2)
                    y2 = max(d1['y'] + d1['h']//2, d2['y'] + d2['h']//2)
                    merged_defect['x'] = (x1 + x2) // 2
                    merged_defect['y'] = (y1 + y2) // 2
                    merged_defect['w'] = x2 - x1
                    merged_defect['h'] = y2 - y1
                    merged_defect['confidence'] = max(d1['confidence'], d2['confidence'])
                    used.add(j)
            merged.append(merged_defect)
            used.add(i)

        return merged

    def _send_results(self, defects):
        """將檢測結果傳送至 ESP32S"""
        if not defects:
            self.ctrl.send("RESULT:OK")
            self._drain_serial(self.ctrl)
        else:
            for d in defects[:MAX_DEFECTS_TO_SEND]:
                # 格式: RESULT:DEFECT,x,y,w,h,type,conf
                cmd = f"RESULT:DEFECT,{d['x']},{d['y']},{d['w']},{d['h']},{d['type']},{d['confidence']:.2f}"
                self.ctrl.send(cmd)
                time.sleep(0.1)  # 給 ESP32S 時間處理
                self._drain_serial(self.ctrl)

        # 發送完成信號
        time.sleep(0.3)
        self.ctrl.send("RESULT:DONE")
        self._drain_serial(self.ctrl)

    def save_images(self, prefix="inspection"):
        """儲存當前擷取的影像"""
        if not os.path.exists(SAVE_DIR):
            os.makedirs(SAVE_DIR, exist_ok=True)
            
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        for color, img in self.images.items():
            if img is not None:
                filename = f"{prefix}_{timestamp}_{color}.jpg"
                filepath = os.path.join(SAVE_DIR, filename)
                cv2.imwrite(filepath, img)
                print(f"  [SAVE] {filepath}")

    def run_gui(self):
        """
        執行 GUI 主迴圈（OpenCV 視窗）
        """
        print("[INFO] Opening display window...")
        cv2.namedWindow("Defect Detection System", cv2.WINDOW_NORMAL)
        cv2.resizeWindow("Defect Detection System", 800, 600)

        # 建立初始畫面
        canvas = self._create_splash_screen()
        cv2.imshow("Defect Detection System", canvas)

        while True:
            key = cv2.waitKey(100) & 0xFF

            # 檢查 ESP32S 按鈕
            if self.ctrl.is_connected:
                btn_line = self.ctrl.readline(timeout=0.05)
                if btn_line and "BTN_PRESSED" in btn_line:
                    print("[BTN] Button pressed! Starting inspection...")
                    self._run_and_display()

            # 鍵盤操作
            if key == ord(' ') or key == 13:   # SPACE 或 Enter
                self._run_and_display()

            elif key == ord('1'):
                self.mode = "single"
                print("[MODE] Switched to single panel mode")

            elif key == ord('9'):
                self.mode = "9panel"
                print("[MODE] Switched to 3x3 panel mode")

            elif key == ord('s') or key == ord('S'):
                self.save_images()

            elif key == ord('r') or key == ord('R'):
                self._capture_and_display("red")

            elif key == ord('g') or key == ord('G'):
                self._capture_and_display("green")

            elif key == ord('b') or key == ord('B'):
                self._capture_and_display("blue")

            elif key == ord('q') or key == ord('Q') or key == 27:   # Q 或 ESC
                break

        # 清理
        self.ctrl.send("LED:OFF")
        self.ctrl.send("BUZZ:OFF")
        cv2.destroyAllWindows()

    def _run_and_display(self):
        """執行檢測並顯示結果"""
        defects = self.run_inspection()

        # 顯示結果影像
        display_img = self._create_result_display(defects)
        if display_img is not None:
            cv2.imshow("Defect Detection System", display_img)

    def _capture_and_display(self, color):
        """單一顏色拍攝並顯示"""
        img = self.capture_image(color)
        if img is not None:
            defects, debug_img = self.detector.detect(img, led_color=color)
            if debug_img is not None:
                cv2.imshow("Defect Detection System", debug_img)
            else:
                cv2.imshow("Defect Detection System", img)
        self.ctrl.send("LED:OFF")

    def _create_splash_screen(self):
        """建立啟動畫面"""
        canvas = np.zeros((600, 800, 3), dtype=np.uint8)

        # 標題
        cv2.putText(canvas, "Surface Defect Detection System", (80, 100),
                   cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 255), 2)
        cv2.putText(canvas, "v1.0 - OpenCV Edition", (240, 140),
                   cv2.FONT_HERSHEY_SIMPLEX, 0.7, (128, 128, 128), 1)

        # 操作說明
        instructions = [
            ("SPACE / BTN", "Start full inspection (R+G+B)"),
            ("R / G / B", "Capture with single LED color"),
            ("1", "Single panel mode"),
            ("9", "3x3 panel mode"),
            ("S", "Save captured images"),
            ("Q / ESC", "Quit"),
        ]

        y = 220
        cv2.putText(canvas, "Controls:", (100, y),
                   cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 200, 0), 2)
        y += 40

        for key, desc in instructions:
            cv2.putText(canvas, f"  [{key}]", (100, y),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.55, (200, 200, 0), 1)
            cv2.putText(canvas, desc, (320, y),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.55, (200, 200, 200), 1)
            y += 30

        # 系統狀態
        y += 30
        cam_status = "Connected" if self.cam.is_connected else "Disconnected"
        ctrl_status = "Connected" if self.ctrl.is_connected else "Disconnected"
        cam_color = (0, 255, 0) if self.cam.is_connected else (0, 0, 255)
        ctrl_color = (0, 255, 0) if self.ctrl.is_connected else (0, 0, 255)

        cv2.putText(canvas, f"ESP32-CAM: {cam_status}", (100, y),
                   cv2.FONT_HERSHEY_SIMPLEX, 0.55, cam_color, 1)
        cv2.putText(canvas, f"ESP32S: {ctrl_status}", (450, y),
                   cv2.FONT_HERSHEY_SIMPLEX, 0.55, ctrl_color, 1)

        cv2.putText(canvas, f"Mode: {self.mode}", (100, y + 30),
                   cv2.FONT_HERSHEY_SIMPLEX, 0.55, (200, 200, 200), 1)

        return canvas

    def _create_result_display(self, defects):
        """建立結果顯示影像"""
        # 使用最後一張有效影像
        img = None
        for color in ['blue', 'green', 'red']:
            if self.images.get(color) is not None:
                img = self.images[color].copy()
                break

        if img is None:
            return None

        h, w = img.shape[:2]

        # 標記瑕疵
        for d in defects:
            x1 = d['x'] - d['w'] // 2
            y1 = d['y'] - d['h'] // 2
            x2 = x1 + d['w']
            y2 = y1 + d['h']

            # 紅色矩形
            cv2.rectangle(img, (x1, y1), (x2, y2), (0, 0, 255), 2)
            # 中心點
            cv2.drawMarker(img, (d['x'], d['y']), (0, 255, 255),
                          cv2.MARKER_CROSS, 15, 2)
            # 標籤
            label = f"{d['type']} ({d['x']},{d['y']}) {d['confidence']:.0%}"
            cv2.putText(img, label, (x1, y1 - 8),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 2)

        # 3×3 網格線（如果是拼接模式）
        if self.mode == "9panel":
            cell_w = w // GRID_COLS
            cell_h = h // GRID_ROWS
            for i in range(1, GRID_COLS):
                cv2.line(img, (i * cell_w, 0), (i * cell_w, h), (255, 255, 0), 1)
            for i in range(1, GRID_ROWS):
                cv2.line(img, (0, i * cell_h), (w, i * cell_h), (255, 255, 0), 1)
            # 面板編號
            for i in range(GRID_ROWS):
                for j in range(GRID_COLS):
                    pid = i * GRID_COLS + j + 1
                    cx = j * cell_w + 5
                    cy = i * cell_h + 15
                    cv2.putText(img, f"P{pid}", (cx, cy),
                               cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 0), 1)

        # 右側資訊面板
        panel = np.zeros((h, 250, 3), dtype=np.uint8)

        y = 30
        cv2.putText(panel, "Inspection Result", (10, y),
                   cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 1)
        y += 30

        if defects:
            cv2.putText(panel, f"DEFECT FOUND!", (10, y),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
            y += 25
            cv2.putText(panel, f"Count: {len(defects)}", (10, y),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)
            y += 30

            for i, d in enumerate(defects[:5]):  # 最多顯示5個
                cv2.putText(panel, f"#{i+1} {d['type']}", (10, y),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 200, 255), 1)
                y += 20
                cv2.putText(panel, f"  Pos:({d['x']},{d['y']})", (10, y),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.4, (180, 180, 180), 1)
                y += 20
                cv2.putText(panel, f"  Conf:{d['confidence']:.0%}", (10, y),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.4, (180, 180, 180), 1)
                y += 25
        else:
            cv2.putText(panel, "PASS - No Defects", (10, y),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 0), 2)

        # 組合
        result = np.hstack([img, panel])
        return result

    def disconnect(self):
        """中斷連線並清理"""
        if self.ctrl.is_connected:
            self.ctrl.send("LED:OFF")
            self.ctrl.send("BUZZ:OFF")
        self.cam.disconnect()
        self.ctrl.disconnect()


# ==================== 最大傳送瑕疵數 ====================
MAX_DEFECTS_TO_SEND = 5


# ==================== 工具函數 ====================
def list_serial_ports():
    """列出所有可用的 COM 埠"""
    ports = serial.tools.list_ports.comports()
    if not ports:
        print("[WARN] No serial ports found!")
        return []

    print("\nAvailable serial ports:")
    for i, port in enumerate(ports):
        print(f"  [{i}] {port.device} - {port.description}")
    return [p.device for p in ports]


def select_port(prompt, available_ports):
    """互動式選擇 COM 埠"""
    if not available_ports:
        return None

    while True:
        choice = input(f"\n{prompt} (enter port name or index): ").strip()
        if choice.upper().startswith("COM"):
            return choice.upper()
        try:
            idx = int(choice)
            if 0 <= idx < len(available_ports):
                return available_ports[idx]
        except ValueError:
            pass
        print("Invalid input. Please try again.")


# ==================== 主程式 ====================
def main():
    parser = argparse.ArgumentParser(
        description="Surface Defect Detection System - PC AI Module",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python defect_detector.py --cam COM3 --ctrl COM4
  python defect_detector.py --cam COM3 --ctrl COM4 --mode 9panel
  python defect_detector.py --list-ports
        """
    )
    parser.add_argument('--cam', type=str, help='ESP32-CAM serial port (e.g., COM3)')
    parser.add_argument('--ctrl', type=str, help='ESP32S Controller serial port (e.g., COM4)')
    parser.add_argument('--mode', type=str, default='single',
                       choices=['single', '9panel'],
                       help='Detection mode: single panel or 3x3 panel grid')
    parser.add_argument('--list-ports', action='store_true',
                       help='List available serial ports and exit')
    parser.add_argument('--min-area', type=int, default=MIN_DEFECT_AREA,
                       help=f'Minimum defect area in pixels (default: {MIN_DEFECT_AREA})')
    parser.add_argument('--baud', type=int, default=BAUD_RATE,
                       help=f'Serial baud rate (default: {BAUD_RATE})')

    args = parser.parse_args()

    # 列出可用 COM 埠
    if args.list_ports:
        list_serial_ports()
        return

    # 如果沒有指定 COM 埠，互動式選擇
    available_ports = list_serial_ports()

    cam_port = args.cam
    ctrl_port = args.ctrl

    if not cam_port:
        cam_port = select_port("Select ESP32-CAM port", available_ports)
        if not cam_port:
            print("[ERROR] No ESP32-CAM port selected. Exiting.")
            return

    if not ctrl_port:
        ctrl_port = select_port("Select ESP32S Controller port", available_ports)
        if not ctrl_port:
            print("[ERROR] No ESP32S Controller port selected. Exiting.")
            return

    if cam_port == ctrl_port:
        print("[ERROR] Camera and Controller cannot use the same port!")
        return

    # 建立系統
    system = DefectDetectionSystem(cam_port, ctrl_port, mode=args.mode)

    # 設定檢測參數
    system.detector.min_area = args.min_area

    # 連接裝置
    if not system.connect():
        print("[ERROR] Failed to connect. Please check connections and try again.")
        return

    try:
        # 執行 GUI 主迴圈
        system.run_gui()
    except KeyboardInterrupt:
        print("\n[INFO] Interrupted by user")
    except Exception as e:
        print(f"\n[ERROR] Unexpected error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        system.disconnect()
        print("[INFO] System shutdown complete.")


if __name__ == "__main__":
    main()
