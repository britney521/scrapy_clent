"""项目公共配置。

客户端和服务端都从这里读取业务参数；环境变量仍可覆盖默认值。
"""

from __future__ import annotations

import os
import platform
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


# 服务端 API / 客户端登录默认值
CRAWLER_API_BASE = os.getenv('CRAWLER_API_BASE', 'http://101.34.208.172:5006/api')
CRAWLER_API_USERNAME = os.getenv('CRAWLER_API_USERNAME', '')
CRAWLER_API_PASSWORD = os.getenv('CRAWLER_API_PASSWORD', '')

# 客户端浏览器配置
if platform.system() == 'Windows':
    DEFAULT_BROWSER_PATH = r'C:\Program Files\Google\Chrome\Application\chrome.exe'
elif platform.system() == 'Darwin':
    DEFAULT_BROWSER_PATH = '/Applications/GPT Chrome.app/Contents/MacOS/GptBrowser'
else:
    DEFAULT_BROWSER_PATH = '/usr/bin/google-chrome'
CRAWLER_BROWSER_PATH = os.getenv('CRAWLER_BROWSER_PATH', DEFAULT_BROWSER_PATH)
CRAWLER_BROWSER_USER_DATA = os.getenv(
    'CRAWLER_BROWSER_USER_DATA',
    os.path.expanduser('~/.crawler_taobao_browser_profile'),
)
CRAWLER_DATA_DIR = os.getenv('CRAWLER_DATA_DIR', str(PROJECT_ROOT / 'crawler_data'))
LOG_DIR = os.getenv('CRAWLER_LOG_DIR', str(PROJECT_ROOT / 'logs'))
LOG_LEVEL = os.getenv('CRAWLER_LOG_LEVEL', 'DEBUG')

# Qt 本地设置命名空间
QT_SETTINGS_ORG = os.getenv('CRAWLER_QT_SETTINGS_ORG', 'CrawlerClient')
QT_SETTINGS_APP = os.getenv('CRAWLER_QT_SETTINGS_APP', 'DistributedCrawler')

# 任务时间策略
TASK_CLAIM_TIMEOUT_SECONDS = env_int('TASK_CLAIM_TIMEOUT_SECONDS', 120)
TASK_FETCH_COOLDOWN_SECONDS = env_int('TASK_FETCH_COOLDOWN_SECONDS', 180)

# 外部队列拉取配置
PULL_TASK_BASE_URL = os.getenv('PULL_TASK_BASE_URL', 'http://8.146.230.26')
PULL_TASK_SITE_NAME = os.getenv('PULL_TASK_SITE_NAME', 'GF_TEAM_B_69FFE4')
PULL_TASK_TOKEN = os.getenv('PULL_TASK_TOKEN', 'G8vmuq9tjoXYerLd6QMaEtLh')
PULL_TASK_TIMEOUT = env_int('PULL_TASK_TIMEOUT', 15)
