# Super fast bulk Roblox username checker with rate control, proxy support, and multi-session
import sys, requests, random, string, traceback, time, threading, concurrent.futures, os
from PyQt5.QtWidgets import *
from PyQt5.QtCore import *
from PyQt5.QtGui import QFont

WORDLIST_OPTIONS = [
	("72k words (Alphabetical)", "https://raw.githubusercontent.com/jeremy-rifkin/Wordlist/refs/heads/master/res/a.txt"),
	("20k (All Words)", "https://github.com/first20hours/google-10000-english/blob/master/20k.txt"),
	("10k No Swears - Medium", "https://github.com/first20hours/google-10000-english/blob/master/google-10000-english-usa-no-swears-medium.txt"),
	("10k No Swears - Short", "https://github.com/first20hours/google-10000-english/blob/master/google-10000-english-usa-no-swears-short.txt"),
	("10k No Swears", "https://github.com/first20hours/google-10000-english/blob/master/google-10000-english-usa-no-swears.txt"),
	("10k Total Words", "https://github.com/first20hours/google-10000-english/blob/master/google-10000-english-usa.txt"),
	("Adjectives", "https://gist.githubusercontent.com/hugsy/8910dc78d208e40de42deb29e62df913/raw/eec99c5597a73f6a9240cab26965a8609fa0f6ea/english-adjectives.txt")
]
TOTAL_WORDLIST_SOURCE = "https://github.com/first20hours/google-10000-english/blob/master/google-10000-english-usa.txt"

