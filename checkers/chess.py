import sys, requests, random, string, traceback, time, threading, re
from PyQt5.QtWidgets import *
from PyQt5.QtCore import *
from PyQt5.QtGui import QFont

# ------------------- Platform Toggle ------------------- #
PLATFORMS = ["Chess.com", "Lichess.org"]

WORDLIST_OPTIONS = [
    ("20k (All Words)", "https://github.com/first20hours/google-10000-english/blob/master/20k.txt"),
    ("10k No Swears - Medium", "https://github.com/first20hours/google-10000-english/blob/master/google-10000-english-usa-no-swears-medium.txt"),
    ("10k No Swears - Short", "https://github.com/first20hours/google-10000-english/blob/master/google-10000-english-usa-no-swears-short.txt"),
    ("10k No Swears", "https://github.com/first20hours/google-10000-english/blob/master/google-10000-english-usa-no-swears.txt"),
    ("10k Total Words", "https://github.com/first20hours/google-10000-english/blob/master/google-10000-english-usa.txt"),
    ("Adjectives", "https://gist.githubusercontent.com/hugsy/8910dc78d208e40de42deb29e62df913/raw/eec99c5597a73f6a9240cab26965a8609fa0f6ea/english-adjectives.txt")
]
TOTAL_WORDLIST_SOURCE = "https://github.com/first20hours/google-10000-english/blob/master/google-10000-english-usa.txt"
MIN_USERNAME_LENGTH = 3
MAX_CHESS_USERNAME_LENGTH = 25
CHESS_USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9]|[-_](?=[A-Za-z0-9])){2,24}$")


def validate_chess_username(username):
    if len(username) < MIN_USERNAME_LENGTH:
        return False, f"Minimum username length is {MIN_USERNAME_LENGTH}"
    if len(username) > MAX_CHESS_USERNAME_LENGTH:
        return False, f"Maximum username length is {MAX_CHESS_USERNAME_LENGTH}"
    if not CHESS_USERNAME_PATTERN.fullmatch(username):
        return False, "Use only letters, numbers, hyphens, underscores; start with letter/number; '-' and '_' must be followed by letter/number"
    if not any(c.isalpha() for c in username):
        return False, "Username must contain at least 1 letter"
    return True, ""


def validate_lichess_username(username):
    if len(username) < MIN_USERNAME_LENGTH:
        return False, f"Minimum username length is {MIN_USERNAME_LENGTH}"
    if not all(c.isalnum() or c == '_' for c in username):
        return False, "Use only letters, numbers, and underscores"
    return True, ""

# ------------------- Checker Thread ------------------- #

