#!/usr/bin/env python3
# coding: utf-8
# File: question_parser.py

import re

class QuestionPaser:
    '''构建实体节点'''

    def build_entitydict(self, args):
        entity_dict = {}
        for arg, types in args.items():
            for type in types:
                if type not in entity_dict:
                    entity_dict[type] = [arg]
                else:
                    entity_dict[type].append(arg)

        return entity_dict

    '''解析主函数'''

    def parser_main(self, res_classify):
        args = res_classify['args']
        entity_dict = self.build_entitydict(args)
        question_types = res_classify['question_types']
        sqls = []
        for question_type in question_types:
            sql_ = {}
            sql_['question_type'] = question_type
            sql = []

            # 处理通用查询类型（查询所有实体）
            if question_type == 'all_selection_methods':
                sql = self.sql_transfer(question_type, None)
            elif question_type == 'all_scale_principles':
                sql = self.sql_transfer(question_type, None)
            elif question_type == 'all_selection_schemes':
                sql = self.sql_transfer(question_type, None)
            elif question_type == 'all_selection_algorithms':
                sql = self.sql_transfer(question_type, None)
            # 道路-路段关系
            elif question_type == 'road_contains_segments':   # 路段1属于哪条路
                sql = self.sql_transfer(question_type, args.get('segment'))
            elif question_type == 'road_consist_segments':   # 路包含什么路段
                sql = self.sql_transfer(question_type, entity_dict.get('road') or args.get('road'))
            elif question_type == 'road_connection_between':
                sql = self.sql_transfer(question_type, entity_dict.get('road') or args.get('road'))
            elif question_type == 'road_connect_road':
                sql = self.sql_transfer(question_type, entity_dict.get('road') or args.get('road'))

            # 网格-路段关系
            elif question_type == 'mesh_contains_segments':   # 路段1属于哪个网格
                sql = self.sql_transfer(question_type, args.get('segment'))
            elif question_type == 'mesh_consist_segments':    # 网眼包含什么路段
                sql = self.sql_transfer(question_type, args.get('mesh'))

            # 方案-方法关系
            elif question_type == 'scheme_contains_methods':    # 方法属于哪个方案
                sql = self.sql_transfer(question_type, entity_dict.get('method'))
            elif question_type == 'scheme_consist_methods':     #方案包括什么方法
                sql = self.sql_transfer(question_type, entity_dict.get('scheme'))

            # 方法-算法关系
            elif question_type == 'method_contains_algorithms':  # 算法属于哪个方法
                sql = self.sql_transfer(question_type, entity_dict.get('algorithm'))
            elif question_type == 'method_consist_algorithms': # 路网选取方法2使用了哪些算法
                sql = self.sql_transfer(question_type, entity_dict.get('method'))

            # 方法-文献关系
            elif question_type == 'method_cites_references':    #方法使用了哪些文献
                sql = self.sql_transfer(question_type, entity_dict.get('method'))
            elif question_type == 'reference_cited_by_methods':    # 文献46被哪些方法引用过
                sql = self.sql_transfer(question_type, args.get('reference'))

            # 方案-原则关系
            elif question_type == 'scheme_applies_principles':   #方案应用了什么原则
                sql = self.sql_transfer(question_type, entity_dict.get('scheme'))
            elif question_type == 'principle_used_in_schemes':  # 比例尺综合原则_25000被哪些方案应用
                sql = self.sql_transfer(question_type, entity_dict.get('principle'))

            # 道路属性查询
            elif question_type.startswith('road_'):
                sql = self.sql_transfer(question_type, entity_dict.get('road') or args.get('road'))

            # 路段属性查询
            elif question_type.startswith('segment_'):
                sql = self.sql_transfer(question_type, args.get('segment'))

            # 网格属性查询
            elif question_type.startswith('mesh_'):
                sql = self.sql_transfer(question_type, args.get('mesh'))

            # 方案属性查询
            elif question_type.startswith('scheme_'):
                sql = self.sql_transfer(question_type, entity_dict.get('scheme'))

            # 方法属性查询
            elif question_type.startswith('method_'):
                sql = self.sql_transfer(question_type, entity_dict.get('method'))

            # 算法属性查询
            elif question_type.startswith('algorithm_'):
                sql = self.sql_transfer(question_type, entity_dict.get('algorithm'))

            # 原则属性查询
            elif question_type.startswith('principle_'):
                sql = self.sql_transfer(question_type, entity_dict.get('principle') or args.get('principle'))

            # 文献属性查询
            elif question_type.startswith('reference_'):
                sql = self.sql_transfer(question_type, args.get('reference'))

            if sql:
                sql_['sql'] = sql
                sqls.append(sql_)

        return sqls

    '''针对不同的问题，生成对应的查询语句'''

    def sql_transfer(self, question_type, entities):
        # 对于通用查询类型，不需要特定实体
        if question_type.startswith('all_'):
            if question_type == 'all_selection_methods':
                return ["MATCH (m:SelectionMethod) RETURN m.selection_method_id, m.method_name"]
            if question_type == 'all_scale_principles':
                return ["MATCH (p:ScaleIntegrationPrinciple) RETURN p.scale_integration_principle_id, p.scale_value, p.integration_requirement, p.integration_threshold"]
            if question_type == 'all_selection_schemes':
                return ["MATCH (s:SelectionScheme) RETURN s.scheme_id, s.name"]
            if question_type == 'all_selection_algorithms':
                return ["MATCH (a:SelectionAlgorithm) RETURN a.selection_algorithm_id, a.algorithm_name"]
            return []

        if not entities:
            return []

        sql = []

        # 道路-路段关系查询
        if question_type == 'road_contains_segments':
            sql = [
                self._cypher(
                    "MATCH (s:Segment)-[:PART_OF]->(r:Road) "
                    "WHERE s.SeID = $segment_id "
                    "RETURN s.SeID, r.RoID, r.Name, r.fclass",
                    segment_id=self._entity_number(i)
                )
                for i in entities
            ]

        elif question_type == 'road_consist_segments':
            sql = [
                self._cypher(
                    "MATCH (s:Segment)-[:PART_OF]->(r:Road) "
                    "WHERE r.Name = $name "
                    "RETURN r.RoID, r.Name, s.SeID, s.Length",
                    name=i
                )
                for i in entities
            ]

        elif question_type == 'road_connect_road':
            sql = [
                self._cypher(
                    "MATCH (r0:Road {Name: $name})-[:CONNECT_TO]-(r:Road) "
                    "WHERE r.Name <> r0.Name "
                    "RETURN DISTINCT r0.RoID, r0.Name, r.RoID, r.Name",
                    name=i
                )
                for i in entities
            ]

        elif question_type == 'road_connection_between':
            if len(entities) >= 2:
                source, target = entities[0], entities[1]
                sql = [
                    self._cypher(
                        "MATCH (r0:Road {Name: $source}), (r1:Road {Name: $target}) "
                        "OPTIONAL MATCH (r0)-[rel:CONNECT_TO]-(r1) "
                        "RETURN r0.Name, r1.Name, count(rel) > 0 AS connected",
                        source=source,
                        target=target
                    )
                ]

        # 网格-路段关系查询
        elif question_type == 'mesh_contains_segments':
            sql = [
                self._cypher(
                    "MATCH (m:Mesh)-[:CONSISTS_OF]->(s:Segment) "
                    "WHERE s.SeID = $segment_id "
                    "RETURN s.SeID, m.MeID, m.Area, m.Density",
                    segment_id=self._entity_number(i)
                )
                for i in entities
            ]

        elif question_type == 'mesh_consist_segments':
            sql = [
                self._cypher(
                    "MATCH (m:Mesh)-[:CONSISTS_OF]->(s:Segment) "
                    "WHERE m.MeID = $mesh_id "
                    "RETURN m.MeID, s.SeID, s.Length",
                    mesh_id=self._entity_number(i)
                )
                for i in entities
            ]

        # 方案-方法关系查询
        elif question_type == 'scheme_contains_methods':
            sql = [
                self._cypher(
                    "MATCH (scheme:SelectionScheme)-[:CONTAINS_METHOD]->(method:SelectionMethod) "
                    "WHERE method.method_name = $name "
                    "RETURN scheme.scheme_id, scheme.name, method.selection_method_id, method.method_name",
                    name=i
                )
                for i in entities
            ]

        elif question_type == 'scheme_consist_methods':
            sql = [
                self._cypher(
                    "MATCH (scheme:SelectionScheme)-[:CONTAINS_METHOD]->(method:SelectionMethod) "
                    "WHERE scheme.name = $name "
                    "RETURN scheme.scheme_id, scheme.name, method.selection_method_id, method.method_name",
                    name=i
                )
                for i in entities
            ]

        # 方法-算法关系查询
        elif question_type == 'method_contains_algorithms':
            sql = [
                self._cypher(
                    "MATCH (method:SelectionMethod)-[:CONTAINS_ALGORITHM]->(algorithm:SelectionAlgorithm) "
                    "WHERE algorithm.algorithm_name = $name "
                    "RETURN method.selection_method_id, method.method_name, algorithm.selection_algorithm_id, algorithm.algorithm_name",
                    name=i
                )
                for i in entities
            ]

        elif question_type == 'method_consist_algorithms':
            sql = [
                self._cypher(
                    "MATCH (method:SelectionMethod)-[:CONTAINS_ALGORITHM]->(algorithm:SelectionAlgorithm) "
                    "WHERE method.method_name = $name "
                    "RETURN method.selection_method_id, method.method_name, algorithm.selection_algorithm_id, algorithm.algorithm_name",
                    name=i
                )
                for i in entities
            ]

        # 方法-文献关系查询
        elif question_type == 'method_cites_references':
            sql = [
                self._cypher(
                    "MATCH (method:SelectionMethod)-[:CITES_REFERENCE]->(ref:Reference) "
                    "WHERE method.method_name = $name "
                    "RETURN method.selection_method_id, method.method_name, ref.reference_id, ref.details, ref.authors, ref.year",
                    name=i
                )
                for i in entities
            ]

        elif question_type == 'reference_cited_by_methods':
            sql = [
                self._cypher(
                    "MATCH (method:SelectionMethod)-[:CITES_REFERENCE]->(ref:Reference) "
                    "WHERE ref.reference_id = $reference_id "
                    "RETURN method.selection_method_id, method.method_name, ref.reference_id, ref.details",
                    reference_id=i
                )
                for i in entities
            ]

        # 方案-原则关系查询
        elif question_type == 'scheme_applies_principles':
            sql = [
                self._cypher(
                    "MATCH (scheme:SelectionScheme)-[:APPLIES_PRINCIPLE]->(principle:ScaleIntegrationPrinciple) "
                    "WHERE scheme.name = $name "
                    "RETURN scheme.scheme_id, scheme.name, principle.scale_integration_principle_id, principle.scale_value, principle.integration_requirement",
                    name=i
                )
                for i in entities
            ]

        elif question_type == 'principle_used_in_schemes':
            sql = [
                self._cypher(
                    "MATCH (scheme:SelectionScheme)-[:APPLIES_PRINCIPLE]->(principle:ScaleIntegrationPrinciple) "
                    "WHERE principle.scale_integration_principle_id = $principle_id "
                    "RETURN scheme.scheme_id, scheme.name, principle.scale_integration_principle_id, principle.scale_value",
                    principle_id=i
                )
                for i in entities
            ]

        # 道路属性查询
        elif question_type.startswith('road_'):
            attr = question_type.split('road_')[1]
            sql = [
                self._cypher(
                    f"MATCH (r:Road) WHERE r.Name = $name RETURN r.RoID, r.Name, r.{attr}",
                    name=i
                )
                for i in entities
            ]

        # 路段属性查询
        elif question_type == 'segment_length':
            sql = [
                self._cypher(
                    "MATCH (s:Segment) WHERE s.SeID = $segment_id RETURN s.SeID, s.Length",
                    segment_id=self._entity_number(i)
                )
                for i in entities
            ]

        # 网格属性查询
        elif question_type.startswith('mesh_'):
            attr = question_type.split('_')[1].capitalize()
            sql = [
                self._cypher(
                    f"MATCH (m:Mesh) WHERE m.MeID = $mesh_id RETURN m.MeID, m.{attr}",
                    mesh_id=self._entity_number(i)
                )
                for i in entities
            ]

        # 方案属性查询
        elif question_type.startswith('scheme_'):
            attr = question_type.split('_')[-1]
            sql = [
                self._cypher(
                    f"MATCH (s:SelectionScheme) WHERE s.name = $name RETURN s.name, s.{attr}",
                    name=i
                )
                for i in entities
            ]

        # 方法属性查询
        elif question_type.startswith('method_'):
            attr = question_type.split('_')[-1]
            sql = [
                self._cypher(
                    f"MATCH (m:SelectionMethod) WHERE m.method_name = $name RETURN m.selection_method_id, m.{attr}",
                    name=i
                )
                for i in entities
            ]

        # 算法属性查询
        elif question_type.startswith('algorithm_'):
            attr = question_type.split('_')[1]
            sql = [
                self._cypher(
                    f"MATCH (a:SelectionAlgorithm) WHERE a.selection_algorithm_id = $algorithm_id RETURN a.algorithm_name, a.{attr}",
                    algorithm_id=i
                )
                for i in entities
            ]

        # 原则属性查询
        elif question_type.startswith('principle_'):
            attr = question_type.split('principle_')[1]
            sql = []
            for i in entities:
                if isinstance(i, str) and re.match(r'^1\s*[:：]\s*\d+$', i):
                    scale_value = i.replace('：', ':').replace(' ', '')
                    alt_scale_value = scale_value.replace(':', '：')
                    sql.append(
                        self._cypher(
                            f"MATCH (p:ScaleIntegrationPrinciple) "
                            f"WHERE p.scale_value IN $scale_values "
                            f"RETURN p.scale_integration_principle_id, p.scale_value, p.{attr}",
                            scale_values=[scale_value, alt_scale_value]
                        )
                    )
                else:
                    sql.append(
                        self._cypher(
                            f"MATCH (p:ScaleIntegrationPrinciple) "
                            f"WHERE p.scale_integration_principle_id = $principle_id "
                            f"RETURN p.scale_integration_principle_id, p.scale_value, p.{attr}",
                            principle_id=i
                        )
                    )

        # 文献属性查询
        elif question_type.startswith('reference_'):
            attr = question_type.split('_')[1]
            sql = [
                self._cypher(
                    f"MATCH (r:Reference) WHERE r.reference_id = $reference_id RETURN r.reference_id, r.{attr}",
                    reference_id=i
                )
                for i in entities
            ]
        return sql

    def _cypher(self, query, **params):
        return {'query': query, 'params': params}

    def _entity_number(self, entity):
        match = re.search(r'\d+', str(entity))
        return int(match.group(0)) if match else entity


if __name__ == '__main__':
    handler = QuestionPaser()
