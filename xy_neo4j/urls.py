"""xy_neo4j URL Configuration

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/3.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.conf.urls import include
from django.urls import path, re_path
from django.contrib import admin
from django.conf import settings
from django.conf.urls.static import static
from django.views.static import serve

urlpatterns = [
    path('admin/', admin.site.urls),
    path(r'accounts/', include(('accounts.urls', 'accounts'), namespace='accounts')),
    path(r'mapping/', include(('mapping.urls', 'mapping'), namespace='mapping')),
    path(r'', include(('myneo4j.urls', 'myneo4j'), namespace='myneo4j')),
]

# ✅ 添加 generated_maps 目录的静态文件服务（开发环境）
if settings.DEBUG:
    urlpatterns += [
        re_path(r'^generated_maps/(?P<path>.*)$', serve, {
            'document_root': settings.GENERATED_MAPS_DIR,
        }),
    ]
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_DIRS)