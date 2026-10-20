"""
Report API路由
提供模Draft报告生成, 获取, 对话等Connect口
"""

import os
import traceback
import threading
from flask import request, jsonify, send_file

from . import report_bp
from ..config import Config
from ..services.report_agent import ReportAgent, ReportManager, ReportStatus
from ..services.simulation_manager import SimulationManager
from ..services.simulation_runner import SimulationRunner, RunnerStatus
from ..services.zep_graph_memory_updater import ZepGraphMemoryManager
from ..models.project import ProjectManager, ProjectStatus
from ..models.task import TaskManager, TaskStatus
from ..utils.logger import get_logger
from ..utils.locale import t, get_locale, set_locale
from ..utils.zep_lifecycle import (
    graph_lifecycle_lock,
    register_graph_reader,
    unregister_graph_reader,
)

logger = get_logger('mirofish.api.report')


# ============== 报告生成Connect口 ==============

@report_bp.route('/generate', methods=['POST'])
def generate_report():
    """
    生成模Draft min析报告 (异步任务) 
    
    这is 一耗 hour操作, Connect口会立即Returntask_id, 
    使Use GET /api/report/generate/status 查询进度
    
    请Request (JSON) : 
        {
            "simulation_id": "sim_xxxx",    // 必填, 模DraftID
            "force_regenerate": false        // 可选, Strong制重新生成
        }
    
    Return: 
        {
            "success": true,
            "data": {
                "simulation_id": "sim_xxxx",
                "task_id": "task_xxxx",
                "status": "generating",
                "message": "Report generation task started"
            }
        }
    """
    try:
        data = request.get_json() or {}
        
        simulation_id = data.get('simulation_id')
        if not simulation_id:
            return jsonify({
                "success": False,
                "error": t('api.requireSimulationId')
            }), 400

        force_regenerate = data.get('force_regenerate', False)
        if not isinstance(force_regenerate, bool):
            return jsonify({
                "success": False,
                "error": "force_regenerate must be a JSON boolean",
            }), 400
        
        # 获取模Draft信息
        manager = SimulationManager()
        state = manager.get_simulation(simulation_id)
        
        if not state:
            return jsonify({
                "success": False,
                "error": t('api.simulationNotFound', id=simulation_id)
            }), 404

        run_state = SimulationRunner.get_run_state(simulation_id)
        updater = ZepGraphMemoryManager.get_updater(simulation_id)
        active_statuses = {
            RunnerStatus.STARTING,
            RunnerStatus.RUNNING,
            RunnerStatus.PAUSED,
            RunnerStatus.STOPPING,
        }
        if updater is not None or (
            run_state is not None and run_state.runner_status in active_statuses
        ):
            return jsonify({
                "success": False,
                "error": (
                    "Simulation or Zep graph ingestion is still active; "
                    "wait for a terminal run status before generating a report"
                ),
                "ingestion_pending": updater is not None,
            }), 409
        successful_terminal_statuses = {
            RunnerStatus.COMPLETED,
            RunnerStatus.STOPPED,
        }
        if (
            run_state is None
            or run_state.runner_status not in successful_terminal_statuses
        ):
            return jsonify({
                "success": False,
                "error": (
                    "A successfully completed or stopped simulation is required "
                    "before generating a report"
                ),
            }), 409

        # 获取项目信息
        project = ProjectManager.get_project(state.project_id)
        if not project:
            return jsonify({
                "success": False,
                "error": t('api.projectNotFound', id=state.project_id)
            }), 404
        
        if project.status != ProjectStatus.GRAPH_COMPLETED:
            return jsonify({
                "success": False,
                "error": "The project graph must be completely built before reporting",
            }), 409

        graph_id = project.graph_id
        if not graph_id:
            return jsonify({
                "success": False,
                "error": t('api.missingGraphIdEnsure')
            }), 400
        if state.graph_id and state.graph_id != graph_id:
            return jsonify({
                "success": False,
                "error": (
                    "The simulation references an older graph; prepare it "
                    "again before generating a report"
                ),
            }), 409
        
        simulation_requirement = project.simulation_requirement
        if not simulation_requirement:
            return jsonify({
                "success": False,
                "error": t('api.missingSimRequirement')
            }), 400
        
        # 提before 生成 report_id, 以便立即Return给before 端
        import uuid
        report_id = f"report_{uuid.uuid4().hex[:12]}"
        
        # Register the background report as a graph reader under the same lock
        # used by graph deletion and updater startup. A lock itself cannot be
        # acquired in this request thread and released by the worker, so the
        # durable reader registration is the cross-thread lease.
        with graph_lifecycle_lock(graph_id):
            refreshed_state = manager.get_simulation(simulation_id)
            refreshed_project = (
                ProjectManager.get_project(refreshed_state.project_id)
                if refreshed_state
                else None
            )
            refreshed_run_state = SimulationRunner.get_run_state(simulation_id)
            refreshed_updater = ZepGraphMemoryManager.get_updater(simulation_id)
            if (
                refreshed_state is None
                or refreshed_project is None
                or refreshed_project.graph_id != graph_id
                or refreshed_project.status != ProjectStatus.GRAPH_COMPLETED
                or (
                    refreshed_state.graph_id
                    and refreshed_state.graph_id != graph_id
                )
            ):
                return jsonify({
                    "success": False,
                    "error": "The project graph changed while reporting was starting",
                }), 409
            if refreshed_updater is not None or (
                refreshed_run_state is not None
                and refreshed_run_state.runner_status in active_statuses
            ):
                return jsonify({
                    "success": False,
                    "error": (
                        "Simulation or Zep graph ingestion became active; "
                        "retry after it reaches a terminal state"
                    ),
                    "ingestion_pending": refreshed_updater is not None,
                }), 409
            if (
                refreshed_run_state is None
                or refreshed_run_state.runner_status
                not in successful_terminal_statuses
            ):
                return jsonify({
                    "success": False,
                    "error": (
                        "A successfully completed or stopped simulation is "
                        "required before generating a report"
                    ),
                }), 409

            # Cached-report reuse is now part of the same atomic barrier, so a
            # concurrent rerun cannot make the returned report stale between
            # the status check and response.
            if not force_regenerate:
                existing_report = ReportManager.get_report_by_simulation(
                    simulation_id
                )
                if (
                    existing_report
                    and existing_report.status == ReportStatus.COMPLETED
                ):
                    return jsonify({
                        "success": True,
                        "data": {
                            "simulation_id": simulation_id,
                            "report_id": existing_report.report_id,
                            "status": "completed",
                            "message": t('api.reportAlreadyExists'),
                            "already_generated": True
                        }
                    })

            task_manager = TaskManager()
            task_id = task_manager.create_task(
                task_type="report_generate",
                metadata={
                    "simulation_id": simulation_id,
                    "graph_id": graph_id,
                    "report_id": report_id
                }
            )
            current_locale = get_locale()
            register_graph_reader(graph_id, report_id)

            def run_generate():
                set_locale(current_locale)
                try:
                    task_manager.update_task(
                        task_id,
                        status=TaskStatus.PROCESSING,
                        progress=0,
                        message=t('api.initReportAgent')
                    )

                    agent = ReportAgent(
                        graph_id=graph_id,
                        simulation_id=simulation_id,
                        simulation_requirement=simulation_requirement
                    )

                    def progress_callback(stage, progress, message):
                        task_manager.update_task(
                            task_id,
                            progress=progress,
                            message=f"[{stage}] {message}"
                        )

                    report = agent.generate_report(
                        progress_callback=progress_callback,
                        report_id=report_id
                    )
                    ReportManager.save_report(report)

                    if report.status == ReportStatus.COMPLETED:
                        task_manager.complete_task(
                            task_id,
                            result={
                                "report_id": report.report_id,
                                "simulation_id": simulation_id,
                                "status": "completed"
                            }
                        )
                    else:
                        task_manager.fail_task(
                            task_id,
                            report.error or t('api.reportGenerateFailed')
                        )
                except Exception as e:
                    logger.error(f"报告生成失败: {str(e)}")
                    task_manager.fail_task(task_id, str(e))
                finally:
                    unregister_graph_reader(graph_id, report_id)

            try:
                thread = threading.Thread(target=run_generate, daemon=True)
                thread.start()
            except Exception:
                unregister_graph_reader(graph_id, report_id)
                raise
        
        return jsonify({
            "success": True,
            "data": {
                "simulation_id": simulation_id,
                "report_id": report_id,
                "task_id": task_id,
                "status": "generating",
                "message": t('api.reportGenerateStarted'),
                "already_generated": False
            }
        })
        
    except Exception as e:
        logger.error(f"启动报告生成任务失败: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@report_bp.route('/generate/status', methods=['POST'])
def get_generate_status():
    """
    查询报告生成任务进度
    
    请Request (JSON) : 
        {
            "task_id": "task_xxxx",         // 可选, generateReturn的task_id
            "simulation_id": "sim_xxxx"     // 可选, 模DraftID
        }
    
    Return: 
        {
            "success": true,
            "data": {
                "task_id": "task_xxxx",
                "status": "processing|completed|failed",
                "progress": 45,
                "message": "..."
            }
        }
    """
    try:
        data = request.get_json() or {}
        
        task_id = data.get('task_id')
        simulation_id = data.get('simulation_id')
        
        # 如果提供了simulation_id, First检查is noalready has完成的报告
        if simulation_id:
            existing_report = ReportManager.get_report_by_simulation(simulation_id)
            if existing_report and existing_report.status == ReportStatus.COMPLETED:
                return jsonify({
                    "success": True,
                    "data": {
                        "simulation_id": simulation_id,
                        "report_id": existing_report.report_id,
                        "status": "completed",
                        "progress": 100,
                        "message": t('api.reportGenerated'),
                        "already_completed": True
                    }
                })
        
        if not task_id:
            return jsonify({
                "success": False,
                "error": t('api.requireTaskOrSimId')
            }), 400
        
        task_manager = TaskManager()
        task = task_manager.get_task(task_id)
        
        if not task:
            return jsonify({
                "success": False,
                "error": t('api.taskNotFound', id=task_id)
            }), 404
        
        return jsonify({
            "success": True,
            "data": task.to_dict()
        })
        
    except Exception as e:
        logger.error(f"查询任务状态失败: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


# ============== 报告获取Connect口 ==============

@report_bp.route('/<report_id>', methods=['GET'])
def get_report(report_id: str):
    """
    获取报告详情
    
    Return: 
        {
            "success": true,
            "data": {
                "report_id": "report_xxxx",
                "simulation_id": "sim_xxxx",
                "status": "completed",
                "outline": {...},
                "markdown_content": "...",
                "created_at": "...",
                "completed_at": "..."
            }
        }
    """
    try:
        report = ReportManager.get_report(report_id)
        
        if not report:
            return jsonify({
                "success": False,
                "error": t('api.reportNotFound', id=report_id)
            }), 404
        
        return jsonify({
            "success": True,
            "data": report.to_dict()
        })
        
    except Exception as e:
        logger.error(f"获取报告失败: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@report_bp.route('/by-simulation/<simulation_id>', methods=['GET'])
def get_report_by_simulation(simulation_id: str):
    """
    根据模DraftID获取报告
    
    Return: 
        {
            "success": true,
            "data": {
                "report_id": "report_xxxx",
                ...
            }
        }
    """
    try:
        report = ReportManager.get_report_by_simulation(simulation_id)
        
        if not report:
            return jsonify({
                "success": False,
                "error": t('api.noReportForSim', id=simulation_id),
                "has_report": False
            }), 404
        
        return jsonify({
            "success": True,
            "data": report.to_dict(),
            "has_report": True
        })
        
    except Exception as e:
        logger.error(f"获取报告失败: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@report_bp.route('/list', methods=['GET'])
def list_reports():
    """
    列Output所has报告
    
    Query参数: 
        simulation_id: 按模DraftID过滤 (可选) 
        limit: Return count限制 (Default认50) 
    
    Return: 
        {
            "success": true,
            "data": [...],
            "count": 10
        }
    """
    try:
        simulation_id = request.args.get('simulation_id')
        limit = request.args.get('limit', 50, type=int)
        
        reports = ReportManager.list_reports(
            simulation_id=simulation_id,
            limit=limit
        )
        
        return jsonify({
            "success": True,
            "data": [r.to_dict() for r in reports],
            "count": len(reports)
        })
        
    except Exception as e:
        logger.error(f"列Output报告失败: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@report_bp.route('/<report_id>/download', methods=['GET'])
def download_report(report_id: str):
    """
    under 载报告 (MarkdownFormat) 
    
    ReturnMarkdown文件
    """
    try:
        report = ReportManager.get_report(report_id)
        
        if not report:
            return jsonify({
                "success": False,
                "error": t('api.reportNotFound', id=report_id)
            }), 404
        
        md_path = ReportManager._get_report_markdown_path(report_id)
        
        if not os.path.exists(md_path):
            # 如果MD文件不存在, 生成一临 hour文件
            import tempfile
            with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
                f.write(report.markdown_content)
                temp_path = f.name
            
            return send_file(
                temp_path,
                as_attachment=True,
                download_name=f"{report_id}.md"
            )
        
        return send_file(
            md_path,
            as_attachment=True,
            download_name=f"{report_id}.md"
        )
        
    except Exception as e:
        logger.error(f"under 载报告失败: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@report_bp.route('/<report_id>', methods=['DELETE'])
def delete_report(report_id: str):
    """Delete报告"""
    try:
        success = ReportManager.delete_report(report_id)
        
        if not success:
            return jsonify({
                "success": False,
                "error": t('api.reportNotFound', id=report_id)
            }), 404
        
        return jsonify({
            "success": True,
            "message": t('api.reportDeleted', id=report_id)
        })
        
    except Exception as e:
        logger.error(f"Delete报告失败: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


# ============== Report AgentConversation interface ==============

@report_bp.route('/chat', methods=['POST'])
def chat_with_report_agent():
    """
     and Report Agent对话
    
    Report Agent可以在对话in 自主InvokeUse检索工具来回答问题
    
    请Request (JSON) : 
        {
            "simulation_id": "sim_xxxx",        // 必填, 模DraftID
            "message": "请解释一under 舆情走向",    // 必填, Use户Delete息
            "chat_history": [                   // 可选, 对话历史
                {"role": "user", "content": "..."},
                {"role": "assistant", "content": "..."}
            ]
        }
    
    Return: 
        {
            "success": true,
            "data": {
                "response": "Agent回复...",
                "tool_calls": [InvokeUse的工具列表],
                "sources": [信息来Source]
            }
        }
    """
    try:
        data = request.get_json() or {}
        
        simulation_id = data.get('simulation_id')
        message = data.get('message')
        chat_history = data.get('chat_history', [])
        
        if not simulation_id:
            return jsonify({
                "success": False,
                "error": t('api.requireSimulationId')
            }), 400

        if not message:
            return jsonify({
                "success": False,
                "error": t('api.requireMessage')
            }), 400
        
        # 获取模Draft and 项目信息
        manager = SimulationManager()
        state = manager.get_simulation(simulation_id)
        
        if not state:
            return jsonify({
                "success": False,
                "error": t('api.simulationNotFound', id=simulation_id)
            }), 404

        project = ProjectManager.get_project(state.project_id)
        if not project:
            return jsonify({
                "success": False,
                "error": t('api.projectNotFound', id=state.project_id)
            }), 404
        
        graph_id = state.graph_id or project.graph_id
        if not graph_id:
            return jsonify({
                "success": False,
                "error": t('api.missingGraphId')
            }), 400
        
        simulation_requirement = project.simulation_requirement or ""
        
        # CreateAgent并进行对话
        agent = ReportAgent(
            graph_id=graph_id,
            simulation_id=simulation_id,
            simulation_requirement=simulation_requirement
        )
        
        result = agent.chat(message=message, chat_history=chat_history)
        
        return jsonify({
            "success": True,
            "data": result
        })
        
    except Exception as e:
        logger.error(f"对话失败: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


# ============== 报告进度 and  min章节Connect口 ==============

@report_bp.route('/<report_id>/progress', methods=['GET'])
def get_report_progress(report_id: str):
    """
    获取报告生成进度 (实 hour) 
    
    Return: 
        {
            "success": true,
            "data": {
                "status": "generating",
                "progress": 45,
                "message": "正在生成章节: 关键发现",
                "current_section": "关键发现",
                "completed_sections": ["Execution summary", "模Draft背景"],
                "updated_at": "2025-12-09T..."
            }
        }
    """
    try:
        progress = ReportManager.get_progress(report_id)
        
        if not progress:
            return jsonify({
                "success": False,
                "error": t('api.reportProgressNotAvail', id=report_id)
            }), 404
        
        return jsonify({
            "success": True,
            "data": progress
        })
        
    except Exception as e:
        logger.error(f"获取报告进度失败: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@report_bp.route('/<report_id>/sections', methods=['GET'])
def get_report_sections(report_id: str):
    """
    获取already 生成的章节列表 ( min章节输Output) 
    
    before 端可以 rounds询此Connect口获取already 生成的章节内容, none需等Pending整报告完成
    
    Return: 
        {
            "success": true,
            "data": {
                "report_id": "report_xxxx",
                "sections": [
                    {
                        "filename": "section_01.md",
                        "section_index": 1,
                        "content": "## Execution summary\\n\\n..."
                    },
                    ...
                ],
                "total_sections": 3,
                "is_complete": false
            }
        }
    """
    try:
        sections = ReportManager.get_generated_sections(report_id)
        
        # 获取报告状态
        report = ReportManager.get_report(report_id)
        is_complete = report is not None and report.status == ReportStatus.COMPLETED
        
        return jsonify({
            "success": True,
            "data": {
                "report_id": report_id,
                "sections": sections,
                "total_sections": len(sections),
                "is_complete": is_complete
            }
        })
        
    except Exception as e:
        logger.error(f"获取章节列表失败: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@report_bp.route('/<report_id>/section/<int:section_index>', methods=['GET'])
def get_single_section(report_id: str, section_index: int):
    """
    Fetch single chapter content
    
    Return: 
        {
            "success": true,
            "data": {
                "filename": "section_01.md",
                "content": "## Execution summary\\n\\n..."
            }
        }
    """
    try:
        section_path = ReportManager._get_section_path(report_id, section_index)
        
        if not os.path.exists(section_path):
            return jsonify({
                "success": False,
                "error": t('api.sectionNotFound', index=f"{section_index:02d}")
            }), 404
        
        with open(section_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        return jsonify({
            "success": True,
            "data": {
                "filename": f"section_{section_index:02d}.md",
                "section_index": section_index,
                "content": content
            }
        })
        
    except Exception as e:
        logger.error(f"获取章节内容失败: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


# ============== 报告状态检查Connect口 ==============

@report_bp.route('/check/<simulation_id>', methods=['GET'])
def check_report_status(simulation_id: str):
    """
    检查模Draftis nohas报告, 以 and 报告状态
    
    Use于before 端判断is no解锁Interview功能
    
    Return: 
        {
            "success": true,
            "data": {
                "simulation_id": "sim_xxxx",
                "has_report": true,
                "report_status": "completed",
                "report_id": "report_xxxx",
                "interview_unlocked": true
            }
        }
    """
    try:
        report = ReportManager.get_report_by_simulation(simulation_id)
        
        has_report = report is not None
        report_status = report.status.value if report else None
        report_id = report.report_id if report else None
        
        # 只has报告完成after 才解锁interview
        interview_unlocked = has_report and report.status == ReportStatus.COMPLETED
        
        return jsonify({
            "success": True,
            "data": {
                "simulation_id": simulation_id,
                "has_report": has_report,
                "report_status": report_status,
                "report_id": report_id,
                "interview_unlocked": interview_unlocked
            }
        })
        
    except Exception as e:
        logger.error(f"检查报告状态失败: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


# ============== Agent  day志Connect口 ==============

@report_bp.route('/<report_id>/agent-log', methods=['GET'])
def get_agent_log(report_id: str):
    """
    获取 Report Agent 的详细执行 day志
    
    实 hour获取报告生成过程in 的每一步动作, 包括: 
    - 报告开Start, 规划开Start/完成
    - Start of each chapter, tool invocation, LLM response, completion
    - Report completion or failure
    
    Query参数: 
        from_line: 从第几行开Start读取 (可选, Default认0, Use于增量获取) 
    
    Return: 
        {
            "success": true,
            "data": {
                "logs": [
                    {
                        "timestamp": "2025-12-13T...",
                        "elapsed_seconds": 12.5,
                        "report_id": "report_xxxx",
                        "action": "tool_call",
                        "stage": "generating",
                        "section_title": "Execution summary",
                        "section_index": 1,
                        "details": {
                            "tool_name": "insight_forge",
                            "parameters": {...},
                            ...
                        }
                    },
                    ...
                ],
                "total_lines": 25,
                "from_line": 0,
                "has_more": false
            }
        }
    """
    try:
        from_line = request.args.get('from_line', 0, type=int)
        
        log_data = ReportManager.get_agent_log(report_id, from_line=from_line)
        
        return jsonify({
            "success": True,
            "data": log_data
        })
        
    except Exception as e:
        logger.error(f"Failed to retrieve Agent logs: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@report_bp.route('/<report_id>/agent-log/stream', methods=['GET'])
def stream_agent_log(report_id: str):
    """
    获取完整的 Agent  day志 (一 times性获取全部) 
    
    Return: 
        {
            "success": true,
            "data": {
                "logs": [...],
                "count": 25
            }
        }
    """
    try:
        logs = ReportManager.get_agent_log_stream(report_id)
        
        return jsonify({
            "success": True,
            "data": {
                "logs": logs,
                "count": len(logs)
            }
        })
        
    except Exception as e:
        logger.error(f"Failed to retrieve Agent logs: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


# ============== 控制台 day志Connect口 ==============

@report_bp.route('/<report_id>/console-log', methods=['GET'])
def get_console_log(report_id: str):
    """
    获取 Report Agent 的控制台输Output day志
    
    实 hour获取报告生成过程in 的控制台输Output (INFO, WARNING等) , 
    这 and  agent-log Connect口Return的结构Transform JSON  day志不Same, 
    is 纯文本Format的控制台Style day志. 
    
    Query参数: 
        from_line: 从第几行开Start读取 (可选, Default认0, Use于增量获取) 
    
    Return: 
        {
            "success": true,
            "data": {
                "logs": [
                    "[19:46:14] INFO: 搜索完成: 找到 15  items相关事实",
                    "[19:46:14] INFO: 图谱搜索: graph_id=xxx, query=...",
                    ...
                ],
                "total_lines": 100,
                "from_line": 0,
                "has_more": false
            }
        }
    """
    try:
        from_line = request.args.get('from_line', 0, type=int)
        
        log_data = ReportManager.get_console_log(report_id, from_line=from_line)
        
        return jsonify({
            "success": True,
            "data": log_data
        })
        
    except Exception as e:
        logger.error(f"获取控制台 day志失败: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@report_bp.route('/<report_id>/console-log/stream', methods=['GET'])
def stream_console_log(report_id: str):
    """
    获取完整的控制台 day志 (一 times性获取全部) 
    
    Return: 
        {
            "success": true,
            "data": {
                "logs": [...],
                "count": 100
            }
        }
    """
    try:
        logs = ReportManager.get_console_log_stream(report_id)
        
        return jsonify({
            "success": True,
            "data": {
                "logs": logs,
                "count": len(logs)
            }
        })
        
    except Exception as e:
        logger.error(f"获取控制台 day志失败: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


# ============== 工具InvokeUseConnect口 (供InvokeTest使Use) ==============

@report_bp.route('/tools/search', methods=['POST'])
def search_graph_tool():
    """
    Graph search tool interface (for debugging use) 
    
    请Request (JSON) : 
        {
            "graph_id": "mirofish_xxxx",
            "query": "搜索查询",
            "limit": 10
        }
    """
    try:
        data = request.get_json() or {}
        
        graph_id = data.get('graph_id')
        query = data.get('query')
        limit = data.get('limit', 10)
        
        if not graph_id or not query:
            return jsonify({
                "success": False,
                "error": t('api.requireGraphIdAndQuery')
            }), 400
        
        from ..services.zep_tools import ZepToolsService
        
        tools = ZepToolsService()
        result = tools.search_graph(
            graph_id=graph_id,
            query=query,
            limit=limit
        )
        
        return jsonify({
            "success": True,
            "data": result.to_dict()
        })
        
    except Exception as e:
        logger.error(f"Graph search failed: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@report_bp.route('/tools/statistics', methods=['POST'])
def get_graph_statistics_tool():
    """
    图谱统计工具Connect口 (供InvokeTest使Use) 
    
    请Request (JSON) : 
        {
            "graph_id": "mirofish_xxxx"
        }
    """
    try:
        data = request.get_json() or {}
        
        graph_id = data.get('graph_id')
        
        if not graph_id:
            return jsonify({
                "success": False,
                "error": t('api.requireGraphId')
            }), 400
        
        from ..services.zep_tools import ZepToolsService
        
        tools = ZepToolsService()
        result = tools.get_graph_statistics(graph_id)
        
        return jsonify({
            "success": True,
            "data": result
        })
        
    except Exception as e:
        logger.error(f"Fetch graph statistics失败: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500
