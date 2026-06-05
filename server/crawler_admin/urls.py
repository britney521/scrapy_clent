from django.contrib import admin
from django.conf import settings
from django.http import JsonResponse
from django.urls import include, path, re_path
from django.views.static import serve

urlpatterns = [
    path('health/', lambda request: JsonResponse({'status': 'ok'})),
    path('admin/', admin.site.urls),
    path('api/', include('tasks.urls')),
]

if getattr(settings, 'DJANGO_SERVE_STATIC', False):
    urlpatterns += [
        re_path(r'^static/(?P<path>.*)$', serve, {'document_root': settings.STATIC_ROOT}),
        re_path(r'^media/(?P<path>.*)$', serve, {'document_root': settings.MEDIA_ROOT}),
    ]
