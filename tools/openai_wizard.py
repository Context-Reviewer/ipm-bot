from __future__ import annotations

import json
import threading
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Iterable

from openai import OpenAI

APP_TITLE = "OpenAI Repo Wizard"
DEFAULT_MODEL = "gpt-5.4-mini"
DEFAULT_RESPONSE_DIR = "tmp/openai_runs"
MAX_PREVIEW_CHARS = 12000

SYSTEM_RULES = """You are a senior Python engineer working on a deterministic automation system.

STRICT RULES:
- Do NOT expand scope.
- Do NOT rewrite unrelated code.
- Preserve fail-closed behavior.
- Preserve deterministic logic.
- Prefer minimal patches.
- Do NOT invent repo behavior not supported by the provided files.
- If no code change is needed, say that explicitly.
- If the issue is operational rather than a code defect, say that explicitly.
- Respect the user's architectural and governance constraints.
- If a patch is proposed, provide only the changed sections unless the user explicitly asks for a full file.
"""

PRESETS = {
    "Bug diagnosis": """Find the most truthful interpretation of the issue.

Constraints:
- Distinguish code defect from runtime or operational behavior.
- Do not change planner behavior unless explicitly justified.
- Do not weaken verification thresholds.
- Preserve fail-closed semantics.
- If no code patch is justified, say so clearly.
- Only provide a patch if it is genuinely needed.
""",
    "Minimal behavioral patch": """Propose the smallest repo-grounded behavioral patch.

Constraints:
- No scope creep.
- Preserve fail-closed semantics.
- Preserve deterministic behavior.
- Do not change planner behavior unless explicitly requested.
- Explain why the patch is necessary.
- Provide only changed sections.
- Provide exact tests to run next.
""",
    "Test-only patch": """Create a minimal test-only patch.

Constraints:
- Do not change production behavior.
- Add or adjust only the smallest necessary tests.
- Explain what behavior is being locked in.
- Provide only changed sections.
- Include exact test commands.
""",
    "Receipt / runtime analysis": """Analyze the provided runtime evidence.

Constraints:
- Use receipts, logs, and command output as the primary evidence.
- Distinguish expected fail-closed behavior from code defects.
- If the issue is operational, say so plainly.
- Recommend the next most useful experiment or validation step.
""",
    "Patch review": """Review the proposed or existing patch.

Constraints:
- Check whether it truly changes behavior.
- Identify hidden scope creep.
- Identify architecture or governance violations.
- Say whether the patch should be accepted, revised, or rejected.
- If revision is needed, provide the smallest corrected patch.
""",
    "Experiment design": """Design the next experiment.

Constraints:
- Keep the experiment narrow, deterministic, and evidence-oriented.
- Prefer measurements over assumptions.
- State exactly what to capture, how to run it, and what outcomes would mean.
- Avoid speculative changes until the evidence supports them.
""",
}

RESPONSE_FORMAT = """RESPONSE FORMAT:
1. Is this a real bug, an operational issue, or still uncertain?
2. Root cause
3. Minimal fix or operational recommendation
4. Code patch (only changed sections, if needed)
5. What to test next"""


