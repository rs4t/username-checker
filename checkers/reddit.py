import sys
import requests
import random
import string
import traceback
import threading
import time
from PyQt5.QtWidgets import *
from PyQt5.QtCore import *
from PyQt5.QtGui import QFont

WORDLIST_OPTIONS = [
    ("20k (All Words)", "https://github.com/first20hours/google-10000-english/blob/master/20k.txt"),
    ("10k No Swears - Medium", "https://github.com/first20hours/google-10000-english/blob/master/google-10000-english-usa-no-swears-medium.txt"),
    ("10k No Swears - Short", "https://github.com/first20hours/google-10000-english/blob/master/google-10000-english-usa-no-swears-short.txt"),
    ("10k No Swears", "https://github.com/first20hours/google-10000-english/blob/master/google-10000-english-usa-no-swears.txt"),
    ("10k Total Words", "https://github.com/first20hours/google-10000-english/blob/master/google-10000-english-usa.txt"),
    ("Adjectives", "https://gist.githubusercontent.com/hugsy/8910dc78d208e40de42deb29e62df913/raw/eec99c5597a73f6a9240cab26965a8609fa0f6ea/english-adjectives.txt")
]
TOTAL_WORDLIST_SOURCE = "https://github.com/first20hours/google-10000-english/blob/master/google-10000-english-usa.txt"
REDDIT_MIN_USERNAME_LENGTH = 3

