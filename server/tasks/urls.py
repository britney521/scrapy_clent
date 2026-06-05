from django.urls import path
from .views import LoginAPIView, MyTaskListAPIView, RegisterAPIView, TaskDataAPIView, TaskListAPIView, TaskStatusAPIView

urlpatterns = [
    path('register/', RegisterAPIView.as_view(), name='register'),
    path('login/', LoginAPIView.as_view(), name='login'),
    path('tasks/', TaskListAPIView.as_view(), name='task-claim'),
    path('my-tasks/', MyTaskListAPIView.as_view(), name='my-task-list'),
    path('tasks/<int:task_id>/status/', TaskStatusAPIView.as_view(), name='task-status'),
    path('tasks/<int:task_id>/data/', TaskDataAPIView.as_view(), name='task-data'),
]