class Checker(QThread):
    update = pyqtSignal(str)
    pupdate = pyqtSignal(int)
    count = 0

    def __init__(self, usernames, webhook_url=None, debug=False, save_to_file=True, platform="Chess.com", proxies=None):
        super().__init__()
        self.usernames = usernames
        self.webhook_url = webhook_url
        self.running = True
        self.debug = debug
        self.save_to_file = save_to_file
        self.platform = platform
        self.count = 0
        self.consecutive_errors = 0
        self.request_delay = 0.25  # safer initial delay for fewer rate limits
        self.min_delay = 0.08      # keep floor high enough to avoid bursty limits
        self.rate_lock = threading.Lock()
        self.file_lock = threading.Lock()
        self.last_request_time = 0
        self.proxies = proxies or []
        self.proxy_index = 0
        self.session_local = threading.local()

    def run(self):
        from concurrent.futures import ThreadPoolExecutor
        self.count_lock = threading.Lock()
        max_workers = 5
        self.count = 0

        def worker(username):
            if not self.running:
                return
            result = self.check_username(username)
            with self.count_lock:
                self.count += 1
                self.pupdate.emit(self.count)
            return result

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = []
            for username in self.usernames:
                if not self.running:
                    break
                futures.append(executor.submit(worker, username))
            for future in futures:
                if not self.running:
                    break
                try:
                    future.result()
                except Exception as e:
                    if self.debug:
                        self.update.emit(f"[DEBUG] Worker error: {e}")

    def stop(self):
        self.running = False

    def get_session(self):
        session = getattr(self.session_local, "session", None)
        if session is None:
            session = requests.Session()
            self.session_local.session = session
        return session

    def save_available_username(self, save_file, username):
        with self.file_lock:
            with open(save_file, "a", encoding="utf-8") as f:
                f.write(f"{username}\n")

    def get_next_proxy(self):
        if not self.proxies:
            return None
        proxy = self.proxies[self.proxy_index]
        self.proxy_index = (self.proxy_index + 1) % len(self.proxies)
        return proxy

    def check_username(self, username):
        if not self.running:
            return
        if self.platform == "Chess.com":
            is_valid, reason = validate_chess_username(username)
            if not is_valid:
                self.update.emit(f"⚠️ [UNCLAIMABLE] {username}: {reason}")
                return
        else:
            is_valid, reason = validate_lichess_username(username)
            if not is_valid:
                self.update.emit(f"⚠️ [UNCLAIMABLE] {username}: {reason}")
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
            if self.platform == "Chess.com":
                url = f"https://www.chess.com/member/{username}"
                webhook_desc = f"`{username}` [is available for **chess.com**!](https://www.chess.com/member/{username})"
                webhook_color = 11045716
                save_file = "available_chess_usernames.txt"
                ratelimit_msg = "Chess.com is rate limiting!"
                blocked_msg = "Chess.com blocked the request!"
            else:
                url = f"https://lichess.org/@/{username}"
                webhook_desc = f"`{username}` [is available for **lichess.org**!](https://lichess.org/@/{username})"
                webhook_color = 0x6A4FB6
                save_file = "available_lichess_usernames.txt"
                ratelimit_msg = "Lichess.org is rate limiting!"
                blocked_msg = "Lichess.org blocked the request!"

            if self.debug:
                self.update.emit(f"\n{'='*60}")
                self.update.emit(f"[DEBUG] Checking: {username}")
                self.update.emit(f"[DEBUG] URL: {url}")

            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }

            proxy = self.get_next_proxy()
            proxy_dict = {"http": proxy, "https": proxy} if proxy else None
            if self.debug and proxy:
                self.update.emit(f"[DEBUG] Using proxy: {proxy}")

            session = self.get_session()
            response = session.get(url, headers=headers, timeout=10, allow_redirects=True, proxies=proxy_dict)

            if self.debug:
                self.update.emit(f"[DEBUG] Status Code: {response.status_code}")

            if self.platform == "Lichess.org" and response.status_code == 404:
                page = response.text
                if "It cannot be used to create a new account." in page:
                    self.update.emit(f"\u26a0\ufe0f [UNCLAIMABLE] {username}: Cannot be used to create a new account.")
                else:
                    self.update.emit(f"\u2705 [AVAILABLE] {username}")
                    if self.save_to_file:
                        try:
                            self.save_available_username(save_file, username)
                        except Exception as e:
                            if self.debug:
                                self.update.emit(f"[DEBUG] Failed to save to file: {e}")
                    if self.webhook_url:
                        self.send_to_discord(username, webhook_desc, webhook_color)
                self.consecutive_errors = 0
                if self.request_delay > 0.2:
                    self.request_delay = max(self.min_delay, self.request_delay * 0.9)
            elif response.status_code == 200:
                self.update.emit(f"\u274c [TAKEN] {username}")
                self.consecutive_errors = 0
                if self.request_delay > 0.2:
                    self.request_delay = max(self.min_delay, self.request_delay * 0.9)
            elif response.status_code == 404:
                self.update.emit(f"\u2705 [AVAILABLE] {username}")
                self.consecutive_errors = 0
                if self.save_to_file:
                    try:
                        self.save_available_username(save_file, username)
                    except Exception as e:
                        if self.debug:
                            self.update.emit(f"[DEBUG] Failed to save to file: {e}")
                if self.webhook_url:
                    self.send_to_discord(username, webhook_desc, webhook_color)
                if self.request_delay > 0.2:
                    self.request_delay = max(self.min_delay, self.request_delay * 0.9)
            elif response.status_code == 429:
                self.update.emit(f"\u26a0\ufe0f [RATE LIMIT] {username}: {ratelimit_msg}")
                self.request_delay = min(10, self.request_delay * 1.7)
            elif response.status_code == 403:
                self.update.emit(f"\u26a0\ufe0f [BLOCKED] {username}: {blocked_msg}")
                self.consecutive_errors += 1
                self.request_delay = min(10, self.request_delay * 1.7)
                time.sleep(5)
            else:
                self.update.emit(f"\u26a0\ufe0f [UNKNOWN] {username}: Status {response.status_code}")
                self.consecutive_errors += 1
        except requests.exceptions.Timeout:
            self.consecutive_errors += 1
            self.update.emit(f"\u23f1\ufe0f [TIMEOUT] {username}")
            self.request_delay = min(10, self.request_delay * 1.7)
            sleep_time = min(30, 2 ** self.consecutive_errors)
            time.sleep(sleep_time)
        except Exception as e:
            self.consecutive_errors += 1
            self.request_delay = min(10, self.request_delay * 1.7)
            if self.debug:
                error_msg = traceback.format_exc()
                self.update.emit(f"\u26a0\ufe0f [ERROR] {username}:\n{error_msg}")
            else:
                error_msg = str(e)
                self.update.emit(f"\u26a0\ufe0f [ERROR] {username}: {error_msg}")

    def send_to_discord(self, username, desc, color):
        try:
            if not self.webhook_url:
                return
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
            response = self.get_session().post(self.webhook_url, json=webhook_data, timeout=5)
            if response.status_code == 204:
                if self.debug:
                    self.update.emit(f"[DEBUG] ✅ Sent {username} to Discord webhook")
            else:
                if self.debug:
                    self.update.emit(f"[DEBUG] ⚠️ Webhook failed: Status {response.status_code}")
        except Exception as e:
            if self.debug:
                self.update.emit(f"[DEBUG] ⚠️ Webhook error: {str(e)}")

