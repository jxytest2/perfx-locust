"""
PerfX Runner - Locust Execution Engine

核心运行器，负责加载用户脚本、配置环境、执行测试并同步状态。
"""
import argparse
import importlib.util
import logging
import os
import sys
from pathlib import Path
from typing import Callable, Dict, List, Optional

import gevent

logger = logging.getLogger(__name__)


class PerfXRunner:
    """
    PerfX 运行器

    包装 Locust 执行流程，提供：
    - 用户脚本加载
    - 配置注入
    - 事件监听与状态同步
    - InfluxDB 数据上报
    """

    def __init__(
            self,
            locustfile: str,
            host: str,
            users: int,
            spawn_rate: float,
            run_time: Optional[str] = None,
            run_id: Optional[str] = None,
            extra_args: Optional[Dict[str, str]] = None,
            locust_args: Optional[List[str]] = None,
    ):
        """
        初始化运行器

        Args:
            locustfile: Locust 脚本路径
            host: 目标主机地址
            users: 并发用户数
            spawn_rate: 用户生成速率
            run_time: 运行时间 (如 "1m", "30s")
            run_id: 测试运行 ID
            extra_args: 额外参数 (会设置为环境变量)
        """
        self.locustfile = Path(locustfile).resolve()
        self.host = host
        self.users = users
        self.spawn_rate = spawn_rate
        self.run_time = run_time
        self.run_id = run_id
        self.extra_args = extra_args or {}
        self.locust_args = locust_args or []

        # 回调函数
        self._on_start: Optional[Callable[[], None]] = None
        self._on_complete: Optional[Callable[[], None]] = None
        self._on_fail: Optional[Callable[[str], None]] = None
        self._on_request: Optional[Callable[[dict], None]] = None
        self._on_stats: Optional[Callable[[dict], None]] = None

        self._locust_parsed_options = None

        # 状态
        self._environment = None
        self._runner = None
        self._stats_greenlet = None
        self._stop_flag = False

    def on_start(self, callback: Callable[[], None]):
        """注册测试开始回调"""
        self._on_start = callback
        return self

    def on_complete(self, callback: Callable[[], None]):
        """注册测试完成回调"""
        self._on_complete = callback
        return self

    def on_fail(self, callback: Callable[[str], None]):
        """注册测试失败回调"""
        self._on_fail = callback
        return self

    def on_request(self, callback: Callable[[dict], None]):
        """注册请求完成回调"""
        self._on_request = callback
        return self

    def on_stats(self, callback: Callable[[dict], None]):
        """注册统计数据回调 (定期调用)"""
        self._on_stats = callback
        return self

    def _load_locustfile(self) -> List[type]:
        """
        加载 Locust 脚本

        Returns:
            User 类列表
        """
        from locust import User

        if not self.locustfile.exists():
            raise FileNotFoundError(f"找不到 Locust 脚本: {self.locustfile}")

        # 将脚本目录添加到 sys.path
        script_dir = str(self.locustfile.parent)
        if script_dir not in sys.path:
            sys.path.insert(0, script_dir)

        # 动态加载模块
        spec = importlib.util.spec_from_file_location(
            "locustfile", str(self.locustfile)
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules["locustfile"] = module
        spec.loader.exec_module(module)

        # 提取 User 类（排除 abstract 和基础 HttpUser）
        from locust import HttpUser
        user_classes = []
        for name in dir(module):
            obj = getattr(module, name)
            if (
                    isinstance(obj, type)
                    and issubclass(obj, User)
                    and obj not in (User, HttpUser)
                    and not getattr(obj, "abstract", False)
            ):
                user_classes.append(obj)

        if not user_classes:
            raise ValueError(f"在 {self.locustfile} 中未找到有效的 User 类")

        logger.info("[Runner] 加载了 %d 个 User 类: %s",
                    len(user_classes), [c.__name__ for c in user_classes])
        return user_classes

    def _prepare_locust_arguments(self):
        """触发脚本自定义命令行参数解析"""
        from locust import events

        parser = argparse.ArgumentParser(add_help=False)
        events.init_command_line_parser.fire(parser=parser)
        parsed_options, unknown = parser.parse_known_args(self.locust_args)
        if unknown:
            logger.warning("[Runner] 未识别的 Locust 脚本参数: %s", unknown)
        self._locust_parsed_options = parsed_options

    def _setup_environment(self):
        """设置额外参数为环境变量"""
        for key, value in self.extra_args.items():
            env_key = f"PERFX_{key.upper()}"
            os.environ[env_key] = str(value)
            logger.debug("[Runner] 设置环境变量 %s=%s", env_key, value)

        # 设置 run_id
        if self.run_id:
            os.environ["PERFX_RUN_ID"] = self.run_id

    def _attach_event_listeners(self):
        """附加事件监听器"""
        from locust import events

        @events.request.add_listener
        def on_request(
                request_type: str,
                name: str,
                response_time: float,
                response_length: int,
                exception: Optional[Exception] = None,
                **kwargs
        ):
            if self._on_request:
                self._on_request({
                    "request_type": request_type,
                    "name": name,
                    "response_time": response_time,
                    "response_length": response_length,
                    "success": exception is None,
                    "exception": str(exception) if exception else None,
                })

        @events.quitting.add_listener
        def on_quitting(environment, **kwargs):
            self._stop_flag = True
            logger.info("[Runner] Locust 正在退出")

    def _start_stats_reporter(self, interval: float = 2.0):
        """启动统计数据上报"""

        def report_stats():
            while not self._stop_flag:
                gevent.sleep(interval)
                if self._runner and self._on_stats:
                    stats = self._runner.stats
                    total = stats.total

                    self._on_stats({
                        "user_count": self._runner.user_count,
                        "rps": total.current_rps,
                        "fail_ratio": total.fail_ratio,
                        "avg_response_time": total.avg_response_time,
                        "min_response_time": total.min_response_time or 0,
                        "max_response_time": total.max_response_time or 0,
                        "median_response_time": total.median_response_time or 0,
                        "p95_response_time": total.get_response_time_percentile(0.95) or 0,
                        "p99_response_time": total.get_response_time_percentile(0.99) or 0,
                    })

        self._stats_greenlet = gevent.spawn(report_stats)

    def _parse_run_time(self) -> Optional[int]:
        """解析运行时间字符串为秒数"""
        if not self.run_time:
            return None

        time_str = self.run_time.strip().lower()
        if time_str.endswith("s"):
            return int(time_str[:-1])
        elif time_str.endswith("m"):
            return int(time_str[:-1]) * 60
        elif time_str.endswith("h"):
            return int(time_str[:-1]) * 3600
        else:
            try:
                return int(time_str)
            except ValueError:
                logger.warning("[Runner] 无法解析运行时间: %s", self.run_time)
                return None

    def run(self) -> bool:
        """
        执行测试

        Returns:
            测试是否成功完成
        """
        from locust.env import Environment
        from locust.log import setup_logging
        from locust.stats import stats_printer

        setup_logging("INFO")

        try:
            # 1. 设置环境变量
            self._setup_environment()

            # 2. 加载用户脚本
            user_classes = self._load_locustfile()

            # 3. 解析脚本自定义命令行参数
            self._prepare_locust_arguments()

            # 4. 创建 Locust Environment
            self._environment = Environment(
                user_classes=user_classes,
                host=self.host,
            )

            if self._locust_parsed_options is not None:
                self._environment.parsed_options = self._locust_parsed_options

            # 触发 init 事件（脚本依赖此事件初始化配置）
            self._environment.events.init.fire(
                environment=self._environment,
                runner=None,
            )

            # 5. 附加事件监听器
            self._attach_event_listeners()

            # 5. 创建 Runner
            self._runner = self._environment.create_local_runner()

            # 6. 触发开始回调
            if self._on_start:
                self._on_start()

            # 7. 启动统计上报
            self._start_stats_reporter()

            # 8. 启动 stats printer (可选)
            gevent.spawn(stats_printer(self._environment.stats))

            # 9. 开始生成用户
            logger.info(
                "[Runner] 开始测试: host=%s, users=%d, spawn_rate=%.1f",
                self.host, self.users, self.spawn_rate
            )
            self._runner.start(self.users, spawn_rate=self.spawn_rate)

            # 10. 等待测试完成
            run_time_seconds = self._parse_run_time()
            if run_time_seconds:
                logger.info("[Runner] 测试将运行 %d 秒", run_time_seconds)
                gevent.sleep(run_time_seconds)
                self._runner.quit()
            else:
                # 无限运行，等待手动停止
                logger.info("[Runner] 测试将持续运行，按 Ctrl+C 停止")
                self._runner.greenlet.join()

            # 11. 等待 runner 停止
            self._stop_flag = True
            if self._stats_greenlet:
                self._stats_greenlet.kill()

            # 12. 触发完成回调
            if self._on_complete:
                self._on_complete()

            logger.info("[Runner] 测试完成")
            return True

        except KeyboardInterrupt:
            logger.info("[Runner] 收到中断信号，正在停止测试...")
            self._stop_flag = True
            if self._runner:
                self._runner.quit()
            if self._on_complete:
                self._on_complete()
            return True

        except Exception as e:
            logger.error("[Runner] 测试执行失败: %s", e, exc_info=True)
            self._stop_flag = True
            if self._on_fail:
                self._on_fail(str(e))
            return False

        finally:
            self._stop_flag = True
            if self._stats_greenlet:
                self._stats_greenlet.kill()

    def print_summary(self):
        """打印测试摘要"""
        if not self._runner:
            return

        stats = self._runner.stats
        total = stats.total

        print("\n" + "=" * 60)
        print("测试摘要")
        print("=" * 60)
        print(f"  总请求数: {total.num_requests}")
        print(f"  失败数: {total.num_failures}")
        print(f"  失败率: {total.fail_ratio * 100:.2f}%")
        print(f"  平均响应时间: {total.avg_response_time:.2f}ms")
        print(f"  最小响应时间: {total.min_response_time or 0:.2f}ms")
        print(f"  最大响应时间: {total.max_response_time or 0:.2f}ms")
        print(f"  中位数响应时间: {total.median_response_time or 0:.2f}ms")
        print(f"  P95 响应时间: {total.get_response_time_percentile(0.95) or 0:.2f}ms")
        print(f"  P99 响应时间: {total.get_response_time_percentile(0.99) or 0:.2f}ms")
        print(f"  RPS: {total.current_rps:.2f}")
        print("=" * 60 + "\n")
