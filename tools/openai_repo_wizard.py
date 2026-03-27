#!/usr/bin/env python3
"""
AI Engineering Cockpit - V6 (Context Intelligence)
A local-first, project-grounded, strategic AI assistant for reliable, deterministic engineering.
Includes Context Filtering Engine, Diagnosis Confidence, explicit Stop Conditions, and all V5 proactive features.
"""

import os
import sys
import json
import threading
import datetime
import difflib
import ast
import subprocess
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext

try:
    import openai
except ImportError:
    print("Error: The 'openai' package is required. Please install it (e.g., pip install openai).")
    sys.exit(1)


###############################################################################
# CONFIGURATION & PRESETS
###############################################################################

PRESETS = {
    "Strategic leverage analysis (Full Project)": (
        "Analyze this project and tell me the highest-leverage improvements, refactors, risks, and next steps. "
        "Focus on maintainability, deterministic fail-closed design, and eliminating technical debt. "
        "Keep your analysis strictly grounded in the selected files."
    ),
    "Bug diagnosis": (
        "Analyze the provided files to diagnose the described bug. "
        "Point out exactly where the issue lies, but do not provide unnecessary code unless asked. "
        "If there is insufficient evidence, ask for more logs or context. "
        "Differentiate between actual code defects and operational issues."
    ),
    "Minimal patch": (
        "Provide the absolute minimal, precise code patch to fix the issue described. "
        "Do not rewrite surrounding context or attempt unsolicited refactoring. "
        "If you are uncertain about the fix, state it explicitly."
    ),
    "Test-only patch": (
        "Write or fix tests for the provided code and failure scenario. "
        "Do not change the implementation logic of the core modules unless instructed."
    ),
    "Receipt/runtime analysis": (
        "Examine the provided receipt, logs, or runtime failures and determine the underlying cause and the required fix. "
        "Focus on extracting the exact failure sequence from the evidence files. "
        "Use the precomputed Truth Engine fields to ground your conclusion entirely."
    ),
    "Refactor review": (
        "Review the provided code for architectural flaws, code smells, or technical debt. "
        "Suggest a structured refactoring sequence. Do not write full implementations; focus on strategy."
    ),
    "Architecture review": (
        "Review the core architecture of the provided project files. "
        "Suggest improvements for reliability, minimal blast radius, and testability."
    ),
    "Experiment design": (
        "Propose a structured way to test a hypothesis or add a new experimental feature to the project, "
        "maximizing isolation, clear validation, and minimal scope creep."
    ),
    "Patch review / critique": (
        "Review the proposed code patch within the provided context. "
        "Look for regressions, edge cases, scope creep, and untested pathways. Critique aggressively but constructively."
    ),
    "Custom (Blank)": ""
}

SYSTEM_PROMPT_BASE = """You are an elite, highly trusted local AI Engineering Cockpit assistant helping a solo developer 
working on deterministic, fail-closed robotics/automation workflows (like ipm-bot).
Your primary directives:
1. GROUNDEDNESS: Only reason based on the provided project files, logs, and receipts. If you lack evidence, explicitly say so.
2. MINIMALISM: Provide minimal, exact changes unless a broad refactor is explicitly requested. No hallucinated code block "updates" that don't change anything.
3. STRATEGY: Offer high-leverage insights. Differentiate between real logic defects, test flakiness, or runtime operational errors.
4. FAIL-CLOSED DESIGN: If the system properly aborted an unsafe or uncertain action, praise the fail-closed behavior.

[EXPECTED RESPONSE FORMAT]
Please format your response EXACTLY as follows to maintain the engineering standard:
1. DETERMINISTIC STATE SUMMARY: (Summarize exactly what the receipt/evidence shows actually happened)
2. INTERPRETATION: (Explain why it happened based on the rules of the system)
3. Diagnosis: (Bug vs operational issue vs uncertain vs expected fail-closed)
4. Root Cause: (Brief explanation)
5. Next Action (Highest Leverage): (Concrete, actionable next step for the developer. Do not give generic advice.)
6. Recommendation: (Minimal fix or operational recommendation. Explicitly use phrasing: "This is expected fail-closed behavior. No code change recommended." if appropriate.)
7. Code Patch: (ONLY if justified and complete. No fake patches.)
8. Validation: (Exact validation commands)
9. Commit Message: (Ready to use commit message)
10. Tag Suggestion: (e.g. bugfix/save-timeout, chore/refactor)
"""

MODELS = [
    "gpt-4o",
    "gpt-4-turbo",
    "gpt-3.5-turbo",
    "o1-preview",
    "o1-mini"
]

###############################################################################
# MODELS & WRAPPERS
###############################################################################

class LLMProvider:
    def stream_completion(self, model: str, prompt: str, on_chunk, on_done, on_error):
        raise NotImplementedError

class OpenAIProvider(LLMProvider):
    def __init__(self):
        try:
            self.client = openai.OpenAI()
            self.initialized = True
        except Exception as e:
            self.client = None
            self.initialized = False
            self.error_msg = str(e)
            
    def stream_completion(self, model: str, prompt: str, on_chunk, on_done, on_error):
        if not self.initialized:
            on_error("OpenAI Client not initialized (check OPENAI_API_KEY).")
            return
            
        def bg_run():
            try:
                response = self.client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": prompt}],
                    stream=True
                )
                full_text = ""
                for chunk in response:
                    delta = chunk.choices[0].delta.content
                    if delta:
                        full_text += delta
                        on_chunk(delta)
                on_done(full_text)
            except Exception as e:
                on_error(str(e))
                
        threading.Thread(target=bg_run, daemon=True).start()

class APIClient:
    def __init__(self):
        self.provider = OpenAIProvider()
    
    @property
    def initialized(self):
        return self.provider.initialized
        
    @property
    def error_msg(self):
        return self.provider.error_msg

    def stream_completion(self, *args, **kwargs):
        return self.provider.stream_completion(*args, **kwargs)


