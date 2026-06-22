import sys
import os
import re
import subprocess
import webbrowser
from PyQt5.QtCore import Qt, QSize, QThread, pyqtSignal, pyqtSlot
from PyQt5.QtGui import QFont, QColor, QPalette, QIcon, QPixmap
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QPushButton,
                             QLabel, QHBoxLayout, QVBoxLayout, QScrollArea,
                             QLineEdit, QDialog)

#####################################################
from PyQt5.QtGui import QPixmap, QIcon
from PyQt5.QtCore import QByteArray
from PyQt5.QtCore import QBuffer



##################################################
# ---------------- Global Configuration and Utility Functions ---------------- #

if getattr(sys, 'frozen', False):
    application_path = os.path.dirname(sys.executable)
else:
    application_path = os.path.dirname(os.path.abspath(__file__))

IPS_FILE = os.path.join(application_path, "FastPing_ips.txt")
DEFAULT_IPS = [
    "5.200.200.200",
    "8.8.8.8",
    "4.2.2.4",
    "ac-client-ws.faceit.com",
    "104.19.156.82"
]

if sys.platform.startswith("win"):
    def get_ping_cmd(ip):
        return [r"C:\Windows\System32\ping.exe", "-t", ip]
    TIME_REGEX = re.compile(r"time=(\d+)ms")
    TIMEOUT_REGEX = re.compile(r"Request timed out", re.IGNORECASE)
else:
    def get_ping_cmd(ip):
        return ["ping", ip]
    TIME_REGEX = re.compile(r"time=(\d+(?:\.\d+)?) ms")
    TIMEOUT_REGEX = re.compile(r"Request timeout", re.IGNORECASE)

def load_ips():
    if os.path.exists(IPS_FILE):
        with open(IPS_FILE, "r", encoding="utf-8") as f:
            ips = [line.strip() for line in f if line.strip()]
    else:
        ips = DEFAULT_IPS.copy()
        update_ips_file(ips)
    return ips

def update_ips_file(ips):
    with open(IPS_FILE, "w", encoding="utf-8") as f:
        for ip in ips:
            f.write(ip + "\n")

# ---------------- Custom Widgets and Worker Thread Classes ---------------- #

class CircularButton(QPushButton):
    def __init__(self, text, size=34,
                 bg_color="#2196F3", hover_color="#1976D2", pressed_color="#1565C0",
                 parent=None):
        super().__init__(text, parent)
        self.size = size
        self.setFixedSize(QSize(size, size))
        self.setFont(QFont("Arial", 16))
        self.setStyleSheet(f"""
            QPushButton {{
                border: 2px solid #555;
                border-radius: {size // 2}px;
                background-color: {bg_color};
                color: white;
            }}
            QPushButton:hover {{
                background-color: {hover_color};
            }}
            QPushButton:pressed {{
                background-color: {pressed_color};
            }}
        """)

class PingWorker(QThread):
    latency_signal = pyqtSignal(str)
    packet_loss_signal = pyqtSignal(str)
    
    def __init__(self, ip, parent=None):
        super().__init__(parent)
        self.ip = ip
        self._running = True
        self.interval_total = 0
        self.interval_received = 0
        self.process = None

    def run(self):
        cmd = get_ping_cmd(self.ip)
        creationflags = subprocess.CREATE_NO_WINDOW if sys.platform.startswith("win") else 0
        self.process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                        text=True, creationflags=creationflags)
        while self._running:
            line = self.process.stdout.readline()
            if not line:
                break
            match = TIME_REGEX.search(line)
            if match:
                self.interval_total += 1
                self.interval_received += 1
                latency = match.group(1)
                self.latency_signal.emit(latency)
            elif TIMEOUT_REGEX.search(line):
                self.interval_total += 1
                self.latency_signal.emit("Timeout")
            if self.interval_total >= 40:
                lost = self.interval_total - self.interval_received
                loss_percent = 100 * lost / self.interval_total
                self.packet_loss_signal.emit(f"loss:{loss_percent:.0f}%")
                self.interval_total = 0
                self.interval_received = 0
        if self.process:
            self.process.terminate()

    def stop(self):
        self._running = False
        if self.process:
            try:
                self.process.terminate()
            except Exception:
                pass
        self.wait()

