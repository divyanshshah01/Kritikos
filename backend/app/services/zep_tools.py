"""
Zep检索工具服务
封装图谱搜索, nodes读取, edges查询等工具, 供Report Agent使Use

核心检索工具 (优Transformafter ) : 
1. InsightForge (深度洞Observe检索) - 最StrongLarge的混合检索, 自动生成Child问题并多维度检索
2. PanoramaSearch (广度搜索) - 获取全貌, 包括过期内容
3. QuickSearch (简单搜索) - 快速检索
"""

import time
import json
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from zep_cloud import NotFoundError

from ..config import Config
from ..utils.logger import get_logger
from ..utils.llm_client import LLMClient
from ..utils.locale import get_locale, t
from ..utils.zep_paging import fetch_all_nodes, fetch_all_edges
from ..utils.zep import (
    call_zep_read_with_retry,
    get_zep_client,
    normalize_zep_search_limit,
    normalize_zep_search_query,
)

logger = get_logger('mirofish.zep_tools')


@dataclass
class SearchResult:
    """搜索结果"""
    facts: List[str]
    edges: List[Dict[str, Any]]
    nodes: List[Dict[str, Any]]
    query: str
    total_count: int
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "facts": self.facts,
            "edges": self.edges,
            "nodes": self.nodes,
            "query": self.query,
            "total_count": self.total_count
        }
    
    def to_text(self) -> str:
        """Convert换为文本Format, 供LLM理解"""
        text_parts = [f"搜索查询: {self.query}", f"找到 {self.total_count}  items相关信息"]
        
        if self.facts:
            text_parts.append("\n### 相关事实:")
            for i, fact in enumerate(self.facts, 1):
                text_parts.append(f"{i}. {fact}")
        
        return "\n".join(text_parts)


@dataclass
class NodeInfo:
    """nodes信息"""
    uuid: str
    name: str
    labels: List[str]
    summary: str
    attributes: Dict[str, Any]
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "uuid": self.uuid,
            "name": self.name,
            "labels": self.labels,
            "summary": self.summary,
            "attributes": self.attributes
        }
    
    def to_text(self) -> str:
        """Convert换为文本Format"""
        entity_type = next((l for l in self.labels if l not in ["Entity", "Node"]), "not KnowledgeClass型")
        return f"entities: {self.name} (Class型: {entity_type})\n摘要: {self.summary}"


@dataclass
class EdgeInfo:
    """edges信息"""
    uuid: str
    name: str
    fact: str
    source_node_uuid: str
    target_node_uuid: str
    source_node_name: Optional[str] = None
    target_node_name: Optional[str] = None
    #  hour间信息
    created_at: Optional[str] = None
    valid_at: Optional[str] = None
    invalid_at: Optional[str] = None
    expired_at: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "uuid": self.uuid,
            "name": self.name,
            "fact": self.fact,
            "source_node_uuid": self.source_node_uuid,
            "target_node_uuid": self.target_node_uuid,
            "source_node_name": self.source_node_name,
            "target_node_name": self.target_node_name,
            "created_at": self.created_at,
            "valid_at": self.valid_at,
            "invalid_at": self.invalid_at,
            "expired_at": self.expired_at
        }
    
    def to_text(self, include_temporal: bool = False) -> str:
        """Convert换为文本Format"""
        source = self.source_node_name or self.source_node_uuid[:8]
        target = self.target_node_name or self.target_node_uuid[:8]
        base_text = f"relations: {source} --[{self.name}]--> {target}\n事实: {self.fact}"
        
        if include_temporal:
            valid_at = self.valid_at or "not Knowledge"
            invalid_at = self.invalid_at or "至今"
            base_text += f"\n hour效: {valid_at} - {invalid_at}"
            if self.expired_at:
                base_text += f" (already 过期: {self.expired_at})"
        
        return base_text
    
    @property
    def is_expired(self) -> bool:
        """is noalready 过期"""
        return self.expired_at is not None
    
    @property
    def is_invalid(self) -> bool:
        """is noalready 失效"""
        return self.invalid_at is not None


@dataclass
class InsightForgeResult:
    """
    深度洞Observe检索结果 (InsightForge)
    Include多Child问题的检索结果, 以 and Summary合 min析
    """
    query: str
    simulation_requirement: str
    sub_queries: List[str]
    
    # 各维度检索结果
    semantic_facts: List[str] = field(default_factory=list)  # 语义搜索结果
    entity_insights: List[Dict[str, Any]] = field(default_factory=list)  # entities洞Observe
    relationship_chains: List[str] = field(default_factory=list)  # relations链
    
    # 统计信息
    total_facts: int = 0
    total_entities: int = 0
    total_relationships: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "query": self.query,
            "simulation_requirement": self.simulation_requirement,
            "sub_queries": self.sub_queries,
            "semantic_facts": self.semantic_facts,
            "entity_insights": self.entity_insights,
            "relationship_chains": self.relationship_chains,
            "total_facts": self.total_facts,
            "total_entities": self.total_entities,
            "total_relationships": self.total_relationships
        }
    
    def to_text(self) -> str:
        """Convert换为详细的文本Format, 供LLM理解"""
        text_parts = [
            f"## not 来预测深度 min析",
            f" min析问题: {self.query}",
            f"预测场景: {self.simulation_requirement}",
            f"\n### 预测数据统计",
            f"- 相关预测事实: {self.total_facts} items",
            f"- Involved and entities: {self.total_entities}",
            f"- relations链: {self.total_relationships} items"
        ]
        
        # Child问题
        if self.sub_queries:
            text_parts.append(f"\n###  min析的Child问题")
            for i, sq in enumerate(self.sub_queries[:3], 1):
                text_parts.append(f"{i}. {sq}")
        
        # 语义搜索结果 (限制before 10 items避免超Outputtoken限额) 
        if self.semantic_facts:
            text_parts.append(f"\n###  [关键事实] (请在报告in 引Use这些原文)")
            for i, fact in enumerate(self.semantic_facts[:10], 1):
                text_parts.append(f"{i}. \"{fact}\"")
        
        # entities洞Observe (限制before 6) 
        if self.entity_insights:
            text_parts.append(f"\n###  [Core Entity] ")
            for entity in self.entity_insights[:6]:
                text_parts.append(f"- **{entity.get('name', 'not Knowledge')}** ({entity.get('type', 'entities')})")
                if entity.get('summary'):
                    summary = entity.get('summary', '')
                    if len(summary) > 120:
                        summary = summary[:120] + "..."
                    text_parts.append(f"  摘要: \"{summary}\"")
                if entity.get('related_facts'):
                    text_parts.append(f"  相关事实: {len(entity.get('related_facts', []))} items")
        
        # Relationship chain (limit first 6 entries) 
        if self.relationship_chains:
            text_parts.append(f"\n###  [relations链] ")
            for chain in self.relationship_chains[:6]:
                text_parts.append(f"- {chain}")
        
        return "\n".join(text_parts)


