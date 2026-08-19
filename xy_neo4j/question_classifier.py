#!/usr/bin/env python3
# coding: utf-8
# File: question_classifier.py
# Author: lhy<lhy_in_blcu@126.com,https://huangyong.github.io>
# Date: 18-10-4

import os
import re
import logging
from difflib import SequenceMatcher
import ahocorasick


class QuestionClassifier:
    def __init__(self):
        # 使用更安全的路径处理方式
        cur_dir = os.path.dirname(os.path.abspath(__file__))
        # cur_dir = 'xy_neo4j/'
        # 特征词路径
        self.road_path = os.path.join(cur_dir, 'dict/road.txt')
        self.principle_path = os.path.join(cur_dir, 'dict/比例尺综合原则.txt')
        self.scheme_path = os.path.join(cur_dir, 'dict/路网综合方案.txt')
        self.method_path = os.path.join(cur_dir, 'dict/路网选取方法.txt')
        self.algorithm_path = os.path.join(cur_dir, 'dict/algorithm.txt')
        # 加载特征词 - 使用 with 语句确保文件关闭
        self.road_wds = self._load_words(self.road_path)
        self.principle_wds = self._load_words(self.principle_path)
        self.scheme_wds = self._load_words(self.scheme_path)
        self.method_wds = self._load_words(self.method_path)
        self.algorithm_wds = self._load_words(self.algorithm_path)
        self.region_words = set(
            self.road_wds + self.principle_wds + self.scheme_wds + self.method_wds + self.algorithm_wds)

        # 构造领域actree
        self.region_tree = self.build_actree(list(self.region_words))

        # 构建词典
        self.wdtype_dict = self.build_wdtype_dict()

        # 初始化问句疑问词和属性词典
        self._init_question_patterns()

        logging.info('知识图谱问句分类器初始化完成')

    def _load_words(self, filepath):
        """从文件加载词汇，使用with语句确保文件关闭"""
        try:
            with open(filepath, encoding='utf-8') as f:
                return [i.strip() for i in f if i.strip()]
        except FileNotFoundError:
            logging.error(f"找不到文件: {filepath}")
            return []

    def _init_question_patterns(self):
        """初始化所有问句模式"""
        # 关系疑问词
        self._init_relation_patterns()

        # 属性疑问词
        self._init_attribute_patterns()

        # 查询所有实体的模式
        self._init_general_query_patterns()

    def _init_relation_patterns(self):
        """初始化关系问句模式"""
        # 新增关系疑问词（带数字匹配模式）
        self.part_of_qwds = [
            '属于', '归属于', '所属',
            '哪条道路', '哪条路',
            re.compile(r'属于哪[条个]'),
            re.compile(r'是哪[条个]的')
        ]
        self.connect_to_qwds = ['连接', '连着', '相连', '联通', '连通']
        self.consist_of_qwds = [
            '包含哪些', '由哪些组成', '组成部分', '包括', '包含', '采用什么', '使用的方法', '集成了哪些方法',
            re.compile(r'由.*?[构组]成'),
            re.compile(r'有哪[些个]'),
            re.compile(r'由.*?路段[构组]成'),
            re.compile(r'有哪[些个]'),
            re.compile(r'的组成部分'),
            re.compile(r'由.*?方法[组成实现]'),
            re.compile(r'包含.*?方法'),
            re.compile(r'用了.*?算法'),
            re.compile(r'由.*?算法[实现组成]')
        ]

        self.method_reference_qwds = [
            '参考哪些文献', '引用了什么论文', '依据的研究', '引用', '使用', '包括什么文献', '包含什么文献',
            '基于哪些文献', '引用哪些的论文', '文献支持', '文献'
        ]
        self.scheme_principle_qwds = [
            '应用哪些原则', '遵循什么标准', '使用的综合原则',
            '基于什么比例尺原则', '基于哪个比例尺原则',
            '应用了哪些比例尺原则', '应用方案', '选取方案'
        ]

    def _init_attribute_patterns(self):
        """初始化属性问句模式"""
        # 道路属性疑问词
        self.road_attr_qwds = {
            'fclass': ['类型', '类别'],
            'name': ['道路名称', '名字', '路名'],
            'bridge': ['桥梁', '是否有桥', '包含桥梁'],
            'tunnel': ['隧道', '是否有隧道', '包含隧道'],
            'ClassZn2': ['道路等级', '等级编号', '等级'],
            'Shape_Leng': ['道路长度', '总长', '长度', '长']
        }

        # 路段属性疑问词
        self.segment_attr_qwds = ['路段长度', '长度是多少', '有多长', '长度', '长']

        # 网格属性疑问词
        self.mesh_attr_qwds = {
            'Length': ['周长', '周长是多少'],
            'Area': ['面积', '面积多大'],
            'Circle': ['紧凑度', '紧凑性指标'],
            'Density': ['密度', '网眼密度']
        }

        self.scheme_attr_qwds = {
            'description': ['描述', '详细介绍', '内容', '步骤', '内容', r'方案.*?的说明'],
            'name': ['方案名称', '方案全称', '名字']
        }
        self.method_attr_qwds = {
            'description': ['描述', '实现原理', '具体步骤', r'如何.*?实现', ],
            'method_name': ['名称', '方法简称', '名字']
        }
        self.algorithm_attr_qwds = {
            'description': ['算法步骤', '步骤', '实现流程', '详细过程', re.compile(r'[如何怎么].*?操作')]
        }
        self.principle_attr_qwds = {
            'scale_value': ['比值'],
            'integration_requirement': ['综合要求', '选取标准', r'需要.*?满足的条件', '标准', '要求', '原则'],
            'integration_threshold': ['综合阈值', '取舍标准', r'长度.*?要求', '阈值']
        }
        self.reference_attr_qwds = {
            'details': ['文献详情', '论文信息', '发表内容', '名字', '详情'],
            'authors': ['作者'],
            'year': ['发表年份', '哪一年出版', r'\d{4}年.*?发表', '年']
        }

    def _init_general_query_patterns(self):
        """初始化通用查询模式，用于查询所有实体"""
        # 查询所有方法的模式
        self.all_methods_qwds = [
            '有哪些方法', '有什么方法', '包含哪些方法', '都有什么方法',
            re.compile(r'路网选取.*?有哪些方法'),
            re.compile(r'路网选取.*?方法有哪些'),
            re.compile(r'有哪些.*?路网选取方法')
        ]

        # 查询所有原则的模式
        self.all_principles_qwds = [
            '有哪些原则', '有什么原则', '包含哪些原则', '都有什么原则',
            re.compile(r'路网选取.*?有哪些原则'),
            re.compile(r'路网选取.*?原则有哪些'),
            re.compile(r'有哪些.*?比例尺综合原则')
        ]

        # 查询所有方案的模式
        self.all_schemes_qwds = [
            '有哪些方案', '有什么方案', '包含哪些方案', '都有什么方案',
            re.compile(r'路网选取.*?有哪些方案'),
            re.compile(r'路网选取.*?方案有哪些'),
            re.compile(r'有哪些.*?路网综合方案')
        ]

        # 查询所有算法的模式
        self.all_algorithms_qwds = [
            '有哪些算法', '有什么算法', '包含哪些算法', '都有什么算法',
            re.compile(r'路网选取.*?有哪些算法'),
            re.compile(r'路网选取.*?算法有哪些'),
            re.compile(r'有哪些.*?选取算法')
        ]

    def classify(self, question):
        """分类主函数"""
        # 提取常规实体 (道路、原则、方案、方法)
        medical_dict = self.check_medical(question)
        data = {'args': medical_dict}
        types = [t for v in medical_dict.values() for t in v]

        # 路段和网眼实体识别（使用预编译正则）
        number_entities = self.extract_number_entities(question)
        candidate_roads = {}
        if number_entities.get('road'):
            number_entities['road'], candidate_roads = self.resolve_road_entities(number_entities['road'])
        data['args'].update(number_entities)
        types += list(number_entities.keys())
        if candidate_roads:
            data['candidate_roads'] = candidate_roads

        # 添加通用查询识别逻辑
        # 即使没有识别到具体实体，我们也允许继续处理通用查询
        self._current_args = data['args']
        question_types = self._identify_question_types(question, types)

        # 对于通用查询，即使没有具体实体，也继续处理
        if (not medical_dict and not number_entities) and not any(qt.startswith('all_') for qt in question_types):
            return None

        data['question_types'] = question_types
        return data

    def _identify_question_types(self, question, types):
        """识别问题类型"""
        question_types = []

        # 关系型问题判断
        self._identify_relation_questions(question, types, question_types)
        question_types = self._dedupe_question_types(question_types)
        if self._has_priority_relation(question_types):
            return self._prioritize_question_types(question_types)

        # 属性型问题判断
        self._identify_attribute_questions(question, types, question_types)

        # 识别通用查询问题
        self._identify_general_query_questions(question, question_types)

        return self._prioritize_question_types(self._dedupe_question_types(question_types))

    def _dedupe_question_types(self, question_types):
        return list(dict.fromkeys(question_types))

    def _has_priority_relation(self, question_types):
        priority_relations = {'road_connection_between', 'road_connect_road'}
        return any(qt in priority_relations for qt in question_types)

    def _prioritize_question_types(self, question_types):
        priority = [
            'road_connection_between',
            'road_connect_road',
            'road_contains_segments',
            'mesh_contains_segments',
            'scheme_contains_methods',
            'method_contains_algorithms',
            'road_consist_segments',
            'mesh_consist_segments',
            'scheme_consist_methods',
            'method_consist_algorithms',
            'method_cites_references',
            'reference_cited_by_methods',
            'scheme_applies_principles',
            'principle_used_in_schemes',
        ]
        for question_type in priority:
            if question_type in question_types:
                if question_type in {'road_connection_between', 'road_connect_road'}:
                    return [question_type]
                break
        return sorted(question_types, key=lambda qt: priority.index(qt) if qt in priority else len(priority))

    def _identify_relation_questions(self, question, types, question_types):
        """识别关系型问题"""
        # Part_of关系判断（路段→道路/网格）
        if self.check_words(self.part_of_qwds, question) is not None:
            if 'method' in types:
                question_types.append('scheme_contains_methods')  # 方法属于哪个方案
            if 'algorithm' in types:
                question_types.append('method_contains_algorithms')  # 算法属于哪个方法
            if 'segment' in types:
                if self.check_words(['网格', '网眼', '密度'], question) is not None:
                    question_types.append('mesh_contains_segments')  # 路段1属于哪个网格
                else:  # 仅提到路段的情况
                    question_types.append('road_contains_segments')  # 路段1属于哪条路
        # connect_to
        has_connection_word = self.check_words(self.connect_to_qwds, question) is not None
        if has_connection_word:
            if 'road' in types:
                road_entities = self._get_road_entities_from_args(getattr(self, '_current_args', {}))
                is_yes_no = self.check_words(['吗', '是否', '是不是'], question) is not None
                if is_yes_no and len(road_entities) >= 2:
                    question_types.append('road_connection_between')
                else:
                    question_types.append('road_connect_road')  # 路连接什么路

        # Consist_of关系判断（道路/网格→路段）
        if not has_connection_word and self.check_words(self.consist_of_qwds, question) is not None:
            if 'road' in types:
                question_types.append('road_consist_segments')  # 路包含什么路段
            if 'mesh' in types:
                question_types.append('mesh_consist_segments')  # 网眼包含什么路段
            if 'scheme' in types:
                question_types.append('scheme_consist_methods')  # 方案包括什么方法
            if 'method' in types:
                question_types.append('method_consist_algorithms')  # 路网选取方法2使用了哪些算法

        # 方法-文献关系
        if self.check_words(self.method_reference_qwds, question) is not None:
            if 'method' in types:
                question_types.append('method_cites_references')  # 方法使用了哪些文献
            elif 'reference' in types:
                question_types.append('reference_cited_by_methods')  # 文献46被哪些方法引用过

        # 方案-原则关系
        if self.check_words(self.scheme_principle_qwds, question) is not None:
            if 'scheme' in types:
                question_types.append('scheme_applies_principles')  # 方案应用了什么原则
            elif 'principle' in types:
                question_types.append('principle_used_in_schemes')  # 比例尺综合原则_25000被哪些方案应用

    def _identify_attribute_questions(self, question, types, question_types):
        """识别属性型问题"""

        # 道路属性
        if 'road' in types:
            for attr, qwds in self.road_attr_qwds.items():
                check = self.check_words(qwds, question)
                if check is not None:
                    question_types.append(f'road_{attr}')

        # 路段属性
        if ('segment' in types) and (self.check_words(self.segment_attr_qwds, question) is not None):
            question_types.append('segment_length')

        # 网格属性
        if 'mesh' in types:
            for attr, qwds in self.mesh_attr_qwds.items():
                check = self.check_words(qwds, question)
                if check is not None:
                    question_types.append(f'mesh_{attr.lower()}')

        # 方案属性
        if 'scheme' in types:
            for attr, qwds in self.scheme_attr_qwds.items():
                check = self.check_words(qwds, question)
                if check is not None:
                    question_types.append(f'scheme_{attr}')

        # 方法属性
        if 'method' in types:
            for attr, qwds in self.method_attr_qwds.items():
                check = self.check_words(qwds, question)
                if check is not None:
                    question_types.append(f'method_{attr}')

        # 算法属性
        if 'algorithm' in types:
            for attr, qwds in self.algorithm_attr_qwds.items():
                check = self.check_words(qwds, question)
                if check is not None:
                    question_types.append(f'algorithm_{attr}')

        # 原则属性
        if 'principle' in types:
            for attr, qwds in self.principle_attr_qwds.items():
                check = self.check_words(qwds, question)
                if check is not None:
                    question_types.append(f'principle_{attr}')

        # 文献属性
        if 'reference' in types:
            for attr, qwds in self.reference_attr_qwds.items():
                check = self.check_words(qwds, question)
                if check is not None:
                    question_types.append(f'reference_{attr}')

    def _identify_general_query_questions(self, question, question_types):
        """识别通用查询问题"""
        # 查询所有方法
        if self.check_words(self.all_methods_qwds, question) is not None:
            question_types.append('all_selection_methods')

        # 查询所有原则
        if self.check_words(self.all_principles_qwds, question) is not None:
            question_types.append('all_scale_principles')

        # 查询所有方案
        if self.check_words(self.all_schemes_qwds, question) is not None:
            question_types.append('all_selection_schemes')

        # 查询所有算法
        if self.check_words(self.all_algorithms_qwds, question) is not None:
            question_types.append('all_selection_algorithms')

    def _get_road_entities_from_args(self, args):
        roads = []
        for key, value in (args or {}).items():
            if key == 'road' and isinstance(value, list):
                roads.extend(value)
            elif isinstance(value, list) and 'road' in value:
                roads.append(key)
        return list(dict.fromkeys(roads))

    def extract_number_entities(self, text):
        """统一提取带数字编号的实体（使用预编译正则表达式）"""
        entities = {}
        # 匹配路段（支持"路段1"/"段1"等格式）
        segments = re.findall(r'(路段|段)(\d+)', text)
        if segments:
            entities['segment'] = [f"{s[0]}{s[1]}" for s in segments]

        # 匹配网格（支持"网格1"/"网眼1"等格式）
        meshes = re.findall(r'(网格|网眼)(\d+)', text)
        if meshes:
            entities['mesh'] = [f"{m[0]}{m[1]}" for m in meshes]

        # 文献（支持"文献46"/"文献-23"）
        references = re.findall(r'(文献)[_\-]?(\d+)', text)
        if references:
            entities['reference'] = [f"{r[0]}{r[1]}" for r in references]

        road_names = self.extract_road_names_from_connection_question(text)
        if road_names:
            entities['road'] = road_names
        else:
            road_name = self.extract_road_name_from_connection_question(text)
            if road_name:
                entities['road'] = [road_name]

        scales = re.findall(r'1\s*[:：]\s*(\d{4,7})', text)
        if scales:
            entities['principle'] = [f"1:{scale}" for scale in scales]

        return entities

    def resolve_road_entities(self, road_names):
        """Resolve free-form road names and return candidate hints for unresolved names."""
        resolved = []
        candidates = {}
        for name in road_names or []:
            cleaned = self._clean_road_name(name)
            if not cleaned:
                continue
            if cleaned in self.road_wds:
                resolved.append(cleaned)
                continue

            normalized = self._normalize_road_name(cleaned)
            normalized_matches = [
                road for road in self.road_wds
                if normalized and self._normalize_road_name(road) == normalized
            ]
            if len(normalized_matches) == 1:
                resolved.append(normalized_matches[0])
                continue

            resolved.append(cleaned)
            candidates[cleaned] = self._find_road_candidates(cleaned)

        return list(dict.fromkeys(resolved)), candidates

    def _clean_road_name(self, name):
        return str(name).strip(' “”，。！？?')

    def _normalize_road_name(self, name):
        name = self._clean_road_name(name)
        for prefix in ['道路', '路名']:
            if name.startswith(prefix):
                name = name[len(prefix):]
        for suffix in ['高速公路', '快速路', '大街', '胡同', '街', '巷', '路']:
            if name.endswith(suffix) and len(name) > len(suffix):
                name = name[:-len(suffix)]
                break
        return name

    def _find_road_candidates(self, road_name, limit=5):
        normalized = self._normalize_road_name(road_name)
        scored = []
        for road in self.road_wds:
            road_normalized = self._normalize_road_name(road)
            score = 0
            if road_name and (road_name in road or road in road_name):
                score = 100 + min(len(road_name), len(road))
            elif normalized and (normalized in road_normalized or road_normalized in normalized):
                score = 80 + min(len(normalized), len(road_normalized))
            else:
                score = int(SequenceMatcher(None, normalized or road_name, road_normalized or road).ratio() * 70)

            if score >= 45:
                scored.append((score, road))

        scored.sort(key=lambda item: (-item[0], len(item[1]), item[1]))
        return [road for _, road in scored[:limit]]

    def extract_road_names_from_connection_question(self, text):
        """Extract two free-form road names from yes/no connection questions."""
        if self.check_words(self.connect_to_qwds, text) is None:
            return []
        if self.check_words(['吗', '是否', '是不是'], text) is None:
            return []

        before_relation = re.split(r'(?:相连|连接|连通|联通|连着)', text, maxsplit=1)[0]
        before_relation = before_relation.strip(' ，。！？?')
        for prefix in ['请问', '查询', '道路']:
            if before_relation.startswith(prefix):
                before_relation = before_relation[len(prefix):].strip(' ，。！？?')

        parts = [
            self._clean_road_name(part)
            for part in re.split(r'[和与同、,，]', before_relation)
            if self._clean_road_name(part)
        ]
        parts = [
            part[2:] if part.startswith('道路') and len(part) > 2 else part
            for part in parts
        ]
        return list(dict.fromkeys(parts[-2:])) if len(parts) >= 2 else []

    def extract_road_name_from_connection_question(self, text):
        """Extract a free-form road name from connection questions."""
        if self.check_words(self.connect_to_qwds, text) is None:
            return None

        patterns = [
            r'(?:与|和|同)?(?:道路)?(.+?)(?:相连|连接|连通|联通|连着)的?道路',
            r'(?:与|和|同)?(?:道路)?(.+?)(?:相连|连接|连通|联通|连着).+?(?:道路|路)',
        ]
        for pattern in patterns:
            match = re.search(pattern, text)
            if not match:
                continue

            candidate = match.group(1).strip(' ，。！？?')
            for prefix in [
                '无法回答与道路', '无法回答与', '无法回答',
                '请问道路', '查询道路', '与道路', '和道路', '同道路',
                '请问', '查询', '道路', '与', '和', '同',
            ]:
                if candidate.startswith(prefix):
                    candidate = candidate[len(prefix):].strip(' ，。！？?')

            if candidate and '哪些' not in candidate and '什么' not in candidate:
                return candidate

        return None

    def check_words(self, patterns, text):
        for pattern in patterns:
            if isinstance(pattern, re.Pattern):  # 编译过的正则
                if pattern.search(text):
                    return pattern
            else:  # 普通字符串
                if pattern in text:
                    return pattern
        return None

    def build_wdtype_dict(self):
        """构造词对应的类型"""
        wd_dict = dict()
        for wd in self.region_words:
            wd_dict[wd] = []
            if wd in self.road_wds:
                wd_dict[wd].append('road')
            if wd in self.principle_wds:
                wd_dict[wd].append('principle')
            if wd in self.scheme_wds:
                wd_dict[wd].append('scheme')
            if wd in self.method_wds:
                wd_dict[wd].append('method')
            if wd in self.algorithm_wds:
                wd_dict[wd].append('algorithm')
        return wd_dict

    def build_actree(self, wordlist):
        """构造actree，加速过滤"""
        actree = ahocorasick.Automaton()
        for index, word in enumerate(wordlist):
            actree.add_word(word, (index, word))
        actree.make_automaton()
        return actree

    def check_medical(self, question):
        """问句过滤，提取实体"""
        region_wds = []
        for i in self.region_tree.iter(question):
            wd = i[1][1]
            region_wds.append(wd)

        # 更高效的子串检查算法
        stop_wds = set()
        sorted_wds = sorted(region_wds, key=len)
        for i, wd1 in enumerate(sorted_wds):
            for wd2 in sorted_wds[i + 1:]:
                if wd1 in wd2:  # wd1是wd2的子串
                    stop_wds.add(wd1)
                    break

        final_wds = [i for i in region_wds if i not in stop_wds]
        final_dict = {i: self.wdtype_dict.get(i) for i in final_wds}

        return final_dict


def main():
    """主函数：用于互动测试"""
    handler = QuestionClassifier()
    while True:
        question = input('input an question:')
        data = handler.classify(question)
        print(data)


if __name__ == '__main__':
    main()