# ------------------- Dual Checker Thread ------------------- #

class DualChecker(QThread):
    update = pyqtSignal(str)
    pupdate = pyqtSignal(int)

    def __init__(self, usernames, webhook_url=None, debug=False, save_to_file=True, proxies=None):
        super().__init__()
        self.usernames = usernames
        self.webhook_url = webhook_url
        self.debug = debug
        self.save_to_file = save_to_file
        self.proxies = proxies or []
        self.running = True
        self.chess_thread = None
        self.lichess_thread = None
        self.total_checked = 0

    def run(self):
        self.update.emit("🔄 Starting simultaneous checking on both platforms...\n")
        self.chess_thread = Checker(self.usernames, self.webhook_url, self.debug, self.save_to_file, "Chess.com", self.proxies)
        self.lichess_thread = Checker(self.usernames, self.webhook_url, self.debug, self.save_to_file, "Lichess.org", self.proxies)
        
        self.chess_thread.update.connect(self.on_chess_update)
        self.chess_thread.pupdate.connect(self.on_progress_update)
        self.lichess_thread.update.connect(self.on_lichess_update)
        self.lichess_thread.pupdate.connect(self.on_progress_update)
        
        self.chess_thread.start()
        self.lichess_thread.start()
        
        self.chess_thread.wait()
        self.lichess_thread.wait()

    def on_chess_update(self, text):
        self.update.emit(f"[CHESS.COM] {text}")

    def on_lichess_update(self, text):
        self.update.emit(f"[LICHESS.ORG] {text}")

    def on_progress_update(self, value):
        self.total_checked += 1
        self.pupdate.emit(self.total_checked)

    def stop(self):
        self.running = False
        if self.chess_thread:
            self.chess_thread.stop()
        if self.lichess_thread:
            self.lichess_thread.stop()

# ------------------- GUI App ------------------- #

