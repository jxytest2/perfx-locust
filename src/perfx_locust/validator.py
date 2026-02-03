"""
Argument Validator for perfx-locust
"""
import logging
from typing import Any, Dict, List

from .models import (
    ArgumentParameter,
    TestRunDetail,
    ValidationError,
    ValidationResult,
)

logger = logging.getLogger(__name__)


class ArgumentValidator:
    """
    参数验证器
    
    根据 Endpoint 的 argument_schema 验证命令行传入的参数。
    """

    def __init__(self, test_run: TestRunDetail):
        """
        初始化验证器
        
        Args:
            test_run: 测试运行详情
        """
        self.test_run = test_run
        self.parameters = test_run.get_argument_parameters()

    def _normalize_key(self, key: str) -> str:
        """将参数名标准化（连字符转下划线）"""
        return key.replace("-", "_")

    def _get_param_value(self, provided_args: Dict[str, Any], param_name: str) -> Any:
        """
        从提供的参数中获取值，支持连字符和下划线两种格式

        Args:
            provided_args: 用户提供的参数字典
            param_name: 参数名（可能带连字符）

        Returns:
            参数值，如果不存在返回 None
        """
        # 先尝试原始名称
        if param_name in provided_args:
            return provided_args[param_name]

        # 尝试下划线格式
        underscore_name = self._normalize_key(param_name)
        if underscore_name in provided_args:
            return provided_args[underscore_name]

        return None

    def validate(self, provided_args: Dict[str, Any]) -> ValidationResult:
        """
        验证参数

        Args:
            provided_args: 用户提供的参数字典

        Returns:
            ValidationResult 验证结果
        """
        errors: List[ValidationError] = []
        resolved: Dict[str, str] = {}

        for param in self.parameters:
            value = self._get_param_value(provided_args, param.name)

            # 检查必填参数
            if param.required and value is None:
                if param.default is not None:
                    # 使用默认值
                    resolved[param.name] = param.default
                    logger.debug(
                        "[Validator] 参数 %s 使用默认值: %s",
                        param.name, param.default
                    )
                else:
                    errors.append(ValidationError(
                        parameter=param.name,
                        message=f"参数 '{param.name}' 是必填的"
                    ))
                continue

            if value is None:
                # 非必填参数，使用默认值或跳过
                if param.default is not None:
                    resolved[param.name] = param.default
                continue

            # 类型验证
            validated_value = self._validate_type(param, value)
            if validated_value is None:
                errors.append(ValidationError(
                    parameter=param.name,
                    message=f"参数 '{param.name}' 类型错误，期望 {param.type}"
                ))
                continue

            # 选项验证
            if param.type == "choice" and param.choices:
                if validated_value not in param.choices:
                    errors.append(ValidationError(
                        parameter=param.name,
                        message=f"参数 '{param.name}' 的值必须是以下之一: {param.choices}"
                    ))
                    continue

            resolved[param.name] = validated_value

        return ValidationResult(
            valid=len(errors) == 0,
            errors=errors,
            resolved_arguments=resolved,
        )

    def _validate_type(self, param: ArgumentParameter, value: Any) -> str | None:
        """
        验证并转换参数类型
        
        Args:
            param: 参数定义
            value: 参数值
            
        Returns:
            转换后的字符串值，如果类型错误返回 None
        """
        try:
            if param.type == "string" or param.type == "choice":
                return str(value)
            elif param.type == "int":
                # 验证是整数
                int(value)
                return str(value)
            elif param.type == "float":
                # 验证是浮点数
                float(value)
                return str(value)
            elif param.type == "bool":
                # 接受 true/false/1/0
                if isinstance(value, bool):
                    return str(value).lower()
                if str(value).lower() in ("true", "1", "yes"):
                    return "true"
                if str(value).lower() in ("false", "0", "no"):
                    return "false"
                return None
            else:
                return str(value)
        except (ValueError, TypeError):
            return None

    def get_required_parameter_names(self) -> List[str]:
        """获取必填参数名列表"""
        return [p.name for p in self.parameters if p.required]

    def get_all_parameter_names(self) -> List[str]:
        """获取所有参数名列表"""
        return [p.name for p in self.parameters]

    def format_help(self) -> str:
        """格式化参数帮助信息"""
        if not self.parameters:
            return "此接口没有定义额外参数"

        lines = ["接口参数说明:", ""]
        for param in self.parameters:
            required_str = "[必填]" if param.required else "[可选]"
            default_str = f" (默认: {param.default})" if param.default else ""
            choices_str = f" 可选值: {param.choices}" if param.choices else ""
            desc = param.description or ""
            
            lines.append(
                f"  --{param.name:<20} {required_str} {desc}{default_str}{choices_str}"
            )

        return "\n".join(lines)
