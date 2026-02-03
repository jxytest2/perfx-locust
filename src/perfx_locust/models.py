"""
Data models for perfx-locust
"""
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class ArgumentParameter(BaseModel):
    """参数定义模型"""
    name: str = Field(..., description="参数名")
    type: Literal["string", "int", "float", "bool", "choice"] = Field(
        default="string",
        description="参数类型"
    )
    required: bool = Field(default=False, description="是否必填")
    default: Optional[str] = Field(default=None, description="默认值")
    description: Optional[str] = Field(default=None, description="参数描述")
    choices: Optional[List[str]] = Field(default=None, description="可选值列表")


class ArgumentSchema(BaseModel):
    """参数架构模型"""
    parameters: List[ArgumentParameter] = Field(
        default_factory=list,
        description="参数列表"
    )


class EndpointInfo(BaseModel):
    """接口信息"""
    endpoint_id: str
    endpoint_path: str
    method: str
    argument_schema: Optional[Dict[str, Any]] = None

    def get_parameters(self) -> List[ArgumentParameter]:
        """获取参数定义列表"""
        if not self.argument_schema:
            return []
        
        params_data = self.argument_schema.get("parameters", [])
        return [ArgumentParameter(**p) for p in params_data]


class EnvironmentInfo(BaseModel):
    """环境信息"""
    env_id: int
    env_code: str
    env_name: str
    gpu_model: Optional[str] = None
    host: Optional[str] = None


class ShapeStep(BaseModel):
    """负载曲线步骤"""
    duration: int = Field(..., description="持续时间(秒)")
    users: int = Field(..., description="用户数")
    spawn_rate: float = Field(..., description="用户生成速率")


class TestRunDetail(BaseModel):
    """测试运行详情 - 与后端 TestRunDetailResponse 对齐"""
    run_id: str
    endpoint_id: Optional[str] = None
    endpoint: Optional[EndpointInfo] = None
    environment: Optional[EnvironmentInfo] = None
    users: Optional[int] = None
    spawn_rate: Optional[float] = None
    run_time: Optional[str] = None
    shape: Optional[List[Dict[str, Any]]] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    duration_seconds: Optional[int] = None
    status: str = "pending"
    error_message: Optional[str] = None
    tags: Optional[List[str]] = None
    notes: Optional[str] = None
    arguments: Optional[Dict[str, str]] = None
    created_at: Optional[datetime] = None

    def get_host(self) -> Optional[str]:
        """获取测试目标 host"""
        if self.environment and self.environment.host:
            return self.environment.host
        return None

    def get_argument_parameters(self) -> List[ArgumentParameter]:
        """获取参数定义列表（从 endpoint 中获取）"""
        if self.endpoint:
            return self.endpoint.get_parameters()
        return []

    def get_required_parameters(self) -> List[ArgumentParameter]:
        """获取必填参数列表"""
        return [p for p in self.get_argument_parameters() if p.required]

    def get_shape_steps(self) -> Optional[List[ShapeStep]]:
        """获取负载曲线步骤"""
        if not self.shape:
            return None
        return [ShapeStep(**step) for step in self.shape]


class ValidationError(BaseModel):
    """参数验证错误"""
    parameter: str
    message: str


class ValidationResult(BaseModel):
    """参数验证结果"""
    valid: bool
    errors: List[ValidationError] = Field(default_factory=list)
    resolved_arguments: Dict[str, str] = Field(default_factory=dict)
