from importlib.util import find_spec
import os
from pathlib import Path
from typing import List

try:
    from dotenv import load_dotenv
except ModuleNotFoundError:
    def load_dotenv(*args, **kwargs):
        return False

BASE_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BASE_DIR.parent
load_dotenv(BASE_DIR / '.env')
load_dotenv(PROJECT_ROOT / '.env')


def env_bool(name: str, default: bool = False) -> bool:
    return str(os.getenv(name, str(default))).lower() in ('1', 'true', 'yes', 'on')


def env_list(name: str, default: str = '') -> List[str]:
    value = os.getenv(name, default)
    return [item.strip() for item in value.split(',') if item.strip()]


SECRET_KEY = os.getenv('DJANGO_SECRET_KEY', 'dev-only-change-me')
DEBUG = env_bool('DJANGO_DEBUG', True)
ALLOWED_HOSTS = env_list('DJANGO_ALLOWED_HOSTS', '*')
CSRF_TRUSTED_ORIGINS = env_list('DJANGO_CSRF_TRUSTED_ORIGINS', '')

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'rest_framework',
    'tasks.apps.TasksConfig',
]

# simpleui 必须放在 django.contrib.admin 前面，才能覆盖默认 admin 模板。
# 本地未安装依赖时先回退到原生 admin，执行 `pip install -r requirements.txt` 后自动启用。
if find_spec('simpleui'):
    INSTALLED_APPS.insert(0, 'simpleui')

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]
if find_spec('whitenoise'):
    MIDDLEWARE.insert(1, 'whitenoise.middleware.WhiteNoiseMiddleware')

ROOT_URLCONF = 'crawler_admin.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {'context_processors': [
            'django.template.context_processors.request',
            'django.contrib.auth.context_processors.auth',
            'django.contrib.messages.context_processors.messages',
        ]},
    }
]

WSGI_APPLICATION = 'crawler_admin.wsgi.application'

DB_ENGINE = os.getenv('DJANGO_DB_ENGINE', 'sqlite').lower()
if DB_ENGINE == 'mysql':
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.mysql',
            'NAME': os.getenv('DJANGO_DB_NAME', ''),
            'USER': os.getenv('DJANGO_DB_USER', ''),
            'PASSWORD': os.getenv('DJANGO_DB_PASSWORD', ''),
            'HOST': os.getenv('DJANGO_DB_HOST', '127.0.0.1'),
            'PORT': os.getenv('DJANGO_DB_PORT', '3306'),
            'OPTIONS': {'charset': 'utf8mb4'},
        }
    }
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / os.getenv('DJANGO_DB_NAME', 'db.sqlite3'),
        }
    }

LANGUAGE_CODE = 'zh-hans'
TIME_ZONE = 'Asia/Shanghai'
USE_I18N = True
USE_TZ = True
STATIC_URL = os.getenv('DJANGO_STATIC_URL', '/static/')
STATIC_ROOT = BASE_DIR / 'staticfiles'
DJANGO_SERVE_STATIC = env_bool('DJANGO_SERVE_STATIC', DEBUG)
STORAGES = {
    'default': {
        'BACKEND': 'django.core.files.storage.FileSystemStorage',
    },
    'staticfiles': {
        'BACKEND': (
            'whitenoise.storage.CompressedStaticFilesStorage'
            if find_spec('whitenoise')
            else 'django.contrib.staticfiles.storage.StaticFilesStorage'
        ),
    },
}
MEDIA_URL = os.getenv('DJANGO_MEDIA_URL', '/media/')
MEDIA_ROOT = BASE_DIR / 'media'
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# 宝塔/Nginx 反代 HTTPS 时需要识别 X-Forwarded-Proto。
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
SESSION_COOKIE_SECURE = env_bool('DJANGO_SESSION_COOKIE_SECURE', False)
CSRF_COOKIE_SECURE = env_bool('DJANGO_CSRF_COOKIE_SECURE', False)

# Django Admin / SimpleUI
SIMPLEUI_HOME_TITLE = '爬虫任务管理后台'
SIMPLEUI_HOME_ICON = 'fa fa-home'
SIMPLEUI_INDEX = '后台首页'
# SIMPLEUI_LOGO 是图片地址，不是文字；不配置可避免请求 /admin/分布式爬虫后台 404。
SIMPLEUI_LOGO = ''
SIMPLEUI_ANALYSIS = False
SIMPLEUI_DEFAULT_THEME = 'admin.lte.css'
SIMPLEUI_CONFIG = {
    # 不使用英文 app 名过滤，避免 app 中文化后菜单被隐藏。
    'system_keep': False,
    'dynamic': False,
    'menus': [
        {
            'app': 'auth',
            'name': '认证和授权',
            'icon': 'fas fa-user-shield',
            'models': [
                {'name': '用户', 'icon': 'fa fa-user', 'url': 'auth/user/'},
                {'name': '组', 'icon': 'fa fa-users', 'url': 'auth/group/'},
            ],
        },
        {
            'app': 'tasks',
            'name': '任务管理',
            'icon': 'fas fa-tasks',
            'models': [
                {'name': '客户端任务', 'icon': 'fa fa-list', 'url': 'tasks/clienttask/'},
                {'name': '采集数据', 'icon': 'fa fa-database', 'url': 'tasks/scrapeddata/'},
                {'name': '任务日志', 'icon': 'fa fa-file-text', 'url': 'tasks/tasklog/'},
                {'name': '任务领取记录', 'icon': 'fa fa-clock-o', 'url': 'tasks/taskclaimrecord/'},
                {'name': '供应商已提交数据', 'icon': 'fa fa-cloud-upload', 'url': 'tasks/vendor-records/'},
            ],
        },
    ],
}

REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework.authentication.SessionAuthentication',
        'rest_framework.authentication.BasicAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],
}

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]