@dataclass
class PanoramaResult:
    """
    广度搜索结果 (Panorama)
    Include所has相关信息, 包括过期内容
    """
    query: str
    
    # 全部nodes
    all_nodes: List[NodeInfo] = field(default_factory=list)
    # 全部edges (包括过期的) 
    all_edges: List[EdgeInfo] = field(default_factory=list)
    # Currently valid facts
    active_facts: List[str] = field(default_factory=list)
    # already 过期/失效的事实 (历史记录) 
    historical_facts: List[str] = field(default_factory=list)
    
    # 统计
    total_nodes: int = 0
    total_edges: int = 0
    active_count: int = 0
    historical_count: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "query": self.query,
            "all_nodes": [n.to_dict() for n in self.all_nodes],
            "all_edges": [e.to_dict() for e in self.all_edges],
            "active_facts": self.active_facts,
            "historical_facts": self.historical_facts,
            "total_nodes": self.total_nodes,
            "total_edges": self.total_edges,
            "active_count": self.active_count,
            "historical_count": self.historical_count
        }
    
    def to_text(self) -> str:
        """Convert换为文本Format (合理控制长度, 避免超OutputLLM TPM限额) """
        text_parts = [
            f"## 广度搜索结果 (not 来全景视图) ",
            f"查询: {self.query}",
            f"\n### 统计信息",
            f"- Total Nodes数: {self.total_nodes}",
            f"- 总edges数: {self.total_edges}",
            f"- 当before has效事实: {self.active_count} items",
            f"- 历史/过期事实: {self.historical_count} items"
        ]
        
        # Currently valid facts (限制before 10 items) 
        if self.active_facts:
            text_parts.append(f"\n###  [当before has效事实] (Original simulation result)")
            for i, fact in enumerate(self.active_facts[:10], 1):
                text_parts.append(f"{i}. \"{fact}\"")
        
        # 历史/过期事实 (限制before 5 items) 
        if self.historical_facts:
            text_parts.append(f"\n###  [历史/过期事实] (PerformChange过程记录)")
            for i, fact in enumerate(self.historical_facts[:5], 1):
                text_parts.append(f"{i}. \"{fact}\"")
        
        # 关键entities (限制before 8) 
        if self.all_nodes:
            text_parts.append(f"\n###  [Involved and entities] ")
            for node in self.all_nodes[:8]:
                entity_type = next((l for l in node.labels if l not in ["Entity", "Node"]), "entities")
                text_parts.append(f"- **{node.name}** ({entity_type})")
        
        return "\n".join(text_parts)


@dataclass
class AgentInterview:
    """单Agent的采访结果"""
    agent_name: str
    agent_role: str  # 角ColorClass型 (如: Learning生, 教师, 媒体等) 
    agent_bio: str  # 简Introduce
    question: str  # 采访问题
    response: str  # 采访回答
    key_quotes: List[str] = field(default_factory=list)  # 关键引言
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent_name": self.agent_name,
            "agent_role": self.agent_role,
            "agent_bio": self.agent_bio,
            "question": self.question,
            "response": self.response,
            "key_quotes": self.key_quotes
        }
    
    def to_text(self) -> str:
        text = f"**{self.agent_name}** ({self.agent_role})\n"
        # 显Example完整的agent_bio, 不截断
        text += f"_简Introduce: {self.agent_bio}_\n\n"
        text += f"**Q:** {self.question}\n\n"
        text += f"**A:** {self.response}\n"
        if self.key_quotes:
            text += "\n**关键引言:**\n"
            for quote in self.key_quotes:
                # 清理各种引号
                clean_quote = quote.replace('\u201c', '').replace('\u201d', '').replace('"', '')
                clean_quote = clean_quote.replace('\u300c', '').replace('\u300d', '')
                clean_quote = clean_quote.strip()
                # Remove leading punctuation
                while clean_quote and clean_quote[0] in ', ,；;: :, . ! ? \n\r\t ':
                    clean_quote = clean_quote[1:]
                # Filter spam containing question numbers (question1-9) 
                skip = False
                for d in '123456789':
                    if f'\u95ee\u9898{d}' in clean_quote:
                        skip = True
                        break
                if skip:
                    continue
                # 截断过长内容 (按句号截断, 而Non硬截断) 
                if len(clean_quote) > 150:
                    dot_pos = clean_quote.find('\u3002', 80)
                    if dot_pos > 0:
                        clean_quote = clean_quote[:dot_pos + 1]
                    else:
                        clean_quote = clean_quote[:147] + "..."
                if clean_quote and len(clean_quote) >= 10:
                    text += f'> "{clean_quote}"\n'
        return text


@dataclass
class InterviewResult:
    """
    采访结果 (Interview)
    Include多模DraftAgent的采访回答
    """
    interview_topic: str  # Interview topic
    interview_questions: List[str]  # 采访问题列表
    
    # 采访选择的Agent
    selected_agents: List[Dict[str, Any]] = field(default_factory=list)
    # 各Agent的采访回答
    interviews: List[AgentInterview] = field(default_factory=list)
    
    # 选择Agent的理由
    selection_reasoning: str = ""
    # 整合after 的采访摘要
    summary: str = ""
    
    # 统计
    total_agents: int = 0
    interviewed_count: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "interview_topic": self.interview_topic,
            "interview_questions": self.interview_questions,
            "selected_agents": self.selected_agents,
            "interviews": [i.to_dict() for i in self.interviews],
            "selection_reasoning": self.selection_reasoning,
            "summary": self.summary,
            "total_agents": self.total_agents,
            "interviewed_count": self.interviewed_count
        }
    
    def to_text(self) -> str:
        """Convert换为详细的文本Format, 供LLM理解 and 报告引Use"""
        text_parts = [
            "## 深度采访报告",
            f"**Interview topic:** {self.interview_topic}",
            f"**采访Person数:** {self.interviewed_count} / {self.total_agents} Positional SimulationAgent",
            "\n### 采访对象选择理由",
            self.selection_reasoning or " (自动选择) ",
            "\n---",
            "\n### 采访实录",
        ]

        if self.interviews:
            for i, interview in enumerate(self.interviews, 1):
                text_parts.append(f"\n#### 采访 #{i}: {interview.agent_name}")
                text_parts.append(interview.to_text())
                text_parts.append("\n---")
        else:
            text_parts.append(" (none采访记录) \n\n---")

        text_parts.append("\n### 采访摘要 and 核心观点")
        text_parts.append(self.summary or " (none摘要) ")

        return "\n".join(text_parts)


