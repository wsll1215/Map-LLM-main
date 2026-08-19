"""
Database management Admin configuration
"""
import os
import csv
from django.contrib import admin
from django.utils.html import format_html
from django.shortcuts import render
from django.urls import path
from django.http import HttpResponse, JsonResponse
from .db_models import MainDatabase, MapStatesDatabase


class DatabaseInfoAdmin(admin.ModelAdmin):
    """Base class for database info display"""

    change_list_template = 'admin/database_info_list.html'

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_module_permission(self, request):
        return True

    def get_urls(self):
        """添加自定义URL"""
        urls = super().get_urls()
        model_name = self.model._meta.model_name
        custom_urls = [
            path('view/<str:table_name>/',
                 self.admin_site.admin_view(self.view_table_data),
                 name=f'{self.model._meta.app_label}_{model_name}_view_table'),
            path('export/<str:table_name>/',
                 self.admin_site.admin_view(self.export_table_data),
                 name=f'{self.model._meta.app_label}_{model_name}_export_table'),
            path('delete/<str:table_name>/<str:pk_value>/',
                 self.admin_site.admin_view(self.delete_record),
                 name=f'{self.model._meta.app_label}_{model_name}_delete_record'),
        ]
        return custom_urls + urls

    def changelist_view(self, request, extra_context=None):
        """Override changelist view to show database info"""
        extra_context = extra_context or {}
        extra_context['title'] = self.model._meta.verbose_name_plural
        extra_context['db_stats'] = self.get_database_stats()
        extra_context['opts'] = self.model._meta
        extra_context['has_add_permission'] = False
        extra_context['has_change_permission'] = False
        extra_context['has_delete_permission'] = False
        extra_context['has_view_permission'] = True

        return render(request, self.change_list_template, extra_context)

    def get_database_stats(self):
        """Override in subclass"""
        return None

    def get_table_data_method(self):
        """Override in subclass to return the method to get table data"""
        return None

    def get_table_name_mapping(self):
        """Override in subclass to return the table name mapping"""
        return {}

    def get_delete_method(self):
        """Override in subclass to return the method to delete record"""
        return None

    def get_primary_key_method(self):
        """Override in subclass to return the method to get primary key"""
        return None

    def view_table_data(self, request, table_name):
        """查看表数据"""
        page = int(request.GET.get('page', 1))
        limit = int(request.GET.get('limit', 50))
        offset = (page - 1) * limit

        get_table_data = self.get_table_data_method()
        if not get_table_data:
            return JsonResponse({'error': '无法获取数据'}, status=500)

        data = get_table_data(table_name, limit=limit, offset=offset)

        # 获取中文表名
        table_name_mapping = self.get_table_name_mapping()
        chinese_name = table_name_mapping.get(table_name, table_name)

        if data and 'error' not in data:
            # 将主键值和行数据组合
            rows_with_pk = []
            primary_key_values = data.get('primary_key_values', [])
            for i, row in enumerate(data['rows']):
                pk_value = primary_key_values[i] if i < len(primary_key_values) else ''
                rows_with_pk.append({
                    'pk': pk_value,
                    'data': row
                })

            context = {
                'title': f'{chinese_name} - 数据查看',
                'table_name': chinese_name,
                'table_name_en': table_name,
                'columns': data['columns'],
                'rows': rows_with_pk,  # 使用包含主键的行数据
                'total': data['total'],
                'page': page,
                'limit': limit,
                'total_pages': (data['total'] + limit - 1) // limit,
                'opts': self.model._meta,
            }
            return render(request, 'admin/table_data_view.html', context)
        else:
            error_msg = data.get('error', '未知错误') if data else '无法获取数据'
            return render(request, 'admin/table_data_view.html', {
                'title': f'{chinese_name} - 数据查看',
                'table_name': chinese_name,
                'table_name_en': table_name,
                'error': error_msg,
                'opts': self.model._meta,
            })

    def export_table_data(self, request, table_name):
        """导出表数据为CSV"""
        get_table_data = self.get_table_data_method()
        if not get_table_data:
            return HttpResponse('无法导出数据', status=500)

        # 获取所有数据
        data = get_table_data(table_name, limit=100000, offset=0)

        if not data or 'error' in data:
            error_msg = data.get('error', '未知错误') if data else '无法获取数据'
            return HttpResponse(f'导出失败: {error_msg}', status=500)

        # 创建CSV响应
        response = HttpResponse(content_type='text/csv; charset=utf-8-sig')
        response['Content-Disposition'] = f'attachment; filename="{table_name}.csv"'

        writer = csv.writer(response)

        # 写入列名
        writer.writerow(data['columns'])

        # 写入数据
        for row in data['rows']:
            writer.writerow(row)

        return response

    def delete_record(self, request, table_name, pk_value):
        """删除表中的记录"""
        if request.method != 'POST':
            return JsonResponse({'success': False, 'error': '只支持POST请求'}, status=405)

        # 获取删除方法
        delete_method = self.get_delete_method()
        if not delete_method:
            return JsonResponse({'success': False, 'error': '无法删除数据'}, status=500)

        # 获取主键方法
        get_primary_key = self.get_primary_key_method()
        if not get_primary_key:
            return JsonResponse({'success': False, 'error': '无法获取主键信息'}, status=500)

        # 获取主键列名
        pk_column = get_primary_key(table_name)
        if not pk_column:
            return JsonResponse({'success': False, 'error': '无法确定主键列'}, status=500)

        # 执行删除
        result = delete_method(table_name, pk_column, pk_value)

        if result.get('success'):
            return JsonResponse(result)
        else:
            return JsonResponse(result, status=500)


class MainDatabaseAdmin(DatabaseInfoAdmin):
    """Django main database management"""

    def get_database_stats(self):
        """Get Django main database statistics"""
        return MainDatabase.get_db_stats()

    def get_table_data_method(self):
        """Return the method to get table data"""
        return MainDatabase.get_table_data

    def get_table_name_mapping(self):
        """Return the table name mapping"""
        return MainDatabase.get_table_name_mapping()

    def get_delete_method(self):
        """Return the method to delete record"""
        return MainDatabase.delete_record

    def get_primary_key_method(self):
        """Return the method to get primary key"""
        return MainDatabase.get_primary_key


class MapStatesDatabaseAdmin(DatabaseInfoAdmin):
    """Map states database management"""

    def get_database_stats(self):
        """Get map states database statistics"""
        return MapStatesDatabase.get_db_stats()

    def get_table_data_method(self):
        """Return the method to get table data"""
        return MapStatesDatabase.get_table_data

    def get_table_name_mapping(self):
        """Return the table name mapping"""
        return MapStatesDatabase.get_table_name_mapping()

    def get_delete_method(self):
        """Return the method to delete record"""
        return MapStatesDatabase.delete_record

    def get_primary_key_method(self):
        """Return the method to get primary key"""
        return MapStatesDatabase.get_primary_key


admin.site.register(MainDatabase, MainDatabaseAdmin)
admin.site.register(MapStatesDatabase, MapStatesDatabaseAdmin)

