from django.urls import path
from . import views
from . import api_views
from . import rest_api

app_name = 'mapping'

urlpatterns = [
    # 主页
    path('', views.mapping_index, name='index'),

    # API 接口
    path('api/create-request/', views.create_map_request, name='create_request'),
    path('api/process-request/', views.process_map_request, name='process_request'),
    path('api/continue-conversation/', views.continue_conversation, name='continue_conversation'),  # 新增：继续对话
    path('api/chat-messages/<int:request_id>/', views.get_chat_messages, name='chat_messages'),
    path('api/generated-maps/<int:request_id>/', views.get_generated_maps, name='generated_maps'),
    path('api/history-maps/', views.get_history_maps, name='history_maps'),
    path('api/activate-history-map/', views.activate_history_map, name='activate_history_map'),
    path('api/realtime-preview/<int:request_id>/', views.get_latest_realtime_preview, name='realtime_preview'),
    path('api/process-logs/<int:request_id>/', views.get_process_logs, name='process_logs'),
    path('api/convert-map-format/', views.convert_map_format, name='convert_map_format'),  # 新增：格式转换

    # Versioned REST resources
    path('api/map-requests/', rest_api.map_request_collection, name='map-request-collection'),
    path('api/map-requests/<int:request_id>/', rest_api.map_request_detail, name='map-request-detail'),
    path('api/map-requests/<int:request_id>/messages/', rest_api.map_message_collection, name='map-message-collection'),
    path('api/map-requests/<int:request_id>/runs/', rest_api.map_run_collection, name='map-run-collection'),
    path('api/map-requests/<int:request_id>/runs/<int:run_id>/', rest_api.map_run_detail, name='map-run-detail'),
    path('api/map-requests/<int:request_id>/runs/<int:run_id>/events/', rest_api.map_trace_event_collection, name='map-trace-event-collection'),
    path('api/map-requests/<int:request_id>/runs/<int:run_id>/events/<str:event_id>/', rest_api.map_trace_event_detail, name='map-trace-event-detail'),
    path('api/map-requests/<int:request_id>/snapshots/current/', rest_api.map_snapshot_current, name='map-snapshot-current'),
    path('api/map-requests/<int:request_id>/snapshots/<int:version>/', rest_api.map_snapshot_detail, name='map-snapshot-detail'),
    path('api/map-requests/<int:request_id>/snapshots/<int:version>/layers/<str:layer_id>/', rest_api.map_layer_manifest, name='map-layer-manifest'),
    path('api/map-requests/<int:request_id>/snapshots/<int:version>/layers/<str:layer_id>/data/', rest_api.map_layer_data, name='map-layer-data'),
    path('api/map-requests/<int:request_id>/snapshots/<int:version>/layers/<str:layer_id>/tiles/<str:z>/<str:x>/<str:y>.pbf', rest_api.map_layer_tile, name='map-layer-tile'),
    path('api/map-requests/<int:request_id>/snapshots/current/layers/<str:layer_id>/data/', rest_api.map_layer_data_current, name='map-layer-data-current'),
    path('api/map-requests/<int:request_id>/artifacts/', rest_api.map_artifact_collection, name='map-artifact-collection'),
    path('api/datasets/', rest_api.dataset_collection, name='dataset-collection'),
    path('api/datasets/<str:dataset_id>/', rest_api.dataset_detail, name='dataset-detail'),
    path('api/datasets/<str:dataset_id>/features/', rest_api.dataset_feature_collection, name='dataset-feature-collection'),

    # 管理 API 接口
    path('api/admin/sessions/', api_views.list_user_sessions, name='api_list_sessions'),
    path('api/admin/sessions/<int:session_id>/', api_views.get_session_detail, name='api_session_detail'),
    path('api/admin/sessions/<int:session_id>/delete/', api_views.delete_session, name='api_delete_session'),
    path('api/admin/sessions/<int:session_id>/download/', api_views.download_session, name='api_download_session'),
    path('api/admin/cleanup/', api_views.cleanup_old_sessions, name='api_cleanup'),

    # 地图删除 API
    path('api/admin/maps/<int:map_id>/delete/', api_views.delete_generated_map, name='api_delete_map'),
]
