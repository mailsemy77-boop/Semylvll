# manager.py — AUTO BOT MANAGER (Final Stable)
import os, sys, json, shutil, subprocess, threading, time, re, signal
from datetime import datetime

# ============================================
# CONFIG — Yaha change kar sakte ho
# ============================================
ACCOUNTS_FILE   = 'accounts.json'
TEMPLATES_BOT   = 'templates_bot'
BOTS_DIR        = 'bots'
SHARED_LIBS     = 'shared_libs'
MAIN_FILE_NAME  = 'main.py'       # aapki bot file ka naam

MAX_ACTIVE      = 35              # ek time pe 40 bots
TARGET_LEVEL    = 12              # level 12 pe replace
CHECK_INTERVAL  = 20              # 20 sec pe check
RESTART_DELAY   = 5               # crash ke baad 5 sec
HANG_TIMEOUT    = 600             # 10 min me level na badhe to restart

os.makedirs(BOTS_DIR, exist_ok=True)
os.makedirs(SHARED_LIBS, exist_ok=True)
os.makedirs(TEMPLATES_BOT, exist_ok=True)

SHARED_PACKAGES = [
    'httpx',
    'google-play-scraper',
    'pycryptodome',
    'protobuf',
    'protobuf-decoder',
]

# ============================================
# SHARED LIBS — ek baar install (quiet)
# ============================================
def ensure_shared_libs():
    marker = os.path.join(SHARED_LIBS, '.installed')
    # Check: agar marker hai + core package import ho raha hai → skip
    if os.path.exists(marker):
        try:
            test = subprocess.run(
                [sys.executable, '-c', 'import httpx, Crypto, google_play_scraper'],
                env={**os.environ, 'PYTHONPATH': os.path.abspath(SHARED_LIBS)},
                capture_output=True, timeout=15
            )
            if test.returncode == 0:
                print(f"[libs] ✅ Already installed in {SHARED_LIBS}/")
                return
        except Exception:
            pass

    print(f"[libs] 📦 Installing {len(SHARED_PACKAGES)} packages to {SHARED_LIBS}/ ...")
    cmd = [sys.executable, '-m', 'pip', 'install',
           '--target', os.path.abspath(SHARED_LIBS),
           '--upgrade', '--disable-pip-version-check',
           '--no-warn-conflicts', '--quiet'] + SHARED_PACKAGES
    try:
        subprocess.run(cmd, check=True, timeout=600)
        with open(marker, 'w') as f:
            f.write(str(datetime.now()))
        print("[libs] ✅ Shared libraries installed!")
    except Exception as e:
        print(f"[libs] ⚠️ Install failed: {e}")

# ============================================
# TEMPLATE DEFAULT FILES
# ============================================
def ensure_template_defaults():
    main_py = os.path.join(TEMPLATES_BOT, MAIN_FILE_NAME)
    if not os.path.exists(main_py):
        with open(main_py, 'w', encoding='utf-8') as f:
            f.write('''import time
print("Bot started")
i=0
while True:
    i+=1
    print(f"[{time.strftime('%I:%M:%S %p')}] Heartbeat #{i}")
    time.sleep(5)
''')
    req = os.path.join(TEMPLATES_BOT, 'requirements.txt')
    if not os.path.exists(req):
        with open(req, 'w', encoding='utf-8') as f:
            f.write('\n'.join(SHARED_PACKAGES) + '\n')

