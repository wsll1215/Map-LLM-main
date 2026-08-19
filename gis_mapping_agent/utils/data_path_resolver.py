"""数据路径解析工具

这个模块提供了智能的数据路径解析功能，能够：
1. 从用户输入中提取数据目录信息
2. 与基础数据路径进行拼接
3. 验证路径的有效性
"""

import re
from pathlib import Path
from typing import Optional, List, Tuple
from .config import Config
from .logger import get_logger


class DataPathResolver:
    """数据路径解析器"""

    def __init__(self):
        self.logger = get_logger("DataPathResolver")
        # 确保base_path是绝对路径
        base_path = Config.DATA_DIRECTORY_BASE
        if not base_path.is_absolute():
            # 如果是相对路径，相对于PROJECT_ROOT解析
            self.base_path = (Config.PROJECT_ROOT / base_path).resolve()
        else:
            self.base_path = base_path.resolve()
        # self.logger.debug(f"数据基础路径: {self.base_path}")
        
    def parse_data_directory_from_request(self, user_request: str) -> Optional[str]:
        """从用户请求中解析数据目录

        Args:
            user_request: 用户的自然语言请求

        Returns:
            str: 解析出的数据目录名称，如 "data1", "data2" 等
        """
        # 常见的数据目录模式
        patterns = [
            r"使用\s*data(\d+)\s*中的数据",
            r"data(\d+)\s*目录",
            r"data(\d+)\s*文件夹",
            r"从\s*data(\d+)",
            r"data(\d+)/",
            r"data(\d+)\\",
        ]

        for pattern in patterns:
            match = re.search(pattern, user_request, re.IGNORECASE)
            if match:
                data_dir = f"data{match.group(1)}"
                self.logger.info(f"🔍 从用户请求中解析到数据目录")
                return data_dir

        # 检查是否有其他数据目录模式
        general_patterns = [
            r"使用\s*([a-zA-Z0-9_-]+)\s*中的数据",
            r"([a-zA-Z0-9_-]+)\s*目录中的",
            r"从\s*([a-zA-Z0-9_-]+)\s*目录",
        ]

        for pattern in general_patterns:
            match = re.search(pattern, user_request, re.IGNORECASE)
            if match:
                data_dir = match.group(1)
                # 验证是否是合理的目录名
                if self._is_valid_directory_name(data_dir):
                    self.logger.info(f"🔍 从用户请求中解析到数据目录")
                    return data_dir

        # 如果没有找到明确的数据目录指定，检查是否是广东数据相关的请求
        # 广东数据的特征文件名（data1目录中的文件）
        guangdong_files = [
            "Guangdong", "guangdong", "广东",
            "Core City of the Pearl River Delta", "珠三角"
        ]

        # 检查请求中是否包含广东数据相关的文件名
        for keyword in guangdong_files:
            if keyword in user_request:
                self.logger.info(f"🔍 检测到广东数据相关请求，默认使用data1目录")
                return "data1"

        self.logger.debug("未从用户请求中找到明确的数据目录指定")
        return None
    
    def resolve_data_path(self, data_directory: Optional[str] = None) -> Path:
        """解析最终的数据路径
        
        Args:
            data_directory: 数据子目录名称（如 "data1"）
            
        Returns:
            Path: 解析后的完整数据路径
        """
        if data_directory:
            final_path = self.base_path / data_directory
        else:
            final_path = self.base_path
            
        self.logger.debug(f"解析数据路径: {data_directory} -> {final_path}")
        return final_path
    
    def list_available_data_directories(self) -> List[str]:
        """列出可用的数据目录
        
        Returns:
            List[str]: 可用的数据目录名称列表
        """
        if not self.base_path.exists():
            self.logger.warning(f"基础数据路径不存在: {self.base_path}")
            return []
        
        data_dirs = []
        for item in self.base_path.iterdir():
            if item.is_dir() and item.name.startswith('data'):
                data_dirs.append(item.name)
        
        data_dirs.sort()
        self.logger.debug(f"找到可用数据目录: {data_dirs}")
        return data_dirs
    
    def validate_data_path(self, data_path: Path) -> bool:
        """验证数据路径是否有效
        
        Args:
            data_path: 要验证的数据路径
            
        Returns:
            bool: 路径是否有效
        """
        if not data_path.exists():
            self.logger.warning(f"数据路径不存在: {data_path}")
            return False
        
        if not data_path.is_dir():
            self.logger.warning(f"数据路径不是目录: {data_path}")
            return False
        
        # 检查是否包含shapefile文件
        shp_files = list(data_path.glob("*.shp"))
        if not shp_files:
            self.logger.warning(f"数据目录中没有找到shapefile文件: {data_path}")
            return False
        
        self.logger.debug(f"数据路径验证通过: {data_path} (包含 {len(shp_files)} 个shapefile)")
        return True
    
    def find_data_files_in_request(self, user_request: str) -> List[str]:
        """从用户请求中提取数据文件名
        
        Args:
            user_request: 用户请求
            
        Returns:
            List[str]: 提取到的文件名列表
        """
                # 匹配 .shp 文件，同时排除后面带冒号的样式定义
        # 例如，匹配 "Guangdong.shp" 但不匹配 "- Guangdong.shp：..."
        shp_pattern = r'\b([a-zA-Z0-9_\s-]+\.shp)(?!\s*[:：])\b'
        matches = re.findall(shp_pattern, user_request, re.IGNORECASE)
        
        # 清理文件名
        files = []
        for match in matches:
            filename = match.strip()
            if filename not in files:
                files.append(filename)
        
        if files:
            self.logger.info(f"🔍 从用户请求中提取到数据文件")
        
        return files
    
    def _is_valid_directory_name(self, name: str) -> bool:
        """检查是否是有效的目录名
        
        Args:
            name: 目录名称
            
        Returns:
            bool: 是否有效
        """
        # 基本的目录名验证
        if not name or len(name) > 50:
            return False
        
        # 检查是否包含非法字符
        invalid_chars = ['<', '>', ':', '"', '|', '?', '*']
        if any(char in name for char in invalid_chars):
            return False
        
        # 检查是否是常见的数据目录模式
        data_patterns = [
            r'^data\d+$',           # data1, data2, etc.
            r'^[a-zA-Z0-9_-]+$',    # 一般的目录名
        ]
        
        return any(re.match(pattern, name) for pattern in data_patterns)


# 全局实例
data_path_resolver = DataPathResolver()


def parse_data_directory_from_request(user_request: str) -> Optional[str]:
    """从用户请求中解析数据目录（便捷函数）
    
    Args:
        user_request: 用户请求
        
    Returns:
        str: 数据目录名称或None
    """
    return data_path_resolver.parse_data_directory_from_request(user_request)


def resolve_data_path(data_directory: Optional[str] = None) -> Path:
    """解析数据路径（便捷函数）
    
    Args:
        data_directory: 数据子目录名称
        
    Returns:
        Path: 完整的数据路径
    """
    return data_path_resolver.resolve_data_path(data_directory)


def extract_data_info_from_request(user_request: str) -> Tuple[Optional[str], List[str]]:
    """从用户请求中提取数据目录和文件信息
    
    Args:
        user_request: 用户请求
        
    Returns:
        Tuple[Optional[str], List[str]]: (数据目录, 数据文件列表)
    """
    data_dir = data_path_resolver.parse_data_directory_from_request(user_request)
    data_files = data_path_resolver.find_data_files_in_request(user_request)
    
    return data_dir, data_files