# ------------------- Checker Thread ------------------- #
class Checker(QThread):
	update = pyqtSignal(str)
	pupdate = pyqtSignal(int)

	def __init__(self, usernames, webhook_url=None, debug=False, save_to_file=True, proxies=None):
		super().__init__()
		self.usernames = usernames
		self.webhook_url = webhook_url
		self.running = True
		self.debug = debug
		self.save_to_file = save_to_file
		self.consecutive_errors = 0
		self.count = 0
		self.count_lock = threading.Lock()
		self.file_lock = threading.Lock()
		self.thread_local = threading.local()
		self.request_delay = 0.15
		self.rate_lock = threading.Lock()
		self.rate_limit_list_lock = threading.Lock()
		self.last_request_time = 0
		self.proxies = proxies or []
		self.proxy_index = 0
		self.proxy_lock = threading.Lock()
		# Adaptive speed detection
		self.consecutive_no_rate_limit = 0
		self.speed_tier = 0  # 0=normal, 1=fast, 2=ultra-fast
		self.speed_lock = threading.Lock()
		self.max_workers = 5

	def run(self):
		available_usernames = []
		file_handle = None
		rate_limited_usernames = []
		if self.save_to_file:
			try:
				file_handle = open("available_roblox_usernames.txt", "a")
			except Exception as e:
				file_handle = None
				if self.debug:
					self.update.emit(f"[DEBUG] Failed to open file: {e}")

		def worker(username):
			if not self.running:
				return
			result = self.check_username(username, file_handle, rate_limited_usernames)
			with self.count_lock:
				self.count += 1
				self.pupdate.emit(self.count)
			return result

		with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as executor:
			futures = []
			for username in self.usernames:
				futures.append(executor.submit(worker, username))
			concurrent.futures.wait(futures)

		if file_handle:
			file_handle.close()

		# Pause before retrying rate-limited usernames
		if rate_limited_usernames:
			# Only wait if not in ultra-fast mode
			if self.speed_tier < 2:
				self.update.emit(f"\n⏳ Waiting 30 seconds before retrying {len(rate_limited_usernames)} rate-limited usernames...")
				time.sleep(30)
			else:
				self.update.emit(f"\n⚡ Retrying {len(rate_limited_usernames)} rate-limited usernames immediately (ultra-fast mode)...")
			with self.count_lock:
				self.count = 0
			if self.save_to_file:
				try:
					file_handle = open("available_roblox_usernames.txt", "a")
				except Exception as e:
					file_handle = None
					if self.debug:
						self.update.emit(f"[DEBUG] Failed to open file for retry: {e}")
			def retry_worker(username):
				if not self.running:
					return
				result = self.check_username(username, file_handle)
				with self.count_lock:
					self.count += 1
					self.pupdate.emit(self.count)
				return result
			max_retry_workers = 3 if self.speed_tier == 0 else (10 if self.speed_tier == 1 else 30)
			with concurrent.futures.ThreadPoolExecutor(max_workers=max_retry_workers) as executor:
				futures = []
				for username in rate_limited_usernames:
					futures.append(executor.submit(retry_worker, username))
				concurrent.futures.wait(futures)
			if file_handle:
				file_handle.close()

	def stop(self):
		self.running = False

	def get_session(self):
		if not hasattr(self.thread_local, 'session'):
			session = requests.Session()
			session.headers.update({
				'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
			})
			self.thread_local.session = session
		return self.thread_local.session

	def maybe_increase_delay_on_errors(self):
		if self.consecutive_errors > 3:
			self.request_delay = min(10, self.request_delay * 1.5)

	def get_next_proxy(self):
		if not self.proxies:
			return None
		with self.proxy_lock:
			proxy = self.proxies[self.proxy_index]
			self.proxy_index = (self.proxy_index + 1) % len(self.proxies)
		return proxy

	def _try_escalate_speed(self):
		"""Auto-escalate speed when detecting no rate limits."""
		with self.speed_lock:
			self.consecutive_no_rate_limit += 1
			# Escalate to fast mode after 5 successful requests
			if self.speed_tier == 0 and self.consecutive_no_rate_limit >= 5:
				self.speed_tier = 1
				self.max_workers = 15
				self.update.emit("⚡ [SPEED] Escalated to FAST MODE (15 workers)")
				self.consecutive_no_rate_limit = 0
			# Escalate to ultra-fast after 10 more successful requests
			elif self.speed_tier == 1 and self.consecutive_no_rate_limit >= 10:
				self.speed_tier = 2
				self.max_workers = 50
				self.request_delay = 0.01
				self.update.emit("⚡⚡ [SPEED] Escalated to ULTRA-FAST MODE (50 workers, minimal delays)")
				self.consecutive_no_rate_limit = 0

	def check_username(self, username, file_handle=None, rate_limited_usernames=None):
		if not self.running:
			return

		retries = 0
		max_retries = 2 if self.speed_tier == 0 else 1
		while retries <= max_retries:
			if not self.running:
				return
			# Global request limiter (less strict in faster modes)
			if self.speed_tier < 2:
				with self.rate_lock:
					now = time.time()
					wait = self.request_delay - (now - self.last_request_time)
					if wait > 0:
						time.sleep(wait)
					self.last_request_time = time.time()
				# Random jitter only in normal mode
				if self.speed_tier == 0:
					time.sleep(random.uniform(0.01, 0.03))
			try:
				url = "https://users.roblox.com/v1/usernames/users"
				data = {"usernames": [username]}
				
				if self.debug:
					self.update.emit(f"\n{'='*60}")
					self.update.emit(f"[DEBUG] Checking: {username}")
					self.update.emit(f"[DEBUG] URL: {url}")

				session = self.get_session()
				proxy = self.get_next_proxy()
				proxy_dict = None
				if proxy:
					proxy_dict = {"http": proxy, "https": proxy}
					if self.debug:
						self.update.emit(f"[DEBUG] Using proxy: {proxy}")
				
				response = session.post(url, json=data, timeout=10, proxies=proxy_dict)

				if self.debug:
					self.update.emit(f"[DEBUG] Status Code: {response.status_code}")
					self.update.emit(f"[DEBUG] Response: {response.text[:200]}")

				if response.status_code == 200:
					result = response.json()
					
					if result.get("data") and len(result["data"]) > 0:
						user_data = result["data"][0]
						if user_data.get("id") is not None:
							user_id = user_data.get("id")
							display_name = user_data.get("displayName", username)
							self.update.emit(f"❌ [TAKEN] {username} (ID: {user_id})")
							self.consecutive_errors = 0
							# Adaptive speed escalation on successful responses
							self._try_escalate_speed()
							if self.request_delay > 0.15:
								self.request_delay = max(0.1, self.request_delay * 0.9)
							return
					
					# Username is available
					self.update.emit(f"✅ [AVAILABLE] {username}")
					self.consecutive_errors = 0
					# Adaptive speed escalation on successful responses
					self._try_escalate_speed()
					if self.request_delay > 0.15:
						self.request_delay = max(0.1, self.request_delay * 0.9)
					if file_handle:
						try:
							with self.file_lock:
								file_handle.write(f"{username}\n")
						except Exception as e:
							if self.debug:
								self.update.emit(f"[DEBUG] Failed to save to file: {e}")
					if self.webhook_url:
						self.send_to_discord(username)
					return
					
				elif response.status_code == 429:
					self.update.emit(f"⚠️ [RATE LIMIT] {username}: Roblox is rate limiting! Backing off.")
					# Reset speed tier on rate limit
					with self.speed_lock:
						self.speed_tier = 0
						self.max_workers = 5
						self.consecutive_no_rate_limit = 0
					self.request_delay = min(10, self.request_delay * 1.7)
					if rate_limited_usernames is not None:
						with self.rate_limit_list_lock:
							rate_limited_usernames.append(username)
					return
				else:
					self.update.emit(f"⚠️ [UNKNOWN] {username}: Status {response.status_code}")
					self.consecutive_errors += 1
					self.maybe_increase_delay_on_errors()
					retries += 1
			except (requests.exceptions.Timeout, requests.exceptions.ConnectionError, requests.exceptions.ProxyError):
				self.consecutive_errors += 1
				self.maybe_increase_delay_on_errors()
				self.update.emit(f"⏱️ [TIMEOUT/CONN ERROR] {username} (retry {retries+1})")
				sleep_time = min(30, 2 ** self.consecutive_errors)
				time.sleep(sleep_time)
				retries += 1
			except Exception as e:
				self.consecutive_errors += 1
				self.maybe_increase_delay_on_errors()
				if self.debug:
					error_msg = traceback.format_exc()
					self.update.emit(f"⚠️ [ERROR] {username}:\n{error_msg}")
				else:
					error_msg = str(e)
					self.update.emit(f"⚠️ [ERROR] {username}: {error_msg}")
				retries += 1
		self.update.emit(f"❌ [FAILED] {username} after {max_retries+1} attempts")

	def send_to_discord(self, username):
		webhook_url = self.webhook_url
		if not webhook_url:
			return
		try:
			webhook_data = {
				"content": "",
				"tts": False,
				"embeds": [
					{
						"title": "🎮 Available Roblox Username Found!",
						"description": f"`{username}` [is available on **Roblox**!](https://www.roblox.com/users/search?keyword={username})",
						"fields": [],
						"color": 3447003
					}
				],
				"components": [],
				"actions": {},
				"flags": 0
			}
			session = self.get_session()
			response = session.post(webhook_url, json=webhook_data, timeout=5)
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
		self.setWindowTitle("Roblox Username Checker")
		self.setGeometry(150, 150, 1100, 800)
		self.active_checker = None
		self.cached_words = {}
		self.initUI()

	def initUI(self):
		wid = QWidget(self)
		self.setCentralWidget(wid)
		main_layout = QVBoxLayout()
		wid.setLayout(main_layout)

		# Title
		title = QLabel("🎮 Roblox Username Checker")
		title_font = QFont()
		title_font.setPointSize(16)
		title_font.setBold(True)
		title.setFont(title_font)
		title.setStyleSheet("padding: 15px; background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #2d2d2d, stop:1 #3498db); color: white; border-radius: 5px;")
		main_layout.addWidget(title)

		# Info Section
		info_group = QGroupBox("ℹ️ About Roblox Username Checker")
		info_group.setStyleSheet("QGroupBox { font-weight: bold; }")
		info_layout = QVBoxLayout()
		instruction = QLabel("✨ Check if Roblox usernames are available!\n⚠️ Note: Roblox may rate limit requests. Check responsibly.\n💾 Available usernames are saved to: available_roblox_usernames.txt")
		instruction.setWordWrap(True)
		instruction.setStyleSheet("background-color: #e7f3ff; padding: 10px; border-radius: 3px; color: #004085;")
		info_layout.addWidget(instruction)
		info_group.setLayout(info_layout)
		main_layout.addWidget(info_group)

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

		# Proxies Section
		proxy_group = QGroupBox("🔗 Proxies (Optional)")
		proxy_group.setStyleSheet("QGroupBox { font-weight: bold; }")
		proxy_layout = QVBoxLayout()
		proxy_info = QLabel("Format: http://ip:port or http://user:pass@ip:port (one per line)\nProxies help avoid rate limits and IP bans")
		proxy_info.setWordWrap(True)
		proxy_info.setStyleSheet("background-color: #d1ecf1; padding: 8px; border-radius: 3px; color: #0c5460;")
		proxy_layout.addWidget(proxy_info)
		proxy_input_layout = QHBoxLayout()
		self.proxy_input = QTextEdit()
		self.proxy_input.setPlaceholderText("http://proxy1.com:8080\nhttp://user:pass@proxy2.com:8080")
		self.proxy_input.setMaximumHeight(80)
		proxy_input_layout.addWidget(self.proxy_input)
		proxy_btns = QVBoxLayout()
		load_proxy_btn = QPushButton("📁 Load File")
		load_proxy_btn.clicked.connect(self.load_proxies_from_file)
		proxy_btns.addWidget(load_proxy_btn)
		clear_proxy_btn = QPushButton("🗑️ Clear")
		clear_proxy_btn.clicked.connect(lambda: self.proxy_input.clear())
		proxy_btns.addWidget(clear_proxy_btn)
		proxy_btns.addStretch()
		proxy_input_layout.addLayout(proxy_btns)
		proxy_layout.addLayout(proxy_input_layout)
		self.proxy_count_lbl = QLabel("Proxies loaded: 0")
		self.proxy_count_lbl.setStyleSheet("font-style: italic; color: #555;")
		proxy_layout.addWidget(self.proxy_count_lbl)
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
		self.prefix_input.setPlaceholderText("e.g., Pro")
		self.prefix_input.setMaximumWidth(100)
		row1.addWidget(self.prefix_input)
		row1.addWidget(QLabel("Suffix:"))
		self.suffix_input = QLineEdit()
		self.suffix_input.setPlaceholderText("e.g., _YT")
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
			"Doubles (suuv, my55)",
			"Triples (aaab, t777)",
			"Quadruples (mmmm, t4444)",
			"Vowels only (aeiou)",
			"One line letters (aceimnorsuvwxz)"
		])
		self.pattern_combo.setMaximumWidth(200)
		row2.addWidget(self.pattern_combo)
		self.include_numbers_checkbox = QCheckBox("+ Numbers")
		self.include_numbers_checkbox.setToolTip("Include numbers in pattern")
		row2.addWidget(self.include_numbers_checkbox)
		self.numbers_only_checkbox = QCheckBox("Numbers Only")
		self.numbers_only_checkbox.setToolTip("Generate usernames with only numbers (0-9)")
		row2.addWidget(self.numbers_only_checkbox)
		self.underscore_checkbox = QCheckBox("Allow Underscore (_}")
		self.underscore_checkbox.setToolTip("Allow at most one underscore per username, not at start or end")
		row2.addWidget(self.underscore_checkbox)
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
		self.gen_button.setStyleSheet("background-color: #3498db; color: white; padding: 8px; font-weight: bold;")
		row2.addWidget(self.gen_button)
		self.debug_checkbox = QCheckBox("🐛 Debug Mode")
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
		self.input_text.setPlaceholderText("Enter usernames here\n(one per line)\n\nExample:\nCoolGamer123\nProPlayer\nEpicUser")
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
		self.start_button.setStyleSheet("background-color: #27ae60; color: white; font-weight: bold; padding: 15px; font-size: 14px;")
		btn_layout.addWidget(self.start_button)
		self.stop_button = QPushButton("⏹️ STOP")
		self.stop_button.clicked.connect(self.stop_clicked)
		self.stop_button.setEnabled(False)
		self.stop_button.setStyleSheet("background-color: #e74c3c; color: white; font-weight: bold; padding: 15px; font-size: 14px;")
		btn_layout.addWidget(self.stop_button)
		self.clear_button = QPushButton("🗑️ Clear Results")
		self.clear_button.clicked.connect(lambda: self.output_text.clear())
		self.clear_button.setStyleSheet("padding: 15px;")
		btn_layout.addWidget(self.clear_button)
		main_layout.addLayout(btn_layout)

		# Progress Bar
		self.progress_bar = QProgressBar()
		self.progress_bar.setStyleSheet("QProgressBar { text-align: center; height: 25px; } QProgressBar::chunk { background-color: #3498db; }")
		main_layout.addWidget(self.progress_bar)

		# Status Label
		self.status_label = QLabel("✅ Ready to check Roblox usernames!")
		self.status_label.setStyleSheet("padding: 8px; font-weight: bold; background-color: #e0e0e0; border-radius: 3px;")
		main_layout.addWidget(self.status_label)

		self.generator_mode_switch.toggled.connect(self.update_generator_mode_ui)
		self.word_source_combo.currentTextChanged.connect(self.update_generator_mode_ui)
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

	def is_problematic_username(self, username):
		"""Check if username contains patterns that are considered slurs."""
		username_lower = username.lower()
		
		# Only filter out "kkk" (Ku Klux Klan reference)
		if "kkk" in username_lower:
			return True
		
		return False

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
			if 3 <= len(username) <= 20 and username not in seen and not self.is_problematic_username(username):
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
			pick_mode = "top" if self.word_pick_combo.currentText() == "top" else "random"
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
			include_numbers = self.include_numbers_checkbox.isChecked()
			numbers_only = self.numbers_only_checkbox.isChecked()
			while len(generated) < count and attempts < max_attempts:
				attempts += 1
				username = ""
				if pattern == "Letters only (abc)":
					if numbers_only:
						username = "".join(random.choice(string.digits) for _ in range(length))
					elif include_numbers:
						chars = string.ascii_lowercase + string.digits
						username = "".join(random.choice(chars) for _ in range(length))
					else:
						username = "".join(random.choice(string.ascii_lowercase) for _ in range(length))
				elif pattern == "Doubles (suuv, my55)":
					if numbers_only:
						chars = string.digits
					elif include_numbers:
						chars = string.ascii_lowercase + string.digits
					else:
						chars = string.ascii_lowercase
					repeat_char = random.choice(chars)
					base = [random.choice(chars) for _ in range(length - 2)]
					pos = random.randint(0, len(base))
					base[pos:pos] = [repeat_char, repeat_char]
					username = "".join(base)
				elif pattern == "Triples (aaab, t777)":
					if numbers_only:
						chars = string.digits
					elif include_numbers:
						chars = string.ascii_lowercase + string.digits
					else:
						chars = string.ascii_lowercase
					repeat_char = random.choice(chars)
					other_chars = [c for c in chars if c != repeat_char]
					base = [random.choice(other_chars) for _ in range(length)]
					triple_positions = random.sample(range(length), 3)
					for pos in triple_positions:
						base[pos] = repeat_char
					username = "".join(base)
				elif pattern == "Quadruples (mmmm, t4444)":
					if numbers_only:
						chars = string.digits
					elif include_numbers:
						chars = string.ascii_lowercase + string.digits
					else:
						chars = string.ascii_lowercase
					repeat_char = random.choice(chars)
					other_chars = [c for c in chars if c != repeat_char]
					base = [random.choice(other_chars) for _ in range(length)]
					# Ensure we have at least 4 positions for quadruples
					if length >= 4:
						quad_positions = random.sample(range(length), 4)
						for pos in quad_positions:
							base[pos] = repeat_char
					else:
						# If length < 4, just fill what we can
						for i in range(min(length, 4)):
							base[i] = repeat_char
					username = "".join(base)
				elif pattern == "Vowels only (aeiou)":
					if numbers_only:
						username = "".join(random.choice(string.digits) for _ in range(length))
					else:
						vowels = "aeiou"
						username = "".join(random.choice(vowels) for _ in range(length))
				elif pattern == "One line letters (aceimnorsuvwxz)":
					if numbers_only:
						username = "".join(random.choice(string.digits) for _ in range(length))
					else:
						one_line_chars = "aceimnorsuvwxz"
						username = "".join(random.choice(one_line_chars) for _ in range(length))
				username = prefix + username + suffix
				# Roblox username validation: 3-20 chars, letters, numbers, underscores
				username = ''.join(c for c in username if c.isalnum() or c == '_')
				if 3 <= len(username) <= 20 and username not in generated and not self.is_problematic_username(username):
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
					"color": 5763719,
					"footer": {
						"text": "Roblox Username Checker - Webhook Test"
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

	def load_proxies_from_file(self):
		fname, _ = QFileDialog.getOpenFileName(self, "Load Proxy List", "", "Text Files (*.txt);;All (*)")
		if fname:
			try:
				with open(fname, "r", encoding="utf-8") as f:
					proxies = [line.strip() for line in f if line.strip()]
				self.proxy_input.setText("\n".join(proxies))
				self.proxy_count_lbl.setText(f"Proxies loaded: {len(proxies)}")
			except Exception as e:
				QMessageBox.critical(self, "Error", f"Failed to load proxies:\n{str(e)}")

	def get_proxies(self):
		txt = self.proxy_input.toPlainText().strip()
		if not txt:
			self.proxy_count_lbl.setText("Proxies loaded: 0")
			return []
		proxies = [line.strip() for line in txt.splitlines() if line.strip() and ("http://" in line or "https://" in line or "socks5://" in line)]
		self.proxy_count_lbl.setText(f"Proxies loaded: {len(proxies)}")
		return proxies

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
		if proxies:
			status_text += f" with {len(proxies)} proxies"
		if save_to_file:
			status_text += " (saving to file)"
		if webhook_url:
			status_text += " (webhook enabled)"
		status_text += "..."
		self.status_label.setText(status_text)
		self.status_label.setStyleSheet("padding: 8px; font-weight: bold; background-color: #fff9c4; border-radius: 3px;")
		self.active_checker = Checker(usernames, webhook_url, debug, save_to_file, proxies)
		self.active_checker.update.connect(self.update_text)
		self.active_checker.pupdate.connect(self.update_progress)
		self.active_checker.finished.connect(self.checking_finished)
		self.active_checker.start()

	def stop_clicked(self):
		if self.active_checker:
			self.active_checker.stop()
			self.active_checker.quit()
			self.active_checker.wait(2000)
		self.checking_finished()

	def checking_finished(self):
		self.start_button.setEnabled(True)
		self.stop_button.setEnabled(False)
		self.status_label.setText("✅ Checking complete!")
		self.status_label.setStyleSheet("padding: 8px; font-weight: bold; background-color: #c8e6c9; border-radius: 3px;")

	def update_text(self, text):
		self.output_text.append(text)
		cursor = self.output_text.textCursor()
		cursor.movePosition(cursor.End)
		self.output_text.setTextCursor(cursor)

	def update_progress(self, value):
		self.progress_bar.setValue(value)
		total = self.progress_bar.maximum()
		percent = 0
		if total and total > 0:
			percent = int((value / total) * 100)
		self.status_label.setText(f"🔄 Progress: {value}/{total} ({percent}%)")

	def get_usernames(self):
		txt = self.input_text.toPlainText().strip()
		usernames = []
		for line in txt.splitlines():
			u = line.strip()
			# Roblox allows letters, numbers, underscores, 3-20 chars
			if u and all(c.isalnum() or c == '_' for c in u) and 3 <= len(u) <= 20:
				usernames.append(u)
		return list(dict.fromkeys(usernames))

# ------------------- Run ------------------- #
if __name__ == "__main__":
	app = QApplication(sys.argv)
	w = App()
	w.show()
	sys.exit(app.exec_())
