from django.conf.urls import url
from django.urls import path, re_path
from .views import *
urlpatterns = [

    # 主页
    path('', index, name='index'),

    # AJAX操作的URL
    path('graph_query/', graph_query, name='graph_query'),
    path('wenda_ajax/', wenda_ajax, name='wenda_ajax'),

    # 保留原有URL用于兼容
    # path('wenda', wenda, name='wenda'),

]
