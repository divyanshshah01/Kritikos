"""
模Draft配置智能生成Device
使UseLLM根据模Draft需Request, 文档内容, 图谱信息自动生成细致的Simulation Parameters
实现全程自动Transform, none需Person工设置参数

采Use min步生成策略, 避免一 times性生成过长内容导致失败: 
1. Generation Time Configuration
2. 生成Event配置
3.  min批生成Agent配置
4. 生成平台配置
"""

import json
import math
from typing import Dict, Any, List, Optional, Callable
from dataclasses import dataclass, field, asdict
from datetime import datetime

from openai import OpenAI

from ..config import Config
from ..utils.logger import get_logger
from ..utils.locale import get_language_instruction, t
from ..utils.openai_chat_compat import create_chat_completion, extract_chat_completion_text
from .zep_entity_reader import EntityNode, ZepEntityReader

logger = get_logger('mirofish.simulation_config')

# in 国作息 hour间配置 (North京 hour间) 
CHINA_TIMEZONE_CONFIG = {
    # 深夜 hourSegment (几乎nonePerson活动) 
    "dead_hours": [0, 1, 2, 3, 4, 5],
    # 早间 hourSegment (逐渐醒来) 
    "morning_hours": [6, 7, 8],
    # 工作 hourSegment
    "work_hours": [9, 10, 11, 12, 13, 14, 15, 16, 17, 18],
    # Evening peak (最活跃) 
    "peak_hours": [19, 20, 21, 22],
    # 夜间 hourSegment (活跃度under 降) 
    "night_hours": [23],
    # 活跃度System数
    "activity_multipliers": {
        "dead": 0.05,      # 凌晨几乎nonePerson
        "morning": 0.4,    # 早间逐渐活跃
        "work": 0.7,       # 工作 hourSegmentin 等
        "peak": 1.5,       # Evening peak
        "night": 0.5       # 深夜under 降
    }
}


@dataclass
class AgentActivityConfig:
    """单Agent的活动配置"""
    agent_id: int
    entity_uuid: str
    entity_name: str
    entity_type: str
    
    # 活跃度配置 (0.0-1.0)
    activity_level: float = 0.5  # 整体活跃度
    
    # 发言频率 (每Hour预期发言 times数) 
    posts_per_hour: float = 1.0
    comments_per_hour: float = 2.0
    
    # 活跃 hour间Segment (24Hour制, 0-23) 
    active_hours: List[int] = field(default_factory=lambda: list(range(8, 23)))
    
    # Response speed (delay in reacting to hot events, unit: simulation minutes)) 
    response_delay_min: int = 5
    response_delay_max: int = 60
    
    # 情感倾向 (-1.0到1.0, 负面到正面)
    sentiment_bias: float = 0.0
    
    # 立场 (对特定话题的态度) 
    stance: str = "neutral"  # supportive, opposing, neutral, observer
    
    # 影响力权重 (决定其发言被其OtherAgent看到的概率) 
    influence_weight: float = 1.0


@dataclass  
class TimeSimulationConfig:
    """ hour间模Draft配置 (基于in 国Person作息习惯) """
    # 模Draft总 hour长 (模DraftHour数) 
    total_simulation_hours: int = 72  # Default认模Draft72Hour (3天) 
    
    # 每 rounds代表的 hour间 (模Draftminutes) - Default认60minutes (1Hour) , 加快 hour间流速
    minutes_per_round: int = 60
    
    # Hourly activation range for agents
    agents_per_hour_min: int = 5
    agents_per_hour_max: int = 20
    
    # 高Peak hourSegment (Evening19-22点, in 国Person最活跃的 hour间) 
    peak_hours: List[int] = field(default_factory=lambda: [19, 20, 21, 22])
    peak_activity_multiplier: float = 1.5
    
    # Off-peak period (early morning0-5点, 几乎nonePerson活动) 
    off_peak_hours: List[int] = field(default_factory=lambda: [0, 1, 2, 3, 4, 5])
    off_peak_activity_multiplier: float = 0.05  # 凌晨活跃度极低
    
    # 早间 hourSegment
    morning_hours: List[int] = field(default_factory=lambda: [6, 7, 8])
    morning_activity_multiplier: float = 0.4
    
    # 工作 hourSegment
    work_hours: List[int] = field(default_factory=lambda: [9, 10, 11, 12, 13, 14, 15, 16, 17, 18])
    work_activity_multiplier: float = 0.7


@dataclass
class EventConfig:
    """Event配置"""
    # 初StartEvent (模Draft开Start hour的Trigger发Event) 
    initial_posts: List[Dict[str, Any]] = field(default_factory=list)
    
    # 定 hourEvent (在特定 hour间Trigger发的Event) 
    scheduled_events: List[Dict[str, Any]] = field(default_factory=list)
    
    # Hot点话题关键词
    hot_topics: List[str] = field(default_factory=list)
    
    # 舆论引导方向
    narrative_direction: str = ""


