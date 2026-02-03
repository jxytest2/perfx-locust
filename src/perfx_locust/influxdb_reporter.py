"""
InfluxDB Reporter for perfx-locust

实时上报 Locust 性能数据到 InfluxDB。
"""
import logging
import time
from datetime import datetime
from typing import Any, Dict, Optional

from influxdb_client import InfluxDBClient, Point, WritePrecision
from influxdb_client.client.write_api import SYNCHRONOUS

logger = logging.getLogger(__name__)


class InfluxDBReporter:
    """
    InfluxDB 数据上报器
    
    监听 Locust 事件，实时将性能数据写入 InfluxDB。
    """

    def __init__(
        self,
        url: str,
        token: str,
        org: str,
        bucket: str,
        run_id: str,
        endpoint_id: Optional[str] = None,
        endpoint_path: Optional[str] = None,
        env_code: Optional[str] = None,
        gpu_model: Optional[str] = None,
        extra_tags: Optional[Dict[str, str]] = None,
    ):
        """
        初始化上报器

        Args:
            url: InfluxDB URL
            token: InfluxDB Token
            org: InfluxDB Organization
            bucket: InfluxDB Bucket
            run_id: 测试运行 ID
            endpoint_id: 接口 ID
            endpoint_path: 接口路径 (用于筛选)
            env_code: 环境编码
            gpu_model: GPU 型号 (用于筛选)
            extra_tags: 额外的标签 (如命令行参数)
        """
        self.url = url
        self.token = token
        self.org = org
        self.bucket = bucket
        self.run_id = run_id
        self.endpoint_id = endpoint_id
        self.endpoint_path = endpoint_path
        self.env_code = env_code
        self.gpu_model = gpu_model
        self.extra_tags = extra_tags or {}
        
        self._client: Optional[InfluxDBClient] = None
        self._write_api = None
        self._enabled = False

    def connect(self) -> bool:
        """
        连接 InfluxDB
        
        Returns:
            是否连接成功
        """
        if not self.url or not self.token:
            logger.info("[InfluxDB] 未配置 InfluxDB，跳过数据上报")
            return False

        try:
            self._client = InfluxDBClient(
                url=self.url,
                token=self.token,
                org=self.org,
            )
            # 测试连接
            self._client.ping()
            self._write_api = self._client.write_api(write_options=SYNCHRONOUS)
            self._enabled = True
            logger.info("[InfluxDB] 连接成功: %s", self.url)
            return True
        except Exception as e:
            logger.error("[InfluxDB] 连接失败: %s", e)
            self._enabled = False
            return False

    def close(self):
        """关闭连接"""
        if self._client:
            self._client.close()
            self._client = None
            self._write_api = None
            self._enabled = False
            logger.info("[InfluxDB] 连接已关闭")

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def _build_base_tags(self) -> Dict[str, str]:
        """构建基础标签"""
        tags = {"run_id": self.run_id}
        if self.endpoint_id:
            tags["endpoint_id"] = self.endpoint_id
        if self.endpoint_path:
            tags["endpoint_path"] = self.endpoint_path
        if self.env_code:
            tags["env_code"] = self.env_code
        if self.gpu_model:
            tags["gpu_model"] = self.gpu_model
        tags.update(self.extra_tags)
        return tags

    def write_request(
        self,
        request_type: str,
        name: str,
        response_time: float,
        response_length: int,
        success: bool,
        exception: Optional[str] = None,
    ):
        """
        写入请求数据
        
        Args:
            request_type: 请求类型 (GET/POST/...)
            name: 请求名称/路径
            response_time: 响应时间 (ms)
            response_length: 响应长度 (bytes)
            success: 是否成功
            exception: 异常信息
        """
        if not self._enabled:
            return

        try:
            tags = self._build_base_tags()
            tags["request_type"] = request_type
            tags["name"] = name
            tags["success"] = str(success).lower()

            point = (
                Point("locust_request")
                .time(datetime.utcnow(), WritePrecision.MS)
            )
            
            for tag_key, tag_value in tags.items():
                point = point.tag(tag_key, tag_value)
            
            point = (
                point
                .field("response_time", response_time)
                .field("response_length", response_length)
                .field("success_count", 1 if success else 0)
                .field("failure_count", 0 if success else 1)
            )
            
            if exception:
                point = point.field("exception", exception[:500])

            self._write_api.write(bucket=self.bucket, record=point)
        except Exception as e:
            logger.warning("[InfluxDB] 写入请求数据失败: %s", e)

    def write_stats(
        self,
        user_count: int,
        rps: float,
        fail_ratio: float,
        avg_response_time: float,
        min_response_time: float,
        max_response_time: float,
        median_response_time: float,
        p95_response_time: float,
        p99_response_time: float,
    ):
        """
        写入统计数据

        Args:
            user_count: 当前用户数
            rps: 每秒请求数
            fail_ratio: 失败率
            avg_response_time: 平均响应时间
            min_response_time: 最小响应时间
            max_response_time: 最大响应时间
            median_response_time: 中位数响应时间
            p95_response_time: P95 响应时间
            p99_response_time: P99 响应时间
        """
        if not self._enabled:
            return

        try:
            tags = self._build_base_tags()

            point = (
                Point("locust_stats")
                .time(datetime.utcnow(), WritePrecision.MS)
            )
            
            for tag_key, tag_value in tags.items():
                point = point.tag(tag_key, tag_value)
            
            point = (
                point
                .field("user_count", user_count)
                .field("rps", rps)
                .field("fail_ratio", fail_ratio)
                .field("avg_response_time", avg_response_time)
                .field("min_response_time", min_response_time)
                .field("max_response_time", max_response_time)
                .field("median_response_time", median_response_time)
                .field("p95_response_time", p95_response_time)
                .field("p99_response_time", p99_response_time)
            )

            self._write_api.write(bucket=self.bucket, record=point)
        except Exception as e:
            logger.warning("[InfluxDB] 写入统计数据失败: %s", e)

    def write_test_event(self, event_type: str, message: Optional[str] = None):
        """
        写入测试事件
        
        Args:
            event_type: 事件类型 (start/complete/fail/stop)
            message: 事件消息
        """
        if not self._enabled:
            return

        try:
            tags = self._build_base_tags()
            tags["event_type"] = event_type

            point = (
                Point("locust_event")
                .time(datetime.utcnow(), WritePrecision.MS)
            )
            
            for tag_key, tag_value in tags.items():
                point = point.tag(tag_key, tag_value)
            
            point = point.field("value", 1)
            if message:
                point = point.field("message", message[:500])

            self._write_api.write(bucket=self.bucket, record=point)
        except Exception as e:
            logger.warning("[InfluxDB] 写入事件数据失败: %s", e)