class PingRow(QWidget):
    def __init__(self, ip, remove_callback, parent=None):
        super().__init__(parent)
        self.ip = ip
        self.remove_callback = remove_callback
        
        layout = QHBoxLayout()
        layout.setContentsMargins(5, 2, 5, 2)
        layout.setSpacing(10)
        
        self.ip_label = QLabel(ip)
        self.ip_label.setFont(QFont("Helvetica", 13))
        self.ip_label.setMinimumWidth(140)
        layout.addWidget(self.ip_label)
        
        self.latency_label = QLabel("...")
        self.latency_label.setFont(QFont("Helvetica", 14))
        self.latency_label.setFixedWidth(50)
        layout.addWidget(self.latency_label)
        
        self.packet_loss_label = QLabel("loss:0%")
        self.packet_loss_label.setFont(QFont("Helvetica", 11))
        self.packet_loss_label.setFixedWidth(56)
        layout.addWidget(self.packet_loss_label)
        
        self.delete_button = QPushButton("✕")
        self.delete_button.setFont(QFont("Arial", 11))
        self.delete_button.setFixedSize(20, 20)
        self.delete_button.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: #ff4444;
                border: none;
            }
            QPushButton:hover {
                background-color: #eeeeee;
            }
        """)
        self.delete_button.clicked.connect(self.delete)
        layout.addWidget(self.delete_button)
        
        self.setLayout(layout)
        
        self.worker = PingWorker(ip)
        self.worker.latency_signal.connect(self.update_latency)
        self.worker.packet_loss_signal.connect(self.update_packet_loss)
        self.worker.start()
        
    @pyqtSlot(str)
    def update_latency(self, text):
        self.latency_label.setText(text)
    
    @pyqtSlot(str)
    def update_packet_loss(self, text):
        self.packet_loss_label.setText(text)
    
    def delete(self):
        self.worker.stop()
        self.remove_callback(self.ip)
        self.deleteLater()

# ---------------- Main Application Window ---------------- #

class FastPingApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("FastPing-v1.3")
        self.resize(380, 338)
        self.ips = load_ips()
        self.ping_rows = {}  # Map IP -> PingRow widget
        self.setWindowIcon(QIcon(":/icon2.ico"))
        # self.setWindowIcon(QIcon("favico.ico"))
        self.theme = "dark"
        central_widget = QWidget()
        self.main_layout = QVBoxLayout()
        central_widget.setLayout(self.main_layout)
        self.setCentralWidget(central_widget)
        
        # Top controls container with no margins for a flush look
        top_widget = QWidget()
        top_layout = QHBoxLayout()
        top_layout.setContentsMargins(0, 0, 0, 0)  # No margins so controls are flush with the corner
        top_widget.setLayout(top_layout)
        self.main_layout.addWidget(top_widget)
        
        # Left: Circular buttons with original spacing between them
        button_widget = QWidget()
        button_layout = QHBoxLayout()
        button_layout.setSpacing(5)
        button_widget.setLayout(button_layout)
        btn_size = 34
        
        self.contact_button = CircularButton("📞", size=btn_size,
                                               bg_color="#2196F3",
                                               hover_color="#1976D2",
                                               pressed_color="#1565C0")
        self.contact_button.clicked.connect(self.show_contact_options)
        button_layout.addWidget(self.contact_button)
        
        self.info_button = CircularButton("!", size=btn_size,
                                            bg_color="#2196F3",
                                            hover_color="#1976D2",
                                            pressed_color="#6A1B9A")
        self.info_button.clicked.connect(self.show_info)
        button_layout.addWidget(self.info_button)
        
        self.theme_button = CircularButton("☀", size=btn_size,
                                             bg_color="#757575",
                                             hover_color="#424242",
                                             pressed_color="#333333")
        self.theme_button.clicked.connect(self.toggle_theme)
        button_layout.addWidget(self.theme_button)
        
        top_layout.addWidget(button_widget, alignment=Qt.AlignLeft)
        
        # Right: Link labels with Twitch and GitHub icons using inline style for color
        link_widget = QWidget()
        link_layout = QHBoxLayout()
        link_widget.setLayout(link_layout)
        self.twitch_label = QLabel('<a style="color: #2196F3; text-decoration: none;" href="https://twitch.tv/amirflack">Twitch</a>')
        self.twitch_label.setFont(QFont("Helvetica", 11, QFont.Bold))
        self.twitch_label.setTextFormat(Qt.RichText)
        self.twitch_label.setTextInteractionFlags(Qt.TextBrowserInteraction)
        self.twitch_label.setOpenExternalLinks(True)
        link_layout.addWidget(self.twitch_label)
        
        self.github_label = QLabel('<a style="color: #2196F3; text-decoration: none;" href="https://github.com/AmirFlack">GitHub</a>')
        self.github_label.setFont(QFont("Helvetica", 11, QFont.Bold))
        self.github_label.setTextFormat(Qt.RichText)
        self.github_label.setTextInteractionFlags(Qt.TextBrowserInteraction)
        self.github_label.setOpenExternalLinks(True)
        link_layout.addWidget(self.github_label)
        
        top_layout.addWidget(link_widget, alignment=Qt.AlignRight)
        
        # Scrollable area for ping rows
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.ip_container = QWidget()
        self.ip_layout = QVBoxLayout()
        self.ip_layout.setAlignment(Qt.AlignTop)
        self.ip_container.setLayout(self.ip_layout)
        self.scroll_area.setWidget(self.ip_container)
        self.main_layout.addWidget(self.scroll_area)
        
        for ip in self.ips:
            self.create_ping_row(ip)
        
        # Add IP section
        add_widget = QWidget()
        add_layout = QHBoxLayout()
        add_widget.setLayout(add_layout)
        self.ip_entry = QLineEdit()
        self.ip_entry.setPlaceholderText("Enter IP/hostname")
        self.ip_entry.setFont(QFont("Helvetica", 13))
        self.ip_entry.setFixedWidth(180)
        add_layout.addWidget(self.ip_entry)
        add_button = QPushButton("Add")
        add_button.setFont(QFont("Helvetica", 11, QFont.Bold))
        add_button.setFixedWidth(60)
        add_button.setFixedHeight(30)  # For a pill-shaped look
        add_button.setStyleSheet("background-color: #4CAF50; color: white; border-radius: 15px;")
        add_button.clicked.connect(self.add_ip)
        add_layout.addWidget(add_button)
        self.main_layout.addWidget(add_widget)
        
        self.credits_label = QLabel("credits:Amirhossein_pdr")
        self.credits_label.setFont(QFont("Helvetica", 10))
        self.credits_label.setStyleSheet("color: #B3B3B3;")
        self.credits_label.setAlignment(Qt.AlignLeft)
        self.main_layout.addWidget(self.credits_label)
        
        self.apply_theme()
        self.update_ping_row_colors()
    
    def apply_theme(self):
        palette = QPalette()
        if self.theme == "dark":
            palette.setColor(QPalette.Window, QColor("#2b2b2b"))
            palette.setColor(QPalette.WindowText, QColor("white"))
            palette.setColor(QPalette.Base, QColor("#2b2b2b"))
            palette.setColor(QPalette.Text, QColor("white"))
            self.ip_container.setStyleSheet("background-color: #2b2b2b;")
            # Set the QLineEdit background to #38343c in dark mode
            self.ip_entry.setStyleSheet("background-color: #38343c; color: white; border: 1px solid #38343c;")

        else:
            palette.setColor(QPalette.Window, QColor("white"))
            palette.setColor(QPalette.WindowText, QColor("black"))
            palette.setColor(QPalette.Base, QColor("white"))
            palette.setColor(QPalette.Text, QColor("black"))
            self.ip_container.setStyleSheet("background-color: white;")
            self.ip_entry.setStyleSheet("background-color: white; color: black;")
        self.setPalette(palette)
    
    def update_ping_row_colors(self):
        for ping_row in self.ping_rows.values():
            if self.theme == "dark":
                ping_row.ip_label.setStyleSheet("color: white;")
                ping_row.latency_label.setStyleSheet("color: lightblue;")
                ping_row.packet_loss_label.setStyleSheet("color: orange;")
            else:
                ping_row.ip_label.setStyleSheet("color: black;")
                ping_row.latency_label.setStyleSheet("color: #2196F3;")
                ping_row.packet_loss_label.setStyleSheet("color: red;")
    
    def create_ping_row(self, ip):
        ping_row = PingRow(ip, self.remove_ip)
        self.ip_layout.addWidget(ping_row)
        self.ping_rows[ip] = ping_row
        if self.theme == "dark":
            ping_row.ip_label.setStyleSheet("color: white;")
            ping_row.latency_label.setStyleSheet("color: lightblue;")
            ping_row.packet_loss_label.setStyleSheet("color: orange;")
        else:
            ping_row.ip_label.setStyleSheet("color: black;")
            ping_row.latency_label.setStyleSheet("color: #2196F3;")
            ping_row.packet_loss_label.setStyleSheet("color: red;")
    
    def add_ip(self):
        new_ip = self.ip_entry.text().strip()
        if new_ip and new_ip not in self.ips:
            self.ips.append(new_ip)
            self.create_ping_row(new_ip)
            update_ips_file(self.ips)
        self.ip_entry.clear()
    
    def remove_ip(self, ip):
        if ip in self.ips:
            self.ips.remove(ip)
        if ip in self.ping_rows:
            del self.ping_rows[ip]
        update_ips_file(self.ips)
    
    def toggle_theme(self):
        self.theme = "light" if self.theme == "dark" else "dark"
        self.apply_theme()
        self.update_ping_row_colors()
        self.theme_button.setText("🌙" if self.theme == "dark" else "☀")
    
    def show_contact_options(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("📱 Contact Options")
        dialog.resize(300, 250)
        layout = QVBoxLayout()
        dialog.setLayout(layout)
        
        btn_style = "padding: 10px; font: 13px Arial; min-width:200px;"
        
        telegram_btn = QPushButton("📲 Telegram")
        telegram_btn.setStyleSheet(btn_style + "background-color:#0088CC; color:white;")
        telegram_btn.clicked.connect(lambda: webbrowser.open("https://t.me/amir_pdr"))
        layout.addWidget(telegram_btn)
        
        twitch_btn = QPushButton("🎮 Twitch")
        twitch_btn.setStyleSheet(btn_style + "background-color:#9146FF; color:white;")
        twitch_btn.clicked.connect(lambda: webbrowser.open("https://twitch.tv/amirflack"))
        layout.addWidget(twitch_btn)
        
        steam_btn = QPushButton("⚙️ Steam")
        steam_btn.setStyleSheet(btn_style + "background-color:#1B2838; color:white;")
        steam_btn.clicked.connect(lambda: webbrowser.open("https://steamcommunity.com/id/amir_pdr/"))
        layout.addWidget(steam_btn)
        
        website_btn = QPushButton("🌐 Website")
        website_btn.setStyleSheet(btn_style + "background-color:#4CAF50; color:white;")
        website_btn.clicked.connect(lambda: webbrowser.open("https://amirflack.github.io/"))
        layout.addWidget(website_btn)
        
        dialog.exec_()
    
    def show_info(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("App Information")
        dialog.resize(360, 335)
        layout = QVBoxLayout()
        dialog.setLayout(layout)
        
        info_text = (
            "🚀 FastPing - Network Monitoring Tool\n\n"
            "🌟 Features:\n"
            "  • Real-time latency monitoring\n"
            "  • Packet loss calculation\n"
            "  • Custom IP/hostname tracking\n"
            "  • Dark/Light theme support\n"
            "  • Automatic save/load of IPs\n\n"
            "📖 Usage:\n"
            "  • Click ➕ to add new IPs/hostnames\n"
            "  • Monitor real-time stats 👀\n"
            "  • Remove entries with the ❌ button\n"
            "  • Toggle themes with 🌙/☀ button\n\n"
            "⚠️ Note:\n"
            "  • Timeouts show as 'Timeout' ⏳\n"
            "  • Statistics update every 40 pings 📈\n"
            "📨 Hint:\n    If you have any suggestions or problems\n"
            "    please let me know throw the channels"
        )
        info_label = QLabel(info_text)
        info_label.setFont(QFont("Helvetica", 13))
        info_label.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        info_label.setWordWrap(True)
        layout.addWidget(info_label)
        
        dialog.exec_()

def main():
    app = QApplication(sys.argv)
    window = FastPingApp()
    window.show()
    sys.exit(app.exec_())

if __name__ == '__main__':
    main()
