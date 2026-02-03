"""
PerfX Platform API Client
"""
import logging
from typing import Any, Dict, Optional

import httpx

from .models import TestRunDetail

logger = logging.getLogger(__name__)


class PerfXClientError(Exception):
    """PerfX Client 错误基类"""
    pass


class PerfXNotFoundError(PerfXClientError):
    """资源不存在错误"""
    pass


class PerfXValidationError(PerfXClientError):
    """验证错误"""
    pass


class PerfXClient:
    """
    PerfX 平台 API 客户端
    
    用于与性能测试平台交互，获取测试运行信息和更新状态。
    """

    def __init__(
        self,
        base_url: str = "http://localhost:8000",
        timeout: float = 30.0,
    ):
        """
        初始化客户端
        
        Args:
            base_url: 平台 API 基础地址
            timeout: 请求超时时间
        """
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._client = httpx.Client(
            base_url=self.base_url,
            timeout=timeout,
            headers={"Content-Type": "application/json"},
        )

    def close(self):
        """关闭客户端"""
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def _handle_response(self, response: httpx.Response) -> Dict[str, Any]:
        """处理响应"""
        if response.status_code == 404:
            data = response.json()
            raise PerfXNotFoundError(data.get("message", "资源不存在"))
        
        if response.status_code >= 400:
            try:
                data = response.json()
                message = data.get("message", response.text)
            except Exception:
                message = response.text
            raise PerfXClientError(f"API 请求失败: {response.status_code} - {message}")
        
        data = response.json()
        # 假设 API 返回格式为 {"code": 0, "data": {...}, "message": "..."}
        if data.get("code") != 0:
            raise PerfXClientError(data.get("message", "未知错误"))
        
        return data.get("data", {})

    def get_test_run_detail(self, run_id: str) -> TestRunDetail:
        """
        获取测试运行详情
        
        Args:
            run_id: 运行ID
            
        Returns:
            TestRunDetail 对象
        """
        logger.debug("[PerfXClient] 获取测试运行详情: %s", run_id)
        response = self._client.get(f"/api/perf/runs/{run_id}")
        data = self._handle_response(response)
        return TestRunDetail(**data)

    def start_test_run(
        self,
        run_id: str,
        arguments: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """
        开始测试运行
        
        Args:
            run_id: 运行ID
            arguments: 运行参数（可选）
            
        Returns:
            更新后的测试运行信息
        """
        logger.info("[PerfXClient] 开始测试运行: %s", run_id)
        payload = {}
        if arguments:
            payload["arguments"] = arguments
        
        response = self._client.post(
            f"/api/perf/runs/{run_id}/start",
            json=payload if payload else None,
        )
        return self._handle_response(response)

    def complete_test_run(
        self,
        run_id: str,
        duration_seconds: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        完成测试运行
        
        Args:
            run_id: 运行ID
            duration_seconds: 持续时间（可选）
            
        Returns:
            更新后的测试运行信息
        """
        logger.info("[PerfXClient] 完成测试运行: %s", run_id)
        payload = {}
        if duration_seconds is not None:
            payload["duration_seconds"] = duration_seconds
        
        response = self._client.post(
            f"/api/perf/runs/{run_id}/complete",
            json=payload if payload else None,
        )
        return self._handle_response(response)

    def fail_test_run(
        self,
        run_id: str,
        error_message: str,
    ) -> Dict[str, Any]:
        """
        标记测试运行失败
        
        Args:
            run_id: 运行ID
            error_message: 错误信息
            
        Returns:
            更新后的测试运行信息
        """
        logger.warning("[PerfXClient] 标记测试运行失败: %s, error: %s", run_id, error_message)
        response = self._client.post(
            f"/api/perf/runs/{run_id}/fail",
            json={"error_message": error_message},
        )
        return self._handle_response(response)

    def cancel_test_run(self, run_id: str) -> Dict[str, Any]:
        """
        取消测试运行
        
        Args:
            run_id: 运行ID
            
        Returns:
            更新后的测试运行信息
        """
        logger.info("[PerfXClient] 取消测试运行: %s", run_id)
        response = self._client.post(f"/api/perf/runs/{run_id}/cancel")
        return self._handle_response(response)

    # 别名方法，方便使用
    def get_test_run(self, run_id: str) -> TestRunDetail:
        """获取测试运行详情（get_test_run_detail 的别名）"""
        return self.get_test_run_detail(run_id)