class App(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Chess/Lichess Username Checker")
        self.setGeometry(150, 150, 1100, 800)
        self.worker_thread = None
        self.platform = PLATFORMS[0]
        self.cached_words = {}
        self.initUI()

    def initUI(self):
        wid = QWidget(self)
        self.setCentralWidget(wid)
        main_layout = QVBoxLayout()
        wid.setLayout(main_layout)

        # Platform Toggle
        plat_layout = QHBoxLayout()
        plat_label = QLabel("Select Platform:")
        plat_label.setStyleSheet("font-weight: bold; padding: 8px;")
        plat_layout.addWidget(plat_label)
        self.platform_combo = QComboBox()
        self.platform_combo.addItems(PLATFORMS)
        self.platform_combo.currentIndexChanged.connect(self.platform_changed)
        plat_layout.addWidget(self.platform_combo)
        self.check_both_checkbox = QCheckBox("✓ Check Both Platforms Simultaneously")
        self.check_both_checkbox.setToolTip("Run Chess.com and Lichess.org checks at the same time with the same settings")
        plat_layout.addWidget(self.check_both_checkbox)
        plat_layout.addStretch()
        main_layout.addLayout(plat_layout)

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
        self.instruction.setStyleSheet("background-color: #e7f3ff; padding: 10px; border-radius: 3px; color: #004085;")
        self.info_layout.addWidget(self.instruction)
        self.info_group.setLayout(self.info_layout)
        main_layout.addWidget(self.info_group)

        # Webhook Section
        webhook_group = QGroupBox("🔔 Discord Webhook (Optional)")
        webhook_group.setStyleSheet("QGroupBox { font-weight: bold; }")
        webhook_layout = QVBoxLayout()
        webhook_info = QLabel("💬 Get notified when available usernames are found!")
        webhook_info.setWordWrap(True)
        webhook_info.setStyleSheet("background-color: #f8d7da; padding: 8px; border-radius: 3px; color: #721c24;")
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
        self.prefix_input.setPlaceholderText("e.g., chess")
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
        self.gen_button.setStyleSheet("background-color: #312e2b; color: white; padding: 8px; font-weight: bold;")
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
        self.input_text.setPlaceholderText("Enter usernames here\n(one per line)\n\nExample:\nabc\nxyz\nchesspro123")
        input_box.addWidget(self.input_text)
        output_box = QVBoxLayout()
        output_label = QLabel("📊 Results:")
        output_label.setStyleSheet("font-weight: bold;")
        output_box.addWidget(output_label)
        self.output_text = QTextEdit()
        self.output_text.setReadOnly(True)
        self.output_text.setStyleSheet("background-color: #1a1a1a; color: #00ff00; font-family: Consolas, Monaco, monospace; padding: 10px;")
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
        self.update_platform_ui()
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
            if len(username) >= 1 and username not in seen:
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
                length = 3
            length = max(1, length)
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
                    if length < 2:
                        continue
                    chars = string.ascii_lowercase + string.digits
                    repeat_char = random.choice(chars)
                    base = [random.choice(chars) for _ in range(length - 2)]
                    pos = random.randint(0, len(base))
                    base[pos:pos] = [repeat_char, repeat_char]
                    username = "".join(base)
                elif pattern == "Triples (aaab, t777)":
                    if length < 3:
                        continue
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
                if len(username) > 0 and username not in generated:
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
                    "color": 16753920,
                    "footer": {
                        "text": f"{self.platform} Username Checker - Webhook Test"
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

    def start_clicked(self):
        usernames = self.get_usernames()
        if not usernames:
            QMessageBox.warning(self, "No Usernames", f"Please enter or generate usernames to check!\nOnly usernames with at least {MIN_USERNAME_LENGTH} characters are checked.")
            return
        debug = self.debug_checkbox.isChecked()
        save_to_file = self.save_checkbox.isChecked()
        webhook_url = self.webhook_input.text().strip() or None
        proxies = self.get_proxies()
        check_both = self.check_both_checkbox.isChecked()
        
        self.progress_bar.setMaximum(len(usernames) * (2 if check_both else 1))
        self.progress_bar.setValue(0)
        self.output_text.clear()
        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.check_both_checkbox.setEnabled(False)
        self.platform_combo.setEnabled(False)
        
        if check_both:
            status_text = f"🔄 Checking {len(usernames)} usernames on BOTH platforms simultaneously"
            if save_to_file:
                status_text += " (saving to files)"
            if webhook_url:
                status_text += " (webhook enabled)"
            if proxies:
                status_text += f" with {len(proxies)} proxies"
            status_text += "..."
            self.status_label.setText(status_text)
            self.status_label.setStyleSheet("padding: 8px; font-weight: bold; background-color: #fff9c4; border-radius: 3px;")
            self.worker_thread = DualChecker(usernames, webhook_url, debug, save_to_file, proxies)
            self.worker_thread.update.connect(self.update_text)
            self.worker_thread.pupdate.connect(self.update_dual_progress)
            self.worker_thread.finished.connect(self.checking_finished)
            self.worker_thread.start()
        else:
            status_text = f"🔄 Checking {len(usernames)} usernames"
            if save_to_file:
                status_text += " (saving to file)"
            if webhook_url:
                status_text += " (webhook enabled)"
            if proxies:
                status_text += f" with {len(proxies)} proxies"
            status_text += f" on {self.platform}..."
            self.status_label.setText(status_text)
            self.status_label.setStyleSheet("padding: 8px; font-weight: bold; background-color: #fff9c4; border-radius: 3px;")
            self.worker_thread = Checker(usernames, webhook_url, debug, save_to_file, self.platform, proxies)
            self.worker_thread.update.connect(self.update_text)
            self.worker_thread.pupdate.connect(self.update_progress)
            self.worker_thread.finished.connect(self.checking_finished)
            self.worker_thread.start()

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

    def stop_clicked(self):
        if self.worker_thread:
            if hasattr(self.worker_thread, 'stop'):
                self.worker_thread.stop()
            self.worker_thread.quit()
            self.worker_thread.wait(2000)
        self.checking_finished()

    def checking_finished(self):
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.check_both_checkbox.setEnabled(True)
        self.platform_combo.setEnabled(True)
        if self.check_both_checkbox.isChecked():
            self.status_label.setText(f"✅ Dual platform checking complete!")
        else:
            self.status_label.setText(f"✅ Checking complete on {self.platform}!")
        self.status_label.setStyleSheet("padding: 8px; font-weight: bold; background-color: #c8e6c9; border-radius: 3px;")

    def update_text(self, text):
        self.output_text.append(text)
        cursor = self.output_text.textCursor()
        cursor.movePosition(cursor.End)
        self.output_text.setTextCursor(cursor)

    def update_progress(self, value):
        self.progress_bar.setValue(value)
        total = self.progress_bar.maximum()
        percent = int((value / total) * 100) if total > 0 else 0
        self.status_label.setText(f"🔄 Progress: {value}/{total} ({percent}%) on {self.platform}")

    def update_dual_progress(self, value):
        self.progress_bar.setValue(value)
        total = self.progress_bar.maximum()
        percent = int((value / total) * 100) if total > 0 else 0
        self.status_label.setText(f"🔄 Dual Platform Progress: {value}/{total} ({percent}%)")

    def get_usernames(self):
        txt = self.input_text.toPlainText().strip()
        usernames = []
        seen = set()
        check_both = self.check_both_checkbox.isChecked()
        skipped_count = 0
        for line in txt.splitlines():
            u = line.strip()
            if not u:
                continue
            if check_both or self.platform == "Chess.com":
                is_valid, _ = validate_chess_username(u)
            else:
                is_valid, _ = validate_lichess_username(u)
            if is_valid and u not in seen:
                seen.add(u)
                usernames.append(u)
            elif not is_valid:
                skipped_count += 1
        if skipped_count > 0:
            self.output_text.append(f"⚠️ Skipped {skipped_count} invalid username(s) for selected platform rules.")
        return usernames

    def platform_changed(self, idx):
        self.platform = PLATFORMS[idx]
        self.update_platform_ui()

    def update_platform_ui(self):
        if self.platform == "Chess.com":
            self.title.setText("♟️ Chess.com Username Checker")
            self.title.setStyleSheet("padding: 15px; background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #312e2b, stop:1 #6e5c4b); color: white; border-radius: 5px;")
            self.info_group.setTitle("ℹ️ About Chess.com Username Checker")
            self.instruction.setText("✨ Check if Chess.com usernames are available!\n⚠️ Note: Chess.com may rate limit requests. Check responsibly.\n💾 Available usernames are saved to: available_chess_usernames.txt")
            self.progress_bar.setStyleSheet("QProgressBar { text-align: center; height: 25px; } QProgressBar::chunk { background-color: #388e3c; }")
        else:
            self.title.setText("♞ Lichess.org Username Checker")
            self.title.setStyleSheet("padding: 15px; background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #3C1E70, stop:1 #6A4FB6); color: white; border-radius: 5px;")
            self.info_group.setTitle("ℹ️ About Lichess.org Username Checker")
            self.instruction.setText("✨ Check if Lichess.org usernames are available!\n⚠️ Note: Lichess.org may rate limit requests. Check responsibly.\n💾 Available usernames are saved to: available_lichess_usernames.txt")
            self.progress_bar.setStyleSheet("QProgressBar { text-align: center; height: 25px; } QProgressBar::chunk { background-color: #6A4FB6; }")

# ------------------- Run ------------------- #
if __name__ == "__main__":
    app = QApplication(sys.argv)
    w = App()
    w.show()
    sys.exit(app.exec_())
