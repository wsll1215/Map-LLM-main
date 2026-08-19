"""对话式制图工具 - 支持多轮对话和增量修改的工具集"""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from langchain_core.callbacks import CallbackManagerForToolRun

from .base import BaseGISTool, GISToolOutput
from ..models.schemas import MapState, ModificationRecord
from ..state import get_state_manager
from ..adjustment import get_modification_engine
from ..rendering.renderer import get_map_renderer
from ..utils.logger import get_logger


class LoadMapStateInput(BaseModel):
    """加载地图状态工具输入"""
    session_id: str = Field(description="会话ID")
    version: Optional[int] = Field(default=None, description="版本号，不指定则加载最新版本")


class LoadMapStateTool(BaseGISTool):
    """加载地图状态工具"""
    
    name: str = "load_map_state"
    description: str = "加载指定会话和版本的地图状态，用于恢复之前的制图会话"
    args_schema: type = LoadMapStateInput
    
    def _execute_tool(
        self,
        input_data: LoadMapStateInput,
        run_manager: Optional[CallbackManagerForToolRun] = None,
    ) -> GISToolOutput:
        """执行加载地图状态"""
        try:
            state_manager = get_state_manager()
            map_state = state_manager.load_state(input_data.session_id, input_data.version)
            
            if map_state is None:
                return GISToolOutput(
                    success=False,
                    message=f"未找到会话 {input_data.session_id} 的状态",
                    data={}
                )
            
            # 更新当前地图状态
            self._current_map_state = map_state
            
            return GISToolOutput(
                success=True,
                message=f"成功加载会话 {input_data.session_id} 版本 {map_state.get_current_version()} 的状态",
                data={
                    "session_id": map_state.get_session_id(),
                    "version": map_state.get_current_version(),
                    "layer_count": len(map_state.layers),
                    "last_modified": map_state.updated_at
                }
            )
            
        except Exception as e:
            return GISToolOutput(
                success=False,
                message=f"加载地图状态失败: {str(e)}",
                data={}
            )


class SaveMapStateInput(BaseModel):
    """保存地图状态工具输入"""
    session_name: Optional[str] = Field(default=None, description="会话名称（可选）")


class SaveMapStateTool(BaseGISTool):
    """保存地图状态工具"""
    
    name: str = "save_map_state"
    description: str = "保存当前地图状态，支持版本管理"
    args_schema: type = SaveMapStateInput
    
    def _execute_tool(
        self,
        input_data: SaveMapStateInput,
        run_manager: Optional[CallbackManagerForToolRun] = None,
    ) -> GISToolOutput:
        """执行保存地图状态"""
        try:
            if self._current_map_state is None:
                return GISToolOutput(
                    success=False,
                    message="没有可保存的地图状态",
                    data={}
                )
            
            # 更新会话名称
            if input_data.session_name:
                self._current_map_state.session_info.session_name = input_data.session_name
            
            state_manager = get_state_manager()
            success = state_manager.save_state(self._current_map_state)
            
            if success:
                return GISToolOutput(
                    success=True,
                    message=f"地图状态保存成功，会话ID: {self._current_map_state.get_session_id()}",
                    data={
                        "session_id": self._current_map_state.get_session_id(),
                        "version": self._current_map_state.get_current_version()
                    }
                )
            else:
                return GISToolOutput(
                    success=False,
                    message="地图状态保存失败",
                    data={}
                )
                
        except Exception as e:
            return GISToolOutput(
                success=False,
                message=f"保存地图状态失败: {str(e)}",
                data={}
            )


class ApplyModificationInput(BaseModel):
    """应用修改工具输入"""
    modification_request: str = Field(description="用户的修改请求描述")
    auto_save: bool = Field(default=True, description="是否自动保存修改后的状态")
    auto_render: bool = Field(default=True, description="是否自动渲染修改后的地图")


