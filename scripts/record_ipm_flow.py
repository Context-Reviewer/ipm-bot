"""Record one manual IPM interaction flow as timestamped CSV."""

from __future__ import annotations

import argparse
import csv
import time
import ctypes
from ctypes import wintypes
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from threading import Event, Lock

from pynput import keyboard, mouse

try:
    from PIL import ImageGrab
except ImportError:  # pragma: no cover - operational dependency
    ImageGrab = None


@dataclass(frozen=True, slots=True)
class RecordedEvent:
    t_rel: float
    event_type: str
    detail: str
    x: int | None
    y: int | None
    screenshot_path: str | None
    screenshot_note: str | None


@dataclass(frozen=True, slots=True)
class WindowSnapshot:
    title: str
    left: int
    top: int
    right: int
    bottom: int


class WindowCapture:
    def __init__(self, title_substring: str) -> None:
        self._title_substring = title_substring.casefold()
        self._user32 = ctypes.windll.user32

    def capture_foreground_window(self, output_path: Path) -> WindowSnapshot:
        if ImageGrab is None:
            raise RuntimeError("Pillow is required for screenshots. Install it with: pip install pillow")

        window_handle = self._user32.GetForegroundWindow()
        if not window_handle:
            raise RuntimeError("No foreground window is available for capture.")

        title = self._get_window_title(window_handle)
        if self._title_substring and self._title_substring not in title.casefold():
            raise RuntimeError(
                f"Foreground window title {title!r} does not match {self._title_substring!r}."
            )

        rect = wintypes.RECT()
        if not self._user32.GetWindowRect(window_handle, ctypes.byref(rect)):
            raise RuntimeError("Failed to query the foreground window bounds.")
        if rect.right <= rect.left or rect.bottom <= rect.top:
            raise RuntimeError("Foreground window bounds are invalid for capture.")

        image = ImageGrab.grab(bbox=(rect.left, rect.top, rect.right, rect.bottom), all_screens=True)
        image.save(output_path)
        return WindowSnapshot(
            title=title,
            left=rect.left,
            top=rect.top,
            right=rect.right,
            bottom=rect.bottom,
        )

    def _get_window_title(self, window_handle: int) -> str:
        title_length = self._user32.GetWindowTextLengthW(window_handle)
        buffer = ctypes.create_unicode_buffer(title_length + 1)
        self._user32.GetWindowTextW(window_handle, buffer, len(buffer))
        return buffer.value


