"""GIS制图工具基类"""

from abc import ABC, abstractmethod
import time
from typing import Any, Dict, Optional, Type
from pydantic import BaseModel, Field
from langchain_core.tools import BaseTool
from langchain_core.callbacks import CallbackManagerForToolRun

from ..models.schemas import MapState
from ..utils.logger import get_logger
from ..utils.helpers import generate_unique_id
from ..state import get_session_context, record_tool_trace, save_map_state_context


class GISToolInput(BaseModel):
    """GIS工具输入基类"""
    pass


class GISToolOutput(BaseModel):
    """GIS工具输出基类"""
    success: bool = Field(description="操作是否成功")
    message: str = Field(description="操作结果消息")
    data: Optional[Dict[str, Any]] = Field(default=None, description="返回的数据")
    map_state: Optional[MapState] = Field(default=None, description="更新后的地图状态")


class BaseGISTool(BaseTool):
    """GIS制图工具基类

    所有GIS制图工具都应该继承此基类，并实现相应的抽象方法。
    """

    # 内部状态
    _current_map_state: Optional[MapState] = None
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # 动态创建logger，避免pickle问题
        logger = get_logger("GISTool")
        logger.info(f"初始化工具: {self.name}")
    
    @property
    def current_map_state(self) -> Optional[MapState]:
        """获取当前地图状态"""
        return self._current_map_state
    
    @current_map_state.setter
    def current_map_state(self, state: MapState) -> None:
        """设置当前地图状态"""
        self._current_map_state = state
        logger = get_logger("GISTool")
        logger.debug(f"更新地图状态: {state.config.map_id}")
    
    def _run(
        self,
        run_manager: Optional[CallbackManagerForToolRun] = None,
        **kwargs: Any,
    ) -> str:
        """执行工具的主要逻辑"""
        start_time = time.time()
        try:
            logger = get_logger("GISTool")
            logger.info(f"开始执行工具: {self.name}")
            logger.debug(f"输入参数: {kwargs}")

            # 验证输入参数
            validated_input = self.args_schema(**kwargs)

            # 执行具体的工具逻辑
            result = self._execute_tool(validated_input, run_manager)

            logger.info(f"工具执行成功: {self.name}")
            logger.debug(f"输出结果: {result.message}")

            # 更新地图状态
            if result.map_state:
                self.current_map_state = result.map_state
                # 同步状态到所有工具
                self._sync_state_to_all_tools()

            map_state = result.map_state or self._current_map_state
            session_id = kwargs.get("session_id")
            if map_state is not None:
                session_id = map_state.get_session_id()
                save_map_state_context(session_id, map_state)
            context = get_session_context(session_id, create=False)
            record_tool_trace(
                session_id=session_id,
                task_id=getattr(context, "task_id", None),
                tool_name=self.name,
                args=kwargs,
                result_summary={"message": result.message, "data": result.data},
                success=result.success,
                error=None if result.success else result.message,
                duration_ms=int((time.time() - start_time) * 1000),
            )

            return self._format_output(result)

        except Exception as e:
            error_msg = f"工具执行失败 {self.name}: {str(e)}"
            logger = get_logger("GISTool")
            logger.error(error_msg)
            session_id = kwargs.get("session_id")
            if self._current_map_state is not None:
                session_id = self._current_map_state.get_session_id()
            context = get_session_context(session_id, create=False)
            record_tool_trace(
                session_id=session_id,
                task_id=getattr(context, "task_id", None),
                tool_name=self.name,
                args=kwargs,
                result_summary=None,
                success=False,
                error=str(e),
                duration_ms=int((time.time() - start_time) * 1000),
            )
            
            error_result = GISToolOutput(
                success=False,
                message=error_msg,
                data={"error": str(e)}
            )
            return self._format_output(error_result)
    
    @abstractmethod
    def _execute_tool(
        self,
        input_data: GISToolInput,
        run_manager: Optional[CallbackManagerForToolRun] = None,
    ) -> GISToolOutput:
        """执行具体的工具逻辑
        
        Args:
            input_data: 验证后的输入数据
            run_manager: 回调管理器
            
        Returns:
            GISToolOutput: 工具执行结果
        """
        pass
    
    def _format_output(self, result: GISToolOutput) -> str:
        """格式化输出结果为字符串"""
        if result.success:
            output = f"✅ {result.message}"
            if result.data:
                output += f"\n📊 数据: {result.data}"
        else:
            output = f"❌ {result.message}"
            if result.data and "error" in result.data:
                output += f"\n🔍 错误详情: {result.data['error']}"
        
        return output
    
    def _generate_id(self) -> str:
        """生成唯一ID"""
        return generate_unique_id()
    
    def _validate_map_state(self) -> bool:
        """验证当前地图状态是否有效"""
        return self._current_map_state is not None
    
    def _get_map_state_or_create(self) -> MapState:
        """获取地图状态，如果不存在则创建默认状态"""
        if self._current_map_state is None:
            from ..models.schemas import MapConfig
            
            default_config = MapConfig(
                map_id=self._generate_id(),
                extent=[-180, -90, 180, 90],  # 全球范围
            )
            self._current_map_state = MapState(config=default_config)
            logger = get_logger("GISTool")
            logger.info("创建默认地图状态")
        
        return self._current_map_state

    def _sync_state_to_all_tools(self):
        """同步地图状态到所有工具"""
        if hasattr(self, '_tool_registry') and self._current_map_state:
            for tool in self._tool_registry:
                if hasattr(tool, '_current_map_state'):
                    tool._current_map_state = self._current_map_state