class OpenAIRepoWizard(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("1500x980")
        self.minsize(1200, 780)

        self.client = OpenAI()

        self.repo_root_var = tk.StringVar(value=str(Path.cwd()))
        self.model_var = tk.StringVar(value=DEFAULT_MODEL)
        self.preset_var = tk.StringVar(value="Bug diagnosis")
        self.auto_save_response_var = tk.BooleanVar(value=True)
        self.include_system_rules_var = tk.BooleanVar(value=True)
        self.status_var = tk.StringVar(value="Ready.")
        self.last_saved_response_path: Path | None = None

        self._build_ui()
        self._apply_preset(initial=True)

    def _build_ui(self) -> None:
        outer = ttk.Frame(self, padding=10)
        outer.pack(fill="both", expand=True)

        self._build_settings(outer)

        body = ttk.PanedWindow(outer, orient=tk.HORIZONTAL)
        body.pack(fill="both", expand=True, pady=(10, 10))

        left = ttk.Frame(body)
        center = ttk.Frame(body)
        right = ttk.Frame(body)
        body.add(left, weight=1)
        body.add(center, weight=2)
        body.add(right, weight=2)

        self._build_file_panel(left, title="Main repo files", attr_name="main_listbox")
        self._build_prompt_panel(center)
        self._build_output_panel(right)

        footer = ttk.Frame(outer)
        footer.pack(fill="x")
        ttk.Label(footer, textvariable=self.status_var, relief="sunken", anchor="w").pack(fill="x")

    def _build_settings(self, parent: ttk.Frame) -> None:
        frame = ttk.LabelFrame(parent, text="Session settings", padding=10)
        frame.pack(fill="x")

        ttk.Label(frame, text="Repo root").grid(row=0, column=0, sticky="w")
        ttk.Entry(frame, textvariable=self.repo_root_var).grid(row=0, column=1, sticky="ew", padx=6)
        ttk.Button(frame, text="Browse", command=self._choose_repo_root).grid(row=0, column=2, sticky="ew")

        ttk.Label(frame, text="Model").grid(row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(frame, textvariable=self.model_var, width=30).grid(row=1, column=1, sticky="w", padx=6, pady=(8, 0))

        ttk.Label(frame, text="Preset").grid(row=1, column=2, sticky="e", pady=(8, 0), padx=(18, 6))
        preset_combo = ttk.Combobox(
            frame,
            textvariable=self.preset_var,
            values=list(PRESETS.keys()),
            state="readonly",
            width=28,
        )
        preset_combo.grid(row=1, column=3, sticky="w", pady=(8, 0))
        preset_combo.bind("<<ComboboxSelected>>", lambda _evt: self._apply_preset())

        ttk.Checkbutton(
            frame,
            text="Include system rules",
            variable=self.include_system_rules_var,
        ).grid(row=2, column=0, sticky="w", pady=(8, 0))
        ttk.Checkbutton(
            frame,
            text="Auto-save response",
            variable=self.auto_save_response_var,
        ).grid(row=2, column=1, sticky="w", pady=(8, 0))

        button_row = ttk.Frame(frame)
        button_row.grid(row=2, column=3, sticky="e", pady=(8, 0))
        ttk.Button(button_row, text="Save session", command=self._save_session).pack(side="left")
        ttk.Button(button_row, text="Load session", command=self._load_session).pack(side="left", padx=(6, 0))

        frame.columnconfigure(1, weight=1)

    def _build_file_panel(self, parent: ttk.Frame, title: str, attr_name: str) -> None:
        frame = ttk.LabelFrame(parent, text=title, padding=10)
        frame.pack(fill="both", expand=True)

        listbox = tk.Listbox(frame, selectmode=tk.EXTENDED, width=42)
        listbox.pack(fill="both", expand=True)
        setattr(self, attr_name, listbox)

        controls = ttk.Frame(frame)
        controls.pack(fill="x", pady=(8, 0))
        ttk.Button(controls, text="Add files", command=lambda: self._add_files_to_listbox(listbox)).pack(side="left")
        ttk.Button(controls, text="Add folder", command=lambda: self._add_folder_to_listbox(listbox)).pack(side="left", padx=(6, 0))
        ttk.Button(controls, text="Auto-add tmp", command=self._auto_add_tmp_files).pack(side="left", padx=(6, 0))
        ttk.Button(controls, text="Remove selected", command=lambda: self._remove_selected(listbox)).pack(side="left", padx=(6, 0))
        ttk.Button(controls, text="Clear", command=lambda: listbox.delete(0, tk.END)).pack(side="left", padx=(6, 0))

        preview_frame = ttk.LabelFrame(frame, text="Selected file preview", padding=6)
        preview_frame.pack(fill="both", expand=True, pady=(10, 0))
        preview = tk.Text(preview_frame, wrap="word", height=18)
        preview.pack(fill="both", expand=True)
        preview.configure(state="disabled")
        setattr(self, f"{attr_name}_preview", preview)

        listbox.bind("<<ListboxSelect>>", lambda _evt, lb=listbox, pv=preview: self._preview_selected(lb, pv))

    def _build_prompt_panel(self, parent: ttk.Frame) -> None:
        frame = ttk.LabelFrame(parent, text="Prompt builder", padding=10)
        frame.pack(fill="both", expand=True)

        toolbar = ttk.Frame(frame)
        toolbar.pack(fill="x", pady=(0, 8))
        ttk.Button(toolbar, text="Load prompt", command=self._load_prompt).pack(side="left")
        ttk.Button(toolbar, text="Save prompt", command=self._save_prompt).pack(side="left", padx=(6, 0))
        ttk.Button(toolbar, text="Insert preset", command=self._apply_preset).pack(side="left", padx=(6, 0))
        ttk.Button(toolbar, text="Build prompt preview", command=self._show_compiled_prompt).pack(side="left", padx=(6, 0))
        ttk.Button(toolbar, text="Clear", command=lambda: self.prompt_text.delete("1.0", tk.END)).pack(side="left", padx=(6, 0))

        self.prompt_text = tk.Text(frame, wrap="word", height=20)
        self.prompt_text.pack(fill="both", expand=True)

        notes_frame = ttk.LabelFrame(frame, text="Optional run notes", padding=6)
        notes_frame.pack(fill="both", expand=False, pady=(10, 0))
        self.notes_text = tk.Text(notes_frame, wrap="word", height=8)
        self.notes_text.pack(fill="both", expand=True)
        self.notes_text.insert(
            "1.0",
            "Use this for observations that do not belong in a repo file, such as timing notes, expected autosave cadence, or experiment context.\n",
        )

    def _build_output_panel(self, parent: ttk.Frame) -> None:
        frame = ttk.LabelFrame(parent, text="Response", padding=10)
        frame.pack(fill="both", expand=True)

        toolbar = ttk.Frame(frame)
        toolbar.pack(fill="x", pady=(0, 8))
        ttk.Button(toolbar, text="Run", command=self._run_request).pack(side="left")
        ttk.Button(toolbar, text="Copy response", command=self._copy_response).pack(side="left", padx=(6, 0))
        ttk.Button(toolbar, text="Save response", command=self._save_response_as).pack(side="left", padx=(6, 0))
        ttk.Button(toolbar, text="Open last saved", command=self._open_last_saved_dir).pack(side="left", padx=(6, 0))
        ttk.Button(toolbar, text="Clear", command=lambda: self.response_text.delete("1.0", tk.END)).pack(side="left", padx=(6, 0))

        self.response_text = tk.Text(frame, wrap="word")
        self.response_text.pack(fill="both", expand=True)

    def _choose_repo_root(self) -> None:
        chosen = filedialog.askdirectory(initialdir=self.repo_root_var.get() or ".")
        if chosen:
            self.repo_root_var.set(chosen)
            self.status_var.set(f"Repo root set to {chosen}")

    def _add_files_to_listbox(self, listbox: tk.Listbox) -> None:
        repo_root = Path(self.repo_root_var.get()).resolve()
        paths = filedialog.askopenfilenames(initialdir=str(repo_root))
        self._insert_paths(listbox, [Path(p) for p in paths])

    def _add_folder_to_listbox(self, listbox: tk.Listbox) -> None:
        folder = filedialog.askdirectory(initialdir=self.repo_root_var.get() or ".")
        if not folder:
            return
        folder_path = Path(folder)
        file_paths = [p for p in folder_path.rglob("*") if p.is_file()]
        self._insert_paths(listbox, file_paths)
        self.status_var.set(f"Added {len(file_paths)} files from {folder_path}")

    def _insert_paths(self, listbox: tk.Listbox, paths: Iterable[Path]) -> None:
        existing = set(listbox.get(0, tk.END))
        repo_root = Path(self.repo_root_var.get()).resolve()
        count = 0
        for path in paths:
            display = self._display_path(path.resolve(), repo_root)
            if display not in existing:
                listbox.insert(tk.END, display)
                existing.add(display)
                count += 1
        if count:
            self.status_var.set(f"Added {count} file(s).")

    def _display_path(self, path: Path, repo_root: Path) -> str:
        try:
            return str(path.relative_to(repo_root))
        except ValueError:
            return str(path)

    def _remove_selected(self, listbox: tk.Listbox) -> None:
        for index in reversed(listbox.curselection()):
            listbox.delete(index)

    def _preview_selected(self, listbox: tk.Listbox, preview_widget: tk.Text) -> None:
        selection = listbox.curselection()
        if not selection:
            self._set_text(preview_widget, "")
            return
        item = listbox.get(selection[0])
        path = self._resolve_path(item)
        try:
            content = path.read_text(encoding="utf-8")
        except Exception as exc:
            content = f"[ERROR READING {path}: {exc}]"
        if len(content) > MAX_PREVIEW_CHARS:
            content = content[:MAX_PREVIEW_CHARS] + "\n\n...[preview truncated]"
        self._set_text(preview_widget, content)

    def _set_text(self, widget: tk.Text, text: str) -> None:
        widget.configure(state="normal")
        widget.delete("1.0", tk.END)
        widget.insert("1.0", text)
        widget.configure(state="disabled")

    def _apply_preset(self, initial: bool = False) -> None:
        preset_text = PRESETS.get(self.preset_var.get(), "")
        if initial:
            self.prompt_text.insert("1.0", preset_text)
            return
        current = self.prompt_text.get("1.0", tk.END).strip()
        if current and not messagebox.askyesno("Replace prompt?", "Replace the current prompt text with the selected preset?"):
            return
        self.prompt_text.delete("1.0", tk.END)
        self.prompt_text.insert("1.0", preset_text)

    def _load_prompt(self) -> None:
        path = filedialog.askopenfilename(filetypes=[("Text / Markdown", "*.txt *.md"), ("All files", "*.*")])
        if not path:
            return
        try:
            content = Path(path).read_text(encoding="utf-8")
        except Exception as exc:
            messagebox.showerror("Load prompt failed", str(exc))
            return
        self.prompt_text.delete("1.0", tk.END)
        self.prompt_text.insert("1.0", content)
        self.status_var.set(f"Loaded prompt from {path}")

    def _save_prompt(self) -> None:
        path = filedialog.asksaveasfilename(defaultextension=".txt", filetypes=[("Text", "*.txt"), ("Markdown", "*.md"), ("All files", "*.*")])
        if not path:
            return
        Path(path).write_text(self.prompt_text.get("1.0", tk.END).strip() + "\n", encoding="utf-8")
        self.status_var.set(f"Saved prompt to {path}")

    def _resolve_path(self, item: str) -> Path:
        candidate = Path(item)
        if candidate.is_absolute():
            return candidate
        return Path(self.repo_root_var.get()).resolve() / candidate

    def _read_file_block(self, label: str, item: str) -> str:
        path = self._resolve_path(item)
        try:
            text = path.read_text(encoding="utf-8")
        except Exception as exc:
            text = f"[ERROR READING {path}: {exc}]"
        return f"\n\n--- {label}: {path.as_posix()} ---\n{text}"

    def _build_full_prompt(self) -> str:
        user_prompt = self.prompt_text.get("1.0", tk.END).strip()
        notes = self.notes_text.get("1.0", tk.END).strip()
        main_files = list(self.main_listbox.get(0, tk.END))
        extra_files = list(self.extra_listbox.get(0, tk.END))

        sections: list[str] = []
        if self.include_system_rules_var.get():
            sections.append(SYSTEM_RULES)
        sections.append(f"USER REQUEST:\n{user_prompt}")
        if notes:
            sections.append(f"RUN NOTES:\n{notes}")

        context_parts: list[str] = []
        for item in main_files:
            context_parts.append(self._read_file_block("FILE", item))
        for item in extra_files:
            context_parts.append(self._read_file_block("EXTRA", item))

        if context_parts:
            sections.append(f"CONTEXT:{''.join(context_parts)}")
        sections.append(RESPONSE_FORMAT)
        return "\n\n".join(sections)

    def _show_compiled_prompt(self) -> None:
        compiled = self._build_full_prompt()
        win = tk.Toplevel(self)
        win.title("Compiled Prompt Preview")
        win.geometry("1100x800")
        txt = tk.Text(win, wrap="word")
        txt.pack(fill="both", expand=True)
        txt.insert("1.0", compiled)

    def _run_request(self) -> None:
        user_prompt = self.prompt_text.get("1.0", tk.END).strip()
        if not user_prompt:
            messagebox.showwarning("Missing prompt", "Enter a prompt before running.")
            return
        self.status_var.set("Sending request...")
        self.response_text.delete("1.0", tk.END)
        threading.Thread(target=self._worker_run_request, daemon=True).start()

    def _worker_run_request(self) -> None:
        try:
            prompt = self._build_full_prompt()
            response = self.client.responses.create(
                model=self.model_var.get().strip() or DEFAULT_MODEL,
                input=prompt,
            )
            text = response.output_text
            save_path = self._auto_save_response(text) if self.auto_save_response_var.get() else None
        except Exception as exc:
            self.after(0, lambda: self._handle_error(exc))
            return
        self.after(0, lambda: self._handle_success(text, save_path))

    def _handle_success(self, text: str, save_path: Path | None) -> None:
        self.response_text.delete("1.0", tk.END)
        self.response_text.insert("1.0", text)
        if save_path:
            self.last_saved_response_path = save_path
            self.status_var.set(f"Request complete. Auto-saved to {save_path}")
        else:
            self.status_var.set("Request complete.")

    def _handle_error(self, exc: Exception) -> None:
        self.status_var.set("Request failed.")
        messagebox.showerror("OpenAI request failed", str(exc))

    def _copy_response(self) -> None:
        text = self.response_text.get("1.0", tk.END).strip()
        self.clipboard_clear()
        self.clipboard_append(text)
        self.status_var.set("Response copied to clipboard.")

    def _save_response_as(self) -> None:
        path = filedialog.asksaveasfilename(defaultextension=".md", filetypes=[("Markdown", "*.md"), ("Text", "*.txt"), ("All files", "*.*")])
        if not path:
            return
        Path(path).write_text(self.response_text.get("1.0", tk.END).strip() + "\n", encoding="utf-8")
        self.last_saved_response_path = Path(path)
        self.status_var.set(f"Saved response to {path}")

    def _auto_save_response(self, text: str) -> Path:
        root = Path(self.repo_root_var.get()).resolve() / DEFAULT_RESPONSE_DIR
        root.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        path = root / f"response_{stamp}.md"
        path.write_text(text.strip() + "\n", encoding="utf-8")
        latest = root / "last_response.md"
        latest.write_text(text.strip() + "\n", encoding="utf-8")
        prompt_snapshot = root / f"prompt_{stamp}.txt"
        prompt_snapshot.write_text(self._build_full_prompt(), encoding="utf-8")
        return path

    def _open_last_saved_dir(self) -> None:
        target = self.last_saved_response_path
        if target is None:
            target = Path(self.repo_root_var.get()).resolve() / DEFAULT_RESPONSE_DIR
        messagebox.showinfo("Saved location", str(target))

    def _save_session(self) -> None:
        path = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("JSON", "*.json"), ("All files", "*.*")])
        if not path:
            return
        data = {
            "repo_root": self.repo_root_var.get(),
            "model": self.model_var.get(),
            "preset": self.preset_var.get(),
            "auto_save_response": self.auto_save_response_var.get(),
            "include_system_rules": self.include_system_rules_var.get(),
            "main_files": list(self.main_listbox.get(0, tk.END)),
            "extra_files": list(self.extra_listbox.get(0, tk.END)),
            "prompt": self.prompt_text.get("1.0", tk.END),
            "notes": self.notes_text.get("1.0", tk.END),
        }
        Path(path).write_text(json.dumps(data, indent=2), encoding="utf-8")
        self.status_var.set(f"Saved session to {path}")

    def _load_session(self) -> None:
        path = filedialog.askopenfilename(filetypes=[("JSON", "*.json"), ("All files", "*.*")])
        if not path:
            return
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except Exception as exc:
            messagebox.showerror("Load session failed", str(exc))
            return

        self.repo_root_var.set(data.get("repo_root", self.repo_root_var.get()))
        self.model_var.set(data.get("model", DEFAULT_MODEL))
        self.preset_var.set(data.get("preset", "Bug diagnosis"))
        self.auto_save_response_var.set(bool(data.get("auto_save_response", True)))
        self.include_system_rules_var.set(bool(data.get("include_system_rules", True)))

        self.main_listbox.delete(0, tk.END)
        for item in data.get("main_files", []):
            self.main_listbox.insert(tk.END, item)

        self.extra_listbox.delete(0, tk.END)
        for item in data.get("extra_files", []):
            self.extra_listbox.insert(tk.END, item)

        self.prompt_text.delete("1.0", tk.END)
        self.prompt_text.insert("1.0", data.get("prompt", ""))
        self.notes_text.delete("1.0", tk.END)
        self.notes_text.insert("1.0", data.get("notes", ""))
        self.status_var.set(f"Loaded session from {path}")

    def _auto_add_tmp_files(self) -> None:
        repo_root = Path(self.repo_root_var.get()).resolve()
        tmp_dir = repo_root / "tmp"
        candidates = [
            tmp_dir / "prompt.txt",
            tmp_dir / "failure.txt",
            tmp_dir / "receipt.json",
            tmp_dir / "notes.txt",
            tmp_dir / "last_response.md",
        ]
        existing = [p for p in candidates if p.exists()]
        if not existing:
            self.status_var.set("No known tmp files found.")
            return
        self._insert_paths(self.extra_listbox, existing)
        self.status_var.set(f"Added {len(existing)} tmp file(s).")


def main() -> None:
    app = OpenAIRepoWizard()
    app.mainloop()


if __name__ == "__main__":
    main()
