"""
Windows 导出 Agent 服务

在 Windows 机器上运行此服务，macOS 可以通过 HTTP 请求触发导出。

使用方法：
1. 在 Windows 上安装 Python 依赖：pip install fastapi uvicorn pyJianYingDraft
2. 运行服务：python windows_export_agent.py
3. macOS 通过 API 调用导出

默认监听: http://0.0.0.0:8765
"""

import os
import sys
import json
import time
import subprocess
import argparse
from typing import Optional
from pathlib import Path

# FastAPI 服务
try:
    from fastapi import FastAPI, HTTPException, BackgroundTasks
    from fastapi.responses import JSONResponse
    import uvicorn
    FASTAPI_AVAILABLE = True
except ImportError:
    FASTAPI_AVAILABLE = False
    print("⚠️ FastAPI 未安装，请运行: pip install fastapi uvicorn")

# 剪映自动导出
try:
    import pyJianYingDraft as draft
    from pyJianYingDraft import ExportResolution, ExportFramerate
    PYDRAFT_AVAILABLE = True
except ImportError:
    PYDRAFT_AVAILABLE = False
    print("⚠️ pyJianYingDraft 未安装")

# =============================================================================
# 配置
# =============================================================================

DEFAULT_PORT = 8765
DEFAULT_HOST = "0.0.0.0"

# 剪映草稿目录
JIANYING_DRAFTS_PATH = os.environ.get(
    "JIANYING_DRAFTS_PATH",
    r"C:\Users\Administrator\AppData\Local\JianyingPro\User Data\Projects\com.lveditor.draft"
)

# =============================================================================
# 导出任务队列
# =============================================================================

export_tasks = {}  # task_id -> status


def get_drafts_list():
    """获取草稿列表"""
    if not os.path.exists(JIANYING_DRAFTS_PATH):
        return []

    drafts = []
    for item in os.listdir(JIANYING_DRAFTS_PATH):
        path = os.path.join(JIANYING_DRAFTS_PATH, item)
        if os.path.isdir(path):
            meta_path = os.path.join(path, "draft_meta_info.json")
            content_path = os.path.join(path, "draft_content.json")
            if os.path.exists(meta_path) or os.path.exists(content_path):
                drafts.append({
                    "name": item,
                    "path": path,
                    "has_content": os.path.exists(content_path),
                    "has_meta": os.path.exists(meta_path)
                })
    return drafts


def export_draft_task(draft_name: str, output_path: str, resolution: str = "1080P",
                      framerate: str = "30fps") -> dict:
    """
    执行导出任务（后台运行）
    """
    task_id = f"export_{int(time.time())}"
    export_tasks[task_id] = {
        "status": "running",
        "draft_name": draft_name,
        "output_path": output_path,
        "start_time": time.time(),
        "progress": 0
    }

    try:
        # 解析分辨率
        res_map = {
            "480P": draft.ExportResolution.RES_480P,
            "720P": draft.ExportResolution.RES_720P,
            "1080P": draft.ExportResolution.RES_1080P,
            "2K": draft.ExportResolution.RES_2K,
            "4K": draft.ExportResolution.RES_4K,
            "8K": draft.ExportResolution.RES_8K,
        }

        # 解析帧率
        fr_map = {
            "24fps": draft.ExportFramerate.FR_24,
            "25fps": draft.ExportFramerate.FR_25,
            "30fps": draft.ExportFramerate.FR_30,
            "50fps": draft.ExportFramerate.FR_50,
            "60fps": draft.ExportFramerate.FR_60,
        }

        target_res = res_map.get(resolution, draft.ExportResolution.RES_1080P)
        target_fr = fr_map.get(framerate, draft.ExportFramerate.FR_30)

        print(f"🔄 开始导出: {draft_name} -> {output_path}")

        # 初始化剪映控制器
        from pyJianYingDraft.jianying_controller import JianyingController
        ctl = JianyingController()

        # 执行导出
        ctl.export_draft(
            draft_name=draft_name,
            output_path=output_path,
            resolution=target_res,
            framerate=target_fr,
            timeout=1800  # 30 分钟超时
        )

        export_tasks[task_id]["status"] = "completed"
        export_tasks[task_id]["progress"] = 100
        export_tasks[task_id]["completed_time"] = time.time()

        print(f"✅ 导出完成: {output_path}")
        return {"status": "success", "task_id": task_id}

    except Exception as e:
        export_tasks[task_id]["status"] = "failed"
        export_tasks[task_id]["error"] = str(e)
        export_tasks[task_id]["failed_time"] = time.time()
        print(f"❌ 导出失败: {e}")
        return {"status": "failed", "error": str(e), "task_id": task_id}


# =============================================================================
# FastAPI 应用
# =============================================================================

