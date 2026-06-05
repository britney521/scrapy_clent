from datetime import timedelta

from django.contrib.auth import authenticate
from django.db.models import Q
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from common.logging_config import log_debug
from .external_tasks import (
    extract_external_task_id,
    extract_target_url,
    extract_task_name,
    pull_task_list,
)
from .models import TASK_CLAIM_TIMEOUT_SECONDS, TASK_FETCH_COOLDOWN_SECONDS, ClientTask, ScrapedData, TaskClaimRecord, TaskLog
from .serializers import ClientTaskSerializer, LoginSerializer, RegisterSerializer, SubmitDataSerializer, TaskStatusSerializer


class RegisterAPIView(APIView):
    """POST /api/register/：客户端注册账号。"""
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        return Response({'id': user.id, 'username': user.username}, status=status.HTTP_201_CREATED)


class LoginAPIView(APIView):
    """POST /api/login/：验证客户端账号密码；后续接口继续使用 Basic Auth。"""
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = authenticate(
            request,
            username=serializer.validated_data['username'],
            password=serializer.validated_data['password'],
        )
        if user is None:
            return Response({'detail': '用户名或密码错误'}, status=status.HTTP_400_BAD_REQUEST)
        return Response({'id': user.id, 'username': user.username}, status=status.HTTP_200_OK)


class TaskListAPIView(APIView):
    """GET /api/tasks/：客户端从公共任务队列 FIFO 领取任务。"""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        limit = self._get_limit(request)
        log_debug('客户端请求领取任务', {'username': request.user.username, 'limit': limit}, app_name='server')
        reset_expired_tasks()
        allowed, wait_seconds = check_claim_cooldown(request.user)
        if not allowed:
            log_debug('领取任务被频率限制', {
                'username': request.user.username,
                'waitSeconds': wait_seconds,
            }, app_name='server')
            return Response(
                {
                    'status': 'fail',
                    'message': f'领取任务过于频繁，请 {wait_seconds} 秒后再试',
                    'wait_seconds': wait_seconds,
                },
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )
        self._ensure_pending_tasks(limit)
        claimed_tasks = []

        # 队列语义：只领取 status=PENDING 且 assigned_to 为空的任务，按 created_at/id 先进先出。
        # 使用条件 UPDATE 防止并发客户端重复领取同一任务；SQLite 下也可工作。
        for _ in range(limit):
            with transaction.atomic():
                candidate = (
                    ClientTask.objects
                    .filter(status=ClientTask.STATUS_PENDING, assigned_to__isnull=True)
                    .order_by('created_at', 'id')
                    .first()
                )
                if not candidate:
                    break

                updated = ClientTask.objects.filter(
                    id=candidate.id,
                    status=ClientTask.STATUS_PENDING,
                    assigned_to__isnull=True,
                ).update(
                    assigned_to=request.user,
                    status=ClientTask.STATUS_CLAIMED,
                    claimed_at=timezone.now(),
                )
                if not updated:
                    continue
                claimed_tasks.append(ClientTask.objects.get(id=candidate.id))

        if claimed_tasks:
            TaskClaimRecord.objects.update_or_create(
                user=request.user,
                defaults={'last_claimed_at': timezone.now()},
            )
        log_debug('客户端领取任务完成', {
            'username': request.user.username,
            'count': len(claimed_tasks),
            'taskIds': [task.external_task_id or task.id for task in claimed_tasks],
        }, app_name='server')
        return Response(ClientTaskSerializer(claimed_tasks, many=True).data)

    @staticmethod
    def _ensure_pending_tasks(limit: int) -> None:
        pending_count = ClientTask.objects.filter(
            status=ClientTask.STATUS_PENDING,
            assigned_to__isnull=True,
        ).count()
        if pending_count >= limit:
            return

        for payload in pull_task_list(count=limit - pending_count):
            try:
                external_task_id = extract_external_task_id(payload)
                target_url = extract_target_url(payload)
            except ValueError:
                log_debug('外部任务缺少必要字段，已跳过', {'payload': payload}, app_name='server')
                continue
            task_name = extract_task_name(payload, external_task_id)
            task, created = ClientTask.objects.get_or_create(
                external_task_id=external_task_id,
                defaults={
                    'task_name': task_name,
                    'target_url': target_url,
                    'raw_payload': payload,
                    'status': ClientTask.STATUS_PENDING,
                },
            )
            if created:
                log_debug('外部任务已写入本地队列', {
                    'externalTaskId': external_task_id,
                    'taskName': task_name,
                    'targetUrl': target_url,
                }, app_name='server')

    @staticmethod
    def _get_limit(request) -> int:
        try:
            limit = int(request.query_params.get('limit', 1))
        except (TypeError, ValueError):
            limit = 1
        return max(1, min(limit, 50))


class MyTaskListAPIView(APIView):
    """GET /api/my-tasks/：查看当前客户端已领取任务。"""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        reset_expired_tasks(user=request.user)
        tasks = ClientTask.objects.filter(assigned_to=request.user).order_by('-claimed_at', '-id')
        return Response(ClientTaskSerializer(tasks, many=True).data)