@dataclass
class PlatformConfig:
    """平台特定配置"""
    platform: str  # twitter or reddit
    
    # Push荐算Method权重
    recency_weight: float = 0.4  #  hour间新鲜度
    popularity_weight: float = 0.3  # Hot度
    relevance_weight: float = 0.3  # 相关性
    
    # 病毒传播阈值 (达到多少互动after Trigger发扩散) 
    viral_threshold: int = 10
    
    # 回声室效应Strong度 (相Similar观点聚集程度) 
    echo_chamber_strength: float = 0.5


@dataclass
class SimulationParameters:
    """完整的Simulation Parameters配置"""
    # 基Base信息
    simulation_id: str
    project_id: str
    graph_id: str
    simulation_requirement: str
    
    #  hour间配置
    time_config: TimeSimulationConfig = field(default_factory=TimeSimulationConfig)
    
    # Agent配置列表
    agent_configs: List[AgentActivityConfig] = field(default_factory=list)
    
    # Event配置
    event_config: EventConfig = field(default_factory=EventConfig)
    
    # 平台配置
    twitter_config: Optional[PlatformConfig] = None
    reddit_config: Optional[PlatformConfig] = None
    
    # LLM配置
    llm_model: str = ""
    llm_base_url: str = ""
    
    # 生成元数据
    generated_at: str = field(default_factory=lambda: datetime.now().isoformat())
    generation_reasoning: str = ""  # LLM的Push理说明
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert换为字典"""
        time_dict = asdict(self.time_config)
        return {
            "simulation_id": self.simulation_id,
            "project_id": self.project_id,
            "graph_id": self.graph_id,
            "simulation_requirement": self.simulation_requirement,
            "time_config": time_dict,
            "agent_configs": [asdict(a) for a in self.agent_configs],
            "event_config": asdict(self.event_config),
            "twitter_config": asdict(self.twitter_config) if self.twitter_config else None,
            "reddit_config": asdict(self.reddit_config) if self.reddit_config else None,
            "llm_model": self.llm_model,
            "llm_base_url": self.llm_base_url,
            "generated_at": self.generated_at,
            "generation_reasoning": self.generation_reasoning,
        }
    
    def to_json(self, indent: int = 2) -> str:
        """Convert换为JSON字Symbol串"""
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)


class SimulationConfigGenerator:
    """
    模Draft配置智能生成Device
    
    使UseLLM min析模Draft需Request, 文档内容, 图谱Entity information, 
    自动生成最佳的Simulation Parameters配置
    
    采Use min步生成策略: 
    1. Generation Time Configuration and Event配置 (Light量级) 
    2.  min批生成Agent配置 (每批10-20) 
    3. 生成平台配置
    """
    
    # on under 文最Large字Symbol数
    MAX_CONTEXT_LENGTH = 50000
    # 每批生成的Agent数量
    AGENTS_PER_BATCH = 15
    
    # 各步骤的on under 文截断长度 (字Symbol数) 
    TIME_CONFIG_CONTEXT_LENGTH = 10000   #  hour间配置
    EVENT_CONFIG_CONTEXT_LENGTH = 8000   # Event配置
    ENTITY_SUMMARY_LENGTH = 300          # entities摘要
    AGENT_SUMMARY_LENGTH = 300           # Agent配置in 的entities摘要
    ENTITIES_PER_TYPE_DISPLAY = 20       # 每Classentities显Example数量
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model_name: Optional[str] = None
    ):
        self.api_key = api_key or Config.LLM_API_KEY
        self.base_url = base_url or Config.LLM_BASE_URL
        self.model_name = model_name or Config.LLM_MODEL_NAME
        
        if not self.api_key:
            raise ValueError("LLM_API_KEY not 配置")
        
        self.client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url
        )
    
    def generate_config(
        self,
        simulation_id: str,
        project_id: str,
        graph_id: str,
        simulation_requirement: str,
        document_text: str,
        entities: List[EntityNode],
        enable_twitter: bool = True,
        enable_reddit: bool = True,
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
    ) -> SimulationParameters:
        """
        智能生成完整的模Draft配置 ( min步生成) 
        
        Args:
            simulation_id: 模DraftID
            project_id: 项目ID
            graph_id: 图谱ID
            simulation_requirement: 模Draft需Request描Description
            document_text: 原Start文档内容
            entities: Filtered entity list
            enable_twitter: is no启UseTwitter
            enable_reddit: is no启UseReddit
            progress_callback: 进度回Invoke函数(current_step, total_steps, message)
            
        Returns:
            SimulationParameters: 完整的Simulation Parameters
        """
        logger.info(f"开Start智能生成模Draft配置: simulation_id={simulation_id}, entities数={len(entities)}")
        
        # 计算总步骤数
        num_batches = math.ceil(len(entities) / self.AGENTS_PER_BATCH)
        total_steps = 3 + num_batches  #  hour间配置 + Event配置 + N批Agent + 平台配置
        current_step = 0
        
        def report_progress(step: int, message: str):
            nonlocal current_step
            current_step = step
            if progress_callback:
                progress_callback(step, total_steps, message)
            logger.info(f"[{step}/{total_steps}] {message}")
        
        # 1. 构建基Baseon under 文信息
        context = self._build_context(
            simulation_requirement=simulation_requirement,
            document_text=document_text,
            entities=entities
        )
        
        reasoning_parts = []
        
        # ========== 步骤1: Generation Time Configuration ==========
        report_progress(1, t('progress.generatingTimeConfig'))
        num_entities = len(entities)
        time_config_result = self._generate_time_config(context, num_entities)
        time_config = self._parse_time_config(time_config_result, num_entities)
        reasoning_parts.append(f"{t('progress.timeConfigLabel')}: {time_config_result.get('reasoning', t('common.success'))}")
        
        # ========== 步骤2: 生成Event配置 ==========
        report_progress(2, t('progress.generatingEventConfig'))
        event_config_result = self._generate_event_config(context, simulation_requirement, entities)
        event_config = self._parse_event_config(event_config_result)
        reasoning_parts.append(f"{t('progress.eventConfigLabel')}: {event_config_result.get('reasoning', t('common.success'))}")
        
        # ========== 步骤3-N:  min批生成Agent配置 ==========
        all_agent_configs = []
        for batch_idx in range(num_batches):
            start_idx = batch_idx * self.AGENTS_PER_BATCH
            end_idx = min(start_idx + self.AGENTS_PER_BATCH, len(entities))
            batch_entities = entities[start_idx:end_idx]
            
            report_progress(
                3 + batch_idx,
                t('progress.generatingAgentConfig', start=start_idx + 1, end=end_idx, total=len(entities))
            )
            
            batch_configs = self._generate_agent_configs_batch(
                context=context,
                entities=batch_entities,
                start_idx=start_idx,
                simulation_requirement=simulation_requirement
            )
            all_agent_configs.extend(batch_configs)
        
        reasoning_parts.append(t('progress.agentConfigResult', count=len(all_agent_configs)))
        
        # ========== Assign publisher to initial post Agent ==========
        logger.info("为初Start帖Child min配合适的发布者 Agent...")
        event_config = self._assign_initial_post_agents(event_config, all_agent_configs)
        assigned_count = len([p for p in event_config.initial_posts if p.get("poster_agent_id") is not None])
        reasoning_parts.append(t('progress.postAssignResult', count=assigned_count))
        
        # ========== 最after 一步: 生成平台配置 ==========
        report_progress(total_steps, t('progress.generatingPlatformConfig'))
        twitter_config = None
        reddit_config = None
        
        if enable_twitter:
            twitter_config = PlatformConfig(
                platform="twitter",
                recency_weight=0.4,
                popularity_weight=0.3,
                relevance_weight=0.3,
                viral_threshold=10,
                echo_chamber_strength=0.5
            )
        
        if enable_reddit:
            reddit_config = PlatformConfig(
                platform="reddit",
                recency_weight=0.3,
                popularity_weight=0.4,
                relevance_weight=0.3,
                viral_threshold=15,
                echo_chamber_strength=0.6
            )
        
        # 构建最终参数
        params = SimulationParameters(
            simulation_id=simulation_id,
            project_id=project_id,
            graph_id=graph_id,
            simulation_requirement=simulation_requirement,
            time_config=time_config,
            agent_configs=all_agent_configs,
            event_config=event_config,
            twitter_config=twitter_config,
            reddit_config=reddit_config,
            llm_model=self.model_name,
            llm_base_url=self.base_url,
            generation_reasoning=" | ".join(reasoning_parts)
        )
        
        logger.info(f"Simulation configuration generation completed: {len(params.agent_configs)} Agent配置")
        
        return params
    
    def _build_context(
        self,
        simulation_requirement: str,
        document_text: str,
        entities: List[EntityNode]
    ) -> str:
        """Build LLM context, truncate to maximum length"""
        
        # entities摘要
        entity_summary = self._summarize_entities(entities)
        
        # 构建on under 文
        context_parts = [
            f"## 模Draft需Request\n{simulation_requirement}",
            f"\n## Entity information ({len(entities)})\n{entity_summary}",
        ]
        
        current_length = sum(len(p) for p in context_parts)
        remaining_length = self.MAX_CONTEXT_LENGTH - current_length - 500  # Leave a 500-character buffer
        
        if remaining_length > 0 and document_text:
            doc_text = document_text[:remaining_length]
            if len(document_text) > remaining_length:
                doc_text += "\n...(文档already 截断)"
            context_parts.append(f"\n## 原Start文档内容\n{doc_text}")
        
        return "\n".join(context_parts)
    
    def _summarize_entities(self, entities: List[EntityNode]) -> str:
        """生成entities摘要"""
        lines = []
        
        # 按Class型 min组
        by_type: Dict[str, List[EntityNode]] = {}
        for e in entities:
            t = e.get_entity_type() or "Unknown"
            if t not in by_type:
                by_type[t] = []
            by_type[t].append(e)
        
        for entity_type, type_entities in by_type.items():
            lines.append(f"\n### {entity_type} ({len(type_entities)})")
            # 使Use配置的显Example数量 and 摘要长度
            display_count = self.ENTITIES_PER_TYPE_DISPLAY
            summary_len = self.ENTITY_SUMMARY_LENGTH
            for e in type_entities[:display_count]:
                summary_preview = (e.summary[:summary_len] + "...") if len(e.summary) > summary_len else e.summary
                lines.append(f"- {e.name}: {summary_preview}")
            if len(type_entities) > display_count:
                lines.append(f"  ... 还has {len(type_entities) - display_count} ")
        
        return "\n".join(lines)
    
    def _call_llm_with_retry(self, prompt: str, system_prompt: str) -> Dict[str, Any]:
        """With重Test的LLMInvokeUse, IncludeJSON修复逻辑"""
        import re
        
        max_attempts = 3
        last_error = None
        
        for attempt in range(max_attempts):
            try:
                response = create_chat_completion(
                    self.client,
                    model=self.model_name,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": prompt}
                    ],
                    response_format={"type": "json_object"},
                    temperature=0.7 - (attempt * 0.1),  # 每 times重Test降低温度
                    # 不设置max_tokens, 让LLM自由发挥
                )
                
                content = extract_chat_completion_text(response)
                finish_reason = response.choices[0].finish_reason
                
                # 检查is no被截断
                if finish_reason == 'length':
                    logger.warning(f"LLM输Output被截断 (attempt {attempt+1})")
                    content = self._fix_truncated_json(content)
                
                # 尝Test解析JSON
                try:
                    return json.loads(content)
                except json.JSONDecodeError as e:
                    logger.warning(f"JSON解析失败 (attempt {attempt+1}): {str(e)[:80]}")
                    
                    # 尝Test修复JSON
                    fixed = self._try_fix_config_json(content)
                    if fixed:
                        return fixed
                    
                    last_error = e
                    
            except Exception as e:
                logger.warning(f"LLMInvokeUse失败 (attempt {attempt+1}): {str(e)[:80]}")
                last_error = e
                import time
                time.sleep(2 * (attempt + 1))
        
        raise last_error or Exception("LLMInvokeUse失败")
    
    def _fix_truncated_json(self, content: str) -> str:
        """修复被截断的JSON"""
        content = content.strip()
        
        # Calculate unclosed parentheses
        open_braces = content.count('{') - content.count('}')
        open_brackets = content.count('[') - content.count(']')
        
        # 检查is nohasnot 闭合的字Symbol串
        if content and content[-1] not in '",}]':
            content += '"'
        
        # 闭合括号
        content += ']' * open_brackets
        content += '}' * open_braces
        
        return content
    
    def _try_fix_config_json(self, content: str) -> Optional[Dict[str, Any]]:
        """尝Test修复配置JSON"""
        import re
        
        # 修复被截断的情况
        content = self._fix_truncated_json(content)
        
        # 提取JSON部 min
        json_match = re.search(r'\{[\s\S]*\}', content)
        if json_match:
            json_str = json_match.group()
            
            # Transfer除字Symbol串in 的换行Symbol
            def fix_string(match):
                s = match.group(0)
                s = s.replace('\n', ' ').replace('\r', ' ')
                s = re.sub(r'\s+', ' ', s)
                return s
            
            json_str = re.sub(r'"[^"\\]*(?:\\.[^"\\]*)*"', fix_string, json_str)
            
            try:
                return json.loads(json_str)
            except:
                # 尝TestTransfer除所has控制字Symbol
                json_str = re.sub(r'[\x00-\x1f\x7f-\x9f]', ' ', json_str)
                json_str = re.sub(r'\s+', ' ', json_str)
                try:
                    return json.loads(json_str)
                except:
                    pass
        
        return None
    
    def _generate_time_config(self, context: str, num_entities: int) -> Dict[str, Any]:
        """Generation Time Configuration"""
        # 使Use配置的on under 文截断长度
        context_truncated = context[:self.TIME_CONFIG_CONTEXT_LENGTH]
        
        # 计算最Large允许值 (80%的agent数) 
        max_agents_allowed = max(1, int(num_entities * 0.9))
        
        prompt = f"""基于以under 模Draft需Request, 生成 hour间模Draft配置. 