class ApplyModificationTool(BaseGISTool):
    """应用修改工具"""
    
    name: str = "apply_modification"
    description: str = "根据用户的自然语言描述对当前地图进行增量修改"
    args_schema: type = ApplyModificationInput
    
    def _execute_tool(
        self,
        input_data: ApplyModificationInput,
        run_manager: Optional[CallbackManagerForToolRun] = None,
    ) -> GISToolOutput:
        """执行修改应用"""
        try:
            if self._current_map_state is None:
                return GISToolOutput(
                    success=False,
                    message="没有可修改的地图状态，请先创建或加载地图",
                    data={}
                )
            
            modification_engine = get_modification_engine()
            
            # 分析修改请求
            analysis = modification_engine.analyze_modification_request(
                input_data.modification_request, 
                self._current_map_state
            )
            
            # 检查是否需要确认
            if analysis.requires_confirmation:
                return GISToolOutput(
                    success=False,
                    message=f"此操作需要确认: {analysis.intent}。请确认是否继续？",
                    data={
                        "requires_confirmation": True,
                        "analysis": analysis.model_dump()
                    }
                )
            
            # 检查是否需要澄清
            if analysis.clarification_questions:
                return GISToolOutput(
                    success=False,
                    message=f"需要澄清以下信息: {', '.join(analysis.clarification_questions)}",
                    data={
                        "requires_clarification": True,
                        "analysis": analysis.model_dump()
                    }
                )
            
            # 生成标准修改补丁
            patch = modification_engine.generate_modification_plan(analysis)
            
            if not patch.operations:
                return GISToolOutput(
                    success=False,
                    message="无法理解修改请求，请提供更具体的描述",
                    data={"analysis": analysis.model_dump()}
                )

            state_manager = get_state_manager() if input_data.auto_save else None
            if state_manager:
                state_manager.save_state(self._current_map_state)
            before_state = self._current_map_state

            # 应用修改
            result = modification_engine.apply_modifications(
                before_state,
                patch,
                input_data.modification_request
            )
            new_state, records = result
            
            # 更新当前状态
            self._current_map_state = new_state
            
            result_data = {
                "session_id": new_state.get_session_id(),
                "new_version": new_state.get_current_version(),
                "modifications_applied": len(records),
                "modification_summary": [record.description for record in records],
                "patch": result.patch.model_dump() if result.patch else None,
                "diff": result.diff,
            }
            
            # 自动保存
            if state_manager:
                state_manager.save_state(new_state)
                result_data["saved"] = True
            
            # 自动渲染
            if input_data.auto_render:
                renderer = get_map_renderer()
                render_result = renderer.render_map(new_state)
                result_data["rendered"] = render_result.get("success", False)
                result_data["render_file"] = render_result.get("file_path")
                result.diff = modification_engine.diff_states(before_state, new_state)
                result_data["diff"] = result.diff
                if state_manager:
                    state_manager.save_state(new_state)
            
            return GISToolOutput(
                success=True,
                message=f"修改应用成功，共执行 {len(records)} 个修改操作",
                data=result_data
            )
            
        except Exception as e:
            return GISToolOutput(
                success=False,
                message=f"应用修改失败: {str(e)}",
                data={}
            )


class UndoModificationInput(BaseModel):
    """撤销修改工具输入"""
    steps: int = Field(default=1, description="撤销的步数，默认撤销最后一步")


class UndoModificationTool(BaseGISTool):
    """撤销修改工具"""
    
    name: str = "undo_modification"
    description: str = "撤销最近的修改操作，回退到之前的版本"
    args_schema: type = UndoModificationInput
    
    def _execute_tool(
        self,
        input_data: UndoModificationInput,
        run_manager: Optional[CallbackManagerForToolRun] = None,
    ) -> GISToolOutput:
        """执行撤销修改"""
        try:
            if self._current_map_state is None:
                return GISToolOutput(
                    success=False,
                    message="没有可撤销的地图状态",
                    data={}
                )
            
            state_manager = get_state_manager()
            previous_state = self._current_map_state
            for _ in range(max(1, input_data.steps)):
                rolled_back = state_manager.rollback_to_previous(previous_state.get_session_id())
                if rolled_back is None:
                    break
                previous_state = rolled_back
            
            if previous_state.get_current_version() == self._current_map_state.get_current_version():
                return GISToolOutput(
                    success=False,
                    message="已经是最早版本，无法撤销",
                    data={}
                )
            
            # 更新当前状态
            self._current_map_state = previous_state
            render_result = get_map_renderer().render_map(previous_state)
            
            return GISToolOutput(
                success=True,
                message=f"成功撤销到版本 {previous_state.get_current_version()}",
                data={
                    "session_id": previous_state.get_session_id(),
                    "current_version": previous_state.get_current_version(),
                    "rendered": render_result.get("success", False),
                    "render_file": render_result.get("file_path")
                }
            )
            
        except Exception as e:
            return GISToolOutput(
                success=False,
                message=f"撤销修改失败: {str(e)}",
                data={}
            )


class RenderMapInput(BaseModel):
    """渲染地图工具输入"""
    custom_filename: Optional[str] = Field(default=None, description="自定义文件名")
    save_file: bool = Field(default=True, description="是否保存文件")


class RenderMapTool(BaseGISTool):
    """渲染地图工具"""
    
    name: str = "render_map"
    description: str = "渲染当前地图状态并保存为图片文件"
    args_schema: type = RenderMapInput
    
    def _execute_tool(
        self,
        input_data: RenderMapInput,
        run_manager: Optional[CallbackManagerForToolRun] = None,
    ) -> GISToolOutput:
        """执行地图渲染"""
        try:
            if self._current_map_state is None:
                return GISToolOutput(
                    success=False,
                    message="没有可渲染的地图状态",
                    data={}
                )
            
            renderer = get_map_renderer()
            result = renderer.render_map(
                self._current_map_state,
                save_file=input_data.save_file,
                custom_filename=input_data.custom_filename
            )
            
            if result["success"]:
                return GISToolOutput(
                    success=True,
                    message=result["message"],
                    data={
                        "file_path": result.get("file_path"),
                        "session_id": result["session_id"],
                        "version": result["version"]
                    }
                )
            else:
                return GISToolOutput(
                    success=False,
                    message=result.get("message", "渲染失败"),
                    data={}
                )
                
        except Exception as e:
            return GISToolOutput(
                success=False,
                message=f"渲染地图失败: {str(e)}",
                data={}
            )


# 对话工具列表
CONVERSATION_TOOLS = [
    LoadMapStateTool(),
    SaveMapStateTool(),
    ApplyModificationTool(),
    UndoModificationTool(),
    RenderMapTool(),
]
