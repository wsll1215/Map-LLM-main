from .pyneo_utils import *
from .models import MyNode, MyWenda
from django.http import JsonResponse
import json
from django.conf import settings
from django.shortcuts import render
from django.contrib.auth.decorators import login_required
import logging

logger = logging.getLogger(__name__)


@login_required
def index(request):
    """主页视图，根据模板继承渲染左右两侧内容"""
    try:
        # 左侧图谱部分的初始数据
        start = request.GET.get("start", "")
        relation = request.GET.get("relation", "")
        end = request.GET.get("end", "")
        all_datas = get_all_relation(start, relation, end)
        links = json.dumps(all_datas["links"])
        datas = json.dumps(all_datas["datas"])
        categories = json.dumps(all_datas["categories"])
        legend_data = json.dumps(all_datas["legend_data"])

        # 右侧问答部分的初始数据
        user = request.user
        all_wendas = MyWenda.objects.filter(user=user).order_by("-id")[:10]

    except Exception as e:
        logger.exception("知识图谱首页初始化失败")
        # 出错时提供空数据
        links = "[]"
        datas = "[]"
        categories = "[]"
        legend_data = "[]"
        all_wendas = []

    return render(request, "home.html", locals())


@login_required
def graph_query(request):
    """处理图谱查询的AJAX请求"""
    try:
        start = request.GET.get("start", "")
        relation = request.GET.get("relation", "")
        end = request.GET.get("end", "")

        all_datas = get_all_relation(start, relation, end)

        # 返回JSON格式的图谱数据
        return JsonResponse({
            'links': all_datas["links"],
            'datas': all_datas["datas"],
            'categories': all_datas["categories"],
            'legend_data': all_datas["legend_data"]
        })
    except Exception as e:
        logger.exception("知识图谱查询失败")
        return JsonResponse({'error': str(e)}, status=500)


@login_required
def wenda_ajax(request):
    """处理问答的AJAX请求"""
    try:
        user = request.user

        # 处理清除历史记录请求
        clean = request.GET.get("clean", "")
        if clean:
            all_wendas = MyWenda.objects.filter(user=user)
            for js in all_wendas:
                js.delete()
            return JsonResponse({'status': 'success'})

        # 处理问答请求
        key = request.GET.get("key", "")
        daan = ''


        if key.lower() in {'你好', '您好', 'hello', '你好！'}:
            daan = ("""你好，很高兴见到你。欢迎问我任何有关路网综合的问题。""")
        elif key:
            res_classify = settings.CLASSIFIER.classify(key)
            final_answers = []
            if isinstance(res_classify, dict):
                res_sql = settings.PARSER.parser_main(res_classify)
                final_answers = settings.SEACHER.search_main(res_sql)
            if final_answers:
                try:
                    daan = settings.DEEPSEEK.get_chatglm_response(key, final_answers)
                except Exception as e:
                    logger.warning("DeepSeek回答优化失败，直接返回知识图谱查询结果: %s", e)
                    daan = '\n'.join(final_answers)
            elif isinstance(res_classify, dict) and res_classify.get('question_types'):
                daan = _build_no_graph_answer(res_classify)
            else:
                try:
                    daan = settings.DEEPSEEK.get_chatglm_response(key)
                except Exception as e:
                    logger.warning("DeepSeek问答失败: %s", e)
                    daan = '暂未在知识图谱中匹配到可查询结果，且外部问答模型当前不可用。请换一种更明确的问法，例如“1:100000比例尺综合原则的综合阈值是什么”。'
            daan = daan.replace('\n', '<br>')
            daan = daan.replace(' ', '&nbsp;')

        # 保存问答记录
        if daan and key:
            wenda = MyWenda.objects.filter(user=user, question=key, anster=daan)
            if len(wenda) > 0:
                for w in wenda:
                    w.delete()

            wenda = MyWenda()
            wenda.user = user
            wenda.question = key
            wenda.anster = daan
            wenda.save()

        return JsonResponse({'answer': daan})

    except Exception as e:
        logger.exception("问答接口处理失败")
        return JsonResponse({
            'answer': '抱歉，问答处理时出现异常，请检查知识图谱服务和模型配置后重试。'
        }, status=200)


