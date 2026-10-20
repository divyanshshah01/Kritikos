"""
Report Agent服务
使UseLangChain + Zep实现ReACT模式的模Draft报告生成

功能: 
1. 根据模Draft需Request and Zep图谱信息生成报告
2. First规划目录结构, 然after  minSegment生成
3. 每Segment采UseReACT多 roundsThought考 and 反Thought模式
4. 支持 and Use户对话, 在对话in 自主InvokeUse检索工具
"""

import os
import json
import time
import re
from typing import Dict, Any, List, Optional, Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from ..config import Config
from ..utils.llm_client import LLMClient
from ..utils.logger import get_logger
from ..utils.locale import get_language_instruction, t
from .zep_tools import (
    ZepToolsService, 
    SearchResult, 
    InsightForgeResult, 
    PanoramaResult,
    InterviewResult
)

logger = get_logger('mirofish.report_agent')


class ReportLogger:
    """
    Report Agent 详细 day志记录Device
    
    在报告文件Clipin 生成 agent_log.jsonl 文件, 记录每一步详细动作. 
    每行is 一完整的 JSON 对象, Include hour间戳, 动作Class型, 详细内容等. 
    """
    
    def __init__(self, report_id: str):
        """
        初StartTransform day志记录Device
        
        Args:
            report_id: 报告ID, Use于确定 day志文件路径
        """
        self.report_id = report_id
        self.log_file_path = os.path.join(
            Config.UPLOAD_FOLDER, 'reports', report_id, 'agent_log.jsonl'
        )
        self.start_time = datetime.now()
        self._ensure_log_file()
    
    def _ensure_log_file(self):
        """确保 day志文件所在目录存在"""
        log_dir = os.path.dirname(self.log_file_path)
        os.makedirs(log_dir, exist_ok=True)
    
    def _get_elapsed_time(self) -> float:
        """获取从开Start到现在的耗 hour (s) """
        return (datetime.now() - self.start_time).total_seconds()
    
    def log(
        self, 
        action: str, 
        stage: str,
        details: Dict[str, Any],
        section_title: str = None,
        section_index: int = None
    ):
        """
        记录一 items day志
        
        Args:
            action: 动作Class型, 如 'start', 'tool_call', 'llm_response', 'section_complete' 等
            stage: 当before 阶Segment, 如 'planning', 'generating', 'completed'
            details: 详细内容字典, 不截断
            section_title: 当before 章节标题 (可选) 
            section_index: 当before 章节索引 (可选) 
        """
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "elapsed_seconds": round(self._get_elapsed_time(), 2),
            "report_id": self.report_id,
            "action": action,
            "stage": stage,
            "section_title": section_title,
            "section_index": section_index,
            "details": details
        }
        
        # 追加写入 JSONL 文件
        with open(self.log_file_path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(log_entry, ensure_ascii=False) + '\n')
    
    def log_start(self, simulation_id: str, graph_id: str, simulation_requirement: str):
        """记录报告生成开Start"""
        self.log(
            action="report_start",
            stage="pending",
            details={
                "simulation_id": simulation_id,
                "graph_id": graph_id,
                "simulation_requirement": simulation_requirement,
                "message": t('report.taskStarted')
            }
        )
    
    def log_planning_start(self):
        """记录Large纲规划开Start"""
        self.log(
            action="planning_start",
            stage="planning",
            details={"message": t('report.planningStart')}
        )
    
    def log_planning_context(self, context: Dict[str, Any]):
        """Record context information obtained during planning"""
        self.log(
            action="planning_context",
            stage="planning",
            details={
                "message": t('report.fetchSimContext'),
                "context": context
            }
        )
    
    def log_planning_complete(self, outline_dict: Dict[str, Any]):
        """记录Large纲规划完成"""
        self.log(
            action="planning_complete",
            stage="planning",
            details={
                "message": t('report.planningComplete'),
                "outline": outline_dict
            }
        )
    
    def log_section_start(self, section_title: str, section_index: int):
        """Log start of chapter generation"""
        self.log(
            action="section_start",
            stage="generating",
            section_title=section_title,
            section_index=section_index,
            details={"message": t('report.sectionStart', title=section_title)}
        )
    
    def log_react_thought(self, section_title: str, section_index: int, iteration: int, thought: str):
        """记录 ReACT Thought考过程"""
        self.log(
            action="react_thought",
            stage="generating",
            section_title=section_title,
            section_index=section_index,
            details={
                "iteration": iteration,
                "thought": thought,
                "message": t('report.reactThought', iteration=iteration)
            }
        )
    
    def log_tool_call(
        self, 
        section_title: str, 
        section_index: int,
        tool_name: str, 
        parameters: Dict[str, Any],
        iteration: int
    ):
        """记录工具InvokeUse"""
        self.log(
            action="tool_call",
            stage="generating",
            section_title=section_title,
            section_index=section_index,
            details={
                "iteration": iteration,
                "tool_name": tool_name,
                "parameters": parameters,
                "message": t('report.toolCall', toolName=tool_name)
            }
        )
    
    def log_tool_result(
        self,
        section_title: str,
        section_index: int,
        tool_name: str,
        result: str,
        iteration: int
    ):
        """记录工具InvokeUse结果 (完整内容, 不截断) """
        self.log(
            action="tool_result",
            stage="generating",
            section_title=section_title,
            section_index=section_index,
            details={
                "iteration": iteration,
                "tool_name": tool_name,
                "result": result,  # 完整结果, 不截断
                "result_length": len(result),
                "message": t('report.toolResult', toolName=tool_name)
            }
        )
    
    def log_llm_response(
        self,
        section_title: str,
        section_index: int,
        response: str,
        iteration: int,
        has_tool_calls: bool,
        has_final_answer: bool
    ):
        """记录 LLM 响应 (完整内容, 不截断) """
        self.log(
            action="llm_response",
            stage="generating",
            section_title=section_title,
            section_index=section_index,
            details={
                "iteration": iteration,
                "response": response,  # 完整响应, 不截断
                "response_length": len(response),
                "has_tool_calls": has_tool_calls,
                "has_final_answer": has_final_answer,
                "message": t('report.llmResponse', hasToolCalls=has_tool_calls, hasFinalAnswer=has_final_answer)
            }
        )
    
    def log_section_content(
        self,
        section_title: str,
        section_index: int,
        content: str,
        tool_calls_count: int
    ):
        """记录章节内容生成完成 (仅记录内容, 不代表整章节完成) """
        self.log(
            action="section_content",
            stage="generating",
            section_title=section_title,
            section_index=section_index,
            details={
                "content": content,  # 完整内容, 不截断
                "content_length": len(content),
                "tool_calls_count": tool_calls_count,
                "message": t('report.sectionContentDone', title=section_title)
            }
        )
    
    def log_section_full_complete(
        self,
        section_title: str,
        section_index: int,
        full_content: str
    ):
        """
        记录章节生成完成

        before 端应监听此 day志来判断一章节is noTrue正完成, 并获取完整内容
        """
        self.log(
            action="section_complete",
            stage="generating",
            section_title=section_title,
            section_index=section_index,
            details={
                "content": full_content,
                "content_length": len(full_content),
                "message": t('report.sectionComplete', title=section_title)
            }
        )
    
    def log_report_complete(self, total_sections: int, total_time_seconds: float):
        """记录报告生成完成"""
        self.log(
            action="report_complete",
            stage="completed",
            details={
                "total_sections": total_sections,
                "total_time_seconds": round(total_time_seconds, 2),
                "message": t('report.reportComplete')
            }
        )
    
    def log_error(self, error_message: str, stage: str, section_title: str = None):
        """记录错误"""
        self.log(
            action="error",
            stage=stage,
            section_title=section_title,
            section_index=None,
            details={
                "error": error_message,
                "message": t('report.errorOccurred', error=error_message)
            }
        )


class ReportConsoleLogger:
    """
    Report Agent 控制台 day志记录Device
    
    将控制台Style的 day志 (INFO, WARNING等) 写入报告文件Clipin 的 console_log.txt 文件. 
    These logs and agent_log.jsonl 不Same, is 纯文本Format的控制台输Output. 
    """
    
    def __init__(self, report_id: str):
        """
        初StartTransform控制台 day志记录Device
        
        Args:
            report_id: 报告ID, Use于确定 day志文件路径
        """
        self.report_id = report_id
        self.log_file_path = os.path.join(
            Config.UPLOAD_FOLDER, 'reports', report_id, 'console_log.txt'
        )
        self._ensure_log_file()
        self._file_handler = None
        self._setup_file_handler()
    
    def _ensure_log_file(self):
        """确保 day志文件所在目录存在"""
        log_dir = os.path.dirname(self.log_file_path)
        os.makedirs(log_dir, exist_ok=True)
    
    def _setup_file_handler(self):
        """设置文件Location理Device, 将 day志Same hour写入文件"""
        import logging
        
        # Create文件Location理Device
        self._file_handler = logging.FileHandler(
            self.log_file_path,
            mode='a',
            encoding='utf-8'
        )
        self._file_handler.setLevel(logging.INFO)
        
        # 使Use and 控制台相Same的简洁Format
        formatter = logging.Formatter(
            '[%(asctime)s] %(levelname)s: %(message)s',
            datefmt='%H:%M:%S'
        )
        self._file_handler.setFormatter(formatter)
        
        # 添加到 report_agent 相关的 logger
        loggers_to_attach = [
            'mirofish.report_agent',
            'mirofish.zep_tools',
        ]
        
        for logger_name in loggers_to_attach:
            target_logger = logging.getLogger(logger_name)
            # 避免重复添加
            if self._file_handler not in target_logger.handlers:
                target_logger.addHandler(self._file_handler)
    
    def close(self):
        """关闭文件Location理Device并从 logger in Transfer除"""
        import logging
        
        if self._file_handler:
            loggers_to_detach = [
                'mirofish.report_agent',
                'mirofish.zep_tools',
            ]
            
            for logger_name in loggers_to_detach:
                target_logger = logging.getLogger(logger_name)
                if self._file_handler in target_logger.handlers:
                    target_logger.removeHandler(self._file_handler)
            
            self._file_handler.close()
            self._file_handler = None
    
    def __del__(self):
        """析构 hour确保关闭文件Location理Device"""
        self.close()


class ReportStatus(str, Enum):
    """报告状态"""
    PENDING = "pending"
    PLANNING = "planning"
    GENERATING = "generating"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class ReportSection:
    """报告章节"""
    title: str
    content: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "content": self.content
        }

    def to_markdown(self, level: int = 2) -> str:
        """Convert换为MarkdownFormat"""
        md = f"{'#' * level} {self.title}\n\n"
        if self.content:
            md += f"{self.content}\n\n"
        return md


@dataclass
class ReportOutline:
    """报告Large纲"""
    title: str
    summary: str
    sections: List[ReportSection]
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "summary": self.summary,
            "sections": [s.to_dict() for s in self.sections]
        }
    
    def to_markdown(self) -> str:
        """Convert换为MarkdownFormat"""
        md = f"# {self.title}\n\n"
        md += f"> {self.summary}\n\n"
        for section in self.sections:
            md += section.to_markdown()
        return md


