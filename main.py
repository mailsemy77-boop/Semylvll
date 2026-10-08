# manager.py — Auto Bot Manager
# 50 servers active rakhta hai, level 12 pe replace karta hai
import os, sys, json, shutil, subprocess, threading, time, re
from datetime import datetime

# ============================================
# CONFIG
# ============================================
ACCOUNTS_FILE  = 'accounts.json'
TEMPLATES_BOT  = 'templates_bot'
BOTS_DIR       = 'bots'
SHARED_LIBS    = 'shared_libs'
MAX_ACTIVE     = 40              # ek time pe max 50 servers
TARGET_LEVEL   = 12              # jab level 12 ho jaye -> replace
CHECK_INTERVAL = 15              # har 15 sec check karo
RESTART_DELAY  = 3               # crash pe 3 sec baad restart

# ============================================
# SETUP FOLDERS
# ============================================
os.makedirs(BOTS_DIR, exist_ok=True)
os.makedirs(SHARED_LIBS, exist_ok=True)
os.makedirs(TEMPLATES_BOT, exist_ok=True)

# ============================================
# SHARED LIBS — ek baar install
# ============================================
SHARED_PACKAGES = [
    'httpx',
    'google-play-scraper',
    'pycryptodome',
    'protobuf',
    'protobuf-decoder',
]

def ensure_shared_libs():
    marker = os.path.join(SHARED_LIBS, '.installed')
    if os.path.exists(marker):
        print("[libs] ✅ Already installed")
        return
    print(f"[libs] 📦 Installing {len(SHARED_PACKAGES)} packages...")
    cmd = [sys.executable, '-m', 'pip', 'install',
           '--target', os.path.abspath(SHARED_LIBS),
           '--upgrade', '--disable-pip-version-check'] + SHARED_PACKAGES
    try:
        subprocess.run(cmd, check=True)
        open(marker, 'w').write(str(datetime.now()))
        print("[libs] ✅ Installed")
    except Exception as e:
        print(f"[libs] ⚠️ Failed: {e}")