{context_truncated}

## 任务
请Generation Time ConfigurationJSON. 

### 基本原则 (仅供参考, 需根据具体Event and 参 and 群体灵活Invoke整) : 
- 请根据模Draft场景Push断目标Use户群体所在 hour区 and 作息习惯, 以under 为东八区(UTC+8)的参考Example例
- 凌晨0-5点几乎nonePerson活动 (活跃度System数0.05) 
- 早on 6-8点逐渐活跃 (活跃度System数0.4) 
- 工作 hour间9-18点in 等活跃 (活跃度System数0.7) 
- Evening19-22点is 高Peak期 (活跃度System数1.5) 
- 23Post-point activity decline (activity coefficient0.5) 
- 一般规律: 凌晨低活跃, 早间渐增, 工作 hourSegmentin 等, Evening peak
- **重要**: 以under Example例值仅供参考, 你需要根据Event性质, 参 and 群体特点来Invoke整具体 hourSegment
  - 例如: Learning生群体高Peak可能is 21-23Points; media active all day; official institutions only during working hours
  - 例如: 突发Hot点可能导致深夜也has讨论, off_peak_hours 可适当缩短

### ReturnJSONFormat (不要markdown) 

Example例: 
{{
    "total_simulation_hours": 72,
    "minutes_per_round": 60,
    "agents_per_hour_min": 5,
    "agents_per_hour_max": 50,
    "peak_hours": [19, 20, 21, 22],
    "off_peak_hours": [0, 1, 2, 3, 4, 5],
    "morning_hours": [6, 7, 8],
    "work_hours": [9, 10, 11, 12, 13, 14, 15, 16, 17, 18],
    "reasoning": "Time configuration description for this event"
}}

