"""클립보드 캡쳐 자동 저장 – PrintScreen/캡쳐하면 자동으로 image 폴더에 저장."""
import time
import os
from pathlib import Path
from PIL import ImageGrab

SAVE_DIR = Path(__file__).parent / "image"
SAVE_DIR.mkdir(exist_ok=True)

CHECK_INTERVAL = 0.5  # 초
last_image = None


def get_clipboard_image():
    try:
        return ImageGrab.grabclipboard()
    except Exception:
        return None


def main():
    global last_image
    print(f"[Clipboard Saver] 감시 시작 – 저장 경로: {SAVE_DIR}")
    print("[Clipboard Saver] 캡쳐(Win+Shift+S 등)하면 자동 저장됩니다. Ctrl+C로 종료.")

    seq = len(list(SAVE_DIR.glob("clip_*.png"))) + 1

    while True:
        img = get_clipboard_image()
        if img is not None:
            img_bytes = img.tobytes()
            if last_image != img_bytes:
                fname = f"clip_{seq:03d}.png"
                save_path = SAVE_DIR / fname
                img.save(save_path, "PNG")
                print(f"  -> 저장: {save_path}")
                last_image = img_bytes
                seq += 1
        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