# ============================================
# TEMPLATE DEFAULTS
# ============================================
def ensure_template_defaults():
    main_py = os.path.join(TEMPLATES_BOT, 'main.py')
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
# ACCOUNTS QUEUE
# ============================================
def load_accounts():
    if not os.path.exists(ACCOUNTS_FILE):
        return []
    try:
        with open(ACCOUNTS_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return [a for a in data if a.get('uid') and a.get('password')]
    except Exception as e:
        print(f"[accounts] ❌ Load failed: {e}")
        return []

# ============================================
# BOT CLASS
# ============================================
class BotInstance:
    def __init__(self, uid, password):
        self.uid = str(uid)
        self.password = str(password)
        self.folder = os.path.join(BOTS_DIR, f"bot_{self.uid}")
        self.log_file = os.path.join(self.folder, 'output.log')
        self.proc = None
        self.started_at = None
        self.thread = None
        self.stop_flag = False
        self.replaced = False   # jab level 12 pe replace ho chuka

    # ---------- create folder from template ----------
    def setup_folder(self):
        # purana folder delete karo (agar hai)
        if os.path.exists(self.folder):
            shutil.rmtree(self.folder, ignore_errors=True)
        os.makedirs(self.folder, exist_ok=True)

        # template se copy karo
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

        # is UID ka accounts.json banao
        acc_file = os.path.join(self.folder, 'accounts.json')
        with open(acc_file, 'w', encoding='utf-8') as f:
            json.dump([{
                'uid': self.uid,
                'password': self.password
            }], f, indent=2, ensure_ascii=False)

    # ---------- log helper ----------
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
        self.log(f"Starting bot UID={self.uid}")

        # pip install requirements
        req_path = os.path.join(self.folder, 'requirements.txt')
        if os.path.exists(req_path):
            try:
                subprocess.run(
                    [sys.executable, '-m', 'pip', 'install', '-r',
                     os.path.abspath(req_path),
                     '--target', os.path.abspath(SHARED_LIBS),
                     '--upgrade', '--disable-pip-version-check',
                     '--quiet'],
                    capture_output=True, timeout=300
                )
            except Exception as e:
                self.log(f"pip error: {e}")

        # env setup
        env = os.environ.copy()
        env['PYTHONIOENCODING'] = 'utf-8'
        env['PYTHONUNBUFFERED'] = '1'
        env['TERM'] = 'xterm'
        existing = env.get('PYTHONPATH', '')
        env['PYTHONPATH'] = os.path.abspath(SHARED_LIBS) + \
                            (os.pathsep + existing if existing else '')

        # main.py path
        main_py = os.path.join(self.folder, 'main.py')
        if not os.path.exists(main_py):
            self.log(f"❌ main.py not found")
            return False

        # spawn process
        try:
            self.proc = subprocess.Popen(
                [sys.executable, os.path.abspath(main_py)],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                cwd=self.folder, text=True, encoding='utf-8',
                errors='replace', bufsize=1, env=env
            )
            self.started_at = datetime.now()
            self.log(f"✅ Started (PID: {self.proc.pid})")

            # stream logs thread
            threading.Thread(target=self._stream_logs, daemon=True).start()
            # monitor thread (level 12 check + crash restart)
            threading.Thread(target=self._monitor, daemon=True).start()
            return True
        except Exception as e:
            self.log(f"❌ Spawn failed: {e}")
            return False

    # ---------- stream logs ----------
    def _stream_logs(self):
        try:
            with open(self.log_file, 'a', encoding='utf-8') as f:
                while True:
                    line = self.proc.stdout.readline()
                    if not line and self.proc.poll() is not None:
                        break
                    if line:
                        f.write(f"[{datetime.now().strftime('%I:%M:%S %p')}] {line.rstrip()}\n")
                        f.flush()
        except Exception:
            pass

    # ---------- current level from log ----------
    def get_current_level(self):
        if not os.path.exists(self.log_file):
            return 0
        level = 0
        exp_re = re.compile(r'Lvl\s+(\d+)')
        try:
            with open(self.log_file, 'r', encoding='utf-8', errors='ignore') as f:
                for line in f:
                    m = exp_re.search(line)
                    if m:
                        lvl = int(m.group(1))
                        if lvl > level:
                            level = lvl
        except Exception:
            pass
        return level

    # ---------- monitor: level check + restart ----------
    def _monitor(self):
        while not self.stop_flag:
            time.sleep(CHECK_INTERVAL)

            # level 12 check
            lvl = self.get_current_level()
            if lvl >= TARGET_LEVEL:
                self.log(f"🎯 Level {lvl} reached → replacing!")
                self.replaced = True
                self.stop()
                return

            # crash check
            if self.proc.poll() is not None:
                self.log(f"💥 Process died (exit {self.proc.returncode})")
                # restart (agar user ne stop nahi kiya aur level 12 nahi aaya)
                if not self.stop_flag and not self.replaced:
                    time.sleep(RESTART_DELAY)
                    if not self.stop_flag:
                        self.start()
                return

    # ---------- stop bot ----------
    def stop(self):
        self.stop_flag = True
        try:
            if self.proc and self.proc.poll() is None:
                self.proc.terminate()
                try:
                    self.proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.proc.kill()
        except Exception:
            pass
        self.log("⛔ Stopped")

    # ---------- is process alive? ----------
    def is_alive(self):
        return self.proc is not None and self.proc.poll() is None


# ============================================
# MANAGER
# ============================================
class BotManager:
    def __init__(self):
        self.all_accounts = []      # saare accounts
        self.used_uids = set()      # jo use ho chuke
        self.active_bots = {}       # uid -> BotInstance
        self.lock = threading.Lock()

    def get_next_account(self):
        """Agla unused account do."""
        for acc in self.all_accounts:
            uid = str(acc['uid'])
            if uid not in self.used_uids:
                self.used_uids.add(uid)
                return acc
        return None

    def spawn_new_bot(self):
        """Naya bot start karo (agla unused account)."""
        acc = self.get_next_account()
        if not acc:
            print("[manager] ⚠️ No more accounts left!")
            return None
        uid = str(acc['uid'])
        bot = BotInstance(uid, acc['password'])
        if bot.start():
            self.active_bots[uid] = bot
            print(f"[manager] ✅ Started bot {uid} ({len(self.active_bots)}/{MAX_ACTIVE})")
            return bot
        return None

    def run(self):
        print("\n" + "=" * 55)
        print("🤖 AUTO BOT MANAGER")
        print("=" * 55)
        print(f"📄 Accounts file  : {ACCOUNTS_FILE}")
        print(f"🎯 Target Level   : {TARGET_LEVEL}")
        print(f"📊 Max Active     : {MAX_ACTIVE}")
        print(f"⏱  Check interval : {CHECK_INTERVAL}s")
        print("=" * 55 + "\n")

        self.all_accounts = load_accounts()
        print(f"[manager] 📋 Loaded {len(self.all_accounts)} accounts")

        if not self.all_accounts:
            print("[manager] ❌ No accounts found. Add some to accounts.json")
            return

        # initial bots spawn karo (up to MAX_ACTIVE)
        print(f"[manager] 🚀 Starting up to {MAX_ACTIVE} bots...")
        for _ in range(min(MAX_ACTIVE, len(self.all_accounts))):
            if not self.spawn_new_bot():
                break
            time.sleep(1)

        # main loop
        try:
            while True:
                time.sleep(CHECK_INTERVAL)

                with self.lock:
                    # dead / replaced bots hatao
                    to_remove = []
                    for uid, bot in list(self.active_bots.items()):
                        if bot.replaced:
                            print(f"[manager] 🔄 {uid} replaced (Lvl {TARGET_LEVEL})")
                            to_remove.append(uid)
                        elif not bot.is_alive() and bot.stop_flag:
                            to_remove.append(uid)

                    for uid in to_remove:
                        self.active_bots.pop(uid, None)

                    # naye bots spawn karo jab tak MAX_ACTIVE na ho
                    while len(self.active_bots) < MAX_ACTIVE:
                        new_bot = self.spawn_new_bot()
                        if not new_bot:
                            break

                    # status print
                    print(f"[manager] 📊 Active: {len(self.active_bots)}/{MAX_ACTIVE} | "
                          f"Used accounts: {len(self.used_uids)}/{len(self.all_accounts)}")

        except KeyboardInterrupt:
            print("\n[manager] 🛑 Shutting down...")
            for bot in self.active_bots.values():
                bot.stop()
            print("[manager] ✅ All bots stopped")


# ============================================
# MAIN
# ============================================
if __name__ == '__main__':
    ensure_shared_libs()
    ensure_template_defaults()
    manager = BotManager()
    manager.run()