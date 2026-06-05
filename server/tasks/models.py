from django.contrib.auth.models import User
from django.db import models

from common.project_settings import TASK_CLAIM_TIMEOUT_SECONDS, TASK_FETCH_COOLDOWN_SECONDS


class ClientTask(models.Model):
    """后台管理员发布的任务；客户端按队列领取后执行。"""
    STATUS_PENDING = 'PENDING'   # 队列中，等待客户端领取
    STATUS_CLAIMED = 'CLAIMED'   # 已被某个客户端账号领取，尚未启动爬虫
    STATUS_RUNNING = 'RUNNING'
    STATUS_SUCCESS = 'SUCCESS'
    STATUS_FAILED = 'FAILED'
    STATUS_TIMEOUT = 'TIMEOUT'
    STATUS_CHOICES = [
        (STATUS_PENDING, '未领取'),
        (STATUS_CLAIMED, '已领取'),
        (STATUS_RUNNING, '进行中'),
        (STATUS_SUCCESS, '已完成'),
        (STATUS_FAILED, '失败'),
        (STATUS_TIMEOUT, '已超时'),
    ]

    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='published_tasks',
        verbose_name='发布管理员',
    )
    assigned_to = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='claimed_tasks',
        verbose_name='领取客户端账号',
    )
    external_task_id = models.CharField(max_length=255, unique=True, null=True, blank=True, verbose_name='外部任务ID')
    task_name = models.CharField(max_length=255, verbose_name='任务名称')
    target_url = models.URLField(verbose_name='目标链接')
    raw_payload = models.JSONField(default=dict, blank=True, verbose_name='外部任务原始数据')
    status = models.CharField(max_length=50, choices=STATUS_CHOICES, default=STATUS_PENDING, verbose_name='任务状态')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    claimed_at = models.DateTimeField(null=True, blank=True, verbose_name='领取时间')

    class Meta:
        verbose_name = '客户端任务'
        verbose_name_plural = '客户端任务'
        ordering = ['created_at', 'id']
        indexes = [
            models.Index(fields=['status', 'created_at', 'id']),
            models.Index(fields=['assigned_to', 'status']),
        ]

    def __str__(self):
        return f'{self.task_name}（{self.get_status_display()}）'


class ScrapedData(models.Model):
    """存储客户端回传的业务数据"""
    task = models.ForeignKey(ClientTask, on_delete=models.CASCADE, related_name='scraped_data', verbose_name='所属任务')
    result_data = models.JSONField(verbose_name='采集到的JSON数据')
    uploaded_at = models.DateTimeField(auto_now_add=True, verbose_name='上传时间')

    class Meta:
        verbose_name = '采集数据'
        verbose_name_plural = '采集数据'
        ordering = ['-uploaded_at', '-id']

    def __str__(self):
        return f'任务 #{self.task_id} 的采集数据'


class TaskLog(models.Model):
    """记录客户端运行日志"""
    task = models.ForeignKey(ClientTask, on_delete=models.CASCADE, related_name='logs', verbose_name='所属任务')
    message = models.TextField(verbose_name='日志内容')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='记录时间')

    class Meta:
        verbose_name = '任务日志'
        verbose_name_plural = '任务日志'
        ordering = ['-created_at', '-id']

    def __str__(self):
        return f'任务 #{self.task_id} 日志：{self.message[:32]}'


class TaskClaimRecord(models.Model):
    """记录客户端领取队列任务的频率限制。"""
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='task_claim_record', verbose_name='客户端账号')
    last_claimed_at = models.DateTimeField(verbose_name='最近领取时间')

    class Meta:
        verbose_name = '任务领取记录'
        verbose_name_plural = '任务领取记录'

    def __str__(self):
        return f'{self.user.username} 最近领取时间：{self.last_claimed_at}'
