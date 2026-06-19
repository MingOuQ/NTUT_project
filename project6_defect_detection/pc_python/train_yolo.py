"""
=============================================================
 YOLOv8 模型訓練腳本
 Train YOLOv8 for Mini LED Defect Detection
=============================================================

 功能：
   1. 使用 mini_led_defect_dataset_rgb_label_v2 資料集
   2. 以 YOLOv8n（nano）預訓練權重進行遷移學習
   3. 訓練完成後自動複製最佳權重到 pc_python 目錄

 使用方式：
   python train_yolo.py                     # 使用預設參數訓練
   python train_yolo.py --epochs 200        # 自訂 epochs
   python train_yolo.py --device cpu        # 強制使用 CPU
   python train_yolo.py --resume            # 從上次中斷處繼續訓練

 前置需求：
   pip install ultralytics
=============================================================
"""

import argparse
import os
import shutil
import sys


def main():
    parser = argparse.ArgumentParser(
        description="Train YOLOv8 for Mini LED Defect Detection",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python train_yolo.py                    # Default training
  python train_yolo.py --epochs 200       # More epochs
  python train_yolo.py --batch 8          # Smaller batch (low VRAM)
  python train_yolo.py --device cpu       # Force CPU
  python train_yolo.py --model yolov8s.pt # Use small model instead of nano
        """
    )
    parser.add_argument('--epochs', type=int, default=300,
                        help='Number of training epochs (default: 100)')
    parser.add_argument('--batch', type=int, default=16,
                        help='Batch size (default: 16, reduce if GPU OOM)')
    parser.add_argument('--imgsz', type=int, default=256,
                        help='Input image size (default: 256, matching dataset)')
    parser.add_argument('--model', type=str, default='yolov8n.pt',
                        help='Base model to finetune (default: yolov8n.pt)')
    parser.add_argument('--device', type=str, default='',
                        help='Training device: "" for auto, "cpu", "0" for GPU 0')
    parser.add_argument('--resume', action='store_true',
                        help='Resume training from last checkpoint')
    parser.add_argument('--name', type=str, default='mini_led_defect',
                        help='Experiment name for run directory')
    parser.add_argument('--patience', type=int, default=20,
                        help='Early stopping patience (default: 20)')

    args = parser.parse_args()

    # 確認 ultralytics 已安裝
    try:
        from ultralytics import YOLO
    except ImportError:
        print("[ERROR] ultralytics 套件未安裝！")
        print("  請執行: pip install ultralytics")
        sys.exit(1)

    # 取得腳本所在目錄
    script_dir = os.path.dirname(os.path.abspath(__file__))
    dataset_yaml = os.path.join(script_dir, "dataset.yaml")

    if not os.path.exists(dataset_yaml):
        print(f"[ERROR] 找不到 dataset.yaml: {dataset_yaml}")
        sys.exit(1)

    print("\n" + "=" * 60)
    print("  YOLOv8 Mini LED Defect Detection - Training")
    print("=" * 60)
    print(f"  Base model  : {args.model}")
    print(f"  Dataset     : {dataset_yaml}")
    print(f"  Epochs      : {args.epochs}")
    print(f"  Batch size  : {args.batch}")
    print(f"  Image size  : {args.imgsz}")
    print(f"  Device      : {args.device or 'auto'}")
    print(f"  Patience    : {args.patience}")
    print("=" * 60 + "\n")

    # 載入模型
    if args.resume:
        # 從上次訓練的最後一個 checkpoint 繼續
        last_pt = os.path.join(script_dir, "runs", "detect", args.name, "weights", "last.pt")
        if os.path.exists(last_pt):
            print(f"[INFO] Resuming from: {last_pt}")
            model = YOLO(last_pt)
        else:
            print(f"[WARN] No checkpoint found at {last_pt}, starting fresh.")
            model = YOLO(args.model)
    else:
        print(f"[INFO] Loading base model: {args.model}")
        model = YOLO(args.model)

    # 開始訓練
    print("[INFO] Starting training...\n")
    results = model.train(
        data=dataset_yaml,
        epochs=args.epochs,
        batch=args.batch,
        imgsz=args.imgsz,
        device=args.device if args.device else None,
        name=args.name,
        project=os.path.join(script_dir, "runs", "detect"),
        patience=args.patience,
        save=True,
        save_period=10,         # 每 10 個 epoch 儲存一次 checkpoint
        plots=True,             # 生成訓練曲線圖
        verbose=True,
        exist_ok=True,          # 允許覆蓋同名實驗
    )

    # 訓練完成 — 複製最佳權重到主目錄
    print("\n" + "=" * 60)
    print("  Training Complete!")
    print("=" * 60)

    best_pt_src = os.path.join(script_dir, "runs", "detect", args.name, "weights", "best.pt")
    best_pt_dst = os.path.join(script_dir, "best.pt")

    if os.path.exists(best_pt_src):
        shutil.copy2(best_pt_src, best_pt_dst)
        print(f"\n[OK] Best model copied to: {best_pt_dst}")
        print(f"     File size: {os.path.getsize(best_pt_dst) / 1024 / 1024:.1f} MB")
    else:
        print(f"\n[WARN] best.pt not found at {best_pt_src}")
        print("  Training may not have completed successfully.")

    # 顯示驗證結果摘要
    print("\n--- Validation Summary ---")
    val_results = model.val()
    if val_results:
        print(f"  mAP50    : {val_results.box.map50:.4f}")
        print(f"  mAP50-95 : {val_results.box.map:.4f}")

    print(f"\n[INFO] Training logs and plots saved to:")
    print(f"  {os.path.join(script_dir, 'runs', 'detect', args.name)}")
    print(f"\n[INFO] To use the trained model, simply run defect_detector.py")
    print(f"  It will automatically load 'best.pt' if found.\n")


if __name__ == "__main__":
    main()
