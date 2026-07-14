A simple, free Coding!

# DeepSeek Free API Hack
[![GitHub license](https://img.shields.io/github/license/rnalimov/deepseek-free-api-hack)](https://github.com/rnalimov/deepseek-free-api-hack/blob/main/LICENSE)
[![GitHub stars](https://img.shields.io/github/stars/rnalimov/deepseek-free-api-hack)](https://github.com/rnalimov/deepseek-free-api-hack/stargazers)
[![GitHub issues](https://img.shields.io/github/issues/rnalimov/deepseek-free-api-hack)](https://github.com/rnalimov/deepseek-free-api-hack/issues)
[![GitHub last commit](https://img.shields.io/github/last-commit/rnalimov/deepseek-free-api-hack)](https://github.com/rnalimov/deepseek-free-api-hack/commits/main)

**Use DeepSeek for free without API keys.**  
A bridge between DeepSeek web interface and local CLI/GUI, **designed specifically for coding, software development, and programming tasks**.  
Provides a Claude Code‑like experience with tools for file editing, terminal execution, Git, GitHub, code review, and more.

## ⚠️ Disclaimer
This project is for educational and entertainment purposes only.  
Using automated scripts on DeepSeek's website may violate their Terms of Service.  
The author is not responsible for account bans or any consequences.

**This project is in early development stage.** There may be many bugs, issues, or incomplete features.  
If you encounter problems, feel free to open an issue or submit a Pull Request — they are warmly welcomed and quickly reviewed.

## 🚀 Features
- CLI with autocomplete (Tab)
- GUI 
- Model switching: Instant / Expert / Vision
- DeepThink toggle
- Interrupt generation
- Tools: Bash, Read, Write, LS, Grep, Find, Edit, Task
- Git commands: diff, commit, branch
- GitHub integration (login, commit, push, PR, branch, sync)
- Planning (`plan.md`) and task management (`tasks.md`)
- Code review, test generation, quality checks
- IDE integration (open, goto)
- Multi‑language: ru, en, de
- Security modes: manual, auto_dir, auto_all
- Admin mode, PowerShell toggle
- Resume session, continue, bypass jailbreak

## 📦 Installation
```bash
git clone https://github.com/rnalimov/deepseek-free-api-hack
cd deepseek-free-api-hack
pip install -r requirements.txt
```
🖥️ Usage
```bash
# Console mode (default)
python server.py

# GUI mode
python server.py --gui

# Debug mode
python server.py --debug
```
Tampermonkey script
Install Tampermonkey extension in your browser.

Copy tampermonkey.js into a new userscript.

Open chat.deepseek.com.

One‑click launcher
Inside the app, type /path to add the current folder to your system PATH and create deephack.bat.
After that you can run deephack from any terminal.

📋 Commands
Command	Description
/send <text>	Send message to DeepSeek
/model <type>	instant / expert / vision
/effort <level>	low / medium / high / ultracode
/dts on/off	DeepThink toggle
/restart	Reload DeepSeek page (go to chat.deepseek.com)
/interrupt	Stop generation
/lang <lang>	ru / en / de
/clear	Clear history
/history	Show history
/status	System status
/cost	Token usage
/diff	Git diff
/commit <msg>	Git commit
/branch <name>	Create branch
/review	Code review
/test-gen	Generate tests
/quality	Quality check
/plan <desc>	Create plan in plan.md
/task add/list/done	Manage tasks
/ide open/goto	IDE integration
/resume	Show last messages
/continue	Continue last incomplete response
/github login/commit/push/pr/branch/sync	GitHub operations
/init	Create instruct.md
/bypass	Send jailbreak prompt
/path	Add to PATH and create deephack.bat
/sysprompt	Show system prompt
/doctor	Diagnosis
/help	Show all commands
/exit	Exit

Better than MCP!
