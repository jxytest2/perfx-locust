# perfx-locust


**perfx-locust** 是一个 Locust 包装器，用于与性能测试平台无缝集成。它允许你使用**标准的 Locust 脚本**，无需任何修改，同时自动同步测试状态、上报数据到 InfluxDB。

## 特性

- 🚀 **零侵入**: 标准 Locust 脚本无需任何修改
- 🔄 **自动状态同步**: 自动同步测试状态 (start/complete/fail) 到平台
- 📊 **InfluxDB 集成**: 实时上报性能数据到 InfluxDB，关联 run_id
- ✅ **参数验证**: 根据平台定义的 argument_schema 验证必填参数
- 🌐 **自动配置**: 从平台获取环境信息，自动设置 host

## 安装

```bash
pip install git+https://g.hz.netease.com/CloudQA/perfx-locust.git
# 或者使用 github
pip install git+https://github.com/jxytest2/perfx-locust.git
```

## 快速开始

### 1. 在平台上创建测试运行

首先在性能测试平台上创建一个测试运行记录，获取 `run_id`。

### 2. 准备 Locust 脚本

编写标准的 Locust 脚本（无需任何修改）：

```python
# locustfile.py
from locust import HttpUser, task, between

class MyUser(HttpUser):
    wait_time = between(1, 3)
    
    @task
    def my_task(self):
        self.client.post("/api/v1/rerank", json={
            "query": "test query",
            "documents": ["doc1", "doc2"]
        })
```

### 3. 执行压测

```bash
# 基本用法
perfx -f locustfile.py --run-id run_20250101_120000_abc123

# 指定平台地址
perfx -f locustfile.py --run-id xxx --platform-url http://perf-platform:8000

# 传入自定义参数（根据 endpoint 的 argument_schema 定义）
perfx -f locustfile.py --run-id xxx --model gpt-4 --batch_size 32

# 启用 InfluxDB 上报
perfx -f locustfile.py --run-id xxx \
    --influxdb-url http://localhost:8086 \
    --influxdb-token your-token \
    --influxdb-org your-org \
    --influxdb-bucket perf-data
```

## 命令行参数

| 参数 | 必填 | 说明 |
|------|------|------|
| `-f, --locustfile` | ✅ | Locust 脚本文件路径 |
| `--run-id` | ✅ | 平台上的测试运行 ID |
| `--platform-url` | ❌ | 平台 API 地址，默认 `http://localhost:8000` |
| `--influxdb-url` | ❌ | InfluxDB 地址 |
| `--influxdb-token` | ❌ | InfluxDB Token |
| `--influxdb-org` | ❌ | InfluxDB Organization |
| `--influxdb-bucket` | ❌ | InfluxDB Bucket |
| `--dry-run` | ❌ | 仅验证参数，不实际执行 |
| `--verbose` | ❌ | 显示详细输出 |

### 动态参数

除了上述固定参数外，CLI 还支持根据 Endpoint 的 `argument_schema` 动态添加参数：

```bash
# 假设 endpoint 定义了以下 argument_schema:
# {
#     "parameters": [
#         {"name": "model", "type": "string", "required": true},
#         {"name": "batch_size", "type": "int", "required": false, "default": "32"}
#     ]
# }

# 则可以这样传参：
perfx -f locustfile.py --run-id xxx --model gpt-4 --batch_size 64
```

## Argument Schema 定义

在平台上创建 Endpoint 时，可以定义 `argument_schema` 来描述该接口测试需要的参数：

```json
{
    "parameters": [
        {
            "name": "model",
            "type": "string",
            "required": true,
            "default": null,
            "description": "模型名称",
            "choices": null
        },
        {
            "name": "batch_size",
            "type": "int",
            "required": false,
            "default": "32",
            "description": "批量大小"
        },
        {
            "name": "gpu_model",
            "type": "choice",
            "required": true,
            "choices": ["A100", "H100", "RTX4090"],
            "description": "GPU型号"
        }
    ]
}
```

支持的参数类型：
- `string`: 字符串
- `int`: 整数
- `float`: 浮点数
- `bool`: 布尔值
- `choice`: 枚举值（需配合 `choices` 字段）

## 工作流程

```
┌─────────────────────────────────────────────────────────────────┐
│                        perfx CLI                                 │
├─────────────────────────────────────────────────────────────────┤
│  1. 解析命令行参数                                               │
│  2. 获取 TestRun 详情 (GET /api/perf/runs/{run_id})             │
│  3. 验证必填参数 (根据 argument_schema)                          │
│  4. 获取环境 host，设置为 Locust 的 --host                       │
│  5. 调用 /start 标记测试开始，同时保存 arguments                  │
│  6. 启动 Locust (headless 模式)                                  │
│  7. 监听 Locust 事件，实时上报数据到 InfluxDB                    │
│  8. 完成后调用 /complete 或失败时调用 /fail                      │
└─────────────────────────────────────────────────────────────────┘
```

## 环境变量

支持通过环境变量配置：

```bash
export PERFX_PLATFORM_URL=http://perf-platform:8000
export PERFX_INFLUXDB_URL=http://localhost:8086
export PERFX_INFLUXDB_TOKEN=your-token
export PERFX_INFLUXDB_ORG=your-org
export PERFX_INFLUXDB_BUCKET=perf-data
```

## 在脚本中访问参数

perfx 会将命令行传入的参数设置为环境变量，格式为 `PERFX_{参数名大写}`：

```python
import os

class MyUser(HttpUser):
    def on_start(self):
        # 获取命令行传入的 model 参数
        self.model = os.environ.get("PERFX_MODEL", "default")
        # 获取 run_id
        self.run_id = os.environ.get("PERFX_RUN_ID")
```

## License

MIT License
