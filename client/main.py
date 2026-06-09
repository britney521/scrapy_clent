import os
import sys
import json
import time
import random
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import requests
from PySide6.QtCore import QAbstractTableModel, QModelIndex, QObject, QSettings, Qt, QThread, QTimer, Signal
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QTableView,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from api_client import ApiClient
from common.logging_config import log_debug
from common.project_settings import (
    CRAWLER_API_BASE,
    CRAWLER_API_PASSWORD,
    CRAWLER_API_USERNAME,
    CRAWLER_BROWSER_PATH,
    CRAWLER_BROWSER_USER_DATA,
    CRAWLER_DATA_DIR,
    QT_SETTINGS_APP,
    QT_SETTINGS_ORG,
    TASK_CLAIM_TIMEOUT_SECONDS,
)
from scasrpy import fetch_product
from DrissionPage import Chromium, ChromiumOptions


API_BASE_URL = CRAWLER_API_BASE
API_USERNAME = CRAWLER_API_USERNAME
API_PASSWORD = CRAWLER_API_PASSWORD
BROWSER_PATH = CRAWLER_BROWSER_PATH
BROWSER_USER_DATA_PATH = CRAWLER_BROWSER_USER_DATA
DATA_DIR = Path(CRAWLER_DATA_DIR)
SETTINGS_ORG = QT_SETTINGS_ORG
SETTINGS_APP = QT_SETTINGS_APP


def debug_log(title: str, payload: Any = None) -> None:
    log_debug(title, payload, app_name='client')


def friendly_api_error(exc: Exception, fallback: str) -> str:
    if isinstance(exc, requests.HTTPError) and exc.response is not None:
        try:
            payload = exc.response.json()
        except ValueError:
            payload = {}
        message = extract_error_message(payload)
        if message:
            return message
        if exc.response.status_code == 400:
            return fallback
        if exc.response.status_code in (401, 403):
            return '账号未授权，请重新登录'
    if isinstance(exc, requests.ConnectionError):
        return '无法连接服务端，请确认后台服务已启动'
    if isinstance(exc, requests.Timeout):
        return '请求超时，请稍后重试'
    return fallback


def extract_error_message(payload: Any) -> str:
    if isinstance(payload, str):
        return payload
    if isinstance(payload, list):
        return '；'.join(str(item) for item in payload)
    if not isinstance(payload, dict):
        return ''

    messages: list[str] = []
    for key, value in payload.items():
        if key == 'detail':
            messages.append(str(value))
        elif isinstance(value, list):
            messages.extend(str(item) for item in value)
        elif isinstance(value, dict):
            nested = extract_error_message(value)
            if nested:
                messages.append(nested)
        elif value:
            messages.append(str(value))
    return '；'.join(messages)


def parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed




def format_datetime_text(value: str | None) -> str:
    parsed = parse_iso_datetime(value)
    if not parsed:
        return '-'
    return parsed.astimezone().strftime('%Y-%m-%d %H:%M:%S')

def task_seconds_remaining(row: dict) -> int | None:
    if row.get('status') in ('SUCCESS', 'TIMEOUT'):
        return None
    claimed_at = parse_iso_datetime(row.get('claimed_at'))
    if not claimed_at:
        return None
    elapsed = int((datetime.now(timezone.utc) - claimed_at.astimezone(timezone.utc)).total_seconds())
    return max(0, TASK_CLAIM_TIMEOUT_SECONDS - elapsed)


def task_countdown_text(row: dict) -> str:
    remaining = task_seconds_remaining(row)
    if remaining is None:
        return '-'
    return f'{remaining // 60:02d}:{remaining % 60:02d}'


def is_timeout_message(message: str) -> bool:
    return '超过2分钟' in (message or '') or '已标记为超时' in (message or '') or '已超时' in (message or '')


def format_seconds(seconds: int) -> str:
    seconds = max(0, int(seconds))
    return f'{seconds // 60:02d}:{seconds % 60:02d}'


def normalize_task(task: dict) -> dict:
    return {
        'task_id': int(task.get('id') or task.get('task_id') or task.get('external_task_id')),
        'task_name': task.get('task_name') or '',
        'target_url': task.get('target_url') or '',
        'status': task.get('status') or 'PENDING',
        'last_error': task.get('last_error') or '',
        'claimed_at': task.get('claimed_at') or '',
        'raw': task,
    }


def save_task_json(task_id: int, payload: list[dict]) -> Path:
    task_dir = DATA_DIR / str(task_id)
    task_dir.mkdir(parents=True, exist_ok=True)
    output = task_dir / 'product_data.json'
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
    return output