Field description: 
- total_simulation_hours (int): 模Draft总 hour长, 24-168Hour, 突发Event短, 持续话题长
- minutes_per_round (int): 每 rounds hour长, 30-120minutes, 建议60minutes
- agents_per_hour_min (int): 每Hour最少激活Agent数 (取值范围: 1-{max_agents_allowed}) 
- agents_per_hour_max (int): Maximum number of agents activated per hour (value range: 1-{max_agents_allowed}) 
- peak_hours (int数组): 高Peak hourSegment, 根据Event参 and 群体Invoke整
- off_peak_hours (int数组): 低谷 hourSegment, 通常深夜凌晨
- morning_hours (int数组): 早间 hourSegment
- work_hours (int数组): 工作 hourSegment
- reasoning (string): 简要说明为什么这样配置"""

        system_prompt = "你is 社交媒体模Draft专Home. Return纯JSONFormat,  hour间配置需Symbol合模Draft场景in 目标Use户群体的作息习惯. "
        system_prompt = f"{system_prompt}\n\n{get_language_instruction()}"

        try:
            return self._call_llm_with_retry(prompt, system_prompt)
        except Exception as e:
            logger.warning(f" hour间配置LLM生成失败: {e}, 使UseDefault认配置")
            return self._get_default_time_config(num_entities)
    
    def _get_default_time_config(self, num_entities: int) -> Dict[str, Any]:
        """获取Default认 hour间配置 (in 国Person作息) """
        return {
            "total_simulation_hours": 72,
            "minutes_per_round": 60,  # 每 rounds1Hour, 加快 hour间流速
            "agents_per_hour_min": max(1, num_entities // 15),
            "agents_per_hour_max": max(5, num_entities // 5),
            "peak_hours": [19, 20, 21, 22],
            "off_peak_hours": [0, 1, 2, 3, 4, 5],
            "morning_hours": [6, 7, 8],
            "work_hours": [9, 10, 11, 12, 13, 14, 15, 16, 17, 18],
            "reasoning": "Use default Chinese daily schedule configuration (1 hour per round)) "
        }
    
    def _parse_time_config(self, result: Dict[str, Any], num_entities: int) -> TimeSimulationConfig:
        """解析 hour间配置结果, 并验证agents_per_hour值不超过总agent数"""
        # 获取原Start值
        agents_per_hour_min = result.get("agents_per_hour_min", max(1, num_entities // 15))
        agents_per_hour_max = result.get("agents_per_hour_max", max(5, num_entities // 5))
        
        # 验证并修正: 确保不超过总agent数
        if agents_per_hour_min > num_entities:
            logger.warning(f"agents_per_hour_min ({agents_per_hour_min}) 超过总Agent数 ({num_entities}), already 修正")
            agents_per_hour_min = max(1, num_entities // 10)
        
        if agents_per_hour_max > num_entities:
            logger.warning(f"agents_per_hour_max ({agents_per_hour_max}) 超过总Agent数 ({num_entities}), already 修正")
            agents_per_hour_max = max(agents_per_hour_min + 1, num_entities // 2)
        
        # 确保 min < max
        if agents_per_hour_min >= agents_per_hour_max:
            agents_per_hour_min = max(1, agents_per_hour_max // 2)
            logger.warning(f"agents_per_hour_min >= max, Corrected to {agents_per_hour_min}")
        
        return TimeSimulationConfig(
            total_simulation_hours=result.get("total_simulation_hours", 72),
            minutes_per_round=result.get("minutes_per_round", 60),  # Default认每 rounds1Hour
            agents_per_hour_min=agents_per_hour_min,
            agents_per_hour_max=agents_per_hour_max,
            peak_hours=result.get("peak_hours", [19, 20, 21, 22]),
            off_peak_hours=result.get("off_peak_hours", [0, 1, 2, 3, 4, 5]),
            off_peak_activity_multiplier=0.05,  # 凌晨几乎nonePerson
            morning_hours=result.get("morning_hours", [6, 7, 8]),
            morning_activity_multiplier=0.4,
            work_hours=result.get("work_hours", list(range(9, 19))),
            work_activity_multiplier=0.7,
            peak_activity_multiplier=1.5
        )
    
    def _generate_event_config(
        self, 
        context: str, 
        simulation_requirement: str,
        entities: List[EntityNode]
    ) -> Dict[str, Any]:
        """生成Event配置"""
        
        # 获取可Use的Entity Type List, 供 LLM 参考
        entity_types_available = list(set(
            e.get_entity_type() or "Unknown" for e in entities
        ))
        
        # 为每种Class型列Output代表性entities名称
        type_examples = {}
        for e in entities:
            etype = e.get_entity_type() or "Unknown"
            if etype not in type_examples:
                type_examples[etype] = []
            if len(type_examples[etype]) < 3:
                type_examples[etype].append(e.name)
        
        type_info = "\n".join([
            f"- {t}: {', '.join(examples)}" 
            for t, examples in type_examples.items()
        ])
        
        # 使Use配置的on under 文截断长度
        context_truncated = context[:self.EVENT_CONFIG_CONTEXT_LENGTH]
        
        prompt = f"""Generate event configuration based on the following simulation requirements. 