@dataclass
class Report:
    """完整报告"""
    report_id: str
    simulation_id: str
    graph_id: str
    simulation_requirement: str
    status: ReportStatus
    outline: Optional[ReportOutline] = None
    markdown_content: str = ""
    created_at: str = ""
    completed_at: str = ""
    error: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "report_id": self.report_id,
            "simulation_id": self.simulation_id,
            "graph_id": self.graph_id,
            "simulation_requirement": self.simulation_requirement,
            "status": self.status.value,
            "outline": self.outline.to_dict() if self.outline else None,
            "markdown_content": self.markdown_content,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
            "error": self.error
        }


# ═══════════════════════════════════════════════════════════════
# Prompt 模板常量
# ═══════════════════════════════════════════════════════════════

# ── 工具描Description ──

TOOL_DESC_INSIGHT_FORGE = """\
 [深度洞Observe检索 - Powerful retrieval tool] 
这is 我们StrongLarge的检索函数, 专为深度 min析设计. 它会: 
1. 自动将你的问题 min解为多Child问题
2. 从多维度检索模Draft图谱in 的信息
3. 整合语义搜索, entities min析, relations链追踪的结果
4. Return最全面, 最深度的检索内容

 [使Use场景] 
- 需要深入 min析某话题
- 需要了解Event的多方面
- 需要获取支撑报告章节的丰富素材

 [Return内容] 
- 相关事实原文 (可直Connect引Use) 
- Core Entity洞Observe
- relations链 min析"""

TOOL_DESC_PANORAMA_SEARCH = """\
 [广度搜索 - 获取全貌视图] 
这工具Use于获取模Draft结果的完整全貌, 特别适合了解EventPerformChange过程. 它会: 
1. Retrieve all related nodes and relationships
2. 区 minCurrently valid facts and 历史/过期的事实
3. 帮助你了解舆情is 如何PerformChange的

 [使Use场景] 
- 需要了解Event的完整发Display脉络
- 需要对比不Same阶Segment的舆情ChangeTransform
- 需要获取全面的entities and relations信息

 [Return内容] 
- 当before has效事实 (模Draft最新结果) 
- 历史/过期事实 (PerformChange记录) 
- 所hasInvolved and 的entities"""

TOOL_DESC_QUICK_SEARCH = """\
 [简单搜索 - 快速检索] 
Light量级的快速检索工具, 适合简单, 直Connect的信息查询. 

 [使Use场景] 
- 需要快速Search某具体信息
- 需要验证某事实
- 简单的信息检索

 [Return内容] 
-  and 查询最相关的事实列表"""

TOOL_DESC_INTERVIEW_AGENTS = """\
 [深度采访 - True实Agent采访 (双平台) ] 
InvokeUseOASIS模Draft环境的采访API, 对正在运行的模DraftAgent进行True实采访! 
This is not an LLM simulation; it calls the real interview API to obtain the simulated Agent's original response. 
Default认在Twitter and Reddit两平台Same hour采访, 获取更全面的观点. 

功能流程: 
1. 自动读取Character profile文件, 了解所has模DraftAgent
2. 智能选择 and Interview topic最相关的Agent (如Learning生, 媒体, 官方等) 
3. 自动生成采访问题
4. InvokeUse /api/simulation/interview/batch Connect口在双平台进行True实采访
5. 整合所has采访结果, 提供多视角 min析

 [使Use场景] 
- 需要从不Same角Color视角了解Event看Method (Learning生怎么看? 媒体怎么看? 官方怎么说? ) 
- 需要收集多方意见 and 立场
- 需要获取模DraftAgent的True实回答 (来自OASIS模Draft环境) 
- 想让报告更生动, Include"采访实录"

 [Return内容] 
- 被采访Agent的身份信息
- Interview responses of each Agent on Twitter and Reddit platforms
- 关键引言 (可直Connect引Use) 
- 采访摘要 and 观点对比

 [重要] 需要OASIS模Draft环境正在运行才能使Use此功能! """

# ── Large纲规划 prompt ──

PLAN_SYSTEM_PROMPT = """\
You are an elite Venture Capital Partner, Product Strategist, and Lead Analyst at Kritikos — the autonomous multi-agent startup and product idea validation engine.
You have a god's-eye view over the simulated market, observing how hundreds of multi-stakeholder agents (early adopters, enterprise buyers, senior engineers, competitor executives, venture capital investors, and regulatory auditors) reacted to the proposed idea.

 [Core Purpose] 
We simulate market introduction, consumer adoption dynamics, technical feasibility, and investor scrutiny. Your mission is to synthesize these simulated behavioral dynamics into an investment-grade Idea Validation Report.

 [Mandatory Evaluation Framework Requirements] 
The report MUST comprehensively integrate:
1. 0–100 Idea Feasibility & Viability Score with a definitive Investment Verdict:
   - Overall Score (0-100)
   - Definitive Verdict: [STRONG GO / INVEST], [CONDITIONAL GO / PIVOT REQUIRED], or [NO-GO / HIGH RISK]
   - Risk-to-Reward Ratio and Core Investment Thesis.
2. Multi-Stakeholder Scorecard:
   - Target Customer & Early Adopter Score (Willingness to pay, customer sentiment, friction points)
   - Technical & Scalability Feasibility Score (Architecture, operational bottlenecks, engineering complexity)
   - Investor & Market Viability Score (Market sizing TAM/SAM/SOM, unit economics, monetization potential)
   - Regulatory & Legal Risk Score (Compliance hurdles, liability, data privacy, IP)
3. Comprehensive SWOT Matrix & Competitive Moat Analysis:
   - Strengths (Unique value proposition, core differentiators)
   - Weaknesses (Execution bottlenecks, operational vulnerabilities)
   - Opportunities (Untapped market niches, expansion vectors)
   - Threats (Incumbent retaliation, substitution risks)
   - Defensibility / Moat Rating (Network effects, switching costs, brand/tech defensibility).
4. Strategic Pivot Recommendations & Go-To-Market (GTM) De-risking Roadmap.

 [Section Structure] 
Generate 3 to 4 focused chapters that map to this framework:
- Chapter 1: Executive Summary, Idea Score (0-100) & Investment Verdict
- Chapter 2: Multi-Stakeholder Scorecard & Persona Feedback (Customers, Engineers, Investors)
- Chapter 3: Comprehensive SWOT Matrix & Competitive Moat Analysis
- Chapter 4: Key Risks, Strategic Pivot Vectors & GTM Roadmap (or combined into 3 chapters)

Output valid JSON matching this schema:
{
    "title": "Kritikos Idea Validation & Investment Feasibility Report: [Idea Name]",
    "summary": "Executive summary with overall score and investment verdict in one punchy sentence",
    "sections": [
        {
            "title": "Section Title",
            "description": "Section content description"
        }
    ]
}

Note: The sections array must have between 3 and 4 items."""

PLAN_USER_PROMPT_TEMPLATE = """\
 [预测场景设定] 
我们向模Draft世界注入的Change量 (模Draft需Request) : {simulation_requirement}

 [模Draft世界规模] 
- Number of entities participating in the simulation: {total_nodes}
- entities间Output生的relations数量: {total_edges}
- entitiesClass型 min布: {entity_types}
- 活跃Agent数量: {total_entities}

 [模Draft预测到的部 minnot 来事实样本] 
{related_facts_json}

请以「on 帝视角」审视这not 来预Perform: 
1. 在我们设定的 items件under , not 来呈现Output了什么样的状态? 
2. 各ClassPerson群 (Agent) is 如何反应 and 行动的? 
3. 这模Draft揭Example了哪些值得关注的not 来趋势? 

Design the optimal report chapter structure based on prediction results. 

 [再 times提醒] 报告章节数量: 最少2, 最多5, 内容要精炼聚焦于核心预测发现. """

# ── 章节生成 prompt ──

