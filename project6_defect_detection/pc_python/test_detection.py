"""
=============================================================
 離線測試腳本 - 不需要硬體就能測試瑕疵檢測演算法
 Offline Test Script - Test defect detection without hardware
=============================================================

 功能：
   1. 自動生成模擬的 RGB 面板影像（含瑕疵）
   2. 用 OpenCV 演算法偵測瑕疵
   3. 顯示偵測結果（標記框、座標、類型）
   4. 測試單面板和 3×3 拼接面板模式

 使用方式：
   python test_detection.py            # 基本測試
   python test_detection.py --mode 9panel    # 3×3 模式
   python test_detection.py --save           # 儲存測試影像
=============================================================
"""

import cv2
import numpy as np
import argparse
import os
import sys

# 加入同目錄的模組
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from defect_detector import DefectDetector


class PanelSimulator:
    """模擬 RGB 面板影像生成器"""

    def __init__(self, width=640, height=480):
        self.width = width
        self.height = height

    def create_rgb_panel(self, led_color="white", defects=None):
        """
        生成模擬的 RGB 面板影像

        Args:
            led_color: 模擬的 LED 顏色 ("red", "green", "blue", "white")
            defects: 要畫的瑕疵列表 [{'x', 'y', 'w', 'h', 'type'}]

        Returns:
            image: BGR 格式的 OpenCV 影像
        """
        img = np.zeros((self.height, self.width, 3), dtype=np.uint8)

        # 將面板分成 RGB 三個區域（模擬 LCD 子像素）
        stripe_w = self.width // 3

        # 根據 LED 顏色決定各區域的亮度
        if led_color == "red":
            # 紅光照射：紅色區域亮，其他暗
            img[:, :stripe_w] = [30, 30, 200]          # R 區 → 亮紅
            img[:, stripe_w:stripe_w*2] = [20, 40, 40] # G 區 → 暗
            img[:, stripe_w*2:] = [20, 20, 40]         # B 區 → 暗
        elif led_color == "green":
            # 綠光照射：綠色區域亮，其他暗
            img[:, :stripe_w] = [20, 40, 40]           # R 區 → 暗
            img[:, stripe_w:stripe_w*2] = [30, 200, 30] # G 區 → 亮綠
            img[:, stripe_w*2:] = [20, 40, 20]         # B 區 → 暗
        elif led_color == "blue":
            # 藍光照射：藍色區域亮，其他暗
            img[:, :stripe_w] = [40, 20, 20]           # R 區 → 暗
            img[:, stripe_w:stripe_w*2] = [40, 40, 20] # G 區 → 暗
            img[:, stripe_w*2:] = [200, 30, 30]        # B 區 → 亮藍
        else:
            # 白光：全部亮
            img[:, :stripe_w] = [60, 60, 220]          # R 區
            img[:, stripe_w:stripe_w*2] = [60, 220, 60] # G 區
            img[:, stripe_w*2:] = [220, 60, 60]        # B 區

        # 加入子像素格線（模擬像素間隙）
        for x in range(0, self.width, stripe_w):
            cv2.line(img, (x, 0), (x, self.height), (10, 10, 10), 1)

        # 加入一些隨機雜訊（模擬真實相機雜訊）
        noise = np.random.normal(0, 5, img.shape).astype(np.int16)
        img = np.clip(img.astype(np.int16) + noise, 0, 255).astype(np.uint8)

        # 畫瑕疵
        if defects:
            for d in defects:
                self._draw_defect(img, d)

        return img

    def _draw_defect(self, img, defect):
        """在影像上繪製模擬瑕疵"""
        x, y = defect['x'], defect['y']
        dtype = defect.get('type', 'scratch')

        if dtype == 'scratch':
            # 劃痕：一條長黑線
            length = defect.get('length', 80)
            angle = defect.get('angle', 0)
            thickness = defect.get('thickness', 3)
            dx = int(length * np.cos(np.radians(angle)))
            dy = int(length * np.sin(np.radians(angle)))
            cv2.line(img, (x - dx//2, y - dy//2), (x + dx//2, y + dy//2),
                    (5, 5, 5), thickness)

        elif dtype == 'spot':
            # 斑點：一個黑色圓點
            radius = defect.get('radius', 8)
            cv2.circle(img, (x, y), radius, (5, 5, 5), -1)

        elif dtype == 'crack':
            # 裂痕：不規則的黑色線條
            pts = []
            num_points = 6
            length = defect.get('length', 40)
            for i in range(num_points):
                px = x + int((i - num_points//2) * length / num_points)
                py = y + np.random.randint(-8, 8)
                pts.append([px, py])
            pts = np.array(pts, dtype=np.int32)
            cv2.polylines(img, [pts], False, (5, 5, 5), 2)

        elif dtype == 'stain':
            # 污漬：不規則的暗色區域
            size = defect.get('size', 25)
            # 用多個重疊的圓模擬不規則形狀
            for _ in range(5):
                cx = x + np.random.randint(-size//2, size//2)
                cy = y + np.random.randint(-size//2, size//2)
                r = np.random.randint(size//3, size//2)
                cv2.circle(img, (cx, cy), r, (8, 8, 8), -1)

    def create_9panel(self, led_color="white", panel_defects=None):
        """
        生成 3×3 拼接面板影像

        Args:
            led_color: LED 顏色
            panel_defects: {panel_id: [defects]} 字典

        Returns:
            image: 拼接後的影像
        """
        cell_w = self.width // 3
        cell_h = self.height // 3

        img = np.zeros((self.height, self.width, 3), dtype=np.uint8)

        for i in range(3):
            for j in range(3):
                panel_id = i * 3 + j + 1
                # 每個子面板
                sub_panel = self._create_sub_panel(cell_w, cell_h, led_color)

                # 加入該面板的瑕疵
                if panel_defects and panel_id in panel_defects:
                    for d in panel_defects[panel_id]:
                        self._draw_defect(sub_panel, d)

                # 放入大影像
                img[i*cell_h:(i+1)*cell_h, j*cell_w:(j+1)*cell_w] = sub_panel

        # 畫面板邊框
        for i in range(1, 3):
            cv2.line(img, (i*cell_w, 0), (i*cell_w, self.height), (80, 80, 80), 2)
            cv2.line(img, (0, i*cell_h), (self.width, i*cell_h), (80, 80, 80), 2)

        return img

    def _create_sub_panel(self, w, h, led_color):
        """建立單個子面板"""
        panel = np.zeros((h, w, 3), dtype=np.uint8)
        stripe = w // 3

        if led_color == "red":
            panel[:, :stripe] = [25, 25, 180]
            panel[:, stripe:stripe*2] = [15, 35, 35]
            panel[:, stripe*2:] = [15, 15, 35]
        elif led_color == "green":
            panel[:, :stripe] = [15, 35, 35]
            panel[:, stripe:stripe*2] = [25, 180, 25]
            panel[:, stripe*2:] = [15, 35, 15]
        elif led_color == "blue":
            panel[:, :stripe] = [35, 15, 15]
            panel[:, stripe:stripe*2] = [35, 35, 15]
            panel[:, stripe*2:] = [180, 25, 25]
        else:
            panel[:, :stripe] = [50, 50, 200]
            panel[:, stripe:stripe*2] = [50, 200, 50]
            panel[:, stripe*2:] = [200, 50, 50]

        # 加入雜訊
        noise = np.random.normal(0, 3, panel.shape).astype(np.int16)
        panel = np.clip(panel.astype(np.int16) + noise, 0, 255).astype(np.uint8)

        return panel


def test_single_panel(detector, save=False):
    """測試單面板瑕疵檢測"""
    print("\n" + "=" * 60)
    print("  TEST: Single Panel Defect Detection")
    print("=" * 60)

    sim = PanelSimulator(640, 480)

    # 定義要繪製的瑕疵
    test_defects = [
        {'x': 320, 'y': 200, 'type': 'scratch', 'length': 100, 'angle': 15, 'thickness': 3},
        {'x': 500, 'y': 350, 'type': 'spot', 'radius': 10},
        {'x': 150, 'y': 300, 'type': 'crack', 'length': 50},
    ]

    colors = ["red", "green", "blue"]
    all_images = {}
    all_defects_by_color = {}

    for color in colors:
        print(f"\n--- {color.upper()} LED ---")

        # 生成模擬影像
        img = sim.create_rgb_panel(led_color=color, defects=test_defects)
        all_images[color] = img

        # 執行瑕疵檢測
        defects, debug_img = detector.detect(img, led_color=color)
        all_defects_by_color[color] = defects

        print(f"  Detected defects: {len(defects)}")
        for i, d in enumerate(defects):
            print(f"    #{i+1}: {d['type']} at ({d['x']},{d['y']}) "
                  f"size={d['w']}x{d['h']} conf={d['confidence']:.0%}")

        # 顯示結果
        if debug_img is not None:
            cv2.imshow(f"Detection - {color.upper()} LED", debug_img)

        if save:
            os.makedirs("test_output", exist_ok=True)
            cv2.imwrite(f"test_output/panel_{color}.jpg", img)
            if debug_img is not None:
                cv2.imwrite(f"test_output/detection_{color}.jpg", debug_img)
            print(f"  Saved to test_output/")

    # 多通道融合測試
    print(f"\n--- Multi-channel Fusion ---")
    fused_defects, combined = detector.detect_multi_channel(
        all_images.get('red'),
        all_images.get('green'),
        all_images.get('blue')
    )
    print(f"  Fused defects: {len(fused_defects)}")
    for i, d in enumerate(fused_defects):
        print(f"    #{i+1}: {d['type']} at ({d['x']},{d['y']}) "
              f"size={d['w']}x{d['h']} conf={d['confidence']:.0%}")

    if combined is not None:
        cv2.imshow("Multi-channel Fusion", combined)
        if save:
            cv2.imwrite("test_output/fusion.jpg", combined)

    return all_images, fused_defects


def test_9panel(detector, save=False):
    """測試 3×3 拼接面板瑕疵檢測"""
    print("\n" + "=" * 60)
    print("  TEST: 3x3 Panel Grid Detection")
    print("=" * 60)

    sim = PanelSimulator(640, 480)

    # 在面板 2、5、7 上放置瑕疵
    panel_defects = {
        2: [{'x': 80, 'y': 60, 'type': 'scratch', 'length': 50, 'angle': 30, 'thickness': 2}],
        5: [{'x': 100, 'y': 80, 'type': 'spot', 'radius': 8}],
        7: [{'x': 60, 'y': 100, 'type': 'stain', 'size': 20}],
    }

    img = sim.create_9panel(led_color="white", panel_defects=panel_defects)

    # 執行瑕疵檢測
    defects, debug_img = detector.detect(img, led_color="white")
    print(f"\n  Total defects detected: {len(defects)}")

    # 分區分析
    h, w = img.shape[:2]
    cell_w, cell_h = w // 3, h // 3
    grid_defects = detector.detect_9panel(img, defects)

    print(f"\n  --- Panel-wise Results ---")
    for pid in range(1, 10):
        pdefects = grid_defects.get(pid, [])
        row, col = (pid - 1) // 3, (pid - 1) % 3
        status = f"DEFECT ({len(pdefects)})" if pdefects else "OK"
        expected = "DEFECT" if pid in panel_defects else "OK"
        match = "[OK]" if (bool(pdefects) == (pid in panel_defects)) else "[MISS]"
        print(f"    Panel {pid} [{row},{col}]: {status:20s} (expected: {expected}) {match}")

    # 標記面板結果
    result_img = img.copy()
    for i in range(1, 3):
        cv2.line(result_img, (i*cell_w, 0), (i*cell_w, h), (255, 255, 0), 2)
        cv2.line(result_img, (0, i*cell_h), (w, i*cell_h), (255, 255, 0), 2)

    for pid in range(1, 10):
        row, col = (pid - 1) // 3, (pid - 1) % 3
        cx = col * cell_w + 5
        cy = row * cell_h + 20
        pdefects = grid_defects.get(pid, [])
        color = (0, 0, 255) if pdefects else (0, 255, 0)
        label = f"P{pid}: {'NG' if pdefects else 'OK'}"
        cv2.putText(result_img, label, (cx, cy),
                   cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)

    # 標記瑕疵
    for d in defects:
        x1, y1 = d['x'] - d['w']//2, d['y'] - d['h']//2
        cv2.rectangle(result_img, (x1, y1), (x1 + d['w'], y1 + d['h']), (0, 0, 255), 2)
        cv2.drawMarker(result_img, (d['x'], d['y']), (0, 255, 255),
                      cv2.MARKER_CROSS, 12, 2)

    cv2.imshow("3x3 Panel Grid Result", result_img)

    if save:
        os.makedirs("test_output", exist_ok=True)
        cv2.imwrite("test_output/9panel_input.jpg", img)
        cv2.imwrite("test_output/9panel_result.jpg", result_img)
        print(f"\n  Saved to test_output/")

    return grid_defects


def test_no_defect(detector):
    """測試無瑕疵面板（應該回報 OK）"""
    print("\n" + "=" * 60)
    print("  TEST: Clean Panel (No Defects)")
    print("=" * 60)

    sim = PanelSimulator(640, 480)

    # 生成無瑕疵的面板
    img = sim.create_rgb_panel(led_color="white", defects=None)

    defects, debug_img = detector.detect(img, led_color="white")

    if len(defects) == 0:
        print(f"  [OK] PASS: No false positives! (0 defects)")
    else:
        print(f"  [FAIL] FAIL: {len(defects)} false positive(s) detected")
        for d in defects:
            print(f"    False positive: {d['type']} at ({d['x']},{d['y']}) area={d['area']}")

    cv2.imshow("Clean Panel Test", img)

    return len(defects) == 0


def test_sensitivity(detector):
    """測試不同大小瑕疵的檢測靈敏度"""
    print("\n" + "=" * 60)
    print("  TEST: Detection Sensitivity")
    print("=" * 60)

    sim = PanelSimulator(640, 480)

    sizes = [
        ("Very small scratch", {'x': 100, 'y': 240, 'type': 'scratch', 'length': 15, 'angle': 0, 'thickness': 1}),
        ("Small scratch",      {'x': 200, 'y': 240, 'type': 'scratch', 'length': 30, 'angle': 0, 'thickness': 2}),
        ("Medium scratch",     {'x': 320, 'y': 240, 'type': 'scratch', 'length': 60, 'angle': 0, 'thickness': 3}),
        ("Large scratch",      {'x': 450, 'y': 240, 'type': 'scratch', 'length': 100, 'angle': 0, 'thickness': 4}),
        ("Small spot",         {'x': 550, 'y': 150, 'type': 'spot', 'radius': 5}),
        ("Large spot",         {'x': 550, 'y': 350, 'type': 'spot', 'radius': 15}),
    ]

    defect_list = [d for _, d in sizes]
    img = sim.create_rgb_panel(led_color="white", defects=defect_list)

    defects, debug_img = detector.detect(img, led_color="white")

    print(f"\n  Total detected: {len(defects)} / {len(sizes)} defects")
    print(f"\n  {'Name':<20} {'Detected':>10}")
    print(f"  {'-'*30}")

    for name, d_info in sizes:
        # 檢查是否被偵測到（比較座標）
        found = any(
            abs(det['x'] - d_info['x']) < 30 and abs(det['y'] - d_info['y']) < 30
            for det in defects
        )
        status = "[OK] YES" if found else "[--] NO"
        print(f"  {name:<20} {status:>10}")

    if debug_img is not None:
        cv2.imshow("Sensitivity Test", debug_img)

    return defects


def main():
    parser = argparse.ArgumentParser(description="Offline defect detection test")
    parser.add_argument('--mode', choices=['single', '9panel', 'all'], default='all',
                       help='Test mode')
    parser.add_argument('--save', action='store_true', help='Save test images')
    parser.add_argument('--min-area', type=int, default=100,
                       help='Minimum defect area for detection')
    args = parser.parse_args()

    print("\n" + "=" * 60)
    print("  Surface Defect Detection - Offline Test")
    print("  (No hardware required)")
    print("=" * 60)

    # 建立偵測器
    detector = DefectDetector()
    detector.min_area = args.min_area

    # 執行測試
    if args.mode in ('single', 'all'):
        test_single_panel(detector, save=args.save)

    if args.mode in ('9panel', 'all'):
        test_9panel(detector, save=args.save)

    if args.mode == 'all':
        test_no_defect(detector)
        test_sensitivity(detector)

    # 統整結果
    print("\n" + "=" * 60)
    print("  All tests complete!")
    print("  Press any key in the OpenCV window to close.")
    print("=" * 60)

    cv2.waitKey(0)
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
