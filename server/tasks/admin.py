import json
from datetime import datetime
from pathlib import Path
from typing import Optional
from django.conf import settings
from django.core.paginator import Paginator
from django.contrib import admin
from django.urls import path
from django.template.response import TemplateResponse
from django.utils.html import format_html

from .external_tasks import query_records
from .models import ClientTask, ScrapedData, TaskClaimRecord, TaskLog


admin.site.site_header = '分布式爬虫管理后台'
admin.site.site_title = '爬虫后台'
admin.site.index_title = '后台管理'


@admin.register(ClientTask)
class ClientTaskAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'external_task_id',
        'task_name',
        'target_url',
        'colored_status',
        'created_by',
        'assigned_to',
        'created_at',
        'claimed_at',
    )
    list_display_links = ('id', 'external_task_id', 'task_name')
    list_filter = ('status', 'created_at', 'claimed_at', 'created_by', 'assigned_to')
    search_fields = ('external_task_id', 'task_name', 'target_url', 'created_by__username', 'assigned_to__username')
    readonly_fields = ('created_by', 'assigned_to', 'claimed_at', 'created_at')
    fields = (
        'external_task_id',
        'task_name',
        'target_url',
        'raw_payload',
        'status',
        'created_by',
        'assigned_to',
        'created_at',
        'claimed_at',
    )
    ordering = ('-created_at', '-id')
    list_per_page = 20

    @admin.display(description='任务状态', ordering='status')
    def colored_status(self, obj):
        color_map = {
            ClientTask.STATUS_PENDING: '#6b7280',
            ClientTask.STATUS_CLAIMED: '#2563eb',
            ClientTask.STATUS_RUNNING: '#f59e0b',
            ClientTask.STATUS_SUCCESS: '#16a34a',
            ClientTask.STATUS_FAILED: '#dc2626',
            ClientTask.STATUS_TIMEOUT: '#7c2d12',
        }
        return format_html(
            '<span style="color:{};font-weight:600;">{}</span>',
            color_map.get(obj.status, '#374151'),
            obj.get_status_display(),
        )

    def save_model(self, request, obj, form, change):
        if not change and obj.created_by_id is None:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(ScrapedData)
class ScrapedDataAdmin(admin.ModelAdmin):
    list_display = ('id', 'task', 'uploaded_at')
    list_display_links = ('id', 'task')
    list_filter = ('uploaded_at',)
    search_fields = ('task__external_task_id', 'task__task_name', 'task__target_url')
    readonly_fields = ('task', 'result_data', 'uploaded_at')
    ordering = ('-uploaded_at', '-id')
    list_per_page = 20


@admin.register(TaskLog)
class TaskLogAdmin(admin.ModelAdmin):
    list_display = ('id', 'task', 'short_message', 'created_at')
    list_display_links = ('id', 'task')
    list_filter = ('created_at',)
    search_fields = ('task__external_task_id', 'task__task_name', 'message')
    readonly_fields = ('task', 'message', 'created_at')
    ordering = ('-created_at', '-id')
    list_per_page = 30

    @admin.display(description='日志内容')
    def short_message(self, obj):
        return obj.message[:80]


@admin.register(TaskClaimRecord)
class TaskClaimRecordAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'last_claimed_at')
    list_display_links = ('id', 'user')
    search_fields = ('user__username',)
    readonly_fields = ('user', 'last_claimed_at')
    ordering = ('-last_claimed_at',)


def _payload_data(payload):
    if isinstance(payload, dict) and isinstance(payload.get('data'), dict):
        return payload['data']
    return payload if isinstance(payload, dict) else {}


def _extract_records(payload):
    data = _payload_data(payload)
    task_records = data.get('taskRecords') if isinstance(data, dict) else None
    if isinstance(task_records, list):
        return task_records
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        return []
    for key in ('taskRecords', 'dataList', 'records', 'list', 'rows'):
        value = payload.get(key)
        if isinstance(value, list):
            return value
        if isinstance(value, dict):
            for nested_key in ('taskRecords', 'dataList', 'records', 'list', 'rows'):
                nested = value.get(nested_key)
                if isinstance(nested, list):
                    return nested
    return []


def _extract_record_stats(payload):
    data = _payload_data(payload)
    team = data.get('team') if isinstance(data, dict) and isinstance(data.get('team'), dict) else {}

    def pick(name: str, fallback: Optional[str] = None):
        if isinstance(team, dict) and name in team:
            return team.get(name) or 0
        if isinstance(data, dict) and name in data:
            return data.get(name) or 0
        if fallback and isinstance(data, dict) and fallback in data:
            return data.get(fallback) or 0
        return 0

    return {
        'submitCount': pick('submitCount', 'totalUploadCount'),
        'pulledTaskCount': pick('pulledTaskCount'),
        'successfulSubmitCount': pick('successfulSubmitCount', 'successCount'),
        'failedSubmitCount': pick('failedSubmitCount', 'failedCount'),
    }


