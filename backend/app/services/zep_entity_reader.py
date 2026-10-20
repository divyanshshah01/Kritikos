"""
Zepentities读取 and 过滤服务
从Zep图谱in 读取nodes, 筛选OutputSymbol合预定义entitiesClass型的nodes
"""

from typing import Dict, Any, List, Optional, Set, Callable, TypeVar
from dataclasses import dataclass, field
from zep_cloud import NotFoundError

from ..config import Config
from ..utils.logger import get_logger
from ..utils.zep_paging import fetch_all_nodes, fetch_all_edges
from ..utils.zep import call_zep_read_with_retry, get_zep_client

logger = get_logger('mirofish.zep_entity_reader')

# Use于泛型ReturnClass型
T = TypeVar('T')


@dataclass
class EntityNode:
    """entitiesnodesData structure"""
    uuid: str
    name: str
    labels: List[str]
    summary: str
    attributes: Dict[str, Any]
    # 相关的edges信息
    related_edges: List[Dict[str, Any]] = field(default_factory=list)
    # 相关的其Othernodes信息
    related_nodes: List[Dict[str, Any]] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "uuid": self.uuid,
            "name": self.name,
            "labels": self.labels,
            "summary": self.summary,
            "attributes": self.attributes,
            "related_edges": self.related_edges,
            "related_nodes": self.related_nodes,
        }
    
    def get_entity_type(self) -> Optional[str]:
        """获取entitiesClass型 (排除Default认的Entity标签) """
        for label in self.labels:
            if label not in ["Entity", "Node"]:
                return label
        return None


@dataclass
class FilteredEntities:
    """过滤after 的entities集合"""
    entities: List[EntityNode]
    entity_types: Set[str]
    total_count: int
    filtered_count: int
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "entities": [e.to_dict() for e in self.entities],
            "entity_types": list(self.entity_types),
            "total_count": self.total_count,
            "filtered_count": self.filtered_count,
        }