class FlowRecorder:
    def __init__(self, window_title_substring: str) -> None:
        self.armed = False
        self.started = False
        self.start_time: float | None = None
        self.stop_event = Event()
        self.lock = Lock()
        self.events: list[RecordedEvent] = []
        self.capture = WindowCapture(window_title_substring)

        repo_root = Path(__file__).resolve().parents[1]
        out_dir = repo_root / "logs" / "input_recordings"
        out_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
        self.session_dir = out_dir / f"{stamp}_ipm_flow"
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self.output_path = self.session_dir / "events.csv"
        self.screenshot_dir = self.session_dir / "screenshots"
        self.screenshot_dir.mkdir(parents=True, exist_ok=True)

    def arm(self) -> None:
        with self.lock:
            self.armed = True
            self.started = False
            self.start_time = None
            self.events.clear()

    def stop(self) -> None:
        self.stop_event.set()

    def _start_on_first_click(self, x: int, y: int) -> None:
        self.started = True
        self.start_time = time.perf_counter()
        self._record_event(
            RecordedEvent(
                t_rel=0.000,
                event_type="mouse_click",
                detail="left_down_start",
                x=x,
                y=y,
                screenshot_path=None,
                screenshot_note=None,
            )
        )
        print(f"[START] t=0.000 on first left click at ({x}, {y})")

    def _elapsed(self) -> float:
        if self.start_time is None:
            return 0.0
        return round(time.perf_counter() - self.start_time, 3)

    def _record_event(self, event: RecordedEvent) -> None:
        screenshot_name = self._build_screenshot_name(len(self.events), event)
        screenshot_path = self.screenshot_dir / screenshot_name
        try:
            snapshot = self.capture.capture_foreground_window(screenshot_path)
            recorded_event = RecordedEvent(
                t_rel=event.t_rel,
                event_type=event.event_type,
                detail=event.detail,
                x=event.x,
                y=event.y,
                screenshot_path=str(screenshot_path.relative_to(self.session_dir)),
                screenshot_note=None,
            )
            self.events.append(recorded_event)
            print(
                f"[SHOT] {recorded_event.screenshot_path} "
                f"title={snapshot.title!r} bounds=({snapshot.left},{snapshot.top},{snapshot.right},{snapshot.bottom})"
            )
        except Exception as exc:
            recorded_event = RecordedEvent(
                t_rel=event.t_rel,
                event_type=event.event_type,
                detail=event.detail,
                x=event.x,
                y=event.y,
                screenshot_path=None,
                screenshot_note=str(exc),
            )
            self.events.append(recorded_event)
            print(f"[WARN] Screenshot skipped for {event.event_type}/{event.detail}: {exc}")

    def _build_screenshot_name(self, index: int, event: RecordedEvent) -> str:
        safe_detail = event.detail.replace(":", "_").replace("'", "")
        return f"{index + 1:03d}_{event.t_rel:07.3f}_{event.event_type}_{safe_detail}.png"

    def record_mouse_click(
        self,
        x: int,
        y: int,
        button: mouse.Button,
        pressed: bool,
    ) -> None:
        with self.lock:
            if not self.armed:
                return
            if button != mouse.Button.left or not pressed:
                return

            if not self.started:
                self._start_on_first_click(x, y)
                return

            event = RecordedEvent(
                t_rel=self._elapsed(),
                event_type="mouse_click",
                detail="left_down",
                x=x,
                y=y,
                screenshot_path=None,
                screenshot_note=None,
            )
            self._record_event(event)
            print(f"[CLICK] t={event.t_rel:>7.3f}  ({x}, {y})")

    def record_key_press(self, key: keyboard.Key | keyboard.KeyCode) -> None:
        with self.lock:
            if not self.armed:
                return

            if key == keyboard.Key.f10:
                print("[STOP] F10 received")
                self.stop()
                return

            if not self.started:
                return

            detail = self._key_to_name(key)
            event = RecordedEvent(
                t_rel=self._elapsed(),
                event_type="key_press",
                detail=detail,
                x=None,
                y=None,
                screenshot_path=None,
                screenshot_note=None,
            )
            self._record_event(event)
            print(f"[KEY ] t={event.t_rel:>7.3f}  {detail}")

    @staticmethod
    def _key_to_name(key: keyboard.Key | keyboard.KeyCode) -> str:
        if isinstance(key, keyboard.KeyCode):
            return f"char:{key.char!r}" if key.char is not None else "keycode:unknown"
        return f"key:{key.name}"

    def write_csv(self) -> None:
        with self.output_path.open("w", newline="", encoding="utf-8") as output_file:
            writer = csv.writer(output_file)
            writer.writerow(
                [
                    "t_rel_seconds",
                    "event_type",
                    "detail",
                    "x",
                    "y",
                    "screenshot_path",
                    "screenshot_note",
                ]
            )
            for event in self.events:
                writer.writerow(
                    [
                        event.t_rel,
                        event.event_type,
                        event.detail,
                        event.x,
                        event.y,
                        event.screenshot_path,
                        event.screenshot_note,
                    ]
                )

    def print_summary(self) -> None:
        print()
        print("=== SUMMARY ===")
        print(f"Armed:   {self.armed}")
        print(f"Started: {self.started}")
        print(f"Events:  {len(self.events)}")
        print(f"Output:  {self.output_path}")
        print(f"Shots:   {self.screenshot_dir}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Record one IPM interaction flow with screenshots.")
    parser.add_argument(
        "--window-title-substring",
        default="BlueStacks App Player",
        help="Foreground window title substring required before saving a screenshot.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    recorder = FlowRecorder(window_title_substring=args.window_title_substring)

    print("IPM Flow Recorder")
    print("-----------------")
    print("1. Focus this terminal.")
    print("2. Press Enter to arm recording.")
    print("3. Alt-Tab to BlueStacks / IPM.")
    print("4. Your FIRST left click becomes t=0.000 and saves a screenshot.")
    print("5. Every later left click and key press is recorded with a screenshot.")
    print("6. Press F10 anywhere to stop and write CSV plus screenshots.")
    print()

    input("Press Enter to arm... ")
    recorder.arm()
    print("[ARMED] Recording is armed. Alt-Tab to IPM. First left click starts timer.")
    print("[INFO ] Press F10 to stop.")
    print()

    mouse_listener = mouse.Listener(on_click=recorder.record_mouse_click)
    key_listener = keyboard.Listener(on_press=recorder.record_key_press)

    mouse_listener.start()
    key_listener.start()

    recorder.stop_event.wait()

    mouse_listener.stop()
    key_listener.stop()

    recorder.write_csv()
    recorder.print_summary()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