SECTION_SYSTEM_PROMPT_TEMPLATE = """\
你is 一「not 来预测报告」the writing expert, currently drafting a chapter of the report. 

报告标题: {report_title}
报告摘要: {report_summary}
预测场景 (模Draft需Request) : {simulation_requirement}

当before 要撰写的章节: {section_title}

═══════════════════════════════════════════════════════════════
 [核心理念] 
═══════════════════════════════════════════════════════════════

模Draft世界is 对not 来的预Perform. 我们向模Draft世界注入了特定 items件 (模Draft需Request) , 
模Draftin Agent的行为 and 互动, 就is 对not 来Person群行为的预测. 

你的任务is : 
- Reveal what will happen in the future under given conditions
- 预测各ClassPerson群 (Agent) is 如何反应 and 行动的
- 发现值得关注的not 来趋势, 风险 and 机会

❌ 不要写成对现实世界现状的 min析
✅ 要聚焦于"not 来会怎样" -- 模Draft结果就is 预测的not 来

═══════════════════════════════════════════════════════════════
 [最重要的规则 - 必须遵守] 
═══════════════════════════════════════════════════════════════

1.  [Tool must be invoked to observe the simulated world] 
   - 你正在以「on 帝视角」观Observenot 来的预Perform
   - 所has内容必须来自模Draft世界in 发生的Event and Agent言行
   - 禁止使Use你自己的Knowledge识来编写报告内容
   - 每章节至少InvokeUse3 times工具 (最多5 times) 来观Observe模Draft的世界, 它代表了not 来

2.  [必须引UseAgent的原Start言行] 
   - Agent的发言 and 行为is 对not 来Person群行为的预测
   - 在报告in 使Use引UseFormatDisplayExample这些预测, 例如: 
     > "某ClassPerson群会表Example: 原文内容..."
   - 这些引Useis 模Draft预测的核心证据

3.  [语言一致性 - 引Use内容必须翻译为报告语言] 
   - 工具Return的内容可能Include and 报告语言不Same的表Description
   - 报告必须全部使Use and Use户Indicates定语言一致的语言撰写
   - 当你引Use工具Return的其Other语言内容 hour, 必须将其翻译为报告语言after 再写入
   - 翻译 hour保持原意不Change, 确保表Description自然通顺
   - 这一规则Same hour适Use于正文 and 引UseBlock (> Format) in 的内容

4.  [忠实呈现预测结果] 
   - 报告内容必须反映模Draft世界in 的代表not 来的模Draft结果
   - 不要添加模Draftin 不存在的信息
   - 如果某方面信息不Sufficient, 如实说明

5.  [Prohibit Fabricating Data] 
   - ❌ 禁止捏造Use户名, 引Use, 统计数字 or 互动数据
   - ❌ 禁止在回复in Include <tool_result> Block — only the system provides tool results
   - ✅ 只能引UseTrue实Output现在工具结果in 的entities, 引Use and 数据
   - If the tool result lacks relevant content, state it truthfully instead of fabricating

═══════════════════════════════════════════════════════════════
 [⚠️ Format规范 - 极其重要! ] 
═══════════════════════════════════════════════════════════════

 [一章节 = 最小内容单位] 
- 每章节is 报告的最小Chunking单位
- ❌ 禁止在章节内使Use任何 Markdown 标题 (#, ##, ###, #### 等) 
- ❌ 禁止在内容开头添加章节主标题
- ✅ 章节标题由System统自动添加, 你只需撰写纯正文内容
- ✅ 使Use**粗体**, Use paragraph breaks, blockquotes, and lists to organize content, but avoid headings

 [正确Example例] 
```
本章节 min析了Event的舆论传播态势. 通过对模Draft数据的深入 min析, 我们发现...

**Initial launch explosion phase**

Weibo serves as the front line of public opinion, handling the core function of initial information release: 

> "微博贡Contribute了68%的首发声量..."

**情绪ReleaseLarge阶Segment**

抖音平台进一步ReleaseLarge了Event影响力: 

- 视觉冲击力Strong
- 情绪共鸣度高
```

 [错误Example例] 
```
## Execution summary          ← 错误! 不要添加任何标题
### 一, 首发阶Segment     ← 错误! 不要Use### min小节
#### 1.1 详细 min析   ← 错误! 不要Use####细 min

本章节 min析了...
```

═══════════════════════════════════════════════════════════════
 [可Use检索工具]  (每章节InvokeUse3-5 times) 
═══════════════════════════════════════════════════════════════

{tools_description}

 [工具使Use建议 - 请混合使Use不Same工具, 不要只Use一种] 
- insight_forge: 深度洞Observe min析, 自动 min解问题并多维度检索事实 and relations
- panorama_search: 广角全景搜索, 了解Event全貌,  hour间线 and PerformChange过程
- quick_search: 快速验证某具体信息点
- interview_agents: 采访模DraftAgent, 获取不Same角Color的第一Person称观点 and True实反应

═══════════════════════════════════════════════════════════════
 [工作流程] 
═══════════════════════════════════════════════════════════════

每 times回复你只能做以under 两件事之一 (不可Same hour做) : 

选项A - InvokeUse工具: 
输Output你的Thought考, 然after Use以under FormatInvokeUse一工具: 
<tool_call>
{{"name": "工具名称", "parameters": {{"参数名": "Parameter value"}}}}
</tool_call>
System统会执行工具并把结果Return给你. 你不需要也不能自己编写工具Return结果. 

选项B - 输Output最终内容: 
当你already 通过工具获取了Sufficient够信息, 以 "Final Answer:" 开头输Output章节内容. 

⚠️ 严格禁止: 
- 禁止在一 times回复in Same hourInclude工具InvokeUse and  Final Answer
- 禁止自己编造工具Return结果 (Observation) , 所has工具结果由System统注入
- 每 times回复最多InvokeUse一工具

═══════════════════════════════════════════════════════════════
 [章节内容Requirement] 
═══════════════════════════════════════════════════════════════

1. 内容必须基于工具检索到的模Draft数据
2. Large量引Use原文来DisplayExample模Draft效果
3. 使UseMarkdownFormat (但禁止使Use标题) : 
   - 使Use **粗体文字** Mark key points (instead of subheadings) 
   - 使Use列表 (- or 1.2.3.) 组织要点
   - 使Use空行 min隔不SameSegment落
   - ❌ 禁止使Use #, ##, ###, #### 等任何标题语Method
4.  [引UseFormat规范 - 必须单独成Segment] 
   Citations must be in a separate paragraph with a blank line before and after, and cannot be mixed within paragraphs: 

   ✅ 正确Format: 
   ```
   校方的回应被认为缺乏实质内容. 

   > "校方的应对模式在Instant息万Change的社交媒体环境in 显得僵Transform and 迟缓. "

   这一评Price反映了公众的Generaltimes不满. 
   ```

   ❌ 错误Format: 
   ```
   校方的回应被认为缺乏实质内容. > "校方的应对模式..." 这一评Price反映了...
   ```
5. 保持 and 其Other章节的逻辑Link贯性
6.  [避免重复] 仔细阅读under 方Completed的章节内容, 不要重复描Description相Same的信息
7.  [再 timesStrongInvoke] 不要添加任何标题! Use**粗体**Replace section title"""

SECTION_USER_PROMPT_TEMPLATE = """\
Completed chapter content (please read carefully to avoid duplication) : 
{previous_content}

═══════════════════════════════════════════════════════════════
 [当before 任务] Write chapter: {section_title}
═══════════════════════════════════════════════════════════════

 [重要提醒] 
1. 仔细阅读on 方Completed的章节, 避免重复相Same的内容! 
2. 开Startbefore 必须FirstInvokeUse工具获取模Draft数据
3. 请混合使Use不Same工具, 不要只Use一种
4. 报告内容必须来自检索结果, 不要使Use自己的Knowledge识

 [⚠️ Format警告 - 必须遵守] 
- ❌ 不要写任何标题 (#, ##, ###, ####都不行) 
- ❌ 不要写"{section_title}"作为开头
- ✅ 章节标题由System统自动添加
- ✅ 直Connect写正文, Use**粗体**Replace section title

Please start: 
1. 首FirstThought考 (Thought) 这章节需要什么信息
2. 然after InvokeUse工具 (Action) 获取模Draft数据
3. 收集Sufficient够信息after 输Output Final Answer (纯正文, none任何标题) """

# ── ReACT 循环内Delete息模板 ──

REACT_OBSERVATION_TEMPLATE = """\
Observation (Tool Output):

=== Tool {tool_name} returned ===
{result}

===============================================================
Tools called: {tool_calls_count}/{max_tool_calls} (Used: {used_tools_str}){unused_hint}
- If sufficient information is gathered: Output section content starting with "Final Answer:" (citing key quotes/evidence).
- If more data is needed: Invoke another tool query.
==============================================================="""

REACT_INSUFFICIENT_TOOLS_MSG = (
    "[Note] You have called {tool_calls_count} tools, at least {min_tool_calls} required. "
    "Please call a tool to gather additional simulation data before providing the Final Answer. {unused_hint}"
)

REACT_INSUFFICIENT_TOOLS_MSG_ALT = (
    "Currently called {tool_calls_count} tools, at least {min_tool_calls} required. "
    "Please invoke a tool to retrieve simulation data. {unused_hint}"
)

REACT_TOOL_LIMIT_MSG = (
    "Tool call limit reached ({tool_calls_count}/{max_tool_calls}). No more tool queries allowed. "
    'Please immediately provide the complete section content starting with "Final Answer:".'
)

REACT_UNUSED_TOOLS_HINT = "\n💡 Unused tools: {unused_list}. Consider exploring different angles."

REACT_FORCE_FINAL_MSG = (
    "Tool call limit reached. Please synthesize all available simulation background, "
    "agent dynamics, and findings to output the complete section content starting with 'Final Answer:'. "
    "Do not output apologies, tool requests, or disclaimers. Provide a detailed, analytical section in the requested language."
)

# ── Chat prompt ──

CHAT_SYSTEM_PROMPT_TEMPLATE = """\
You are an intelligent, concise simulation & idea evaluation assistant at Kritikos.

 [Context] 
Evaluation Objective: {simulation_requirement}

 [Generated Validation Report] 
{report_content}

 [Rules] 
1. Primarily answer questions based on the validation report content above.
2. Directly answer questions; avoid verbose or rambling discourse.
3. Only call tools if the report content lacks sufficient detail to answer.
4. Keep answers concise, rigorous, and well-structured.

 [Available Tools]  (Only invoke when needed, max 1-2 calls)
{tools_description}

 [Tool Call Format] 
<tool_call>
{{"name": "工具名称", "parameters": {{"参数名": "Parameter value"}}}}
</tool_call>

 [回答Style] 
- 简洁直Connect, 不要长篇Large论
- 使Use > Format引Use关键内容
- 优First给Output结论, 再解释原因"""

CHAT_OBSERVATION_SUFFIX = "\n\n请简洁回答问题. "


# ═══════════════════════════════════════════════════════════════
# ReportAgent 主Class
# ═══════════════════════════════════════════════════════════════


