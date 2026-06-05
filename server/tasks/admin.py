from django.contrib import admin
from django.utils.html import format_html

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
