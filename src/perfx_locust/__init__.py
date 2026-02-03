"""
PerfX Locust - 性能测试平台 Locust 集成工具

提供与性能测试平台的无缝集成，包括：
- 自动同步测试状态
- 从平台获取配置
- 参数验证
- InfluxDB 数据上报
"""

__version__ = "0.1.0"

from .client import PerfXClient
from .influxdb_reporter import InfluxDBReporter
from .models import (
    ArgumentParameter,
    TestRunDetail,
    ValidationError,
    ValidationResult,
)
from .runner import PerfXRunner
from .validator import ArgumentValidator

__all__ = [
    "PerfXClient",
    "PerfXRunner",
    "InfluxDBReporter",
    "ArgumentValidator",
    "TestRunDetail",
    "ArgumentParameter",
    "ValidationResult",
    "ValidationError",
]