if FASTAPI_AVAILABLE:
    app = FastAPI(title="JianYing Windows Export Agent")

    @app.get("/")
    async def root():
        return {
            "service": "JianYing Windows Export Agent",
            "version": "1.0.0",
            "status": "running"
        }

    @app.get("/health")
    async def health():
        """健康检查"""
        return {
            "status": "healthy",
            "drafts_path": JIANYING_DRAFTS_PATH,
            "drafts_count": len(get_drafts_list())
        }

    @app.get("/drafts")
    async def list_drafts():
        """列出可用草稿"""
        return {"drafts": get_drafts_list()}

    @app.post("/export")
    async def start_export(
        draft_name: str,
        output_path: str,
        resolution: str = "1080P",
        framerate: str = "30fps"
    ):
        """启动导出任务"""
        if not PYDRAFT_AVAILABLE:
            raise HTTPException(status_code=500, detail="pyJianYingDraft 未安装")

        if not os.path.exists(JIANYING_DRAFTS_PATH):
            raise HTTPException(status_code=400, detail=f"草稿目录不存在: {JIANYING_DRAFTS_PATH}")

        draft_path = os.path.join(JIANYING_DRAFTS_PATH, draft_name)
        if not os.path.exists(draft_path):
            raise HTTPException(status_code=404, detail=f"草稿不存在: {draft_name}")

        # 后台执行导出
        background_tasks = BackgroundTasks()
        # 注意：这里需要在后台运行但不使用 FastAPI 的 BackgroundTasks

        import threading
        thread = threading.Thread(
            target=export_draft_task,
            args=(draft_name, output_path, resolution, framerate)
        )
        thread.daemon = True
        thread.start()

        # 等待任务开始
        time.sleep(0.5)

        # 找到最新的任务
        active_tasks = [t for t in export_tasks.values()
                      if t.get("draft_name") == draft_name and t.get("status") == "running"]
        if active_tasks:
            task_id = list(export_tasks.keys())[list(export_tasks.values()).index(active_tasks[0])]
        else:
            task_id = "unknown"

        return {
            "message": "导出任务已启动",
            "task_id": task_id,
            "draft_name": draft_name,
            "output_path": output_path,
            "check_status_url": f"/export/{task_id}/status"
        }

    @app.get("/export/{task_id}/status")
    async def get_export_status(task_id: str):
        """查询导出状态"""
        if task_id not in export_tasks:
            raise HTTPException(status_code=404, detail=f"任务不存在: {task_id}")

        task = export_tasks[task_id]
        return {
            "task_id": task_id,
            "status": task.get("status"),
            "progress": task.get("progress", 0),
            "draft_name": task.get("draft_name"),
            "output_path": task.get("output_path"),
            "elapsed_time": time.time() - task.get("start_time", 0) if task.get("start_time") else 0
        }


# =============================================================================
# CLI 模式（不使用 FastAPI）
# =============================================================================

def cli_mode(draft_name: str, output_path: str, resolution: str = "1080",
             framerate: str = "30"):
    """命令行模式直接执行导出"""
    if not PYDRAFT_AVAILABLE:
        print("❌ pyJianYingDraft 未安装")
        return 1

    result = export_draft_task(draft_name, output_path, resolution, framerate)

    if result["status"] == "success":
        print(f"✅ 导出成功: {output_path}")
        return 0
    else:
        print(f"❌ 导出失败: {result.get('error', '未知错误')}")
        return 1


# =============================================================================
# 主入口
# =============================================================================

def main():
    parser = argparse.ArgumentParser(description="JianYing Windows Export Agent")
    parser.add_argument("--host", default=DEFAULT_HOST, help="监听地址")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="监听端口")
    parser.add_argument("--drafts-path", help="剪映草稿目录")
    parser.add_argument("--cli", action="store_true", help="命令行模式（不启动服务）")
    parser.add_argument("draft_name", nargs="?", help="草稿名称（CLI 模式）")
    parser.add_argument("output_path", nargs="?", help="输出路径（CLI 模式）")
    parser.add_argument("--res", default="1080", help="分辨率 (480/720/1080/2K/4K/8K)")
    parser.add_argument("--fps", default="30", help="帧率 (24/25/30/50/60)")

    args = parser.parse_args()

    # 设置草稿目录
    global JIANYING_DRAFTS_PATH
    if args.drafts_path:
        JIANYING_DRAFTS_PATH = args.drafts_path

    if args.cli:
        # 命令行模式
        if not args.draft_name or not args.output_path:
            parser.print_help()
            return 1
        return cli_mode(args.draft_name, args.output_path, args.res, args.fps)
    else:
        # 服务模式
        if not FASTAPI_AVAILABLE:
            print("❌ FastAPI 未安装，无法启动服务")
            print("请运行: pip install fastapi uvicorn")
            print("或使用 CLI 模式: python windows_export_agent.py --cli <草稿名> <输出路径>")
            return 1

        print(f"""
╔════════════════════════════════════════════════════════════╗
║       JianYing Windows Export Agent                       ║
╠════════════════════════════════════════════════════════════╣
║  监听地址: http://{args.host}:{args.port}                        ║
║  草稿目录: {JIANYING_DRAFTS_PATH[:50]}...  ║
║                                                            ║
║  API 端点:                                                 ║
║    GET  /              - 服务信息                          ║
║    GET  /health        - 健康检查                          ║
║    GET  /drafts        - 列出草稿                          ║
║    POST /export        - 启动导出任务                      ║
║    GET  /export/{{id}}/status - 查询导出状态              ║
╚════════════════════════════════════════════════════════════╝
        """)

        uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
