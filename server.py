import os, sys, subprocess, shutil, platform
from pathlib import Path

DSFREEHACK_DIR  = Path.home() / "DSFREEHACK"
WASM_CACHE_DIR  = DSFREEHACK_DIR / "wasm_cache"
IDE_DIR         = DSFREEHACK_DIR / "ide"
try: DSFREEHACK_DIR.mkdir(parents=True, exist_ok=True)
except Exception: pass
try: WASM_CACHE_DIR.mkdir(parents=True, exist_ok=True)
except Exception: pass
try: IDE_DIR.mkdir(parents=True, exist_ok=True)
except Exception: pass

IDE_STATE_FILE = IDE_DIR / "state.json"
IDE_CMD_FILE   = IDE_DIR / "cmd.jsonl"
IDE_LOG_FILE   = IDE_DIR / "log.txt"
VSCODE_EXT_DIR = Path.home() / ".vscode" / "extensions" / "rnalimov.dfreecode-ide-1.0.0"

def _pip_install(pkg, import_name=None):
    name = import_name or pkg
    try: __import__(name); return True
    except ImportError: pass
    print(f"  · auto-installing {pkg} ...")
    try:
        r = subprocess.run(
            [sys.executable,"-m","pip","install","--quiet","--disable-pip-version-check",pkg],
            capture_output=True, timeout=900,
            encoding="utf-8", errors="replace",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if r.returncode != 0:
            print(f"  ! {pkg} install failed: {((r.stderr or '') + (r.stdout or ''))[:300]}")
            return False
    except Exception as e:
        print(f"  ! {pkg} install error: {e}"); return False
    try: __import__(name); return True
    except ImportError:
        print(f"  ! {pkg} installed but import still fails"); return False

_pip_install("requests")
for _pkg, _imp in [("websocket-client","websocket"),("wasmtime","wasmtime"),("Pillow","PIL"),
                   ("pyautogui","pyautogui"),("prompt_toolkit","prompt_toolkit")]:
    _pip_install(_pkg, _imp)
_pip_install("rapidocr-onnxruntime", "rapidocr_onnxruntime")
_pip_install("opencv-python", "cv2")
_pip_install("numpy", "numpy")
_pip_install("pyperclip", "pyperclip")

import time, json, threading, re, random, base64, tempfile, signal, struct
import urllib.request, urllib.parse
import concurrent.futures as _cf
from datetime import datetime
from collections import Counter

try: sys.setrecursionlimit(100_000)
except Exception: pass

try: import requests
except ImportError: print("FATAL: requests missing"); sys.exit(1)
try: import wasmtime; WASMTIME_OK = True
except ImportError: WASMTIME_OK = False
try: import websocket; WEBSOCKET_OK = True
except ImportError: WEBSOCKET_OK = False
try: from PIL import Image, ImageDraw, ImageFont, ImageGrab; PIL_OK = True
except ImportError: PIL_OK = False
try: import pyautogui; PYAUTOGUI_OK = True
except ImportError: PYAUTOGUI_OK = False

RAPIDOCR_OK = False
_RAPIDOCR_ENGINE = None
try:
    from rapidocr_onnxruntime import RapidOCR
    import numpy as np
    RAPIDOCR_OK = True
except ImportError:
    RAPIDOCR_OK = False

try:
    from prompt_toolkit import PromptSession
    from prompt_toolkit.completion import Completer, Completion
    from prompt_toolkit.history import InMemoryHistory
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.keys import Keys
    PROMPT_AVAILABLE = True
except ImportError:
    PROMPT_AVAILABLE = False

def _get_rapidocr():
    global _RAPIDOCR_ENGINE
    if _RAPIDOCR_ENGINE is None and RAPIDOCR_OK:
        try:
            _RAPIDOCR_ENGINE = RapidOCR()
            print_ok("RapidOCR engine initialised")
        except Exception as e:
            print_error(f"RapidOCR init failed: {e}")
            _RAPIDOCR_ENGINE = None
    return _RAPIDOCR_ENGINE

# ─── UI ────────────────────────────────────────────────────────────────────
def _rgb(r,g,b): return f"\033[38;2;{r};{g};{b}m"
ACCENT,DIM,FAINT,FG,ERR_C,OK_C,WARN_C = _rgb(94,156,255),_rgb(163,174,189),_rgb(100,112,128),_rgb(232,237,245),_rgb(224,108,108),_rgb(126,176,122),_rgb(214,178,100)
RESET,BOLD = "\033[0m","\033[1m"
_print_lock = threading.Lock()

def _tw(d=80,c=110):
    try: w=shutil.get_terminal_size((d,24)).columns
    except Exception: w=d
    return max(50,min(w,c))
def print_info(m): sys.stdout.write(f"  {FAINT}·{RESET} {DIM}{m}{RESET}\n"); sys.stdout.flush()
def print_ok(m): sys.stdout.write(f"  {FAINT}·{RESET} {OK_C}{m}{RESET}\n"); sys.stdout.flush()
def print_warn(m): sys.stdout.write(f"  {FAINT}·{RESET} {WARN_C}{m}{RESET}\n"); sys.stdout.flush()
def print_error(m): sys.stdout.write(f"  {FAINT}·{RESET} {ERR_C}{m}{RESET}\n"); sys.stdout.flush()
def print_debug(m):
    if CONFIG.get("verbose_http",False): sys.stdout.write(f"  {FAINT}[dbg]{RESET} {FAINT}{m}{RESET}\n"); sys.stdout.flush()
def print_exec(p,cmd,prev=""):
    pr=(prev or "").split("\n")[0][:70]
    with _print_lock:
        sys.stdout.write(f"  {FAINT}exec{RESET} {ACCENT}{p}{RESET} {DIM}{cmd[:60]}{RESET}")
        if pr: sys.stdout.write(f"  {FAINT}→ {pr}{RESET}")
        sys.stdout.write("\n"); sys.stdout.flush()
def print_header(sub,cwd,ver="v16.7"):
    w=_tw()
    sys.stdout.write(f"\n{ACCENT}{FAINT}╭{'─'*(w-2)}╮{RESET}\n")
    left=f" {ACCENT}{BOLD}✻ DeepSeek Assistant{RESET}"
    pad=max(1,w-25-len(ver))
    sys.stdout.write(f"{FAINT}│{RESET}{left}{' '*pad}{FAINT}{ver}{RESET} {FAINT}│{RESET}\n")
    sys.stdout.write(f"{FAINT}│{RESET} {ACCENT}{sub}{RESET}\n")
    cs=cwd if len(cwd)<w-6 else "…"+cwd[-(w-7):]
    sys.stdout.write(f"{FAINT}│{RESET} {FAINT}{cs}{RESET}\n{FAINT}╰{'─'*(w-2)}╯{RESET}\n\n")
def print_response(resp,elapsed=None):
    m=re.match(r'^\[REASONING\]\n([\s\S]*?)\n\[/REASONING\]\n\n([\s\S]*)$',resp)
    if m:
        reasoning,answer=m.group(1).strip(),m.group(2).strip()
        if reasoning:
            sys.stdout.write(f"\n  {FAINT}▶ {ACCENT}thinking{RESET}\n")
            for l in reasoning.split("\n"): sys.stdout.write(f"  {FAINT}│{RESET} {DIM}{l}{RESET}\n")
            sys.stdout.write(f"  {FAINT}└─{RESET}\n")
        if answer:
            sys.stdout.write("\n")
            for l in answer.split("\n"): sys.stdout.write(f"  {FG}{l}{RESET}\n")
            sys.stdout.write("\n")
    else:
        sys.stdout.write("\n")
        for l in (resp or "").split("\n"): sys.stdout.write(f"  {FG}{l}{RESET}\n")
        sys.stdout.write("\n")
    if elapsed is not None: sys.stdout.write(f"  {FAINT}·{RESET} {FAINT}{elapsed:.1f}s{RESET}\n")
    sys.stdout.flush()

CONFIG = {
    "token":"","session_id":"","thinking":False,"search":False,
    "effort":"medium","security":"manual","language":"ru","system_prompt":"",
    "history_limit":500,
    "agent_max_iterations":0,
    "agents_enabled":True,"read_max_lines":500,"root_listing_enabled":True,
    "cdp_port":9222,
    "user_agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "timeout":300,"sse_silence_timeout":120,"verbose_http":False,
    "_tmp_profile":None,"_cancel":False,"loop_active":False,
    "fetch_max_bytes":500_000,"grid_step":50,"file_poll_timeout":120,
    "infinite_mode":False,
    "infinite_recent":30,"infinite_summary_budget":3000,
    "ocr_lang":"ru",
    "ocr_min_conf":30,
    "ai_blacklist":set(),
    "ai_whitelist":set(),
    "vars_max":25,
    "ide_welded":False,
    "wasm_url":os.environ.get("DEEPSEEK_WASM_URL",
        "https://fe-static.deepseek.com/chat/static/sha3_wasm_bg.7b9ca65ddd.wasm"),
    "system_prompt_every":10,
    "empty_retry_max":2,
    "long_cmd_timeout":300,   # hard ceiling for direct bash/powershell (sec)
    "shell_idle_kill":90,     # kill tree if silent for N sec while alive
}
TOKEN_FILE,HISTORY_FILE = "token.txt","chat_history.json"
FORCE_DEEPTHINK_EFFORTS={"high","ultracode","auto"}
SECURITY_ORDER=["manual","safe-auto","auto"]
FS_MARKERS={"READ:","WRITE:","EDIT:","LS:","GREP:","FIND:","FETCH:"}
SERIAL_MARKERS={"MOUSE:","SCREENSHOT:","PRESS:","PRINT:","OCR:"}
MARKER_AGENTS_RE=re.compile(r'<<<CUSTOM:\s*AGENTS\s*>>>',re.IGNORECASE)
MARKER_EDIT_IT_RE=re.compile(r'<<<CUSTOM:\s*EDIT-IT\s*\[(.*?)\]\s*>>>',re.IGNORECASE|re.DOTALL)
CMD_RE=re.compile(r'<<<\s*(.*?)\s*>>>',re.DOTALL)
BROKEN_CMD_RE=re.compile(
    r'<<<\s*(BASH|POWERSHELL|READ|WRITE|LS|GREP|FIND|EDIT|TASK|FETCH|MOUSE)\s*>>>\s*([^\n<]+)',
    re.IGNORECASE)
DEMO_TASKS=["Briefly describe what this project does, using the files in the current directory.",
    "Find all Python files in the current folder and propose one improvement idea.",
    "Check the current working directory for README or instructions and summarize them.",
    "Propose one safe refactoring for the main file of this project (or the closest analog).",
    "Draft a 3-step plan to improve code readability in this project."]
ANSWER_LANGUAGE_NAMES={"ru":"Russian","en":"English","de":"German"}

def _norm_cmd_name(s):
    s = s.strip().strip('"').strip("'").strip().rstrip(":").upper()
    if ":" in s: s = s.split(":")[-1].strip()
    return s

def _parse_ai_list(text):
    s=(text or "").strip()
    if s.startswith("[") and s.endswith("]"): s=s[1:-1]
    parts=re.split(r'\s*[;,]\s*',s)
    out=[]; seen=set()
    for p in parts:
        n=_norm_cmd_name(p)
        if n and n not in seen: seen.add(n); out.append(n)
    return out

_last_ctrlc=[0.0]
def install_ctrlc_handler():
    def h(s,f):
        now=time.time()
        if now-_last_ctrlc[0]<1.5:
            sys.stdout.write("\n"); sys.stdout.flush(); print_info("Exit."); os._exit(0)
        _last_ctrlc[0]=now; CONFIG["_cancel"]=True
        print_warn("Ctrl+C: cancel request (press again to exit)")
    try: signal.signal(signal.SIGINT,h)
    except Exception: pass

# ─── Промпты ──────────────────────────────────────────────────────────────
STRICT_RULES = """
[!!!!!!!!!! READ THIS FIRST — VIOLATION = BROKEN LOOP !!!!!!!!!!]
You are NOT a chatbot. You are a tool-calling agent. You emit EXACTLY ONE
of these two things per message:

    (A) One or more TOOL CALLS — each on its own line, EXACT syntax below.
    (B) A FINAL ANSWER in plain text, with ZERO <<<...>>> markers in it.

There is NO third option. Do not mix. Do not narrate. Do not apologize.
Do not explain what you are about to do. Just emit the calls or the answer.

[========== NO PROMISES — ACT, DON'T NARRATE ==========]
Writing "I'll check X", "Let me run Y", "First I need to look at Z",
"Starting with..." WITHOUT a matching tool call on the SAME turn is a BUG.

    ✗ WRONG:  "I'll check adb devices and read the log."         [no call]
    ✗ WRONG:  "Let me wait and check the build log."              [no call]
    ✗ WRONG:  "Let me plan: 1. … 2. … 3. …"                       [no call]

    ✓ RIGHT:  <<<BASH: adb devices>>>
    ✓ RIGHT:  <<<READ: vr_test.cpp>>>

RULE: every promise to act MUST be immediately followed by the tool call
on the NEXT LINE of the SAME message. If you have nothing to call — write
the FINAL ANSWER and stop.

[========== TOOL CALLS IN REASONING — STRICTLY FORBIDDEN ==========]
Your model has an internal "thinking" / reasoning block. TOOL CALLS ARE
FORBIDDEN THERE. The runner scans ONLY the FINAL ANSWER.

    ✗ NEVER write `<<<...>>>` inside a thinking block.

Correct pattern:
    thinking:  pure internal monologue, NO markers, NO tool syntax.
    answer:    EITHER the actual <<<...>>> calls, OR the final answer.

[========== LONG-RUNNING PROCESSES — HOW TO WAIT ==========]
To run something that takes a while (build, install, test, script) —
just call it DIRECTLY. The runner WAITS for it to finish, shows a live
progress indicator ("running: <cmd> · 12.3s · 45 lines") while it works,
and returns the COMPLETE stdout+stderr in the tool result. This is the
ONLY correct way to get output from a long command. Sleep-polling is
FORBIDDEN.

    ✓ <<<BASH: python build.py>>>
    ✓ <<<POWERSHELL: npm run build>>>
    ✓ <<<BASH: gradlew.bat assembleRelease>>>
    ✓ <<<BASH: pip install -r requirements.txt>>>
    ✓ <<<READ: D:\\LiquidBounce-0.40.0\\build\\build.log>>>

If a command is bigger than the runner's long-command window, split it
into stages you can read back with <<<READ: ...>>>. Do NOT try to sleep
or spin-wait.

Start-Process is ONLY for GUI apps you want to leave running in the
background (notepad, explorer, browser). It returns immediately; the
child's stdout/stderr is NOT captured by the runner. Use it ONLY for
that narrow case:

    ✓ <<<POWERSHELL: Start-Process notepad>>>
    ✓ <<<POWERSHELL: Start-Process explorer -ArgumentList 'D:\\projects'>>>

ABSOLUTELY FORBIDDEN — the runner REJECTS these with an error:
    ✗ sleep 5
    ✗ Start-Sleep -Seconds 5
    ✗ timeout /t 5
    ✗ ping -n 5 127.0.0.1              (sleep trick)
    ✗ Start-Process ... -Wait
    ✗ Wait-Process
    ✗ Start-Process cmd.exe -ArgumentList '/c','... && timeout /t 45 ...'
    ✗ Start-Process cmd.exe -ArgumentList '/c','... && Start-Sleep 5 ...'

Reason: the runner already waits for direct calls and returns the log.
Sleep-polling is a bug — you would re-read a stale file and PRETEND to
make progress. Do not do it.

[========== OCR vs SCREENSHOT ==========]
  OCR      →  CHEAP, text-only. Returns exact (x,y) centers of every
              visible text line. Use for ANYTHING you can NAME as text.
  SCREENSHOT →  EXPENSIVE, image upload. Use ONLY when pixels matter
              (icons, images, canvas, verifying a red marker).

  DECISION: name-able text → OCR. Pixels-only → SCREENSHOT.

[========== SYNTAX — THE #1 MISTAKE YOU KEEP MAKING ==========]
Marker is ALWAYS followed by a COLON, then a space, then the argument.
NO colon = NOT a tool call.

    WRONG:  <<<POWERSHELL>>> Start-Process mspaint
    RIGHT:  <<<POWERSHELL: Start-Process mspaint>>>
    WRONG:  <<<BASH>>> ls -la
    RIGHT:  <<<BASH: ls -la>>>
    WRONG:  <<<READ>>> main.py
    RIGHT:  <<<READ: main.py>>>
    WRONG:  <<<WRITE>>> a.txt|hello
    RIGHT:  <<<WRITE: a.txt|hello>>>
    WRONG:  <<<EDIT>>> a.py|old|new
    RIGHT:  <<<EDIT: a.py|old|new>>>
    WRONG:  <<<LS>>> .
    RIGHT:  <<<LS: .>>>
    WRONG:  <<<GREP>>> pattern
    RIGHT:  <<<GREP: pattern>>>
    WRONG:  <<<MOUSE>>> click 100,200
    RIGHT:  <<<MOUSE: click 100,200>>>
    WRONG:  <<<MOUSE>>> drag 100,200 800,500
    RIGHT:  <<<MOUSE: drag 100,200 800,500>>>
    WRONG:  <<<CUSTOM: PRESS>>> enter
    RIGHT:  <<<CUSTOM: PRESS enter>>>
    WRONG:  <<<CUSTOM: PRINT>>> hello
    RIGHT:  <<<CUSTOM: PRINT hello>>>
    WRONG:  <<<CUSTOM: SCREENSHOT>>> 500,300
    RIGHT:  <<<CUSTOM: SCREENSHOT 500,300>>>

[========== ALLOWED MARKERS ==========]
    <<<BASH: shell command>>>
    <<<POWERSHELL: ps command>>>
    <<<READ: path>>>  or  <<<READ: path:start-end>>>
    <<<WRITE: path|full content>>>
    <<<EDIT: path|old text|new text>>>
    <<<LS: path>>>
    <<<GREP: pattern>>>
    <<<FIND: name>>>
    <<<TASK: "text" N>>>
    <<<FETCH: https://url>>>
    <<<MOUSE: click x,y>>> | move x,y | rclick x,y | dblclick x,y
    <<<MOUSE: drag x1,y1 x2,y2>>>
    <<<IDE>>>
    <<<CUSTOM: OCR>>>
    <<<CUSTOM: SCREENSHOT [x,y]>>>
    <<<CUSTOM: PRESS key>>>
    <<<CUSTOM: PRINT text>>>

Only `<<<IDE>>>` and `<<<CUSTOM: OCR>>>` take NO argument.

[========== HARD RULES ==========]
1.  ONE marker per line.
2.  NEVER wrap commands in quotes/backticks/fences/JSON/XML.
3.  NEVER invent, guess, or simulate tool output.
4.  NEVER repeat the SAME call twice in a row without new info.
5.  Short narrative text between calls is OK, but the call MUST be present.
6.  NEVER ask the user for info you can get with a tool.
7.  DONE → plain-text FINAL ANSWER, ZERO markers. Only way to end a turn.

[========== SHELL RULES ==========]
- BASH: runs via cmd.exe on Windows.
- POWERSHELL: passes through `powershell -Command "<arg>"`. No extra quotes.
- POWERSHELL does NOT understand `&&` or `||` (Windows PowerShell 5.1).
  For chaining in PS use `;` — but for `cd /d X && cmd` style use
  <<<BASH: ...>>> instead. If you put `&&` in a POWERSHELL command, the
  runner auto-routes it to BASH.
- `cd /d X` is cmd syntax. In PowerShell use `Set-Location X`.
- To read a FILE use <<<READ: path>>> — NEVER `type file` / `cat file`
  in BASH. `type` mangles UTF-8 / UTF-16 / non-ASCII on Windows.
- Windows Gradle projects: use `gradlew.bat` (wrapper), NOT `gradle`.
  Do not `cd X && gradle` — use <<<BASH: cd /d X && gradlew.bat build>>>.
- If a shell command fails with "not recognized" / "не является внутренней" —
  the exe does not exist. List the directory or use <<<FIND: name>>>.
  Do NOT retry the same command.
- Do NOT use `timeout /t`, `Start-Sleep`, `sleep`, `ping -n` — see
  [LONG-RUNNING PROCESSES] above. They are REJECTED by the runner.

[========== READ / WRITE / EDIT ==========]
- READ: `path` or `path:start-end` (1-based).
- WRITE: `path|content`.
- EDIT: `path|old|new` — first occurrence of `old` → `new`. `old` must be unique.

[========== SCREENSHOT GRID ==========]
Mesh 50×50 px. Origin (0,0) top-left. X right, Y down.
Yellow numbers on top = X, on left = Y. Subdivide each cell into 5 → 10 px precision.
Cursor drawn as cyan crosshair; its coords also in the info header.

[========== CLICK CORRECTION ==========]
Miss = confirmed by FRESH screenshot/OCR. Compute dx,dy = target - click.
Apply SAME delta. Max 3 corrections per element.

[========== UI NUANCES ==========]
- DESKTOP icons → DOUBLE-CLICK.
- FILE EXPLORER → DOUBLE-CLICK contents, SINGLE left tree.
- TASKBAR/BROWSER/MENUS/DIALOGS → SINGLE click.
- TEXT FIELDS → SINGLE focus, THEN <<<CUSTOM: PRINT ...>>>.
- DRAG: <<<MOUSE: drag x1,y1 x2,y2>>>.

[========== "-mt" PARALLEL FLAG ==========]
Parallel-safe: READ, LS, GREP, FIND, FETCH, BASH, POWERSHELL, WRITE, EDIT.
Serial-only (ignored): MOUSE, SCREENSHOT, OCR, PRESS, PRINT.

[========== SECURITY MODES ==========]
manual / safe-auto / auto. If "[NAME] command not available" → move on.

[========== AUTONOMY ==========]
- Tool fails → try 2 corrections BEFORE reporting.
- Never ask for obtainable info.
- Report DID + RESULT, not difficulties.

[========== FINAL REMINDER ==========]
ACT, do not narrate. Every "I'll do X" must be followed by the call.
When done → plain text, ZERO markers.
"""
MEMORY_HINT = ("[FIRST STEP] Before answering — locate and read memory.md "
    "(in cwd and subdirs, e.g. via <<<FIND: memory.md>>> and <<<READ: ...>>>). "
    "If absent — fall back to AGENTS.md, CLAUDE.md, README.md.")
_CMDS = ("Available commands: <<<BASH: cmd>>>, <<<POWERSHELL: cmd>>>, <<<READ: path>>>, "
         "<<<WRITE: path|content>>>, <<<LS: path>>>,\n<<<GREP: pattern>>>, <<<FIND: name>>>, "
         "<<<EDIT: path|old|new>>>, <<<TASK: \"text\" N>>>, <<<FETCH: url>>>, "
         "<<<MOUSE: click|move|rclick|dblclick x,y>>>,\n<<<MOUSE: drag x1,y1 x2,y2>>>, <<<IDE>>>, "
         "<<<CUSTOM: OCR>>> (cheap, text+coords), <<<CUSTOM: SCREENSHOT [x,y]>>> (expensive, visual), "
         "<<<CUSTOM: PRESS key>>>, <<<CUSTOM: PRINT text>>>.\n"
         "Long-running build/test/install → run DIRECTLY with <<<BASH: ...>>> — "
         "the runner WAITS for it, shows live progress, and returns the full log. "
         "NEVER use sleep / Start-Sleep / timeout /t / Start-Process -Wait — those are "
         "REJECTED. Start-Process is ONLY for background GUI apps (notepad, explorer).")
_TMPL = ("You are DeepSeek. {desc}\n" + _CMDS + "\n"
    "[Security: {security}] {security_hint}\n"
    "Settings: effort={effort}, model={model}, cwd={cwd}\n"
    "Answer language: {answer_language}. Only the final natural-language answer must be in {answer_language}.")
SYSTEM_PROMPTS = {
    "low": _TMPL.replace("{desc}","Mode LOW. Concise, no emojis, minimal agency."),
    "medium": _TMPL.replace("{desc}","Mode MEDIUM. Concise, autonomous, no emojis."),
    "high": _TMPL.replace("{desc}","HIGH. DEEPTHINK ENABLED. Use <<<CUSTOM: AGENTS>>>. Tool calls in ANSWER, never in thinking."),
    "ultracode": _TMPL.replace("{desc}","ULTRACODE. DEEPTHINK ENABLED. Actively use <<<CUSTOM: AGENTS>>>. Tool calls in ANSWER, never in thinking."),
    "auto": _TMPL.replace("{desc}","AUTO. DEEPTHINK ENABLED. Always use <<<CUSTOM: AGENTS>>>. Tool calls in ANSWER, never in thinking."),
}
SECURITY_HINTS={
    "manual":"Ask for confirmation before EVERY command, including OCR, PRESS, PRINT and SCREENSHOT (unless a /wl whitelist overrides it).",
    "safe-auto":"OCR, PRESS, and file ops inside cwd run without confirmation. Bash/PowerShell, writes outside cwd, MOUSE, PRINT and SCREENSHOT still ask.",
    "auto":"Any command runs without confirmation."}
INDEX_MULTIAGENT_HEADER="[MULTI-AGENT MODE]\nYou are the INDEX AGENT. Call <<<CUSTOM: AGENTS>>> to run an iteration.\nUser task: {task}\n\n"+STRICT_RULES
DEV2_PROMPT="[AGENT-DEVELOPER 2]\nTask: {task}\nIndex plan: {index_response}\nAnalyze, propose alternatives, find problems. Keep it concise.\n\n"+STRICT_RULES
REVIEW_PROMPT="[REVIEW AGENT]\nTask: {task}\nIndex: {index_response}\nDev2: {dev2_response}\nIf there are issues — call <<<CUSTOM: EDIT-IT[reason]>>>.\n\n"+STRICT_RULES
SAFE_REVIEW_PROMPT="[SAFE REVIEW AGENT]\nTask: {task}\nIndex: {index_response}\nDev2: {dev2_response}\nReview: {review_response}\nVerdict: SAFE / NEEDS_FIXES / DANGEROUS.\n\n"+STRICT_RULES
_ROOT_IGNORE={'.git','.svn','.hg','.idea','.vscode','.DS_Store','__pycache__','node_modules',
    '.pytest_cache','.mypy_cache','.tox','venv','.venv','env','.env','dist','build','.next','.nuxt','target','bin','obj'}
def get_root_listing(max_entries=40,max_chars=900):
    try: entries=sorted(os.listdir('.'))
    except Exception: return "(cannot list)"
    dirs,files,hidden=[],[],0
    for name in entries:
        if name in _ROOT_IGNORE: hidden+=1; continue
        full=os.path.join('.',name)
        try:
            if os.path.isdir(full): dirs.append(f"{name}/")
            else: files.append(name)
        except Exception: files.append(name)
    ordered=dirs+files; total=len(ordered); shown=ordered[:max_entries]
    text=", ".join(shown)
    if total>len(shown): text+=f" …(+{total-len(shown)})"
    if hidden: text+=f" [{hidden} ignored]"
    if not text: text="(empty)"
    if len(text)>max_chars: text=text[:max_chars-3]+"..."
    return text
def current_model_name():
    dts,sch=CONFIG["thinking"],CONFIG["search"]
    if dts and sch: return "deepseek-reasoner-search"
    if dts: return "deepseek-reasoner"
    if sch: return "deepseek-search"
    return "deepseek-chat"
def current_model_type():
    dts,sch=CONFIG["thinking"],CONFIG["search"]
    if dts and sch: return "reasoner-search"
    if dts: return "reasoner"
    if sch: return "search"
    return "default"
def _answer_language_name(): return ANSWER_LANGUAGE_NAMES.get(CONFIG.get("language","ru"),"Russian")
def build_system_prompt():
    base=SYSTEM_PROMPTS.get(CONFIG["effort"],SYSTEM_PROMPTS["medium"])
    prompt=base.format(effort=CONFIG["effort"],model=current_model_name(),
        security=CONFIG["security"],security_hint=SECURITY_HINTS.get(CONFIG["security"],""),
        cwd=os.getcwd(),answer_language=_answer_language_name())
    if CONFIG.get("root_listing_enabled",True):
        prompt+=f"\n\n[FILES IN cwd ROOT]\n{get_root_listing()}\n(use READ/LS for details)"
    if CONFIG.get("ide_welded"):
        st = _read_ide_state(max_age_sec=30)
        if st:
            ide_lines = ["[IDE CONTEXT — the user has these open right now]"]
            if st.get("workspace"): ide_lines.append(f"workspace: {st['workspace']}")
            if st.get("activeFile"): ide_lines.append(f"active file: {st['activeFile']}")
            sel = st.get("selection") or {}
            if sel.get("text"):
                t = sel["text"]
                if len(t) > 500: t = t[:500] + "…"
                ide_lines.append(f"selection (lines {sel.get('start',{}).get('line',0)+1}–{sel.get('end',{}).get('line',0)+1}):")
                ide_lines.append(t)
            opens = st.get("openFiles") or []
            if opens:
                ide_lines.append("open tabs: " + ", ".join(os.path.basename(p) for p in opens[:12]))
            prompt += "\n\n" + "\n".join(ide_lines)
    return MEMORY_HINT+"\n\n"+STRICT_RULES+"\n\n"+prompt

def normalize_token(raw):
    if not raw: return ""
    t=raw.strip().lstrip("\ufeff").strip('"').strip("'")
    if not t: return ""
    if t.startswith("{") and t.endswith("}"):
        try: j=json.loads(t)
        except Exception: return ""
        if not isinstance(j,dict): return ""
        for k in ("value","token","userToken","access_token"):
            v=j.get(k)
            if isinstance(v,str) and v.strip(): return v.strip()
        return ""
    return t
def _looks_like_real_token(t):
    if not t or not isinstance(t,str) or len(t)<20: return False
    if t.startswith("{") or t.startswith("<"): return False
    if t.startswith("eyJ") and t.count(".")>=2: return True
    if " " in t or "\n" in t: return False
    return len(t)>=30

# ─── kill tree ─────────────────────────────────────────────────────────────
def _kill_tree(proc):
    """Kill a process AND its whole child tree (Windows: taskkill /F /T)."""
    if proc is None:
        return
    try:
        if platform.system() == "Windows" and proc.pid:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                capture_output=True, timeout=5,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            return
    except Exception:
        pass
    try: proc.kill()
    except Exception: pass

# ─── safe subprocess + LIVE progress ───────────────────────────────────────
def _run_capture(args, timeout=60, shell=False,
                 stdin_devnull=True, fire_and_forget=False, label=None):
    """
    Robust subprocess runner with LIVE progress.

    Root-cause fixes:
      * Reader uses os.read(fd, 4096) — returns as soon as ANY byte is
        available. `proc.stdout.read(N)` blocks until N bytes are read
        or EOF, which froze the reader on short outputs.
      * Exit detection uses a dedicated waiter thread on proc.wait(),
        not poll() in the render loop. When the child dies, the main
        loop breaks immediately — no stuck-at-50s.
      * On exit/timeout/kill, proc.stdout.close() unblocks a possibly
        still-blocked reader.

    Watchdogs:
      * effective_timeout — hard wall-clock ceiling.
      * idle_kill_after   — no bytes for N seconds AND still alive → kill
        (catches PS 5.1 hung parse, or a shell waiting for stdin).
    """
    kwargs = dict(
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        shell=shell,
        bufsize=0,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if stdin_devnull:
        kwargs["stdin"] = subprocess.DEVNULL

    try:
        proc = subprocess.Popen(args, **kwargs)
    except Exception as e:
        return f"Error: {type(e).__name__}: {e}"

    fd = proc.stdout.fileno()
    out_lines = []
    stats = {"chars": 0}
    lock = threading.Lock()
    last_growth = [time.time()]

    def _reader():
        try:
            while True:
                try:
                    raw = os.read(fd, 4096)
                except OSError:
                    break
                except Exception:
                    break
                if not raw:
                    break
                try:
                    chunk = raw.decode("utf-8", errors="replace")
                except Exception:
                    chunk = raw.decode("latin-1", errors="replace")
                with lock:
                    stats["chars"] += len(chunk)
                    last_growth[0] = time.time()
                    norm = chunk.replace("\r\n", "\n").replace("\r", "\n")
                    for ln in norm.split("\n"):
                        if ln.strip():
                            out_lines.append(ln)
        except Exception:
            pass

    th = threading.Thread(target=_reader, daemon=True)
    th.start()

    # Reliable exit detection, independent of the render loop.
    done = threading.Event()
    def _waiter():
        try: proc.wait()
        except Exception: pass
        finally: done.set()
    threading.Thread(target=_waiter, daemon=True).start()

    if label is None:
        label_txt = args if isinstance(args, str) else " ".join(map(str, args))
    else:
        label_txt = label
    label_txt = re.sub(r"\s+", " ", label_txt)[:60]

    spark = ["✻","✼","✽","✾","❋","✺","✹","✸","✶","✷"]
    spin = 0
    timed_out = False
    killed_idle = False
    effective_timeout = 15 if fire_and_forget else timeout
    idle_kill_after = 45 if fire_and_forget else int(CONFIG.get("shell_idle_kill", 90))

    def _fb(n):
        if n < 1024: return f"{n} B"
        if n < 1048576: return f"{n/1024:.1f} KB"
        return f"{n/1048576:.2f} MB"

    start = time.time()
    try:
        while not done.is_set():
            now = time.time()
            el = now - start
            if effective_timeout and el > effective_timeout:
                timed_out = True
                _kill_tree(proc)
                done.wait(timeout=3.0)
                break
            silent = now - last_growth[0]
            if el > idle_kill_after and silent > idle_kill_after:
                killed_idle = True
                _kill_tree(proc)
                done.wait(timeout=3.0)
                break
            with lock:
                nl = len(out_lines)
                nb = stats["chars"]
            s = spark[spin % len(spark)]
            tail = ""
            if nb == 0 and el > 10:
                tail = f"  {WARN_C}(no output yet){RESET}"
            line = (f"\r  {FAINT}·{RESET} {ACCENT}{s}{RESET} "
                    f"{DIM}running{RESET} {FG}{label_txt}{RESET} "
                    f"{FAINT}· {el:5.1f}s · {_fb(nb)} · {nl} lines{RESET}"
                    f"{tail}")
            with _print_lock:
                sys.stdout.write(line + "    ")
                sys.stdout.flush()
            spin += 1
            time.sleep(0.1)
    except KeyboardInterrupt:
        _kill_tree(proc)
        done.wait(timeout=2.0)
        raise

    # Force-close pipe from parent — unblocks a stuck reader if any.
    try: proc.stdout.close()
    except Exception: pass
    try: th.join(timeout=1.0)
    except Exception: pass

    with _print_lock:
        try: cols = shutil.get_terminal_size((120, 24)).columns
        except Exception: cols = 120
        sys.stdout.write("\r" + " " * max(80, cols) + "\r")
        sys.stdout.flush()

    with lock:
        lines_copy = list(out_lines)
    out = "\n".join(lines_copy).strip()
    total_bytes = stats["chars"]

    if timed_out:
        body = out if out else "(no output before timeout)"
        return body + (f"\n[timeout: killed process tree after "
                       f"{effective_timeout}s. Total output: {total_bytes} bytes.]")
    if killed_idle:
        body = out if out else "(no output)"
        return body + (f"\n[watchdog: killed process tree — silent for "
                       f"{idle_kill_after}s while still alive. Likely a hung "
                       f"shell (e.g. PowerShell 5.1 parse-error on `&&`). "
                       f"Total output: {total_bytes} bytes.]")
    if not out:
        out = "(no output)"
    if fire_and_forget:
        out += "\n[fire-and-forget: process launched, python did not wait]"
    return out


# ─── Forbidden-wait detection ──────────────────────────────────────────────
_FORBIDDEN_PATTERNS = (
    (re.compile(r'\bstart-sleep\b', re.IGNORECASE),
     "Start-Sleep is FORBIDDEN — the runner already waits and returns the log"),
    (re.compile(r'(?<![\w-])sleep(?![\w-])', re.IGNORECASE),
     "`sleep` is FORBIDDEN — the runner already waits and returns the log"),
    (re.compile(r'\btimeout\s+/t\b', re.IGNORECASE),
     "`timeout /t` is FORBIDDEN — the runner already waits and returns the log"),
    (re.compile(r'\bping\b[^\n]{0,80}?-n\s+\d+', re.IGNORECASE),
     "`ping -n N` used as a sleep trick is FORBIDDEN"),
    (re.compile(r'\bwait-process\b', re.IGNORECASE),
     "Wait-Process is FORBIDDEN"),
    (re.compile(r'\bwait-event\b', re.IGNORECASE),
     "Wait-Event is FORBIDDEN"),
    (re.compile(r'(?<!\S)Start-Process(?!\S)[^\n]*?-Wait\b', re.IGNORECASE),
     "`Start-Process ... -Wait` is FORBIDDEN — it blocks the loop"),
    (re.compile(r'(?<!\S)Start-Process(?!\S)[^\n]*?\bcmd\.exe\b[^\n]*?(?:/c\b|/k\b)',
                re.IGNORECASE),
     "Start-Process of cmd.exe /c is FORBIDDEN — this is an attempt to hide "
     "a synchronous shell. Run cmd.exe directly in <<<BASH: ...>>> instead."),
)
def _forbidden_reason(cmd):
    if not cmd: return None
    for rx, why in _FORBIDDEN_PATTERNS:
        if rx.search(cmd):
            return why
    return None

# ─── Shell "not found" annotation ──────────────────────────────────────────
_SHELL_NOT_FOUND_RX = re.compile(
    r"(not recognized as an internal or external command"
    r"|не является внутренней или внешней командой"
    r"|is not recognized"
    r"|CommandNotFoundException"
    r"|The term '.*?' is not recognized"
    r"|is not defined)",
    re.IGNORECASE | re.DOTALL,
)

def _annotate_shell_output(cmd, out):
    """
    If a shell command failed with 'not recognized', append an explicit
    hint so the model stops repeating the same broken command.
    """
    if not out or not _SHELL_NOT_FOUND_RX.search(out):
        return out
    exe_hint = ""
    m = re.search(r'["\']?([\w.\-\\/]+?\.(?:bat|cmd|exe|ps1))["\']?', cmd or "")
    if m:
        exe_hint = f"  The command tried to run: {m.group(1)}\n"
    hint = (
        "\n[runner hint] The shell reported NOT FOUND — the executable does "
        "not exist. Do NOT repeat the same command. Do this instead:\n"
        f"{exe_hint}"
        "  (1) See what's actually in the directory:  <<<LS: .>>>\n"
        "  (2) On Windows the Gradle wrapper is `gradlew.bat`, NOT `gradle`.\n"
        "      Try: <<<BASH: gradlew.bat build>>>\n"
        "  (3) Locate the real executable: <<<FIND: gradlew>>> or "
        "<<<BASH: where gradle>>>\n"
        "  (4) Only after you know the correct path — run it."
    )
    return out + hint

# ─── "promise without action" heuristic ───────────────────────────────────
_PROMISE_TRIGGERS_EN = (
    "i'll ", "i will ", "let me ", "let's ", "i'm going to ", "i am going to ",
    "next, ", "next i ", "first, ", "first i ", "now i ", "now let ",
    "starting with ", "starting by ", "i need to ", "i should ",
    "checking ", "reading ", "running ", "executing ", "calling ",
    "invoking ", "fetching ", "greping ", "grepping ", "searching ",
    "waiting ", "let me wait",
)
_PROMISE_TRIGGERS_RU = (
    "сейчас ", "проверю ", "прочитаю ", "запущу ", "начну ", "давай ",
    "сначала ", "потом ", "далее ", "иду ", "открою ", "заберу ",
    "посмотрю ", "гляну ", "поищу ", "выполню ", "подожду ", "жду ",
)
_PROMISE_FINISHED = (
    "done", "completed", "finished", "готово", "выполнено", "завершено",
    "итог", "итого", "результат:", "task is complete", "задача выполнена",
)
def _looks_like_promise(text):
    if not text: return False
    t = text.strip()
    if len(t) < 15: return False
    low = t.lower()
    if any(f in low for f in _PROMISE_FINISHED):
        return False
    return any(tr in low for tr in _PROMISE_TRIGGERS_EN) or \
           any(tr in low for tr in _PROMISE_TRIGGERS_RU)

# ─── Thinking Animator ────────────────────────────────────────────────────
class ThinkingAnimator:
    SPARKS = ["✻", "✼", "✽", "✾", "❋", "✺", "✹", "✸", "✶", "✷"]
    _HUES = [
        (94,156,255),(120,180,255),(168,140,255),(220,120,240),
        (255,120,180),(255,150,140),(230,190,120),(150,220,160),(94,200,220),
    ]
    def __init__(self, label="Thinking"):
        self.label = label
        self._stop = threading.Event()
        self._thread = None
        self._tokens = 0
        self._t0 = time.time()
        self._lock = threading.Lock()
        self._last_len = 0
    @classmethod
    def _lerp_color(cls, t):
        n = len(cls._HUES); x = (t % 1.0) * n
        i = int(x) % n; j = (i + 1) % n; k = x - int(x)
        a = cls._HUES[i]; b = cls._HUES[j]
        return (int(a[0]*(1-k)+b[0]*k), int(a[1]*(1-k)+b[1]*k), int(a[2]*(1-k)+b[2]*k))
    def start(self):
        self._t0 = time.time()
        self._thread = threading.Thread(target=self._run, daemon=True); self._thread.start()
    def set_tokens(self, n):
        try: n = int(n)
        except Exception: return
        with self._lock: self._tokens = max(0, n)
    def stop(self, keep_line=False):
        self._stop.set()
        if self._thread:
            try: self._thread.join(timeout=1.0)
            except Exception: pass
        if not keep_line:
            with _print_lock:
                sys.stdout.write("\r" + " " * (self._last_len + 2) + "\r"); sys.stdout.flush()
            self._last_len = 0
    def _fmt_tokens(self, n):
        if n < 1000: return f"{n}"
        if n < 10000: return f"{n/1000:.1f}k"
        if n < 1_000_000: return f"{n//1000}k"
        return f"{n/1_000_000:.1f}M"
    def _run(self):
        tick = 0
        while not self._stop.is_set():
            with self._lock: toks = self._tokens
            elapsed = time.time() - self._t0
            r, g, b = self._lerp_color((time.time() * 0.35) % 1.0)
            col = f"\033[38;2;{r};{g};{b}m"
            spark = self.SPARKS[tick % len(self.SPARKS)]
            tok_s = self._fmt_tokens(toks)
            line = (f"  {col}{spark}{RESET} {col}{self.label}…{RESET} "
                    f"{FAINT}{tok_s} tokens · {elapsed:.0f}s{RESET}")
            visible = re.sub(r'\033\[[0-9;]*m', '', line); vislen = len(visible)
            with _print_lock:
                pad = max(0, self._last_len - vislen)
                sys.stdout.write("\r" + line + (" " * pad)); sys.stdout.flush()
                self._last_len = vislen
            tick += 1; time.sleep(0.08)


# ─── IDE bridge ────────────────────────────────────────────────────────────
IDE_EXT_PACKAGE_JSON = '''{
  "name": "dfreecode-ide",
  "displayName": "DeepSeek Free Code",
  "description": "Bridge for DFreeCode CLI — exposes active file, selection, and applies AI edits.",
  "version": "1.0.0",
  "publisher": "rnalimov",
  "engines": { "vscode": "^1.60.0" },
  "activationEvents": ["onStartupFinished"],
  "main": "./extension.js",
  "contributes": {
    "commands": [
      { "command": "dfreecode.status", "title": "DFreeCode: Show Status" },
      { "command": "dfreecode.openCwd", "title": "DFreeCode: Open Workspace" }
    ]
  }
}
'''

IDE_EXT_EXTENSION_JS = r'''
const vscode = require('vscode');
const fs = require('fs');
const path = require('path');
const os = require('os');
const crypto = require('crypto');

const DIR        = path.join(os.homedir(), 'DSFREEHACK', 'ide');
const STATE_FILE = path.join(DIR, 'state.json');
const CMD_FILE   = path.join(DIR, 'cmd.jsonl');
const LOG_FILE   = path.join(DIR, 'log.txt');

let statusBar = null;
let lastCmdOffset = 0;
let tickCounter = 0;
const bootId = crypto.randomBytes(6).toString('hex');

function log(msg) {
    try { fs.appendFileSync(LOG_FILE, `[${new Date().toISOString()}] ${msg}\n`); } catch(e){}
}

function writeState() {
    try {
        const editor = vscode.window.activeTextEditor;
        const ws = vscode.workspace.workspaceFolders;
        const state = {
            ts: Date.now(),
            tick: ++tickCounter,
            bootId: bootId,
            pid: process.pid,
            vscode: vscode.version,
            workspace: (ws && ws[0]) ? ws[0].uri.fsPath : null,
            activeFile: editor ? editor.document.uri.fsPath : null,
            language: editor ? editor.document.languageId : null,
            lineCount: editor ? editor.document.lineCount : 0,
            selection: editor ? {
                start: { line: editor.selection.start.line, char: editor.selection.start.character },
                end:   { line: editor.selection.end.line,   char: editor.selection.end.character },
                text: editor.document.getText(editor.selection)
            } : null,
            openFiles: vscode.workspace.textDocuments
                .filter(d => d.uri.scheme === 'file')
                .map(d => d.uri.fsPath)
        };
        fs.writeFileSync(STATE_FILE, JSON.stringify(state, null, 2));
    } catch (e) { log('writeState: ' + e.message); }
}

function setStatus(txt) {
    if (!statusBar) return;
    statusBar.text = '$(radio-tower) ' + txt;
}

async function applyCommand(cmd) {
    if (!cmd || !cmd.cmd) return;
    log('cmd: ' + JSON.stringify(cmd).substring(0, 300));
    try {
        if (cmd.cmd === 'open') {
            if (cmd.file) {
                const uri = vscode.Uri.file(cmd.file);
                const doc = await vscode.workspace.openTextDocument(uri);
                const ed = await vscode.window.showTextDocument(doc);
                if (typeof cmd.line === 'number') {
                    const line = Math.max(0, Math.min(cmd.line - 1, doc.lineCount - 1));
                    const pos = new vscode.Position(line, 0);
                    ed.selection = new vscode.Selection(pos, pos);
                    ed.revealRange(new vscode.Range(pos, pos), vscode.TextEditorRevealType.InCenter);
                }
            }
        } else if (cmd.cmd === 'diff') {
            if (cmd.file) {
                const right = vscode.Uri.file(cmd.file);
                const left = vscode.Uri.parse('dfreecode-orig:' + encodeURIComponent(cmd.file));
                await vscode.commands.executeCommand('vscode.diff', left, right, (cmd.title || 'DFreeCode diff'));
            }
        } else if (cmd.cmd === 'notify') {
            if (cmd.text) vscode.window.showInformationMessage(String(cmd.text));
        } else if (cmd.cmd === 'status') {
            setStatus(cmd.text || 'DFreeCode');
        } else if (cmd.cmd === 'reveal') {
            if (cmd.file) {
                const uri = vscode.Uri.file(cmd.file);
                await vscode.commands.executeCommand('revealInExplorer', uri);
            }
        }
    } catch (e) { log('applyCommand: ' + e.message); }
}

async function processCmdFile() {
    try {
        if (!fs.existsSync(CMD_FILE)) return;
        const st = fs.statSync(CMD_FILE);
        if (st.size <= lastCmdOffset) return;
        const fd = fs.openSync(CMD_FILE, 'r');
        const buf = Buffer.alloc(st.size - lastCmdOffset);
        fs.readSync(fd, buf, 0, buf.length, lastCmdOffset);
        fs.closeSync(fd);
        lastCmdOffset = st.size;
        const lines = buf.toString('utf8').split('\n').filter(x => x.trim());
        for (const line of lines) {
            try { await applyCommand(JSON.parse(line)); } catch(e){}
        }
    } catch (e) {}
}

function activate(ctx) {
    try { fs.mkdirSync(DIR, { recursive: true }); } catch(e){}
    statusBar = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 100);
    statusBar.text = '$(radio-tower) DFreeCode';
    statusBar.tooltip = 'DeepSeek Free Code — bridged to CLI';
    statusBar.command = 'dfreecode.status';
    statusBar.show();

    ctx.subscriptions.push(vscode.commands.registerCommand('dfreecode.status', () => {
        const ed = vscode.window.activeTextEditor;
        const info = ed
            ? 'Active: ' + path.basename(ed.document.fileName) + ' (' + ed.document.lineCount + ' lines)'
            : 'No active file';
        vscode.window.showInformationMessage('DFreeCode: ' + info);
    }));
    ctx.subscriptions.push(vscode.commands.registerCommand('dfreecode.openCwd', () => {
        const ws = vscode.workspace.workspaceFolders;
        if (ws && ws[0]) vscode.commands.executeCommand('revealInExplorer', ws[0].uri);
    }));

    writeState();
    setInterval(writeState, 800);
    setInterval(processCmdFile, 400);

    ctx.subscriptions.push(vscode.window.onDidChangeActiveTextEditor(writeState));
    ctx.subscriptions.push(vscode.window.onDidChangeTextEditorSelection(writeState));
    ctx.subscriptions.push(vscode.workspace.onDidOpenTextDocument(writeState));
    ctx.subscriptions.push(vscode.workspace.onDidCloseTextDocument(writeState));
    ctx.subscriptions.push(vscode.workspace.onDidSaveTextDocument(writeState));

    log('activated bootId=' + bootId + ' pid=' + process.pid);
}

function deactivate() {
    if (statusBar) statusBar.dispose();
    try { fs.unlinkSync(STATE_FILE); } catch(e){}
}

module.exports = { activate, deactivate };
'''

def _find_code_cli():
    names_win = ["code.cmd", "code.exe", "cursor.cmd", "windsurf.cmd"]
    for n in names_win:
        p = shutil.which(n.replace(".cmd", "").replace(".exe", ""))
        if p: return p
    cands = []
    if platform.system() == "Windows":
        la = os.environ.get("LOCALAPPDATA", "")
        pf = os.environ.get("ProgramFiles", r"C:\Program Files")
        pf86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
        cands += [
            os.path.join(la, r"Programs\Microsoft VS Code\bin\code.cmd"),
            os.path.join(la, r"Programs\Microsoft VS Code\Code.exe"),
            os.path.join(pf, r"Microsoft VS Code\Code.exe"),
            os.path.join(pf86, r"Microsoft VS Code\Code.exe"),
            os.path.join(la, r"Programs\cursor\Cursor.exe"),
            os.path.join(la, r"Programs\Windsurf\Windsurf.exe"),
        ]
    else:
        cands += ["/usr/bin/code", "/usr/local/bin/code",
                  "/Applications/Visual Studio Code.app/Contents/Resources/app/bin/code"]
    for c in cands:
        if c and os.path.exists(c): return c
    return None

def _code_extension_root():
    home = Path.home()
    for cand in [home / ".vscode" / "extensions",
                 home / ".vscode-insiders" / "extensions",
                 home / ".cursor" / "extensions",
                 home / ".windsurf" / "extensions"]:
        parent = cand.parent
        if parent.exists():
            return cand
    return home / ".vscode" / "extensions"

def _detect_host():
    tp = os.environ.get("TERM_PROGRAM", "").lower()
    if "vscode" in tp: return "vscode-terminal"
    if "cursor" in tp: return "cursor-terminal"
    if "windsurf" in tp: return "windsurf-terminal"
    if os.environ.get("VSCODE_PID"): return "vscode-terminal"
    if os.environ.get("CURSOR_TRACE_ID"): return "cursor-terminal"
    if os.environ.get("TERM_PROGRAM") or os.environ.get("WT_SESSION"):
        return "generic-terminal"
    return "standalone"

def _install_ide_extension():
    ext_root = _code_extension_root()
    target = ext_root / "rnalimov.dfreecode-ide-1.0.0"
    try:
        target.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        return None, f"cannot create extension dir {target}: {e}"
    try:
        (target / "package.json").write_text(IDE_EXT_PACKAGE_JSON, encoding="utf-8")
        (target / "extension.js").write_text(IDE_EXT_EXTENSION_JS, encoding="utf-8")
    except Exception as e:
        return None, f"cannot write extension files: {e}"
    return target, None

def _uninstall_ide_extension():
    ext_root = _code_extension_root()
    target = ext_root / "rnalimov.dfreecode-ide-1.0.0"
    removed = []
    if target.exists():
        try: shutil.rmtree(target); removed.append(str(target))
        except Exception as e: print_warn(f"could not remove {target}: {e}")
    legacy = ext_root / "dfreecode-ide-1.0.0"
    if legacy.exists():
        try: shutil.rmtree(legacy); removed.append(str(legacy))
        except Exception: pass
    for f in (IDE_STATE_FILE, IDE_CMD_FILE, IDE_LOG_FILE):
        if f.exists():
            try: f.unlink(); removed.append(str(f))
            except Exception: pass
    return removed

def _send_ide_cmd(cmd):
    try:
        with open(IDE_CMD_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(cmd, ensure_ascii=False) + "\n")
        return True
    except Exception as e:
        print_warn(f"ide cmd write failed: {e}")
        return False

def _pid_alive(pid):
    if not pid: return False
    try: pid = int(pid)
    except Exception: return False
    try:
        if platform.system() == "Windows":
            r = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/NH", "/FO", "CSV"],
                capture_output=True, timeout=3,
                encoding="utf-8", errors="replace",
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            out = r.stdout or ""
            return f'"{pid}"' in out
        else:
            os.kill(pid, 0); return True
    except ProcessLookupError: return False
    except PermissionError: return True
    except Exception: return True

def _read_ide_state(max_age_sec=15, check_pid=True):
    try:
        if not IDE_STATE_FILE.exists(): return None
        st = IDE_STATE_FILE.stat()
        if max_age_sec and (time.time() - st.st_mtime) > max_age_sec: return None
        with open(IDE_STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if check_pid and data.get("pid"):
            if not _pid_alive(data["pid"]):
                return None
        return data
    except Exception:
        return None

def _notify_ide(text): _send_ide_cmd({"cmd": "notify", "text": text})

def _open_in_ide(path, line=None):
    c = {"cmd": "open", "file": str(path)}
    if line is not None: c["line"] = int(line)
    _send_ide_cmd(c)

def _ide_weld():
    print_info(f"host: {_detect_host()}")
    ext_root = _code_extension_root()
    print_info(f"extensions dir: {ext_root}")
    target, err = _install_ide_extension()
    if err: return False, err
    print_ok(f"extension installed: {target}")
    code = _find_code_cli()
    if not code:
        print_warn("VS Code CLI not found — install VS Code, or open the extensions folder manually")
        print_info(f"after reloading VS Code, the extension will write state to:")
        print_info(f"  {IDE_STATE_FILE}")
        return False, "vscode CLI not found"
    cwd = os.getcwd()
    print_info(f"launching: {os.path.basename(code)} {cwd}")
    try: subprocess.Popen([code, cwd], shell=False)
    except Exception:
        try: subprocess.Popen(f'"{code}" "{cwd}"', shell=True)
        except Exception as e: return False, f"failed to launch: {e}"
    print_info("waiting for extension to become active (up to 60s)...")
    print_info("if VS Code was already open: Ctrl+Shift+P → Developer: Reload Window")
    t0 = time.time(); last = 0
    while time.time() - t0 < 60:
        st = _read_ide_state(max_age_sec=60)
        if st and st.get("pid"):
            print_ok(f"welded: vscode {st.get('vscode','?')} pid {st.get('pid')} boot {st.get('bootId','?')}")
            print_ok(f"workspace: {st.get('workspace') or '(none)'}")
            return True, "ok"
        el = int(time.time() - t0)
        if el // 5 != last:
            last = el // 5
            sys.stdout.write(f"\r  {FAINT}·{RESET} {DIM}...waiting ({el}s){RESET}    "); sys.stdout.flush()
        time.sleep(1)
    sys.stdout.write("\r" + " "*70 + "\r"); sys.stdout.flush()
    return False, "extension did not activate within 60s"

def _ide_status_line():
    st = _read_ide_state(max_age_sec=30)
    if not st: return "IDE: not connected"
    parts = []
    if st.get("workspace"): parts.append(f"ws={os.path.basename(st['workspace'])}")
    if st.get("activeFile"): parts.append(f"file={os.path.basename(st['activeFile'])}")
    if st.get("lineCount"): parts.append(f"{st['lineCount']}L")
    sel = st.get("selection") or {}
    if sel.get("text"):
        t = sel["text"].replace("\n", " ")[:40]
        parts.append(f"sel='{t}'")
    return "IDE: " + (", ".join(parts) if parts else "connected")

def _set_clipboard(text):
    try:
        import pyperclip; pyperclip.copy(text); return True
    except Exception: pass
    if platform.system() == "Windows":
        try:
            import ctypes
            CF_UNICODETEXT = 13; GMEM_MOVEABLE = 0x0002
            user32 = ctypes.windll.user32; kernel32 = ctypes.windll.kernel32
            if not user32.OpenClipboard(None): return False
            try:
                user32.EmptyClipboard()
                data = text.encode("utf-16-le") + b"\x00\x00"
                h = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data))
                if not h: return False
                p = kernel32.GlobalLock(h)
                if not p: return False
                ctypes.memmove(p, data, len(data)); kernel32.GlobalUnlock(h)
                if not user32.SetClipboardData(CF_UNICODETEXT, h): return False
            finally: user32.CloseClipboard()
            return True
        except Exception: return False
    return False

DEFAULT_WASM_URL="https://fe-static.deepseek.com/chat/static/sha3_wasm_bg.7b9ca65ddd.wasm"
class DeepSeekPow:
    def __init__(self,wasm_url=None):
        if not WASMTIME_OK: raise RuntimeError("wasmtime not installed")
        self.wasm_url=wasm_url or CONFIG.get("wasm_url") or DEFAULT_WASM_URL
        self._engine=wasmtime.Engine(); self._module=None; self._lock=threading.Lock()
    def _load_module(self):
        if self._module is not None: return self._module
        with self._lock:
            if self._module is not None: return self._module
            wasm_path = WASM_CACHE_DIR / "sha3_wasm.wasm"
            if not wasm_path.exists():
                print_info(f"Downloading PoW WASM → {wasm_path}")
                req=urllib.request.Request(self.wasm_url,headers={"User-Agent":CONFIG["user_agent"]})
                with urllib.request.urlopen(req,timeout=60) as r: data=r.read()
                try: wasm_path.write_bytes(data)
                except Exception: pass
                print_ok(f"PoW WASM saved ({len(data)} bytes)"); wasm=data
            else: wasm=wasm_path.read_bytes()
            self._module=wasmtime.Module(self._engine,wasm); return self._module
    def make_header(self,ch):
        if isinstance(ch,str): ch=json.loads(ch)
        module=self._load_module(); store=wasmtime.Store(self._engine)
        try: inst=wasmtime.Instance(store,module,[])
        except Exception as e:
            try:
                linker=wasmtime.Linker(self._engine)
                try: linker.define_wasi()
                except Exception: pass
                inst=linker.instantiate(store,module)
            except Exception as e2: raise RuntimeError(f"Cannot instantiate WASM: {e} / {e2}")
        ex=inst.exports(store)
        mem,alloc,stack_fn,solve=ex["memory"],ex["__wbindgen_export_0"],ex["__wbindgen_add_to_stack_pointer"],ex["wasm_solve"]
        salt,exp,chhex,diff=ch["salt"],ch["expire_at"],ch["challenge"],ch["difficulty"]
        c_b=chhex.encode(); p_b=f"{salt}_{exp}_".encode()
        cP=alloc(store,len(c_b),1); pP=alloc(store,len(p_b),1)
        mem.write(store,c_b,cP); mem.write(store,p_b,pP)
        sp=stack_fn(store,-16)
        solve(store,sp,cP,len(c_b),pP,len(p_b),float(diff))
        raw=bytes(mem.read(store,sp,sp+16)); stack_fn(store,16)
        code=struct.unpack("<i",raw[0:4])[0]; answer=struct.unpack("<d",raw[8:16])[0]
        if code==0 or not (answer>0): raise RuntimeError(f"PoW failed: code={code}, answer={answer}")
        n=int(answer); print_ok(f"PoW solved: nonce={n}")
        return base64.b64encode(json.dumps({"algorithm":ch.get("algorithm","DeepSeekHashV1"),
            "challenge":chhex,"salt":salt,"answer":n,"signature":ch.get("signature",""),
            "target_path":ch.get("target_path","/api/v0/chat/completion")},
            separators=(",",":")).encode()).decode()

def find_chrome():
    for c in [r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expanduser(r"~\AppData\Local\Google\Chrome\Application\chrome.exe"),
        "/usr/bin/google-chrome","/usr/bin/chromium",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"]:
        if os.path.exists(c): return c
    return None
def _connect(u):
    try: return websocket.create_connection(u,timeout=5,origin="http://localhost")
    except Exception:
        try: return websocket.create_connection(u,timeout=5)
        except Exception: return None
def cdp_eval(ws, expr, timeout=5, await_promise=False):
    try:
        mid = random.randint(1000, 999999)
        params = {"expression": expr, "returnByValue": True}
        if await_promise: params["awaitPromise"] = True
        ws.send(json.dumps({"id": mid, "method": "Runtime.evaluate", "params": params}))
        dl = time.time() + timeout
        while time.time() < dl:
            r = json.loads(ws.recv())
            if r.get("id") == mid:
                if "error" in r: return None
                result = r.get("result", {}).get("result", {})
                if result.get("subtype") == "error": return None
                return result.get("value")
    except Exception: return None
    return None

def _get_login_state(ws):
    js = r"""
    (function(){
      var out = {url: location.href, token: '', source: ''};
      try { var t = localStorage.getItem('userToken') || '';
        if (t) { out.token = t; out.source = 'localStorage'; } } catch(e){}
      if (!out.token) {
        try { var t2 = sessionStorage.getItem('userToken') || '';
          if (t2) { out.token = t2; out.source = 'sessionStorage'; } } catch(e){}
      }
      return out;
    })()
    """
    return cdp_eval(ws, js, timeout=6, await_promise=False)

def _user_info_valid(s):
    if not s or not isinstance(s, str): return False
    s = s.strip()
    if s in ("", "null", "{}", "undefined", "[]", "false"): return False
    try: j = json.loads(s)
    except Exception: return False
    if not isinstance(j, dict): return False
    for k in ("id", "user_id", "userId", "uid"):
        v = j.get(k)
        if v not in (None, "", 0, "0", "null"): return True
    if j.get("email") and (j.get("name") or j.get("username") or j.get("nickname")):
        return True
    return False

def _validate_token_remotely(token, timeout=8):
    if not token or not _looks_like_real_token(token):
        return False, "malformed"
    try:
        r = requests.post(
            "https://chat.deepseek.com/api/v0/chat_session/create",
            headers={"Authorization": f"Bearer {token}", "accept": "*/*",
                "user-agent": CONFIG["user_agent"], "origin": "https://chat.deepseek.com",
                "referer": "https://chat.deepseek.com/"},
            json={}, timeout=timeout)
        if r.status_code in (401, 403): return False, f"HTTP {r.status_code}"
        if r.status_code >= 500: return False, f"HTTP {r.status_code}"
        try: j = r.json()
        except Exception: return False, f"HTTP {r.status_code} non-JSON"
        code = j.get("code", 0)
        if code != 0: return False, f"code={code}"
        return True, (j.get("data") or {}).get("biz_data") or "ok"
    except requests.exceptions.Timeout: return False, "timeout"
    except Exception as e: return False, f"{type(e).__name__}"

def launch_chrome_for_registration():
    chrome=find_chrome()
    if not chrome: print_error("Chrome not found."); return None,None
    ts=datetime.now().strftime("%Y%m%d_%H%M%S")
    pd=os.path.join(tempfile.gettempdir(),f"ds_assistant_{ts}"); os.makedirs(pd,exist_ok=True)
    print_info("Launching Chrome with a clean temporary profile..."); print_info(f"Profile: {pd}")
    proc=subprocess.Popen([chrome,f"--user-data-dir={pd}",f"--remote-debugging-port={CONFIG['cdp_port']}",
        "--remote-allow-origins=*","--no-first-run","--disable-blink-features=AutomationControlled",
        "--incognito","https://chat.deepseek.com"])
    CONFIG["_tmp_profile"]=pd; tid=None; t0=time.time()
    while time.time()-t0<20:
        try:
            tabs=requests.get(f"http://127.0.0.1:{CONFIG['cdp_port']}/json",timeout=2).json()
            t_=next((t for t in tabs if "deepseek.com" in (t.get("url") or "").lower()),None)
            if t_: tid=t_.get("id"); break
        except Exception: pass
        time.sleep(0.5)
    return proc,tid

def fetch_token_via_cdp(timeout=900, target_id=None):
    if not WEBSOCKET_OK:
        print_error("pip install websocket-client"); return None, None
    port = CONFIG["cdp_port"]; start = time.time()
    last_token = ""; last_check = 0.0
    print_info("Please sign in to your account in the Chrome window.")
    print_info("  Tip: QR / phone / email — whichever the page offers.")
    print_info("  Do NOT close the window. userToken is captured automatically.")
    while time.time() - start < timeout:
        try: tabs = requests.get(f"http://127.0.0.1:{port}/json", timeout=2).json()
        except Exception: time.sleep(1); continue
        ds = next((t for t in tabs if "chat.deepseek.com" in (t.get("url") or "")), None)
        if not ds: time.sleep(1.5); continue
        wsu = ds.get("webSocketDebuggerUrl")
        if not wsu: time.sleep(1); continue
        ws = _connect(wsu)
        if not ws: time.sleep(2); continue
        try: st = _get_login_state(ws)
        finally:
            try: ws.close()
            except Exception: pass
        now = time.time()
        tok = normalize_token((st or {}).get("token") or "")
        if _looks_like_real_token(tok):
            must_check = (tok != last_token) or ((now - last_check) >= 3.0)
            if must_check:
                last_token = tok; last_check = now
                ok, info = _validate_token_remotely(tok, timeout=6)
                if ok:
                    print_ok(f"userToken accepted: {tok[:40]}... (len={len(tok)})")
                    return tok, st
                elapsed = int(now - start)
                if elapsed // 10 != (elapsed - 1) // 10:
                    print_info(f"  token present but rejected: {info}")
        elapsed = int(now - start)
        if elapsed // 15 != (elapsed - 1) // 15:
            if not last_token: print_info(f"  waiting for userToken... ({elapsed}s)")
        time.sleep(1.0)
    print_error("Timeout — no accepted userToken.")
    return None, None

def load_token_from_file():
    if not os.path.exists(TOKEN_FILE): return False
    try:
        with open(TOKEN_FILE,"r",encoding="utf-8") as f:
            lines=[l.strip() for l in f.read().lstrip("\ufeff").split("\n") if l.strip()]
        if not lines: return False
        tok=normalize_token(lines[0])
        if not _looks_like_real_token(tok): return False
        CONFIG["token"]=tok
        if len(lines)>1: CONFIG["session_id"]=normalize_token(lines[1])
        return True
    except Exception: return False
def save_token_to_file():
    with open(TOKEN_FILE,"w",encoding="utf-8") as f:
        f.write(CONFIG["token"]+"\n")
        if CONFIG["session_id"]: f.write(CONFIG["session_id"]+"\n")
    print_ok(f"Saved to {TOKEN_FILE}")
def delete_token_file():
    if os.path.exists(TOKEN_FILE): os.remove(TOKEN_FILE); print_ok("Token deleted.")
def paste_token_manually():
    print_info("chat.deepseek.com → F12 → Application → Local Storage → userToken")
    raw=input("  userToken: ").strip()
    tok=normalize_token(raw)
    if not _looks_like_real_token(tok): print_error("Invalid token"); return False
    CONFIG["token"]=tok; save_token_to_file(); return True

class DeepSeekAuthError(Exception): pass
class DeepSeekClient:
    BASE="https://chat.deepseek.com"
    def __init__(self,token,session_id=""):
        self.token=normalize_token(token); self.session_id=session_id
        self.pow=DeepSeekPow(); self.http=requests.Session(); self._lock=threading.Lock()
        self.http.headers.update({
            "accept":"*/*","accept-language":"en-US,en;q=0.9",
            "authorization":f"Bearer {self.token}","cache-control":"no-cache",
            "content-type":"application/json","origin":self.BASE,"pragma":"no-cache",
            "referer":f"{self.BASE}/",'sec-ch-ua':'"Chromium";v="131", "Not_A Brand";v="24"',
            "sec-ch-ua-mobile":"?0",'sec-ch-ua-platform':'"Windows"',
            "sec-fetch-dest":"empty","sec-fetch-mode":"cors","sec-fetch-site":"same-origin",
            "user-agent":CONFIG["user_agent"],"x-app-version":"2.0.0","x-client-version":"2.0.0",
            "x-client-platform":"web","x-client-locale":"ru","x-client-timezone-offset":"14400",
            "x-client-bundle-id":"com.deepseek.chat","x-hif-dliq":"","x-hif-leim":""})
        if session_id: self.http.cookies.set("ds_session_id",session_id,domain="chat.deepseek.com")
    def _dump(self,r,l):
        if not CONFIG.get("verbose_http",False): return
        b=r.text or ""; print_debug(f"{l}: HTTP {r.status_code}, len={len(b)}"); print_debug(f"  {b[:400]}")
    def _check(self,r,l):
        if r.status_code in (401,403): self._dump(r,l); raise DeepSeekAuthError(f"HTTP {r.status_code}")
        if r.status_code>=500: self._dump(r,l); raise RuntimeError(f"{l}: HTTP {r.status_code}")
        try: j=r.json()
        except Exception:
            self._dump(r,l); raise DeepSeekAuthError(f"{l}: non-JSON HTTP {r.status_code}")
        self._dump(r,l)
        if j.get("code",0)!=0:
            code=j.get("code"); msg=j.get("msg","")
            if code in (40001,40002,40003,40100,40101,40102) or any(k in str(msg).lower() for k in ("token","auth","login")):
                raise DeepSeekAuthError(f"{l}: code={code} msg={msg}")
            raise RuntimeError(f"{l}: code={code} msg={msg}")
        return j["data"]
    def verify_token(self):
        try: sid=self.create_chat_session(); return True,"ok",sid
        except DeepSeekAuthError as e: return False,str(e),None
        except Exception as e: return False,f"unknown: {e}",None
    def create_chat_session(self):
        with self._lock:
            r=self.http.post(f"{self.BASE}/api/v0/chat_session/create",json={},timeout=20)
            d=self._check(r,"create_chat_session")
        biz=d.get("biz_data") or {}
        sid=(biz.get("chat_session") or {}).get("id") or biz.get("id")
        if not sid: raise RuntimeError(f"no session id in biz_data: {biz}")
        return sid
    def create_pow_challenge(self,target="/api/v0/chat/completion"):
        with self._lock:
            r=self.http.post(f"{self.BASE}/api/v0/chat/create_pow_challenge",json={"target_path":target},timeout=20)
            d=self._check(r,"create_pow_challenge")
        biz=d.get("biz_data") if isinstance(d,dict) else None
        if not isinstance(biz,dict) or "challenge" not in biz:
            raise RuntimeError(f"no PoW challenge for target_path={target} (biz_data={biz!r})")
        return biz["challenge"]
    def _hdrs(self): return {k:v for k,v in self.http.headers.items() if k.lower() not in ("content-type","content-length")}
    def _fid(self,j):
        if not isinstance(j,dict) or j.get("code",0)!=0: return None
        d=j.get("data") or {}
        if not isinstance(d,dict): return None
        b=d.get("biz_data") if isinstance(d.get("biz_data"),dict) else {}
        fo=d.get("file") if isinstance(d.get("file"),dict) else {}
        for c in (d.get("id"),b.get("id"),b.get("file_id"),fo.get("id"),d.get("file_id")):
            if c and isinstance(c,str): return c
        return None
    def _fst(self,j):
        if not isinstance(j,dict) or j.get("code",0)!=0: return None
        d=j.get("data") or {}
        if not isinstance(d,dict): return None
        b=d.get("biz_data") if isinstance(d.get("biz_data"),dict) else {}
        for o in (b,d):
            st=o.get("status") if isinstance(o,dict) else None
            if st: return st
        for k in ("files","file_list"):
            arr=d.get(k) or b.get(k)
            if isinstance(arr,list) and arr:
                f=arr[0]
                if isinstance(f,dict):
                    st=f.get("status") or f.get("file_status")
                    if st: return st
        return None
    def wait_for_file_ready(self,fid,timeout=None):
        timeout=timeout or CONFIG.get("file_poll_timeout",120)
        start=time.time(); last=None; delay=0.6
        NOT_READY={"PENDING","PARSING","PROCESSING","IN_PROGRESS","UPLOADING"}
        FAILED={"FAILED","ERROR","REJECTED"}
        while time.time()-start<timeout:
            try:
                with self._lock:
                    r=self.http.get(f"{self.BASE}/api/v0/file/fetch_files",params={"file_ids":fid},timeout=10)
                if r.status_code>=400: return False,f"HTTP {r.status_code}"
                try: j=r.json()
                except Exception: return False,"non-JSON"
                st=self._fst(j)
                if st:
                    up=st.upper(); last=st
                    if up in FAILED: return False,st
                    if up not in NOT_READY: return True,st
                if CONFIG.get("verbose_http",False): print_debug(f"file {fid}: status={st}")
                else:
                    sys.stdout.write(f"\r  {FAINT}·{RESET} {DIM}file status: {st} ({int(time.time()-start)}s){RESET}    ")
                    sys.stdout.flush()
            except Exception as e:
                if CONFIG.get("verbose_http",False): print_debug(f"file poll error: {e}")
            time.sleep(delay); delay=min(delay*1.5,3.0)
        sys.stdout.write("\r"+" "*60+"\r"); sys.stdout.flush()
        return False,last or "timeout"
    def upload_file(self,path,mime="image/png"):
        if not os.path.exists(path): return None,f"file not found: {path}"
        base=self._hdrs(); fname=os.path.basename(path)
        try:
            ch=self.create_pow_challenge("/api/v0/file/upload_file")
            pow_b64=self.pow.make_header(ch)
        except Exception as e: return None,f"upload PoW challenge failed: {e}"
        try:
            with open(path,"rb") as fh:
                files={"file":(fname,fh,mime)}
                r=requests.post(f"{self.BASE}/api/v0/file/upload_file",
                    headers={**base,"x-ds-pow-response":pow_b64},files=files,timeout=90)
        except Exception as e: return None,f"upload request error: {e}"
        print_info(f"upload_file: HTTP {r.status_code}, {len(r.text or '')} bytes")
        if r.status_code>=400:
            print_info(f"  {r.text[:300]}"); return None,f"upload HTTP {r.status_code}: {r.text[:200]}"
        try: j=r.json()
        except Exception: return None,f"upload non-JSON (HTTP {r.status_code}): {r.text[:200]}"
        fid=self._fid(j)
        if not fid: return None,f"upload: no file_id in response: {json.dumps(j,ensure_ascii=False)[:300]}"
        print_ok(f"upload_file → file_id={fid} (status={self._fst(j) or 'unknown'})")
        print_info(f"waiting for file parsing (up to {CONFIG.get('file_poll_timeout',120)}s)...")
        ready,last=self.wait_for_file_ready(fid)
        sys.stdout.write("\r"+" "*60+"\r"); sys.stdout.flush()
        if not ready:
            print_error(f"file never became ready (last status={last})")
            return None,f"file parsing did not complete (status={last})"
        print_ok(f"file ready (status={last})")
        try:
            fr=requests.post(f"{self.BASE}/api/v0/file/fork_file_task",headers=base,
                json={"file_id":fid,"to_model_type":"vision"},timeout=60)
            if fr.status_code in (200,201):
                try:
                    fj=fr.json()
                    if isinstance(fj,dict) and fj.get("code",0)==0:
                        nid=self._fid(fj)
                        if nid and nid!=fid: fid=nid
                except Exception: pass
        except Exception: pass
        return fid,None
    def completion(self,prompt,chat_session_id,parent_message_id=None,ref_file_ids=None):
        CONFIG["_cancel"]=False
        print_info("Requesting PoW challenge...")
        ch=self.create_pow_challenge(); ph=self.pow.make_header(ch)
        body={"chat_session_id":chat_session_id,"parent_message_id":parent_message_id,
            "prompt":prompt,"ref_file_ids":ref_file_ids or [],
            "thinking_enabled":CONFIG["thinking"],"search_enabled":CONFIG["search"],
            "action":None,"preempt":False,"model_type":current_model_type()}
        if ref_file_ids: print_info(f"(attaching {len(ref_file_ids)} file(s): {ref_file_ids})")
        print_info(f"Sending prompt ({len(prompt)} chars, model={current_model_name()}, "
                   f"thinking={'on' if CONFIG['thinking'] else 'off'})...")
        _read_to = max(30, min(int(CONFIG["timeout"]),
                               int(CONFIG["sse_silence_timeout"]) + 15))
        with self._lock:
            r=self.http.post(f"{self.BASE}/api/v0/chat/completion",json=body,
                headers={"x-ds-pow-response":ph,"connection":"close"},stream=True,
                timeout=(10,_read_to))
        if r.status_code in (401,403):
            try: r.close()
            except Exception: pass
            raise DeepSeekAuthError(f"HTTP {r.status_code} on completion")
        if r.status_code>=400:
            print_error(f"HTTP {r.status_code}: {r.text[:300]}")
            try: r.close()
            except Exception: pass
            return "","",None

        anim = ThinkingAnimator(label="Thinking"); anim.start()
        frags=[]; direct=[]; mid=None; fin=None; last=time.time()
        dbgc=[0]; total=[0]; path=[None]; ended=[None]; raw_first=[]; first_seen=[False]

        def addf(v):
            for f in (v if isinstance(v,list) else [v]):
                if isinstance(f,dict): frags.append(dict(f))
        def foc(fid,ft="RESPONSE"):
            for f in frags:
                if f.get("id")==fid: return f
            n={"id":fid,"type":ft,"content":""}; frags.append(n); return n
        def _update_token_count():
            chars = sum(len(f.get("content","") or "") for f in frags)
            chars += sum(len(x) for x in direct)
            anim.set_tokens(chars // 3)

        try:
            for line in r.iter_lines(decode_unicode=True):
                if CONFIG.get("_cancel"):
                    CONFIG["_cancel"]=False; anim.stop(); print_warn("Request cancelled")
                    try: r.close()
                    except Exception: pass
                    return "","",None
                now=time.time()
                if now-last>CONFIG["sse_silence_timeout"]: ended[0]="silence_timeout"; break
                if not line: continue
                if len(raw_first)<8 and line.strip(): raw_first.append(line[:220])
                if line.startswith("event:"):
                    if line[6:].strip()=="close": ended[0]="event_close"; break
                    if CONFIG.get("verbose_http",False) and dbgc[0]<40:
                        print_debug(f"SSE: {line[:220]}"); dbgc[0]+=1
                    continue
                if line.startswith("{") and not line.startswith('{"v"'):
                    try:
                        e=json.loads(line)
                        if e.get("code",0)!=0:
                            print_error(f"Server error: code={e.get('code')} msg={e.get('msg')}")
                            ended[0]=f"server_error_{e.get('code')}"; break
                    except json.JSONDecodeError: pass
                if CONFIG.get("verbose_http",False) and dbgc[0]<40:
                    print_debug(f"SSE: {line[:220]}"); dbgc[0]+=1
                if not line.startswith("data:"): continue
                last=now; total[0]+=1
                if not first_seen[0]: first_seen[0]=True
                p=line[5:].strip()
                if not p: continue
                if p=="[DONE]": ended[0]="done"; break
                try: o=json.loads(p)
                except json.JSONDecodeError: continue
                if isinstance(o,dict) and o.get("code",0)!=0 and "v" not in o:
                    print_error(f"Server error: code={o.get('code')} msg={o.get('msg')}")
                    ended[0]=f"server_error_{o.get('code')}"; break
                tp=o.get("p")
                if tp is not None: path[0]=tp
                v=o.get("v")
                if isinstance(v,dict) and "response" in v:
                    resp=v["response"]
                    if not mid: mid=resp.get("message_id") or resp.get("id")
                    if isinstance(resp.get("fragments"),list) and resp["fragments"]:
                        frags.clear(); addf(resp["fragments"])
                    if resp.get("finish_reason") is not None: fin=resp["finish_reason"]
                if path[0]=="response" and isinstance(v,list):
                    for op in v:
                        if isinstance(op,dict) and op.get("p")=="fragments" and op.get("o")=="APPEND":
                            addf(op.get("v"))
                if path[0]=="response/fragments" and v is not None: addf(v)
                if path[0]=="response/content" and isinstance(v,str): direct.append(v)
                if path[0]=="response/status":
                    if isinstance(v,str) and v.upper()=="FINISHED": ended[0]="status_finished"; break
                    if v is not None: fin=v
                if path[0]=="response/finish_reason" and v is not None: fin=v
                if path[0]=="response/fragments/-1/content" and isinstance(v,str):
                    if not frags: frags.append({"id":1,"type":"RESPONSE","content":""})
                    frags[-1]["content"]=(frags[-1].get("content") or "")+v
                if isinstance(path[0],str) and isinstance(v,str):
                    m=re.match(r"response/fragments/(-?\d+)/content$",path[0])
                    if m and m.group(1)!="-1":
                        try: fid=int(m.group(1))
                        except ValueError: fid=None
                        if fid is not None:
                            foc(fid,"RESPONSE")["content"]=foc(fid,"RESPONSE").get("content","")+v
                if o.get("response_message_id") is not None and not mid:
                    mid=o["response_message_id"]
                _update_token_count()
        except requests.exceptions.ReadTimeout:
            ended[0]="read_timeout_after_data" if first_seen[0] else "read_timeout_no_data"
            if not first_seen[0]: print_error("Read timeout before any data")
        except requests.exceptions.ChunkedEncodingError:
            ended[0]="chunked_encoding_error"
        except Exception as e:
            if CONFIG.get("_cancel"):
                CONFIG["_cancel"]=False; anim.stop(); print_warn("Request cancelled")
                try: r.close()
                except Exception: pass
                return "","",None
            print_error(f"stream: {e}"); ended[0]=f"exception: {e}"
        finally:
            try: r.close()
            except Exception: pass
            _update_token_count(); anim.stop()
            if ended[0] in ("silence_timeout","read_timeout_no_data",
                            "chunked_encoding_error","event_close"):
                print_warn(f"stream ended early: {ended[0]}")

        answer="".join(direct)
        if not answer:
            answer="".join(f.get("content","") for f in frags if f.get("type") in ("RESPONSE","SEARCH"))
        reasoning="".join(f.get("content","") for f in frags if f.get("type") in ("THINKING","THINK","REASONING"))
        print_info(f"Stream ended ({ended[0] or 'unknown'}): answer={len(answer)}, reasoning={len(reasoning)}, "
                   f"lines={total[0]}, finish={fin}")
        if not answer and ref_file_ids and total[0]==0:
            print_warn("Empty stream WITH ref_file_ids attached. Raw SSE (first lines):")
            for ln in raw_first: sys.stdout.write(f"    {FAINT}{ln}{RESET}\n")
            sys.stdout.flush()
        return reasoning.strip(),answer.strip(),mid

class AgentContext:
    def __init__(self,sid): self.chat_session_id=sid; self.parent_message_id=None; self.message_count=0

class DeepSeekAssistant:
    def __init__(self):
        self.client=None; self.agent_contexts={}; self.current_agent="main"
        self.chat_history=[]; self.last_response_clean=""; self.active_task=None
        self.user_message_count=0; self.init_ok=False; self.init_error_msg=""
        self.loop_thread=None; self.pending_files=[]
        self._recent_failed_cmds = []
        self.init_client()
    def init_client(self):
        tok = CONFIG.get("token","")
        if not tok:
            self.init_error_msg = "no token — use option 2 (Chrome sign-in) or 3 (paste)"
            return False
        if not _looks_like_real_token(tok):
            self.init_error_msg = ("userToken MALFORMED — not JWT-like, contains spaces, "
                                   "or too short. Re-copy it from chat.deepseek.com → F12 → "
                                   "Application → Local Storage → userToken")
            return False
        if not WASMTIME_OK:
            self.init_error_msg = "wasmtime not installed — restart the script"
            return False
        try:
            self.client = DeepSeekClient(tok, CONFIG.get("session_id",""))
            sid = self.client.create_chat_session()
            self.agent_contexts["main"] = AgentContext(sid)
            print_ok(f"Main chat session: {sid[:8]}...")
            self.init_ok = True
            return True
        except DeepSeekAuthError as e:
            self.init_error_msg = (f"userToken REJECTED by server (expired or logged out): {e}. "
                                   f"Refresh via /token or re-run option 2/3.")
            return False
        except Exception as e:
            self.init_error_msg = f"init failed: {e}"
            return False
    def _ensure_agent(self,name):
        if name not in self.agent_contexts:
            sid=self.client.create_chat_session(); self.agent_contexts[name]=AgentContext(sid)
            print_info(f"created session [{name}]: {sid[:8]}...")
        return self.agent_contexts[name]
    def _switch_agent(self,name): self.current_agent=name; return self._ensure_agent(name)

    # ─── SHELL: fire-and-forget + forbidden-wait + PS5.1 && auto-route ────
    def execute_bash(self,cmd):
        r = _forbidden_reason(cmd)
        if r: return f"Error: {r}"
        fire_and_forget = bool(re.match(r'^\s*start(?:\s|$)', cmd or "",
                                        re.IGNORECASE))
        return _run_capture(
            cmd,
            timeout=15 if fire_and_forget else int(CONFIG.get("long_cmd_timeout", 300)),
            shell=True, fire_and_forget=fire_and_forget,
        )

    def execute_powershell(self,cmd):
        r = _forbidden_reason(cmd)
        if r: return f"Error: {r}"
        # Windows PowerShell 5.1 doesn't support && / || — ParserError.
        # If the model wrote cmd-style chaining, route to cmd.exe.
        if re.search(r'&&|\|\|', cmd or ""):
            print_warn("POWERSHELL cmd contains `&&` / `||` — routing to BASH (cmd.exe)")
            return self.execute_bash(cmd)
        fire_and_forget = bool(re.search(r'(?<!\S)Start-Process(?!\S)', cmd or "",
                                         re.IGNORECASE))
        args = ["powershell","-NoProfile","-NonInteractive",
                "-ExecutionPolicy","Bypass","-Command",cmd]
        return _run_capture(
            args,
            timeout=15 if fire_and_forget else int(CONFIG.get("long_cmd_timeout", 300)),
            shell=False, fire_and_forget=fire_and_forget,
        )

    def read_file(self,path,max_lines=None):
        max_lines=max_lines or CONFIG.get("read_max_lines",500)
        s=e_=None
        m=re.match(r'^(.*?):(\d+)(?:-(\d+))?$',path)
        if m and os.path.exists(m.group(1)):
            path=m.group(1); s=int(m.group(2)); e_=int(m.group(3)) if m.group(3) else None
        try:
            with open(path,'r',encoding='utf-8',errors='replace') as f: lines=f.readlines()
        except FileNotFoundError: return f"File not found: {path}"
        except PermissionError: return f"Permission denied: {path}"
        except Exception as e: return f"Error: {e}"
        total=len(lines)
        if total==0: return f"--- {path} (empty) ---"
        w=max(3,len(str(total))); out=[]
        if s is not None:
            a=max(1,s); b=min(total,e_ if e_ is not None else a+max_lines-1)
            if b-a+1>max_lines: b=a+max_lines-1
            out.append(f"--- {path} (lines {a}-{b} of {total}) ---")
            for i in range(a-1,b): out.append(f"{i+1:>{w}}│ {lines[i].rstrip()}")
            out.append("--- end ---"); return "\n".join(out)
        out.append(f"--- {path} ({total} lines) ---")
        if total<=max_lines:
            for i,l in enumerate(lines,1): out.append(f"{i:>{w}}│ {l.rstrip()}")
        else:
            h=max_lines//2
            for i in range(h): out.append(f"{i+1:>{w}}│ {lines[i].rstrip()}")
            out.append(f"{'':>{w}}│ ... ({total-max_lines} skipped) ...")
            for i in range(total-h,total): out.append(f"{i+1:>{w}}│ {lines[i].rstrip()}")
        out.append("--- end ---"); return "\n".join(out)
    def write_file(self,path,content):
        try:
            d=os.path.dirname(path)
            if d: os.makedirs(d,exist_ok=True)
            with open(path,'w',encoding='utf-8') as f: f.write(content)
            if CONFIG.get("ide_welded"):
                try: _open_in_ide(path)
                except Exception: pass
            return f"File saved: {path}"
        except Exception as e: return f"Error: {e}"
    def list_files(self,path='.'):
        try:
            files=sorted(os.listdir(path)); out=[]
            for f in files:
                full=os.path.join(path,f)
                out.append(f"{f}/" if os.path.isdir(full) else f"{f} ({os.path.getsize(full)}b)")
            return "\n".join(out) if out else "Folder is empty"
        except Exception as e: return f"Error: {e}"

    def grep(self,pat,path='.'):
        try:
            res=[]; deadline=time.time()+20.0
            try: rx=re.compile(pat)
            except re.error: rx=None
            for root,dirs,files in os.walk(path):
                if time.time()>deadline:
                    res.append("(grep timed out after 20s — partial results)"); break
                dirs[:]=[d for d in dirs if d not in _ROOT_IGNORE]
                for fn in files:
                    if time.time()>deadline:
                        res.append("(grep timed out after 20s — partial results)"); break
                    fp=os.path.join(root,fn)
                    try:
                        with open(fp,'r',encoding='utf-8',errors='ignore') as fh:
                            for i,l in enumerate(fh,1):
                                if (rx and rx.search(l)) or (not rx and pat in l):
                                    res.append(f"{fp}:{i}: {l.rstrip()[:200]}")
                                    if len(res)>=30: return "\n".join(res)
                    except Exception: continue
            return "\n".join(res) if res else "No matches"
        except Exception as e: return f"Error: {e}"

    def find_files(self,name,path='.'):
        try:
            res=[]; nl=name.lower(); deadline=time.time()+20.0
            for root,dirs,files in os.walk(path):
                if time.time()>deadline:
                    res.append("(find timed out after 20s — partial results)"); break
                dirs[:]=[d for d in dirs if d not in _ROOT_IGNORE]
                for d in dirs:
                    if nl in d.lower():
                        res.append(os.path.join(root,d)+"/")
                        if len(res)>=30: return "\n".join(res)
                for fn in files:
                    if nl in fn.lower():
                        res.append(os.path.join(root,fn))
                        if len(res)>=30: return "\n".join(res)
            return "\n".join(res) if res else "No files"
        except Exception as e: return f"Error: {e}"

    def fetch_url(self,cmd):
        url=(cmd or "").strip()
        if not url: return "Error: FETCH requires a URL"
        if not url.startswith(("http://","https://")): url="https://"+url
        mb=CONFIG.get("fetch_max_bytes",500_000)
        try:
            hdrs={"User-Agent":CONFIG["user_agent"]}
            r=requests.get(url,headers=hdrs,timeout=20)
            ctype=r.headers.get("content-type","").lower(); text=r.text or ""
            parts=[f"=== FETCH {url} (HTTP {r.status_code}, {ctype}) ==="]
            hc=text[:mb//2]
            parts.append(f"=== HTML/TEXT ({len(text)} chars, showing {len(hc)}) ==="); parts.append(hc)
            total=len(hc)
            looks=("html" in ctype) or text.lstrip()[:200].lower().startswith(("<!doctype","<html"))
            if looks and total<mb:
                srcs=re.findall(r'<script[^>]+src=["\']([^"\']+)["\']',text,re.IGNORECASE)
                seen=set()
                for s in srcs:
                    if total>=mb: break
                    if s in seen: continue
                    seen.add(s); ju=urllib.parse.urljoin(url,s)
                    try:
                        rj=requests.get(ju,headers=hdrs,timeout=20)
                        jt=rj.text or ""; rem=mb-total; ch=jt[:rem]
                        parts.append(f"\n=== JS {ju} (HTTP {rj.status_code}, {len(jt)} chars, showing {len(ch)}) ===")
                        parts.append(ch); total+=len(ch)
                    except Exception as e: parts.append(f"\n=== JS {ju} — ERROR: {e} ===")
            parts.append(f"\n=== END (total shown: {total} bytes) ===")
            return "\n".join(parts)
        except Exception as e: return f"Error fetching {url}: {e}"

    def mouse_drag(self, cmd):
        s = (cmd or "").strip()
        if not s:
            return "Error: MOUSE drag needs two points: 'drag x1,y1 x2,y2'"
        s = re.sub(r'\s*(->|to)\s*', ' ', s, flags=re.IGNORECASE)
        nums = re.findall(r'-?\d+', s)
        if len(nums) < 4:
            return ("Error: MOUSE drag needs 4 integers (x1,y1,x2,y2). "
                    "Example: <<<MOUSE: drag 100,200 800,500>>>")
        try: x1, y1, x2, y2 = [int(n) for n in nums[:4]]
        except Exception as e: return f"Error parsing drag coords: {e}"
        if platform.system() != "Windows":
            return "Error: MOUSE is only supported on Windows in this build"
        if not PYAUTOGUI_OK: return "Error: pyautogui is not installed."
        try:
            sw, sh = pyautogui.size()
            PHI        = (1 + 5 ** 0.5) / 2
            min_dim    = max(1, min(sw, sh))
            speed_px_s = min_dim / PHI
            dist = ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5
            duration = max(0.15, min(2.5, dist / max(1.0, speed_px_s)))
            pyautogui.moveTo(x1, y1, duration=0.08); time.sleep(0.05)
            pyautogui.mouseDown(button="left"); time.sleep(0.05)
            pyautogui.moveTo(x2, y2, duration=duration); time.sleep(0.05)
            pyautogui.mouseUp(button="left")
            cx, cy = pyautogui.position()
            return (f"Dragged ({x1},{y1}) → ({x2},{y2}) end=({cx},{cy}) "
                    f"dist={int(dist)}px screen={sw}x{sh} speed={int(speed_px_s)}px/s "
                    f"duration={duration:.2f}s")
        except Exception as e:
            return f"Error dragging: {e}"

    def mouse_action(self,cmd):
        ps=(cmd or "").strip().split()
        if not ps: return "Error: MOUSE requires an action"
        if ps[0].lower() == "drag": return self.mouse_drag(" ".join(ps[1:]))
        if len(ps)<2: return "Error: MOUSE format: <click|move|rclick|dblclick|drag> ..."
        act=ps[0].lower(); co=ps[1].replace(" ","")
        if "," not in co: return "Error: MOUSE coords must be 'x,y' with actual numbers (e.g. 'click 120,340')"
        try: x,y=[int(v.strip()) for v in co.split(",")]
        except Exception: return ("Error: MOUSE coords must be integers. You likely wrote the literal string 'x,y'. "
            "Substitute real coordinates from the screenshot grid, e.g. 'click 120,340'.")
        if platform.system()!="Windows": return "Error: MOUSE is only supported on Windows in this build"
        if not PYAUTOGUI_OK: return "Error: pyautogui is not installed."
        try:
            pyautogui.moveTo(int(x), int(y), duration=0.15); time.sleep(0.08)
            cx,cy=pyautogui.position()
            if act=="move": return f"Mouse moved to ({cx},{cy}) target ({x},{y})"
            if act=="click":
                pyautogui.mouseDown(button="left"); time.sleep(0.06)
                pyautogui.mouseUp(button="left"); time.sleep(0.05)
                cx,cy=pyautogui.position(); return f"Mouse clicked at ({cx},{cy}) target ({x},{y})"
            if act=="rclick":
                pyautogui.mouseDown(button="right"); time.sleep(0.06)
                pyautogui.mouseUp(button="right"); time.sleep(0.05)
                cx,cy=pyautogui.position(); return f"Mouse right-clicked at ({cx},{cy}) target ({x},{y})"
            if act=="dblclick":
                pyautogui.doubleClick(button="left", interval=0.06)
                cx,cy=pyautogui.position(); return f"Mouse double-clicked at ({cx},{cy}) target ({x},{y})"
            return f"Error: unknown MOUSE action '{act}'"
        except Exception as e: return f"Error: {e}"

    def press_key(self, cmd):
        key = (cmd or "").strip().lower()
        if not key: return "Error: PRESS requires a key name (e.g. 'enter', 'tab', 'f5', 'ctrl+s')"
        if platform.system() != "Windows":
            return "Error: PRESS is only supported on Windows in this build"
        if not PYAUTOGUI_OK: return "Error: pyautogui is not installed."
        try:
            if "+" in key:
                parts = [p.strip() for p in key.split("+") if p.strip()]
                if not parts: return f"Error: bad key combo '{key}'"
                pyautogui.hotkey(*parts); return f"Pressed combo: {'+'.join(parts)}"
            pyautogui.press(key); return f"Pressed: {key}"
        except Exception as e:
            return f"Error pressing '{key}': {e}"

    def print_text(self, cmd):
        text = cmd or ""
        if not text.strip(): return "Error: PRINT requires text"
        if platform.system() != "Windows":
            return "Error: PRINT is only supported on Windows in this build"
        if not PYAUTOGUI_OK: return "Error: pyautogui is not installed."
        try:
            text = text.replace("\\n", "\n").replace("\\t", "\t")
            preview = text[:80] + ("…" if len(text) > 80 else "")
            has_non_ascii = any(ord(c) > 127 for c in text)
            if has_non_ascii:
                if not _set_clipboard(text):
                    return ("Error: cannot set clipboard for Unicode text. "
                            "Install pyperclip: pip install pyperclip")
                time.sleep(0.08); pyautogui.hotkey("ctrl", "v"); time.sleep(0.05)
                return f"Printed {len(text)} char(s) via clipboard: {preview!r}"
            pyautogui.write(text, interval=0.02)
            return f"Printed {len(text)} char(s) via keyboard: {preview!r}"
        except Exception as e:
            return f"Error printing: {e}"

    def ide_tool(self):
        if not CONFIG.get("ide_welded"):
            return "IDE not connected. Ask the user to run /ide."
        st = _read_ide_state(max_age_sec=60)
        if not st:
            return "IDE state file missing, stale, or process dead — VS Code may not be running."
        lines = ["[IDE]", f"host: {_detect_host()}"]
        if st.get("vscode"): lines.append(f"vscode: {st['vscode']}")
        if st.get("pid"): lines.append(f"pid: {st['pid']} (alive)")
        if st.get("bootId"): lines.append(f"boot: {st['bootId']}")
        if st.get("tick") is not None: lines.append(f"tick: {st['tick']}")
        if st.get("workspace"): lines.append(f"workspace: {st['workspace']}")
        if st.get("activeFile"):
            lines.append(f"active file: {st['activeFile']}")
            lines.append(f"language: {st.get('language','?')}, lines: {st.get('lineCount','?')}")
        sel = st.get("selection") or {}
        if sel.get("text"):
            s_line = sel.get("start",{}).get("line",0)+1
            e_line = sel.get("end",{}).get("line",0)+1
            t = sel["text"]
            if len(t) > 800: t = t[:800] + "…"
            lines.append(f"selection lines {s_line}–{e_line}:")
            lines.append(t)
        opens = st.get("openFiles") or []
        if opens:
            lines.append(f"open tabs ({len(opens)}):")
            for p in opens[:20]: lines.append(f"  {p}")
        return "\n".join(lines)

    def ocr_screen(self):
        if not PIL_OK: return "Error: Pillow is not installed."
        if not RAPIDOCR_OK:
            return ("Error: RapidOCR not available. "
                    "Run: pip install rapidocr-onnxruntime opencv-python numpy")
        engine = _get_rapidocr()
        if engine is None: return "Error: RapidOCR engine failed to initialise."
        try: img = ImageGrab.grab()
        except Exception as e: return f"Error capturing screen: {e}"
        cur_x = cur_y = None
        if PYAUTOGUI_OK:
            try:
                cur_x, cur_y = pyautogui.position()
                cur_x = int(cur_x); cur_y = int(cur_y)
            except Exception: cur_x = cur_y = None
        try:
            img_np = np.array(img); result, _ = engine(img_np)
        except Exception as e: return f"Error running RapidOCR: {e}"
        if not result:
            head = f"[OCR] {img.size[0]}x{img.size[1]} px — no visible text detected."
            if cur_x is not None: head += f"\n  cursor: x={cur_x} y={cur_y}"
            return head
        min_conf = float(CONFIG.get("ocr_min_conf", 30)) / 100.0
        out = [f"[OCR] {img.size[0]}x{img.size[1]} px — {len(result)} text line(s) [CHEAP — no image attached]"]
        if cur_x is not None: out.append(f"  cursor: x={cur_x} y={cur_y}")
        for item in result:
            try:
                box, text, score = item
                if float(score) < min_conf: continue
                xs = [p[0] for p in box]; ys = [p[1] for p in box]
                cx = int(sum(xs) / len(xs)); cy = int(sum(ys) / len(ys))
                w = int(max(xs) - min(xs)); h = int(max(ys) - min(ys))
                out.append(f"  x={cx:>5} y={cy:>5}  ({w}x{h})  \"{text[:200]}\"")
            except Exception: continue
        if len(out) <= 2:
            return "\n".join(out) + "\n  (no line above confidence threshold)"
        out.append("Coordinates are line CENTERS in screen pixels (origin top-left). "
                   "Use them DIRECTLY with <<<MOUSE: click x,y>>> — no image was attached.")
        return "\n".join(out)

    def take_screenshot(self,marker=None):
        if not PIL_OK: return "Error: Pillow is not installed."
        try: img=ImageGrab.grab()
        except Exception as e: return f"Error capturing screenshot: {e}"
        w,h=img.size; step=int(CONFIG.get("grid_step",50) or 50)
        rgba=img.convert("RGBA"); ov=Image.new("RGBA",rgba.size,(0,0,0,0)); od=ImageDraw.Draw(ov)
        for x in range(0,w+1,step): od.line([(x,0),(x,h)],fill=(255,0,0,80),width=1)
        for y in range(0,h+1,step): od.line([(0,y),(w,y)],fill=(255,0,0,80),width=1)
        img=Image.alpha_composite(rgba,ov).convert("RGB")
        draw=ImageDraw.Draw(img)
        try: font=ImageFont.load_default()
        except Exception: font=None
        def label(x0,y0,t,fill=(255,255,0),bg=(0,0,0)):
            if font is not None:
                try: b=draw.textbbox((0,0),t,font=font); lw,lh=b[2]-b[0],b[3]-b[1]
                except Exception: lw,lh=len(t)*6,11
            else: lw,lh=len(t)*6,11
            draw.rectangle([x0,y0,x0+lw+6,y0+lh+4],fill=bg)
            draw.text((x0+3,y0+2),t,fill=fill,font=font)
        for x in range(step,w,step): label(x+2,2,str(x))
        for y in range(step,h,step): label(2,y+2,str(y))
        label(2,2,"0,0"); label(w-60,2,f"W={w}"); label(2,h-20,f"H={h}")
        cursor_info = ""
        if PYAUTOGUI_OK:
            try:
                cur_x, cur_y = pyautogui.position()
                cur_x = int(cur_x); cur_y = int(cur_y)
                if 0 <= cur_x < w and 0 <= cur_y < h:
                    cl = 16
                    draw.line([(cur_x-cl, cur_y), (cur_x+cl, cur_y)], fill=(255,255,255), width=4)
                    draw.line([(cur_x, cur_y-cl), (cur_x, cur_y+cl)], fill=(255,255,255), width=4)
                    draw.line([(cur_x-cl, cur_y), (cur_x+cl, cur_y)], fill=(0,255,255), width=2)
                    draw.line([(cur_x, cur_y-cl), (cur_x, cur_y+cl)], fill=(0,255,255), width=2)
                    draw.ellipse([cur_x-3, cur_y-3, cur_x+3, cur_y+3], fill=(0,255,255), outline=(255,255,255))
                    label(cur_x+14, cur_y+14, f"cursor {cur_x},{cur_y}", fill=(0,0,0), bg=(0,255,255))
                    cursor_info = f"cursor at ({cur_x},{cur_y}) [drawn as cyan crosshair]"
                else:
                    cursor_info = f"cursor at ({cur_x},{cur_y}) [outside screen]"
            except Exception as e:
                cursor_info = f"cursor capture failed: {e}"
        marker_info=""
        if marker is not None:
            mx,my=marker
            mx=max(0,min(w-1,mx)); my=max(0,min(h-1,my))
            r=8
            draw.ellipse([mx-r,my-r,mx+r,my+r],fill=(255,0,0),outline=(255,255,255),width=2)
            draw.line([(mx-14,my),(mx+14,my)],fill=(255,255,255),width=2)
            draw.line([(mx,my-14),(mx,my+14)],fill=(255,255,255),width=2)
            label(mx+12,my+12,f"{mx},{my}",fill=(255,255,255),bg=(180,0,0))
            marker_info=f"marker at ({mx},{my})"
        ts=datetime.now().strftime("%Y%m%d_%H%M%S")
        out=os.path.join(DSFREEHACK_DIR,f"ds_screenshot_{ts}.png")
        try: img.save(out,"PNG",optimize=True)
        except Exception as e: return f"Error saving screenshot: {e}"
        fid=None; err=None
        try: fid,err=self.client.upload_file(out,mime="image/png")
        except Exception as e: err=str(e)
        info=[f"[SCREENSHOT — EXPENSIVE detailed view] {w}x{h} px, grid {step}x{step} px, saved to: {out}"]
        if cursor_info: info.append(cursor_info)
        if marker_info: info.append(marker_info)
        info.append(f"Coordinate system: origin (0,0) is top-left, x goes right, y goes down. "
                    f"Grid lines every {step}px (fine 50x50 grid); the yellow numbers label that grid line's coordinate.")
        if fid:
            self.pending_files.append(fid); info.append(f"uploaded file_id={fid}")
            info.append("The image WILL be attached to your NEXT message (in the same turn, do not wait).")
            if marker is not None:
                info.append(f"Red dot marks ({marker[0]},{marker[1]}). "
                            "If it did not land on the intended element — read [CLICK CORRECTION] "
                            "in your rules: compute dx,dy = target - last_click and apply the SAME delta. "
                            "You may do this up to 3 times in a row for the same target. Do not ask the user. "
                            "Only after the red dot is exactly on target, emit the MOUSE click with the SAME coordinates.")
        else:
            info.append(f"upload FAILED: {err}")
            info.append("IMPORTANT: You CANNOT see the screen. Do NOT guess coordinates.")
        return "\n".join(info)
    def edit_file(self,cmd):
        parts=cmd.split('|')
        if len(parts)<3: return "Error: path|old|new"
        p,o,n=parts[0].strip(),parts[1].strip(),parts[2].strip()
        if not os.path.exists(p): return f"Error: not found: {p}"
        try:
            with open(p,'r',encoding='utf-8') as f: c=f.read()
            if o not in c: return f"Error: '{o}' not found"
            with open(p,'w',encoding='utf-8') as f: f.write(c.replace(o,n,1))
            if CONFIG.get("ide_welded"):
                try: _open_in_ide(p)
                except Exception: pass
            return f"Updated: {p}"
        except Exception as e: return f"Error: {e}"
    def get_diff(self):
        out = _run_capture("git diff", timeout=10, shell=True, label="git diff")
        return out if out and not out.startswith("Error") else (out or "No changes")
    def git_commit(self,msg):
        return _run_capture(f'git commit -am "{msg}"', timeout=10, shell=True,
                            label=f"git commit -am {msg[:40]}")
    def confirm(self,t):
        try:
            with _print_lock:
                sys.stdout.write(f"  {ACCENT}?{RESET} {DIM}{t} (y/n): {RESET}"); sys.stdout.flush()
            return input().strip().lower()=='y'
        except Exception: return False
    def _in_cwd(self,p):
        try:
            c=os.path.abspath('.').lower().rstrip('\\/')+os.sep
            return os.path.abspath(p).lower().startswith(c)
        except Exception: return False
    def _fs_path(self,m,cmd):
        if m in ("READ:","LS:","FIND:","GREP:","FETCH:"): return cmd.strip() or "."
        if m=="WRITE:": return cmd.split("|",1)[0].strip()
        if m=="EDIT:": return cmd.split("|",1)[0].strip()
        return None
    def _confirm(self,m,cmd):
        name=m.rstrip(":").upper()
        if name in CONFIG["ai_whitelist"]: return False
        if name=="IDE": return False
        sec=CONFIG["security"]
        if sec=="auto": return False
        if m=="SCREENSHOT:": return True
        if m=="OCR:": return sec=="manual"
        if m=="PRESS:": return sec=="manual"
        if m=="PRINT:": return True
        if sec=="safe-auto":
            if m not in FS_MARKERS: return True
            p=self._fs_path(m,cmd)
            return False if p is None else not self._in_cwd(p)
        return True
    def _strip_mt(self,cmd):
        s=(cmd or "").rstrip(); low=s.lower()
        if low.endswith(" -mt"): return s[:-4].rstrip(), True
        if low=="-mt": return "", True
        return cmd, False
    def _extract_cmds(self,text):
        cmds=[]
        for mm in CMD_RE.findall(text or ""):
            m=mm.strip()
            cust=re.match(r'CUSTOM:\s*(\w+)\b(.*)$',m,re.IGNORECASE|re.DOTALL)
            if cust:
                name=cust.group(1).upper(); rest=cust.group(2).strip()
                if name in ("SCREENSHOT","PRESS","PRINT"):
                    rest,_had = self._strip_mt(rest)
                    cmds.append((f"{name}:",rest,False)); continue
                if name=="OCR":
                    cmds.append(("OCR:","",False)); continue
                continue
            mu = m.upper().strip()
            if mu == "IDE" or mu == "IDE:":
                cmds.append(("IDE:", "", False)); continue
            for mk in ['BASH:','POWERSHELL:','READ:','WRITE:','LS:','GREP:','FIND:','EDIT:','TASK:','FETCH:','MOUSE:']:
                if mu.startswith(mk):
                    arg=m[len(mk):].strip()
                    arg,had=self._strip_mt(arg)
                    if mk in SERIAL_MARKERS: had = False
                    cmds.append((mk,arg,had)); break
        return cmds
    def _repair_broken_cmds(self,text):
        if not text: return text
        def _fix(m):
            mk=m.group(1).upper(); arg=m.group(2).strip()
            return f"<<<{mk}: {arg}>>>"
        return BROKEN_CMD_RE.sub(_fix, text)
    def _strip_cmds(self,text):
        text=re.sub(r'<<<\s*CUSTOM:\s*(?:SCREENSHOT|OCR|AGENTS|PRESS|PRINT)\b[^>]*>>>','',text,flags=re.IGNORECASE|re.DOTALL)
        text=re.sub(r'<<<CUSTOM:\s*EDIT-IT\s*\[.*?\]\s*>>>','',text,flags=re.IGNORECASE|re.DOTALL)
        return re.sub(r'<<<\s*(BASH|POWERSHELL|READ|WRITE|LS|GREP|FIND|EDIT|TASK|FETCH|MOUSE|IDE)\s*:?.*?>>>','',text,flags=re.DOTALL).strip()

    def _print_text_chunk(self, text):
        txt = (text or "").strip()
        if not txt: return
        sys.stdout.write("\n")
        for l in txt.split("\n"): sys.stdout.write(f"  {FG}{l}{RESET}\n")
        sys.stdout.write("\n"); sys.stdout.flush()

    def _split_response(self, text):
        if not text: return []
        out = []; pos = 0; found_cmd = False
        for m in CMD_RE.finditer(text):
            raw_cmd = m.group(0)
            if not self._extract_cmds(raw_cmd): continue
            pre = text[pos:m.start()]
            if pre.strip(): out.append(("text", pre))
            out.append(("cmd", raw_cmd)); pos = m.end(); found_cmd = True
        tail = text[pos:]
        if tail.strip(): out.append(("text", tail))
        if not found_cmd:
            stripped = self._strip_cmds(text)
            return [("text", stripped)] if stripped.strip() else []
        return out

    def _print_interleaved(self, text, print_text=True):
        segments = self._split_response(text)
        any_cmd = any(k == "cmd" for k, _ in segments)
        pending = []; results_blocks = []
        def _flush():
            if not pending: return
            block = "\n".join(pending); pending.clear()
            res = self.run_cmds(block)
            if res: results_blocks.append(res)
        for kind, content in segments:
            if kind == "text":
                _flush()
                if print_text: self._print_text_chunk(content)
            else: pending.append(content)
        _flush()
        if not any_cmd: return None
        joined = "\n\n".join(results_blocks)
        return joined or None

    def _has_agents(self,t): return bool(MARKER_AGENTS_RE.search(t or ""))
    def _edit_it(self,t):
        if not t: return None
        m=MARKER_EDIT_IT_RE.search(t); return m.group(1).strip() if m else None
    def _parse_marker(self,arg):
        s=(arg or "").strip()
        if not s: return None
        m=re.match(r'^\(?\s*(-?\d+)\s*,\s*(-?\d+)\s*\)?$',s)
        if not m: return None
        try: return (int(m.group(1)),int(m.group(2)))
        except Exception: return None
    def _compress_text(self,text,max_chars=2000):
        if len(text)<=max_chars: return text
        sentences=[s.strip() for s in re.split(r'(?<=[.!?])\s+',text) if len(s.strip())>20]
        if len(sentences)<=5: return text[:max_chars]
        freq=Counter()
        for s in sentences:
            for w in re.findall(r'\w+',s.lower()):
                if len(w)>3: freq[w]+=1
        scored=[]
        for i,s in enumerate(sentences):
            words=re.findall(r'\w+',s.lower())
            sc=sum(freq.get(w,0) for w in words if len(w)>3)
            scored.append((sc/max(1,len(s)),i,s))
        scored.sort(reverse=True)
        kept=sorted(scored[:40],key=lambda x:x[1])
        out=[]; total=0
        for _,_,s in kept:
            if total+len(s)+1>max_chars: break
            out.append(s); total+=len(s)+1
        return "[compressed] "+" ".join(out)
    def _infinite_history_block(self):
        hist=self.chat_history
        if not hist: return ""
        max_recent=int(CONFIG.get("infinite_recent",30))
        budget=int(CONFIG.get("infinite_summary_budget",3000))
        recent=hist[-max_recent:]; older=hist[:-max_recent]
        parts=[]
        if older:
            text="\n".join(
                f"{'User' if m.get('role')=='user' else 'Assistant'}: {m.get('clean_content',m.get('content',''))}"
                for m in older)
            parts.append("[SUMMARY OF EARLIER CONVERSATION]\n"+self._compress_text(text,budget))
        if recent:
            lines=[]
            for m in recent:
                role="User" if m.get("role")=="user" else "Assistant"
                c=m.get("clean_content",m.get("content",""))
                if len(c)>3000: c=c[:3000]+"…"
                lines.append(f"{role}: {c}")
            parts.append("[RECENT MESSAGES]\n"+"\n\n".join(lines))
        return "\n\n".join(parts)

    def _remember_cmd(self, marker, cmd, out):
        if not out or not _SHELL_NOT_FOUND_RX.search(out):
            return
        key = (marker, cmd.strip())
        recent = self._recent_failed_cmds
        if key in recent[-5:]:
            print_warn(f"AI repeated a known-bad command: {cmd[:60]}")
        recent.append(key)
        del recent[:-20]

    def _run_one_cmd(self,marker,cmd):
        if marker=="BASH:":
            out = _annotate_shell_output(cmd, self.execute_bash(cmd))
            self._remember_cmd(marker, cmd, out)
            return marker, out
        if marker=="POWERSHELL:":
            out = _annotate_shell_output(cmd, self.execute_powershell(cmd))
            self._remember_cmd(marker, cmd, out)
            return marker, out
        if marker=="READ:": return marker,self.read_file(cmd)
        if marker=="WRITE:":
            p=cmd.split("|",1)
            if len(p)==2: return marker,self.write_file(p[0].strip(),p[1].strip())
            return marker,"Error: WRITE needs path|content"
        if marker=="EDIT:": return marker,self.edit_file(cmd)
        if marker=="LS:": return marker,self.list_files(cmd or ".")
        if marker=="GREP:": return marker,self.grep(cmd)
        if marker=="FIND:": return marker,self.find_files(cmd)
        if marker=="IDE:": return marker,self.ide_tool()
        if marker=="TASK:":
            t=cmd.strip(); c=5
            mm=re.match(r'"([^"]*)"\s*(\d+)?',t)
            if mm:
                t=mm.group(1)
                if mm.group(2): c=int(mm.group(2))
            if not t: return marker,'Format: TASK: "text" <count>'
            c=max(1,min(600,c)); self.active_task={"text":t,"remaining":c}
            return marker,f"Task saved for {c} messages: {t[:120]}"
        if marker=="FETCH:": return marker,self.fetch_url(cmd)
        if marker=="MOUSE:": return marker,self.mouse_action(cmd)
        if marker=="OCR:": return marker,self.ocr_screen()
        if marker=="SCREENSHOT:": return marker,self.take_screenshot(marker=self._parse_marker(cmd))
        if marker=="PRESS:": return marker,self.press_key(cmd)
        if marker=="PRINT:": return marker,self.print_text(cmd)
        return marker,f"Error: unknown marker {marker}"

    def run_cmds(self,text):
        text = self._repair_broken_cmds(text)
        raw=self._extract_cmds(text)
        if not raw: return None
        bl=CONFIG["ai_blacklist"]
        slots=[]
        for marker,cmd,had_mt in raw:
            name=marker.rstrip(":").upper()
            if name in bl:
                slots.append({"m":marker,"c":cmd,"mt":False,
                              "out":f"[{marker[:-1]}] command not available in this session. "
                                    f"Continue the task using other tools — do not ask why, do not retry.",
                              "done":True})
                print_warn(f"{marker} silently skipped (blocked)"); continue
            if self._confirm(marker,cmd) and not self.confirm(f"allow {marker[:-1]}: {cmd[:60]}?"):
                slots.append({"m":marker,"c":cmd,"mt":False,
                              "out":f"[{marker[:-1]} REJECTED] {cmd}.","done":True})
                print_error(f"{marker} rejected")
            else:
                slots.append({"m":marker,"c":cmd,"mt":had_mt,"out":None,"done":False})
        chunks=[]; i=0
        while i<len(slots):
            if slots[i]["done"]: i+=1; continue
            if slots[i]["mt"]:
                j=i
                while j<len(slots) and not slots[j]["done"] and slots[j]["mt"]: j+=1
                chunks.append(("parallel",list(range(i,j)))); i=j
            else:
                chunks.append(("single",[i])); i+=1
        for kind,idxs in chunks:
            if kind=="parallel" and len(idxs)>1:
                n=min(8,len(idxs))
                ex=_cf.ThreadPoolExecutor(max_workers=n)
                try:
                    futs={k:ex.submit(self._run_one_cmd,slots[k]["m"],slots[k]["c"]) for k in idxs}
                    for k in idxs:
                        try:
                            _mk,out=futs[k].result(timeout=180)
                        except _cf.TimeoutError:
                            out="Error: command timed out after 180s (parallel)"
                            print_warn(f"timeout: {slots[k]['m'][:-1]} {slots[k]['c'][:60]}")
                        except Exception as e:
                            out=f"Error: {e}"
                        slots[k]["out"]=out
                        print_exec(slots[k]["m"][:-1].lower(),slots[k]["c"],out)
                finally:
                    try: ex.shutdown(wait=False, cancel_futures=True)
                    except TypeError: ex.shutdown(wait=False)
            else:
                for k in idxs:
                    try:
                        _mk,out=self._run_one_cmd(slots[k]["m"],slots[k]["c"])
                    except Exception as e:
                        out=f"Error: {e}"
                    slots[k]["out"]=out
                    print_exec(slots[k]["m"][:-1].lower(),slots[k]["c"],out)
        return "\n\n".join(f"[{s['m'][:-1]}]\n{s['out']}" for s in slots)

    def _send_raw(self,prompt,agent_name=None):
        if agent_name: self._switch_agent(agent_name)
        ctx=self._ensure_agent(self.current_agent)
        if not ctx: return None,None,None
        start=time.time(); rids=self.pending_files[:]; self.pending_files.clear()
        try:
            reason,ans,mid=self.client.completion(prompt=prompt,chat_session_id=ctx.chat_session_id,
                parent_message_id=ctx.parent_message_id,ref_file_ids=rids if rids else None)
        except DeepSeekAuthError as e: print_error(f"AUTH: {e}"); return None,None,None
        except Exception as e: print_error(f"HTTP: {e}"); return None,None,None
        if mid: ctx.parent_message_id=mid
        ctx.message_count+=1
        return reason,ans,time.time()-start
    def _send_raw_infinite(self,prompt):
        sid=self.client.create_chat_session()
        sys_text=CONFIG["system_prompt"] or build_system_prompt()
        hist_block=self._infinite_history_block()
        full=f"{sys_text}\n\n{hist_block}\n\nUser: {prompt}" if hist_block else f"{sys_text}\n\nUser: {prompt}"
        rids=self.pending_files[:]; self.pending_files.clear()
        start=time.time()
        try:
            reason,ans,_=self.client.completion(prompt=full,chat_session_id=sid,parent_message_id=None,
                ref_file_ids=rids if rids else None)
        except DeepSeekAuthError as e: print_error(f"AUTH: {e}"); return None,None,None
        except Exception as e: print_error(f"HTTP: {e}"); return None,None,None
        return reason,ans,time.time()-start

    def send_to_deepseek(self, prompt, force_system=False, check_agents=True,
                         agent_name=None, interleave=True):
        CONFIG["_cancel"]=False
        current_prompt=prompt; current_force_system=force_system
        switched_agent=False; last_clean,last_elapsed = None, 0.0
        iter_no=0
        empty_retries_left = int(CONFIG.get("empty_retry_max", 2))
        sys_every = max(1, int(CONFIG.get("system_prompt_every", 10)))
        while True:
            iter_no+=1
            if CONFIG.get("_cancel"):
                CONFIG["_cancel"]=False; print_warn("cancelled"); return None, last_elapsed
            if iter_no==1 and self.active_task and self.active_task["remaining"]>0:
                current_prompt=f"Current task: {self.active_task['text']}\n"+current_prompt
                self.active_task["remaining"]-=1
                if self.active_task["remaining"]==0: self.active_task=None
            self.chat_history.append({"role":"user","content":current_prompt,
                "agent":self.current_agent,"timestamp":datetime.now().isoformat()})
            self.user_message_count+=1; self.save_history()
            if CONFIG["infinite_mode"]:
                reason,ans,elapsed=self._send_raw_infinite(current_prompt)
            else:
                if agent_name and not switched_agent:
                    self._switch_agent(agent_name); switched_agent=True
                ctx=self._ensure_agent(self.current_agent)
                if not ctx: return None, last_elapsed
                first=(ctx.message_count==0)
                send_sys=first or current_force_system or (self.user_message_count % sys_every == 0)
                full=(f"{CONFIG['system_prompt'] or build_system_prompt()}\n\nUser: {current_prompt}"
                      if send_sys else f"User: {current_prompt}")
                reason,ans,elapsed=self._send_raw(full)
            current_force_system=False
            if ans is None: return None, last_elapsed
            if not (reason or ans):
                if empty_retries_left > 0:
                    empty_retries_left -= 1
                    print_warn(f"empty response from server — retrying "
                               f"({empty_retries_left} left)")
                    if self.chat_history and self.chat_history[-1].get("role")=="user":
                        self.chat_history.pop()
                        self.user_message_count = max(0, self.user_message_count - 1)
                        self.save_history()
                    agent_name=None; switched_agent=True; continue
                print_warn("server kept returning empty — ending turn")
                return last_clean, last_elapsed
            resp=f"[REASONING]\n{reason}\n[/REASONING]\n\n{ans}" if reason else ans
            clean=self._strip_cmds(resp); self.last_response_clean=clean
            last_clean,last_elapsed=clean,elapsed

            if check_agents and CONFIG["agents_enabled"] and self._has_agents(ans):
                if interleave:
                    reason_display = self._strip_cmds(reason) if reason else ""
                    if reason_display:
                        sys.stdout.write(f"\n  {FAINT}▶ {ACCENT}thinking{RESET}\n")
                        for l in reason_display.split("\n"):
                            sys.stdout.write(f"  {FAINT}│{RESET} {DIM}{l}{RESET}\n")
                        sys.stdout.write(f"  {FAINT}└─{RESET}\n"); sys.stdout.flush()
                    self._print_interleaved(ans)
                final=self.handle_agents_trigger(task=current_prompt,initial_response=ans)
                if final:
                    self.chat_history.append({"role":"assistant","content":final,"clean_content":final,
                        "agent":self.current_agent,"timestamp":datetime.now().isoformat()})
                    self.save_history()
                    if interleave: self._print_interleaved(final)
                    else: self.run_cmds(final)
                    return final, elapsed
                return last_clean, elapsed

            if interleave:
                reason_display = self._strip_cmds(reason) if reason else ""
                if reason_display:
                    sys.stdout.write(f"\n  {FAINT}▶ {ACCENT}thinking{RESET}\n")
                    for l in reason_display.split("\n"):
                        sys.stdout.write(f"  {FAINT}│{RESET} {DIM}{l}{RESET}\n")
                    sys.stdout.write(f"  {FAINT}└─{RESET}\n"); sys.stdout.flush()
                all_results = self._print_interleaved(ans)
                if not all_results and reason:
                    probe = self._repair_broken_cmds(reason)
                    if self._extract_cmds(probe):
                        print_warn("tool call(s) found inside REASONING block — executing them")
                        all_results = self._print_interleaved(reason, print_text=False)
                if not all_results and empty_retries_left > 0 and (
                        _looks_like_promise(ans) or _looks_like_promise(reason)):
                    empty_retries_left -= 1
                    print_warn(f"model promised action but emitted no tool call — retrying "
                               f"({empty_retries_left} retries left)")
                    self.chat_history.append({"role":"assistant","content":resp,"clean_content":clean,
                        "agent":self.current_agent,"timestamp":datetime.now().isoformat(),"elapsed":elapsed})
                    self.save_history()
                    current_prompt = (
                        "[STRICT RETRY] Your previous message contained NO <<<...>>> tool calls. "
                        "You described what you WOULD do, but did not actually emit any markers. "
                        "The runner executed nothing. NOW do ONE of these:\n"
                        "  (A) Emit at least ONE tool call with EXACT syntax <<<MARKER: argument>>> — "
                        "one per line, on the ANSWER block, NOT in thinking.\n"
                        "  (B) If the task is genuinely complete, write the FINAL ANSWER in plain text "
                        "with ZERO markers.\n"
                        "No plans. No promises. No 'let me'. ACT or CONCLUDE."
                    )
                    agent_name=None; switched_agent=True; continue
                self.chat_history.append({"role":"assistant","content":resp,"clean_content":clean,
                    "agent":self.current_agent,"timestamp":datetime.now().isoformat(),"elapsed":elapsed})
                self.save_history()
                if not all_results:
                    if not (reason or ans):
                        print_warn("empty stream — turn ended with no content")
                    return clean, elapsed
                self.chat_history.append({"role":"user","content":f"Result:\n{all_results}",
                    "agent":self.current_agent,"timestamp":datetime.now().isoformat()})
                self.user_message_count+=1; self.save_history()
                current_prompt=f"Continue using the result above:\n{all_results}"
                agent_name=None; switched_agent=True; continue
            else:
                result=self.run_cmds(ans)
                self.chat_history.append({"role":"assistant","content":resp,"clean_content":clean,
                    "agent":self.current_agent,"timestamp":datetime.now().isoformat(),"elapsed":elapsed})
                self.save_history()
                if not result: return last_clean, last_elapsed
                self.chat_history.append({"role":"user","content":f"Result:\n{result}",
                    "agent":self.current_agent,"timestamp":datetime.now().isoformat()})
                self.user_message_count+=1; self.save_history()
                current_prompt=f"Continue using the result above:\n{result}"
                agent_name=None; switched_agent=True
    def _agent_wait(self,prompt,force_system=True,agent_name=None):
        r,_=self.send_to_deepseek(prompt,force_system=force_system,check_agents=False,
            agent_name=agent_name,interleave=False)
        return r
    def _print_agent(self,name,resp):
        prev=(resp or "<no response>")[:120].replace("\n"," ")
        sys.stdout.write(f"  {FAINT}·{RESET} {ACCENT}{name:<14}{RESET} {DIM}{prev}{RESET}\n"); sys.stdout.flush()
    def _iter_report(self,rs):
        parts=[f"[ITERATION RESULT {rs['iteration']}]","","=== Dev2 ===",rs.get("dev2") or "(empty)","",
               "=== Review ===",rs.get("review") or "(empty)","",
               "=== Safe Review ===",rs.get("safe_review") or "(empty)"]
        er,es=rs.get("edit_it_review"),rs.get("edit_it_safe")
        if er or es:
            parts+=["","=== EDIT-IT ==="]
            if er: parts.append("[Review]: "+er)
            if es: parts.append("[Safe]: "+es)
        parts+=["","Continue as the Index agent."]
        return "\n".join(parts)
    def _run_iter(self,task,idx,n):
        rs={"dev2":None,"review":None,"safe_review":None,"edit_it_review":None,"edit_it_safe":None,"iteration":n}
        print_info(f"iteration {n}: dev2")
        rs["dev2"]=self._agent_wait(DEV2_PROMPT.format(task=task,index_response=idx or "(no)"),agent_name="dev2")
        self._print_agent("Agent-Dev-2",rs["dev2"])
        print_info(f"iteration {n}: review")
        rs["review"]=self._agent_wait(REVIEW_PROMPT.format(task=task,index_response=idx or "(no)",
            dev2_response=rs["dev2"] or "(no)"),agent_name="review")
        self._print_agent("Review",rs["review"])
        er=self._edit_it(rs["review"])
        if er: rs["edit_it_review"]=er
        print_info(f"iteration {n}: safe-review")
        rs["safe_review"]=self._agent_wait(SAFE_REVIEW_PROMPT.format(task=task,index_response=idx or "(no)",
            dev2_response=rs["dev2"] or "(no)",review_response=rs["review"] or "(no)"),agent_name="safe_review")
        self._print_agent("Safe-Review",rs["safe_review"])
        es=self._edit_it(rs["safe_review"])
        if es: rs["edit_it_safe"]=es
        return rs
    def handle_agents_trigger(self,task,initial,force=False,max_iter_override=None):
        idx=initial; it=0
        mx=max_iter_override if max_iter_override is not None else CONFIG["agent_max_iterations"]
        first=True
        while True:
            if mx and it>=mx: break
            if not self._has_agents(idx) and not (force and first): break
            first=False; it+=1
            sys.stdout.write(f"\n  {ACCENT}─── iteration {it} ───{RESET}\n"); sys.stdout.flush()
            ir=self._run_iter(task,idx,it); rep=self._iter_report(ir)
            idx,_=self.send_to_deepseek(rep,force_system=True,check_agents=False,
                agent_name="index",interleave=False)
            if not idx: break
            self._print_agent("Index",idx)
        return idx
    def run_agents(self,task,force=False,demo=False):
        if not force and not CONFIG["agents_enabled"]: print_error("agents disabled"); return None
        for k in ("dev2","review","safe_review"): self.agent_contexts.pop(k,None)
        ip=INDEX_MULTIAGENT_HEADER.format(task=task)
        if force: ip+="\n\n[FORCED]\nYou MUST output <<<CUSTOM: AGENTS>>>."
        idx,_=self.send_to_deepseek(ip,force_system=True,check_agents=False,
            agent_name="index",interleave=False)
        if not idx: print_error("index: no response"); return None
        self._print_agent("Index",idx)
        final=self.handle_agents_trigger(task,idx,force=force,max_iter_override=2 if demo else None)
        if final:
            sys.stdout.write(f"\n{ACCENT}● index final{RESET}\n{FG}{final}{RESET}\n\n")
            tr=self.run_cmds(final)
            if tr: print_info("(executed trailing tool calls from final index answer)")
        return final
    def run_agents_demo(self):
        t=random.choice(DEMO_TASKS); print_info(f"random task: {t}"); return self.run_agents(t,force=True,demo=True)
    def run_agents_variance(self, task, count=5):
        try: count = int(count)
        except Exception:
            print_error(f"Invalid count: {count!r}"); return
        if count > CONFIG.get("vars_max", 25):
            print_error(f"Limit Reached — variance mode supports at most {CONFIG['vars_max']} chats (requested {count}).")
            return
        count = max(2, count)
        if count > 10: print_warn(f"{count} parallel chats may hit rate limits; consider fewer.")
        print_info(f"variance mode: launching {count} independent chats in parallel...")
        results = [""] * count; meta = [None] * count
        def _worker(i):
            try:
                sid = self.client.create_chat_session()
                sys_text = CONFIG["system_prompt"] or build_system_prompt()
                full = f"{sys_text}\n\nUser: {task}"
                reason, ans, _ = self.client.completion(
                    prompt=full, chat_session_id=sid,
                    parent_message_id=None, ref_file_ids=None)
                return i, sid, (ans or ""), (reason or ""), None
            except Exception as e:
                return i, None, "", "", str(e)
        t0 = time.time()
        with _cf.ThreadPoolExecutor(max_workers=min(8, count)) as ex:
            futs = [ex.submit(_worker, i) for i in range(count)]
            done = 0
            for fut in _cf.as_completed(futs):
                i, sid, ans, reason, err = fut.result()
                if err:
                    results[i] = ""; meta[i] = {"err": err, "sid": sid}
                    print_info(f"chat {done+1}/{count} failed: {err[:80]}")
                else:
                    results[i] = ans; meta[i] = {"err": None, "sid": sid, "reason": reason}
                    print_info(f"chat {done+1}/{count} done ({len(ans)} chars)")
                done += 1
        elapsed = time.time() - t0
        sys.stdout.write(f"\n  {ACCENT}{BOLD}▸ variance results{RESET}  "
                         f"{FAINT}{count} chats in {elapsed:.1f}s{RESET}\n\n")
        for i in range(count):
            m = meta[i] or {}; r = results[i]
            if m.get("err"): preview = f"ERROR: {m['err']}"; color = ERR_C
            else:
                preview = (r or "(empty)").replace("\n", " ").replace("\r", " ")
                preview = preview[:100] + ("…" if len(preview) > 100 else "")
                color = DIM
            sys.stdout.write(f"  {FAINT}[{i+1:>2}]{RESET}  {color}{preview}{RESET}\n")
        sys.stdout.write("\n"); sys.stdout.flush()
        ok = [i for i in range(count) if not (meta[i] or {}).get("err") and results[i].strip()]
        if len(ok) < 2:
            print_warn("not enough successful answers for review")
            self.chat_history.append({"role":"user","content":f"/agents -vars({count}): {task}",
                                       "agent":"variance","timestamp":datetime.now().isoformat()})
            self.save_history(); return
        try:
            with _print_lock:
                sys.stdout.write(f"  {ACCENT}?{RESET} {DIM}run review and pick the best? (y/n): {RESET}")
                sys.stdout.flush()
            answer = input().strip().lower()
        except Exception: answer = "n"
        if answer != "y":
            self.chat_history.append({"role":"user","content":f"/agents -vars({count}): {task}",
                                       "agent":"variance","timestamp":datetime.now().isoformat()})
            self.save_history(); return
        print_info("review: sending all answers to a fresh chat...")
        cap = 8000
        parts = [f"[TASK]\n{task}\n",
                 f"[VARIANCE MODE] {len(ok)} independent answers, indices listed below.",
                 "Pick the single BEST answer. Judge on correctness, clarity, completeness."]
        for idx in ok:
            r = results[idx]
            if len(r) > cap: r = r[:cap] + "\n…[truncated]"
            parts.append(f"\n=== ANSWER {idx+1} ===\n{r}")
        parts.append(
            "\n=== END ===\n"
            "Reply EXACTLY in this format:\n"
            "BEST: <number>\n"
            "WHY: <one short paragraph>\n"
            "---\n"
            "<the full final answer you selected, cleaned up if needed>"
        )
        review_prompt = "\n".join(parts)
        try:
            sid = self.client.create_chat_session()
            rreason, rans, _ = self.client.completion(
                prompt=review_prompt, chat_session_id=sid, parent_message_id=None)
        except Exception as e:
            print_error(f"review failed: {e}"); return
        if rreason:
            sys.stdout.write(f"\n  {FAINT}▶ {ACCENT}review thinking{RESET}\n")
            for l in rreason.split("\n"): sys.stdout.write(f"  {FAINT}│{RESET} {DIM}{l}{RESET}\n")
            sys.stdout.write(f"  {FAINT}└─{RESET}\n")
        if rans:
            sys.stdout.write("\n")
            for l in rans.split("\n"): sys.stdout.write(f"  {FG}{l}{RESET}\n")
            sys.stdout.write("\n")
        self.chat_history.append({"role":"user","content":f"/agents -vars({count}): {task}",
                                   "agent":"variance","timestamp":datetime.now().isoformat()})
        self.chat_history.append({"role":"assistant","content":rans or "","agent":"variance",
                                   "timestamp":datetime.now().isoformat()})
        self.save_history()
    def loop_agents(self,task):
        if CONFIG["loop_active"]: print_info("loop already running"); return
        CONFIG["loop_active"]=True; print_info("loop started. stop with /unloop")
        def w():
            try:
                for k in ("dev2","review","safe_review"): self.agent_contexts.pop(k,None)
                ip=INDEX_MULTIAGENT_HEADER.format(task=task)+"\n\n[LOOP]\nYou MUST output <<<CUSTOM: AGENTS>>>."
                idx,_=self.send_to_deepseek(ip,force_system=True,check_agents=False,
                    agent_name="index",interleave=False)
                if not idx: return
                self._print_agent("Index",idx)
                it=0; mx=CONFIG["agent_max_iterations"]
                while CONFIG["loop_active"]:
                    if mx and it>=mx: break
                    it+=1; sys.stdout.write(f"\n  {ACCENT}─── iteration {it} ───{RESET}\n"); sys.stdout.flush()
                    ir=self._run_iter(task,idx,it); rep=self._iter_report(ir)+"\n\n[LOOP] Continue or STOP."
                    idx,_=self.send_to_deepseek(rep,force_system=True,check_agents=False,
                        agent_name="index",interleave=False)
                    if not idx: break
                    self._print_agent("Index",idx)
                    if "<<<STOP>>>" in idx.upper(): break
                    if not CONFIG["loop_active"]: break
            except Exception as e: print_error(f"loop error: {e}")
            finally: CONFIG["loop_active"]=False; print_info("loop stopped")
        self.loop_thread=threading.Thread(target=w,daemon=True); self.loop_thread.start()
    def save_history(self):
        try:
            with open(HISTORY_FILE,"w",encoding="utf-8") as f:
                json.dump(self.chat_history[-CONFIG["history_limit"]:],f,ensure_ascii=False,indent=2)
        except Exception: pass
    def new_session(self):
        if not self.client: return False
        try:
            sid=self.client.create_chat_session()
            self.agent_contexts["main"]=AgentContext(sid); self.current_agent="main"
            print_ok(f"new main session: {sid[:8]}..."); return True
        except Exception as e: print_error(f"Error: {e}"); return False
    def resume(self):
        try:
            with open(HISTORY_FILE,"r",encoding="utf-8") as f: self.chat_history=json.load(f)
        except Exception: self.chat_history=[]
        if self.chat_history:
            print_info("last messages")
            for msg in self.chat_history[-10:]:
                role="user" if msg.get("role")=="user" else "asst"
                c=msg.get("clean_content",msg.get("content",""))
                sys.stdout.write(f"  {FAINT}{role:<5}{RESET} {DIM}{c[:160]}{RESET}\n")
        else: print_info("no messages")

COMMANDS={"send":"send message","effort":"effort level","clear":"clear history",
    "compact":"compress history","context":"show context","history":"show history",
    "status":"system status","debug":"debug on/off","doctor":"diagnosis",
    "diff":"git diff","commit":"git commit","review":"code review",
    "dts":"DeepThink on/off","search":"Search on/off","lang":"answer language",
    "security":"security mode","ps":"PowerShell on/off","admin":"admin on/off",
    "sys":"set system prompt","sysclear":"clear system prompt","sysprompt":"show system prompt",
    "model":"current model","continue":"continue response","resume":"resume session",
    "screenshot":"capture screen and send to AI","ocr":"read visible screen text + coords",
    "press":"press a key (e.g. /press enter, /press ctrl+s)",
    "print":"type text via keyboard (e.g. /print hello world)",
    "drag":"drag from point 1 to point 2 (e.g. /drag 100,200 800,500)",
    "ide":"weld into VS Code (install bridge extension)","ide unweld":"detach from VS Code",
    "bl":"blacklist AI commands (never allowed)","wl":"whitelist AI commands (always allowed)",
    "help":"help","agents":"agents on/off/task/demo or /agents <task> -vars [--N]",
    "loop":"autonomous loop","unloop":"stop loop",
    "infl":"infinite mode on/off (new chat + compressed history)",
    "token":"show/refresh token","forget":"delete token.txt","exit":"exit"}
COMMAND_LIST=list(COMMANDS.keys())
def _sec_tag(): return {"manual":"M","safe-auto":"SA","auto":"A"}.get(CONFIG["security"],"?")
def _prompt_msg(): return f"▸ [{_sec_tag()}] "
class SlashCompleter(Completer):
    def __init__(self,cmds): self.cmds=cmds
    def get_completions(self,doc,ev):
        t=doc.text_before_cursor
        if "\n" in t: return
        s=t.lstrip()
        if not s.startswith("/"): return
        w=s[1:]
        if " " in w: return
        for c in self.cmds:
            if c.startswith(w.lower()): yield Completion("/"+c,start_position=-len(s))
def process_command(a,ui):
    if ui.startswith("/send "):
        final, _ = a.send_to_deepseek(ui[6:].strip(),force_system=False)
        if final is None and not a.last_response_clean:
            print_warn("empty turn — press Enter to retry, or type a new message")
        return
    if ui.startswith("/effort "):
        lv=ui[8:].strip().lower()
        if lv in SYSTEM_PROMPTS:
            CONFIG["effort"]=lv; CONFIG["system_prompt"]=""
            if lv in FORCE_DEEPTHINK_EFFORTS: CONFIG["thinking"]=True
            print_ok(f"Effort: {lv} (model={current_model_name()})")
        else: print_error("Available: low, medium, high, ultracode, auto")
        return
    if ui.startswith("/dts"):
        p=ui.split()
        if len(p)==2 and p[1] in ("on","off"):
            CONFIG["thinking"]=(p[1]=="on"); print_ok(f"DeepThink: {'ON' if CONFIG['thinking'] else 'OFF'} → {current_model_name()}")
        else: print_error("Use: /dts on|off")
        return
    if ui.startswith("/search"):
        p=ui.split()
        if len(p)==2 and p[1] in ("on","off"):
            CONFIG["search"]=(p[1]=="on"); print_ok(f"Search: {'ON' if CONFIG['search'] else 'OFF'} → {current_model_name()}")
        else: print_error("Use: /search on|off")
        return
    if ui=="/model": print_info(f"Model: {current_model_name()}"); return
    if ui=="/clear":
        a.chat_history=[]; a.save_history(); a.new_session()
        print_ok("History cleared"); return
    if ui.startswith("/sys "): CONFIG["system_prompt"]=ui[5:].strip(); print_ok("System prompt set"); return
    if ui=="/sysclear": CONFIG["system_prompt"]=""; print_ok("Cleared"); return
    if ui=="/sysprompt": sys.stdout.write(f"\n{FG}{CONFIG['system_prompt'] or build_system_prompt()}{RESET}\n\n"); return
    if ui.startswith("/security"):
        p=ui.split()
        if len(p)==1:
            print_info(f"Security: {CONFIG['security']} (use: /security manual|safe-auto|auto)")
            print_info("  manual    → asks for every command, including OCR, PRESS, PRINT and SCREENSHOT")
            print_info("  safe-auto → OCR + cwd file ops + PRESS silent; SCREENSHOT, PRINT, MOUSE still ask")
            print_info("  auto      → never asks")
            return
        m=p[1].strip().lower(); m={"auto_dir":"safe-auto","auto_all":"auto"}.get(m,m)
        if m in SECURITY_ORDER: CONFIG["security"]=m; print_ok(f"Security: {m}")
        else: print_error("Available: manual, safe-auto, auto")
        return
    if ui.startswith("/ps"):
        p=ui.split()
        if len(p)==1: print_info(f"PowerShell: {'on' if CONFIG['ps_enabled'] else 'off'}"); return
        if p[1] in ("on","off"): CONFIG["ps_enabled"]=(p[1]=="on"); print_ok(f"PowerShell: {p[1]}")
        return
    if ui.startswith("/admin"):
        p=ui.split()
        if len(p)==1: print_info(f"Admin: {'on' if CONFIG['admin'] else 'off'}"); return
        if p[1] in ("on","off"): CONFIG["admin"]=(p[1]=="on"); print_ok(f"Admin: {p[1]}")
        return
    if ui.startswith("/lang"):
        p=ui.split()
        if len(p)==1: print_info(f"Answer language: {ANSWER_LANGUAGE_NAMES.get(CONFIG['language'],'?')} ({CONFIG['language']})"); return
        nl=p[1].strip().lower()
        if nl in ANSWER_LANGUAGE_NAMES: CONFIG["language"]=nl; print_ok(f"Answer language: {ANSWER_LANGUAGE_NAMES[nl]} ({nl})")
        else: print_error("Available: ru, en, de")
        return
    if ui.startswith("/infl"):
        p=ui.split()
        if len(p)==1:
            state="ON" if CONFIG["infinite_mode"] else "OFF"
            print_info(f"Infinite mode: {state} "
                       f"({'fresh chat per request, inline history' if CONFIG['infinite_mode'] else 'single chat with built-in memory'})")
            print_info("Use: /infl on | /infl off")
            return
        v=p[1].strip().lower()
        if v=="on": CONFIG["infinite_mode"]=True; print_ok("Infinite mode: ON")
        elif v=="off": CONFIG["infinite_mode"]=False; print_ok("Infinite mode: OFF")
        else: print_error("Use: /infl on|off")
        return
    if ui.startswith("/ide"):
        rest = ui[4:].strip().lower()
        if rest == "unweld":
            removed = _uninstall_ide_extension()
            CONFIG["ide_welded"] = False
            if removed:
                for p in removed: print_info(f"removed: {p}")
                print_ok("IDE un-welded. Reload VS Code (Ctrl+Shift+P → Developer: Reload Window).")
            else: print_info("nothing to remove — already unwelded")
            return
        if rest == "status":
            st = _read_ide_state(max_age_sec=60)
            print_info(_ide_status_line())
            if st:
                if st.get("vscode"): print_info(f"vscode: {st['vscode']} pid={st.get('pid')} (alive)")
                if st.get("bootId"): print_info(f"boot: {st['bootId']}  tick: {st.get('tick','?')}")
                if st.get("workspace"): print_info(f"workspace: {st['workspace']}")
                if st.get("activeFile"): print_info(f"active file: {st['activeFile']} ({st.get('lineCount','?')} lines)")
                opens = st.get("openFiles") or []
                if opens:
                    print_info(f"open tabs: {len(opens)}")
                    for p in opens[:10]: print_info(f"  {os.path.basename(p)}")
            print_info("Use: /ide          — weld (install bridge, launch VS Code)")
            print_info("     /ide unweld   — detach from VS Code")
            return
        ok, msg = _ide_weld()
        if ok:
            CONFIG["ide_welded"] = True
            print_ok("welded to VS Code. AI now sees your active file, edits open there.")
            print_info("If VS Code was already open: Ctrl+Shift+P → Developer: Reload Window")
        else:
            print_error(f"weld failed: {msg}")
            print_info("manual fallback:")
            print_info("  1. Install VS Code if not installed: https://code.visualstudio.com/")
            print_info(f"  2. Extension files are already at: {_code_extension_root() / 'rnalimov.dfreecode-ide-1.0.0'}")
            print_info("  3. Restart VS Code. Status bar will show a radio-tower icon.")
        return
    if ui.startswith("/bl"):
        rest=ui[3:].strip()
        if not rest:
            bl=CONFIG["ai_blacklist"]
            print_info(f"AI blacklist: {', '.join(sorted(bl)) if bl else '(empty)'}")
            print_info('Use: /bl ["SCREENSHOT"; "LS"]   — AI never runs these, silently skips')
            print_info('     /bl clear                     — reset')
            return
        if rest.lower()=="clear":
            CONFIG["ai_blacklist"]=set(); print_ok("AI blacklist cleared"); return
        names=_parse_ai_list(rest)
        if not names: print_error('Could not parse. Use: /bl ["CMD1"; "CMD2"]'); return
        CONFIG["ai_blacklist"]=set(names)
        print_ok(f"AI blacklist: {', '.join(sorted(CONFIG['ai_blacklist']))}")
        ov=CONFIG["ai_blacklist"] & CONFIG["ai_whitelist"]
        if ov: print_warn(f"Also in whitelist (blacklist wins at runtime): {', '.join(sorted(ov))}")
        return
    if ui.startswith("/wl"):
        rest=ui[3:].strip()
        if not rest:
            wl=CONFIG["ai_whitelist"]
            print_info(f"AI whitelist: {', '.join(sorted(wl)) if wl else '(empty)'}")
            print_info('Use: /wl ["SCREENSHOT"]   — AI runs these silently even in manual')
            print_info('     /wl clear            — reset')
            return
        if rest.lower()=="clear":
            CONFIG["ai_whitelist"]=set(); print_ok("AI whitelist cleared"); return
        names=_parse_ai_list(rest)
        if not names: print_error('Could not parse. Use: /wl ["CMD1"; "CMD2"]'); return
        CONFIG["ai_whitelist"]=set(names)
        print_ok(f"AI whitelist: {', '.join(sorted(CONFIG['ai_whitelist']))}")
        ov=CONFIG["ai_blacklist"] & CONFIG["ai_whitelist"]
        if ov: print_warn(f"Also in blacklist (blacklist wins at runtime): {', '.join(sorted(ov))}")
        return
    if ui=="/status":
        print_info(f"Effort: {CONFIG['effort']} | Model: {current_model_name()}")
        print_info(f"Security: {CONFIG['security']} | PS: {'on' if CONFIG['ps_enabled'] else 'off'}")
        print_info(f"Answer language: {ANSWER_LANGUAGE_NAMES.get(CONFIG['language'],'?')} ({CONFIG['language']})")
        print_info(f"Debug: {'on' if CONFIG['verbose_http'] else 'off'}")
        print_info(f"Agents: {'on' if CONFIG['agents_enabled'] else 'off'} | Loop: {'on' if CONFIG['loop_active'] else 'off'}")
        print_info(f"Agent max iterations: {CONFIG['agent_max_iterations']} (0 = unlimited)")
        print_info(f"System prompt every: {CONFIG.get('system_prompt_every',10)} messages")
        print_info(f"Empty-answer retry cap: {CONFIG.get('empty_retry_max',2)}")
        print_info(f"Long cmd timeout: {CONFIG.get('long_cmd_timeout',300)}s  |  idle kill: {CONFIG.get('shell_idle_kill',90)}s")
        print_info(f"Serial-only markers (no -mt): {', '.join(sorted(SERIAL_MARKERS))}")
        print_info(f"Infinite mode: {'ON' if CONFIG['infinite_mode'] else 'OFF'}")
        bl=CONFIG["ai_blacklist"]; wl=CONFIG["ai_whitelist"]
        print_info(f"AI blacklist: {', '.join(sorted(bl)) if bl else '(empty)'}")
        print_info(f"AI whitelist: {', '.join(sorted(wl)) if wl else '(empty)'}")
        print_info(f"Vars max chats: {CONFIG['vars_max']}")
        print_info(f"DSFREEHACK: {DSFREEHACK_DIR}")
        print_info(f"Screenshot (expensive, visual): {'available' if PIL_OK else 'MISSING Pillow'} (grid {CONFIG['grid_step']}px, cursor drawn)")
        print_info(f"OCR (cheap, text+coords): {'available (RapidOCR)' if RAPIDOCR_OK else 'MISSING'} (lang={CONFIG.get('ocr_lang')}, returns cursor)")
        print_info(f"pyautogui: {'ok' if PYAUTOGUI_OK else 'MISSING'} (MOUSE/drag/PRESS/PRINT, Unicode-safe)")
        print_info(_ide_status_line())
        return
    if ui=="/cost": print_info(f"History: {len(a.chat_history)} messages"); return
    if ui=="/context":
        tokens=sum(len(m.get("content",""))//4 for m in a.chat_history)
        print_info(f"Context: {len(a.chat_history)} msgs, ~{tokens} tokens"); return
    if ui=="/history":
        if a.chat_history:
            for i,m in enumerate(a.chat_history[-10:]):
                role=m.get("agent","user" if m.get("role")=="user" else "asst")
                c=m.get("clean_content",m.get("content",""))
                sys.stdout.write(f"  {FAINT}{i+1:>2}.{RESET} {ACCENT}{role:<8}{RESET} {DIM}{c[:120]}{RESET}\n")
        else: print_info("History empty")
        return
    if ui=="/compact":
        if len(a.chat_history)>10: a.chat_history=a.chat_history[-5:]; a.save_history(); print_ok("Compacted")
        return
    if ui.startswith("/debug"):
        p=ui.split()
        if len(p)==1: CONFIG["verbose_http"]=not CONFIG["verbose_http"]; print_ok(f"Debug: {'on' if CONFIG['verbose_http'] else 'off'}"); return
        arg=p[1].lower()
        if arg=="on": CONFIG["verbose_http"]=True; print_ok("Debug: on")
        elif arg=="off": CONFIG["verbose_http"]=False; print_ok("Debug: off")
        else: print_error("Use: /debug on|off")
        return
    if ui=="/doctor":
        print_info(f"Python: {sys.version.split()[0]}"); print_info(f"CWD: {os.getcwd()}")
        print_info(f"Token: {CONFIG['token'][:20]}..."); print_info(f"Init OK: {a.init_ok}")
        print_info(f"DSFREEHACK: {DSFREEHACK_DIR}")
        print_info(f"wasmtime: {'ok' if WASMTIME_OK else 'MISSING'}")
        print_info(f"websocket: {'ok' if WEBSOCKET_OK else 'MISSING'}")
        print_info(f"Pillow: {'ok' if PIL_OK else 'MISSING'}")
        print_info(f"RapidOCR: {'ok' if RAPIDOCR_OK else 'MISSING'}")
        print_info(f"pyautogui: {'ok' if PYAUTOGUI_OK else 'MISSING'}")
        try:
            import pyperclip; _pc = "ok"
        except ImportError: _pc = "MISSING (Unicode PRINT falls back to Win API)"
        print_info(f"pyperclip: {_pc}")
        print_info(f"VS Code CLI: {_find_code_cli() or 'MISSING'}")
        print_info(f"extensions dir: {_code_extension_root()}")
        print_info(f"ide state file: {IDE_STATE_FILE} ({'exists' if IDE_STATE_FILE.exists() else 'missing'})")
        st = _read_ide_state(max_age_sec=3600, check_pid=False)
        if st:
            pid_ok = _pid_alive(st.get("pid"))
            print_info(f"ide pid: {st.get('pid')} alive={pid_ok} boot={st.get('bootId','?')} tick={st.get('tick','?')}")
        return
    if ui.startswith("/ocr"):
        r=a.ocr_screen(); print_info(r); return
    if ui.startswith("/screenshot"):
        arg=ui[11:].strip()
        marker=a._parse_marker(arg)
        r=a.take_screenshot(marker=marker); print_info(r); return
    if ui.startswith("/press "):
        r=a.press_key(ui[7:].strip()); print_info(r); return
    if ui.startswith("/print "):
        r=a.print_text(ui[7:].strip()); print_info(r); return
    if ui.startswith("/drag "):
        r=a.mouse_drag(ui[6:].strip()); print_info(r); return
    if ui=="/diff": print_response(a.get_diff()); return
    if ui.startswith("/commit "): print_response(a.git_commit(ui[8:].strip())); return
    if ui=="/review":
        d=a.get_diff()
        if not d or d=="No changes": print_info("No changes"); return
        a.send_to_deepseek(f"Review code changes:\n{d}",force_system=False)
        return
    if ui=="/continue":
        if not a.last_response_clean: print_info("History empty"); return
        a.send_to_deepseek("Continue from where you left off.\n\n"+a.last_response_clean,force_system=False)
        return
    if ui=="/resume": a.resume(); return
    if ui=="/token":
        print_info(f"Token: {CONFIG['token'][:20]}...")
        try: ans=input("  Update? (y/n): ").strip().lower()
        except Exception: ans="n"
        if ans=="y" or ans=="":
            if paste_token_manually():
                a.init_client()
                print_ok(f"Reinit: {a.init_ok}")
                if not a.init_ok: print_error(f"init: {a.init_error_msg}")
        return
    if ui=="/forget": delete_token_file(); CONFIG["token"]=""; return
    if ui.startswith("/agents"):
        rest=ui[7:].strip()
        m_vars=re.search(r'(?:^|\s)-vars(?:\s+--?(\d+))?\s*$',rest)
        if m_vars:
            cnt=int(m_vars.group(1)) if m_vars.group(1) else 5
            task=rest[:m_vars.start()].strip()
            if not task:
                print_error("Usage: /agents <task> -vars [--N]"); return
            a.run_agents_variance(task,count=cnt); return
        r=rest
        if r in ("","status"): print_info(f"Agents: {'on' if CONFIG['agents_enabled'] else 'off'}")
        elif r=="on": CONFIG["agents_enabled"]=True; print_ok("Agents: on")
        elif r=="off": CONFIG["agents_enabled"]=False; print_ok("Agents: off")
        elif r=="demo": a.run_agents_demo()
        elif r.startswith("task"):
            t=r[4:].strip()
            if t: a.run_agents(t,force=True)
            else: print_error("Usage: /agents task <text>")
        else: a.run_agents(r,force=True)
        return
    if ui.startswith("/loop"):
        t=ui[5:].strip()
        if t: a.loop_agents(t)
        else: print_error("Usage: /loop <task>")
        return
    if ui=="/unloop":
        if CONFIG["loop_active"]: CONFIG["loop_active"]=False; print_ok("Loop stopped")
        else: print_info("Loop not running")
        return
    if ui=="/help":
        for c,d in COMMANDS.items(): sys.stdout.write(f"  {ACCENT}/{c:<16}{RESET} {DIM}{d}{RESET}\n")
        return
    if ui=="/exit": print_info("Exit."); sys.exit(0)
    final, _ = a.send_to_deepseek(ui,force_system=False)
    if final is None and not a.last_response_clean:
        print_warn("empty turn — press Enter to retry, or type a new message")

def _cycle_sec():
    try: i=SECURITY_ORDER.index(CONFIG["security"])
    except ValueError: i=0
    CONFIG["security"]=SECURITY_ORDER[(i+1)%len(SECURITY_ORDER)]
def chat_loop(a):
    print_info(f"Model: {current_model_name()}")
    print_info("Type /help for commands, /exit to quit")
    print_info("Shift+Tab cycles security (M → SA → A)")
    print_info(f"Infinite mode: {'ON' if CONFIG['infinite_mode'] else 'OFF'} (toggle with /infl on|off)")
    print_info("Type /ide to weld into VS Code (install bridge + launch)")
    print()
    if PROMPT_AVAILABLE:
        session=PromptSession(history=InMemoryHistory())
        completer=SlashCompleter(COMMAND_LIST); kb=KeyBindings()
        @kb.add('s-tab')
        def _st(ev): _cycle_sec(); ev.app.invalidate()
        try:
            @kb.add(Keys.BackTab)
            def _bt(ev): _cycle_sec(); ev.app.invalidate()
        except Exception: pass
        while True:
            try:
                sys.stdout.write("\n"); sys.stdout.flush()
                ui=session.prompt(_prompt_msg,completer=completer,complete_while_typing=True,key_bindings=kb).strip()
                if not ui: continue
                process_command(a,ui)
            except KeyboardInterrupt: pass
            except EOFError: print_info("Exit."); sys.exit(0)
            except Exception as e: print_error(f"Error: {e}")
    else:
        while True:
            try:
                sys.stdout.write(f"\n{ACCENT}▸{RESET} {FAINT}[{_sec_tag()}]{RESET} "); sys.stdout.flush()
                ui=input().strip()
                if not ui: continue
                process_command(a,ui)
            except KeyboardInterrupt: pass
            except EOFError: print_info("Exit."); sys.exit(0)
            except Exception as e: print_error(f"Error: {e}")

def show_launcher():
    print()
    print(f"  {ACCENT}{BOLD}DeepSeek Assistant{RESET}\n")
    if CONFIG["token"]: print_info(f"Token: {CONFIG['token'][:20]}...{CONFIG['token'][-10:]}")
    else: print_warn("Token missing")
    if not WASMTIME_OK: print_error("wasmtime missing — will retry next launch")
    if not PIL_OK: print_warn("Pillow missing — SCREENSHOT/OCR will not work")
    if not RAPIDOCR_OK:
        print_warn("RapidOCR missing — OCR will not work")
        print_info("  fix: pip install rapidocr-onnxruntime opencv-python numpy")
    if not PYAUTOGUI_OK: print_warn("pyautogui missing — cursor draw / MOUSE / DRAG / PRESS / PRINT will not work")
    print_info(f"DSFREEHACK home: {DSFREEHACK_DIR}")
    print_info(_ide_status_line())
    print()
    print(f"  {ACCENT}1{RESET} {DIM}— Start{RESET}")
    print(f"  {ACCENT}2{RESET} {DIM}— Sign in via Chrome{RESET}")
    print(f"  {ACCENT}3{RESET} {DIM}— Paste token{RESET}")
    print(f"  {ACCENT}4{RESET} {DIM}— Delete token{RESET}")
    print(f"  {ACCENT}0{RESET} {DIM}— Exit{RESET}\n")
    return input(f"{ACCENT}▸{RESET} ").strip()
def _cleanup():
    p=CONFIG.get("_tmp_profile")
    if p:
        try: shutil.rmtree(p,ignore_errors=True)
        except Exception: pass
        CONFIG.pop("_tmp_profile",None)
def main():
    print_header("by rnalimov · DeepSeek Free Code",os.getcwd(),"v16.7")
    install_ctrlc_handler(); load_token_from_file()
    if _read_ide_state(max_age_sec=30):
        CONFIG["ide_welded"] = True
    while True:
        ch=show_launcher()
        if ch=="0": _cleanup(); print_info("Exit."); sys.exit(0)
        if ch=="1":
            if not CONFIG["token"]:
                print_error("Token missing. Use option 2 or 3 first."); continue
            if not _looks_like_real_token(CONFIG["token"]):
                print_error("Token malformed — re-paste it via option 3."); continue
            if not WASMTIME_OK: print_error("wasmtime missing — restart the script"); continue
            a=DeepSeekAssistant()
            if not a.init_ok:
                print_error(f"Init failed: {a.init_error_msg}")
                print_info("If the token is expired, use option 2 (Chrome sign-in) or 3 (paste fresh).")
                continue
            chat_loop(a); break
        if ch=="2":
            proc,tid=launch_chrome_for_registration()
            if not proc: continue
            token,state=fetch_token_via_cdp(target_id=tid)
            if token:
                token=normalize_token(token)
                if _looks_like_real_token(token): CONFIG["token"]=token; save_token_to_file()
            else: print_warn("Token not received.")
            try: proc.terminate()
            except Exception: pass
            time.sleep(0.5); _cleanup(); print_info("Chrome closed.")
            continue
        if ch=="3": paste_token_manually(); continue
        if ch=="4": delete_token_file(); CONFIG["token"]=""; continue
        print_error("Invalid choice.")
if __name__=="__main__":
    try: main()
    finally: _cleanup()
