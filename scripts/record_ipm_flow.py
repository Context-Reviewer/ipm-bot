"""Record one manual IPM interaction flow as timestamped CSV."""

from __future__ import annotations

import csv
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from threading import Event, Lock

from pynput import keyboard, mouse


@dataclass(frozen=True, slots=True)
class RecordedEvent:
    t_rel: float
    event_type: str
    detail: str
    x: int | None
    y: int | None


class FlowRecorder:
    def __init__(self) -> None:
        self.armed = False
        self.started = False
        self.start_time: float | None = None
        self.stop_event = Event()
        self.lock = Lock()
        self.events: list[RecordedEvent] = []

        repo_root = Path(__file__).resolve().parents[1]
        out_dir = repo_root / "logs" / "input_recordings"
        out_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
        self.output_path = out_dir / f"{stamp}_ipm_flow.csv"

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
        self.events.append(
            RecordedEvent(
                t_rel=0.000,
                event_type="mouse_click",
                detail="left_down_start",
                x=x,
                y=y,
            )
        )
        print(f"[START] t=0.000 on first left click at ({x}, {y})")

    def _elapsed(self) -> float:
        if self.start_time is None:
            return 0.0
        return round(time.perf_counter() - self.start_time, 3)

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
            )
            self.events.append(event)
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
            )
            self.events.append(event)
            print(f"[KEY ] t={event.t_rel:>7.3f}  {detail}")

    @staticmethod
    def _key_to_name(key: keyboard.Key | keyboard.KeyCode) -> str:
        if isinstance(key, keyboard.KeyCode):
            return f"char:{key.char!r}" if key.char is not None else "keycode:unknown"
        return f"key:{key.name}"

    def write_csv(self) -> None:
        with self.output_path.open("w", newline="", encoding="utf-8") as output_file:
            writer = csv.writer(output_file)
            writer.writerow(["t_rel_seconds", "event_type", "detail", "x", "y"])
            for event in self.events:
                writer.writerow([event.t_rel, event.event_type, event.detail, event.x, event.y])

    def print_summary(self) -> None:
        print()
        print("=== SUMMARY ===")
        print(f"Armed:   {self.armed}")
        print(f"Started: {self.started}")
        print(f"Events:  {len(self.events)}")
        print(f"Output:  {self.output_path}")


def main() -> int:
    recorder = FlowRecorder()

    print("IPM Flow Recorder")
    print("-----------------")
    print("1. Focus this terminal.")
    print("2. Press Enter to arm recording.")
    print("3. Alt-Tab to BlueStacks / IPM.")
    print("4. Your FIRST left click becomes t=0.000.")
    print("5. Every later left click and key press is recorded.")
    print("6. Press F10 anywhere to stop and write CSV.")
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