class WizardState:
    def __init__(self):
        self.repo_root = Path.cwd()
        self.source_files = set()
        self.evidence_files = set()
        self.preset_name = "Strategic leverage analysis (Full Project)"
        self.prompt_text = ""
        self.operator_notes = ""
        self.model = "gpt-4o"
        self.failure_classification = "unknown"
        self.receipt_meta = {
            "action": "",
            "final_status": "",
            "failure_reason": "",
            "changed_save_count": 0,
            "candidate_hashes": [],
            "verifier_messages": [],
            "elapsed_seconds": 0.0
        }

    def get_heuristic_context_size(self):
        total_chars = 0
        for f in self.source_files | self.evidence_files:
            try:
                total_chars += f.stat().st_size
            except:
                pass
        total_chars += len(self.prompt_text)
        return total_chars // 4


class SaveDiffer:
    @staticmethod
    def compute_diff(f1_path: Path, f2_path: Path):
        b1 = f1_path.read_bytes()
        b2 = f2_path.read_bytes()
        
        if b1 == b2:
            return "Files are identical. No state drift occurred.", "Files are identical."
        
        size_diff = len(b2) - len(b1)
        min_len = min(len(b1), len(b2))
        first_diff = -1
        regions = 0
        in_diff = False
        
        for i in range(min_len):
            if b1[i] != b2[i]:
                if first_diff == -1:
                    first_diff = i
                if not in_diff:
                    regions += 1
                    in_diff = True
            else:
                in_diff = False
                
        if len(b1) != len(b2):
            regions += 1
            if first_diff == -1:
                first_diff = min_len

        intel = (
            f"SAVE DIFF INTELLIGENCE:\n"
            f"- Size Delta: {size_diff} bytes\n"
            f"- First Changed Offset: {first_diff} bytes\n"
            f"- Total Changed Regions: {regions}\n"
            f"- Interpretation: "
        )
        if regions == 1 and size_diff > 0:
            intel += "Appears to be a clean append or single-block update."
        elif regions > 5:
            intel += "Highly fragmented save diff. Significant re-serialization or state-wipe occurred."
        else:
            intel += "Standard multi-region update."

        text_diff = f"Size 1: {len(b1)} bytes. Size 2: {len(b2)} bytes.\n"
        try:
            s1 = b1.decode('utf-8').splitlines()
            s2 = b2.decode('utf-8').splitlines()
            d = list(difflib.unified_diff(s1, s2, fromfile='Save1', tofile='Save2', n=1))
            text_diff += "Text Diff (first ~50 lines):\n" + "\n".join(d[:50])
            if len(d) > 50:
                text_diff += "\n... (truncated)"
        except:
            text_diff += "Binary files differ. Cannot show text diff."

        return intel, intel + "\n\n" + text_diff


class ContextEngine:
    @staticmethod
    def extract_high_signal_blocks(content: str, rel_path: str, action: str, failure_class: str) -> str:
        if not rel_path.endswith(".py"):
            return content
            
        try:
            tree = ast.parse(content)
        except Exception:
            return content
            
        keywords = []
        if action:
            keywords.append(action.lower())
        if "TIMEOUT" in failure_class:
            keywords.extend(["wait", "sleep", "timeout", "verify"])
        if "VERIFICATION" in failure_class:
            keywords.extend(["verify", "validate", "state"])
            
        if not keywords:
            return content
            
        high_signal = []
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                try:
                    block_text = ast.get_source_segment(content, node)
                    if not block_text: continue
                    if any(k in block_text.lower() for k in keywords):
                        high_signal.append(block_text)
                except Exception:
                    pass
        
        if high_signal:
            return "\n\n... [AST Filtered for High-Signal Blocks] ...\n\n" + "\n\n".join(high_signal)
        return "\n".join(content.splitlines()[:50]) + "\n... [Context omitted: No relevant AST keywords matched]"