class TaskStatusAPIView(APIView):
    """POST /api/tasks/{id}/status/：领取该任务的客户端才能更新状态并记录错误日志。"""
    permission_classes = [IsAuthenticated]

    def post(self, request, task_id):
        task = get_task_for_user(task_id, request.user)
        serializer = TaskStatusSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        new_status = serializer.validated_data['status']

        if is_task_expired(task):
            if task.status == ClientTask.STATUS_SUCCESS and new_status == ClientTask.STATUS_SUCCESS:
                return Response(ClientTaskSerializer(task).data, status=status.HTTP_200_OK)
            message = mark_task_timeout(task, '任务领取后超过2分钟未完成上传，已标记为超时')
            return Response({'status': 'fail', 'message': message}, status=status.HTTP_400_BAD_REQUEST)

        task.status = new_status
        task.save(update_fields=['status'])

        error_msg = serializer.validated_data.get('error_msg') or ''
        if error_msg:
            TaskLog.objects.create(task=task, message=error_msg)

        return Response(ClientTaskSerializer(task).data, status=status.HTTP_200_OK)


class TaskDataAPIView(APIView):
    """POST /api/tasks/{id}/data/：领取该任务的客户端提交 JSON 数组数据。"""
    permission_classes = [IsAuthenticated]

    def post(self, request, task_id):
        task = get_task_for_user(task_id, request.user)
        if is_task_expired(task):
            message = mark_task_timeout(task, '任务领取后超过2分钟未完成上传，已标记为超时')
            return Response({'status': 'fail', 'message': message}, status=status.HTTP_400_BAD_REQUEST)

        serializer = SubmitDataSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result_data = serializer.validated_data['result_data']
        valid, message = self._validate_product_payload(result_data)
        if not valid:
            TaskLog.objects.create(task=task, message=f'商品数据校验失败：{message}')
            return Response(
                {'status': 'fail', 'message': message},
                status=status.HTTP_400_BAD_REQUEST,
            )

        scraped = ScrapedData.objects.create(
            task=task,
            result_data=result_data,
        )
        task.status = ClientTask.STATUS_SUCCESS
        task.save(update_fields=['status'])
        TaskLog.objects.create(task=task, message=f'商品数据保存成功：ScrapedData #{scraped.id}')
        return Response(
            {'status': 'success', 'id': scraped.id, 'uploaded_at': scraped.uploaded_at},
            status=status.HTTP_200_OK,
        )

    @staticmethod
    def _validate_product_payload(result_data: list[dict]) -> tuple[bool, str]:
        for index, row in enumerate(result_data):
            product = row.get('product') if isinstance(row, dict) else None
            if not isinstance(product, dict):
                return False, f'第 {index + 1} 条缺少 product 商品 JSON'
            item_id = row.get('itemId') or product.get('item_id') or product.get('itemId')
            title = product.get('title')
            price = product.get('price')
            properties = product.get('properties')
            missing = []
            if not item_id:
                missing.append('itemId')
            if not title:
                missing.append('title')
            if not price or (isinstance(price, dict) and not price.get('values')):
                missing.append('price')
            if not properties:
                missing.append('properties')
            if missing:
                return False, f'第 {index + 1} 条商品字段为空：{", ".join(missing)}'
        return True, ''


def get_task_for_user(task_id: int, user):
    return get_object_or_404(
        ClientTask,
        Q(id=task_id) | Q(external_task_id=str(task_id)),
        assigned_to=user,
    )


def claim_expire_before():
    return timezone.now() - timedelta(seconds=TASK_CLAIM_TIMEOUT_SECONDS)


def is_task_expired(task: ClientTask) -> bool:
    if task.status == ClientTask.STATUS_SUCCESS:
        return False
    return bool(task.claimed_at and task.claimed_at <= claim_expire_before())


def mark_task_timeout(task: ClientTask, message: str) -> str:
    task.status = ClientTask.STATUS_TIMEOUT
    task.save(update_fields=['status'])
    TaskLog.objects.create(task=task, message=message)
    return message


def reset_expired_tasks(user=None) -> int:
    queryset = ClientTask.objects.filter(
        status__in=[ClientTask.STATUS_CLAIMED, ClientTask.STATUS_RUNNING],
        claimed_at__lte=claim_expire_before(),
    )
    if user is not None:
        queryset = queryset.filter(assigned_to=user)

    expired_tasks = list(queryset)
    for task in expired_tasks:
        mark_task_timeout(task, '任务领取后超过2分钟未完成上传，自动标记为超时')
    return len(expired_tasks)


def check_claim_cooldown(user) -> tuple[bool, int]:
    record = TaskClaimRecord.objects.filter(user=user).first()
    if record is None:
        return True, 0
    elapsed = int((timezone.now() - record.last_claimed_at).total_seconds())
    wait_seconds = TASK_FETCH_COOLDOWN_SECONDS - elapsed
    if wait_seconds > 0:
        return False, wait_seconds
    return True, 0