模Draft需Request: {simulation_requirement}

{context_truncated}

## 可UseentitiesClass型 and Example例
{type_info}

## 任务
请生成Event配置JSON: 
- 提取Hot点话题关键词
- Describe the direction of public opinion development
- 设计初Start帖Child内容, **每帖Child必须Indicates定 poster_type (发布者Class型) **

**重要**: poster_type 必须从on 面的"可UseentitiesClass型"in 选择, 这样初Start帖Child才能 min配给合适的 Agent 发布. 
例如: 官方声明应由 Official/University Class型发布, 新闻由 MediaOutlet 发布, Learning生观点由 Student 发布. 

ReturnJSONFormat (不要markdown) : 
{{
    "hot_topics": ["关键词1", "关键词2", ...],
    "narrative_direction": "<舆论发Display方向描Description>",
    "initial_posts": [
        {{"content": "帖Child内容", "poster_type": "entitiesClass型 (必须从可UseClass型in 选择) "}},
        ...
    ],
    "reasoning": "<简要说明>"
}}"""

        system_prompt = "你is 舆论 min析专Home. Return纯JSONFormat. 注意 poster_type Must exactly match available entity types. "
        system_prompt = f"{system_prompt}\n\n{get_language_instruction()}\nIMPORTANT: The 'poster_type' field value MUST be in English PascalCase exactly matching the available entity types. Only 'content', 'narrative_direction', 'hot_topics' and 'reasoning' fields should use the specified language."

        try:
            return self._call_llm_with_retry(prompt, system_prompt)
        except Exception as e:
            logger.warning(f"Event配置LLM生成失败: {e}, 使UseDefault认配置")
            return {
                "hot_topics": [],
                "narrative_direction": "",
                "initial_posts": [],
                "reasoning": "使UseDefault认配置"
            }
    
    def _parse_event_config(self, result: Dict[str, Any]) -> EventConfig:
        """解析Event配置结果"""
        return EventConfig(
            initial_posts=result.get("initial_posts", []),
            scheduled_events=[],
            hot_topics=result.get("hot_topics", []),
            narrative_direction=result.get("narrative_direction", "")
        )
    
    def _assign_initial_post_agents(
        self,
        event_config: EventConfig,
        agent_configs: List[AgentActivityConfig]
    ) -> EventConfig:
        """
        为初Start帖Child min配合适的发布者 Agent
        
        Based on each post's poster_type 匹配最合适的 agent_id
        """
        if not event_config.initial_posts:
            return event_config
        
        # Create Agent Index by Entity Type
        agents_by_type: Dict[str, List[AgentActivityConfig]] = {}
        for agent in agent_configs:
            etype = agent.entity_type.lower()
            if etype not in agents_by_type:
                agents_by_type[etype] = []
            agents_by_type[etype].append(agent)
        
        # Class型Mapping表 (Location理 LLM 可能输Output的不SameFormat) 
        type_aliases = {
            "official": ["official", "university", "governmentagency", "government"],
            "university": ["university", "official"],
            "mediaoutlet": ["mediaoutlet", "media"],
            "student": ["student", "person"],
            "professor": ["professor", "expert", "teacher"],
            "alumni": ["alumni", "person"],
            "organization": ["organization", "ngo", "company", "group"],
            "person": ["person", "student", "alumni"],
        }
        
        # 记录每种Class型already 使Use的 agent 索引, 避免重复使UseSame一 agent
        used_indices: Dict[str, int] = {}
        
        updated_posts = []
        for post in event_config.initial_posts:
            poster_type = post.get("poster_type", "").lower()
            content = post.get("content", "")
            
            # 尝Test找到匹配的 agent
            matched_agent_id = None
            
            # 1. 直Connect匹配
            if poster_type in agents_by_type:
                agents = agents_by_type[poster_type]
                idx = used_indices.get(poster_type, 0) % len(agents)
                matched_agent_id = agents[idx].agent_id
                used_indices[poster_type] = idx + 1
            else:
                # 2. 使Use别名匹配
                for alias_key, aliases in type_aliases.items():
                    if poster_type in aliases or alias_key == poster_type:
                        for alias in aliases:
                            if alias in agents_by_type:
                                agents = agents_by_type[alias]
                                idx = used_indices.get(alias, 0) % len(agents)
                                matched_agent_id = agents[idx].agent_id
                                used_indices[alias] = idx + 1
                                break
                    if matched_agent_id is not None:
                        break
            
            # 3. 如果仍not 找到, 使Use影响力最高的 agent
            if matched_agent_id is None:
                logger.warning(f"not 找到Class型 '{poster_type}' 的匹配 Agent, 使Use影响力最高的 Agent")
                if agent_configs:
                    # 按影响力排序, 选择影响力最高的
                    sorted_agents = sorted(agent_configs, key=lambda a: a.influence_weight, reverse=True)
                    matched_agent_id = sorted_agents[0].agent_id
                else:
                    matched_agent_id = 0
            
            updated_posts.append({
                "content": content,
                "poster_type": post.get("poster_type", "Unknown"),
                "poster_agent_id": matched_agent_id
            })
            
            logger.info(f"初Start帖Child min配: poster_type='{poster_type}' -> agent_id={matched_agent_id}")
        
        event_config.initial_posts = updated_posts
        return event_config
    
    def _generate_agent_configs_batch(
        self,
        context: str,
        entities: List[EntityNode],
        start_idx: int,
        simulation_requirement: str
    ) -> List[AgentActivityConfig]:
        """ min批生成Agent配置"""
        
        # 构建Entity information (使Use配置的摘要长度) 
        entity_list = []
        summary_len = self.AGENT_SUMMARY_LENGTH
        for i, e in enumerate(entities):
            entity_list.append({
                "agent_id": start_idx + i,
                "entity_name": e.name,
                "entity_type": e.get_entity_type() or "Unknown",
                "summary": e.summary[:summary_len] if e.summary else ""
            })
        
        prompt = f"""基于以under 信息, 为每entities生成社交媒体活动配置. 