class PrecomputedIntelligence:
    @staticmethod
    def generate_truth_block(meta: dict, failure_class: str) -> str:
        if not meta or not meta.get("action"):
            return "No recent runtime receipt found. State is officially unknown."
        
        saves = meta.get('changed_save_count', 0)
        verif_msgs = meta.get('verifier_messages', [])
        
        # Derive System Conclusion Fault Layer
        save_changed = "YES" if saves > 0 else "NO"
        verif_started = "YES" if verif_msgs or "VERIFICATION" in failure_class else "NO"
        
        fault_layer = "UNKNOWN"
        if failure_class == "TIMEOUT_NO_SAVE_CHANGE" or "ACTUATION" in failure_class:
            fault_layer = "ACTUATION (Input/UI interaction failed or was ignored)"
        elif failure_class == "SAVE_WATCH_ERROR":
            fault_layer = "PERSISTENCE (Failed to read or lock datastore)"
        elif "VERIFICATION" in failure_class or failure_class == "TIMEOUT_AFTER_SAVE_CHANGES":
            fault_layer = "VERIFICATION (State mutated but was rejected or verifier stalled)"
        elif "AMBIGUOUS" in failure_class:
            fault_layer = "PLANNER/VISION (Cannot decide safe target)"

        # Confidence Computation
        if verif_msgs and saves > 0:
            confidence = "HIGH (Full state mutation and verifier rejection trace available)"
        elif saves == 0 and ("TIMEOUT" in failure_class or "ACTUATION" in failure_class):
            confidence = "MEDIUM (No state changes recorded, relying purely on actuation timing/errors)"
        elif "AMBIGUOUS" in failure_class:
            confidence = "HIGH (Planner safely aborted due to strict constraints)"
        else:
            confidence = "LOW (Sparse receipt data)"

        # Stop Condition Computation
        if "AMBIGUOUS" in failure_class or (verif_msgs and "ABORT" in str(verif_msgs).upper()):
            stop_condition = "STOP: System is behaving correctly (Proper fail-closed execution confirmed)"
        else:
            stop_condition = "CONTINUE: Anomalous failure detected"

        lines = [
            f"ACTION FIRED: '{meta.get('action')}'",
            f"DETERMINISTIC FAILURE MODE: '{failure_class}'",
            f"FINAL RESULTING STATUS: {meta.get('final_status')}",
            f"ELAPSED TIME: {meta.get('elapsed_seconds')}s",
            f"STATE SAVES TRIGGERED: {saves}",
            f"VERIFIER OUTPUT: {verif_msgs}",
            "",
            "--- SYSTEM CONCLUSION ---",
            f"-> Save File Changed?  {save_changed}",
            f"-> Verification Run?   {verif_started}",
            f"-> Fault Layer:        {fault_layer}",
            f"-> DIAGNOSIS CONF:     {confidence}",
            f"-> {stop_condition}"
        ]
        return "\n".join(lines)

    @staticmethod
    def detect_patterns(runs: list) -> dict:
        if not runs:
            return {"text": "No prior runs available in tmp/openai_runs.", "is_looping": False, "recent_failures": []}
            
        failures = [r.get("failure", "unknown") for r in runs if r.get("failure") != "unknown"]
        if not failures:
            return {"text": "No repeated failure data.", "is_looping": False, "recent_failures": []}
            
        is_loop = (len(failures) >= 3 and failures[0] == failures[1] == failures[2])
        pattern_text = ""
        
        if is_loop:
            pattern_text = f"CRITICAL PATTERN: The last 3+ runs ALL failed with '{failures[0]}'. System is mathematically looping. Breaking change required."
        else:
            unique = list(dict.fromkeys(failures))
            if len(unique) > 1 and unique[0] != unique[1]:
                pattern_text = f"TRANSITION DETECTED: Failure mode shifted from '{unique[1]}' to '{unique[0]}'. The system is progressing but hit a new barrier."
            else:
                pattern_text = f"Recent Failure History (Newest -> Oldest): {', '.join(failures[:5])}."
                
        return {"text": pattern_text, "is_looping": is_loop, "recent_failures": failures}

    @staticmethod
    def generate_next_actions(failure_class: str, is_looping: bool) -> list:
        actions = []
        if is_looping:
            actions.append({"rank": 1, "confidence": "HIGH", "action": "ABORT current retry approach. Implement a forced hard-reset or fail-closed catch to break the infinite loop."})
            
        rank_offset = 1 if not is_looping else 2
        
        if "TIMEOUT_NO_SAVE_CHANGE" in failure_class or "ACTUATION" in failure_class:
            actions.append({"rank": rank_offset, "confidence": "HIGH", "action": "Inspect actuation targets (UI coords, OCR thresholds). The command clicked/typed but the local app completely ignored it."})
            actions.append({"rank": rank_offset + 1, "confidence": "MEDIUM", "action": "Check if a blocking modal or unexpected window state prevented input processing."})
        elif "TIMEOUT_AFTER_SAVE_CHANGES" in failure_class:
            actions.append({"rank": rank_offset, "confidence": "HIGH", "action": "Investigate verifier.py blocking locks or infinite wait conditions. The save updated, but the system hung waiting for read."})
        elif "VERIFICATION_FAILED" in failure_class:
            actions.append({"rank": rank_offset, "confidence": "HIGH", "action": "Read the exact verifier message. Fix the state transition logic to match strict validation bounds."})
            actions.append({"rank": rank_offset + 1, "confidence": "MEDIUM", "action": "If the verifier is factually wrong, update the verifier schema directly instead of code logic."})
        elif "AMBIGUOUS" in failure_class:
            actions.append({"rank": rank_offset, "confidence": "HIGH", "action": "Refine the planner's OCR/vision target specificity. It found multiple targets and safely aborted."})
            actions.append({"rank": rank_offset + 1, "confidence": "HIGH", "action": "This is likely a correct STOP sequence. No code changes needed if ambiguity was real."})
        elif "SAVE_WATCH_ERROR" in failure_class:
            actions.append({"rank": rank_offset, "confidence": "HIGH", "action": "Fix file IO locking or permissions on the save file watcher. Cannot evaluate state."})
        else:
            actions.append({"rank": rank_offset, "confidence": "LOW", "action": "Analyze raw evidence logs for untracked exception tracebacks."})
            
        return actions

    @staticmethod
    def format_actions(actions: list) -> str:
        lines = []
        for a in actions:
            lines.append(f"[{a['rank']}] [CONFIDENCE: {a['confidence']}]\n    -> {a['action']}")
        return "\n".join(lines)