def _vendor_records_cache_path() -> Path:
    cache_dir = Path(settings.BASE_DIR) / 'cache'
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir / 'vendor_records.json'


def _read_vendor_records_cache() -> dict:
    cache_path = _vendor_records_cache_path()
    if not cache_path.exists():
        return {}
    try:
        return json.loads(cache_path.read_text(encoding='utf-8'))
    except Exception:
        return {}


def _write_vendor_records_cache(payload: dict) -> Path:
    cache_path = _vendor_records_cache_path()
    cache_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
    return cache_path


def _flatten_record(value, prefix=''):
    result = {}
    if isinstance(value, dict):
        for key, item in value.items():
            name = f'{prefix}.{key}' if prefix else str(key)
            if isinstance(item, dict):
                result.update(_flatten_record(item, name))
            elif isinstance(item, list):
                result[name] = json.dumps(item, ensure_ascii=False, default=str)
            else:
                result[name] = '' if item is None else str(item)
    else:
        result[prefix or 'value'] = str(value)
    return result


def _format_vendor_datetime(value):
    if not value:
        return ''
    try:
        parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return parsed.astimezone().strftime('%Y-%m-%d %H:%M:%S')
    except Exception:
        return str(value)


def _build_records_table(records):
    columns = ['任务ID', '商品名称', '竞品ID', '目标链接', '状态', '领取时间']
    table_rows = []
    for row in records:
        row = row if isinstance(row, dict) else {}
        content = row.get('content') if isinstance(row.get('content'), dict) else {}
        table_rows.append([
            row.get('taskId') or row.get('task_id') or row.get('id') or '',
            content.get('itemName') or row.get('itemName') or '',
            content.get('competitorId') or row.get('competitorId') or '',
            content.get('targetUrl') or row.get('targetUrl') or '',
            row.get('status') or content.get('status') or '',
            _format_vendor_datetime(row.get('acceptedAt') or content.get('acceptedAt')),
        ])
    return columns, table_rows


def vendor_records_view(request):
    force_refresh = request.GET.get('refresh') in ('1', 'true', 'yes')
    cache_path = _vendor_records_cache_path()
    context = {
        **admin.site.each_context(request),
        'title': '供应商已提交数据',
        'records': [],
        'stats': {
            'submitCount': 0,
            'pulledTaskCount': 0,
            'successfulSubmitCount': 0,
            'failedSubmitCount': 0,
        },
        'columns': [],
        'table_rows': [],
        'page_obj': None,
        'paginator': None,
        'payload': {},
        'payload_text': '{}',
        'error': '',
        'from_cache': not force_refresh,
        'cache_path': str(cache_path),
        'cache_exists': cache_path.exists(),
    }
    try:
        if force_refresh:
            payload = query_records()
            _write_vendor_records_cache(payload)
            context['from_cache'] = False
        else:
            payload = _read_vendor_records_cache()
            context['from_cache'] = True
            if not payload:
                context['error'] = '暂无本地缓存，请点击刷新立即请求供应商接口。'
        records = _extract_records(payload)
        stats = _extract_record_stats(payload)
        page_number = request.GET.get('page') or 1
        paginator = Paginator(records, 20)
        page_obj = paginator.get_page(page_number)
        columns, table_rows = _build_records_table(page_obj.object_list)
        context['payload'] = payload
        context['payload_text'] = json.dumps(payload, ensure_ascii=False, indent=2, default=str)
        context['records'] = records
        context['stats'] = stats
        context['columns'] = columns
        context['table_rows'] = table_rows
        context['page_obj'] = page_obj
        context['paginator'] = paginator
        context['cache_exists'] = cache_path.exists()
    except Exception as exc:
        context['error'] = str(exc)
    return TemplateResponse(request, 'admin/tasks/vendor_records.html', context)


def _install_vendor_records_admin_url():
    original_get_urls = admin.site.get_urls

    def get_urls():
        custom_urls = [
            path(
                'tasks/vendor-records/',
                admin.site.admin_view(vendor_records_view),
                name='tasks_vendor_records',
            ),
        ]
        return custom_urls + original_get_urls()

    admin.site.get_urls = get_urls


_install_vendor_records_admin_url()