class ZepEntityReader:
    """
    Zepentities读取 and 过滤服务
    
    主要功能: 
    1. 从Zep图谱读取所hasnodes
    2. 筛选OutputSymbol合预定义entitiesClass型的nodes (Labels不只is Entity的nodes) 
    3. 获取每entities的相关edges and 关联nodes信息
    """
    
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or Config.ZEP_API_KEY
        if not self.api_key:
            raise ValueError("ZEP_API_KEY not 配置")
        
        self.client = get_zep_client(self.api_key)
    
    def _call_with_retry(
        self, 
        func: Callable[[], T], 
        operation_name: str,
        max_retries: int = 3,
        initial_delay: float = 2.0
    ) -> T:
        """
        With重Test机制的Zep APIInvokeUse
        
        Args:
            func: 要执行的函数 (none参数的lambda or callable) 
            operation_name: 操作名称, Use于 day志
            max_retries: 最Large重Test times数 (Default认3 times, 即最多尝Test3 times) 
            initial_delay: 初Start延迟s数
            
        Returns:
            APIInvokeUse结果
        """
        return call_zep_read_with_retry(
            func,
            operation_name=operation_name,
            max_attempts=max_retries,
            initial_delay=initial_delay,
        )
    
    def get_all_nodes(self, graph_id: str) -> List[Dict[str, Any]]:
        """
        获取图谱的所hasnodes ( min页获取) 

        Args:
            graph_id: 图谱ID

        Returns:
            nodes列表
        """
        logger.info(f"获取图谱 {graph_id} 的所hasnodes...")

        nodes = fetch_all_nodes(self.client, graph_id)

        nodes_data = []
        for node in nodes:
            nodes_data.append({
                "uuid": getattr(node, 'uuid_', None) or getattr(node, 'uuid', ''),
                "name": node.name or "",
                "labels": node.labels or [],
                "summary": node.summary or "",
                "attributes": node.attributes or {},
            })

        logger.info(f"共获取 {len(nodes_data)} nodes")
        return nodes_data

    def get_all_edges(self, graph_id: str) -> List[Dict[str, Any]]:
        """
        获取图谱All edges of ( min页获取) 

        Args:
            graph_id: 图谱ID

        Returns:
            edges列表
        """
        logger.info(f"获取图谱 {graph_id} All edges of...")

        edges = fetch_all_edges(self.client, graph_id)

        edges_data = []
        for edge in edges:
            edges_data.append({
                "uuid": getattr(edge, 'uuid_', None) or getattr(edge, 'uuid', ''),
                "name": edge.name or "",
                "fact": edge.fact or "",
                "source_node_uuid": edge.source_node_uuid,
                "target_node_uuid": edge.target_node_uuid,
                "attributes": edge.attributes or {},
            })

        logger.info(f"共获取 {len(edges_data)}  itemsedges")
        return edges_data
    
    def get_node_edges(
        self,
        node_uuid: str,
        *,
        graph_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Get Related Edges of Specified Node. 

        Zep Cloud 3.25 的 ``graph.node.get_edges`` 实测只Returnnodes作为
        source 的edges, 尽管文档将其描Description为"all edges". 需要完整on under 文 hour必须
        提供 graph_id, 以全图 min页after Same hour筛选 incoming  and  outgoing edges. 
        
        Args:
            node_uuid: nodesUUID
            graph_id: 图谱ID；提供 hour保证Return双向完整relations
            
        Returns:
            edges列表
        """
        try:
            if graph_id:
                return [
                    edge
                    for edge in self.get_all_edges(graph_id)
                    if edge["source_node_uuid"] == node_uuid
                    or edge["target_node_uuid"] == node_uuid
                ]

            # 使Use重Test机制InvokeUseZep API
            edges = self._call_with_retry(
                func=lambda: self.client.graph.node.get_edges(node_uuid=node_uuid),
                operation_name=f"获取nodesedges(node={node_uuid[:8]}...)"
            )
            
            edges_data = []
            for edge in edges:
                edges_data.append({
                    "uuid": getattr(edge, 'uuid_', None) or getattr(edge, 'uuid', ''),
                    "name": edge.name or "",
                    "fact": edge.fact or "",
                    "source_node_uuid": edge.source_node_uuid,
                    "target_node_uuid": edge.target_node_uuid,
                    "attributes": edge.attributes or {},
                })
            
            return edges_data
        except Exception as e:
            # An empty edge list is valid data. Authentication, permission and
            # transport failures must not be made indistinguishable from it.
            logger.error(f"获取nodes {node_uuid} 的edges失败: {str(e)}")
            raise
    
    def filter_defined_entities(
        self, 
        graph_id: str,
        defined_entity_types: Optional[List[str]] = None,
        enrich_with_edges: bool = True
    ) -> FilteredEntities:
        """
        筛选OutputSymbol合预定义entitiesClass型的nodes
        
        Filtering logic: 
        - 如果nodes的Labels只has一"Entity", 说明这entities不Symbol合我们预定义的Class型, 跳过
        - 如果nodes的LabelsInclude除"Entity" and "Node"Tags Outside Indicate Conformance to Predefined Types, Retained
        
        Args:
            graph_id: 图谱ID
            defined_entity_types: 预定义的Entity Type List (可选, 如果提供则只保留这些Class型) 
            enrich_with_edges: is no获取每entities的相关edges信息
            
        Returns:
            FilteredEntities: 过滤after 的entities集合
        """
        logger.info(f"开Start筛选图谱 {graph_id} 的entities...")
        
        # 获取所hasnodes
        all_nodes = self.get_all_nodes(graph_id)
        total_count = len(all_nodes)
        
        # 获取所hasedges (Use于after 续关联Search) 
        all_edges = self.get_all_edges(graph_id) if enrich_with_edges else []
        
        # 构建nodesUUID到nodes数据的Mapping
        node_map = {n["uuid"]: n for n in all_nodes}
        
        # 筛选Meets criteria的entities
        filtered_entities = []
        entity_types_found = set()
        
        for node in all_nodes:
            labels = node.get("labels", [])
            
            # Filtering logic: Labels必须Include除"Entity" and "Node"之外的标签
            custom_labels = [l for l in labels if l not in ["Entity", "Node"]]
            
            if not custom_labels:
                # 只hasDefault认标签, 跳过
                continue
            
            # 如果Indicates定了预定义Class型, 检查is no匹配
            if defined_entity_types:
                matching_labels = [l for l in custom_labels if l in defined_entity_types]
                if not matching_labels:
                    continue
                entity_type = matching_labels[0]
            else:
                entity_type = custom_labels[0]
            
            entity_types_found.add(entity_type)
            
            # Createentitiesnodes对象
            entity = EntityNode(
                uuid=node["uuid"],
                name=node["name"],
                labels=labels,
                summary=node["summary"],
                attributes=node["attributes"],
            )
            
            # 获取相关edges and nodes
            if enrich_with_edges:
                related_edges = []
                related_node_uuids = set()
                
                for edge in all_edges:
                    if edge["source_node_uuid"] == node["uuid"]:
                        related_edges.append({
                            "direction": "outgoing",
                            "edge_name": edge["name"],
                            "fact": edge["fact"],
                            "target_node_uuid": edge["target_node_uuid"],
                        })
                        related_node_uuids.add(edge["target_node_uuid"])
                    elif edge["target_node_uuid"] == node["uuid"]:
                        related_edges.append({
                            "direction": "incoming",
                            "edge_name": edge["name"],
                            "fact": edge["fact"],
                            "source_node_uuid": edge["source_node_uuid"],
                        })
                        related_node_uuids.add(edge["source_node_uuid"])
                
                entity.related_edges = related_edges
                
                # 获取关联nodes的基本信息
                related_nodes = []
                for related_uuid in related_node_uuids:
                    if related_uuid in node_map:
                        related_node = node_map[related_uuid]
                        related_nodes.append({
                            "uuid": related_node["uuid"],
                            "name": related_node["name"],
                            "labels": related_node["labels"],
                            "summary": related_node.get("summary", ""),
                        })
                
                entity.related_nodes = related_nodes
            
            filtered_entities.append(entity)
        
        logger.info(f"筛选完成: Total Nodes {total_count}, Meets criteria {len(filtered_entities)}, "
                   f"entitiesClass型: {entity_types_found}")
        
        return FilteredEntities(
            entities=filtered_entities,
            entity_types=entity_types_found,
            total_count=total_count,
            filtered_count=len(filtered_entities),
        )
    
    def get_entity_with_context(
        self, 
        graph_id: str, 
        entity_uuid: str
    ) -> Optional[EntityNode]:
        """
        获取单entities and 其完整on under 文 (edges and 关联nodes, With重Test机制) 
        
        Args:
            graph_id: 图谱ID
            entity_uuid: entitiesUUID
            
        Returns:
            EntityNode or None
        """
        try:
            # 使Use重Test机制获取nodes
            node = self._call_with_retry(
                func=lambda: self.client.graph.node.get(uuid_=entity_uuid),
                operation_name=f"获取nodes详情(uuid={entity_uuid[:8]}...)"
            )
            
            if not node:
                return None
            
            # 获取nodes的edges
            edges = self.get_node_edges(entity_uuid, graph_id=graph_id)
            
            # 获取所hasnodesUse于关联Search
            all_nodes = self.get_all_nodes(graph_id)
            node_map = {n["uuid"]: n for n in all_nodes}
            
            # Location理相关edges and nodes
            related_edges = []
            related_node_uuids = set()
            
            for edge in edges:
                if edge["source_node_uuid"] == entity_uuid:
                    related_edges.append({
                        "direction": "outgoing",
                        "edge_name": edge["name"],
                        "fact": edge["fact"],
                        "target_node_uuid": edge["target_node_uuid"],
                    })
                    related_node_uuids.add(edge["target_node_uuid"])
                else:
                    related_edges.append({
                        "direction": "incoming",
                        "edge_name": edge["name"],
                        "fact": edge["fact"],
                        "source_node_uuid": edge["source_node_uuid"],
                    })
                    related_node_uuids.add(edge["source_node_uuid"])
            
            # 获取关联nodes信息
            related_nodes = []
            for related_uuid in related_node_uuids:
                if related_uuid in node_map:
                    related_node = node_map[related_uuid]
                    related_nodes.append({
                        "uuid": related_node["uuid"],
                        "name": related_node["name"],
                        "labels": related_node["labels"],
                        "summary": related_node.get("summary", ""),
                    })
            
            return EntityNode(
                uuid=getattr(node, 'uuid_', None) or getattr(node, 'uuid', ''),
                name=node.name or "",
                labels=node.labels or [],
                summary=node.summary or "",
                attributes=node.attributes or {},
                related_edges=related_edges,
                related_nodes=related_nodes,
            )
            
        except NotFoundError:
            return None
        except Exception as e:
            # Only an actual Zep 404 means "entity not found". Propagate 401,
            # 403 and exhausted transport errors so callers cannot prepare a
            # simulation with silently incomplete graph context.
            logger.error(f"获取entities {entity_uuid} 失败: {str(e)}")
            raise
    
    def get_entities_by_type(
        self, 
        graph_id: str, 
        entity_type: str,
        enrich_with_edges: bool = True
    ) -> List[EntityNode]:
        """
        获取Indicates定Class型的所hasentities
        
        Args:
            graph_id: 图谱ID
            entity_type: entitiesClass型 (如 "Student", "PublicFigure" 等) 
            enrich_with_edges: is no获取相关edges信息
            
        Returns:
            entities列表
        """
        result = self.filter_defined_entities(
            graph_id=graph_id,
            defined_entity_types=[entity_type],
            enrich_with_edges=enrich_with_edges
        )
        return result.entities