class FailureAnalyzer:
    @staticmethod
    def find_latest_receipt(repo_root: Path):
        receipts_dir = repo_root / "logs" / "receipts"
        if not receipts_dir.exists() or not receipts_dir.is_dir():
            return None
        receipts = list(receipts_dir.glob("*.json"))
        if not receipts:
            return None
        return max(receipts, key=lambda p: p.stat().st_mtime)

    @staticmethod
    def extract_schema(data: dict) -> dict:
        return {
            "action": data.get("action", ""),
            "final_status": data.get("final_status", ""),
            "failure_reason": data.get("failure_reason", ""),
            "changed_save_count": data.get("changed_save_count", 0),
            "candidate_hashes": data.get("candidate_hashes", []),
            "verifier_messages": data.get("verifier_messages", []),
            "elapsed_seconds": data.get("elapsed_seconds", 0.0)
        }

    @staticmethod
    def classify_failure(meta: dict, failure_text: str) -> str:
        text_dump = (
            str(meta.get("failure_reason", "")) + " " + 
            str(failure_text) + " " + 
            str(meta.get("verifier_messages", "")) + " " +
            str(meta.get("final_status", ""))
        ).upper()
        
        saves = meta.get("changed_save_count", 0)
        
        if "TIMEOUT" in text_dump:
            if saves > 0:
                return "TIMEOUT_AFTER_SAVE_CHANGES"
            return "TIMEOUT_NO_SAVE_CHANGE"
            
        if "VERIFICATION" in text_dump or "FAILED" in text_dump:
            return "VERIFICATION_FAILED"
            
        if "AMBIGUOUS" in text_dump:
            return "AMBIGUOUS_TRANSITION"
            
        if "WATCH" in text_dump:
            return "SAVE_WATCH_ERROR"
            
        if "ERROR" in text_dump or "EXCEPTION" in text_dump:
            return "ACTUATION_ERROR"
            
        return "UNKNOWN"

    @staticmethod
    def suggest_files(repo_root: Path, classification: str, action: str):
        suggested = []
        core_targets = {"planner.py", "runner.py", "contracts.py", "save_watcher.py", "receipt_store.py", "actions.py", "verifier.py", "state.py"}
        for p in repo_root.rglob("*.py"):
            if "__pycache__" not in p.parts and "venv" not in p.parts and "node_modules" not in p.parts:
                if p.name in core_targets:
                    suggested.append(p.resolve())
        return list(set(suggested))

    @staticmethod
    def analyze(repo_root: Path):
        meta = {}
        suggested_evidence = []
        failure_text = ""
        
        failure_txt = repo_root / "tmp" / "failure.txt"
        if failure_txt.exists():
            suggested_evidence.append(failure_txt.resolve())
            failure_text = failure_txt.read_text(errors="ignore")

        latest_receipt = FailureAnalyzer.find_latest_receipt(repo_root)
        if latest_receipt:
            suggested_evidence.append(latest_receipt.resolve())
            try:
                data = json.loads(latest_receipt.read_text(errors="ignore"))
                meta = FailureAnalyzer.extract_schema(data)
            except json.JSONDecodeError:
                meta = {"failure_reason": "malformed receipt JSON"}
        
        classification = FailureAnalyzer.classify_failure(meta, failure_text)
        suggested_sources = FailureAnalyzer.suggest_files(repo_root, classification, meta.get("action", ""))
        
        return classification, meta, suggested_evidence, suggested_sources


class PromptCompiler:
    @staticmethod
    def compile(state: WizardState) -> str:
        parts = [SYSTEM_PROMPT_BASE]
        
        preset_instructions = PRESETS.get(state.preset_name, "")
        if preset_instructions:
            parts.append(f"\n[CURRENT OPERATIONAL DIRECTIVE]\n{preset_instructions}")
            
        # Add Precomputed Intelligence Block
        parts.append("\n==================== SYSTEM-COMPUTED TRUTH ====================")
        truth_block = PrecomputedIntelligence.generate_truth_block(state.receipt_meta, state.failure_classification)
        parts.append(truth_block)
        
        # Add Multi-Run Pattern Engine (tmp/openai_runs)
        recent_runs = SessionManager.load_recent_runs(state.repo_root, limit=5)
        pat_data = PrecomputedIntelligence.detect_patterns(recent_runs)
        parts.append("\n==================== MULTI-RUN PATTERN ENGINE ====================")
        parts.append(pat_data["text"])

        # Add Next Action Precomputation
        parts.append("\n==================== PRECOMPUTED NEXT ACTION ====================")
        actions = PrecomputedIntelligence.generate_next_actions(state.failure_classification, pat_data["is_looping"])
        parts.append(PrecomputedIntelligence.format_actions(actions))
        
        # Add structured Evidence Summary
        parts.append("\n==================== EVIDENCE SUMMARY ====================")
        parts.append(f"Source Files count: {len(state.source_files)}")
        parts.append(f"Evidence Files count: {len(state.evidence_files)}")
        parts.append("========================================================\n")

        parts.append("\n==================== PROJECT CONTEXT ====================")
        
        if state.source_files:
            parts.append("\\n--- SOURCE FILES ---")
            for f in sorted(state.source_files):
                if f.exists():
                    try:
                        content = f.read_text(encoding="utf-8")
                        rel_path = str(f.relative_to(state.repo_root))
                    except ValueError:
                        rel_path = f.name
                    except UnicodeDecodeError:
                        content = "[Binary or unreadable text file]"
                        rel_path = f.name
                        
                    # AST Context Filtering applied here natively
                    if content != "[Binary or unreadable text file]":
                        content = ContextEngine.extract_high_signal_blocks(content, rel_path, state.receipt_meta.get("action", ""), state.failure_classification)
                        
                    parts.append(f'<file name="{rel_path}">\n{content}\n</file>')
        
        if state.evidence_files:
            parts.append("\n--- EVIDENCE & LOGS ---")
            for f in sorted(state.evidence_files):
                if f.exists():
                    try:
                        content = f.read_text(encoding="utf-8")
                        rel_path = str(f.relative_to(state.repo_root))
                    except ValueError:
                        rel_path = f.name
                    except UnicodeDecodeError:
                        content = "[Binary or unreadable text file]"
                    parts.append(f'<evidence name="{rel_path}">\n{content}\n</evidence>')

        if state.operator_notes.strip():
            parts.append("\n==================== OPERATOR NOTES ====================")
            parts.append(state.operator_notes.strip())

        parts.append("\n==================== USER REQUEST ====================")
        parts.append(state.prompt_text.strip())
        
        return "\n".join(parts)


