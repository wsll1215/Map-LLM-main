from neo4j import GraphDatabase
import os
import logging

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class Neo4jImporter:
    def __init__(self, uri, username, password, data_dir, use_apoc=False, clear_db=False):
        """
        初始化Neo4j导入器
        
        Args:
            uri: Neo4j数据库URI
            username: 用户名
            password: 密码
            data_dir: CSV文件所在目录
            use_apoc: 是否使用APOC插件进行批量导入
            clear_db: 导入前是否清空数据库
        """
        self.uri = uri
        self.username = username
        self.password = password
        self.data_dir = data_dir
        self.use_apoc = use_apoc
        self.clear_db = clear_db
        self.driver = None
    
    def connect(self):
        """连接到Neo4j数据库"""
        try:
            self.driver = GraphDatabase.driver(self.uri, auth=(self.username, self.password))
            logger.info("成功连接到Neo4j数据库")
        except Exception as e:
            logger.error(f"连接Neo4j数据库失败: {e}")
            raise
    
    def close(self):
        """关闭数据库连接"""
        if self.driver:
            self.driver.close()
            logger.info("Neo4j数据库连接已关闭")
    
    def run_query(self, query):
        """
        执行Cypher查询
        
        Args:
            query: Cypher查询语句
        """
        if not self.driver:
            logger.error("未连接到Neo4j数据库")
            return
        
        with self.driver.session() as session:
            try:
                result = session.run(query)
                logger.info("查询执行成功")
                return result
            except Exception as e:
                logger.error(f"查询执行失败: {e}")
                raise
    
    def clear_database(self):
        """清空数据库中的所有节点和关系"""
        if self.clear_db:
            logger.info("开始清空数据库...")
            # 先删除所有关系，再删除所有节点
            self.run_query("MATCH ()-[r]-() DELETE r")
            self.run_query("MATCH (n) DELETE n")
            logger.info("数据库已清空")
    
    def check_data_exists(self):
        """检查数据库中是否已存在数据"""
        with self.driver.session() as session:
            result = session.run("MATCH (n) RETURN count(n) as count")
            count = result.single()["count"]
            return count > 0
    
    def import_data(self):
        """导入所有CSV数据到Neo4j"""
        try:
            # 检查数据是否已存在
            if not self.clear_db and self.check_data_exists():
                logger.warning("数据库中已有数据存在。如果要重新导入，请使用clear_db=True参数。")
                logger.info("跳过数据导入过程")
                return
            
            # 如果需要，清空数据库
            if self.clear_db:
                self.clear_database()
            
            # 创建唯一约束
            self._create_constraints()
            
            # 导入节点数据
            self._import_roads()
            self._import_segments()
            self._import_meshes()
            self._import_selection_schemes()
            self._import_scale_integration_principles()
            self._import_selection_methods()
            self._import_selection_algorithms()
            self._import_references()
            
            # 导入关系数据
            self._import_mesh_segment_relations()
            self._import_road_segment_relations()
            self._import_method_algorithm_relations()
            self._import_scheme_method_relations()
            self._import_method_reference_relations()
            self._import_scheme_principle_relations()
            self._import_road_to_road_relations()
            
            logger.info("所有数据导入完成")
        except Exception as e:
            logger.error(f"数据导入过程中发生错误: {e}")
            raise
    
    def _create_constraints(self):
        """创建所有必要的唯一约束"""
        constraints = [
            "CREATE CONSTRAINT road_id_unique IF NOT EXISTS FOR (r:Road) REQUIRE r.RoID IS UNIQUE",
            "CREATE CONSTRAINT segment_id_unique IF NOT EXISTS FOR (s:Segment) REQUIRE s.SeID IS UNIQUE",
            "CREATE CONSTRAINT mesh_id_unique IF NOT EXISTS FOR (m:Mesh) REQUIRE m.MeID IS UNIQUE",
            "CREATE CONSTRAINT selection_scheme_unique IF NOT EXISTS FOR (s:SelectionScheme) REQUIRE s.scheme_id IS UNIQUE",
            "CREATE CONSTRAINT selection_method_unique IF NOT EXISTS FOR (m:SelectionMethod) REQUIRE m.selection_method_id IS UNIQUE",
            "CREATE CONSTRAINT selection_algorithm_unique IF NOT EXISTS FOR (a:SelectionAlgorithm) REQUIRE a.selection_algorithm_id IS UNIQUE",
            "CREATE CONSTRAINT reference_unique IF NOT EXISTS FOR (r:Reference) REQUIRE r.reference_id IS UNIQUE",
            "CREATE CONSTRAINT scale_principle_unique IF NOT EXISTS FOR (s:ScaleIntegrationPrinciple) REQUIRE s.scale_integration_principle_id IS UNIQUE"
        ]
        
        for constraint in constraints:
            try:
                self.run_query(constraint)
                logger.info(f"创建约束: {constraint}")
            except Exception as e:
                logger.warning(f"创建约束失败 (可能已存在): {constraint}, 错误: {e}")
    
    def _import_roads(self):
        """导入道路数据"""
        file_path = os.path.join(self.data_dir, "Road.csv")
        file_name = os.path.basename(file_path)
        
        query = """
        LOAD CSV WITH HEADERS FROM $file_url AS row
        CREATE (:Road {
          RoID: row.RoID,
          fclass: row.fclass,
          Name: row.Name,
          bridge: row.bridge,
          tunnel: row.tunnel,
          ClassZn2: toInteger(row.ClassZn2),
          Shape_Leng: toFloat(row.Shape_Leng)
        })
        """
        
        file_url = f"file:///{file_name}"
        self.run_query(query.replace("$file_url", f"'{file_url}'"))
        logger.info("道路数据导入完成")
    
    def _import_segments(self):
        """导入路段数据"""
        file_path = os.path.join(self.data_dir, "Segment.CSV")
        file_name = os.path.basename(file_path)
        
        query = """
        LOAD CSV WITH HEADERS FROM $file_url AS row
        CREATE (:Segment {
          SeID: toInteger(row.SeID),
          Length: toFloat(row.Length)
        })
        """
        
        file_url = f"file:///{file_name}"
        self.run_query(query.replace("$file_url", f"'{file_url}'"))
        logger.info("路段数据导入完成")
    
    def _import_meshes(self):
        """导入网眼数据"""
        file_path = os.path.join(self.data_dir, "Mesh.csv")
        file_name = os.path.basename(file_path)
        
        query = """
        LOAD CSV WITH HEADERS FROM $file_url AS row
        CREATE (:Mesh {
          MeID: toInteger(row.MeID),     
          Length: toFloat(row.Length),    
          Area: toFloat(row.Area),         
          Circle: toFloat(row.Circle),     
          Density: toFloat(row.Density)   
        })
        """
        
        file_url = f"file:///{file_name}"
        self.run_query(query.replace("$file_url", f"'{file_url}'"))
        logger.info("网眼数据导入完成")
    
    def _import_selection_schemes(self):
        """导入路网选取方案"""
        file_path = os.path.join(self.data_dir, "SelectionScheme.csv")
        file_name = os.path.basename(file_path)
        
        query = """
        LOAD CSV WITH HEADERS FROM $file_url AS row
        CREATE (:SelectionScheme {
          scheme_id: row.scheme_id,       
          name: row.name,                 
          description: row.description   
        })
        """
        
        file_url = f"file:///{file_name}"
        self.run_query(query.replace("$file_url", f"'{file_url}'"))
        logger.info("路网选取方案导入完成")
    
    def _import_scale_integration_principles(self):
        """导入比例尺原则"""
        file_path = os.path.join(self.data_dir, "Scale_Integration_Principles.csv")
        file_name = os.path.basename(file_path)
        
        query = """
        LOAD CSV WITH HEADERS FROM $file_url AS row
        CREATE (:ScaleIntegrationPrinciple {
          scale_integration_principle_id: row.scale_integration_principle_id,
          scale_value: row.scale_value,
          integration_requirement: row.integration_requirement,
          integration_threshold: row.integration_threshold
        })
        """
        
        file_url = f"file:///{file_name}"
        self.run_query(query.replace("$file_url", f"'{file_url}'"))
        logger.info("比例尺原则导入完成")
    
    def _import_selection_methods(self):
        """导入方法"""
        file_path = os.path.join(self.data_dir, "Selection_Methods.csv")
        file_name = os.path.basename(file_path)
        
        query = """
        LOAD CSV WITH HEADERS FROM $file_url AS row
        MERGE (m:SelectionMethod {
          selection_method_id: row.selection_method_id
        })
        SET 
          m.method_name = row.method_name,
          m.description = row.description
        """
        
        file_url = f"file:///{file_name}"
        self.run_query(query.replace("$file_url", f"'{file_url}'"))
        logger.info("选择方法导入完成")
    
    def _import_selection_algorithms(self):
        """导入算法"""
        file_path = os.path.join(self.data_dir, "Selection_Algorithms.csv")
        file_name = os.path.basename(file_path)
        
        query = """
        LOAD CSV WITH HEADERS FROM $file_url AS row
        MERGE (a:SelectionAlgorithm {
          selection_algorithm_id: row.selection_algorithm_id
        })
        SET 
          a.algorithm_name = row.algorithm_name,
          a.description = row.description
        """
        
        file_url = f"file:///{file_name}"
        self.run_query(query.replace("$file_url", f"'{file_url}'"))
        logger.info("选择算法导入完成")
    
    def _import_references(self):
        """导入参考文献"""
        file_path = os.path.join(self.data_dir, "References.csv")
        file_name = os.path.basename(file_path)
        
        query = """
        LOAD CSV WITH HEADERS FROM $file_url AS row
        MERGE (r:Reference {reference_id: row.reference_id})
        SET 
          r.details = row.details,
          r.authors = row.authors,
          r.year = toInteger(row.year)
        """
        
        file_url = f"file:///{file_name}"
        self.run_query(query.replace("$file_url", f"'{file_url}'"))
        logger.info("参考文献导入完成")
    
    def _import_mesh_segment_relations(self):
        """导入网眼-路段关系"""
        file_path = os.path.join(self.data_dir, "Mesh_Segment_Relation.csv")
        file_name = os.path.basename(file_path)
        
        if self.use_apoc:
            # 使用APOC方式
            query = """
            CALL apoc.periodic.iterate(
              "LOAD CSV WITH HEADERS FROM $file_url AS row RETURN row",
              "MATCH (mesh:Mesh {MeID: toInteger(row.MeID)}), (segment:Segment {SeID: toInteger(row.SeID)})
               CREATE (mesh)-[:CONSISTS_OF {Relationship: row.Relationship}]->(segment)",
              {batchSize:500, parallel:true}
            )
            """
        else:
            # 使用新的事务子查询语法替代PERIODIC COMMIT
            query = """
            CALL {
              LOAD CSV WITH HEADERS FROM $file_url AS row
              MATCH (mesh:Mesh {MeID: toInteger(row.MeID)})
              MATCH (segment:Segment {SeID: toInteger(row.SeID)})
              CREATE (mesh)-[:CONSISTS_OF {Relationship: row.Relationship}]->(segment)
            } IN TRANSACTIONS OF 500 ROWS
            """
        
        file_url = f"file:///{file_name}"
        self.run_query(query.replace("$file_url", f"'{file_url}'"))
        logger.info("网眼-路段关系导入完成")
    
    def _import_road_segment_relations(self):
        """导入路段-道路关系"""
        file_path = os.path.join(self.data_dir, "Road_Segment_Relation.csv")
        file_name = os.path.basename(file_path)
        
        if self.use_apoc:
            # 使用APOC方式
            query = """
            CALL apoc.periodic.iterate(
              "LOAD CSV WITH HEADERS FROM $file_url AS row RETURN row",
              "MATCH (segment:Segment {SeID: toInteger(row.SeID)}), (road:Road {RoID: coalesce(row.RoID, '')})
               CREATE (segment)-[:PART_OF {Relationship: row.Relationship}]->(road)",
              {batchSize:500, parallel:true}
            )
            """
        else:
            # 使用新的事务子查询语法替代PERIODIC COMMIT
            query = """
            CALL {
              LOAD CSV WITH HEADERS FROM $file_url AS row
              MATCH (segment:Segment {SeID: toInteger(row.SeID)})
              MATCH (road:Road {RoID: coalesce(row.RoID, '')})
              CREATE (segment)-[:PART_OF {Relationship: row.Relationship}]->(road)
            } IN TRANSACTIONS OF 500 ROWS
            """
        
        file_url = f"file:///{file_name}"
        self.run_query(query.replace("$file_url", f"'{file_url}'"))
        logger.info("路段-道路关系导入完成")
    
    def _import_method_algorithm_relations(self):
        """导入方法-算法关系"""
        file_path = os.path.join(self.data_dir, "Methods-Algorithms.csv")
        file_name = os.path.basename(file_path)
        
        # 使用OPTIONAL MATCH避免笛卡尔积
        query = """
        LOAD CSV WITH HEADERS FROM $file_url AS row
        MATCH (method:SelectionMethod {selection_method_id: row.selection_method_id})
        MATCH (algorithm:SelectionAlgorithm {selection_algorithm_id: row.selection_algorithm_id})
        WHERE method IS NOT NULL AND algorithm IS NOT NULL
        MERGE (method)-[:CONTAINS_ALGORITHM]->(algorithm)
        """
        
        file_url = f"file:///{file_name}"
        self.run_query(query.replace("$file_url", f"'{file_url}'"))
        logger.info("方法-算法关系导入完成")
    
    def _import_scheme_method_relations(self):
        """导入方案-方法关系"""
        file_path = os.path.join(self.data_dir, "Methods-Schemes.csv")
        file_name = os.path.basename(file_path)
        
        # 使用OPTIONAL MATCH避免笛卡尔积
        query = """
        LOAD CSV WITH HEADERS FROM $file_url AS row
        MATCH (scheme:SelectionScheme {scheme_id: row.scheme_id})
        MATCH (method:SelectionMethod {selection_method_id: row.selection_method_id})
        WHERE scheme IS NOT NULL AND method IS NOT NULL
        MERGE (scheme)-[:CONTAINS_METHOD]->(method)
        """
        
        file_url = f"file:///{file_name}"
        self.run_query(query.replace("$file_url", f"'{file_url}'"))
        logger.info("方案-方法关系导入完成")
    
    def _import_method_reference_relations(self):
        """导入方法-参考文献关系"""
        file_path = os.path.join(self.data_dir, "References-Selection_Methods.csv")
        file_name = os.path.basename(file_path)
        
        # 使用OPTIONAL MATCH避免笛卡尔积
        query = """
        LOAD CSV WITH HEADERS FROM $file_url AS row
        MATCH (method:SelectionMethod {selection_method_id: row.selection_method_id})
        MATCH (ref:Reference {reference_id: row.reference_id})
        WHERE method IS NOT NULL AND ref IS NOT NULL
        MERGE (method)-[:CITES_REFERENCE]->(ref)
        """
        
        file_url = f"file:///{file_name}"
        self.run_query(query.replace("$file_url", f"'{file_url}'"))
        logger.info("方法-参考文献关系导入完成")
    
    def _import_scheme_principle_relations(self):
        """导入方案-比例尺原则关系"""
        file_path = os.path.join(self.data_dir, "Scale_Integration_Principles-Selection_Schemes.csv")
        file_name = os.path.basename(file_path)
        
        # 使用OPTIONAL MATCH避免笛卡尔积
        query = """
        LOAD CSV WITH HEADERS FROM $file_url AS row
        MATCH (scheme:SelectionScheme {scheme_id: row.scheme_id})
        MATCH (principle:ScaleIntegrationPrinciple {scale_integration_principle_id: row.scale_integration_principle_id})
        WHERE scheme IS NOT NULL AND principle IS NOT NULL
        MERGE (scheme)-[:APPLIES_PRINCIPLE]->(principle)
        """
        
        file_url = f"file:///{file_name}"
        self.run_query(query.replace("$file_url", f"'{file_url}'"))
        logger.info("方案-比例尺原则关系导入完成")
    
    def _import_road_to_road_relations(self):
        """导入道路-道路连接关系"""
        file_path = os.path.join(self.data_dir, "RoadtoRoad.csv")
        file_name = os.path.basename(file_path)
        
        if self.use_apoc and os.path.getsize(file_path) > 10000000:  # 如果文件超过10MB，使用APOC
            query = """
            CALL apoc.periodic.iterate(
              "LOAD CSV WITH HEADERS FROM $file_url AS row 
               WITH row WHERE row.RoID IS NOT NULL AND row.RoID_end IS NOT NULL
               RETURN row",
              "MATCH (source:Road {RoID: row.RoID})
               MATCH (target:Road {RoID: row.RoID_end})
               CREATE (source)-[:CONNECT_TO]->(target)",
              {batchSize:500, parallel:true}
            )
            """
        else:
            # 使用新的事务子查询语法
            query = """
            CALL {
              LOAD CSV WITH HEADERS FROM $file_url AS row
              WITH row WHERE row.RoID IS NOT NULL AND row.RoID_end IS NOT NULL
              MATCH (source:Road {RoID: row.RoID})
              MATCH (target:Road {RoID: row.RoID_end})
              CREATE (source)-[:CONNECT_TO]->(target)
            } IN TRANSACTIONS OF 500 ROWS
            """
        
        file_url = f"file:///{file_name}"
        self.run_query(query.replace("$file_url", f"'{file_url}'"))
        logger.info("道路-道路连接关系导入完成")

def main():
    """主函数，用于启动导入过程"""
    try:
        neo4j_uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
        neo4j_user = os.getenv("NEO4J_USER", "neo4j")
        neo4j_password = os.getenv("NEO4J_PASSWORD", "neo4j")
        data_directory = os.getenv("DATA_DIRECTORY_BASE", "../data")
        use_apoc = os.getenv("NEO4J_USE_APOC", "false").lower() == "true"
        clear_db = os.getenv("NEO4J_CLEAR_DB", "true").lower() == "true"
        
        # 创建导入器实例
        importer = Neo4jImporter(neo4j_uri, neo4j_user, neo4j_password, data_directory, use_apoc, clear_db)
        
        # 连接数据库
        importer.connect()
        
        # 导入数据
        importer.import_data()
        
    except Exception as e:
        logger.error(f"导入过程中发生错误: {e}")
    finally:
        # 确保连接关闭
        if 'importer' in locals() and importer:
            importer.close()

if __name__ == "__main__":
    main() 
