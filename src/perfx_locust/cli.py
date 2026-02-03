"""
PerfX CLI - Command Line Interface

提供 `perfx` 命令，用于执行 Locust 性能测试。
"""
import logging
import sys
from typing import Any, Dict, Optional

import click

from .client import PerfXClient
from .influxdb_reporter import InfluxDBReporter
from .runner import PerfXRunner
from .validator import ArgumentValidator

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def parse_extra_args(args: tuple) -> Dict[str, Any]:
    """
    解析额外的命令行参数
    
    支持格式: --arg-name value 或 --arg-name=value
    
    Args:
        args: 原始参数元组
        
    Returns:
        参数字典
    """
    result = {}
    i = 0
    while i < len(args):
        arg = args[i]
        if arg.startswith("--"):
            if "=" in arg:
                # --key=value 格式
                key, value = arg[2:].split("=", 1)
                result[key.replace("-", "_")] = value
            elif i + 1 < len(args) and not args[i + 1].startswith("--"):
                # --key value 格式
                key = arg[2:].replace("-", "_")
                result[key] = args[i + 1]
                i += 1
            else:
                # --flag 格式 (布尔值)
                key = arg[2:].replace("-", "_")
                result[key] = True
        i += 1
    return result


@click.command(
    context_settings=dict(
        ignore_unknown_options=True,
        allow_extra_args=True,
    )
)
@click.option(
    "-f", "--locustfile",
    required=True,
    type=click.Path(exists=True),
    help="Locust 脚本文件路径",
)
@click.option(
    "--run-id",
    required=True,
    help="测试运行 ID (从平台获取)",
)
@click.option(
    "--platform-url",
    envvar="PERFX_PLATFORM_URL",
    default="http://localhost:8000",
    help="性能测试平台 URL",
)
@click.option(
    "--influxdb-url",
    envvar="PERFX_INFLUXDB_URL",
    help="InfluxDB URL",
)
@click.option(
    "--influxdb-token",
    envvar="PERFX_INFLUXDB_TOKEN",
    help="InfluxDB Token",
)
@click.option(
    "--influxdb-org",
    envvar="PERFX_INFLUXDB_ORG",
    default="performance",
    help="InfluxDB Organization",
)
@click.option(
    "--influxdb-bucket",
    envvar="PERFX_INFLUXDB_BUCKET",
    default="locust",
    help="InfluxDB Bucket",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="仅验证参数，不执行测试",
)
@click.option(
    "-v", "--verbose",
    is_flag=True,
    help="显示详细日志",
)
@click.pass_context
def main(
        ctx: click.Context,
        locustfile: str,
        run_id: str,
        platform_url: str,
        influxdb_url: Optional[str],
        influxdb_token: Optional[str],
        influxdb_org: str,
        influxdb_bucket: str,
        dry_run: bool,
        verbose: bool,
):
    """
    PerfX - Locust 性能测试执行器
    
    使用平台配置执行 Locust 性能测试，自动同步状态和上报数据。
    
    \b
    示例:
      perfx -f locustfile.py --run-id abc123
      perfx -f locustfile.py --run-id abc123 --api-key secret
    """
    if verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # 解析额外参数
    extra_args = parse_extra_args(ctx.args)
    if extra_args:
        logger.info("[CLI] 额外参数: %s", extra_args)

    # 创建平台客户端
    client = PerfXClient(base_url=platform_url)

    try:
        # 1. 获取测试运行详情
        logger.info("[CLI] 正在获取测试运行配置 (run_id=%s)...", run_id)
        test_run = client.get_test_run(run_id)

        logger.info("[CLI] 测试配置:")
        logger.info("  - 接口: %s", test_run.endpoint_name or "未知")
        logger.info("  - 环境: %s", test_run.env_code or "未知")
        logger.info("  - Host: %s", test_run.host or "未知")
        logger.info("  - 用户数: %s", test_run.users)
        logger.info("  - 生成速率: %s", test_run.spawn_rate)
        logger.info("  - 运行时间: %s", test_run.run_time or "无限制")

        # 2. 验证参数
        validator = ArgumentValidator(test_run)
        validation_result = validator.validate(extra_args)

        if not validation_result.valid:
            logger.error("[CLI] 参数验证失败:")
            for error in validation_result.errors:
                logger.error("  - %s: %s", error.parameter, error.message)

            # 显示帮助信息
            print("\n" + validator.format_help())

            # 标记测试失败
            error_msg = "; ".join([e.message for e in validation_result.errors])
            client.fail_test_run(run_id, error_msg)
            sys.exit(1)

        resolved_args = validation_result.resolved_arguments
        logger.info("[CLI] 参数验证通过: %s", resolved_args)

        if dry_run:
            logger.info("[CLI] Dry run 模式，跳过实际执行")
            print("\n" + "=" * 60)
            print("参数验证成功！以下是将要使用的配置：")
            print("=" * 60)
            print(f"  脚本: {locustfile}")
            print(f"  Host: {test_run.host}")
            print(f"  用户数: {test_run.users}")
            print(f"  生成速率: {test_run.spawn_rate}")
            print(f"  运行时间: {test_run.run_time or '无限制'}")
            print(f"  额外参数: {resolved_args}")
            print("=" * 60)
            return

        # 3. 检查必要配置
        if not test_run.host:
            error_msg = "测试配置中未设置目标 Host"
            logger.error("[CLI] %s", error_msg)
            client.fail_test_run(run_id, error_msg)
            sys.exit(1)

        # 4. 创建 InfluxDB 上报器
        influx_reporter = None
        if influxdb_url:
            influx_reporter = InfluxDBReporter(
                url=influxdb_url,
                token=influxdb_token,
                org=influxdb_org,
                bucket=influxdb_bucket,
                run_id=run_id,
                endpoint_id=test_run.endpoint_id,
                env_code=test_run.env_code,
            )
            if influx_reporter.connect():
                logger.info("[CLI] InfluxDB 连接成功")
            else:
                logger.warning("[CLI] InfluxDB 连接失败，数据将不会上报")
                influx_reporter = None

        # 5. 创建运行器
        runner = PerfXRunner(
            locustfile=locustfile,
            host=test_run.host,
            users=test_run.users,
            spawn_rate=test_run.spawn_rate,
            run_time=test_run.run_time,
            run_id=run_id,
            extra_args=resolved_args,
        )

        # 6. 注册回调
        def on_start():
            logger.info("[CLI] 测试开始，同步状态到平台...")
            client.start_test_run(run_id, resolved_args)
            if influx_reporter:
                influx_reporter.write_test_event("start")

        def on_complete():
            logger.info("[CLI] 测试完成，同步状态到平台...")
            client.complete_test_run(run_id)
            if influx_reporter:
                influx_reporter.write_test_event("complete")
                influx_reporter.close()

        def on_fail(error: str):
            logger.error("[CLI] 测试失败: %s", error)
            client.fail_test_run(run_id, error)
            if influx_reporter:
                influx_reporter.write_test_event("fail", error)
                influx_reporter.close()

        def on_request(data: dict):
            if influx_reporter:
                influx_reporter.write_request(
                    request_type=data["request_type"],
                    name=data["name"],
                    response_time=data["response_time"],
                    response_length=data["response_length"],
                    success=data["success"],
                    exception=data.get("exception"),
                )

        def on_stats(data: dict):
            if influx_reporter:
                influx_reporter.write_stats(**data)

        runner.on_start(on_start)
        runner.on_complete(on_complete)
        runner.on_fail(on_fail)
        runner.on_request(on_request)
        runner.on_stats(on_stats)

        # 7. 执行测试
        logger.info("[CLI] 开始执行测试...")
        success = runner.run()

        # 8. 打印摘要
        runner.print_summary()

        sys.exit(0 if success else 1)

    except Exception as e:
        logger.error("[CLI] 执行失败: %s", e, exc_info=verbose)
        try:
            client.fail_test_run(run_id, str(e))
        except Exception:
            pass
        sys.exit(1)


if __name__ == "__main__":
    main()