class SessionManager:
    @staticmethod
    def init_dirs(repo_root: Path):
        runs_dir = repo_root / "tmp" / "openai_runs"
        runs_dir.mkdir(parents=True, exist_ok=True)
        return runs_dir

    @staticmethod
    def load_recent_runs(repo_root: Path, limit=5):
        runs_dir = repo_root / "tmp" / "openai_runs"
        if not runs_dir.exists():
            return []
        files = list(runs_dir.glob("run_*.json"))
        files.sort(key=lambda x: x.stat().st_mtime, reverse=True)
        recent = []
        for f in files[:limit]:
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                recent.append({
                    "timestamp": data.get("timestamp"),
                    "failure": data.get("failure_classification", "unknown"),
                    "model": data.get("model", "unknown")
                })
            except:
                pass
        return recent

    @staticmethod
    def save_run(state: WizardState, compiled_prompt: str, response: str):
        runs_dir = SessionManager.init_dirs(state.repo_root)
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        run_file = runs_dir / f"run_{timestamp}.json"
        
        data = {
            "timestamp": timestamp,
            "model": state.model,
            "preset": state.preset_name,
            "failure_classification": state.failure_classification,
            "receipt_summary": state.receipt_meta,
            "source_files": [str(f) for f in state.source_files],
            "evidence_files": [str(f) for f in state.evidence_files],
            "prompt": state.prompt_text,
            "operator_notes": state.operator_notes,
            "compiled_prompt": compiled_prompt,
            "response": response
        }
        
        with run_file.open('w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
        return run_file


###############################################################################
# UI (TKINTER) APPLICATION
###############################################################################

class WizardApp:
    def __init__(self, root):
        self.root = root
        self.root.title("AI Engineering Cockpit v6 (Context Intelligence)")
        self.root.geometry("1500x950")
        
        self.state = WizardState()
        self.api = APIClient()

        if not self.api.initialized:
            messagebox.showwarning("API Error", self.api.error_msg)

        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        self.main_pw = ttk.PanedWindow(self.notebook, orient=tk.HORIZONTAL)
        self.notebook.add(self.main_pw, text="AI Cockpit")
        
        self.build_left_pane()
        self.build_center_pane()
        self.build_right_pane()
        self.build_signal_lab_tab()
        self.build_status_bar()
        
        self.root.after(100, lambda: self.main_pw.sashpos(0, 350))
        self.root.after(100, lambda: self.main_pw.sashpos(1, 900))

        self.refresh_status()

    # --- UI Layout Builders ---

    def build_left_pane(self):
        self.left_frame = ttk.Frame(self.main_pw)
        self.main_pw.add(self.left_frame, weight=1)
        
        rf = ttk.LabelFrame(self.left_frame, text="Project Root")
        rf.pack(fill=tk.X, padx=5, pady=5)
        self.repo_var = tk.StringVar(value=str(self.state.repo_root))
        ttk.Entry(rf, textvariable=self.repo_var, state='readonly').pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5, pady=5)
        ttk.Button(rf, text="Browse", command=self.change_repo_root).pack(side=tk.RIGHT, padx=5, pady=5)
        
        hf = ttk.Frame(self.left_frame)
        hf.pack(fill=tk.X, padx=5, pady=0)
        ttk.Button(hf, text="Curated Auto-Add", command=self.add_common_files).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=2)
        ttk.Button(hf, text="Analyze Last Failure", command=self.analyze_failure).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=2)

        es_f = ttk.LabelFrame(self.left_frame, text="Receipt Summary")
        es_f.pack(fill=tk.X, padx=5, pady=5)
        self.lst_receipt = scrolledtext.ScrolledText(es_f, height=5, font=("Consolas", 9), state='disabled', bg="#fdfdfd")
        self.lst_receipt.pack(fill=tk.X, padx=5, pady=5)

        sf = ttk.LabelFrame(self.left_frame, text="Source Files")
        sf.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        self.lst_sources = tk.Listbox(sf, selectmode=tk.EXTENDED)
        self.lst_sources.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        sbtn_f = ttk.Frame(sf)
        sbtn_f.pack(fill=tk.X, padx=5, pady=5)
        ttk.Button(sbtn_f, text="+ File", command=lambda: self.add_files('source')).pack(side=tk.LEFT, expand=True, fill=tk.X)
        ttk.Button(sbtn_f, text="+ Dir", command=lambda: self.add_dir('source')).pack(side=tk.LEFT, expand=True, fill=tk.X)
        ttk.Button(sbtn_f, text="- Remove", command=lambda: self.remove_files('source')).pack(side=tk.LEFT, expand=True, fill=tk.X)
        ttk.Button(sbtn_f, text="Preview", command=lambda: self.preview_file('source')).pack(side=tk.LEFT, expand=True, fill=tk.X)

        ef = ttk.LabelFrame(self.left_frame, text="Evidence Files (Logs/Receipts)")
        ef.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        self.lst_evidence = tk.Listbox(ef, selectmode=tk.EXTENDED)
        self.lst_evidence.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        ebtn_f = ttk.Frame(ef)
        ebtn_f.pack(fill=tk.X, padx=5, pady=5)
        ttk.Button(ebtn_f, text="+ File", command=lambda: self.add_files('evidence')).pack(side=tk.LEFT, expand=True, fill=tk.X)
        ttk.Button(ebtn_f, text="- Remove", command=lambda: self.remove_files('evidence')).pack(side=tk.LEFT, expand=True, fill=tk.X)
        ttk.Button(ebtn_f, text="Preview", command=lambda: self.preview_file('evidence')).pack(side=tk.LEFT, expand=True, fill=tk.X)


    def build_center_pane(self):
        self.center_frame = ttk.Frame(self.main_pw)
        self.main_pw.add(self.center_frame, weight=3)
        
        pf = ttk.LabelFrame(self.center_frame, text="Strategic Preset")
        pf.pack(fill=tk.X, padx=5, pady=5)
        self.preset_var = tk.StringVar(value=self.state.preset_name)
        preset_cb = ttk.Combobox(pf, textvariable=self.preset_var, values=list(PRESETS.keys()), state="readonly")
        preset_cb.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5, pady=5)
        ttk.Button(pf, text="Compare 2 Saves (Diff)", command=self.compare_saves).pack(side=tk.RIGHT, padx=5, pady=5)
        preset_cb.bind("<<ComboboxSelected>>", self.on_preset_change)
        
        upf = ttk.LabelFrame(self.center_frame, text="Prompt Workspace")
        upf.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        self.txt_prompt = scrolledtext.ScrolledText(upf, wrap=tk.WORD, font=("Consolas", 11))
        self.txt_prompt.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        onf = ttk.LabelFrame(self.center_frame, text="Operator Notes (Included in Context)")
        onf.pack(fill=tk.X, padx=5, pady=5)
        self.txt_notes = scrolledtext.ScrolledText(onf, wrap=tk.WORD, font=("Consolas", 10), height=5)
        self.txt_notes.pack(fill=tk.X, padx=5, pady=5)
        
        tf = ttk.Frame(self.center_frame)
        tf.pack(fill=tk.X, padx=5, pady=5)
        ttk.Button(tf, text="Preview Compiled Prompt", command=self.preview_compiled_prompt).pack(side=tk.RIGHT)


    def build_right_pane(self):
        self.right_frame = ttk.Frame(self.main_pw)
        self.main_pw.add(self.right_frame, weight=3)
        
        ctrl_f = ttk.Frame(self.right_frame)
        ctrl_f.pack(fill=tk.X, padx=5, pady=5)
        
        ttk.Label(ctrl_f, text="Model:").pack(side=tk.LEFT, padx=5)
        self.model_var = tk.StringVar(value=self.state.model)
        ttk.Combobox(ctrl_f, textvariable=self.model_var, values=MODELS, state="readonly", width=15).pack(side=tk.LEFT)
        self.btn_run = ttk.Button(ctrl_f, text="RUN ->", command=self.run_api, style="Accent.TButton")
        self.btn_run.pack(side=tk.RIGHT, padx=5)
        ttk.Button(ctrl_f, text="Copy Response", command=self.copy_response).pack(side=tk.RIGHT, padx=5)
        
        res_f = ttk.LabelFrame(self.right_frame, text="Structured Response")
        res_f.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        self.txt_response = scrolledtext.ScrolledText(res_f, wrap=tk.WORD, font=("Consolas", 11), bg="#f5f5f5")
        self.txt_response.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        self.lbl_run_status = ttk.Label(self.right_frame, text="Idle", foreground="gray")
        self.lbl_run_status.pack(side=tk.LEFT, padx=5, pady=5)

    def build_signal_lab_tab(self):
        self.lab_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.lab_frame, text="IPM Signal Lab")
        
        # Tool Buttons
        btn_frame = ttk.Frame(self.lab_frame)
        btn_frame.pack(side=tk.TOP, fill=tk.X, padx=5, pady=5)
        
        self.lab_btns = []
        def add_btn(text, cmd):
            b = ttk.Button(btn_frame, text=text, command=cmd)
            b.pack(side=tk.LEFT, padx=5)
            self.lab_btns.append(b)

        add_btn("Start ADB", lambda: self.run_subprocess(["C:\\dev\\platform-tools\\adb.exe", "start-server"]))
        add_btn("Connect BlueStacks", lambda: self.run_subprocess(["C:\\dev\\platform-tools\\adb.exe", "connect", "127.0.0.1:5555"]))
        add_btn("Check Devices", lambda: self.run_subprocess(["C:\\dev\\platform-tools\\adb.exe", "devices"]))
        add_btn("Pull playerInfo.dat", lambda: self.run_subprocess(["C:\\dev\\platform-tools\\adb.exe", "-s", "127.0.0.1:5555", "pull", "/sdcard/Android/data/com.TironiumTech.IdlePlanetMiner/files/playerInfo.dat", "C:\\dev\\ipm-bot\\data\\pulled\\playerInfo.dat"]))
        
        py_cmd = [
            r"C:\dev\ipm-bot\.venv\Scripts\python.exe", "-m", "ipm_bot.experiment",
            "--save-source", "adb-pull",
            "--actuator", "adb",
            "--adb-path", r"C:\dev\platform-tools\adb.exe",
            "--adb-serial", "127.0.0.1:5555",
            "--app-package", "com.TironiumTech.IdlePlanetMiner",
            "--app-activity", "com.unity3d.player.UnityPlayerActivity",
            "--activate-ad-boost-tap", "848,394",
            "--activate-ad-boost-watch-tap", "448,859",
            "--action-override", "activate_ad_boost",
            "--timeout-seconds", "60",
            "/sdcard/Android/data/com.TironiumTech.IdlePlanetMiner/files/playerInfo.dat"
        ]
        add_btn("Run activate_ad_boost", lambda: self.run_subprocess(py_cmd))
        add_btn("Open latest receipt", self.open_latest_receipt)
        add_btn("Copy Ads analysis prompt", self.copy_ads_prompt)
        
        # Output Log Space
        log_frame = ttk.LabelFrame(self.lab_frame, text="Subprocess Output")
        log_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        self.lab_out = scrolledtext.ScrolledText(log_frame, wrap=tk.WORD, font=("Consolas", 10), bg="#1e1e1e", fg="#d4d4d4")
        self.lab_out.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # Ads Signal Dashboard
        sig_frame = ttk.LabelFrame(self.lab_frame, text="Candidate Ads Signals")
        sig_frame.pack(fill=tk.X, padx=5, pady=5)
        signals = (
            "FIELDS TO MAP FROM playerInfo.dat:\n"
            "- arkRewardReadyToClaim\n"
            "- pendingRewardType\n"
            "- rewardIsDarkMatterBool\n"
            "- lastAdWatchedDate\n"
            "- nextAdSeconds\n"
            "- adsWatched\n"
            "- arksClaimed\n"
            "- adAvailableBool\n"
            "- adFailedBool\n"
            "- adStartedFromBoost"
        )
        sig_text = scrolledtext.ScrolledText(sig_frame, height=12, font=("Consolas", 10))
        sig_text.pack(fill=tk.X, padx=5, pady=5)
        sig_text.insert("1.0", signals)
        sig_text.configure(state="disabled")

    def run_subprocess(self, cmd_list):
        for b in self.lab_btns:
            b.config(state=tk.DISABLED)
        self.lab_out.insert(tk.END, f"\n> {' '.join(cmd_list)}\n")
        self.lab_out.see(tk.END)
        
        def task():
            try:
                proc = subprocess.Popen(
                    cmd_list,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    cwd=r"C:\dev\ipm-bot",
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
                )
                for line in proc.stdout:
                    self.root.after(0, lambda l=line: [self.lab_out.insert(tk.END, l), self.lab_out.see(tk.END)])
                proc.wait()
                self.root.after(0, lambda: self.lab_out.insert(tk.END, f"[Exited with code {proc.returncode}]\n"))
            except Exception as e:
                self.root.after(0, lambda err=e: self.lab_out.insert(tk.END, f"[Exception: {err}]\n"))
            finally:
                self.root.after(0, lambda: [b.config(state=tk.NORMAL) for b in self.lab_btns])
                
        threading.Thread(target=task, daemon=True).start()

    def open_latest_receipt(self):
        r = FailureAnalyzer.find_latest_receipt(self.state.repo_root)
        if r and r.exists():
            (os.startfile(r) if os.name == 'nt' else subprocess.run(['open', r]))
            self.lab_out.insert(tk.END, f"\n> Opened receipt: {r.name}\n")
        else:
            self.lab_out.insert(tk.END, "\n> No receipt found.\n")

    def copy_ads_prompt(self):
        prompt = (
            "Analyze these IPM ad signals against the provided logs/receipt. "
            "Identify safe automation bounds for activate_ad_boost."
        )
        self.root.clipboard_clear()
        self.root.clipboard_append(prompt)
        self.lab_out.insert(tk.END, "\n> Copied analysis prompt to clipboard.\n")



    def build_status_bar(self):
        self.status_frame = ttk.Frame(self.root, relief=tk.SUNKEN)
        self.status_frame.pack(side=tk.BOTTOM, fill=tk.X)
        
        self.lbl_context_sz = ttk.Label(self.status_frame, text="Context Size Estimate: ~0", width=30)
        self.lbl_context_sz.pack(side=tk.LEFT, padx=10, pady=2)
        self.lbl_failure_mode = ttk.Label(self.status_frame, text="Failure Mode: None")
        self.lbl_failure_mode.pack(side=tk.LEFT, padx=10, pady=2)
        self.lbl_files_summary = ttk.Label(self.status_frame, text="0 Sources | 0 Evidence")
        self.lbl_files_summary.pack(side=tk.RIGHT, padx=10, pady=2)

    # --- Actions ---

    def change_repo_root(self):
        d = filedialog.askdirectory(initialdir=str(self.state.repo_root), title="Select Repository Root")
        if d:
            self.state.repo_root = Path(d)
            self.repo_var.set(str(self.state.repo_root))
            self.state.source_files.clear()
            self.state.evidence_files.clear()
            self.state.failure_classification = "unknown"
            self.state.receipt_meta = {}
            self.update_file_lists()

    def add_common_files(self):
        common = ["pyproject.toml", "README.md", "tests/conftest.py"]
        added = 0
        for name in common:
            p = self.state.repo_root / name
            if p.exists():
                self.state.source_files.add(p.resolve())
                added += 1
        for n in ["main.py", "run.py"]:
            p = self.state.repo_root / n
            if p.exists():
                self.state.source_files.add(p.resolve())
                added += 1
        self.update_file_lists()
        messagebox.showinfo("Auto-Add", f"Added {added} curated project files.")

    def analyze_failure(self):
        cls_name, meta, evidence, sources = FailureAnalyzer.analyze(self.state.repo_root)
        self.state.failure_classification = cls_name
        self.state.receipt_meta = meta
        
        recent_runs = SessionManager.load_recent_runs(self.state.repo_root, limit=5)
        pat_data = PrecomputedIntelligence.detect_patterns(recent_runs)
        
        for f in evidence:
            self.state.evidence_files.add(f.resolve())
        for f in sources:
            self.state.source_files.add(f.resolve())
            
        self.state.preset_name = "Receipt/runtime analysis"
        self.preset_var.set(self.state.preset_name)
        self.update_file_lists()
        
        # PROACTIVE GUIDANCE POPUP
        actions = PrecomputedIntelligence.generate_next_actions(cls_name, pat_data["is_looping"])
        action_text = PrecomputedIntelligence.format_actions(actions)
        truth_block = PrecomputedIntelligence.generate_truth_block(meta, cls_name)
        
        msg = f"--- DETERMINISTIC FAILURE DISCOVERED ---\nClassification: {cls_name}\n"
        msg += f"Files Loaded: {len(sources)}\n\n"
        msg += f"{truth_block}\n\n"
        if pat_data["text"]:
            msg += f"--- PATTERN ENGINE ---\n{pat_data['text']}\n\n"
        msg += f"--- PROACTIVE GUIDANCE (SUGGESTED ACTIONS) ---\n{action_text}"
        
        messagebox.showinfo("System Conclusion & Proactive Guidance", msg)

    def compare_saves(self):
        f1 = filedialog.askopenfilename(title="Select Save 1 (Older)", initialdir=str(self.state.repo_root))
        if not f1: return
        f2 = filedialog.askopenfilename(title="Select Save 2 (Newer)", initialdir=str(self.state.repo_root))
        if not f2: return
        
        try:
            intel, text_diff = SaveDiffer.compute_diff(Path(f1), Path(f2))
            self.sync_state()
            self.state.operator_notes += f"\n\n{intel}\n\n{text_diff}"
            self.txt_notes.delete("1.0", tk.END)
            self.txt_notes.insert("1.0", self.state.operator_notes.strip())
            messagebox.showinfo("Diff Complete", "Diff intelligence appended to Operator Notes.")
        except Exception as e:
            messagebox.showerror("Diff Error", str(e))

    def add_files(self, ftype='source'):
        files = filedialog.askopenfilenames(initialdir=str(self.state.repo_root))
        target_set = self.state.source_files if ftype == 'source' else self.state.evidence_files
        for f in files:
            target_set.add(Path(f).resolve())
        self.update_file_lists()

    def add_dir(self, ftype='source'):
        d = filedialog.askdirectory(initialdir=str(self.state.repo_root))
        if d:
            target_set = self.state.source_files if ftype == 'source' else self.state.evidence_files
            for p in Path(d).rglob("*"):
                if p.is_file() and not p.name.startswith(".") and "__pycache__" not in p.parts:
                    target_set.add(p.resolve())
            self.update_file_lists()

    def remove_files(self, ftype='source'):
        lst = self.lst_sources if ftype == 'source' else self.lst_evidence
        target_set = self.state.source_files if ftype == 'source' else self.state.evidence_files
        indices = lst.curselection()
        if not indices: return
        
        to_remove = [self.state.repo_root / lst.get(i) for i in indices]
        for f in to_remove:
            target_set.discard(f.resolve())
        self.update_file_lists()

    def preview_file(self, ftype='source'):
        lst = self.lst_sources if ftype == 'source' else self.lst_evidence
        indices = lst.curselection()
        if not indices: return
        rel_path = lst.get(indices[0])
        full_path = self.state.repo_root / rel_path
        
        if full_path.exists():
            try:
                content = full_path.read_text(encoding='utf-8')
                self.show_preview_window(f"Preview: {rel_path}", content)
            except Exception as e:
                messagebox.showerror("Read Error", str(e))

    def update_file_lists(self):
        self.lst_sources.delete(0, tk.END)
        for f in sorted(self.state.source_files):
            try:
                self.lst_sources.insert(tk.END, str(f.relative_to(self.state.repo_root)))
            except ValueError:
                self.lst_sources.insert(tk.END, str(f))
                
        self.lst_evidence.delete(0, tk.END)
        for f in sorted(self.state.evidence_files):
            try:
                self.lst_evidence.insert(tk.END, str(f.relative_to(self.state.repo_root)))
            except ValueError:
                self.lst_evidence.insert(tk.END, str(f))
                
        self.lst_receipt.configure(state='normal')
        self.lst_receipt.delete('1.0', tk.END)
        if self.state.receipt_meta and self.state.receipt_meta.get('action'):
            rm = self.state.receipt_meta
            text = f"Action: {rm.get('action')}\n"
            text += f"Status: {rm.get('final_status')}\n"
            text += f"Reason: {rm.get('failure_reason')}\n"
            text += f"Saves:  {rm.get('changed_save_count')}\n"
            text += f"Time:   {rm.get('elapsed_seconds')}s"
            self.lst_receipt.insert(tk.END, text)
        else:
            self.lst_receipt.insert(tk.END, "No recent receipt data loaded.")
        self.lst_receipt.configure(state='disabled')
                
        self.refresh_status()

    def on_preset_change(self, event=None):
        self.state.preset_name = self.preset_var.get()

    def sync_state(self):
        self.state.prompt_text = self.txt_prompt.get("1.0", tk.END)
        self.state.operator_notes = self.txt_notes.get("1.0", tk.END)
        self.state.model = self.model_var.get()
        self.state.preset_name = self.preset_var.get()

    def refresh_status(self):
        self.sync_state()
        c_size = self.state.get_heuristic_context_size()
        self.lbl_context_sz.config(
            text=f"Context Size Estimate: ~{c_size}",
            foreground="darkorange" if c_size > 50000 else "black"
        )
        self.lbl_failure_mode.config(text=f"Failure: {self.state.failure_classification}")
        self.lbl_files_summary.config(text=f"{len(self.state.source_files)} Sources | {len(self.state.evidence_files)} Evidence")

    def show_preview_window(self, title, content):
        top = tk.Toplevel(self.root)
        top.title(title)
        top.geometry("800x600")
        txt = scrolledtext.ScrolledText(top, wrap=tk.WORD, font=("Consolas", 10))
        txt.pack(fill=tk.BOTH, expand=True)
        txt.insert("1.0", content)
        txt.configure(state="disabled")

    def preview_compiled_prompt(self):
        self.sync_state()
        compiled = PromptCompiler.compile(self.state)
        self.show_preview_window("Compiled Prompt Preview", compiled)

    def copy_response(self):
        self.root.clipboard_clear()
        self.root.clipboard_append(self.txt_response.get("1.0", tk.END))
        messagebox.showinfo("Copied", "Response copied to clipboard.")

    def set_ui_state(self, running):
        state = tk.DISABLED if running else tk.NORMAL
        self.btn_run.config(state=state)
        self.txt_prompt.config(state=state)
        self.lbl_run_status.config(text="Running..." if running else "Idle", foreground="blue" if running else "gray")

    def run_api(self):
        self.sync_state()
        compiled_prompt = PromptCompiler.compile(self.state)
        self.txt_response.delete("1.0", tk.END)
        self.set_ui_state(True)
        
        def on_chunk(delta):
            self.root.after(0, lambda d=delta: self.txt_response.insert(tk.END, d))
            self.root.after(0, lambda: self.txt_response.see(tk.END))
            
        def on_done(full_text):
            def finalize():
                try:
                    saved_file = SessionManager.save_run(self.state, compiled_prompt, full_text)
                    self.lbl_run_status.config(text=f"Saved to {saved_file.name}", foreground="green")
                except Exception as e:
                    self.lbl_run_status.config(text="Error saving run log", foreground="red")
                self.set_ui_state(False)
            self.root.after(0, finalize)
            
        def on_error(err_str):
            def log_error():
                messagebox.showerror("API Error", err_str)
                self.lbl_run_status.config(text="API Failed", foreground="red")
                self.set_ui_state(False)
            self.root.after(0, log_error)

        self.api.stream_completion(
            model=self.state.model,
            prompt=compiled_prompt,
            on_chunk=on_chunk,
            on_done=on_done,
            on_error=on_error
        )

if __name__ == "__main__":
    style = ttk.Style()
    style.theme_use('clam')
    root = tk.Tk()
    app = WizardApp(root)
    root.mainloop()

