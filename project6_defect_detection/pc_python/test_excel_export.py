"""
測試 Excel 匯出功能（不需要硬體）
模擬瑕疵檢測結果，產生 Excel 報告
"""
import os
import sys

# 確保能找到同目錄的模組
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from defect_detector import DefectDetectionSystem, EXCEL_DIR

# ---- 建立假的系統物件（跳過 Serial 連線）----
class MockExcelTest:
    def __init__(self):
        self.mode = "single"
        self.images = {'red': None, 'green': None, 'blue': None, 'white': None}
        os.makedirs(EXCEL_DIR, exist_ok=True)
        # 借用真正的 export 方法
        self.export_defects_to_excel = DefectDetectionSystem.export_defects_to_excel.__get__(self)

    def test_single_mode(self):
        """測試單面板模式的 Excel 匯出"""
        print("=" * 40)
        print("  Test 1: Single Panel Mode")
        print("=" * 40)

        self.mode = "single"
        fake_defects = [
            {'x': 120, 'y': 85,  'w': 30, 'h': 12, 'type': 'scratch',  'confidence': 0.92, 'area': 360},
            {'x': 245, 'y': 190, 'w': 15, 'h': 14, 'type': 'spot',     'confidence': 0.78, 'area': 210},
            {'x': 310, 'y': 55,  'w': 22, 'h': 18, 'type': 'crack',    'confidence': 0.85, 'area': 396},
            {'x': 88,  'y': 300, 'w': 45, 'h': 40, 'type': 'stain',    'confidence': 0.65, 'area': 1800},
            {'x': 400, 'y': 210, 'w': 8,  'h': 7,  'type': 'point',    'confidence': 0.55, 'area': 56},
        ]

        result = self.export_defects_to_excel(fake_defects)
        if result:
            print(f"  [OK] Excel file created successfully!")
            print(f"  [OK] Path: {os.path.abspath(result)}")
        else:
            print(f"  [FAIL] Excel export failed!")
        return result

    def test_9panel_mode(self):
        """測試 3x3 面板模式的 Excel 匯出"""
        print("\n" + "=" * 40)
        print("  Test 2: 9-Panel Mode")
        print("=" * 40)

        self.mode = "9panel"
        fake_defects = [
            {'x': 50,  'y': 40,  'w': 20, 'h': 10, 'type': 'scratch', 'confidence': 0.90, 'area': 200},
            {'x': 300, 'y': 150, 'w': 12, 'h': 11, 'type': 'spot',    'confidence': 0.82, 'area': 132},
            {'x': 500, 'y': 350, 'w': 35, 'h': 30, 'type': 'stain',   'confidence': 0.71, 'area': 1050},
        ]

        result = self.export_defects_to_excel(fake_defects)
        if result:
            print(f"  [OK] Excel file created successfully!")
            print(f"  [OK] Path: {os.path.abspath(result)}")
        else:
            print(f"  [FAIL] Excel export failed!")
        return result


if __name__ == "__main__":
    print("\n  Excel Export Test\n")

    tester = MockExcelTest()
    f1 = tester.test_single_mode()
    f2 = tester.test_9panel_mode()

    print("\n" + "=" * 40)
    if f1 and f2:
        print("  ALL TESTS PASSED!")
        print(f"  Check folder: {os.path.abspath(EXCEL_DIR)}")
    else:
        print("  SOME TESTS FAILED!")
    print("=" * 40)
