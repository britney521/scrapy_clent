from typing import Any
from urllib.parse import urlencode

import requests

from common.project_settings import PULL_TASK_BASE_URL, PULL_TASK_SITE_NAME, PULL_TASK_TIMEOUT, PULL_TASK_TOKEN


def pull_task(count: int = 1) -> dict[str, Any]:
    response = requests.get(
        f'{PULL_TASK_BASE_URL.rstrip("/")}/pullTask',
        params={'siteName': PULL_TASK_SITE_NAME, 'token': PULL_TASK_TOKEN, 'count': count},
        timeout=PULL_TASK_TIMEOUT,
    )
    response.raise_for_status()
    return response.json()


def pull_task_list(count: int = 1) -> list[dict[str, Any]]:
    payload = pull_task(count=count)
    data_list = payload.get('dataList')
    if isinstance(data_list, list):
        return [item for item in data_list if isinstance(item, dict)]

    data = payload.get('data')
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]

    if isinstance(data, dict):
        nested_list = data.get('dataList')
        if isinstance(nested_list, list):
            return [item for item in nested_list if isinstance(item, dict)]

    return []


def extract_external_task_id(payload: dict[str, Any]) -> str:
    for key in ('taskId', 'task_id', 'id', 'taskID', 'tid'):
        value = payload.get(key)
        if value not in (None, ''):
            return str(value)
    raise ValueError(f'外部任务缺少任务ID字段: {payload}')


def extract_target_url(payload: dict[str, Any]) -> str:
    for item in _iter_payload_dicts(payload):
        for key in ('url', 'targetUrl', 'target_url', 'link', 'href'):
            value = item.get(key)
            if value:
                return str(value)
    content = payload.get('content')
    if isinstance(content, dict):
        keyword = content.get('keyWord') or content.get('keyword') or content.get('itemName')
        if keyword:
            return 'https://s.taobao.com/search?' + urlencode({'q': str(keyword)})
    raise ValueError(f'外部任务缺少 URL 字段: {payload}')


def has_target_url(payload: dict[str, Any]) -> bool:
    try:
        extract_target_url(payload)
    except ValueError:
        return False
    return True


def _iter_payload_dicts(payload: dict[str, Any]):
    yield payload
    content = payload.get('content')
    if isinstance(content, dict):
        yield content


def extract_task_name(payload: dict[str, Any], external_task_id: str) -> str:
    for item in _iter_payload_dicts(payload):
        for key in ('taskName', 'task_name', 'name', 'title', 'itemName', 'keyWord', 'keyword'):
            value = item.get(key)
            if value:
                return str(value)
    return f'外部任务 {external_task_id}'
