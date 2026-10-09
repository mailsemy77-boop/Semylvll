# main.py — AUTO BOT MANAGER (Clean Output Version)
import os, sys, json, shutil, subprocess, threading, time, re, signal
from datetime import datetime

# ============================================
# CONFIG
# ============================================
ACCOUNTS_FILE   = 'accounts.json'
TEMPLATES_BOT   = 'templates_bot'
BOTS_DIR        = 'bots'
MAIN_FILE_NAME  = 'main.py'

MAX_ACTIVE      = 40
TARGET_LEVEL    = 12
CHECK_INTERVAL  = 20
RESTART_DELAY   = 5
HANG_TIMEOUT    = 600

os.makedirs(BOTS_DIR, exist_ok=True)
os.makedirs(TEMPLATES_BOT, exist_ok=True)

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
        return [a for a in data if a.get('uid') and a.get('password')]
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
        self.stop_flag = False
        self.replaced = False
        self.last_level = 0
        self.last_level_time = time.time()

    def setup_folder(self):
        if os.path.exists(self.folder):
            shutil.rmtree(self.folder, ignore_errors=True)
        os.makedirs(self.folder, exist_ok=True)
        if os.path.exists(TEMPLATES_BOT):
            for item in os.listdir(TEMPLATES_BOT):
                if item.startswith('.'): continue
                src = os.path.join(TEMPLATES_BOT, item)
                dst = os.path.join(self.folder, item)
                if os.path.isdir(src):
                    shutil.copytree(src, dst, dirs_exist_ok=True)
                else:
                    shutil.copy2(src, dst)
        with open(os.path.join(self.folder, 'accounts.json'), 'w', encoding='utf-8') as f:
            json.dump([{'uid': self.uid, 'password': self.password}], f, indent=2, ensure_ascii=False)

    def log(self, msg):
        line = f"[{datetime.now().strftime('%I:%M:%S %p')}] {msg}"
        try:
            with open(self.log_file, 'a', encoding='utf-8') as f:
                f.write(line + '\n'); f.flush()
        except Exception: pass
        print(f"[{self.uid}] {msg}")

    def start(self):
        self.setup_folder()
        open(self.log_file, 'w').close()
        self.stop_flag = False
        self.replaced = False
        self.last_level = 0
        self.last_level_time = time.time()

        env = os.environ.copy()
        env['PYTHONIOENCODING'] = 'utf-8'
        env['PYTHONUNBUFFERED'] = '1'
        env['TERM'] = 'xterm'

        main_py = os.path.join(self.folder, MAIN_FILE_NAME)
        if not os.path.exists(main_py):
            self.log(f"❌ {MAIN_FILE_NAME} not found!")
            self.replaced = True
            return False
        try:
            self.proc = subprocess.Popen(
                [sys.executable, os.path.abspath(main_py)],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                cwd=self.folder, text=True, encoding='utf-8',
                errors='replace', bufsize=1, env=env, start_new_session=True)
            threading.Thread(target=self._stream_logs, daemon=True).start()
            threading.Thread(target=self._monitor, daemon=True).start()
            return True
        except Exception as e:
            self.log(f"❌ Spawn failed: {e}")
            return False

    # ---------- sirf [PROFILE] tak terminal pe print ----------
    def _stream_logs(self):
        try:
            with open(self.log_file, 'a', encoding='utf-8') as f:
                profile_done = False
                while True:
                    line = self.proc.stdout.readline()
                    if not line and self.proc.poll() is not None:
                        break
                    if line:
                        # log file me poora save karo
                        f.write(f"[{datetime.now().strftime('%I:%M:%S %p')}] {line.rstrip()}\n")
                        f.flush()

                        # terminal pe sirf [PROFILE] tak dikhao
                        if not profile_done:
                            print(f"[{self.uid}] {line.rstrip()}")
                            if '[PROFILE]' in line:
                                profile_done = True
                                print()
        except Exception:
            pass

    def get_current_level(self):
        if not os.path.exists(self.log_file): return 0
        level = 0
        exp_re = re.compile(r'Lvl\s+(\d+)')
        try:
            with open(self.log_file, 'r', encoding='utf-8', errors='ignore') as f:
                lines = f.readlines()
            for line in lines[-50:]:
                m = exp_re.search(line)
                if m:
                    lvl = int(m.group(1))
                    if lvl > level: level = lvl
        except Exception: pass
        return level

    def _monitor(self):
        while not self.stop_flag:
            time.sleep(CHECK_INTERVAL)
            lvl = self.get_current_level()
            if lvl > self.last_level:
                self.last_level = lvl
                self.last_level_time = time.time()
            if lvl >= TARGET_LEVEL:
                self.log(f"🎯 Level {lvl} reached → replacing!")
                self.replaced = True
                self.stop()
                return
            if self.proc.poll() is not None:
                self.log(f"💥 Process died (exit {self.proc.returncode})")
                # 👇 crash pe poora error terminal pe
                print("\n" + "="*70)
                print(f"❌ BOT {self.uid} CRASHED")
                print("-"*70)
                try:
                    with open(self.log_file, 'r', encoding='utf-8', errors='ignore') as f:
                        for line in f.readlines()[-20:]:
                            print(f"[{self.uid}] {line.rstrip()}")
                except Exception: pass
                print("="*70 + "\n")
                if not self.stop_flag and not self.replaced:
                    time.sleep(RESTART_DELAY)
                    if not self.stop_flag: self.start()
                return
            if time.time() - self.last_level_time > HANG_TIMEOUT:
                self.log(f"⏱ No level change → restart")
                self.stop()
                if not self.stop_flag:
                    time.sleep(RESTART_DELAY)
                    self.start()
                return

    def stop(self):
        self.stop_flag = True
        try:
            if self.proc and self.proc.poll() is None:
                try: os.killpg(os.getpgid(self.proc.pid), signal.SIGTERM)
                except Exception: self.proc.terminate()
                try: self.proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    try: os.killpg(os.getpgid(self.proc.pid), signal.SIGKILL)
                    except Exception: self.proc.kill()
        except Exception: pass

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
        if not acc: return None
        uid = str(acc['uid'])
        bot = BotInstance(uid, acc['password'])
        if bot.start():
            self.active_bots[uid] = bot
            return bot
        return None

    def run(self):
        print("\n" + "=" * 60)
        print("🤖 AUTO BOT MANAGER")
        print("=" * 60)
        print(f"📄 Accounts  : {ACCOUNTS_FILE}")
        print(f"🎯 Target    : Level {TARGET_LEVEL}")
        print(f"📊 Max Active: {MAX_ACTIVE}")
        print("=" * 60 + "\n")

        self.all_accounts = load_accounts()
        print(f"[manager] 📋 Loaded {len(self.all_accounts)} accounts\n")
        if not self.all_accounts:
            print("[manager] ❌ No accounts found!")
            return

        print(f"[manager] 🚀 Launching up to {MAX_ACTIVE} bots...\n")

        for i in range(min(MAX_ACTIVE, len(self.all_accounts))):
            acc = self.get_next_account()
            if not acc: break
            uid = str(acc['uid'])
            bot = BotInstance(uid, acc['password'])
            if bot.start():
                self.active_bots[uid] = bot
                # 👇 agla bot start karne se pehle thoda wait (PROFILE line aane do)
                time.sleep(6)

        print(f"\n[manager] ✅ Launched {len(self.active_bots)} bots.\n")

        try:
            while True:
                time.sleep(CHECK_INTERVAL)
                with self.lock:
                    to_remove = []
                    for uid, bot in list(self.active_bots.items()):
                        if bot.replaced or (not bot.is_alive() and bot.stop_flag):
                            to_remove.append(uid)
                    for uid in to_remove:
                        self.active_bots.pop(uid, None)
                    while len(self.active_bots) < MAX_ACTIVE:
                        if not self.spawn_new_bot(): break
                        time.sleep(6)   # PROFILE line ka wait
                    print(f"[manager] 📊 Active: {len(self.active_bots)}/{MAX_ACTIVE} | Used: {self.account_index}/{len(self.all_accounts)}")
        except KeyboardInterrupt:
            print("\n[manager] 🛑 Shutting down...")
            for bot in self.active_bots.values(): bot.stop()
            print("[manager] ✅ Done")

if __name__ == '__main__':
    print("\n🚀 JUBAYER HOSTING — Bot Manager\n")
    BotManager().run()
