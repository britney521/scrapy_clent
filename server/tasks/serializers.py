from datetime import timedelta

from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils import timezone
from rest_framework import serializers
from .models import TASK_CLAIM_TIMEOUT_SECONDS, ClientTask, ScrapedData, TaskLog


class ClientTaskSerializer(serializers.ModelSerializer):
    id = serializers.SerializerMethodField()
    db_id = serializers.IntegerField(source='id', read_only=True)
    created_by_username = serializers.CharField(source='created_by.username', read_only=True)
    assigned_to_username = serializers.CharField(source='assigned_to.username', read_only=True)
    claim_expires_at = serializers.SerializerMethodField()
    claim_seconds_remaining = serializers.SerializerMethodField()

    class Meta:
        model = ClientTask
        fields = [
            'id',
            'db_id',
            'external_task_id',
            'task_name',
            'target_url',
            'status',
            'created_at',
            'claimed_at',
            'claim_expires_at',
            'claim_seconds_remaining',
            'created_by_username',
            'assigned_to_username',
        ]
        read_only_fields = [
            'id',
            'db_id',
            'external_task_id',
            'created_at',
            'claimed_at',
            'claim_expires_at',
            'claim_seconds_remaining',
            'created_by_username',
            'assigned_to_username',
        ]

    def get_id(self, obj):
        if obj.external_task_id:
            try:
                return int(obj.external_task_id)
            except ValueError:
                return obj.external_task_id
        return obj.id

    def get_claim_expires_at(self, obj):
        if not obj.claimed_at:
            return None
        return obj.claimed_at + timedelta(seconds=TASK_CLAIM_TIMEOUT_SECONDS)

    def get_claim_seconds_remaining(self, obj):
        if not obj.claimed_at:
            return None
        remaining = TASK_CLAIM_TIMEOUT_SECONDS - int((timezone.now() - obj.claimed_at).total_seconds())
        return max(0, remaining)


class RegisterSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150)
    password = serializers.CharField(min_length=6, write_only=True)

    def validate_username(self, value):
        if User.objects.filter(username=value).exists():
            raise serializers.ValidationError('用户名已存在')
        return value

    def validate_password(self, value):
        try:
            validate_password(value)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(list(exc.messages))
        return value

    def create(self, validated_data):
        return User.objects.create_user(
            username=validated_data['username'],
            password=validated_data['password'],
        )


class LoginSerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField(write_only=True)


class TaskStatusSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=[c[0] for c in ClientTask.STATUS_CHOICES])
    error_msg = serializers.CharField(required=False, allow_blank=True, allow_null=True)


class ScrapedDataSerializer(serializers.ModelSerializer):
    class Meta:
        model = ScrapedData
        fields = ['id', 'task', 'result_data', 'uploaded_at']
        read_only_fields = ['id', 'task', 'uploaded_at']


class SubmitDataSerializer(serializers.Serializer):
    result_data = serializers.ListField(child=serializers.JSONField(), allow_empty=False)


class TaskLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = TaskLog
        fields = ['id', 'task', 'message', 'created_at']
        read_only_fields = ['id', 'task', 'created_at']
