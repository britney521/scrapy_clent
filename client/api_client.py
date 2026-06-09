from __future__ import annotations

import requests

from common.project_settings import CRAWLER_API_BASE


class ApiClient:
    def __init__(self, base_url: str = CRAWLER_API_BASE, username: str = '', password: str = ''):
        self.base_url = base_url.rstrip('/')
        self.auth = (username, password) if username and password else None

    def register(self, username: str, password: str) -> dict:
        resp = requests.post(
            f'{self.base_url}/register/',
            json={'username': username, 'password': password},
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()

    def login(self, username: str, password: str) -> dict:
        resp = requests.post(
            f'{self.base_url}/login/',
            json={'username': username, 'password': password},
            timeout=15,
        )
        resp.raise_for_status()
        self.auth = (username, password)
        return resp.json()

    def fetch_tasks(self, limit: int = 1) -> list[dict]:
        # 服务端按队列 FIFO 领取任务；默认每次领取 1 个。
        # 外部任务源由服务端拉取，客户端只领取已入库任务并在本机执行商品采集。
        resp = requests.get(
            f'{self.base_url}/tasks/',
            params={'limit': limit},
            auth=self.auth,
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()

    def my_tasks(self) -> list[dict]:
        resp = requests.get(f'{self.base_url}/my-tasks/', auth=self.auth, timeout=15)
        resp.raise_for_status()
        return resp.json()

    def post_status(self, task_id: int, status: str, error_msg: str = '') -> dict:
        resp = requests.post(
            f'{self.base_url}/tasks/{task_id}/status/',
            json={'status': status, 'error_msg': error_msg},
            auth=self.auth,
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()

    def post_data(self, task_id: int, result_data: list[dict]) -> dict:
        resp = requests.post(
            f'{self.base_url}/tasks/{task_id}/data/',
            json={'result_data': result_data},
            auth=self.auth,
            timeout=20,
        )
        resp.raise_for_status()
        return resp.json()