class LoginDialog(QDialog):
    def __init__(self, parent=None, username: str = '', password: str = '', remember: bool = True):
        super().__init__(parent)
        self.setWindowTitle('账号登录')
        self.setMinimumWidth(420)
        self.setStyleSheet('''
            QDialog {
                background: #f7f8fa;
            }
            QLabel#TitleLabel {
                color: #1f2937;
                font-size: 20px;
                font-weight: 700;
            }
            QLabel#HintLabel {
                color: #6b7280;
                font-size: 12px;
            }
            QLabel#StatusLabel {
                color: #b91c1c;
                min-height: 22px;
            }
            QLineEdit {
                background: white;
                border: 1px solid #d1d5db;
                border-radius: 6px;
                padding: 8px 10px;
                min-height: 20px;
            }
            QLineEdit:focus {
                border-color: #2563eb;
            }
            QTabWidget::pane {
                border: 1px solid #e5e7eb;
                border-radius: 6px;
                background: white;
                top: -1px;
            }
            QTabBar::tab {
                padding: 8px 18px;
                background: #eef2f7;
                border: 1px solid #e5e7eb;
                border-bottom: none;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
            }
            QTabBar::tab:selected {
                background: white;
                color: #111827;
                font-weight: 600;
            }
            QPushButton {
                border: none;
                border-radius: 6px;
                padding: 8px 14px;
                background: #e5e7eb;
                color: #111827;
            }
            QPushButton#PrimaryButton {
                background: #2563eb;
                color: white;
                font-weight: 600;
            }
            QPushButton#PrimaryButton:hover {
                background: #1d4ed8;
            }
        ''')

        title = QLabel('分布式爬虫客户端')
        title.setObjectName('TitleLabel')
        hint = QLabel('登录后才能领取任务、上报状态和同步数据')
        hint.setObjectName('HintLabel')

        self.login_username_edit = QLineEdit(username)
        self.login_username_edit.setPlaceholderText('请输入用户名')
        self.login_password_edit = QLineEdit(password)
        self.login_password_edit.setPlaceholderText('请输入密码')
        self.login_password_edit.setEchoMode(QLineEdit.Password)
        self.remember_checkbox = QCheckBox('记住登录状态')
        self.remember_checkbox.setChecked(remember)

        self.register_username_edit = QLineEdit()
        self.register_username_edit.setPlaceholderText('3-150 个字符')
        self.register_password_edit = QLineEdit()
        self.register_password_edit.setPlaceholderText('至少 8 位，不能是纯数字或常见密码')
        self.register_password_edit.setEchoMode(QLineEdit.Password)
        self.confirm_password_edit = QLineEdit()
        self.confirm_password_edit.setPlaceholderText('再次输入密码')
        self.confirm_password_edit.setEchoMode(QLineEdit.Password)

        self.status_label = QLabel('')
        self.status_label.setObjectName('StatusLabel')
        self.status_label.setWordWrap(True)

        tabs = QTabWidget()
        tabs.addTab(self._build_login_tab(), '登录')
        tabs.addTab(self._build_register_tab(), '注册')

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(12)
        layout.addWidget(title)
        layout.addWidget(hint)
        layout.addWidget(tabs)
        layout.addWidget(self.status_label)

        self.username = ''
        self.password = ''
        self.remember = remember
        QTimer.singleShot(0, self.login_username_edit.setFocus)

    def _build_login_tab(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        form.setContentsMargins(18, 18, 18, 14)
        form.setSpacing(12)
        form.addRow('用户名', self.login_username_edit)
        form.addRow('密码', self.login_password_edit)
        form.addRow('', self.remember_checkbox)

        buttons = QWidget()
        row = QHBoxLayout(buttons)
        row.setContentsMargins(0, 8, 0, 0)
        row.addStretch(1)
        cancel_button = QPushButton('取消')
        login_button = QPushButton('登录')
        login_button.setObjectName('PrimaryButton')
        cancel_button.clicked.connect(self.reject)
        login_button.clicked.connect(self.login)
        row.addWidget(cancel_button)
        row.addWidget(login_button)
        form.addRow(buttons)
        return page

    def _build_register_tab(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        form.setContentsMargins(18, 18, 18, 14)
        form.setSpacing(12)
        form.addRow('用户名', self.register_username_edit)
        form.addRow('密码', self.register_password_edit)
        form.addRow('确认密码', self.confirm_password_edit)

        buttons = QWidget()
        row = QHBoxLayout(buttons)
        row.setContentsMargins(0, 8, 0, 0)
        row.addStretch(1)
        register_button = QPushButton('注册并登录')
        register_button.setObjectName('PrimaryButton')
        register_button.clicked.connect(self.register)
        row.addWidget(register_button)
        form.addRow(buttons)
        return page

    def _login_credentials(self) -> tuple[str, str] | None:
        username = self.login_username_edit.text().strip()
        password = self.login_password_edit.text()
        if not username or not password:
            self.status_label.setText('请输入用户名和密码')
            return None
        return username, password

    def _register_credentials(self) -> tuple[str, str] | None:
        username = self.register_username_edit.text().strip()
        password = self.register_password_edit.text()
        confirm_password = self.confirm_password_edit.text()
        if len(username) < 3:
            self.status_label.setText('用户名至少 3 个字符')
            return None
        if not password or not confirm_password:
            self.status_label.setText('请输入密码和确认密码')
            return None
        if len(password) < 8:
            self.status_label.setText('密码至少 8 位')
            return None
        if password.isdigit():
            self.status_label.setText('密码不能全是数字')
            return None
        if password != confirm_password:
            self.status_label.setText('两次输入的密码不一致')
            return None
        return username, password

    def _set_success(self, username: str, password: str):
        self.username = username
        self.password = password
        self.remember = self.remember_checkbox.isChecked()
        self.accept()

    def login(self):
        credentials = self._login_credentials()
        if credentials is None:
            return
        username, password = credentials
        try:
            ApiClient(API_BASE_URL).login(username, password)
            self._set_success(username, password)
        except Exception as exc:
            self.status_label.setText(f'登录失败：{friendly_api_error(exc, "用户名或密码错误")}')

    def register(self):
        credentials = self._register_credentials()
        if credentials is None:
            return
        username, password = credentials
        try:
            api = ApiClient(API_BASE_URL)
            api.register(username, password)
            api.login(username, password)
            self._set_success(username, password)
        except Exception as exc:
            self.status_label.setText(f'注册失败：{friendly_api_error(exc, "注册信息不符合要求")}')

    def showEvent(self, event):
        super().showEvent(event)
        QTimer.singleShot(0, self.login_username_edit.setFocus)


class TaskTableModel(QAbstractTableModel):
    headers = ['任务ID', '任务名', '目标URL', '状态', '领取时间', '倒计时']

    def __init__(self):
        super().__init__()
        self.all_rows: list[dict[str, Any]] = []
        self.rows: list[dict[str, Any]] = []
        self.status_filter = 'ALL'

    def set_tasks(self, tasks: list[dict]):
        self.beginResetModel()
        deduped: list[dict[str, Any]] = []
        seen: set[int] = set()
        for task in tasks:
            normalized = normalize_task(task)
            task_id = int(normalized['task_id'])
            if task_id in seen:
                continue
            seen.add(task_id)
            deduped.append(normalized)
        self.all_rows = deduped
        for row in self.all_rows:
            remaining = task_seconds_remaining(row)
            if remaining == 0 and row.get('status') in ('CLAIMED', 'RUNNING'):
                row['status'] = 'TIMEOUT'
                row['last_error'] = '任务领取后超过2分钟未完成上传，已超时'
        self.rows = self.apply_filter(self.all_rows)
        self.endResetModel()

    def reload(self):
        self.beginResetModel()
        for row in self.all_rows:
            remaining = task_seconds_remaining(row)
            if remaining == 0 and row.get('status') in ('CLAIMED', 'RUNNING'):
                row['status'] = 'TIMEOUT'
                row['last_error'] = '任务领取后超过2分钟未完成上传，已超时'
        self.rows = self.apply_filter(self.all_rows)
        self.endResetModel()

    def upsert_task(self, task: dict):
        normalized = normalize_task(task)
        self.beginResetModel()
        self.all_rows = [row for row in self.all_rows if int(row['task_id']) != int(normalized['task_id'])]
        self.all_rows.insert(0, normalized)
        self.rows = self.apply_filter(self.all_rows)
        self.endResetModel()

    def update_task_status(self, task_id: int, status: str, last_error: str = ''):
        for row in self.all_rows:
            if int(row['task_id']) == int(task_id):
                row['status'] = status
                row['last_error'] = last_error
                break
        self.reload()

    def set_status_filter(self, status_filter: str):
        self.status_filter = status_filter
        self.reload()

    def apply_filter(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if self.status_filter == 'SUCCESS':
            return [row for row in rows if row.get('status') == 'SUCCESS']
        if self.status_filter == 'INCOMPLETE':
            return [row for row in rows if row.get('status') != 'SUCCESS']
        return rows

    def rowCount(self, parent=QModelIndex()):
        return len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return len(self.headers)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or role not in (Qt.DisplayRole, Qt.EditRole):
            return None
        row = self.rows[index.row()]
        col = index.column()
        if col == 0:
            return row.get('task_id')
        if col == 1:
            return row.get('task_name') or ''
        if col == 2:
            return row.get('target_url') or ''
        if col == 3:
            return self.display_status(row.get('status') or '')
        if col == 4:
            return format_datetime_text(row.get('claimed_at'))
        if col == 5:
            return task_countdown_text(row)
        return None

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return self.headers[section]
        return None

    def task_at(self, row: int) -> dict:
        return self.rows[row]

    @staticmethod
    def display_status(status: str) -> str:
        if status == 'SUCCESS':
            return '完成'
        if status == 'TIMEOUT':
            return '已超时'
        if status == 'RUNNING':
            return '进行中'
        return '未完成'



class SpiderWorker(QThread):
    status_changed = Signal(object, str, str)
    data_fetched = Signal(object, list)
    login_required = Signal(object, str)

    def __init__(self, task_id: int, target_url: str, min_delay: int = 10, max_delay: int = 15):
        super().__init__()
        self.task_id = task_id
        self.target_url = target_url
        self.min_delay = max(0, int(min_delay))
        self.max_delay = max(self.min_delay, int(max_delay))

    def run(self):
        debug_log('启动爬虫线程', {
            'taskId': str(self.task_id),
            'targetUrl': self.target_url,
            'browserPath': BROWSER_PATH,
            'userDataPath': BROWSER_USER_DATA_PATH,
            'minDelay': self.min_delay,
            'maxDelay': self.max_delay,
        })
        self.status_changed.emit(self.task_id, 'RUNNING', '')
        browser = None
        try:
            if ChromiumOptions is None or Chromium is None:
                raise RuntimeError('DrissionPage 未安装，请先 pip install -r requirements.txt')
            os.makedirs(BROWSER_USER_DATA_PATH, exist_ok=True)
            wait_seconds = random.randint(self.min_delay, self.max_delay)
            debug_log('访问目标网站前随机等待', {'taskId': str(self.task_id), 'waitSeconds': wait_seconds})
            time.sleep(wait_seconds)
            if self.isInterruptionRequested():
                raise RuntimeError('任务已停止，访问前中断')
            co = ChromiumOptions().set_browser_path(BROWSER_PATH).set_user_data_path(BROWSER_USER_DATA_PATH)
            # co.headless(True)
            browser = Chromium(co)
            page = browser.get_tab()
            product = fetch_product(page, self.target_url)
            if self.isInterruptionRequested():
                raise RuntimeError('任务已重新获取，旧任务中断')
            if product.get('login_required'):
                message = product.get('error') or '需要登录淘宝账号后再获取'
                self.login_required.emit(self.task_id, message)
                debug_log('检测到需要登录，等待 30 秒后重试', {'taskId': str(self.task_id), 'message': message})
                time.sleep(30)
                if self.isInterruptionRequested():
                    raise RuntimeError('任务已重新获取，旧任务中断')
                product = fetch_product(page, self.target_url)
                if product.get('login_required'):
                    raise RuntimeError('等待 30 秒后仍未登录，任务失败')
            if self.isInterruptionRequested():
                raise RuntimeError('任务已重新获取，旧任务中断')
            debug_log('爬虫获取到商品数据', {'taskId': str(self.task_id), 'product': product})
            data = [product]
            self.data_fetched.emit(self.task_id, data)
        except Exception as exc:
            debug_log('爬虫任务异常', {'taskId': str(self.task_id), 'error': str(exc)})
            self.status_changed.emit(self.task_id, 'FAILED', str(exc))
        finally:
            if browser is not None:
                try:
                    browser.quit()
                except Exception:
                    pass


class SyncWorker(QObject):
    finished = Signal(bool, str)

    def __init__(self, task_id: int, data: list, username: str, password: str):
        super().__init__()
        self.task_id = task_id
        self.data = data
        self.username = username
        self.password = password

    def sync(self):
        try:
            api = ApiClient(API_BASE_URL, self.username, self.password)
            debug_log('开始上传商品数据到服务端', {'taskId': str(self.task_id), 'data': self.data})
            response = api.post_data(self.task_id, self.data)
            debug_log('上传商品数据成功', {'taskId': str(self.task_id), 'response': response})
            if response.get('status') != 'success':
                self.finished.emit(False, response.get('message') or f'服务端返回非 success：{response}')
                return
            self.finished.emit(True, '')
        except Exception as exc:
            response_text = ''
            response = getattr(exc, 'response', None)
            if response is not None:
                response_text = getattr(response, 'text', '') or ''
            debug_log('上传商品数据失败', {
                'taskId': str(self.task_id),
                'exception': str(exc),
                'responseText': response_text[:2000],
            })
            self.finished.emit(False, friendly_api_error(exc, '数据上传失败，请稍后重试'))


class MainWindow(QMainWindow):
    sync_finished = Signal(object, bool, str)

    def __init__(self):
        super().__init__()
        self.setWindowTitle('分布式爬虫客户端')
        self.resize(1100, 600)
        self.workers: dict[int, SpiderWorker] = {}
        self.sync_threads: list[QThread] = []
        self.sync_workers: list[SyncWorker] = []
        self.is_fetching_tasks = False
        self.auto_running = False
        self.current_task_id: int | None = None
        self.finished_task_ids: set[int] = set()
        self.settings = QSettings(SETTINGS_ORG, SETTINGS_APP)
        self.api_username = API_USERNAME or self.settings.value('auth/username', '', str)
        self.api_password = API_PASSWORD or self.settings.value('auth/password', '', str)
        self.remember_login = self.settings.value('auth/remember', False, bool)

        self.model = TaskTableModel()
        self.sync_finished.connect(self.on_sync_finished)
        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setWordWrap(False)
        self.table.setHorizontalScrollMode(QTableView.ScrollPerPixel)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Interactive)
        header.setStretchLastSection(False)
        header.setMinimumSectionSize(90)
        self.apply_table_column_widths()

        toolbar = QToolBar('工具栏')
        self.login_btn = QPushButton('登录/注册')
        self.login_btn.clicked.connect(self.show_login_dialog)
        self.user_label = QLabel('')
        self.user_label.setStyleSheet('color: #374151; padding: 0 8px;')
        self.logout_btn = QPushButton('退出登录')
        self.logout_btn.clicked.connect(self.logout)
        self.refresh_btn = QPushButton('刷新后台任务')
        self.refresh_btn.clicked.connect(self.refresh_local)
        self.status_filter_box = QComboBox()
        self.status_filter_box.addItem('全部任务', 'ALL')
        self.status_filter_box.addItem('未完成', 'INCOMPLETE')
        self.status_filter_box.addItem('完成', 'SUCCESS')
        self.status_filter_box.currentIndexChanged.connect(self.on_status_filter_changed)
        self.min_delay_edit = QLineEdit(str(self.settings.value('crawler/min_delay', 10, int) or 10))
        self.min_delay_edit.setFixedWidth(54)
        self.max_delay_edit = QLineEdit(str(self.settings.value('crawler/max_delay', 15, int) or 15))
        self.max_delay_edit.setFixedWidth(54)
        self.auto_btn = QPushButton('开始执行任务')
        self.auto_btn.setObjectName('PrimaryButton')
        self.auto_btn.clicked.connect(self.toggle_auto_run)
        self.login_action = toolbar.addWidget(self.login_btn)
        self.user_action = toolbar.addWidget(self.user_label)
        self.logout_action = toolbar.addWidget(self.logout_btn)
        toolbar.addWidget(self.refresh_btn)
        toolbar.addWidget(QLabel('状态筛选：'))
        toolbar.addWidget(self.status_filter_box)
        toolbar.addSeparator()
        toolbar.addWidget(QLabel('访问间隔：'))
        toolbar.addWidget(self.min_delay_edit)
        toolbar.addWidget(QLabel('-'))
        toolbar.addWidget(self.max_delay_edit)
        toolbar.addWidget(QLabel('秒'))
        toolbar.addWidget(self.auto_btn)
        self.addToolBar(toolbar)

        root = QWidget()
        layout = QHBoxLayout(root)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.addWidget(self.table)
        self.setCentralWidget(root)
        self.update_auth_ui()
        self.countdown_timer = QTimer(self)
        self.countdown_timer.timeout.connect(self.refresh_countdown)
        self.countdown_timer.start(1000)
        self.update_auto_button_state()

        QTimer.singleShot(100, self.after_window_ready)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.apply_table_column_widths()

    def after_window_ready(self):
        if not self.api_username or not self.api_password:
            self.show_login_dialog()
            return
        self.refresh_local()

    def apply_table_column_widths(self):
        if not hasattr(self, 'table'):
            return
        width = max(self.table.viewport().width(), 900)
        task_name_width = int(width * 0.20)
        claimed_width = 170
        countdown_width = 90
        columns = [
            (0, 190),
            (1, task_name_width),
            (2, max(360, width - 190 - task_name_width - 110 - claimed_width - countdown_width - 36)),
            (3, 110),
            (4, claimed_width),
            (5, countdown_width),
        ]
        for column, column_width in columns:
            self.table.setColumnWidth(column, column_width)

    def refresh_countdown(self):
        has_claimed_task = any(row.get('claimed_at') and row.get('status') != 'SUCCESS' for row in self.model.all_rows)
        if has_claimed_task:
            self.model.reload()

    def on_status_filter_changed(self):
        self.model.set_status_filter(self.status_filter_box.currentData())

    def update_auto_button_state(self):
        if not hasattr(self, 'auto_btn'):
            return
        if self.is_fetching_tasks:
            self.auto_btn.setEnabled(False)
            self.auto_btn.setText('请求任务中...')
            return
        self.auto_btn.setEnabled(bool(self.api_username and self.api_password))
        if self.auto_running:
            self.auto_btn.setText('停止执行')
            self.auto_btn.setStyleSheet('background:#dc2626;color:white;font-weight:600;border-radius:6px;padding:6px 12px;')
        else:
            self.auto_btn.setText('开始执行任务')
            self.auto_btn.setStyleSheet('background:#2563eb;color:white;font-weight:600;border-radius:6px;padding:6px 12px;')

    def show_login_dialog(self):
        dialog = LoginDialog(
            self,
            username=self.api_username,
            password=self.api_password,
            remember=True,
        )
        if dialog.exec() == QDialog.Accepted:
            self.api_username = dialog.username
            self.api_password = dialog.password
            self.remember_login = dialog.remember
            if self.remember_login:
                self.save_login()
            else:
                self.clear_saved_login()
            self.setWindowTitle(f'分布式爬虫客户端 - {self.api_username}')
            self.update_auth_ui()
            QTimer.singleShot(0, self.refresh_local)

    def logout(self):
        self.api_username = ''
        self.api_password = ''
        self.remember_login = False
        self.clear_saved_login()
        self.setWindowTitle('分布式爬虫客户端')
        self.model.set_tasks([])
        self.update_auth_ui()
        self.statusBar().showMessage('已退出登录', 3000)

    def save_login(self):
        self.settings.setValue('auth/username', self.api_username)
        self.settings.setValue('auth/password', self.api_password)
        self.settings.setValue('auth/remember', True)
        self.settings.sync()

    def clear_saved_login(self):
        self.settings.remove('auth')
        self.settings.sync()

    def update_auth_ui(self):
        logged_in = bool(self.api_username and self.api_password)
        self.login_btn.setVisible(not logged_in)
        self.login_action.setVisible(not logged_in)
        self.user_label.setVisible(logged_in)
        self.user_action.setVisible(logged_in)
        self.logout_btn.setVisible(logged_in)
        self.logout_action.setVisible(logged_in)
        self.user_label.setText(f'当前用户：{self.api_username}' if logged_in else '')
        if logged_in:
            self.setWindowTitle(f'分布式爬虫客户端 - {self.api_username}')
        self.update_auto_button_state()

    def refresh_local(self):
        if not self.ensure_logged_in():
            return
        try:
            tasks = ApiClient(API_BASE_URL, self.api_username, self.api_password).my_tasks()
            self.model.set_tasks(tasks)
            self.statusBar().showMessage('后台任务已刷新', 3000)
        except Exception as exc:
            QMessageBox.warning(self, '刷新失败', friendly_api_error(exc, '后台任务刷新失败，请稍后重试'))

    def toggle_auto_run(self):
        if self.auto_running:
            self.stop_auto_run('已停止自动执行任务')
            return
        if not self.ensure_logged_in():
            return
        self.auto_running = True
        self.finished_task_ids.clear()
        debug_log('自动执行任务已启动', {'username': self.api_username, 'apiBaseUrl': API_BASE_URL})
        self.statusBar().showMessage('自动执行已启动：请求任务 → 爬取 → 上传 → 请求下一任务', 5000)
        self.update_auto_button_state()
        QTimer.singleShot(0, self.run_next_task)

    def stop_auto_run(self, message: str = '已停止自动执行任务'):
        self.auto_running = False
        self.current_task_id = None
        for task_id, worker in list(self.workers.items()):
            if worker.isRunning():
                worker.requestInterruption()
        debug_log('自动执行任务已停止', {'username': self.api_username})
        self.statusBar().showMessage(message, 4000)
        self.update_auto_button_state()

    def schedule_next_task(self, delay_ms: int = 1000):
        if not self.auto_running:
            return
        QTimer.singleShot(max(0, int(delay_ms)), self.run_next_task)

    def run_next_task(self):
        if not self.auto_running:
            return
        if not self.ensure_logged_in():
            self.stop_auto_run('未登录，自动执行已停止')
            return
        if self.is_fetching_tasks:
            debug_log('领取任务被忽略：已有领取请求进行中', {'username': self.api_username})
            return
        self.is_fetching_tasks = True
        self.update_auto_button_state()
        try:
            debug_log('开始从服务端队列领取任务', {'username': self.api_username, 'apiBaseUrl': API_BASE_URL})
            min_delay, max_delay = self.get_visit_delay_settings()
            tasks = ApiClient(API_BASE_URL, self.api_username, self.api_password).fetch_tasks(limit=1)
            debug_log('从服务端队列领取任务成功', {'username': self.api_username, 'count': len(tasks), 'tasks': tasks})
            self.model.set_tasks(tasks + self.model.all_rows)
            if not tasks:
                self.statusBar().showMessage('当前没有可领取任务，10 秒后自动重试', 5000)
                self.schedule_next_task(10000)
                return
            task = normalize_task(tasks[0])
            self.current_task_id = int(task['task_id'])
            debug_log('已领取任务，客户端本地准备执行商品采集', {
                'taskId': str(self.current_task_id),
                'minDelay': min_delay,
                'maxDelay': max_delay,
            })
            self.start_task(task, show_running_message=False, min_delay=min_delay, max_delay=max_delay)
        except Exception as exc:
            message = friendly_api_error(exc, '领取任务失败，请稍后重试')
            response = getattr(exc, 'response', None)
            response_text = ''
            if response is not None:
                response_text = getattr(response, 'text', '') or ''
            debug_log('从服务端队列领取任务失败', {
                'username': self.api_username,
                'exception': str(exc),
                'message': message,
                'responseText': response_text[:2000],
            })
            self.statusBar().showMessage(f'请求任务失败：{message}，10 秒后自动重试', 8000)
            self.schedule_next_task(10000)
        finally:
            self.is_fetching_tasks = False
            self.update_auto_button_state()
            debug_log('领取任务流程结束', {
                'username': self.api_username,
            })

    def get_visit_delay_settings(self) -> tuple[int, int]:
        def parse(edit: QLineEdit, default: int) -> int:
            try:
                return max(0, int(edit.text().strip()))
            except (TypeError, ValueError):
                return default

        min_delay = parse(self.min_delay_edit, 10)
        max_delay = parse(self.max_delay_edit, 15)
        if max_delay < min_delay:
            max_delay = min_delay
            self.max_delay_edit.setText(str(max_delay))
        self.settings.setValue('crawler/min_delay', min_delay)
        self.settings.setValue('crawler/max_delay', max_delay)
        self.settings.sync()
        return min_delay, max_delay

    def start_task(self, task: dict, show_running_message: bool = True, min_delay: int | None = None, max_delay: int | None = None) -> bool:
        task_id = int(task['task_id'])
        status = task.get('status') or ''
        if status == 'SUCCESS':
            if show_running_message:
                QMessageBox.information(self, '提示', f'任务 {task_id} 已完成')
            return False
        if status == 'TIMEOUT':
            if show_running_message:
                QMessageBox.information(self, '提示', f'任务 {task_id} 已超时，不能再次启动')
            return False
        if task_id in self.workers and self.workers[task_id].isRunning():
            self.workers[task_id].requestInterruption()
            self.workers.pop(task_id, None)
            self.model.update_task_status(task_id, 'PENDING', '重新获取任务')
        self.statusBar().showMessage(f'任务 {task_id} 已启动，正在爬取...', 3000)
        debug_log('点击启动任务', {'taskId': str(task_id), 'targetUrl': task.get('target_url'), 'status': status})
        if min_delay is None or max_delay is None:
            min_delay, max_delay = self.get_visit_delay_settings()
        worker = SpiderWorker(task_id, task['target_url'], min_delay=min_delay, max_delay=max_delay)
        worker.status_changed.connect(self.on_status_changed)
        worker.data_fetched.connect(self.on_data_fetched)
        worker.login_required.connect(self.on_login_required)
        worker.finished.connect(lambda tid=task_id: self.workers.pop(tid, None))
        self.workers[task_id] = worker
        worker.start()
        return True

    def on_login_required(self, task_id: object, message: str):
        task_id = int(task_id)
        debug_log('任务需要登录', {'taskId': str(task_id), 'message': message, 'waitSeconds': 30})
        self.statusBar().showMessage(f'任务 {task_id} 需要登录，请在 30 秒内完成登录', 20000)

    def on_status_changed(self, task_id: object, status: str, error_msg: str):
        task_id = int(task_id)
        self.model.update_task_status(task_id, status, error_msg)
        try:
            response = ApiClient(API_BASE_URL, self.api_username, self.api_password).post_status(task_id, status, error_msg)
            self.model.upsert_task(response)
            debug_log('回传服务端状态成功', {'taskId': str(task_id), 'status': status, 'error': error_msg, 'response': response})
        except Exception as exc:
            message = friendly_api_error(exc, '状态上报失败，已保存在本地')
            debug_log('回传服务端状态失败', {'taskId': str(task_id), 'status': status, 'error': error_msg, 'exception': str(exc), 'message': message})
            if is_timeout_message(message):
                self.model.update_task_status(task_id, 'TIMEOUT', message)
            self.statusBar().showMessage(message, 5000)
        if status == 'FAILED':
            self.statusBar().showMessage(f'任务 {task_id} 失败：{error_msg}', 8000)
            self.mark_auto_task_finished(task_id, delay_ms=1000)
        self.refresh_local()

    def on_data_fetched(self, task_id: object, data: list):
        task_id = int(task_id)
        try:
            payload = self.build_upload_payload(task_id, data)
            debug_log('准备上传商品数据', {'taskId': str(task_id), 'payload': payload})
            saved_path = save_task_json(task_id, payload)
            debug_log('商品数据已保存到本地JSON文件', {'taskId': str(task_id), 'path': str(saved_path)})
            thread = QThread(self)
            syncer = SyncWorker(task_id, payload, self.api_username, self.api_password)
            syncer.moveToThread(thread)
            thread.started.connect(syncer.sync)
            # 不要从上传线程直接调用 UI 槽函数。macOS 下后台线程创建/触碰窗口会崩溃：
            # NSWindow should only be instantiated on the main thread.
            syncer.finished.connect(lambda ok, msg, tid=task_id: self.sync_finished.emit(tid, ok, msg))
            syncer.finished.connect(thread.quit)
            syncer.finished.connect(syncer.deleteLater)
            thread.finished.connect(thread.deleteLater)
            thread.finished.connect(lambda t=thread: self.sync_threads.remove(t) if t in self.sync_threads else None)
            thread.finished.connect(lambda s=syncer: self.sync_workers.remove(s) if s in self.sync_workers else None)
            self.sync_threads.append(thread)
            self.sync_workers.append(syncer)
            debug_log('上传线程已启动', {'taskId': str(task_id), 'jsonPath': str(saved_path)})
            thread.start()
        except Exception as exc:
            message = f'上传线程启动失败：{exc}'
            debug_log('上传线程启动失败', {'taskId': str(task_id), 'exception': str(exc)})
            self.model.update_task_status(task_id, 'FAILED', message)
            try:
                ApiClient(API_BASE_URL, self.api_username, self.api_password).post_status(task_id, 'FAILED', message)
            except Exception as status_exc:
                debug_log('上传线程启动失败后状态回传失败', {'taskId': str(task_id), 'exception': str(status_exc)})
            self.statusBar().showMessage(f'任务 {task_id} 上传失败：{message}', 8000)
            self.refresh_local()
            self.mark_auto_task_finished(task_id, delay_ms=1000)

    def build_upload_payload(self, task_id: int, products: list) -> list[dict]:
        payload = []
        for product in products:
            product = product if isinstance(product, dict) else {'raw': product}
            payload.append({
                'username': self.api_username,
                'taskId': str(task_id),
                'itemId': str(product.get('item_id') or product.get('itemId') or ''),
                'product': product,
            })
        return payload

    def on_sync_finished(self, task_id: int, ok: bool, msg: str):
        if not ok:
            final_status = 'TIMEOUT' if is_timeout_message(msg) else 'FAILED'
            self.model.update_task_status(task_id, final_status, f'数据未同步：{msg}')
            try:
                response = ApiClient(API_BASE_URL, self.api_username, self.api_password).post_status(task_id, final_status, msg)
                self.model.upsert_task(response)
                debug_log('上传失败后回传失败状态成功', {'taskId': str(task_id), 'response': response})
            except Exception as exc:
                debug_log('上传失败后回传失败状态失败', {'taskId': str(task_id), 'exception': str(exc)})
            self.statusBar().showMessage(f'任务 {task_id} 同步失败：{msg}', 8000)
        else:
            self.model.update_task_status(task_id, 'SUCCESS', '')
            try:
                response = ApiClient(API_BASE_URL, self.api_username, self.api_password).post_status(task_id, 'SUCCESS', '')
                self.model.upsert_task(response)
                debug_log('任务完成状态回传成功', {'taskId': str(task_id), 'response': response})
            except Exception as exc:
                debug_log('任务完成状态回传失败', {'taskId': str(task_id), 'exception': str(exc)})
                self.statusBar().showMessage(f'任务已完成，但状态上报失败：{friendly_api_error(exc, "状态上报失败")}', 5000)
            self.statusBar().showMessage(f'任务 {task_id} 爬取成功，数据已上传', 3000)
        self.refresh_local()
        self.mark_auto_task_finished(task_id, delay_ms=1000)

    def mark_auto_task_finished(self, task_id: int, delay_ms: int = 1000):
        task_id = int(task_id)
        if task_id in self.finished_task_ids:
            return
        self.finished_task_ids.add(task_id)
        if self.current_task_id == task_id:
            self.current_task_id = None
        if self.auto_running:
            debug_log('自动任务单轮结束，准备请求下一任务', {
                'username': self.api_username,
                'taskId': str(task_id),
                'delayMs': delay_ms,
            })
            self.schedule_next_task(delay_ms)

    def ensure_logged_in(self) -> bool:
        if self.api_username and self.api_password:
            return True
        self.show_login_dialog()
        return bool(self.api_username and self.api_password)


if __name__ == '__main__':
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())