# ------------------- Checker Thread ------------------- #
class Checker(QThread):
    update = pyqtSignal(str)
    pupdate = pyqtSignal(int)
    count = 0

    def __init__(self, usernames, webhook_url=None, debug=False, save_to_file=True, proxies=None):
        super().__init__()
        self.usernames = usernames
        self.webhook_url = webhook_url
        self.running = True
        self.debug = debug
        self.save_to_file = save_to_file
        self.consecutive_errors = 0
        self.request_delay = 0.2  # initial delay between requests (faster)
        self.min_delay = 0.01     # minimum allowed delay (ultra fast)
        self.rate_lock = threading.Lock()
        self.last_request_time = 0
        self.proxies = proxies or []
        self.proxy_index = 0
        self.proxy_lock = threading.Lock()
        self.thread_local = threading.local()

    def run(self):
        from concurrent.futures import ThreadPoolExecutor
        self.count_lock = threading.Lock()
        max_workers = 5
        rate_limited_usernames = []
        def worker(username):
            if not self.running:
                return
            result = self.check_username(username, rate_limited_usernames)
            with self.count_lock:
                self.count += 1
                self.pupdate.emit(self.count)
            return result
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            for username in self.usernames:
                executor.submit(worker, username)

        # Pause before retrying rate-limited usernames
        if rate_limited_usernames:
            self.update.emit(f"\n⏳ Waiting 30 seconds before retrying {len(rate_limited_usernames)} rate-limited usernames...")
            time.sleep(30)
            self.count_lock.acquire()
            self.count = 0
            self.count_lock.release()
            def retry_worker(username):
                if not self.running:
                    return
                result = self.check_username(username)
                with self.count_lock:
                    self.count += 1
                    self.pupdate.emit(self.count)
                return result
            with ThreadPoolExecutor(max_workers=3) as executor:
                for username in rate_limited_usernames:
                    executor.submit(retry_worker, username)

    def stop(self):
        self.running = False

    def get_session(self, proxy=None):
        if not hasattr(self.thread_local, 'session') or self.thread_local.session_proxy != proxy:
            session = requests.Session()
            session.headers.update({
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'application/json, text/javascript, */*; q=0.01',
                'Accept-Language': 'en-US,en;q=0.9',
                'Accept-Encoding': 'gzip, deflate, br',
                'Referer': 'https://old.reddit.com/',
                'Connection': 'keep-alive',
            })
            if proxy:
                session.proxies = {'http': proxy, 'https': proxy}
            self.thread_local.session = session
            self.thread_local.session_proxy = proxy
        return self.thread_local.session

    def get_next_proxy(self):
        if not self.proxies:
            return None
        with self.proxy_lock:
            proxy = self.proxies[self.proxy_index]
            self.proxy_index = (self.proxy_index + 1) % len(self.proxies)
        return proxy

    def confirm_username_available(self, session, username):
        confirm_url = f"https://www.reddit.com/api/username_available.json?user={username}"
        try:
            response = session.get(confirm_url, timeout=10)
            body = response.text.strip().lower()
            if self.debug:
                self.update.emit(f"[DEBUG] Confirm URL: {confirm_url}")
                self.update.emit(f"[DEBUG] Confirm Status: {response.status_code}")
                self.update.emit(f"[DEBUG] Confirm Body: {response.text[:120]}")
            if response.status_code == 200:
                if body == "true":
                    return True, "confirmed available"
                if body == "false":
                    return False, "reported unavailable"
                return None, f"unexpected response body: {response.text[:80]}"
            if response.status_code == 429:
                return None, "confirmation endpoint rate limited"
            if response.status_code == 403:
                return None, "confirmation endpoint blocked by Cloudflare"
            return None, f"confirmation endpoint status {response.status_code}"
        except Exception as e:
            return None, f"confirmation failed: {str(e)[:80]}"

    def check_username(self, username, rate_limited_usernames=None):
        if not self.running:
            return
        retries = 0
        max_retries = 2
        while retries <= max_retries:
            if not self.running:
                return
            # Global request limiter
            with self.rate_lock:
                now = time.time()
                wait = self.request_delay - (now - self.last_request_time)
                if wait > 0:
                    time.sleep(wait)
                self.last_request_time = time.time()
            # Random jitter
            time.sleep(random.uniform(0.02, 0.08))
            try:
                url = f"https://old.reddit.com/user/{username}/about.json"
                webhook_desc = f"`{username}` [is available for **Reddit**!](https://www.reddit.com/user/{username})"
                webhook_color = 0xFF4500
                save_file = "available_reddit_usernames.txt"
                proxy = self.get_next_proxy()
                if self.debug and proxy:
                    self.update.emit(f"[DEBUG] Using proxy: {proxy}")
                session = self.get_session(proxy)
                response = session.get(url, timeout=10)
                if self.debug:
                    self.update.emit(f"\n{'='*60}")
                    self.update.emit(f"[DEBUG] Checking: {username}")
                    self.update.emit(f"[DEBUG] URL: {url}")
                    self.update.emit(f"[DEBUG] Status Code: {response.status_code}")
                    self.update.emit(f"[DEBUG] Response: {response.text[:200]}")
                if response.status_code == 200:
                    profile_text = response.text.lower()
                    profile_data = {}
                    try:
                        profile_data = response.json().get("data", {})
                    except Exception:
                        profile_data = {}

                    if "this user has deleted their account" in profile_text or profile_data.get("name", "").lower() == "[deleted]":
                        self.update.emit(f"⚠️ [UNCLAIMABLE] {username}: Account was deleted")
                    elif profile_data.get("is_suspended") is True:
                        self.update.emit(f"🚫 [BANNED] {username}")
                    else:
                        self.update.emit(f"❌ [TAKEN] {username}")
                    self.consecutive_errors = 0
                    if self.request_delay > 0.2:
                        self.request_delay = max(self.min_delay, self.request_delay * 0.9)
                    return
                elif response.status_code == 404:
                    # 404 can be fake-available due to deleted/suspended edge cases.
                    # Confirm using Reddit's availability endpoint before marking available.
                    is_available, reason = self.confirm_username_available(session, username)
                    if is_available is True:
                        self.update.emit(f"✅ [AVAILABLE] {username}")
                        self.consecutive_errors = 0
                        if self.save_to_file:
                            try:
                                with open(save_file, "a") as f:
                                    f.write(f"{username}\n")
                            except Exception as e:
                                if self.debug:
                                    self.update.emit(f"[DEBUG] Failed to save to file: {e}")
                        if self.webhook_url:
                            self.send_to_discord(username, webhook_desc, webhook_color)
                        if self.request_delay > 0.2:
                            self.request_delay = max(self.min_delay, self.request_delay * 0.9)
                        return
                    if is_available is False:
                        self.update.emit(f"⚠️ [UNCLAIMABLE] {username}: {reason}")
                        self.consecutive_errors = 0
                        return

                    self.update.emit(f"⚠️ [UNCLEAR] {username}: {reason}")
                    self.consecutive_errors += 1
                    retries += 1
                elif response.status_code == 429:
                    self.update.emit(f"⚠️ [RATE LIMIT] {username}: Reddit is rate limiting! Skipping for now.")
                    self.request_delay = min(10, self.request_delay * 1.7)
                    if rate_limited_usernames is not None:
                        rate_limited_usernames.append(username)
                    return
                elif response.status_code == 403:
                    # Cloudflare challenge (HTML) or Reddit block — force new session next time
                    self.thread_local.session = None if hasattr(self.thread_local, 'session') else None
                    if hasattr(self.thread_local, 'session'):
                        del self.thread_local.session
                    is_cloudflare = '<html' in response.text[:100].lower() or '<body' in response.text[:100].lower()
                    self.update.emit(f"⚠️ [BLOCKED] {username}: {'Cloudflare challenge' if is_cloudflare else 'Reddit blocked the request!'}")
                    self.consecutive_errors += 1
                    self.request_delay = min(10, self.request_delay * 1.7)
                    time.sleep(5)
                    retries += 1
                else:
                    self.update.emit(f"⚠️ [UNKNOWN] {username}: Status {response.status_code}")
                    self.consecutive_errors += 1
                    retries += 1
            except requests.exceptions.ProxyError as e:
                self.consecutive_errors += 1
                self.update.emit(f"⚠️ [PROXY ERROR] {username}: {str(e)[:80]}")
                retries += 1
            except requests.exceptions.Timeout:
                self.consecutive_errors += 1
                self.update.emit(f"⏱️ [TIMEOUT] {username} (retry {retries+1})")
                sleep_time = min(30, 2 ** self.consecutive_errors)
                time.sleep(sleep_time)
                retries += 1
            except Exception as e:
                self.consecutive_errors += 1
                if self.debug:
                    error_msg = traceback.format_exc()
                    self.update.emit(f"⚠️ [ERROR] {username}:\n{error_msg}")
                else:
                    error_msg = str(e)
                    self.update.emit(f"⚠️ [ERROR] {username}: {error_msg}")
                retries += 1
        self.update.emit(f"❌ [FAILED] {username} after {max_retries+1} attempts")

    def send_to_discord(self, username, desc, color):
        try:
            webhook_data = {
                "content": "",
                "tts": False,
                "embeds": [
                    {
                        "id": 487189062,
                        "description": desc,
                        "color": color,
                        "fields": []
                    }
                ],
                "components": [],
                "actions": {},
                "flags": 0
            }
            response = requests.post(self.webhook_url, json=webhook_data, timeout=5)
            if response.status_code == 204:
                if self.debug:
                    self.update.emit(f"[DEBUG] ✅ Sent {username} to Discord webhook")
            else:
                if self.debug:
                    self.update.emit(f"[DEBUG] ⚠️ Webhook failed: Status {response.status_code}")
        except Exception as e:
            if self.debug:
                self.update.emit(f"[DEBUG] ⚠️ Webhook error: {str(e)}")