# ============================================
# LOAD ACCOUNTS
# ============================================
def load_accounts():
    if not os.path.exists(ACCOUNTS_FILE):
        print(f"[accounts] ❌ {ACCOUNTS_FILE} not found")
        return []
    try:
        with open(ACCOUNTS_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        valid = [a for a in data if a.get('uid') and a.get('password')]
        return valid
    except Exception as e:
        print(f"[accounts] ❌ Load failed: {e}")
        return []

# ============================================
# BOT INSTANCE
# ============================================
class BotInstance:
    def __init__(self, uid, password):
        self.uid = str(uid)
        self.password = str(password)
        self.folder = os.path.join(BOTS_DIR, f"bot_{self.uid}")
        self.log_file = os.path.join(self.folder, 'output.log')
        self.proc = None
        self.started_at = None
        self.stop_flag = False
        self.replaced = False
        self.last_level = 0
        self.last_level_time = time.time()

    # ---------- create folder from template ----------
    def setup_folder(self):
        if os.path.exists(self.folder):
            shutil.rmtree(self.folder, ignore_errors=True)
        os.makedirs(self.folder, exist_ok=True)
        if os.path.exists(TEMPLATES_BOT):
            for item in os.listdir(TEMPLATES_BOT):
                if item.startswith('.'):
                    continue
                src = os.path.join(TEMPLATES_BOT, item)
                dst = os.path.join(self.folder, item)
                if os.path.isdir(src):
                    shutil.copytree(src, dst, dirs_exist_ok=True)
                else:
                    shutil.copy2(src, dst)
        # sirf is uid ka accounts.json
        with open(os.path.join(self.folder, 'accounts.json'), 'w', encoding='utf-8') as f:
            json.dump([{'uid': self.uid, 'password': self.password}],
                      f, indent=2, ensure_ascii=False)

    def log(self, msg):
        line = f"[{datetime.now().strftime('%I:%M:%S %p')}] {msg}"
        try:
            with open(self.log_file, 'a', encoding='utf-8') as f:
                f.write(line + '\n')
                f.flush()
        except Exception:
            pass
        print(f"[{self.uid}] {msg}")

    # ---------- start bot ----------
    def start(self):
        self.setup_folder()
        open(self.log_file, 'w').close()
        self.stop_flag = False
        self.replaced = False
        self.last_level = 0
        self.last_level_time = time.time()
        self.log(f"▶ Starting bot UID={self.uid}")

        # pip install (quiet, fast)
        req_path = os.path.join(self.folder, 'requirements.txt')
        if os.path.exists(req_path):
            try:
                subprocess.run(
                    [sys.executable, '-m', 'pip', 'install', '-r',
                     os.path.abspath(req_path),
                     '--target', os.path.abspath(SHARED_LIBS),
                     '--upgrade', '--disable-pip-version-check',
                     '--no-warn-conflicts', '--quiet'],
                    capture_output=True, timeout=180
                )
            except Exception:
                pass

        env = os.environ.copy()
        env['PYTHONIOENCODING'] = 'utf-8'
        env['PYTHONUNBUFFERED'] = '1'
        env['TERM'] = 'xterm'
        existing = env.get('PYTHONPATH', '')
        env['PYTHONPATH'] = os.path.abspath(SHARED_LIBS) + \
                            (os.pathsep + existing if existing else '')

        main_py = os.path.join(self.folder, MAIN_FILE_NAME)
        if not os.path.exists(main_py):
            self.log(f"❌ {MAIN_FILE_NAME} not found!")
            self.replaced = True   # aage badhne do
            return False

        try:
            self.proc = subprocess.Popen(
                [sys.executable, os.path.abspath(main_py)],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                cwd=self.folder, text=True, encoding='utf-8',
                errors='replace', bufsize=1, env=env,
                start_new_session=True
            )
            self.started_at = datetime.now()
            self.log(f"✅ Started (PID: {self.proc.pid})")
            threading.Thread(target=self._stream_logs, daemon=True).start()
            threading.Thread(target=self._monitor, daemon=True).start()
            return True
        except Exception as e:
            self.log(f"❌ Spawn failed: {e}")
            return False

    # ---------- stream output (keeps log small) ----------
    def _stream_logs(self):
        try:
            line_count = 0
            with open(self.log_file, 'a', encoding='utf-8') as f:
                while True:
                    line = self.proc.stdout.readline()
                    if not line and self.proc.poll() is not None:
                        break
                    if line:
                        line_count += 1
                        # sirf last 500 lines rakho (RAM bachane ke liye)
                        if line_count % 500 == 0:
                            try:
                                with open(self.log_file, 'r', encoding='utf-8', errors='ignore') as r:
                                    all_lines = r.readlines()
                                with open(self.log_file, 'w', encoding='utf-8') as w:
                                    w.writelines(all_lines[-500:])
                            except Exception:
                                pass
                        f.write(f"[{datetime.now().strftime('%I:%M:%S %p')}] {line.rstrip()}\n")
                        f.flush()
                        print(f"[{self.uid}] {line.rstrip()}")
        except Exception:
            pass

    # ---------- level detect (only from latest log) ----------
    def get_current_level(self):
        if not os.path.exists(self.log_file):
            return 0
        level = 0
        exp_re = re.compile(r'Lvl\s+(\d+)')
        try:
            with open(self.log_file, 'r', encoding='utf-8', errors='ignore') as f:
                # last 50 lines hi padho (fast)
                lines = f.readlines()
            for line in lines[-50:]:
                m = exp_re.search(line)
                if m:
                    lvl = int(m.group(1))
                    if lvl > level:
                        level = lvl
        except Exception:
            pass
        return level

    # ---------- monitor ----------
    def _monitor(self):
        while not self.stop_flag:
            time.sleep(CHECK_INTERVAL)

            lvl = self.get_current_level()
            if lvl > self.last_level:
                self.last_level = lvl
                self.last_level_time = time.time()

            # level 12 replace
            if lvl >= TARGET_LEVEL:
                self.log(f"🎯 Level {lvl} reached → replacing!")
                self.replaced = True
                self.stop()
                return

            # crash check
            if self.proc.poll() is not None:
                self.log(f"💥 Process died (exit {self.proc.returncode})")
                # terminal pe error dikhao
                print("\n" + "="*70)
                print(f"❌ BOT {self.uid} CRASHED")
                print("-"*70)
                try:
                    with open(self.log_file, 'r', encoding='utf-8', errors='ignore') as f:
                        for line in f.readlines()[-20:]:
                            print(line.rstrip())
                except Exception:
                    pass
                print("="*70 + "\n")
                if not self.stop_flag and not self.replaced:
                    time.sleep(RESTART_DELAY)
                    if not self.stop_flag:
                        self.start()
                return

            # hang check (10 min me level nahi badha)
            if time.time() - self.last_level_time > HANG_TIMEOUT:
                self.log(f"⏱ No level change in {HANG_TIMEOUT}s → restarting")
                self.stop()
                if not self.stop_flag:
                    time.sleep(RESTART_DELAY)
                    self.start()
                return

    def stop(self):
        self.stop_flag = True
        try:
            if self.proc and self.proc.poll() is None:
                if sys.platform == 'win32':
                    subprocess.run(['taskkill', '/F', '/PID', str(self.proc.pid)],
                                   capture_output=True)
                else:
                    try:
                        os.killpg(os.getpgid(self.proc.pid), signal.SIGTERM)
                    except Exception:
                        self.proc.terminate()
                try:
                    self.proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    try:
                        os.killpg(os.getpgid(self.proc.pid), signal.SIGKILL)
                    except Exception:
                        self.proc.kill()
        except Exception:
            pass

    def is_alive(self):
        return self.proc is not None and self.proc.poll() is None

# ============================================
# MANAGER
# ============================================
class BotManager:
    def __init__(self):
        self.all_accounts = []
        self.used_uids = set()
        self.active_bots = {}
        self.lock = threading.Lock()
        self.account_index = 0

    def get_next_account(self):
        while self.account_index < len(self.all_accounts):
            acc = self.all_accounts[self.account_index]
            self.account_index += 1
            uid = str(acc['uid'])
            if uid not in self.used_uids:
                self.used_uids.add(uid)
                return acc
        return None

    def spawn_new_bot(self):
        acc = self.get_next_account()
        if not acc:
            return None
        uid = str(acc['uid'])
        bot = BotInstance(uid, acc['password'])
        if bot.start():
            self.active_bots[uid] = bot
            print(f"[manager] ✅ Started {uid} ({len(self.active_bots)}/{MAX_ACTIVE})")
            return bot
        return None

    def run(self):
        print("\n" + "=" * 60)
        print("🤖 AUTO BOT MANAGER — Running")
        print("=" * 60)
        print(f"📄 Accounts  : {ACCOUNTS_FILE}")
        print(f"🎯 Target    : Level {TARGET_LEVEL}")
        print(f"📊 Max Active: {MAX_ACTIVE}")
        print("=" * 60 + "\n")

        self.all_accounts = load_accounts()
        print(f"[manager] 📋 Loaded {len(self.all_accounts)} accounts")

        if not self.all_accounts:
            print("[manager] ❌ No accounts found!")
            print("[manager] ℹ Add UID/password to accounts.json and restart.")
            return

        print(f"[manager] 🚀 Launching up to {MAX_ACTIVE} bots...\n")
        for _ in range(min(MAX_ACTIVE, len(self.all_accounts))):
            if not self.spawn_new_bot():
                break
            time.sleep(1.5)

        print(f"\n[manager] ✅ Launched {len(self.active_bots)} bots. Monitoring...\n")

        try:
            while True:
                time.sleep(CHECK_INTERVAL)
                with self.lock:
                    to_remove = []
                    for uid, bot in list(self.active_bots.items()):
                        if bot.replaced:
                            print(f"[manager] 🔄 {uid} replaced")
                            to_remove.append(uid)
                        elif not bot.is_alive() and bot.stop_flag:
                            to_remove.append(uid)
                    for uid in to_remove:
                        self.active_bots.pop(uid, None)
                    while len(self.active_bots) < MAX_ACTIVE:
                        if not self.spawn_new_bot():
                            break
                    print(f"[manager] 📊 Active: {len(self.active_bots)}/{MAX_ACTIVE} | "
                          f"Used: {self.account_index}/{len(self.all_accounts)}")
        except KeyboardInterrupt:
            print("\n[manager] 🛑 Shutting down...")
            for bot in self.active_bots.values():
                bot.stop()
            print("[manager] ✅ Done")

# ============================================
# MAIN
# ============================================
if __name__ == '__main__':
    print("\n" + "="*60)
    print("🚀 JUBAYER HOSTING — Bot Manager Starting")
    print("="*60 + "\n")
    ensure_shared_libs()
    ensure_template_defaults()
    manager = BotManager()
    manager.run()