class ZepToolsService:
    """
    Zep检索工具服务
    
     [核心检索工具 - 优Transformafter ] 
    1. insight_forge - 深度洞Observe检索 (最StrongLarge, 自动生成Child问题, 多维度检索) 
    2. panorama_search - Breadth-first search (obtain full view, including expired content) 
    3. quick_search - 简单搜索 (快速检索) 
    4. interview_agents - 深度采访 (采访模DraftAgent, 获取多视角观点) 
    
     [基Base工具] 
    - search_graph - 图谱语义搜索
    - get_all_nodes - 获取图谱所hasnodes
    - get_all_edges - 获取图谱所hasedges (含 hour间信息) 
    - get_node_detail - 获取nodes详细信息
    - get_node_edges - 获取nodes相关的edges
    - get_entities_by_type - 按Class型获取entities
    - get_entity_summary - Get summary of entity relationships
    """
    
    # 重Test配置
    MAX_RETRIES = 3
    RETRY_DELAY = 2.0
    
    def __init__(self, api_key: Optional[str] = None, llm_client: Optional[LLMClient] = None):
        self.api_key = api_key or Config.ZEP_API_KEY
        if not self.api_key:
            raise ValueError("ZEP_API_KEY not 配置")
        
        self.client = get_zep_client(self.api_key)
        # LLM客户端Use于InsightForge生成Child问题
        self._llm_client = llm_client
        logger.info(t("console.zepToolsInitialized"))
    
    @property
    def llm(self) -> LLMClient:
        """延迟初StartTransformLLM客户端"""
        if self._llm_client is None:
            self._llm_client = LLMClient()
        return self._llm_client
    
    def _call_with_retry(self, func, operation_name: str, max_retries: int = None):
        """Retry one safe read using typed Zep/HTTPX error classification."""

        return call_zep_read_with_retry(
            func,
            operation_name=operation_name,
            max_attempts=max_retries or self.MAX_RETRIES,
            initial_delay=self.RETRY_DELAY,
        )
    
    def search_graph(
        self, 
        graph_id: str, 
        query: str, 
        limit: int = 10,
        scope: str = "edges"
    ) -> SearchResult:
        """
        图谱语义搜索
        
        使Use混合搜索 (语义+BM25) 在图谱in 搜索相关信息. 
        如果Zep Cloud的search API不可Use, 则降级为本地关键词匹配. 
        
        Args:
            graph_id: 图谱ID (Standalone Graph)
            query: 搜索查询
            limit: Return结果数量
            scope: 搜索范围, "edges"  or  "nodes"
            
        Returns:
            SearchResult: 搜索结果
        """
        logger.info(t("console.graphSearch", graphId=graph_id, query=query[:50]))
        
        zep_query = normalize_zep_search_query(query)
        zep_limit = normalize_zep_search_limit(limit)

        try:
            search_results = self._call_with_retry(
                func=lambda: self.client.graph.search(
                    graph_id=graph_id,
                    query=zep_query,
                    limit=zep_limit,
                    scope=scope,
                    reranker="cross_encoder"
                ),
                operation_name=t("console.graphSearchOp", graphId=graph_id)
            )
            
            facts = []
            edges = []
            nodes = []
            
            # 解析edges搜索结果
            if hasattr(search_results, 'edges') and search_results.edges:
                for edge in search_results.edges:
                    if hasattr(edge, 'fact') and edge.fact:
                        facts.append(edge.fact)
                    edges.append({
                        "uuid": getattr(edge, 'uuid_', None) or getattr(edge, 'uuid', ''),
                        "name": getattr(edge, 'name', ''),
                        "fact": getattr(edge, 'fact', ''),
                        "source_node_uuid": getattr(edge, 'source_node_uuid', ''),
                        "target_node_uuid": getattr(edge, 'target_node_uuid', ''),
                    })
            
            # 解析nodes搜索结果
            if hasattr(search_results, 'nodes') and search_results.nodes:
                for node in search_results.nodes:
                    nodes.append({
                        "uuid": getattr(node, 'uuid_', None) or getattr(node, 'uuid', ''),
                        "name": getattr(node, 'name', ''),
                        "labels": getattr(node, 'labels', []),
                        "summary": getattr(node, 'summary', ''),
                    })
                    # nodes摘要也算作事实
                    if hasattr(node, 'summary') and node.summary:
                        facts.append(f"[{node.name}]: {node.summary}")
            
            logger.info(t("console.searchComplete", count=len(facts)))
            
            return SearchResult(
                facts=facts,
                edges=edges,
                nodes=nodes,
                query=query,
                total_count=len(facts)
            )
            
        except Exception as e:
            # Authentication, invalid input, missing graphs, and exhausted
            # transient failures must remain visible to the report workflow.
            logger.error(t("console.zepSearchApiFallback", error=str(e)))
            raise
    
    def _local_search(
        self, 
        graph_id: str, 
        query: str, 
        limit: int = 10,
        scope: str = "edges"
    ) -> SearchResult:
        """
        本地关键词匹配搜索 (作为Zep Search API的降级方案) 
        
        获取所hasedges/Nodes, then perform keyword matching locally
        
        Args:
            graph_id: 图谱ID
            query: 搜索查询
            limit: Return结果数量
            scope: 搜索范围
            
        Returns:
            SearchResult: 搜索结果
        """
        logger.info(t("console.usingLocalSearch", query=query[:30]))
        
        facts = []
        edges_result = []
        nodes_result = []
        
        # 提取查询关键词 (简单 min词) 
        query_lower = query.lower()
        keywords = [w.strip() for w in query_lower.replace(',', ' ').replace(', ', ' ').split() if len(w.strip()) > 1]
        
        def match_score(text: str) -> int:
            """计算文本 and 查询的匹配 min数"""
            if not text:
                return 0
            text_lower = text.lower()
            # 完全匹配查询
            if query_lower in text_lower:
                return 100
            # 关键词匹配
            score = 0
            for keyword in keywords:
                if keyword in text_lower:
                    score += 10
            return score
        
        try:
            if scope in ["edges", "both"]:
                # Retrieve all edges and match
                all_edges = self.get_all_edges(graph_id)
                scored_edges = []
                for edge in all_edges:
                    score = match_score(edge.fact) + match_score(edge.name)
                    if score > 0:
                        scored_edges.append((score, edge))
                
                # 按 min数排序
                scored_edges.sort(key=lambda x: x[0], reverse=True)
                
                for score, edge in scored_edges[:limit]:
                    if edge.fact:
                        facts.append(edge.fact)
                    edges_result.append({
                        "uuid": edge.uuid,
                        "name": edge.name,
                        "fact": edge.fact,
                        "source_node_uuid": edge.source_node_uuid,
                        "target_node_uuid": edge.target_node_uuid,
                    })
            
            if scope in ["nodes", "both"]:
                # 获取所hasnodes并匹配
                all_nodes = self.get_all_nodes(graph_id)
                scored_nodes = []
                for node in all_nodes:
                    score = match_score(node.name) + match_score(node.summary)
                    if score > 0:
                        scored_nodes.append((score, node))
                
                scored_nodes.sort(key=lambda x: x[0], reverse=True)
                
                for score, node in scored_nodes[:limit]:
                    nodes_result.append({
                        "uuid": node.uuid,
                        "name": node.name,
                        "labels": node.labels,
                        "summary": node.summary,
                    })
                    if node.summary:
                        facts.append(f"[{node.name}]: {node.summary}")
            
            logger.info(t("console.localSearchComplete", count=len(facts)))
            
        except Exception as e:
            logger.error(t("console.localSearchFailed", error=str(e)))
        
        return SearchResult(
            facts=facts,
            edges=edges_result,
            nodes=nodes_result,
            query=query,
            total_count=len(facts)
        )
    
    def get_all_nodes(self, graph_id: str) -> List[NodeInfo]:
        """
        获取图谱的所hasnodes ( min页获取) 

        Args:
            graph_id: 图谱ID

        Returns:
            nodes列表
        """
        logger.info(t("console.fetchingAllNodes", graphId=graph_id))

        nodes = fetch_all_nodes(self.client, graph_id)

        result = []
        for node in nodes:
            node_uuid = getattr(node, 'uuid_', None) or getattr(node, 'uuid', None) or ""
            result.append(NodeInfo(
                uuid=str(node_uuid) if node_uuid else "",
                name=node.name or "",
                labels=node.labels or [],
                summary=node.summary or "",
                attributes=node.attributes or {}
            ))

        logger.info(t("console.fetchedNodes", count=len(result)))
        return result

    def get_all_edges(self, graph_id: str, include_temporal: bool = True) -> List[EdgeInfo]:
        """
        获取图谱All edges of ( min页获取, Include hour间信息) 

        Args:
            graph_id: 图谱ID
            include_temporal: Whether to include timestamp (defaultTrue) 

        Returns:
            edges列表 (Includecreated_at, valid_at, invalid_at, expired_at) 
        """
        logger.info(t("console.fetchingAllEdges", graphId=graph_id))

        edges = fetch_all_edges(self.client, graph_id)

        result = []
        for edge in edges:
            edge_uuid = getattr(edge, 'uuid_', None) or getattr(edge, 'uuid', None) or ""
            edge_info = EdgeInfo(
                uuid=str(edge_uuid) if edge_uuid else "",
                name=edge.name or "",
                fact=edge.fact or "",
                source_node_uuid=edge.source_node_uuid or "",
                target_node_uuid=edge.target_node_uuid or ""
            )

            # 添加 hour间信息
            if include_temporal:
                edge_info.created_at = getattr(edge, 'created_at', None)
                edge_info.valid_at = getattr(edge, 'valid_at', None)
                edge_info.invalid_at = getattr(edge, 'invalid_at', None)
                edge_info.expired_at = getattr(edge, 'expired_at', None)

            result.append(edge_info)

        logger.info(t("console.fetchedEdges", count=len(result)))
        return result
    
    def get_node_detail(self, node_uuid: str) -> Optional[NodeInfo]:
        """
        获取单nodes的详细信息
        
        Args:
            node_uuid: nodesUUID
            
        Returns:
            Node Information orNone
        """
        logger.info(t("console.fetchingNodeDetail", uuid=node_uuid[:8]))
        
        try:
            node = self._call_with_retry(
                func=lambda: self.client.graph.node.get(uuid_=node_uuid),
                operation_name=t("console.fetchNodeDetailOp", uuid=node_uuid[:8])
            )
            
            if not node:
                return None
            
            return NodeInfo(
                uuid=getattr(node, 'uuid_', None) or getattr(node, 'uuid', ''),
                name=node.name or "",
                labels=node.labels or [],
                summary=node.summary or "",
                attributes=node.attributes or {}
            )
        except NotFoundError:
            return None
        except Exception as e:
            logger.error(t("console.fetchNodeDetailFailed", error=str(e)))
            raise
    
    def get_node_edges(self, graph_id: str, node_uuid: str) -> List[EdgeInfo]:
        """
        获取nodes相关All edges of
        
        通过获取图谱所hasedges, 然after 过滤Output and Indicates定nodes相关的edges
        
        Args:
            graph_id: 图谱ID
            node_uuid: nodesUUID
            
        Returns:
            edges列表
        """
        logger.info(t("console.fetchingNodeEdges", uuid=node_uuid[:8]))
        
        try:
            # 获取图谱所hasedges, 然after 过滤
            all_edges = self.get_all_edges(graph_id)
            
            result = []
            for edge in all_edges:
                # 检查edgesis no and Indicates定nodes相关 (作为Source or 目标) 
                if edge.source_node_uuid == node_uuid or edge.target_node_uuid == node_uuid:
                    result.append(edge)
            
            logger.info(t("console.foundNodeEdges", count=len(result)))
            return result
            
        except Exception as e:
            logger.error(t("console.fetchNodeEdgesFailed", error=str(e)))
            raise
    
    def get_entities_by_type(
        self, 
        graph_id: str, 
        entity_type: str
    ) -> List[NodeInfo]:
        """
        按Class型获取entities
        
        Args:
            graph_id: 图谱ID
            entity_type: entitiesClass型 (如 Student, PublicFigure 等) 
            
        Returns:
            Symbol合Class型的entities列表
        """
        logger.info(t("console.fetchingEntitiesByType", type=entity_type))
        
        all_nodes = self.get_all_nodes(graph_id)
        
        filtered = []
        for node in all_nodes:
            # 检查labelsis noIncludeIndicates定Class型
            if entity_type in node.labels:
                filtered.append(node)
        
        logger.info(t("console.foundEntitiesByType", count=len(filtered), type=entity_type))
        return filtered
    
    def get_entity_summary(
        self, 
        graph_id: str, 
        entity_name: str
    ) -> Dict[str, Any]:
        """
        获取Indicates定entities的relations摘要
        
        搜索 and 该entities相关的所has信息, 并生成摘要
        
        Args:
            graph_id: 图谱ID
            entity_name: entities名称
            
        Returns:
            entities摘要信息
        """
        logger.info(t("console.fetchingEntitySummary", name=entity_name))
        
        # First搜索该entities相关的信息
        search_result = self.search_graph(
            graph_id=graph_id,
            query=entity_name,
            limit=20
        )
        
        # 尝Test在所hasnodesin 找到该entities
        all_nodes = self.get_all_nodes(graph_id)
        entity_node = None
        for node in all_nodes:
            if node.name.lower() == entity_name.lower():
                entity_node = node
                break
        
        related_edges = []
        if entity_node:
            # 传入graph_id参数
            related_edges = self.get_node_edges(graph_id, entity_node.uuid)
        
        return {
            "entity_name": entity_name,
            "entity_info": entity_node.to_dict() if entity_node else None,
            "related_facts": search_result.facts,
            "related_edges": [e.to_dict() for e in related_edges],
            "total_relations": len(related_edges)
        }
    
    def get_graph_statistics(self, graph_id: str) -> Dict[str, Any]:
        """
        获取图谱的统计信息
        
        Args:
            graph_id: 图谱ID
            
        Returns:
            统计信息
        """
        logger.info(t("console.fetchingGraphStats", graphId=graph_id))
        
        nodes = self.get_all_nodes(graph_id)
        edges = self.get_all_edges(graph_id)
        
        # 统计entitiesClass型 min布
        entity_types = {}
        for node in nodes:
            for label in node.labels:
                if label not in ["Entity", "Node"]:
                    entity_types[label] = entity_types.get(label, 0) + 1
        
        # 统计relationsClass型 min布
        relation_types = {}
        for edge in edges:
            relation_types[edge.name] = relation_types.get(edge.name, 0) + 1
        
        return {
            "graph_id": graph_id,
            "total_nodes": len(nodes),
            "total_edges": len(edges),
            "entity_types": entity_types,
            "relation_types": relation_types
        }
    
    def get_simulation_context(
        self, 
        graph_id: str,
        simulation_requirement: str,
        limit: int = 30
    ) -> Dict[str, Any]:
        """
        获取模Draft相关的on under 文信息
        
        Summary合搜索 and 模Draft需Request相关的所has信息
        
        Args:
            graph_id: 图谱ID
            simulation_requirement: 模Draft需Request描Description
            limit: 每Class信息的数量限制
            
        Returns:
            模Drafton under 文信息
        """
        logger.info(t("console.fetchingSimContext", requirement=simulation_requirement[:50]))
        
        # 搜索 and 模Draft需Request相关的信息
        search_result = self.search_graph(
            graph_id=graph_id,
            query=simulation_requirement,
            limit=limit
        )
        
        # Fetch graph statistics
        stats = self.get_graph_statistics(graph_id)
        
        # 获取所hasentitiesnodes
        all_nodes = self.get_all_nodes(graph_id)
        
        # 筛选has实际Class型的entities (Non纯Entitynodes) 
        entities = []
        for node in all_nodes:
            custom_labels = [l for l in node.labels if l not in ["Entity", "Node"]]
            if custom_labels:
                entities.append({
                    "name": node.name,
                    "type": custom_labels[0],
                    "summary": node.summary
                })
        
        return {
            "simulation_requirement": simulation_requirement,
            "related_facts": search_result.facts,
            "graph_statistics": stats,
            "entities": entities[:limit],  # 限制数量
            "total_entities": len(entities)
        }
    
    # ========== 核心检索工具 (优Transformafter )  ==========
    
    def insight_forge(
        self,
        graph_id: str,
        query: str,
        simulation_requirement: str,
        report_context: str = "",
        max_sub_queries: int = 5
    ) -> InsightForgeResult:
        """
         [InsightForge - 深度洞Observe检索] 
        
        最StrongLarge的混合检索函数, 自动 min解问题并多维度检索: 
        1. 使UseLLM将问题 min解为多Child问题
        2. 对每Child问题进行语义搜索
        3. 提取相关entities并获取其详细信息
        4. 追踪relations链
        5. 整合所has结果, 生成深度洞Observe
        
        Args:
            graph_id: 图谱ID
            query: Use户问题
            simulation_requirement: 模Draft需Request描Description
            report_context: 报告on under 文 (可选, Use于更精准的Child问题生成) 
            max_sub_queries: 最LargeChild问题数量
            
        Returns:
            InsightForgeResult: 深度洞Observe检索结果
        """
        logger.info(t("console.insightForgeStart", query=query[:50]))
        
        result = InsightForgeResult(
            query=query,
            simulation_requirement=simulation_requirement,
            sub_queries=[]
        )
        
        # Step 1: 使UseLLM生成Child问题
        sub_queries = self._generate_sub_queries(
            query=query,
            simulation_requirement=simulation_requirement,
            report_context=report_context,
            max_queries=max_sub_queries
        )
        result.sub_queries = sub_queries
        logger.info(t("console.generatedSubQueries", count=len(sub_queries)))
        
        # Step 2: 对每Child问题进行语义搜索
        all_facts = []
        all_edges = []
        seen_facts = set()
        
        for sub_query in sub_queries:
            search_result = self.search_graph(
                graph_id=graph_id,
                query=sub_query,
                limit=15,
                scope="edges"
            )
            
            for fact in search_result.facts:
                if fact not in seen_facts:
                    all_facts.append(fact)
                    seen_facts.add(fact)
            
            all_edges.extend(search_result.edges)
        
        # 对原Start问题也进行搜索
        main_search = self.search_graph(
            graph_id=graph_id,
            query=query,
            limit=20,
            scope="edges"
        )
        for fact in main_search.facts:
            if fact not in seen_facts:
                all_facts.append(fact)
                seen_facts.add(fact)
        
        result.semantic_facts = all_facts
        result.total_facts = len(all_facts)
        
        # Step 3: 从edgesin 提取相关entitiesUUID, 只获取这些entities的信息 (不获取全部nodes) 
        entity_uuids = set()
        for edge_data in all_edges:
            if isinstance(edge_data, dict):
                source_uuid = edge_data.get('source_node_uuid', '')
                target_uuid = edge_data.get('target_node_uuid', '')
                if source_uuid:
                    entity_uuids.add(source_uuid)
                if target_uuid:
                    entity_uuids.add(target_uuid)
        
        # 获取所has相关entities的详情 (不限制数量, 完整输Output) 
        entity_insights = []
        node_map = {}  # Use于after 续relations链构建
        
        for uuid in list(entity_uuids):  # Location理所hasentities, 不截断
            if not uuid:
                continue
            try:
                # 单独获取每related nodes的信息
                node = self.get_node_detail(uuid)
                if node:
                    node_map[uuid] = node
                    entity_type = next((l for l in node.labels if l not in ["Entity", "Node"]), "entities")
                    
                    # Retrieve all facts related to the entity (no truncation) 
                    related_facts = [
                        f for f in all_facts 
                        if node.name.lower() in f.lower()
                    ]
                    
                    entity_insights.append({
                        "uuid": node.uuid,
                        "name": node.name,
                        "type": entity_type,
                        "summary": node.summary,
                        "related_facts": related_facts  # Full Output, No Truncation
                    })
            except Exception as e:
                logger.debug(f"获取nodes {uuid} 失败: {e}")
                continue
        
        result.entity_insights = entity_insights
        result.total_entities = len(entity_insights)
        
        # Step 4: 构建所hasrelations链 (不限制数量) 
        relationship_chains = []
        for edge_data in all_edges:  # Location理所hasedges, 不截断
            if isinstance(edge_data, dict):
                source_uuid = edge_data.get('source_node_uuid', '')
                target_uuid = edge_data.get('target_node_uuid', '')
                relation_name = edge_data.get('name', '')
                
                source_name = node_map.get(source_uuid, NodeInfo('', '', [], '', {})).name or source_uuid[:8]
                target_name = node_map.get(target_uuid, NodeInfo('', '', [], '', {})).name or target_uuid[:8]
                
                chain = f"{source_name} --[{relation_name}]--> {target_name}"
                if chain not in relationship_chains:
                    relationship_chains.append(chain)
        
        result.relationship_chains = relationship_chains
        result.total_relationships = len(relationship_chains)
        
        logger.info(t("console.insightForgeComplete", facts=result.total_facts, entities=result.total_entities, relationships=result.total_relationships))
        return result
    
    def _generate_sub_queries(
        self,
        query: str,
        simulation_requirement: str,
        report_context: str = "",
        max_queries: int = 5
    ) -> List[str]:
        """
        使UseLLM生成Child问题
        
        Decompose complex problem into multiple independently searchable sub‑questions
        """
        system_prompt = """你is 一专业的问题 min析专Home. 你的任务is 将一复杂问题 min解为多可以在模Draft世界in 独立观Observe的Child问题. 

Requirement: 
1. Each sub-question should be specific enough to locate relevant Agent behaviors or events in the simulated world
2. Child问题应该覆Cover原问题的不Same维度 (如: 谁, 什么, 为什么, 怎么样, 何 hour, 何地) 
3. Sub-questions should be relevant to the simulation scenario
4. ReturnJSONFormat: {"sub_queries": ["Child问题1", "Child问题2", ...]}"""

        user_prompt = f"""模Draft需Request背景: 
{simulation_requirement}

{f"报告on under 文: {report_context[:500]}" if report_context else ""}

Please decompose the following question into{max_queries}Child问题: 
{query}

ReturnJSONFormat的Child问题列表. """

        try:
            response = self.llm.chat_json(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.3
            )
            
            sub_queries = response.get("sub_queries", [])
            # Ensure it is a list of strings
            return [str(sq) for sq in sub_queries[:max_queries]]
            
        except Exception as e:
            logger.warning(t("console.generateSubQueriesFailed", error=str(e)))
            # 降级: Return基于原问题的Change体
            return [
                query,
                f"{query} 的主要参 and 者",
                f"{query} 的原因 and 影响",
                f"{query} 的发Display过程"
            ][:max_queries]
    
    def panorama_search(
        self,
        graph_id: str,
        query: str,
        include_expired: bool = True,
        limit: int = 50
    ) -> PanoramaResult:
        """
         [PanoramaSearch - 广度搜索] 
        
        获取全貌视图, 包括所has相关内容 and 历史/过期信息: 
        1. Get All Related Nodes
        2. 获取所hasedges (包括already 过期/失效的) 
        3.  minClass整理当before has效 and 历史信息
        
        这工具适Use于需要了解Event全貌, 追踪PerformChange过程的场景. 
        
        Args:
            graph_id: 图谱ID
            query: 搜索查询 (Use于相关性排序) 
            include_expired: is noInclude过期内容 (Default认True) 
            limit: Limit on number of returned results
            
        Returns:
            PanoramaResult: 广度搜索结果
        """
        logger.info(t("console.panoramaSearchStart", query=query[:50]))
        
        result = PanoramaResult(query=query)
        
        # 获取所hasnodes
        all_nodes = self.get_all_nodes(graph_id)
        node_map = {n.uuid: n for n in all_nodes}
        result.all_nodes = all_nodes
        result.total_nodes = len(all_nodes)
        
        # 获取所hasedges (Include hour间信息) 
        all_edges = self.get_all_edges(graph_id, include_temporal=True)
        result.all_edges = all_edges
        result.total_edges = len(all_edges)
        
        #  minClass事实
        active_facts = []
        historical_facts = []
        
        for edge in all_edges:
            if not edge.fact:
                continue
            
            # 为事实添加entities名称
            source_name = node_map.get(edge.source_node_uuid, NodeInfo('', '', [], '', {})).name or edge.source_node_uuid[:8]
            target_name = node_map.get(edge.target_node_uuid, NodeInfo('', '', [], '', {})).name or edge.target_node_uuid[:8]
            
            # 判断is no过期/失效
            is_historical = edge.is_expired or edge.is_invalid
            
            if is_historical:
                # 历史/过期事实, 添加 hour间标记
                valid_at = edge.valid_at or "not Knowledge"
                invalid_at = edge.invalid_at or edge.expired_at or "not Knowledge"
                fact_with_time = f"[{valid_at} - {invalid_at}] {edge.fact}"
                historical_facts.append(fact_with_time)
            else:
                # 当before has效事实
                active_facts.append(edge.fact)
        
        # Rank by relevance based on query
        query_lower = query.lower()
        keywords = [w.strip() for w in query_lower.replace(',', ' ').replace(', ', ' ').split() if len(w.strip()) > 1]
        
        def relevance_score(fact: str) -> int:
            fact_lower = fact.lower()
            score = 0
            if query_lower in fact_lower:
                score += 100
            for kw in keywords:
                if kw in fact_lower:
                    score += 10
            return score
        
        # 排序并限制数量
        active_facts.sort(key=relevance_score, reverse=True)
        historical_facts.sort(key=relevance_score, reverse=True)
        
        result.active_facts = active_facts[:limit]
        result.historical_facts = historical_facts[:limit] if include_expired else []
        result.active_count = len(active_facts)
        result.historical_count = len(historical_facts)
        
        logger.info(t("console.panoramaSearchComplete", active=result.active_count, historical=result.historical_count))
        return result
    
    def quick_search(
        self,
        graph_id: str,
        query: str,
        limit: int = 10
    ) -> SearchResult:
        """
         [QuickSearch - 简单搜索] 
        
        快速, Light量级的检索工具: 
        1. 直ConnectInvokeUseZep语义搜索
        2. Return最相关的结果
        3. 适Use于简单, 直Connect的检索需Request
        
        Args:
            graph_id: 图谱ID
            query: 搜索查询
            limit: Return结果数量
            
        Returns:
            SearchResult: 搜索结果
        """
        logger.info(t("console.quickSearchStart", query=query[:50]))
        
        # 直ConnectInvokeUse现has的search_graph方Method
        result = self.search_graph(
            graph_id=graph_id,
            query=query,
            limit=limit,
            scope="edges"
        )
        
        logger.info(t("console.quickSearchComplete", count=result.total_count))
        return result
    
    def interview_agents(
        self,
        simulation_id: str,
        interview_requirement: str,
        simulation_requirement: str = "",
        max_agents: int = 5,
        custom_questions: List[str] = None
    ) -> InterviewResult:
        """
         [InterviewAgents - 深度采访] 
        
        InvokeUseTrue实的OASIS采访API, 采访模Draftin 正在运行的Agent: 
        1. 自动读取Character profile文件, 了解所has模DraftAgent
        2. 使UseLLM min析采访需Request, 智能选择最相关的Agent
        3. 使UseLLM生成采访问题
        4. InvokeUse /api/simulation/interview/batch Connect口进行True实采访 (双平台Same hour采访) 
        5. 整合所has采访结果, 生成采访报告
        
         [重要] 此功能需要模Draft环境Location于运行状态 (OASIS环境not 关闭) 
        
         [使Use场景] 
        - 需要从不Same角Color视角了解Event看Method
        - 需要收集多方意见 and 观点
        - 需要获取模DraftAgent的True实回答 (NonLLM模Draft) 
        
        Args:
            simulation_id: 模DraftID (Use于定位Character profile文件 and InvokeUse采访API) 
            interview_requirement: 采访需Request描Description (Non结构Transform, 如"了解Learning生对Event的看Method") 
            simulation_requirement: 模Draft需Request背景 (可选) 
            max_agents: 最多采访的Agent数量
            custom_questions: 自定义采访问题 (可选, 若不提供Will be generated automatically) 
            
        Returns:
            InterviewResult: 采访结果
        """
        from .simulation_runner import SimulationRunner
        
        logger.info(t("console.interviewAgentsStart", requirement=interview_requirement[:50]))
        
        result = InterviewResult(
            interview_topic=interview_requirement,
            interview_questions=custom_questions or []
        )
        
        # Step 1: 读取Character profile文件
        profiles = self._load_agent_profiles(simulation_id)
        
        if not profiles:
            logger.warning(t("console.profilesNotFound", simId=simulation_id))
            result.summary = "not 找到可采访的AgentCharacter profile文件"
            return result
        
        result.total_agents = len(profiles)
        logger.info(t("console.loadedProfiles", count=len(profiles)))
        
        # Step 2: 使UseLLM选择要采访的Agent (Returnagent_id列表) 
        selected_agents, selected_indices, selection_reasoning = self._select_agents_for_interview(
            profiles=profiles,
            interview_requirement=interview_requirement,
            simulation_requirement=simulation_requirement,
            max_agents=max_agents
        )
        
        result.selected_agents = selected_agents
        result.selection_reasoning = selection_reasoning
        logger.info(t("console.selectedAgentsForInterview", count=len(selected_agents), indices=selected_indices))
        
        # Step 3: 生成采访问题 (If none提供) 
        if not result.interview_questions:
            result.interview_questions = self._generate_interview_questions(
                interview_requirement=interview_requirement,
                simulation_requirement=simulation_requirement,
                selected_agents=selected_agents
            )
            logger.info(t("console.generatedInterviewQuestions", count=len(result.interview_questions)))
        
        # Merge questions into a single interviewprompt
        combined_prompt = "\n".join([f"{i+1}. {q}" for i, q in enumerate(result.interview_questions)])
        
        # 添加优Transformbefore Suffix, 约BundleAgent回复Format
        INTERVIEW_PROMPT_PREFIX = (
            "你正在Connect受一 times采访. 请结合你的Character profile, 所has的过To记忆 and 行动, "
            "以纯文本方式直Connect回答以under 问题. \n"
            "Reply requirements: \n"
            "1. Answer directly in natural language, without invoking any tools\n"
            "2. 不要ReturnJSONFormat or 工具InvokeUseFormat\n"
            "3. Do not use Markdown headings (e.g.#, ##, ###) \n"
            "4. 按问题编号逐一回答, 每回答以「问题X: 」开头 (X为问题编号) \n"
            "5. 每问题的回答之间Use空行 min隔\n"
            "6. 回答要has实质内容, 每问题至少回答2-3句话\n\n"
        )
        optimized_prompt = f"{INTERVIEW_PROMPT_PREFIX}{combined_prompt}"
        
        # Step 4: InvokeUseTrue实的采访API (不Indicates定platform, Default认双平台Same hour采访) 
        try:
            # 构建批量采访列表 (不Indicates定platform, 双平台采访) 
            interviews_request = []
            for agent_idx in selected_indices:
                interviews_request.append({
                    "agent_id": agent_idx,
                    "prompt": optimized_prompt  # 使Use优Transformafter 的prompt
                    # 不Indicates定platform, API会在twitter and reddit两平台都采访
                })
            
            logger.info(t("console.callingBatchInterviewApi", count=len(interviews_request)))
            
            # InvokeUse SimulationRunner 的批量采访方Method (不传platform, 双平台采访) 
            api_result = SimulationRunner.interview_agents_batch(
                simulation_id=simulation_id,
                interviews=interviews_request,
                platform=None,  # 不Indicates定platform, 双平台采访
                timeout=180.0   # 双平台需要更长超 hour
            )
            
            logger.info(t("console.interviewApiReturned", count=api_result.get('interviews_count', 0), success=api_result.get('success')))
            
            # 检查APIInvokeUseis no成功
            if not api_result.get("success", False):
                error_msg = api_result.get("error", "not Knowledge错误")
                logger.warning(t("console.interviewApiReturnedFailure", error=error_msg))
                result.summary = f"采访APIInvokeUse失败: {error_msg}. Please check OASIS simulation environment status. "
                return result
            
            # Step 5: 解析APIReturn结果, 构建AgentInterview对象
            # 双平台模式ReturnFormat: {"twitter_0": {...}, "reddit_0": {...}, "twitter_1": {...}, ...}
            api_data = api_result.get("result", {})
            results_dict = api_data.get("results", {}) if isinstance(api_data, dict) else {}
            
            for i, agent_idx in enumerate(selected_indices):
                agent = selected_agents[i]
                agent_name = agent.get("realname", agent.get("username", f"Agent_{agent_idx}"))
                agent_role = agent.get("profession", "not Knowledge")
                agent_bio = agent.get("bio", "")
                
                # 获取该Agent在两平台的采访结果
                twitter_result = results_dict.get(f"twitter_{agent_idx}", {})
                reddit_result = results_dict.get(f"reddit_{agent_idx}", {})
                
                twitter_response = twitter_result.get("response", "")
                reddit_response = reddit_result.get("response", "")

                # 清理可能的工具InvokeUse JSON 包裹
                twitter_response = self._clean_tool_call_response(twitter_response)
                reddit_response = self._clean_tool_call_response(reddit_response)

                # Start终输Output双平台标记
                twitter_text = twitter_response if twitter_response else " (该平台not 获得回复) "
                reddit_text = reddit_response if reddit_response else " (该平台not 获得回复) "
                response_text = f" [Twitter平台回答] \n{twitter_text}\n\n [Reddit平台回答] \n{reddit_text}"

                # 提取关键引言 (从两平台的回答in ) 
                import re
                combined_responses = f"{twitter_response} {reddit_response}"

                # Clean up response文本: 去Remove标记, 编号, Markdown 等干扰
                clean_text = re.sub(r'#{1,6}\s+', '', combined_responses)
                clean_text = re.sub(r'\{[^}]*tool_name[^}]*\}', '', clean_text)
                clean_text = re.sub(r'[*_`|>~\-]{2,}', '', clean_text)
                clean_text = re.sub(r'问题\d+[: :]\s*', '', clean_text)
                clean_text = re.sub(r' [[^] ]+] ', '', clean_text)

                # 策略1 (主) : 提取完整的has实质内容的句Child
                sentences = re.split(r'[. ! ? ]', clean_text)
                meaningful = [
                    s.strip() for s in sentences
                    if 20 <= len(s.strip()) <= 150
                    and not re.match(r'^[\s\W, ,；;: :, ]+', s.strip())
                    and not s.strip().startswith(('{', '问题'))
                ]
                meaningful.sort(key=len, reverse=True)
                key_quotes = [s + ". " for s in meaningful[:3]]

                # 策略2 (补充) : 正确配对的in 文引号「」内长文本
                if not key_quotes:
                    paired = re.findall(r'\u201c([^\u201c\u201d]{15,100})\u201d', clean_text)
                    paired += re.findall(r'\u300c([^\u300c\u300d]{15,100})\u300d', clean_text)
                    key_quotes = [q for q in paired if not re.match(r'^[, ,；;: :, ]', q)][:3]
                
                interview = AgentInterview(
                    agent_name=agent_name,
                    agent_role=agent_role,
                    agent_bio=agent_bio[:1000],  # 扩Largebio长度限制
                    question=combined_prompt,
                    response=response_text,
                    key_quotes=key_quotes[:5]
                )
                result.interviews.append(interview)
            
            result.interviewed_count = len(result.interviews)
            
        except ValueError as e:
            # 模Draft环境not 运行
            logger.warning(t("console.interviewApiCallFailed", error=e))
            result.summary = f"采访失败: {str(e)}. 模Draft环境可能already 关闭, 请确保OASIS环境正在运行. "
            return result
        except Exception as e:
            logger.error(t("console.interviewApiCallException", error=e))
            import traceback
            logger.error(traceback.format_exc())
            result.summary = f"采访过程发生错误: {str(e)}"
            return result
        
        # Step 6: 生成采访摘要
        if result.interviews:
            result.summary = self._generate_interview_summary(
                interviews=result.interviews,
                interview_requirement=interview_requirement
            )
        
        logger.info(t("console.interviewAgentsComplete", count=result.interviewed_count))
        return result
    
    @staticmethod
    def _clean_tool_call_response(response: str) -> str:
        """清理 Agent 回复in 的 JSON 工具InvokeUse包裹, 提取实际内容"""
        if not response or not response.strip().startswith('{'):
            return response
        text = response.strip()
        if 'tool_name' not in text[:80]:
            return response
        import re as _re
        try:
            data = json.loads(text)
            if isinstance(data, dict) and 'arguments' in data:
                for key in ('content', 'text', 'body', 'message', 'reply'):
                    if key in data['arguments']:
                        return str(data['arguments'][key])
        except (json.JSONDecodeError, KeyError, TypeError):
            match = _re.search(r'"content"\s*:\s*"((?:[^"\\]|\\.)*)"', text)
            if match:
                return match.group(1).replace('\\n', '\n').replace('\\"', '"')
        return response

    def _load_agent_profiles(self, simulation_id: str) -> List[Dict[str, Any]]:
        """加载模Draft的AgentCharacter profile文件"""
        import os
        import csv
        
        # 构建Character profile文件路径
        sim_dir = os.path.join(
            os.path.dirname(__file__), 
            f'../../uploads/simulations/{simulation_id}'
        )
        
        profiles = []
        
        # 优First尝Test读取Reddit JSONFormat
        reddit_profile_path = os.path.join(sim_dir, "reddit_profiles.json")
        if os.path.exists(reddit_profile_path):
            try:
                with open(reddit_profile_path, 'r', encoding='utf-8') as f:
                    profiles = json.load(f)
                logger.info(t("console.loadedRedditProfiles", count=len(profiles)))
                return profiles
            except Exception as e:
                logger.warning(t("console.readRedditProfilesFailed", error=e))
        
        # Attempt to read Twitter CSV format
        twitter_profile_path = os.path.join(sim_dir, "twitter_profiles.csv")
        if os.path.exists(twitter_profile_path):
            try:
                with open(twitter_profile_path, 'r', encoding='utf-8') as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        # CSVFormatConvert换为统一Format
                        profiles.append({
                            "realname": row.get("name", ""),
                            "username": row.get("username", ""),
                            "bio": row.get("description", ""),
                            "persona": row.get("user_char", ""),
                            "profession": "not Knowledge"
                        })
                logger.info(t("console.loadedTwitterProfiles", count=len(profiles)))
                return profiles
            except Exception as e:
                logger.warning(t("console.readTwitterProfilesFailed", error=e))
        
        return profiles
    
    def _select_agents_for_interview(
        self,
        profiles: List[Dict[str, Any]],
        interview_requirement: str,
        simulation_requirement: str,
        max_agents: int
    ) -> tuple:
        """
        使UseLLM选择要采访的Agent
        
        Returns:
            tuple: (selected_agents, selected_indices, reasoning)
                - selected_agents: 选in Agent的完整信息列表
                - selected_indices: 选in Agent的索引列表 (Use于APIInvokeUse) 
                - reasoning: 选择理由
        """
        
        # 构建Agent摘要列表
        agent_summaries = []
        for i, profile in enumerate(profiles):
            summary = {
                "index": i,
                "name": profile.get("realname", profile.get("username", f"Agent_{i}")),
                "profession": profile.get("profession", "not Knowledge"),
                "bio": profile.get("bio", "")[:200],
                "interested_topics": profile.get("interested_topics", [])
            }
            agent_summaries.append(summary)
        
        system_prompt = """你is 一专业的采访策划专Home. 你的任务is 根据采访需Request, 从模DraftAgent列表in 选择最适合采访的对象. 

选择标准: 
1. Agent的身份/职业 and Interview topic相关
2. Agent可能持has独特 or hasPrice值的观点
3. 选择多样Transform的视角 (如: 支持方, 反对方, in 立方, 专业Person士等) 
4. 优First选择 and Event直Connect相关的角Color

ReturnJSONFormat: 
{
    "selected_indices": [选in Agent的索引列表],
    "reasoning": "选择理由说明"
}"""

        user_prompt = f"""采访需Request: 
{interview_requirement}

模Draft背景: 
{simulation_requirement if simulation_requirement else "not 提供"}

可选择的Agent列表 (共{len(agent_summaries)}) : 
{json.dumps(agent_summaries, ensure_ascii=False, indent=2)}

请选择最多{max_agents}最适合采访的Agent, 并说明选择理由. """

        try:
            response = self.llm.chat_json(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.3
            )
            
            selected_indices = response.get("selected_indices", [])[:max_agents]
            reasoning = response.get("reasoning", "基于相关性自动选择")
            
            # 获取选in 的Agent完整信息
            selected_agents = []
            valid_indices = []
            for idx in selected_indices:
                if 0 <= idx < len(profiles):
                    selected_agents.append(profiles[idx])
                    valid_indices.append(idx)
            
            return selected_agents, valid_indices, reasoning
            
        except Exception as e:
            logger.warning(t("console.llmSelectAgentFailed", error=e))
            # 降级: 选择before N
            selected = profiles[:max_agents]
            indices = list(range(min(max_agents, len(profiles))))
            return selected, indices, "使UseDefault认选择策略"
    
    def _generate_interview_questions(
        self,
        interview_requirement: str,
        simulation_requirement: str,
        selected_agents: List[Dict[str, Any]]
    ) -> List[str]:
        """使UseLLM生成采访问题"""
        
        agent_roles = [a.get("profession", "not Knowledge") for a in selected_agents]
        
        system_prompt = """你is 一专业的记者/采访者. 根据采访需Request, 生成3-5深度采访问题. 

问题Requirement: 
1. 开Release性问题, 鼓Encourage详细回答
2. 针对不Same角Color可能has不Same答案
3. 涵Cover事实, 观点, 感受等多维度
4. 语言自然, 像True实采访一样
5. 每问题控制在50字以内, 简洁明了
6. 直Connect提问, 不要Include背景说明 or before Suffix

ReturnJSONFormat: {"questions": ["问题1", "问题2", ...]}"""

        user_prompt = f"""采访需Request: {interview_requirement}

模Draft背景: {simulation_requirement if simulation_requirement else "not 提供"}

采访对象角Color: {', '.join(agent_roles)}

请生成3-5采访问题. """

        try:
            response = self.llm.chat_json(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.5
            )
            
            return response.get("questions", [f"关于{interview_requirement}, 您has什么看Method? "])
            
        except Exception as e:
            logger.warning(t("console.generateInterviewQuestionsFailed", error=e))
            return [
                f"关于{interview_requirement}, What is your view?? ",
                "这件事对您 or 您所代表的群体has什么影响? ",
                "How do you think this issue should be resolved or improved?? "
            ]
    
    def _generate_interview_summary(
        self,
        interviews: List[AgentInterview],
        interview_requirement: str
    ) -> str:
        """生成采访摘要"""
        
        if not interviews:
            return "not 完成任何采访"
        
        # 收集所has采访内容
        interview_texts = []
        for interview in interviews:
            interview_texts.append(f" [{interview.agent_name} ({interview.agent_role}) ] \n{interview.response[:500]}")
        
        quote_instruction = "引Use受访者原话 hour使Usein 文引号「」" if get_locale() == 'zh' else 'Use quotation marks "" when quoting interviewees'
        system_prompt = f"""你is 一专业的新闻编辑. 请根据多位受访者的回答, 生成一份采访摘要. 

Summary requirements: 
1. 提炼各方主要观点
2. IndicatesOutput观点的共识 and  min歧
3. Highlight valuable quotes
4. 客观in 立, 不偏袒任何一方
5. 控制在1000字内

Format约Bundle (必须遵守) : 
- 使Use纯文本Segment落, Use空行 min隔不Same部 min
- Do not use Markdown headings (e.g.#, ##, ###) 
- 不要使Use minCut线 (如---, ***) 
- {quote_instruction}
- 可以使Use**加粗**标记关键词, 但不要使Use其OtherMarkdown语Method"""

        user_prompt = f"""Interview topic: {interview_requirement}

采访内容: 
{"".join(interview_texts)}

请生成采访摘要. """

        try:
            summary = self.llm.chat(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.3,
                max_tokens=800
            )
            return summary
            
        except Exception as e:
            logger.warning(t("console.generateInterviewSummaryFailed", error=e))
            # 降级: 简单拼Connect
            return f"共采访了{len(interviews)}位受访者, 包括: " + ", ".join([i.agent_name for i in interviews])