模Draft需Request: {simulation_requirement}

## entities列表
```json
{json.dumps(entity_list, ensure_ascii=False, indent=2)}
```

## 任务
为每entities生成活动配置, 注意: 
- ** hour间Symbol合目标Use户群体作息**: 以under 为参考 (东八区) , 请根据模Draft场景Invoke整
- **官方机构** (University/GovernmentAgency) : Low activity(0.1-0.3), 工作 hour间(9-17)活动, 响应慢(60-240minutes), 影响力高(2.5-3.0)
- **媒体** (MediaOutlet) : 活跃度in (0.4-0.6), All-day activity(8-23), 响应快(5-30minutes), 影响力高(2.0-2.5)
- **Person** (Student/Person/Alumni) : 活跃度高(0.6-0.9), 主要Evening活动(18-23), 响应快(1-15minutes), 影响力低(0.8-1.2)
- **公众Person物/专Home**: 活跃度in (0.4-0.6), 影响力in 高(1.5-2.0)

ReturnJSONFormat (不要markdown) : 
{{
    "agent_configs": [
        {{
            "agent_id": <Must match the input>,
            "activity_level": <0.0-1.0>,
            "posts_per_hour": <发帖频率>,
            "comments_per_hour": <评论频率>,
            "active_hours": [<活跃Hour列表, 考虑in 国Person作息>],
            "response_delay_min": <最小响应延迟minutes>,
            "response_delay_max": <最Large响应延迟minutes>,
            "sentiment_bias": <-1.0到1.0>,
            "stance": "<supportive/opposing/neutral/observer>",
            "influence_weight": <影响力权重>
        }},
        ...
    ]
}}"""

        system_prompt = "你is 社交媒体行为 min析专Home. Return纯JSON, 配置需Symbol合模Draft场景in 目标Use户群体的作息习惯. "
        system_prompt = f"{system_prompt}\n\n{get_language_instruction()}\nIMPORTANT: The 'stance' field value MUST be one of the English strings: 'supportive', 'opposing', 'neutral', 'observer'. All JSON field names and numeric values must remain unchanged. Only natural language text fields should use the specified language."

        try:
            result = self._call_llm_with_retry(prompt, system_prompt)
            llm_configs = {cfg["agent_id"]: cfg for cfg in result.get("agent_configs", [])}
        except Exception as e:
            logger.warning(f"Agent配置批 timesLLM生成失败: {e}, 使Use规则生成")
            llm_configs = {}
        
        # 构建AgentActivityConfig对象
        configs = []
        for i, entity in enumerate(entities):
            agent_id = start_idx + i
            cfg = llm_configs.get(agent_id, {})
            
            # 如果LLM没has生成, 使Use规则生成
            if not cfg:
                cfg = self._generate_agent_config_by_rule(entity)
            
            config = AgentActivityConfig(
                agent_id=agent_id,
                entity_uuid=entity.uuid,
                entity_name=entity.name,
                entity_type=entity.get_entity_type() or "Unknown",
                activity_level=cfg.get("activity_level", 0.5),
                posts_per_hour=cfg.get("posts_per_hour", 0.5),
                comments_per_hour=cfg.get("comments_per_hour", 1.0),
                active_hours=cfg.get("active_hours", list(range(9, 23))),
                response_delay_min=cfg.get("response_delay_min", 5),
                response_delay_max=cfg.get("response_delay_max", 60),
                sentiment_bias=cfg.get("sentiment_bias", 0.0),
                stance=cfg.get("stance", "neutral"),
                influence_weight=cfg.get("influence_weight", 1.0)
            )
            configs.append(config)
        
        return configs
    
    def _generate_agent_config_by_rule(self, entity: EntityNode) -> Dict[str, Any]:
        """基于规则生成单Agent配置 (in 国Person作息) """
        entity_type = (entity.get_entity_type() or "Unknown").lower()
        
        if entity_type in ["university", "governmentagency", "ngo"]:
            # 官方机构: 工作 hour间活动, 低频率, 高影响力
            return {
                "activity_level": 0.2,
                "posts_per_hour": 0.1,
                "comments_per_hour": 0.05,
                "active_hours": list(range(9, 18)),  # 9:00-17:59
                "response_delay_min": 60,
                "response_delay_max": 240,
                "sentiment_bias": 0.0,
                "stance": "neutral",
                "influence_weight": 3.0
            }
        elif entity_type in ["mediaoutlet"]:
            # 媒体: All-day activity, in 等频率, 高影响力
            return {
                "activity_level": 0.5,
                "posts_per_hour": 0.8,
                "comments_per_hour": 0.3,
                "active_hours": list(range(7, 24)),  # 7:00-23:59
                "response_delay_min": 5,
                "response_delay_max": 30,
                "sentiment_bias": 0.0,
                "stance": "observer",
                "influence_weight": 2.5
            }
        elif entity_type in ["professor", "expert", "official"]:
            # 专Home/教授: 工作+Evening活动, in 等频率
            return {
                "activity_level": 0.4,
                "posts_per_hour": 0.3,
                "comments_per_hour": 0.5,
                "active_hours": list(range(8, 22)),  # 8:00-21:59
                "response_delay_min": 15,
                "response_delay_max": 90,
                "sentiment_bias": 0.0,
                "stance": "neutral",
                "influence_weight": 2.0
            }
        elif entity_type in ["student"]:
            # Learning生: Evening为主, 高频率
            return {
                "activity_level": 0.8,
                "posts_per_hour": 0.6,
                "comments_per_hour": 1.5,
                "active_hours": [8, 9, 10, 11, 12, 13, 18, 19, 20, 21, 22, 23],  # on 午+Evening
                "response_delay_min": 1,
                "response_delay_max": 15,
                "sentiment_bias": 0.0,
                "stance": "neutral",
                "influence_weight": 0.8
            }
        elif entity_type in ["alumni"]:
            # 校友: Evening为主
            return {
                "activity_level": 0.6,
                "posts_per_hour": 0.4,
                "comments_per_hour": 0.8,
                "active_hours": [12, 13, 19, 20, 21, 22, 23],  # 午休+Evening
                "response_delay_min": 5,
                "response_delay_max": 30,
                "sentiment_bias": 0.0,
                "stance": "neutral",
                "influence_weight": 1.0
            }
        else:
            # General通Person: Evening peak
            return {
                "activity_level": 0.7,
                "posts_per_hour": 0.5,
                "comments_per_hour": 1.2,
                "active_hours": [9, 10, 11, 12, 13, 18, 19, 20, 21, 22, 23],  # 白天+Evening
                "response_delay_min": 2,
                "response_delay_max": 20,
                "sentiment_bias": 0.0,
                "stance": "neutral",
                "influence_weight": 1.0
            }
    