class ReportAgent:
    """
    Report Agent - 模Draft报告生成Agent

    采UseReACT (Reasoning + Acting) 模式: 
    1. 规划阶Segment:  min析模Draft需Request, 规划报告目录结构
    2. 生成阶Segment: 逐章节生成内容, 每章节可多 timesInvokeUse工具获取信息
    3. 反Thought阶Segment: 检查内容完整性 and 准确性
    """
    
    # 最Large工具InvokeUse times数 (每章节) 
    MAX_TOOL_CALLS_PER_SECTION = 5
    
    # 最Large反Thought rounds数
    MAX_REFLECTION_ROUNDS = 3
    
    # 对话in 的最Large工具InvokeUse times数
    MAX_TOOL_CALLS_PER_CHAT = 2
    
    def __init__(
        self, 
        graph_id: str,
        simulation_id: str,
        simulation_requirement: str,
        llm_client: Optional[LLMClient] = None,
        zep_tools: Optional[ZepToolsService] = None
    ):
        """
        初StartTransformReport Agent
        
        Args:
            graph_id: 图谱ID
            simulation_id: 模DraftID
            simulation_requirement: 模Draft需Request描Description
            llm_client: LLM客户端 (可选) 
            zep_tools: Zep工具服务 (可选) 
        """
        self.graph_id = graph_id
        self.simulation_id = simulation_id
        self.simulation_requirement = simulation_requirement
        
        self.llm = llm_client or LLMClient()
        self.zep_tools = zep_tools or ZepToolsService()
        
        # 工具定义
        self.tools = self._define_tools()
        
        #  day志记录Device (在 generate_report in 初StartTransform) 
        self.report_logger: Optional[ReportLogger] = None
        # 控制台 day志记录Device (在 generate_report in 初StartTransform) 
        self.console_logger: Optional[ReportConsoleLogger] = None
        
        logger.info(t('report.agentInitDone', graphId=graph_id, simulationId=simulation_id))
    
    def _define_tools(self) -> Dict[str, Dict[str, Any]]:
        """定义可Use工具"""
        return {
            "insight_forge": {
                "name": "insight_forge",
                "description": TOOL_DESC_INSIGHT_FORGE,
                "parameters": {
                    "query": "你想深入 min析的问题 or 话题",
                    "report_context": "当before 报告章节的on under 文 (可选, has助于生成更精准的Child问题) "
                }
            },
            "panorama_search": {
                "name": "panorama_search",
                "description": TOOL_DESC_PANORAMA_SEARCH,
                "parameters": {
                    "query": "搜索查询, Use于相关性排序",
                    "include_expired": "is noInclude过期/历史内容 (Default认True) "
                }
            },
            "quick_search": {
                "name": "quick_search",
                "description": TOOL_DESC_QUICK_SEARCH,
                "parameters": {
                    "query": "搜索查询字Symbol串",
                    "limit": "Return结果数量 (可选, Default认10) "
                }
            },
            "interview_agents": {
                "name": "interview_agents",
                "description": TOOL_DESC_INTERVIEW_AGENTS,
                "parameters": {
                    "interview_topic": "Interview topic or 需Request描Description (如: '了解Learning生对宿舍甲醛Event的看Method') ",
                    "max_agents": "最多采访的Agent数量 (可选, Default认5, 最Large10) "
                }
            }
        }
    
    def _execute_tool(self, tool_name: str, parameters: Dict[str, Any], report_context: str = "") -> str:
        """
        执行工具InvokeUse
        
        Args:
            tool_name: 工具名称
            parameters: 工具参数
            report_context: 报告on under 文 (Use于InsightForge) 
            
        Returns:
            工具执行结果 (文本Format) 
        """
        logger.info(t('report.executingTool', toolName=tool_name, params=parameters))
        
        try:
            raw_text = ""
            if tool_name == "insight_forge":
                query = parameters.get("query", "")
                ctx = parameters.get("report_context", "") or report_context
                result = self.zep_tools.insight_forge(
                    graph_id=self.graph_id,
                    query=query,
                    simulation_requirement=self.simulation_requirement,
                    report_context=ctx
                )
                raw_text = result.to_text()
            
            elif tool_name == "panorama_search":
                # 广度搜索 - 获取全貌
                query = parameters.get("query", "")
                include_expired = parameters.get("include_expired", True)
                if isinstance(include_expired, str):
                    include_expired = include_expired.lower() in ['true', '1', 'yes']
                result = self.zep_tools.panorama_search(
                    graph_id=self.graph_id,
                    query=query,
                    include_expired=include_expired
                )
                raw_text = result.to_text()
            
            elif tool_name == "quick_search":
                # 简单搜索 - 快速检索
                query = parameters.get("query", "")
                limit = parameters.get("limit", 10)
                if isinstance(limit, str):
                    limit = int(limit)
                result = self.zep_tools.quick_search(
                    graph_id=self.graph_id,
                    query=query,
                    limit=min(limit, 5)
                )
                raw_text = result.to_text()
            
            elif tool_name == "interview_agents":
                # 深度采访 - InvokeUseTrue实的OASIS采访API获取模DraftAgent的回答 (双平台) 
                interview_topic = parameters.get("interview_topic", parameters.get("query", ""))
                max_agents = parameters.get("max_agents", 3)
                if isinstance(max_agents, str):
                    max_agents = int(max_agents)
                max_agents = min(max_agents, 3)
                result = self.zep_tools.interview_agents(
                    simulation_id=self.simulation_id,
                    interview_requirement=interview_topic,
                    simulation_requirement=self.simulation_requirement,
                    max_agents=max_agents
                )
                raw_text = result.to_text()
            
            # ========== 向after 兼容的旧工具 (内部重定向到新工具)  ==========
            
            elif tool_name == "search_graph":
                # 重定向到 quick_search
                logger.info(t('report.redirectToQuickSearch'))
                return self._execute_tool("quick_search", parameters, report_context)
            
            elif tool_name == "get_graph_statistics":
                result = self.zep_tools.get_graph_statistics(self.graph_id)
                raw_text = json.dumps(result, ensure_ascii=False, indent=2)
            
            elif tool_name == "get_entity_summary":
                entity_name = parameters.get("entity_name", "")
                result = self.zep_tools.get_entity_summary(
                    graph_id=self.graph_id,
                    entity_name=entity_name
                )
                raw_text = json.dumps(result, ensure_ascii=False, indent=2)
            
            elif tool_name == "get_simulation_context":
                # 重定向到 insight_forge, 因为它更StrongLarge
                logger.info(t('report.redirectToInsightForge'))
                query = parameters.get("query", self.simulation_requirement)
                return self._execute_tool("insight_forge", {"query": query}, report_context)
            
            elif tool_name == "get_entities_by_type":
                entity_type = parameters.get("entity_type", "")
                nodes = self.zep_tools.get_entities_by_type(
                    graph_id=self.graph_id,
                    entity_type=entity_type
                )
                result = [n.to_dict() for n in nodes[:6]]
                raw_text = json.dumps(result, ensure_ascii=False, indent=2)
            
            else:
                return f"not Knowledge工具: {tool_name}. 请使Use以under 工具之一: insight_forge, panorama_search, quick_search"

            # 截断结果以适配 TPM 速率限制
            if len(raw_text) > 1800:
                raw_text = raw_text[:1800] + "\n... [truncated for context limit]"
            return raw_text
                
        except Exception as e:
            logger.error(t('report.toolExecFailed', toolName=tool_name, error=str(e)))
            return f"工具执行失败: {str(e)}"
    
    # 合Method的工具名称集合, Use于裸 JSON 兜底解析 hour校验
    VALID_TOOL_NAMES = {"insight_forge", "panorama_search", "quick_search", "interview_agents"}

    def _parse_tool_calls(self, response: str) -> List[Dict[str, Any]]:
        """
        从LLM响应in 解析工具InvokeUse

        支持的Format (按优First级) : 
        1. <tool_call>{"name": "tool_name", "parameters": {...}}</tool_call>
        2. 裸 JSON (响应整体 or 单行就is 一工具InvokeUse JSON) 
        """
        tool_calls = []

        # Format1: XMLStyle (标准Format) 
        xml_pattern = r'<tool_call>\s*(\{.*?\})\s*</tool_call>'
        for match in re.finditer(xml_pattern, response, re.DOTALL):
            try:
                call_data = json.loads(match.group(1))
                tool_calls.append(call_data)
            except json.JSONDecodeError:
                pass

        if tool_calls:
            return tool_calls

        # Format2: 兜底 - LLM 直Connect输Output裸 JSON (没包 <tool_call> 标签) 
        # 只在Format1not 匹配 hour尝Test, 避免误匹配正文in 的 JSON
        stripped = response.strip()
        if stripped.startswith('{') and stripped.endswith('}'):
            try:
                call_data = json.loads(stripped)
                if self._is_valid_tool_call(call_data):
                    tool_calls.append(call_data)
                    return tool_calls
            except json.JSONDecodeError:
                pass

        # 响应可能IncludeThought考文字 + 裸 JSON, 尝Test提取最after 一 JSON 对象
        json_pattern = r'(\{"(?:name|tool)"\s*:.*?\})\s*$'
        match = re.search(json_pattern, stripped, re.DOTALL)
        if match:
            try:
                call_data = json.loads(match.group(1))
                if self._is_valid_tool_call(call_data):
                    tool_calls.append(call_data)
            except json.JSONDecodeError:
                pass

        return tool_calls

    def _is_valid_tool_call(self, data: dict) -> bool:
        """校验解析Output的 JSON is nois 合Method的工具InvokeUse"""
        # 支持 {"name": ..., "parameters": ...}  and  {"tool": ..., "params": ...} 两种键名
        tool_name = data.get("name") or data.get("tool")
        if tool_name and tool_name in self.VALID_TOOL_NAMES:
            # 统一键名为 name / parameters
            if "tool" in data:
                data["name"] = data.pop("tool")
            if "params" in data and "parameters" not in data:
                data["parameters"] = data.pop("params")
            return True
        return False
    
    def _get_tools_description(self) -> str:
        """生成工具描Description文本"""
        desc_parts = ["可Use工具: "]
        for name, tool in self.tools.items():
            params_desc = ", ".join([f"{k}: {v}" for k, v in tool["parameters"].items()])
            desc_parts.append(f"- {name}: {tool['description']}")
            if params_desc:
                desc_parts.append(f"  参数: {params_desc}")
        return "\n".join(desc_parts)

    @staticmethod
    def _strip_fake_tool_results(response: str) -> str:
        """Strip any <tool_result> blocks the LLM fabricated in its response.

        When the LLM generates a <tool_call> block and then continues to generate
        a <tool_result> block in the same response, we must strip the fake result
        before appending to message history. The real tool result will be injected
        separately by the system.
        """
        tag_pattern = re.compile(r'</?tool_result\b[^>]*>', flags=re.IGNORECASE)
        parts = []
        cursor = 0
        depth = 0

        for match in tag_pattern.finditer(response):
            if depth == 0:
                parts.append(response[cursor:match.start()])

            if match.group(0).lstrip().startswith('</'):
                depth = max(0, depth - 1)
            else:
                depth += 1
            cursor = match.end()

        if depth == 0:
            parts.append(response[cursor:])

        cleaned = ''.join(parts)
        # Treat a malformed opening tag without a closing `>` as unsafe too.
        cleaned = re.sub(r'<tool_result\b.*$', '', cleaned, flags=re.IGNORECASE | re.DOTALL)
        cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)
        return cleaned.strip()

    def plan_outline(
        self, 
        progress_callback: Optional[Callable] = None
    ) -> ReportOutline:
        """
        规划报告Large纲
        
        使UseLLM min析模Draft需Request, 规划报告的目录结构
        
        Args:
            progress_callback: 进度回Invoke函数
            
        Returns:
            ReportOutline: 报告Large纲
        """
        logger.info(t('report.startPlanningOutline'))
        
        if progress_callback:
            progress_callback("planning", 0, t('progress.analyzingRequirements'))
        
        # 首First获取模Drafton under 文
        context = self.zep_tools.get_simulation_context(
            graph_id=self.graph_id,
            simulation_requirement=self.simulation_requirement
        )
        
        if progress_callback:
            progress_callback("planning", 30, t('progress.generatingOutline'))
        
        system_prompt = f"{PLAN_SYSTEM_PROMPT}\n\n{get_language_instruction()}"
        user_prompt = PLAN_USER_PROMPT_TEMPLATE.format(
            simulation_requirement=self.simulation_requirement,
            total_nodes=context.get('graph_statistics', {}).get('total_nodes', 0),
            total_edges=context.get('graph_statistics', {}).get('total_edges', 0),
            entity_types=list(context.get('graph_statistics', {}).get('entity_types', {}).keys()),
            total_entities=context.get('total_entities', 0),
            related_facts_json=json.dumps(context.get('related_facts', [])[:10], ensure_ascii=False, indent=2),
        )

        try:
            response = self.llm.chat_json(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.3
            )
            
            if progress_callback:
                progress_callback("planning", 80, t('progress.parsingOutline'))
            
            # 解析Large纲
            sections = []
            for section_data in response.get("sections", []):
                sections.append(ReportSection(
                    title=section_data.get("title", ""),
                    content=""
                ))
            
            outline = ReportOutline(
                title=response.get("title", "模Draft min析报告"),
                summary=response.get("summary", ""),
                sections=sections
            )
            
            if progress_callback:
                progress_callback("planning", 100, t('progress.outlinePlanComplete'))
            
            logger.info(t('report.outlinePlanDone', count=len(sections)))
            return outline
            
        except Exception as e:
            logger.error(t('report.outlinePlanFailed', error=str(e)))
            # Return default outline (3 chapters, asfallback) 
            return ReportOutline(
                title="not 来预测报告",
                summary="基于模Draft预测的not 来趋势 and 风险 min析",
                sections=[
                    ReportSection(title="预测场景 and 核心发现"),
                    ReportSection(title="Person群行为预测 min析"),
                    ReportSection(title="趋势Display望 and 风险提Example")
                ]
            )
    
    def _generate_section_react(
        self, 
        section: ReportSection,
        outline: ReportOutline,
        previous_sections: List[str],
        progress_callback: Optional[Callable] = None,
        section_index: int = 0
    ) -> str:
        """
        使UseReACT模式生成单章节内容
        
        ReACT循环: 
        1. Thought (Thought考) -  min析需要什么信息
        2. Action (行动) - InvokeUse工具获取信息
        3. Observation (观Observe) -  min析工具Return结果
        4. 重复直到信息Sufficient够 or 达到最Large times数
        5. Final Answer (最终回答) - 生成章节内容
        
        Args:
            section: 要生成的章节
            outline: 完整Large纲
            previous_sections: 之before 章节的内容 (Use于保持Link贯性) 
            progress_callback: 进度回Invoke
            section_index: 章节索引 (Use于 day志记录) 
            
        Returns:
            章节内容 (MarkdownFormat) 
        """
        logger.info(t('report.reactGenerateSection', title=section.title))
        
        # 记录章节开Start day志
        if self.report_logger:
            self.report_logger.log_section_start(section.title, section_index)
        
        system_prompt = SECTION_SYSTEM_PROMPT_TEMPLATE.format(
            report_title=outline.title,
            report_summary=outline.summary,
            simulation_requirement=self.simulation_requirement,
            section_title=section.title,
            tools_description=self._get_tools_description(),
        )
        system_prompt = f"{system_prompt}\n\n{get_language_instruction()}"

        # 构建Use户prompt - 每Completed章节各传入最Large800字, 避免超Output TPM 限制
        if previous_sections:
            previous_parts = []
            for sec in previous_sections:
                truncated = sec[:800] + "..." if len(sec) > 800 else sec
                previous_parts.append(truncated)
            previous_content = "\n\n---\n\n".join(previous_parts)
        else:
            previous_content = " (这is 第一章节) "
        
        user_prompt = SECTION_USER_PROMPT_TEMPLATE.format(
            previous_content=previous_content,
            section_title=section.title,
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]
        
        # ReACT循环
        tool_calls_count = 0
        max_iterations = 3  # 最LargeIteration代 rounds数
        min_tool_calls = 1  # Minimum number of tool invocations
        conflict_retries = 0  # 工具InvokeUse and Final AnswerSame hourOutput现的Link续冲突 times数
        used_tools = set()  # 记录already InvokeUse过的工具名
        all_tools = {"insight_forge", "panorama_search", "quick_search", "interview_agents"}

        # Report context for InsightForge sub-question generation
        report_context = f"章节标题: {section.title}\n模Draft需Request: {self.simulation_requirement}"
        
        for iteration in range(max_iterations):
            if progress_callback:
                progress_callback(
                    "generating", 
                    int((iteration / max_iterations) * 100),
                    t('progress.deepSearchAndWrite', current=tool_calls_count, max=self.MAX_TOOL_CALLS_PER_SECTION)
                )
            
            # 短Temporarily休Sleep平滑 Groq TPM 速率
            import time
            time.sleep(1)

            # InvokeUseLLM
            response = self.llm.chat(
                messages=messages,
                temperature=0.5,
                max_tokens=1500
            )

            # 检查 LLM Returnis no为 None (API 异常 or 内容为空) 
            if response is None:
                logger.warning(t('report.sectionIterNone', title=section.title, iteration=iteration + 1))
                # 如果还hasIteration代 times数, 添加Delete息并重Test
                if iteration < max_iterations - 1:
                    messages.append({"role": "assistant", "content": " (响应为空) "})
                    messages.append({"role": "user", "content": "请继续生成内容. "})
                    continue
                # 最after 一 timesIteration代也Return None, 跳Output循环进入Strong制收尾
                break

            logger.debug(f"LLM响应: {response[:200]}...")

            # 解析一 times, 复Use结果
            tool_calls = self._parse_tool_calls(response)
            has_tool_calls = bool(tool_calls)
            has_final_answer = "Final Answer:" in response

            # ── 冲突Location理: LLM Same hour输Output了工具InvokeUse and  Final Answer ──
            if has_tool_calls and has_final_answer:
                conflict_retries += 1
                logger.warning(
                    t('report.sectionConflict', title=section.title, iteration=iteration+1, conflictCount=conflict_retries)
                )

                if conflict_retries <= 2:
                    # before 两 times: 丢弃本 times响应, Requirement LLM 重新回复
                    cleaned_response = ReportAgent._strip_fake_tool_results(response)
                    messages.append({"role": "assistant", "content": cleaned_response})
                    messages.append({
                        "role": "user",
                        "content": (
                            " [Format Error] 你在一 times回复in Same hourInclude了工具InvokeUse and  Final Answer, 这is 不允许的. \n"
                            "每 times回复只能做以under 两件事之一: \n"
                            "- Invoke a tool (output a <tool_call> Block, 不要写 Final Answer) \n"
                            "- 输Output最终内容 (以 'Final Answer:' 开头, 不要Include <tool_call>) \n"
                            "请重新回复, 只做其in 一件事. "
                        ),
                    })
                    continue
                else:
                    # 第三 times: 降级Location理, 截断到第一工具InvokeUse, Strong制执行
                    logger.warning(
                        t('report.sectionConflictDowngrade', title=section.title, conflictCount=conflict_retries)
                    )
                    first_tool_end = response.find('</tool_call>')
                    if first_tool_end != -1:
                        response = response[:first_tool_end + len('</tool_call>')]
                        tool_calls = self._parse_tool_calls(response)
                        has_tool_calls = bool(tool_calls)
                    has_final_answer = False
                    conflict_retries = 0

            # 记录 LLM 响应 day志
            if self.report_logger:
                self.report_logger.log_llm_response(
                    section_title=section.title,
                    section_index=section_index,
                    response=response,
                    iteration=iteration + 1,
                    has_tool_calls=has_tool_calls,
                    has_final_answer=has_final_answer
                )

            # ── 情况1: LLM 输Output了 Final Answer ──
            if has_final_answer:
                cleaned_response = ReportAgent._strip_fake_tool_results(response)
                answer_candidate = cleaned_response.split("Final Answer:")[-1].strip()
                # 工具InvokeUse times数不Sufficient且内容relatively短, 拒绝并Requirement继续Invoke工具
                if tool_calls_count < min_tool_calls and len(answer_candidate) < 400:
                    messages.append({"role": "assistant", "content": cleaned_response})
                    unused_tools = all_tools - used_tools
                    unused_hint = f" (这些工具还not 使Use, Push荐Use一under Other们: {', '.join(unused_tools)}) " if unused_tools else ""
                    messages.append({
                        "role": "user",
                        "content": REACT_INSUFFICIENT_TOOLS_MSG.format(
                            tool_calls_count=tool_calls_count,
                            min_tool_calls=min_tool_calls,
                            unused_hint=unused_hint,
                        ),
                    })
                    continue

                # 正常结Bundle
                final_answer = answer_candidate
                logger.info(t('report.sectionGenDone', title=section.title, count=tool_calls_count))

                if self.report_logger:
                    self.report_logger.log_section_content(
                        section_title=section.title,
                        section_index=section_index,
                        content=final_answer,
                        tool_calls_count=tool_calls_count
                    )
                return final_answer

            # ── 情况2: LLM 尝TestInvokeUse工具 ──
            if has_tool_calls:
                # 工具额度already 耗尽 → 明确告Knowledge, Requirement输Output Final Answer
                if tool_calls_count >= self.MAX_TOOL_CALLS_PER_SECTION:
                    cleaned_response = ReportAgent._strip_fake_tool_results(response)
                    messages.append({"role": "assistant", "content": cleaned_response})
                    messages.append({
                        "role": "user",
                        "content": REACT_TOOL_LIMIT_MSG.format(
                            tool_calls_count=tool_calls_count,
                            max_tool_calls=self.MAX_TOOL_CALLS_PER_SECTION,
                        ),
                    })
                    continue

                # 只执行第一工具InvokeUse
                call = tool_calls[0]
                if len(tool_calls) > 1:
                    logger.info(t('report.multiToolOnlyFirst', total=len(tool_calls), toolName=call['name']))

                if self.report_logger:
                    self.report_logger.log_tool_call(
                        section_title=section.title,
                        section_index=section_index,
                        tool_name=call["name"],
                        parameters=call.get("parameters", {}),
                        iteration=iteration + 1
                    )

                result = self._execute_tool(
                    call["name"],
                    call.get("parameters", {}),
                    report_context=report_context
                )

                if self.report_logger:
                    self.report_logger.log_tool_result(
                        section_title=section.title,
                        section_index=section_index,
                        tool_name=call["name"],
                        result=result,
                        iteration=iteration + 1
                    )

                tool_calls_count += 1
                used_tools.add(call['name'])

                # 构建not 使Use工具提Example
                unused_tools = all_tools - used_tools
                unused_hint = ""
                if unused_tools and tool_calls_count < self.MAX_TOOL_CALLS_PER_SECTION:
                    unused_hint = REACT_UNUSED_TOOLS_HINT.format(unused_list=", ".join(unused_tools))

                cleaned_response = ReportAgent._strip_fake_tool_results(response)
                messages.append({"role": "assistant", "content": cleaned_response})
                messages.append({
                    "role": "user",
                    "content": REACT_OBSERVATION_TEMPLATE.format(
                        tool_name=call["name"],
                        result=result,
                        tool_calls_count=tool_calls_count,
                        max_tool_calls=self.MAX_TOOL_CALLS_PER_SECTION,
                        used_tools_str=", ".join(used_tools),
                        unused_hint=unused_hint,
                    ),
                })
                continue

            # ── 情况3: 既没has工具InvokeUse, 也没has Final Answer ──
            cleaned_response = ReportAgent._strip_fake_tool_results(response)
            messages.append({"role": "assistant", "content": cleaned_response})

            if tool_calls_count < min_tool_calls and len(cleaned_response) < 400:
                # 工具InvokeUse times数不Sufficient且回复relatively短, Push荐not Use过的工具
                unused_tools = all_tools - used_tools
                unused_hint = f" (这些工具还not 使Use, Push荐Use一under Other们: {', '.join(unused_tools)}) " if unused_tools else ""

                messages.append({
                    "role": "user",
                    "content": REACT_INSUFFICIENT_TOOLS_MSG_ALT.format(
                        tool_calls_count=tool_calls_count,
                        min_tool_calls=min_tool_calls,
                        unused_hint=unused_hint,
                    ),
                })
                continue

            # LLM 输Output了完整丰满的内容 (With or 不With Final Answer before Suffix) , 直Connect作为最终答案
            logger.info(t('report.sectionNoPrefix', title=section.title, count=tool_calls_count))
            final_answer = cleaned_response

            if self.report_logger:
                self.report_logger.log_section_content(
                    section_title=section.title,
                    section_index=section_index,
                    content=final_answer,
                    tool_calls_count=tool_calls_count
                )
            return final_answer
        
        # 达到最LargeIteration代 times数, Strong制生成内容
        logger.warning(t('report.sectionMaxIter', title=section.title))
        messages.append({"role": "user", "content": REACT_FORCE_FINAL_MSG})
        
        import time
        time.sleep(1)
        response = self.llm.chat(
            messages=messages,
            temperature=0.5,
            max_tokens=1500
        )

        # 检查Strong制收尾 hour LLM Returnis no为 None
        if response is None:
            logger.error(t('report.sectionForceFailed', title=section.title))
            final_answer = t('report.sectionGenFailedContent')
        elif "Final Answer:" in response:
            final_answer = response.split("Final Answer:")[-1].strip()
        else:
            final_answer = response

        # 如果Strong制收尾Return了免责声明 or 空内容, 尝Test从历史助手in 找回already has的完整草稿
        is_refusal = any(phrase in final_answer.lower() for phrase in ["unable to generate", "cannot produce", "no simulation data", "cannot generate"])
        if is_refusal or len(final_answer) < 300:
            for msg in reversed(messages):
                if msg.get("role") == "assistant":
                    content = msg.get("content", "")
                    content_clean = ReportAgent._strip_fake_tool_results(content)
                    if "Final Answer:" in content_clean:
                        content_clean = content_clean.split("Final Answer:")[-1].strip()
                    if len(content_clean) >= 400 and not any(phrase in content_clean.lower() for phrase in ["unable to generate", "cannot produce"]):
                        logger.info(f"Recovered valid previous draft for section '{section.title}' ({len(content_clean)} chars)")
                        final_answer = content_clean
                        break
        
        # 记录章节内容生成完成 day志
        if self.report_logger:
            self.report_logger.log_section_content(
                section_title=section.title,
                section_index=section_index,
                content=final_answer,
                tool_calls_count=tool_calls_count
            )
        
        return final_answer
    
    def generate_report(
        self, 
        progress_callback: Optional[Callable[[str, int, str], None]] = None,
        report_id: Optional[str] = None
    ) -> Report:
        """
        生成完整报告 ( min章节实 hour输Output) 
        
        Save each chapter to the folder immediately after generation, without waiting for the entire report to finish. 
        文件结构: 
        reports/{report_id}/
            meta.json       - 报告元信息
            outline.json    - 报告Large纲
            progress.json   - 生成进度
            section_01.md   - 第1章节
            section_02.md   - Chapter 2
            ...
            full_report.md  - 完整报告
        
        Args:
            progress_callback: 进度回Invoke函数 (stage, progress, message)
            report_id: 报告ID (可选, 如果不传Will be generated automatically) 
            
        Returns:
            Report: 完整报告
        """
        import uuid
        
        # If none传入 report_id, Will be generated automatically
        if not report_id:
            report_id = f"report_{uuid.uuid4().hex[:12]}"
        start_time = datetime.now()
        
        report = Report(
            report_id=report_id,
            simulation_id=self.simulation_id,
            graph_id=self.graph_id,
            simulation_requirement=self.simulation_requirement,
            status=ReportStatus.PENDING,
            created_at=datetime.now().isoformat()
        )
        
        # List of completed chapter titles (for progress tracking) 
        completed_section_titles = []
        
        try:
            # Initialization: create report folder and save initial state
            ReportManager._ensure_report_folder(report_id)
            
            # Initialize log recorder (structured logging) agent_log.jsonl) 
            self.report_logger = ReportLogger(report_id)
            self.report_logger.log_start(
                simulation_id=self.simulation_id,
                graph_id=self.graph_id,
                simulation_requirement=self.simulation_requirement
            )
            
            # 初StartTransform控制台 day志记录Device (console_log.txt) 
            self.console_logger = ReportConsoleLogger(report_id)
            
            ReportManager.update_progress(
                report_id, "pending", 0, t('progress.initReport'),
                completed_sections=[]
            )
            ReportManager.save_report(report)
            
            # 阶Segment1: 规划Large纲
            report.status = ReportStatus.PLANNING
            ReportManager.update_progress(
                report_id, "planning", 5, t('progress.startPlanningOutline'),
                completed_sections=[]
            )
            
            # 记录规划开Start day志
            self.report_logger.log_planning_start()
            
            if progress_callback:
                progress_callback("planning", 0, t('progress.startPlanningOutline'))
            
            outline = self.plan_outline(
                progress_callback=lambda stage, prog, msg: 
                    progress_callback(stage, prog // 5, msg) if progress_callback else None
            )
            report.outline = outline
            
            # 记录规划完成 day志
            self.report_logger.log_planning_complete(outline.to_dict())
            
            # Save outline to file
            ReportManager.save_outline(report_id, outline)
            ReportManager.update_progress(
                report_id, "planning", 15, t('progress.outlineDone', count=len(outline.sections)),
                completed_sections=[]
            )
            ReportManager.save_report(report)
            
            logger.info(t('report.outlineSavedToFile', reportId=report_id))
            
            # 阶Segment2: 逐章节生成 ( min章节保存) 
            report.status = ReportStatus.GENERATING
            
            total_sections = len(outline.sections)
            generated_sections = []  # 保存内容Use于on under 文
            
            for i, section in enumerate(outline.sections):
                section_num = i + 1
                base_progress = 20 + int((i / total_sections) * 70)
                
                # Update progress
                ReportManager.update_progress(
                    report_id, "generating", base_progress,
                    t('progress.generatingSection', title=section.title, current=section_num, total=total_sections),
                    current_section=section.title,
                    completed_sections=completed_section_titles
                )

                if progress_callback:
                    progress_callback(
                        "generating",
                        base_progress,
                        t('progress.generatingSection', title=section.title, current=section_num, total=total_sections)
                    )
                
                # 生成主章节内容
                section_content = self._generate_section_react(
                    section=section,
                    outline=outline,
                    previous_sections=generated_sections,
                    progress_callback=lambda stage, prog, msg:
                        progress_callback(
                            stage, 
                            base_progress + int(prog * 0.7 / total_sections),
                            msg
                        ) if progress_callback else None,
                    section_index=section_num
                )
                
                section.content = section_content
                generated_sections.append(f"## {section.title}\n\n{section_content}")

                # 保存章节
                ReportManager.save_section(report_id, section_num, section)
                completed_section_titles.append(section.title)

                # Log chapter completion
                full_section_content = f"## {section.title}\n\n{section_content}"

                if self.report_logger:
                    self.report_logger.log_section_full_complete(
                        section_title=section.title,
                        section_index=section_num,
                        full_content=full_section_content.strip()
                    )

                logger.info(t('report.sectionSaved', reportId=report_id, sectionNum=f"{section_num:02d}"))
                
                # Update progress
                ReportManager.update_progress(
                    report_id, "generating", 
                    base_progress + int(70 / total_sections),
                    t('progress.sectionDone', title=section.title),
                    current_section=None,
                    completed_sections=completed_section_titles
                )
                
                # 间隔休Sleep, 避免超Output Groq TPM 每minutes限额
                import time
                time.sleep(3)
            
            # 阶Segment3: 组装完整报告
            if progress_callback:
                progress_callback("generating", 95, t('progress.assemblingReport'))
            
            ReportManager.update_progress(
                report_id, "generating", 95, t('progress.assemblingReport'),
                completed_sections=completed_section_titles
            )
            
            # 使UseReportManager组装完整报告
            report.markdown_content = ReportManager.assemble_full_report(report_id, outline)
            report.status = ReportStatus.COMPLETED
            report.completed_at = datetime.now().isoformat()
            
            # 计算总耗 hour
            total_time_seconds = (datetime.now() - start_time).total_seconds()
            
            # Log report completion
            if self.report_logger:
                self.report_logger.log_report_complete(
                    total_sections=total_sections,
                    total_time_seconds=total_time_seconds
                )
            
            # 保存最终报告
            ReportManager.save_report(report)
            ReportManager.update_progress(
                report_id, "completed", 100, t('progress.reportComplete'),
                completed_sections=completed_section_titles
            )
            
            if progress_callback:
                progress_callback("completed", 100, t('progress.reportComplete'))
            
            logger.info(t('report.reportGenDone', reportId=report_id))
            
            # 关闭控制台 day志记录Device
            if self.console_logger:
                self.console_logger.close()
                self.console_logger = None
            
            return report
            
        except Exception as e:
            logger.error(t('report.reportGenFailed', error=str(e)))
            report.status = ReportStatus.FAILED
            report.error = str(e)
            
            # 记录错误 day志
            if self.report_logger:
                self.report_logger.log_error(str(e), "failed")
            
            # 保存失败状态
            try:
                ReportManager.save_report(report)
                ReportManager.update_progress(
                    report_id, "failed", -1, t('progress.reportFailed', error=str(e)),
                    completed_sections=completed_section_titles
                )
            except Exception:
                pass  # 忽略保存失败的错误
            
            # 关闭控制台 day志记录Device
            if self.console_logger:
                self.console_logger.close()
                self.console_logger = None
            
            return report
    
    def chat(
        self, 
        message: str,
        chat_history: List[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """
         and Report Agent对话
        
        在对话in Agent可以自主InvokeUse检索工具来回答问题
        
        Args:
            message: Use户Delete息
            chat_history: 对话历史
            
        Returns:
            {
                "response": "Agent回复",
                "tool_calls": [InvokeUse的工具列表],
                "sources": [信息来Source]
            }
        """
        logger.info(t('report.agentChat', message=message[:50]))
        
        chat_history = chat_history or []
        
        # 获取already 生成的报告内容
        report_content = ""
        try:
            report = ReportManager.get_report_by_simulation(self.simulation_id)
            if report and report.markdown_content:
                # 限制报告长度, 避免on under 文过长
                report_content = report.markdown_content[:15000]
                if len(report.markdown_content) > 15000:
                    report_content += "\n\n... [报告内容already 截断] ..."
        except Exception as e:
            logger.warning(t('report.fetchReportFailed', error=e))
        
        system_prompt = CHAT_SYSTEM_PROMPT_TEMPLATE.format(
            simulation_requirement=self.simulation_requirement,
            report_content=report_content if report_content else " (Temporarilynone报告) ",
            tools_description=self._get_tools_description(),
        )
        system_prompt = f"{system_prompt}\n\n{get_language_instruction()}"

        # 构建Delete息
        messages = [{"role": "system", "content": system_prompt}]
        
        # 添加历史对话
        for h in chat_history[-10:]:  # 限制历史长度
            messages.append(h)
        
        # 添加Use户Delete息
        messages.append({
            "role": "user", 
            "content": message
        })
        
        # ReACT循环 (简Transform版) 
        tool_calls_made = []
        max_iterations = 2  # 减少Iteration代 rounds数
        
        for iteration in range(max_iterations):
            response = self.llm.chat(
                messages=messages,
                temperature=0.5
            )
            
            # 解析工具InvokeUse
            tool_calls = self._parse_tool_calls(response)
            
            if not tool_calls:
                # 没has工具InvokeUse, 直ConnectReturn响应
                clean_response = re.sub(r'<tool_call>.*?</tool_call>', '', response, flags=re.DOTALL)
                clean_response = re.sub(r'\[TOOL_CALL\].*?\)', '', clean_response)
                clean_response = ReportAgent._strip_fake_tool_results(clean_response)
                
                return {
                    "response": clean_response.strip(),
                    "tool_calls": tool_calls_made,
                    "sources": [tc.get("parameters", {}).get("query", "") for tc in tool_calls_made]
                }
            
            # 执行工具InvokeUse (限制数量) 
            tool_results = []
            for call in tool_calls[:1]:  # 每 rounds最多执行1 times工具InvokeUse
                if len(tool_calls_made) >= self.MAX_TOOL_CALLS_PER_CHAT:
                    break
                result = self._execute_tool(call["name"], call.get("parameters", {}))
                tool_results.append({
                    "tool": call["name"],
                    "result": result[:1500]  # 限制结果长度
                })
                tool_calls_made.append(call)
            
            # Add result to message
            cleaned_response = ReportAgent._strip_fake_tool_results(response)
            messages.append({"role": "assistant", "content": cleaned_response})
            observation = "\n".join([f"[{r['tool']}结果]\n{r['result']}" for r in tool_results])
            messages.append({
                "role": "user",
                "content": observation + CHAT_OBSERVATION_SUFFIX
            })
        
        # Reached maximum iterations, obtain final response
        final_response = self.llm.chat(
            messages=messages,
            temperature=0.5
        )
        
        # Clean up response
        clean_response = re.sub(r'<tool_call>.*?</tool_call>', '', final_response, flags=re.DOTALL)
        clean_response = re.sub(r'\[TOOL_CALL\].*?\)', '', clean_response)
        clean_response = ReportAgent._strip_fake_tool_results(clean_response)
        
        return {
            "response": clean_response.strip(),
            "tool_calls": tool_calls_made,
            "sources": [tc.get("parameters", {}).get("query", "") for tc in tool_calls_made]
        }


class ReportManager:
    """
    报告管理Device
    
    负责报告的持DurationTransform存储 and 检索
    
    文件结构 ( min章节输Output) : 
    reports/
      {report_id}/
        meta.json          - 报告元信息 and 状态
        outline.json       - 报告Large纲
        progress.json      - 生成进度
        section_01.md      - 第1章节
        section_02.md      - Chapter 2
        ...
        full_report.md     - 完整报告
    """
    
    # 报告存储目录
    REPORTS_DIR = os.path.join(Config.UPLOAD_FOLDER, 'reports')
    
    @classmethod
    def _ensure_reports_dir(cls):
        """确保报告根目录存在"""
        os.makedirs(cls.REPORTS_DIR, exist_ok=True)
    
    @classmethod
    def _get_report_folder(cls, report_id: str) -> str:
        """获取报告文件Clip路径"""
        return os.path.join(cls.REPORTS_DIR, report_id)
    
    @classmethod
    def _ensure_report_folder(cls, report_id: str) -> str:
        """确保报告文件Clip存在并Return路径"""
        folder = cls._get_report_folder(report_id)
        os.makedirs(folder, exist_ok=True)
        return folder
    
    @classmethod
    def _get_report_path(cls, report_id: str) -> str:
        """获取报告元信息文件路径"""
        return os.path.join(cls._get_report_folder(report_id), "meta.json")
    
    @classmethod
    def _get_report_markdown_path(cls, report_id: str) -> str:
        """获取完整报告Markdown文件路径"""
        return os.path.join(cls._get_report_folder(report_id), "full_report.md")
    
    @classmethod
    def _get_outline_path(cls, report_id: str) -> str:
        """获取Large纲文件路径"""
        return os.path.join(cls._get_report_folder(report_id), "outline.json")
    
    @classmethod
    def _get_progress_path(cls, report_id: str) -> str:
        """获取进度文件路径"""
        return os.path.join(cls._get_report_folder(report_id), "progress.json")
    
    @classmethod
    def _get_section_path(cls, report_id: str, section_index: int) -> str:
        """获取章节Markdown文件路径"""
        return os.path.join(cls._get_report_folder(report_id), f"section_{section_index:02d}.md")
    
    @classmethod
    def _get_agent_log_path(cls, report_id: str) -> str:
        """获取 Agent  day志文件路径"""
        return os.path.join(cls._get_report_folder(report_id), "agent_log.jsonl")
    
    @classmethod
    def _get_console_log_path(cls, report_id: str) -> str:
        """获取控制台 day志文件路径"""
        return os.path.join(cls._get_report_folder(report_id), "console_log.txt")
    
    @classmethod
    def get_console_log(cls, report_id: str, from_line: int = 0) -> Dict[str, Any]:
        """
        Get console log content
        
        这is 报告生成过程in 的控制台输Output day志 (INFO, WARNING等) , 
         and  agent_log.jsonl 的结构Transform day志不Same. 
        
        Args:
            report_id: 报告ID
            from_line: 从第几行开Start读取 (Use于增量获取, 0 表Example从头开Start) 
            
        Returns:
            {
                "logs": [Log line list],
                "total_lines": 总行数,
                "from_line": 起Start行号,
                "has_more": is no还has更多 day志
            }
        """
        log_path = cls._get_console_log_path(report_id)
        
        if not os.path.exists(log_path):
            return {
                "logs": [],
                "total_lines": 0,
                "from_line": 0,
                "has_more": False
            }
        
        logs = []
        total_lines = 0
        
        with open(log_path, 'r', encoding='utf-8') as f:
            for i, line in enumerate(f):
                total_lines = i + 1
                if i >= from_line:
                    # 保留原Start day志行, 去Remove末尾换行Symbol
                    logs.append(line.rstrip('\n\r'))
        
        return {
            "logs": logs,
            "total_lines": total_lines,
            "from_line": from_line,
            "has_more": False  # already 读取到末尾
        }
    
    @classmethod
    def get_console_log_stream(cls, report_id: str) -> List[str]:
        """
        获取完整的控制台 day志 (一 times性获取全部) 
        
        Args:
            report_id: 报告ID
            
        Returns:
            Log line list
        """
        result = cls.get_console_log(report_id, from_line=0)
        return result["logs"]
    
    @classmethod
    def get_agent_log(cls, report_id: str, from_line: int = 0) -> Dict[str, Any]:
        """
        获取 Agent  day志内容
        
        Args:
            report_id: 报告ID
            from_line: 从第几行开Start读取 (Use于增量获取, 0 表Example从头开Start) 
            
        Returns:
            {
                "logs": [ day志 items目列表],
                "total_lines": 总行数,
                "from_line": 起Start行号,
                "has_more": is no还has更多 day志
            }
        """
        log_path = cls._get_agent_log_path(report_id)
        
        if not os.path.exists(log_path):
            return {
                "logs": [],
                "total_lines": 0,
                "from_line": 0,
                "has_more": False
            }
        
        logs = []
        total_lines = 0
        
        with open(log_path, 'r', encoding='utf-8') as f:
            for i, line in enumerate(f):
                total_lines = i + 1
                if i >= from_line:
                    try:
                        log_entry = json.loads(line.strip())
                        logs.append(log_entry)
                    except json.JSONDecodeError:
                        # Skip rows that fail to parse
                        continue
        
        return {
            "logs": logs,
            "total_lines": total_lines,
            "from_line": from_line,
            "has_more": False  # already 读取到末尾
        }
    
    @classmethod
    def get_agent_log_stream(cls, report_id: str) -> List[Dict[str, Any]]:
        """
        获取完整的 Agent  day志 (Use于一 times性获取全部) 
        
        Args:
            report_id: 报告ID
            
        Returns:
             day志 items目列表
        """
        result = cls.get_agent_log(report_id, from_line=0)
        return result["logs"]
    
    @classmethod
    def save_outline(cls, report_id: str, outline: ReportOutline) -> None:
        """
        Save Report Outline
        
        在规划阶Segment完成after 立即InvokeUse
        """
        cls._ensure_report_folder(report_id)
        
        with open(cls._get_outline_path(report_id), 'w', encoding='utf-8') as f:
            json.dump(outline.to_dict(), f, ensure_ascii=False, indent=2)
        
        logger.info(t('report.outlineSaved', reportId=report_id))
    
    @classmethod
    def save_section(
        cls,
        report_id: str,
        section_index: int,
        section: ReportSection
    ) -> str:
        """
        保存单章节

        在每章节生成完成after 立即InvokeUse, 实现 min章节输Output

        Args:
            report_id: 报告ID
            section_index: 章节索引 (从1开Start) 
            section: 章节对象

        Returns:
            保存的文件路径
        """
        cls._ensure_report_folder(report_id)

        # 构建章节Markdown内容 - 清理可能存在的重复标题
        cleaned_content = cls._clean_section_content(section.content, section.title)
        md_content = f"## {section.title}\n\n"
        if cleaned_content:
            md_content += f"{cleaned_content}\n\n"

        # 保存文件
        file_suffix = f"section_{section_index:02d}.md"
        file_path = os.path.join(cls._get_report_folder(report_id), file_suffix)
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(md_content)

        logger.info(t('report.sectionFileSaved', reportId=report_id, fileSuffix=file_suffix))
        return file_path
    
    @classmethod
    def _clean_section_content(cls, content: str, section_title: str) -> str:
        """
        清理章节内容
        
        1. Transfer除内容开头 and 章节标题重复的Markdown标题行
        2. 将所has ### and below级别的标题Convert换为粗体文本
        
        Args:
            content: 原Start内容
            section_title: 章节标题
            
        Returns:
            清理after 的内容
        """
        import re
        
        if not content:
            return content
        
        content = content.strip()
        lines = content.split('\n')
        cleaned_lines = []
        skip_next_empty = False
        
        for i, line in enumerate(lines):
            stripped = line.strip()
            
            # 检查is nois Markdown标题行
            heading_match = re.match(r'^(#{1,6})\s+(.+)$', stripped)
            
            if heading_match:
                level = len(heading_match.group(1))
                title_text = heading_match.group(2).strip()
                
                # 检查is nois  and 章节标题重复的标题 (跳过before 5行内的重复) 
                if i < 5:
                    if title_text == section_title or title_text.replace(' ', '') == section_title.replace(' ', ''):
                        skip_next_empty = True
                        continue
                
                # 将所has级别的标题 (#, ##, ###, ####等) Convert换为粗体
                # 因为章节标题由System统添加, 内容in 不应has任何标题
                cleaned_lines.append(f"**{title_text}**")
                cleaned_lines.append("")  # 添加空行
                continue
            
            # If the previous line is a skipped title and the current line is empty, also skip
            if skip_next_empty and stripped == '':
                skip_next_empty = False
                continue
            
            skip_next_empty = False
            cleaned_lines.append(line)
        
        # Remove leading blank lines
        while cleaned_lines and cleaned_lines[0].strip() == '':
            cleaned_lines.pop(0)
        
        # Remove leading separator line
        while cleaned_lines and cleaned_lines[0].strip() in ['---', '***', '___']:
            cleaned_lines.pop(0)
            # Also remove blank lines after separators
            while cleaned_lines and cleaned_lines[0].strip() == '':
                cleaned_lines.pop(0)
        
        return '\n'.join(cleaned_lines)
    
    @classmethod
    def update_progress(
        cls, 
        report_id: str, 
        status: str, 
        progress: int, 
        message: str,
        current_section: str = None,
        completed_sections: List[str] = None
    ) -> None:
        """
        更新报告生成进度
        
        before 端可以通过读取progress.json获取实 hour进度
        """
        cls._ensure_report_folder(report_id)
        
        progress_data = {
            "status": status,
            "progress": progress,
            "message": message,
            "current_section": current_section,
            "completed_sections": completed_sections or [],
            "updated_at": datetime.now().isoformat()
        }
        
        with open(cls._get_progress_path(report_id), 'w', encoding='utf-8') as f:
            json.dump(progress_data, f, ensure_ascii=False, indent=2)
    
    @classmethod
    def get_progress(cls, report_id: str) -> Optional[Dict[str, Any]]:
        """获取报告生成进度"""
        path = cls._get_progress_path(report_id)
        
        if not os.path.exists(path):
            return None
        
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    
    @classmethod
    def get_generated_sections(cls, report_id: str) -> List[Dict[str, Any]]:
        """
        获取already 生成的章节列表
        
        Return所hasalready 保存的章节文件信息
        """
        folder = cls._get_report_folder(report_id)
        
        if not os.path.exists(folder):
            return []
        
        sections = []
        for filename in sorted(os.listdir(folder)):
            if filename.startswith('section_') and filename.endswith('.md'):
                file_path = os.path.join(folder, filename)
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()

                # 从文件名解析章节索引
                parts = filename.replace('.md', '').split('_')
                section_index = int(parts[1])

                sections.append({
                    "filename": filename,
                    "section_index": section_index,
                    "content": content
                })

        return sections
    
    @classmethod
    def assemble_full_report(cls, report_id: str, outline: ReportOutline) -> str:
        """
        组装完整报告
        
        从already 保存的章节文件组装完整报告, 并进行标题清理
        """
        folder = cls._get_report_folder(report_id)
        
        # 构建报告头部
        md_content = f"# {outline.title}\n\n"
        md_content += f"> {outline.summary}\n\n"
        md_content += f"---\n\n"
        
        # Read all chapter files sequentially
        sections = cls.get_generated_sections(report_id)
        for section_info in sections:
            md_content += section_info["content"]
        
        # after Location理: 清理整报告的标题问题
        md_content = cls._post_process_report(md_content, outline)
        
        # 保存完整报告
        full_path = cls._get_report_markdown_path(report_id)
        with open(full_path, 'w', encoding='utf-8') as f:
            f.write(md_content)
        
        logger.info(t('report.fullReportAssembled', reportId=report_id))
        return md_content
    
    @classmethod
    def _post_process_report(cls, content: str, outline: ReportOutline) -> str:
        """
        after Location理报告内容
        
        1. Transfer除重复的标题
        2. 保留报告主标题(#)and Chapter Title(##), Transfer除其Other级别的标题(###, ####等)
        3. 清理多余的空行 and  min隔线
        
        Args:
            content: 原Start报告内容
            outline: 报告Large纲
            
        Returns:
            Location理after 的内容
        """
        import re
        
        lines = content.split('\n')
        processed_lines = []
        prev_was_heading = False
        
        # 收集Large纲in 的所has章节标题
        section_titles = set()
        for section in outline.sections:
            section_titles.add(section.title)
        
        i = 0
        while i < len(lines):
            line = lines[i]
            stripped = line.strip()
            
            # 检查is nois 标题行
            heading_match = re.match(r'^(#{1,6})\s+(.+)$', stripped)
            
            if heading_match:
                level = len(heading_match.group(1))
                title = heading_match.group(2).strip()
                
                # 检查is nois 重复标题 (在Link续5行内Output现相Same内容的标题) 
                is_duplicate = False
                for j in range(max(0, len(processed_lines) - 5), len(processed_lines)):
                    prev_line = processed_lines[j].strip()
                    prev_match = re.match(r'^(#{1,6})\s+(.+)$', prev_line)
                    if prev_match:
                        prev_title = prev_match.group(2).strip()
                        if prev_title == title:
                            is_duplicate = True
                            break
                
                if is_duplicate:
                    # 跳过重复标题 and 其after 的空行
                    i += 1
                    while i < len(lines) and lines[i].strip() == '':
                        i += 1
                    continue
                
                # 标题层级Location理: 
                # - # (level=1) 只保留报告主标题
                # - ## (level=2) 保留章节标题
                # - ### and below (level>=3) Convert换为粗体文本
                
                if level == 1:
                    if title == outline.title:
                        # 保留报告主标题
                        processed_lines.append(line)
                        prev_was_heading = True
                    elif title in section_titles:
                        # 章节标题错误使Use了#, 修正为##
                        processed_lines.append(f"## {title}")
                        prev_was_heading = True
                    else:
                        # 其Other一级标题Convert为粗体
                        processed_lines.append(f"**{title}**")
                        processed_lines.append("")
                        prev_was_heading = False
                elif level == 2:
                    if title in section_titles or title == outline.title:
                        # 保留章节标题
                        processed_lines.append(line)
                        prev_was_heading = True
                    else:
                        # Non章节的二级标题Convert为粗体
                        processed_lines.append(f"**{title}**")
                        processed_lines.append("")
                        prev_was_heading = False
                else:
                    # ### and below级别的标题Convert换为粗体文本
                    processed_lines.append(f"**{title}**")
                    processed_lines.append("")
                    prev_was_heading = False
                
                i += 1
                continue
            
            elif stripped == '---' and prev_was_heading:
                # 跳过标题after 紧跟的 min隔线
                i += 1
                continue
            
            elif stripped == '' and prev_was_heading:
                # 标题after 只保留一空行
                if processed_lines and processed_lines[-1].strip() != '':
                    processed_lines.append(line)
                prev_was_heading = False
            
            else:
                processed_lines.append(line)
                prev_was_heading = False
            
            i += 1
        
        # 清理Link续的多空行 (保留最多2) 
        result_lines = []
        empty_count = 0
        for line in processed_lines:
            if line.strip() == '':
                empty_count += 1
                if empty_count <= 2:
                    result_lines.append(line)
            else:
                empty_count = 0
                result_lines.append(line)
        
        return '\n'.join(result_lines)
    
    @classmethod
    def save_report(cls, report: Report) -> None:
        """保存报告元信息 and 完整报告"""
        cls._ensure_report_folder(report.report_id)
        
        # 保存元信息JSON
        with open(cls._get_report_path(report.report_id), 'w', encoding='utf-8') as f:
            json.dump(report.to_dict(), f, ensure_ascii=False, indent=2)
        
        # 保存Large纲
        if report.outline:
            cls.save_outline(report.report_id, report.outline)
        
        # 保存完整Markdown报告
        if report.markdown_content:
            with open(cls._get_report_markdown_path(report.report_id), 'w', encoding='utf-8') as f:
                f.write(report.markdown_content)
        
        logger.info(t('report.reportSaved', reportId=report.report_id))
    
    @classmethod
    def get_report(cls, report_id: str) -> Optional[Report]:
        """获取报告"""
        path = cls._get_report_path(report_id)
        
        if not os.path.exists(path):
            # 兼容旧Format: 检查直Connect存储在reports目录under 的文件
            old_path = os.path.join(cls.REPORTS_DIR, f"{report_id}.json")
            if os.path.exists(old_path):
                path = old_path
            else:
                return None
        
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # 重建Report对象
        outline = None
        if data.get('outline'):
            outline_data = data['outline']
            sections = []
            for s in outline_data.get('sections', []):
                sections.append(ReportSection(
                    title=s['title'],
                    content=s.get('content', '')
                ))
            outline = ReportOutline(
                title=outline_data['title'],
                summary=outline_data['summary'],
                sections=sections
            )
        
        # 如果markdown_content为空, 尝Test从full_report.md读取
        markdown_content = data.get('markdown_content', '')
        if not markdown_content:
            full_report_path = cls._get_report_markdown_path(report_id)
            if os.path.exists(full_report_path):
                with open(full_report_path, 'r', encoding='utf-8') as f:
                    markdown_content = f.read()
        
        return Report(
            report_id=data['report_id'],
            simulation_id=data['simulation_id'],
            graph_id=data['graph_id'],
            simulation_requirement=data['simulation_requirement'],
            status=ReportStatus(data['status']),
            outline=outline,
            markdown_content=markdown_content,
            created_at=data.get('created_at', ''),
            completed_at=data.get('completed_at', ''),
            error=data.get('error')
        )
    
    @classmethod
    def get_report_by_simulation(cls, simulation_id: str) -> Optional[Report]:
        """根据模DraftID获取报告"""
        cls._ensure_reports_dir()
        
        for item in os.listdir(cls.REPORTS_DIR):
            item_path = os.path.join(cls.REPORTS_DIR, item)
            # 新Format: 文件Clip
            if os.path.isdir(item_path):
                report = cls.get_report(item)
                if report and report.simulation_id == simulation_id:
                    return report
            # 兼容旧Format: JSON文件
            elif item.endswith('.json'):
                report_id = item[:-5]
                report = cls.get_report(report_id)
                if report and report.simulation_id == simulation_id:
                    return report
        
        return None
    
    @classmethod
    def list_reports(cls, simulation_id: Optional[str] = None, limit: int = 50) -> List[Report]:
        """列Output报告"""
        cls._ensure_reports_dir()
        
        reports = []
        for item in os.listdir(cls.REPORTS_DIR):
            item_path = os.path.join(cls.REPORTS_DIR, item)
            # 新Format: 文件Clip
            if os.path.isdir(item_path):
                report = cls.get_report(item)
                if report:
                    if simulation_id is None or report.simulation_id == simulation_id:
                        reports.append(report)
            # 兼容旧Format: JSON文件
            elif item.endswith('.json'):
                report_id = item[:-5]
                report = cls.get_report(report_id)
                if report:
                    if simulation_id is None or report.simulation_id == simulation_id:
                        reports.append(report)
        
        # 按Create hour间Reverse序
        reports.sort(key=lambda r: r.created_at, reverse=True)
        
        return reports[:limit]
    
    @classmethod
    def delete_report(cls, report_id: str) -> bool:
        """Delete报告 (整文件Clip) """
        import shutil
        
        folder_path = cls._get_report_folder(report_id)
        
        # New Format: Delete Entire Folder
        if os.path.exists(folder_path) and os.path.isdir(folder_path):
            shutil.rmtree(folder_path)
            logger.info(t('report.reportFolderDeleted', reportId=report_id))
            return True
        
        # 兼容旧Format: Delete单独的文件
        deleted = False
        old_json_path = os.path.join(cls.REPORTS_DIR, f"{report_id}.json")
        old_md_path = os.path.join(cls.REPORTS_DIR, f"{report_id}.md")
        
        if os.path.exists(old_json_path):
            os.remove(old_json_path)
            deleted = True
        if os.path.exists(old_md_path):
            os.remove(old_md_path)
            deleted = True
        
        return deleted
