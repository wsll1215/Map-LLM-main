#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
广东省行政区划图修改功能测试用例
基于具体制图要求的完整测试套件
"""

import sys
from datetime import datetime

# 设置 UTF-8 编码（Windows 兼容）
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

from gis_mapping_agent.utils.config import Config
from gis_mapping_agent.agent import ConversationalMappingAgent

class GuangdongMapModificationTester:
    """广东省地图修改功能测试器"""

    def __init__(self):

        self.agent = ConversationalMappingAgent(
            model_name=Config.OPENAI_MODEL,
            verbose=True
        )
        self.session_id = None
        self.test_results = []
        self.start_time = datetime.now()

        # 基础制图要求
        self.base1 = """使用data5目录中的数据生成地图:
                            Wuhan.shp, Skating Rink.shp, Racecourse.shp  
                        图层样式要求： 
                            Skating Rink.shp: 设计一个关于滑雪设施的符号，样式为矢量图层.
                            Racecourse.shp: 设计一个关于赛马的符号，样式为矢量图层   
                            Wuhan.shp: 根据 地名 属性调整多边形要素的颜色"""
        
        # self.base2 = """根据之前所有制图要求，添加以下制图要求：
        #                 对于 武汉市.shp 文件，根据 地名 属性调整多边形要素的颜色。
        #                 对于 赛马场.shp 文件，设计一个新的与赛马相关的符号，作为矢量图层的样式。
        #                 对于 冰雪运动.shp 文件，使用之前生成的符号作为矢量图层的样式。"""
        self.base_diturequest_beijing = """请使用data8目录中数据文件创建北京行政区划图：
                        beijing.shp, 综合前.shp

                        地图设置要求：
                        1. 不添加地图标题
                        2. 背景色：lightblue
                        图层样式要求： 
                            beijing.shp: 线宽稍微增加，颜色为黑色
                            综合前.shp: 颜色为白色, 添加图例为：路网
                        """

        self.base_diturequest = """请使用以下数据文件创建广东省行政区划图：
                        Coastal Economic Belt City.shp, Core City of the Pearl River Delta.shp, Guangdong.shp, Highway.shp, Provincial Deputy Central City.shp, Railway.shp

                        地图设置要求：
                        1. 地图标题：广东省行政区划图
                        2. 背景色：lightblue

                        图层样式要求：
                        - Highway.shp：线宽稍微增加，颜色改为白色
                        - Railway.shp：线宽稍微增加，颜色改为黑色，线型改为虚线
                        - Guangdong.shp：根据"地区"属性调整多边形颜色，并根据"地名"属性添加标签

                        最后添加一段约50字的中文说明，介绍广东省2023年的GDP发展情况。"""

        # 路网综合测试用例1：使用Stroke算法（基于尺度要求）
        self.base_luwangrequest_stroke = """请使用data7目录中的以下数据文件进行路网综合可视化：
                            综合前.shp

                            算法要求：
                            使用Stroke算法

                            尺度要求：
                            源尺度为1:500，目标尺度为1:20000的自动缩编

                           """

        # 路网综合测试用例2：使用GCNN算法（基于保留比例）
        self.base_luwangrequest_gcnn = """请使用data6目录中的以下数据文件进行路网综合可视化：
                            综合前.shp

                            算法要求：
                            使用gcnn算法

                            保留比例为：0.7

                        """

        # 路网综合测试用例4：使用层次算法（按属性字段）
        self.base_luwangrequest_hierarchy_attr = """请使用data6目录中的以下数据文件进行路网综合可视化：
                            综合前.shp

                            算法要求：
                            使用层次算法，按照road_class属性字段进行选取

                            尺度要求：
                            源尺度为1:500，目标尺度为1:20000的自动缩编

                           """

        # 默认使用Stroke算法测试
        self.base_luwangrequest = self.base_diturequest_beijing
        
        self.base_diturequest_1 = """【使用数据说明】
                        使用data1目录中的以下文件：
                        - Guangdong.shp（省界）
                        - Coastal Economic Belt City.shp（沿海经济带）
                        - Core City of the Pearl River Delta.shp（珠三角核心城市）
                        - Provincial Deputy Central City.shp（副中心城市）
                        - Highway.shp（高速公路）

                        【地图设置要求】
                        - 标题：广东省经济区划图
                        - 背景色：浅灰色
                        - 图片大小：(14, 10)
                        - 分辨率：400
                        - 显示图例，位置：右下角
                        - 显示比例尺，不显示指北针

                        【图层样式要求】
                        - Guangdong.shp：根据"地区"属性调整多边形颜色，并根据"地名"属性添加标签
                        - Coastal Economic Belt City.shp：橙色圆点标记，白色边框，标记大小120
                        - Core City of the Pearl River Delta.shp：红色圆点标记，白色边框，标记大小120
                        - Provincial Deputy Central City.shp：绿色圆点标记，白色边框，标记大小120
                        - Highway.shp：黑色线条，线宽1.5，透明度0.7
                        - 添加注记：广东省形成了多层次经济发展格局"""


    def run_test(self, test_name, request):
        """运行单个测试"""
        print(f"\n👤 {test_name}")
        print(f"   请求: {request[:100]}{'...' if len(request) > 100 else ''}")

        try:
            # 使用chat方法进行对话式交互
            response = self.agent.chat(request, self.session_id)

            # 记录会话ID
            if not self.session_id:
                self.session_id = response.get('session_id')
                print(f"   📝 会话已创建：{self.session_id[:8]}...")

            # 检查响应是否成功
            success = response.get('success', False)
            message = response.get('response', '')

            # 打印响应信息
            print(f"   🤖 响应: {message[:150]}{'...' if len(message) > 150 else ''}")

            if response.get('map_info'):
                map_info = response['map_info']
                print(f"   📊 地图信息：版本v{map_info['version']}, 图层数{map_info['layer_count']}")

            # 处理需要确认的操作
            if response.get('requires_confirmation'):
                print(f"   ⚠️ 需要确认操作，自动确认...")
                confirm_response = self.agent.chat("是", self.session_id)
                success = confirm_response.get('success', False)
                message = confirm_response.get('response', '')
                print(f"   🤖 确认后响应: {message[:150]}{'...' if len(message) > 150 else ''}")

            status = "✅" if success else "❌"
            print(f"   {status} 测试结果: {'成功' if success else '失败'}")

            return success, message

        except Exception as e:
            print(f"   ❌ 测试失败: {str(e)}")
            return False, str(e)

    def test_01_create_luwangbase_map(self):
        """测试用例01：创建路网基础地图"""
        # 重置 session_id，开始新的会话
        self.session_id = None
        # 同时重置 Agent 的 session_id
        import uuid
        self.agent.session_id = str(uuid.uuid4())

        success, response = self.run_test("01-创建路网基础地图", self.base_luwangrequest)

        return success

    def test_01_create_ditubase_map(self):
        """测试用例01：创建传统制图基础地图"""
        # 重置 session_id，开始新的会话
        self.session_id = None
        # 同时重置 Agent 的 session_id
        import uuid
        self.agent.session_id = str(uuid.uuid4())

        success, response = self.run_test("01-创建地图基础地图", self.base_diturequest)

        return success


    def test_02_delete_layers(self):
        """测试用例02：删除图层功能"""
        print("\n" + "="*80)
        print("🗑️  测试用例02：删除图层功能测试")
        print("="*80)
        
        # 02-1: 删除Highway图层
        self.run_test("02-1-删除Highway图层", "请删除Highway图层")
        
        # 02-2: 删除Railway图层
        self.run_test("02-2-删除Railway图层", "请删除Railway图层")
        
        # 02-3: 删除Provincial Deputy Central City图层
        self.run_test("02-3-删除Provincial Deputy Central City图层", 
                     "请删除Provincial Deputy Central City图层")
        
    
    def test_03_delete_map_elements(self):
        """测试用例03：删除地图元素功能"""
        print("\n" + "="*80)
        print("🧭 测试用例03：删除地图元素功能测试")
        print("="*80)
        
        # 03-1: 删除指北针
        self.run_test("03-1-删除指北针", "请删除指北针")
        
        # 03-2: 删除比例尺
        self.run_test("03-2-删除比例尺", "请删除比例尺")
        
        # 03-3: 删除所有注记
        self.run_test("03-3-删除所有注记", "请删除所有文字注记")
        
    
    def test_04_add_layers(self):
        """测试用例04：添加图层功能"""
        print("\n" + "="*80)
        print("➕ 测试用例04：添加图层功能测试")
        print("="*80)
        
        # 04-1: 重新添加Highway图层（红色，线宽3）
        self.run_test("04-1-添加Highway图层-红色", 
                     """请使用data1目录中的Highway.shp添加图层，设置样式：
                     - 颜色改为红色
                     - 线宽设为3""")
        
        # 04-2: 重新添加Railway图层（蓝色，点划线）
        self.run_test("04-2-添加Railway图层-蓝色点划线", 
                     """请使用data1目录中的Railway.shp添加图层，设置样式：
                     - 颜色改为蓝色
                     - 线型改为点划线
                     - 线宽设为2.5""")
        
        # 04-3: 添加Coastal Economic Belt City图层（绿色）
        self.run_test("04-3-添加Coastal Economic Belt City图层", 
                     """请使用data1目录中的Coastal Economic Belt City.shp添加图层，设置样式：
                     - 颜色改为绿色
                     - 符号大小适中""")
    
    def test_05_add_map_elements(self):
        """测试用例05：添加地图元素功能"""
        print("\n" + "="*80)
        print("🧭 测试用例05：添加地图元素功能测试")
        print("="*80)
        
        # 05-1: 添加指北针（右上角）
        self.run_test("05-1-添加指北针", "请添加指北针到地图")
        
        # 05-2: 添加比例尺（左下角）
        self.run_test("05-2-添加比例尺", "请添加比例尺到地图")
        
        # # 05-3: 添加GDP发展情况注记
        self.run_test("05-3-添加GDP注记", 
                     """请添加一段中文注记，介绍广东省2023年的GDP发展情况：
                     "广东省2023年GDP总量达13.57万亿元，同比增长4.8%，连续35年居全国首位。其中，珠三角地区贡献超过80%，展现出强劲的经济活力和创新驱动发展成效。"
                     
                     请将注记放置在地图下方中央位置，字体大小12，颜色为深蓝色。""")


    def test_06_modify_styles(self):
        """测试用例06：修改样式功能"""
        print("🎨 测试用例06：修改样式功能测试")
        # 06-1: 修改Highway图层样式（改为黄色，线宽4）
        self.run_test("06-1-修改Highway样式", 
                     """请修改Highway图层的样式：
                     - 颜色改为黄色
                     - 线宽改为4
                     - 线型改为实线""")
        
        # 06-2: 修改Railway图层样式（改为紫色，虚线）
        self.run_test("06-2-修改Railway样式", 
                     """请修改Railway图层的样式：
                     - 颜色改为紫色
                     - 线型改为虚线
                     - 线宽改为3""")
        
        # 06-3: 修改Guangdong图层样式（边框加粗）
        self.run_test("06-3-修改Guangdong样式", 
                     """请修改Guangdong图层的样式：
                     - 边框颜色改为黑色
                     - 边框线宽改为2
                     - 保持原有填充色""")
        
        # 06-4: 修改地图背景色
        self.run_test("06-4-修改背景色", "请将地图背景色改为淡绿色")
        
        # 06-5: 修改地图标题
        self.run_test("06-5-修改标题", "请将地图标题改为'广东省行政区划图（修改版）'")
        
        
    def test_08_annotation_modification(self):
        """测试用例08：注记修改功能"""
        print("\n" + "="*80)
        print("📝 测试用例08：注记修改功能测试")
        print("="*80)
        
        # 08-1: 修改GDP注记内容
        self.run_test("08-1-修改GDP注记", 
                     """请修改GDP发展情况的注记内容为：
                     "广东省2024年经济持续稳健发展，GDP预计突破14万亿元大关，高质量发展成效显著，区域协调发展格局进一步优化。"
                     
                     保持原有位置和样式。""")


    def test_09_complex_operations(self):
        """测试用例09：复合操作测试"""
        print("🔄 测试用例09：复合操作测试")
        # 09-1: 同时修改多个图层样式
        # self.run_test("09-1-批量修改图层样式", 
        #              """请同时进行以下修改：
        #              1. 地图背景色改为浅黄色
        #              2. Railway图层：颜色改为深绿色，线型改为点线
        #              3. Highway图层：颜色改为橙色，线宽改为5""")
    
        self.run_test("09-1-批量删除图层样式",
                     """请同时进行以下修改：
                     删除比例尺和指北针""")
        
        # self.run_test("09-1-批量增加图层样式",
        #              """请同时进行以下修改：
        #              添加比例尺和指北针""")

        # 09-2: 添加多个注记
        # self.run_test("09-2-添加多个注记",
        #              """请添加以下多个注记：
        #              1. 在地图左上角添加："珠三角核心区"，字体12，红色
        #              2. 在地图右上角添加："粤东西北地区"，字体12，蓝色
        #              3. 在地图中央添加："广东省"，字体16，黑色，加粗""")

        # 09-3: 批量修改多个图层样式（不包含背景色）
        # self.run_test("09-3-批量修改多个图层样式",
        #              """请同时修改以下图层的样式：
        #              1. Highway图层：颜色改为紫色，线宽改为4
        #              2. Railway图层：颜色改为橙色，线宽改为3""")

        # 09-4: 混合操作：添加图层 + 修改样式
        # self.run_test("09-4-添加图层并修改样式",
        #              """请添加data1目录中的Coastal Economic Belt City.shp图层，
        #              颜色设为绿色，然后将Highway图层的颜色改为红色""")

        # 09-5: 混合操作：修改标题 + 修改背景色
        # self.run_test("09-5-修改标题和背景色",
        #              """请同时进行以下修改：
        #              1. 将地图标题改为"广东省交通网络图"
        #              2. 将地图背景色改为灰色
        #              3. 将Highway图层的颜色改为红色""")

        # 09-6: 混合操作：删除图层 + 添加比例尺
        # self.run_test("09-6-删除图层并添加比例尺",
        #              """请删除Coastal Economic Belt City图层，
        #              然后删除比例尺和指北针""")

        # # 09-7: 批量修改三个图层样式
        # self.run_test("09-7-批量修改三个图层",
        #              """请同时修改以下图层的样式：
        #              1. Guangdong图层：填充色改为浅绿色，边框颜色改为深绿色
        #              2. Highway图层：颜色改为金色，线宽改为5
        #              3. Railway图层：颜色改为银色，线宽改为4""")

        # # 09-8: 混合操作：修改背景色 + 修改标题 + 修改图层样式
        # self.run_test("09-8-综合修改",
        #              """请同时进行以下修改：
        #              1. 地图背景色改为米色
        #              2. 标题改为"广东省综合交通图"
        #              3. Highway图层颜色改为深蓝色""")

        # # 09-9: 批量操作：修改多个图层的透明度
        # self.run_test("09-9-批量修改透明度",
        #              """请同时修改以下图层的透明度：
        #              1. Highway图层：透明度改为0.1
        #              2. Railway图层：透明度改为0.6""")

        # # 09-10: 混合操作：删除和添加
        # self.run_test("09-10-删除后重新添加",
        #              """请先删除Highway图层，
        #              然后重新添加data1目录中的Highway.shp，颜色设为黑色，线宽设为2""")

    
    def test_10_final_verification(self):
        """测试用例10：最终验证"""
        print("\n" + "="*80)
        print("🔍 测试用例10：最终验证测试")
        print("="*80)
        # 10-1: 获取地图状态信息
        self.run_test("10-1-获取地图状态", "请显示当前地图的所有图层信息和状态")
        
        # 10-2: 最终导出（高分辨率）
        # self.run_test("10-2-最终导出", 
        #              "请将当前地图导出为PNG格式，文件名为'test_10_final_map.png'，分辨率设为300dpi")
        # 10-3: 导出为PDF格式
        # self.run_test("10-3-导出PDF", 
        #              "请将当前地图导出为PDF格式，文件名为'test_10_final_map.pdf'")



    def test_02_modify_algorithm(self):
        """测试用例02：修改算法"""
        print("\n" + "="*80)
        print("🔄 测试用例02：修改算法为Stroke构建算法")
        print("="*80)

        success, response = self.run_test("修改算法为Stroke构建算法",
                     """请改用层次算法重新进行路网综合，
                     其他参数保持不变。""")

        return success

    def test_03_modify_scale(self):
        """测试用例03：修改比例尺"""
        print("\n" + "="*80)
        print("🔄 测试用例03：修改目标比例尺")
        print("="*80)

        success, response = self.run_test("修改目标比例尺",
                     """请将目标比例尺改为1:5000，
                     继续使用Stroke算法。""")

        return success
    
    def test_04_delect_elements(self):
        
        # 05-1: 添加指北针（右上角）
        self.run_test("05-1-删除指北针", "请删除指北针")
        
        # 05-2: 添加比例尺（左下角）
        # self.run_test("05-2-添加比例尺", "请删除比例尺")

    def test_05_add_elements(self):
        
        # 05-1: 添加指北针（右上角）
        self.run_test("05-1-添加指北针", "请添加指北针")
        
        # 05-2: 添加比例尺（左下角）
        self.run_test("05-2-添加比例尺", "请添加比例尺")
        
        
    
    def run_all_tests(self):
        """运行所有测试用例"""
        print(f"开始时间: {self.start_time.strftime('%Y-%m-%d %H:%M:%S')}")
        print("="*80)

        # 运行所有测试用例
        test_methods = [
            self.test_01_create_ditubase_map,
            # self.test_02_modify_algorithm,
            # self.test_03_modify_scale,
            # self.test_04_delect_elements,
            # self.test_05_add_elements

            # self.test_01_create_ditubase_map,
            # self.test_02_delete_layers,
            # self.test_03_delete_map_elements,
            # self.test_04_add_layers,
            # self.test_05_add_map_elements,
            self.test_06_modify_styles,
            # # self.test_07_layer_visibility,
            # self.test_08_annotation_modification,
            # self.test_09_complex_operations,
            # self.test_10_final_verification

        ]

        for test_method in test_methods:
            try:
                test_method()
            except Exception as e:
                print(f"❌ 测试方法 {test_method.__name__} 执行失败: {e}")
                import traceback
                traceback.print_exc()

        # 生成测试报告
        self.generate_report()
        return True

    def generate_report(self):
        """生成测试报告"""
        print("\n" + "="*80)
        print("📊 测试报告")
        print("="*80)

        total_duration = (datetime.now() - self.start_time).total_seconds()

        print(f"会话ID: {self.session_id[:8] if self.session_id else '未创建'}...")
        print(f"总耗时: {total_duration:.2f}秒")
       


def main():
    """主函数"""
    tester = GuangdongMapModificationTester()
    success = tester.run_all_tests()

    if success:
        print("\n🎉 测试完成！")
        return 0
    else:
        print("\n⚠️  测试过程中出现错误")
        return 1


if __name__ == "__main__":
    print("🚀 启动广东省地图修改功能测试")
    try:
        # 运行测试
        sys.exit(main())

    except KeyboardInterrupt:
        print("\n\n⚠️  测试被用户中断")
        sys.exit(1)

    except Exception as e:
        print(f"\n❌ 测试过程中出现错误: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