# ------------------- GUI App ------------------- #
class App(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Reddit Username Checker")
        self.setGeometry(150, 150, 1100, 800)
        self.thread = None
        self.cached_words = {}
        self.initUI()

    def initUI(self):
        wid = QWidget(self)
        self.setCentralWidget(wid)
        main_layout = QVBoxLayout()
        wid.setLayout(main_layout)

        # Title
        self.title = QLabel()
        self.title_font = QFont()
        self.title_font.setPointSize(16)
        self.title_font.setBold(True)
        self.title.setFont(self.title_font)
        main_layout.addWidget(self.title)

        # Info Section
        self.info_group = QGroupBox()
        self.info_group.setStyleSheet("QGroupBox { font-weight: bold; }")
        self.info_layout = QVBoxLayout()
        self.instruction = QLabel()
        self.instruction.setWordWrap(True)
        self.instruction.setStyleSheet("background-color: #ff4500; padding: 10px; border-radius: 3px; color: white;")
        self.info_layout.addWidget(self.instruction)
        self.info_group.setLayout(self.info_layout)
        main_layout.addWidget(self.info_group)

        # Webhook Section
        webhook_group = QGroupBox("🔔 Discord Webhook (Optional)")
        webhook_group.setStyleSheet("QGroupBox { font-weight: bold; }")
        webhook_layout = QVBoxLayout()
        webhook_info = QLabel("💬 Get notified when available usernames are found!")
        webhook_info.setWordWrap(True)
        webhook_info.setStyleSheet("background-color: #ffe5d5; padding: 8px; border-radius: 3px; color: #ff4500;")
        webhook_layout.addWidget(webhook_info)
        webhook_input_layout = QHBoxLayout()
        self.webhook_input = QLineEdit()
        self.webhook_input.setPlaceholderText("https://discord.com/api/webhooks/...")
        webhook_input_layout.addWidget(self.webhook_input)
        test_webhook_btn = QPushButton("🧪 Test")
        test_webhook_btn.setMaximumWidth(80)
        test_webhook_btn.clicked.connect(self.test_webhook)
        webhook_input_layout.addWidget(test_webhook_btn)
        webhook_layout.addLayout(webhook_input_layout)
        webhook_group.setLayout(webhook_layout)
        main_layout.addWidget(webhook_group)

        # Proxy Section
        proxy_group = QGroupBox("🌐 Proxies (Optional)")
        proxy_group.setStyleSheet("QGroupBox { font-weight: bold; }")
        proxy_layout = QVBoxLayout()
        proxy_info = QLabel("Format: http://ip:port  or  http://user:pass@ip:port  or  socks5://ip:port  (one per line)")
        proxy_info.setWordWrap(True)
        proxy_info.setStyleSheet("background-color: #d1ecf1; padding: 6px; border-radius: 3px; color: #0c5460;")
        proxy_layout.addWidget(proxy_info)
        proxy_row = QHBoxLayout()
        self.proxy_input = QTextEdit()
        self.proxy_input.setPlaceholderText("http://proxy1.com:8080\nhttp://user:pass@proxy2.com:8080\nsocks5://proxy3.com:1080")
        self.proxy_input.setMaximumHeight(75)
        proxy_row.addWidget(self.proxy_input)
        proxy_btns = QVBoxLayout()
        load_proxy_btn = QPushButton("Load File")
        load_proxy_btn.clicked.connect(self.load_proxies_from_file)
        proxy_btns.addWidget(load_proxy_btn)
        clr_proxy_btn = QPushButton("Clear")
        clr_proxy_btn.clicked.connect(lambda: self.proxy_input.clear())
        proxy_btns.addWidget(clr_proxy_btn)
        proxy_btns.addStretch()
        proxy_row.addLayout(proxy_btns)
        proxy_layout.addLayout(proxy_row)
        self.proxy_count_label = QLabel("Proxies loaded: 0")
        self.proxy_count_label.setStyleSheet("font-style: italic; color: #555;")
        proxy_layout.addWidget(self.proxy_count_label)
        proxy_group.setLayout(proxy_layout)
        main_layout.addWidget(proxy_group)

        # Generator Section
        gen_group = QGroupBox()
        gen_group.setStyleSheet("QGroupBox { font-weight: bold; }")
        gen_layout = QVBoxLayout()
        header_row = QHBoxLayout()
        header_label = QLabel("Step 1: Generate Usernames (Optional)")
        header_label.setStyleSheet("font-weight: bold;")
        header_row.addWidget(header_label)
        self.generator_mode_switch = QCheckBox("Words Mode")
        self.generator_mode_switch.setToolTip("Off = Random mode, On = Words mode")
        header_row.addWidget(self.generator_mode_switch)
        header_row.addStretch()
        gen_layout.addLayout(header_row)
        row1 = QHBoxLayout()
        self.length_label = QLabel("Length:")
        row1.addWidget(self.length_label)
        self.length_input = QLineEdit("3")
        self.length_input.setMaximumWidth(60)
        row1.addWidget(self.length_input)
        self.max_length_label = QLabel("Max Length:")
        row1.addWidget(self.max_length_label)
        self.max_length_input = QLineEdit("8")
        self.max_length_input.setMaximumWidth(60)
        row1.addWidget(self.max_length_input)
        row1.addWidget(QLabel("Prefix:"))
        self.prefix_input = QLineEdit()
        self.prefix_input.setPlaceholderText("e.g., reddit")
        self.prefix_input.setMaximumWidth(100)
        row1.addWidget(self.prefix_input)
        row1.addWidget(QLabel("Suffix:"))
        self.suffix_input = QLineEdit()
        self.suffix_input.setPlaceholderText("e.g., pro")
        self.suffix_input.setMaximumWidth(100)
        row1.addWidget(self.suffix_input)
        row1.addWidget(QLabel("Count:"))
        self.count_input = QLineEdit("10")
        self.count_input.setMaximumWidth(60)
        row1.addWidget(self.count_input)
        row1.addStretch()
        gen_layout.addLayout(row1)
        row2 = QHBoxLayout()
        self.pattern_label = QLabel("Pattern:")
        row2.addWidget(self.pattern_label)
        self.pattern_combo = QComboBox()
        self.pattern_combo.addItems([
            "Letters only (abc)",
            "Letters + Numbers (a1b2)",
            "Doubles (suuv, my55)",
            "Triples (aaab, t777)",
            "Vowels only (aeiou)",
            "One line letters (aceimnorsuvwxz)"
        ])
        self.pattern_combo.setMaximumWidth(200)
        row2.addWidget(self.pattern_combo)
        self.word_source_label = QLabel("Word List:")
        row2.addWidget(self.word_source_label)
        self.word_source_combo = QComboBox()
        for label, source in WORDLIST_OPTIONS:
            self.word_source_combo.addItem(label, source)
        self.word_source_combo.setMaximumWidth(230)
        row2.addWidget(self.word_source_combo)
        self.word_pick_label = QLabel("Word Pick:")
        row2.addWidget(self.word_pick_label)
        self.word_pick_combo = QComboBox()
        self.word_pick_combo.addItems([
            "Random",
            "From Top"
        ])
        self.word_pick_combo.setMaximumWidth(110)
        row2.addWidget(self.word_pick_combo)
        self.gen_button = QPushButton("🎲 Generate")
        self.gen_button.clicked.connect(self.generate_usernames)
        self.gen_button.setStyleSheet("background-color: #ff4500; color: white; padding: 8px; font-weight: bold;")
        row2.addWidget(self.gen_button)
        self.debug_checkbox = QCheckBox("🐛 Debug Mode (Detailed)")
        self.debug_checkbox.setToolTip("Show detailed responses")
        row2.addWidget(self.debug_checkbox)
        self.save_checkbox = QCheckBox("💾 Save to File")
        self.save_checkbox.setChecked(True)
        self.save_checkbox.setToolTip("Save available usernames to file")
        row2.addWidget(self.save_checkbox)
        row2.addStretch()
        gen_layout.addLayout(row2)
        gen_group.setLayout(gen_layout)
        main_layout.addWidget(gen_group)

        # Input/Output Section
        io_group = QGroupBox("Step 2: Check Usernames")
        io_group.setStyleSheet("QGroupBox { font-weight: bold; }")
        io_layout = QHBoxLayout()
        input_box = QVBoxLayout()
        input_label = QLabel("📝 Usernames to Check:")
        input_label.setStyleSheet("font-weight: bold;")
        input_box.addWidget(input_label)
        self.input_text = QTextEdit()
        self.input_text.setPlaceholderText("Enter usernames here\n(one per line)\n\nExample:\nabc\nxyz\nredditpro123")
        input_box.addWidget(self.input_text)
        output_box = QVBoxLayout()
        output_label = QLabel("📊 Results:")
        output_label.setStyleSheet("font-weight: bold;")
        output_box.addWidget(output_label)
        self.output_text = QTextEdit()
        self.output_text.setReadOnly(True)
        self.output_text.setStyleSheet("background-color: #1a1a1a; color: #ff4500; font-family: Consolas, Monaco, monospace; padding: 10px;")
        output_box.addWidget(self.output_text)
        io_layout.addLayout(input_box)
        io_layout.addLayout(output_box)
        io_group.setLayout(io_layout)
        main_layout.addWidget(io_group)

        # Control Buttons
        btn_layout = QHBoxLayout()
        self.start_button = QPushButton("▶️ START CHECKING")
        self.start_button.clicked.connect(self.start_clicked)
        btn_layout.addWidget(self.start_button)
        self.stop_button = QPushButton("⏹️ STOP")
        self.stop_button.clicked.connect(self.stop_clicked)
        self.stop_button.setEnabled(False)
        btn_layout.addWidget(self.stop_button)
        self.clear_button = QPushButton("🗑️ Clear Results")
        self.clear_button.clicked.connect(lambda: self.output_text.clear())
        btn_layout.addWidget(self.clear_button)
        main_layout.addLayout(btn_layout)
        self.progress_bar = QProgressBar()
        main_layout.addWidget(self.progress_bar)
        self.status_label = QLabel()
        main_layout.addWidget(self.status_label)

        self.generator_mode_switch.toggled.connect(self.update_generator_mode_ui)
        self.word_source_combo.currentTextChanged.connect(self.update_generator_mode_ui)
        self.update_ui()
        self.update_generator_mode_ui()

    def is_words_mode(self):
        return self.generator_mode_switch.isChecked()

    def get_selected_word_source(self):
        source = self.word_source_combo.currentData()
        if source:
            return source
        return WORDLIST_OPTIONS[0][1]

    def is_total_words_source_selected(self):
        return self.get_selected_word_source() == TOTAL_WORDLIST_SOURCE

    def to_raw_github_url(self, github_blob_url):
        if "github.com" in github_blob_url and "/blob/" in github_blob_url:
            return github_blob_url.replace("https://github.com/", "https://raw.githubusercontent.com/").replace("/blob/", "/")
        return github_blob_url

    def update_generator_mode_ui(self):
        is_words_mode = self.is_words_mode()
        is_total_words_source = is_words_mode and self.is_total_words_source_selected()
        self.pattern_label.setVisible(not is_words_mode)
        self.pattern_combo.setVisible(not is_words_mode)
        self.word_source_label.setVisible(is_words_mode)
        self.word_source_combo.setVisible(is_words_mode)
        self.max_length_label.setVisible(is_words_mode)
        self.max_length_input.setVisible(is_words_mode)
        self.word_pick_label.setVisible(is_words_mode)
        self.word_pick_combo.setVisible(is_words_mode)
        if is_words_mode:
            self.length_label.setText("Min Length:")
            self.length_label.setEnabled(is_total_words_source)
            self.length_input.setEnabled(is_total_words_source)
            self.max_length_label.setEnabled(is_total_words_source)
            self.max_length_input.setEnabled(is_total_words_source)
            if is_total_words_source:
                self.length_input.setToolTip("Enabled for google-10000-english-usa.txt")
                self.max_length_input.setToolTip("Enabled for google-10000-english-usa.txt")
            else:
                self.length_input.setToolTip("Length filters are only enabled for google-10000-english-usa.txt")
                self.max_length_input.setToolTip("Length filters are only enabled for google-10000-english-usa.txt")
        else:
            self.length_label.setText("Length:")
            self.length_label.setEnabled(True)
            self.length_input.setEnabled(True)
            self.max_length_label.setEnabled(True)
            self.max_length_input.setEnabled(True)
            self.length_input.setToolTip("")
            self.max_length_input.setToolTip("")

    def get_wordlist(self, source_url):
        if source_url in self.cached_words:
            return self.cached_words[source_url], None
        try:
            download_url = self.to_raw_github_url(source_url)
            response = requests.get(download_url, timeout=10)
            if response.status_code != 200:
                return None, f"Status code {response.status_code}"
            words = []
            for line in response.text.splitlines():
                word = line.strip().lower()
                if word and word.isalpha():
                    words.append(word)
            self.cached_words[source_url] = words
            return self.cached_words[source_url], None
        except Exception as e:
            return None, str(e)

    def generate_word_usernames(self, source_url, min_len, max_len, count, prefix, suffix, pick_mode, apply_length_filter):
        words, err = self.get_wordlist(source_url)
        if err or not words:
            return [], err or "No words were downloaded", 0

        filtered = []
        seen = set()
        for word in words:
            if apply_length_filter and not (min_len <= len(word) <= max_len):
                continue
            username = prefix + word + suffix
            username = ''.join(c for c in username if c.isalnum() or c == '_')
            if len(username) >= REDDIT_MIN_USERNAME_LENGTH and username not in seen:
                seen.add(username)
                filtered.append(username)

        available_count = len(filtered)
        if available_count == 0:
            return [], None, 0
        if pick_mode == "top":
            return filtered[:count], None, available_count
        if count >= available_count:
            return filtered, None, available_count
        return random.sample(filtered, count), None, available_count

    def generate_usernames(self):
        is_words_mode = self.is_words_mode()
        prefix = self.prefix_input.text().strip()
        suffix = self.suffix_input.text().strip()
        try:
            count = int(self.count_input.text())
        except:
            count = 10
        count = max(1, count)

        generated = []
        available_count = count

        if is_words_mode:
            selected_word_source = self.get_selected_word_source()
            use_length_filter = self.is_total_words_source_selected()
            min_len = 1
            max_len = 999
            if use_length_filter:
                try:
                    min_len = int(self.length_input.text())
                except:
                    min_len = 3
                try:
                    max_len = int(self.max_length_input.text())
                except:
                    max_len = max(3, min_len)
                min_len = max(1, min_len)
                max_len = max(1, max_len)
                if max_len < min_len:
                    self.status_label.setText("⚠️ Max length must be greater than or equal to min length")
                    self.status_label.setStyleSheet("padding: 8px; font-weight: bold; background-color: #fff3cd; border-radius: 3px;")
                    return
            pick_mode = "top" if self.word_pick_combo.currentText() == "From Top" else "random"
            self.status_label.setText("⏳ Downloading word list and generating usernames...")
            self.status_label.setStyleSheet("padding: 8px; font-weight: bold; background-color: #fff9c4; border-radius: 3px;")
            QApplication.processEvents()
            generated, err, available_count = self.generate_word_usernames(
                selected_word_source,
                min_len,
                max_len,
                count,
                prefix,
                suffix,
                pick_mode,
                use_length_filter
            )
            if err:
                self.status_label.setText(f"⚠️ Word generator failed: {err}")
                self.status_label.setStyleSheet("padding: 8px; font-weight: bold; background-color: #ffcdd2; border-radius: 3px;")
                return
        else:
            try:
                length = int(self.length_input.text())
            except:
                length = REDDIT_MIN_USERNAME_LENGTH
            length = max(REDDIT_MIN_USERNAME_LENGTH, length)
            pattern = self.pattern_combo.currentText()
            attempts = 0
            max_attempts = count * 3
            while len(generated) < count and attempts < max_attempts:
                attempts += 1
                username = ""
                if pattern == "Letters only (abc)":
                    username = "".join(random.choice(string.ascii_lowercase) for _ in range(length))
                elif pattern == "Letters + Numbers (a1b2)":
                    chars = string.ascii_lowercase + string.digits
                    username = "".join(random.choice(chars) for _ in range(length))
                elif pattern == "Doubles (suuv, my55)":
                    chars = string.ascii_lowercase + string.digits
                    repeat_char = random.choice(chars)
                    base = [random.choice(chars) for _ in range(length - 2)]
                    pos = random.randint(0, len(base))
                    base[pos:pos] = [repeat_char, repeat_char]
                    username = "".join(base)
                elif pattern == "Triples (aaab, t777)":
                    chars = string.ascii_lowercase + string.digits
                    repeat_char = random.choice(chars)
                    other_chars = [c for c in chars if c != repeat_char]
                    base = [random.choice(other_chars) for _ in range(length)]
                    triple_positions = random.sample(range(length), 3)
                    for pos in triple_positions:
                        base[pos] = repeat_char
                    username = "".join(base)
                elif pattern == "Vowels only (aeiou)":
                    vowels = "aeiou"
                    username = "".join(random.choice(vowels) for _ in range(length))
                elif pattern == "One line letters (aceimnorsuvwxz)":
                    one_line_chars = "aceimnorsuvwxz"
                    username = "".join(random.choice(one_line_chars) for _ in range(length))
                username = prefix + username + suffix
                username = ''.join(c for c in username if c.isalnum() or c == '_')
                if len(username) >= REDDIT_MIN_USERNAME_LENGTH and username not in generated:
                    generated.append(username)

        if len(generated) == 0:
            self.status_label.setText(f"⚠️ No valid usernames generated")
            self.status_label.setStyleSheet("padding: 8px; font-weight: bold; background-color: #fff3cd; border-radius: 3px;")
            return
        existing = self.input_text.toPlainText().strip()
        all_usernames = ("\n".join(generated) if not existing else existing + "\n" + "\n".join(generated))
        self.input_text.setText(all_usernames)
        if is_words_mode and available_count < count:
            self.status_label.setText(f"⚠️ Generated {len(generated)} usernames (only {available_count} matched filters)")
            self.status_label.setStyleSheet("padding: 8px; font-weight: bold; background-color: #fff3cd; border-radius: 3px;")
        else:
            self.status_label.setText(f"✅ Generated {len(generated)} usernames")
            self.status_label.setStyleSheet("padding: 8px; font-weight: bold; background-color: #c8e6c9; border-radius: 3px;")

    def test_webhook(self):
        webhook_url = self.webhook_input.text().strip()
        if not webhook_url:
            QMessageBox.warning(self, "No Webhook", "Please enter a webhook URL first!")
            return
        try:
            test_data = {
                "embeds": [{
                    "title": "🧪 Test Message",
                    "description": "Your webhook is working correctly!",
                    "color": 0xFF4500,
                    "footer": {
                        "text": "Reddit Username Checker - Webhook Test"
                    }
                }]
            }
            response = requests.post(webhook_url, json=test_data, timeout=5)
            if response.status_code == 204:
                QMessageBox.information(self, "Success", "✅ Webhook test successful!\nCheck your Discord channel.")
            else:
                QMessageBox.warning(self, "Failed", f"❌ Webhook test failed!\nStatus code: {response.status_code}")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"❌ Failed to send test message:\n{str(e)}")

    def get_proxies(self):
        txt = self.proxy_input.toPlainText().strip()
        if not txt:
            return []
        proxies = [
            l.strip() for l in txt.splitlines()
            if l.strip() and any(l.strip().startswith(p) for p in ("http://", "https://", "socks5://"))
        ]
        self.proxy_count_label.setText(f"Proxies loaded: {len(proxies)}")
        return proxies

    def load_proxies_from_file(self):
        fname, _ = QFileDialog.getOpenFileName(self, "Load Proxy List", "", "Text Files (*.txt);;All (*)")
        if fname:
            try:
                with open(fname, "r", encoding="utf-8") as f:
                    content = f.read()
                self.proxy_input.setText(content)
                cnt = len([l for l in content.splitlines() if l.strip()])
                self.proxy_count_label.setText(f"Proxies loaded: {cnt}")
                self.status_label.setText(f"✅ Loaded {cnt} proxies")
                self.status_label.setStyleSheet("padding: 8px; font-weight: bold; background-color: #c8e6c9; border-radius: 3px;")
            except Exception as e:
                QMessageBox.critical(self, "Error", str(e))

    def start_clicked(self):
        usernames = self.get_usernames()
        if not usernames:
            QMessageBox.warning(self, "No Usernames", "Please enter or generate usernames to check!")
            return
        debug = self.debug_checkbox.isChecked()
        save_to_file = self.save_checkbox.isChecked()
        webhook_url = self.webhook_input.text().strip() or None
        proxies = self.get_proxies()
        self.progress_bar.setMaximum(len(usernames))
        self.progress_bar.setValue(0)
        self.output_text.clear()
        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        status_text = f"🔄 Checking {len(usernames)} usernames"
        if save_to_file:
            status_text += " (saving to file)"
        if webhook_url:
            status_text += " (webhook enabled)"
        if proxies:
            status_text += f" with {len(proxies)} proxies"
        status_text += " on Reddit..."
        self.status_label.setText(status_text)
        self.status_label.setStyleSheet("padding: 8px; font-weight: bold; background-color: #fff9c4; border-radius: 3px;")
        self.thread = Checker(usernames, webhook_url, debug, save_to_file, proxies)
        self.thread.update.connect(self.update_text)
        self.thread.pupdate.connect(self.update_progress)
        self.thread.finished.connect(self.checking_finished)
        self.thread.start()

    def stop_clicked(self):
        if self.thread:
            self.thread.stop()
            self.thread.quit()
            self.thread.wait(2000)
        self.checking_finished()

    def checking_finished(self):
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.status_label.setText(f"✅ Checking complete on Reddit!")
        self.status_label.setStyleSheet("padding: 8px; font-weight: bold; background-color: #c8e6c9; border-radius: 3px;")

    def update_text(self, text):
        # Color coding for UI
        color = None
        if '[TAKEN]' in text:
            color = '#888888'  # gray
        elif '[AVAILABLE]' in text:
            color = '#00ff00'  # green
        elif '[BANNED]' in text:
            color = '#ff4500'  # reddit orange
        elif '[RATE LIMIT]' in text or '[BLOCKED]' in text or '[UNKNOWN]' in text or '[ERROR]' in text or '[TIMEOUT]' in text or '[UNCLEAR]' in text or '[UNCLAIMABLE]' in text:
            color = '#fff700'  # yellow
        else:
            color = '#ff4500'  # default reddit orange

        # Console output with color
        try:
            import sys
            if color == '#00ff00':
                print(f"\033[92m{text}\033[0m")  # green
            elif color == '#888888':
                print(f"\033[90m{text}\033[0m")  # gray
            elif color == '#fff700':
                print(f"\033[93m{text}\033[0m")  # yellow
            elif color == '#ff4500':
                print(f"\033[91m{text}\033[0m")  # orange/red
            else:
                print(text)
        except Exception:
            print(text)

        # UI output with color
        self.output_text.append(f'<span style="color:{color}">{text}</span>')
        cursor = self.output_text.textCursor()
        cursor.movePosition(cursor.End)
        self.output_text.setTextCursor(cursor)

    def update_progress(self, value):
        self.progress_bar.setValue(value)
        total = self.progress_bar.maximum()
        percent = int((value / total) * 100) if total > 0 else 0
        self.status_label.setText(f"🔄 Progress: {value}/{total} ({percent}%) on Reddit")

    def get_usernames(self):
        txt = self.input_text.toPlainText().strip()
        usernames = []
        for line in txt.splitlines():
            u = line.strip()
            if len(u) >= REDDIT_MIN_USERNAME_LENGTH and all(c.isalnum() or c == '_' for c in u):
                usernames.append(u)
        return usernames

    def update_ui(self):
        self.title.setText("👤 Reddit Username Checker")
        self.title.setStyleSheet("padding: 15px; background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #ff4500, stop:1 #ffb380); color: white; border-radius: 5px;")
        self.info_group.setTitle("ℹ️ About Reddit Username Checker")
        self.instruction.setText("✨ Check if Reddit usernames are available!\n⚠️ Note: Reddit may rate limit requests. Check responsibly.\n💾 Available usernames are saved to: available_reddit_usernames.txt")
        self.progress_bar.setStyleSheet("QProgressBar { text-align: center; height: 25px; } QProgressBar::chunk { background-color: #ff4500; }")

# ------------------- Run ------------------- #
if __name__ == "__main__":
    app = QApplication(sys.argv)
    w = App()
    w.show()
    sys.exit(app.exec_())