def _build_no_graph_answer(res_classify):
    question_types = res_classify.get('question_types') or []
    args = res_classify.get('args') or {}
    candidate_roads = res_classify.get('candidate_roads') or {}
    if 'road_connection_between' in question_types:
        road_names = _extract_road_names(args)
        if len(road_names) >= 2:
            hints = _format_road_candidate_hints(candidate_roads, road_names)
            return f'知识图谱中未查询到“{road_names[0]}”和“{road_names[1]}”之间的连接关系记录。{hints}'
        return '知识图谱中未识别到两个明确的道路名称，请输入类似“东经路和永安路相连吗”的问题。'

    if 'road_connect_road' in question_types:
        road_names = _extract_road_names(args)
        if road_names:
            hints = _format_road_candidate_hints(candidate_roads, road_names)
            return f'知识图谱中未查询到道路“{road_names[0]}”的连接道路记录。请确认道路名称是否存在于道路数据中，或尝试输入更完整的道路名称。{hints}'
        return '知识图谱中未识别到明确的道路名称，请输入类似“东四十条连接哪些道路”的问题。'

    return '知识图谱中未查询到与该问题匹配的记录，请换一种更明确的问法。'


def _extract_road_names(args):
    road_names = []
    for key, value in (args or {}).items():
        if key == 'road' and isinstance(value, list):
            road_names.extend(value)
        elif isinstance(value, list) and 'road' in value:
            road_names.append(key)
    return list(dict.fromkeys(road_names))


def _format_road_candidate_hints(candidate_roads, road_names):
    hints = []
    for road_name in road_names:
        candidates = candidate_roads.get(road_name) or []
        if candidates:
            hints.append(f'“{road_name}”的相近道路：{"、".join(candidates[:5])}')
    if not hints:
        return ''
    return '可参考：' + '；'.join(hints) + '。'


# 保留原始的wenda函数作为备用，并重定向到相应的AJAX处理
# @login_required
# def wenda(request):
#     """
#     原始的问答视图，现在主要是为了兼容，实际会重定向到AJAX处理
#     注意：如果需要直接通过URL访问/wenda，此函数仍保持原有功能
#     """
#     print("232132")
#     try:
#         user = request.user
#
#         # 处理清除历史记录
#         clean = request.GET.get("clean", "")
#         if clean:
#             all_wendas = MyWenda.objects.filter(user=user)
#             for js in all_wendas:
#                 js.delete()
#
#         # 处理问答
#         key = request.GET.get("key", "")
#         daan = ''
#         if "路网选取" in key and "方法" in key:
#             daan = '方法有专家-经验驱动、算法-模型驱动、数据-知识驱动'
#         if key:
#             if key.lower() in {'你好', '您好', 'hello', '你好！'}:
#                 daan = '你好，很高兴见到你。欢迎问我任何有关路网综合的问题。'
#             else:
#                 res_classify, question_qwds = settings.CLASSIFIER.classify(key)
#                 final_answers = []
#
#                 if res_classify:
#                     res_sql = settings.PARSER.parser_main(res_classify)
#                     final_answers = settings.SEACHER.search_main(res_sql, key, ai=False)
#
#                 daan = '\n'.join(
#                     final_answers if final_answers
#                     else settings.DEEPSEEK.get_chatglm_response(key, neo4j=False)
#                 )
#
#
#             # 保存问答记录
#             if daan:
#                 wenda = MyWenda.objects.filter(user=user, question=key, anster=daan)
#                 if len(wenda) > 0:
#                     for w in wenda:
#                         w.delete()
#
#                 wenda = MyWenda()
#                 wenda.user = user
#                 wenda.question = key
#                 wenda.anster = daan
#                 wenda.save()
#
#         # 获取最近的问答记录
#         all_wendas = MyWenda.objects.filter(user=user).order_by("-id")[:10]
#
#         return render(request, "home.html", locals())
#     except Exception as e:
#         print(e)
#         return render(request, "home.html", locals())
