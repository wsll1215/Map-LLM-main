#!/usr/bin/env python3
# coding: utf-8
# File: answer_search.py
# Author: lhy<lhy_in_blcu@126.com,https://huangyong.github.io>
# Date: 18-10-5

import os

from py2neo import Graph

answers_mapping = {'fclass': '类别',
                   'name': '名字',
                   'bridge': '是否有桥',
                   'tunnel': '是否有隧道',
                   'ClassZn2': '等级',
                   'Shape_Leng': '长度',
                   'Length': '周长',
                   'Area': '面积',
                   'Circle': '紧凑度',
                   'Density': '密度',
                   'description': '描述',
                   'name': '名字',
                   'method_name': '名字',
                   'scale_value': '比值',
                   'integration_threshold': '阈值',
                   'integration_requirement': '综合要求',
                   'details': '信息',
                   'authors': '作者',
                   'year': '发表年份',
                   }


class AnswerSearcher:
    def __init__(self):
        self.g = Graph(
            os.getenv('NEO4J_URL', 'http://localhost:7474'),
            user=os.getenv('NEO4J_USER', 'neo4j'),
            password=os.getenv('NEO4J_PASSWORD', ''),
        )
        self.num_limit = 20

    '''执行cypher查询，并返回相应结果'''

    def search_main(self, sqls):
        final_answers = []
        for sql_ in sqls:
            question_type = sql_['question_type']
            queries = sql_['sql']
            answers = []
            for query in queries:
                if isinstance(query, dict):
                    ress = self.g.run(query.get('query'), **query.get('params', {})).data()
                else:
                    ress = self.g.run(query).data()
                answers += ress
            final_answer = self.answer_prettify(question_type, answers)
            if final_answer:
                final_answers.append(final_answer)
        return final_answers

    '''根据对应的qustion_type，调用相应的回复模板'''

    def answer_prettify(self, question_type, answers):
        final_answer = []
        if not answers:
            return ''

        # 处理通用查询
        if question_type == 'all_selection_methods':
            method_list = [f"方法ID:{i['m.selection_method_id']} 方法名称:{i['m.method_name']}" for i in answers]
            final_answer = '路网选取方法包括：{0}'.format('；'.join(list(set(method_list))[:self.num_limit]))

        elif question_type == 'all_scale_principles':
            principle_list = [
                f"原则ID:{i['p.scale_integration_principle_id']} 比例值:{i['p.scale_value']} 综合要求:{i['p.integration_requirement']} 阈值:{i.get('p.integration_threshold', '')}"
                for i in answers]
            final_answer = '路网选取原则包括：{0}'.format('；'.join(list(set(principle_list))[:self.num_limit]))

        elif question_type == 'all_selection_schemes':
            scheme_list = [f"方案ID:{i['s.scheme_id']} 方案名称:{i['s.name']}" for i in answers]
            final_answer = '路网选取方案包括：{0}'.format('；'.join(list(set(scheme_list))[:self.num_limit]))

        elif question_type == 'all_selection_algorithms':
            algorithm_list = [f"算法ID:{i['a.selection_algorithm_id']} 算法名称:{i['a.algorithm_name']}" for i in
                              answers]
            final_answer = '路网选取算法包括：{0}'.format('；'.join(list(set(algorithm_list))[:self.num_limit]))

        # 道路-路段关系查询
        elif question_type == 'road_contains_segments':
            subject = answers[0]['s.SeID']
            desc = [f"道路ID:{i['r.RoID']} 名称:{i['r.Name']} 类型:{i['r.fclass']}" for i in answers]
            final_answer = '路段{0}属于以下道路：{1}'.format(subject, '；'.join(list(set(desc))[:self.num_limit]))

        elif question_type == 'road_consist_segments':
            subject = answers[0]['r.Name'] if answers[0]['r.Name'] else answers[0]['r.RoID']
            desc = [f"路段ID:{i['s.SeID']} 长度:{i['s.Length']}" for i in answers]
            final_answer = '{0}包含以下路段：{1}'.format(subject, '；'.join(list(set(desc))[:self.num_limit]))
        elif question_type == 'road_connect_road':
            subject = answers[0]['r0.Name'] if answers[0].get('r0.Name') else answers[0]['r0.RoID']
            desc = []
            for item in answers:
                road_name = item.get('r.Name') or item.get('r.RoID')
                if road_name and road_name != subject and road_name not in desc:
                    desc.append(road_name)
            if desc:
                final_answer = '{0}连接以下道路：{1}'.format(subject, '；'.join(desc[:self.num_limit]))

        elif question_type == 'road_connection_between':
            source = answers[0].get('r0.Name')
            target = answers[0].get('r1.Name')
            connected = answers[0].get('connected')
            final_answer = '{0}和{1}{2}相连。'.format(
                source,
                target,
                '' if connected else '不'
            )
        # 网格-路段关系查询
        elif question_type == 'mesh_contains_segments':
            subject = answers[0]['s.SeID']
            desc = [f"网格ID:{i['m.MeID']} 面积:{i['m.Area']} 密度:{i['m.Density']}" for i in answers]
            final_answer = '路段{0}属于以下网格：{1}'.format(subject, '；'.join(list(set(desc))[:self.num_limit]))

        elif question_type == 'mesh_consist_segments':
            subject = answers[0]['m.MeID']
            desc = [f"路段ID:{i['s.SeID']} 长度:{i['s.Length']}" for i in answers]
            final_answer = '网格{0}包含以下路段：{1}'.format(subject, '；'.join(list(set(desc))[:self.num_limit]))

        # 方案-方法关系查询
        elif question_type == 'scheme_contains_methods':
            subject = answers[0]['method.method_name'] if answers[0]['method.method_name'] else answers[0][
                'method.selection_method_id']
            desc = [f"方案ID:{i['scheme.scheme_id']} 方案名称:{i['scheme.name']}" for i in answers]
            final_answer = '方法{0}属于以下方案：{1}'.format(subject, '；'.join(list(set(desc))[:self.num_limit]))

        elif question_type == 'scheme_consist_methods':
            subject = answers[0]['scheme.name'] if answers[0]['scheme.name'] else answers[0]['scheme.scheme_id']
            desc = [f"方法ID:{i['method.selection_method_id']} 方法名称:{i['method.method_name']}" for i in answers]
            final_answer = '方案{0}包含以下方法：{1}'.format(subject, '；'.join(list(set(desc))[:self.num_limit]))

        # 方法-算法关系查询
        elif question_type == 'method_contains_algorithms':
            subject = answers[0]['algorithm.algorithm_name'] if answers[0]['algorithm.algorithm_name'] else answers[0][
                'algorithm.selection_algorithm_id']
            desc = [f"方法ID:{i['method.selection_method_id']} 方法名称:{i['method.method_name']}" for i in answers]
            final_answer = '算法{0}属于以下方法：{1}'.format(subject, '；'.join(list(set(desc))[:self.num_limit]))

        elif question_type == 'method_consist_algorithms':
            subject = answers[0]['method.method_name'] if answers[0]['method.method_name'] else answers[0][
                'method.selection_method_id']
            desc = [f"算法ID:{i['algorithm.selection_algorithm_id']} 算法名称:{i['algorithm.algorithm_name']}" for i in
                    answers]
            final_answer = '方法{0}包含以下算法：{1}'.format(subject, '；'.join(list(set(desc))[:self.num_limit]))

        # 方法-文献关系查询
        elif question_type == 'method_cites_references':
            subject = answers[0]['method.method_name'] if answers[0]['method.method_name'] else answers[0][
                'method.selection_method_id']
            desc = [
                f"{i['ref.reference_id']} 详情:{i['ref.details']} 作者:{i['ref.authors']} 年份:{i['ref.year']}"
                for i in answers]
            final_answer = '方法{0}引用了以下文献：{1}'.format(subject, '；'.join(list(set(desc))[:self.num_limit]))

        elif question_type == 'reference_cited_by_methods':
            subject = answers[0]['ref.details'] if answers[0]['ref.details'] else answers[0]['ref.reference_id']
            desc = [f"方法ID:{i['method.selection_method_id']} 方法名称:{i['method.method_name']}" for i in answers]
            final_answer = '文献{0}被以下方法引用：{1}'.format(subject, '；'.join(list(set(desc))[:self.num_limit]))

        # 方案-原则关系查询
        elif question_type == 'scheme_applies_principles':
            subject = answers[0]['scheme.name'] if answers[0]['scheme.name'] else answers[0]['scheme.scheme_id']
            desc = [
                f"原则ID:{i['principle.scale_integration_principle_id']} 比例:{i['principle.scale_value']} 要求:{i['principle.integration_requirement']}"
                for i in answers]
            final_answer = '方案{0}应用了以下比例尺综合原则：{1}'.format(subject,
                                                                        '；'.join(list(set(desc))[:self.num_limit]))

        elif question_type == 'principle_used_in_schemes':
            subject = answers[0]['principle.scale_integration_principle_id']
            desc = [f"方案名称:{i['scheme.name']}" for i in answers]
            final_answer = '比例尺综合原则{0}被以下方案应用：{1}'.format(subject,
                                                                        '；'.join(list(set(desc))[:self.num_limit]))

        # 道路属性查询
        elif question_type.startswith('road_'):
            attr = question_type.split('road_')[1]
            subject = answers[0]['r.Name'] if answers[0]['r.Name'] else answers[0]['r.RoID']
            desc = [f"{i['r.' + attr]}" for i in answers]
            final_answer = '{0}的{1}是：{2}'.format(subject, answers_mapping[attr],
                                                   '；'.join(list(set(desc))[:self.num_limit]))

        # 路段属性查询
        elif question_type == 'segment_length':
            subject = answers[0]['s.SeID']
            desc = [f"{i['s.Length']}" for i in answers]
            final_answer = '路段{0}的长度是：{1}'.format(subject, '；'.join(list(set(desc))[:self.num_limit]))

        # 网格属性查询
        elif question_type.startswith('mesh_'):
            attr = question_type.split('_')[1].capitalize()
            subject = answers[0]['m.MeID']
            desc = [f"{i['m.' + attr]}" for i in answers]
            final_answer = '网格{0}的{1}是：{2}'.format(subject, answers_mapping[attr],
                                                       '；'.join(list(set(desc))[:self.num_limit]))

        # 方案属性查询
        elif question_type.startswith('scheme_'):
            attr = question_type.split('_')[1]
            subject = answers[0]['s.name']
            desc = [f"{i['s.' + attr]}" for i in answers]
            final_answer = '{0}的{1}是：{2}'.format(subject, answers_mapping[attr],
                                                   '；'.join(list(set(desc))[:self.num_limit]))

        # 方法属性查询
        elif question_type.startswith('method_'):
            attr = question_type.split('_')[-1]
            subject = answers[0]['m.selection_method_id']
            desc = [f"{i['m.' + attr]}" for i in answers]
            final_answer = '{0}的{1}是：{2}'.format(subject, answers_mapping[attr],
                                                   '；'.join(list(set(desc))[:self.num_limit]))

        # 算法属性查询
        elif question_type.startswith('algorithm_'):
            attr = question_type.split('_')[1]
            subject = answers[0]['a.algorithm_name']
            desc = [f"{i['a.' + attr]}" for i in answers]
            final_answer = '{0}的{1}是：{2}'.format(subject, answers_mapping[attr],
                                                   '；'.join(list(set(desc))[:self.num_limit]))

        # 原则属性查询
        elif question_type.startswith('principle_'):
            attr = question_type.split('principle_')[1]
            subject = answers[0]['p.scale_integration_principle_id']
            desc = [f"{i['p.' + attr]}" for i in answers]
            final_answer = '{0}的{1}是：{2}'.format(subject, answers_mapping[attr],
                                                   '；'.join(list(set(desc))[:self.num_limit]))

        # 文献属性查询
        elif question_type.startswith('reference_'):
            attr = question_type.split('_')[1]
            subject = answers[0]['r.reference_id']
            desc = [f"{i['r.' + attr]}" for i in answers]
            final_answer = '{0}的{1}是：{2}'.format(subject, answers_mapping[attr],
                                                   '；'.join(list(set(desc))[:self.num_limit]))

        return final_answer


if __name__ == '__main__':
    searcher = AnswerSearcher()
