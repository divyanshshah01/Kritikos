"""
Zep Entity Reader and Filter Service
Reads nodes from the Zep knowledge graph and filters matching entity types for simulations.
"""

from typing import Dict, Any, List, Optional, Set, Callable, TypeVar
from dataclasses import dataclass, field
from zep_cloud import NotFoundError

from ..config import Config
from ..utils.logger import get_logger
from ..utils.zep_paging import fetch_all_nodes, fetch_all_edges
from ..utils.zep import call_zep_read_with_retry, get_zep_client

logger = get_logger('kritikos.zep_entity_reader')

# Generic return type
T = TypeVar('T')


@dataclass
class EntityNode:
    """Entity node data structure"""
    uuid: str
    name: str
    labels: List[str]
    summary: str
    attributes: Dict[str, Any]
    # Related edge information
    related_edges: List[Dict[str, Any]] = field(default_factory=list)
    # Related neighbor nodes
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
        """Get entity type excluding default Entity and Node labels"""
        for label in self.labels:
            if label not in ["Entity", "Node"]:
                return label
        return None


@dataclass
class FilteredEntities:
    """Collection of filtered entities"""
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
    Zep Entity Reader and Filter Service
    
    Key capabilities:
    1. Reads all nodes from a Zep knowledge graph
    2. Filters nodes matching predefined or custom entity types
    3. Retrieves associated edges and neighbor node information
    """
    
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or Config.ZEP_API_KEY
        if not self.api_key:
            raise ValueError("ZEP_API_KEY is not configured")
        
        self.client = get_zep_client(self.api_key)
    
    def _call_with_retry(
        self, 
        func: Callable[[], T], 
        operation_name: str,
        max_retries: int = 3,
        initial_delay: float = 2.0
    ) -> T:
        """
        Invoke Zep API with retry mechanism
        
        Args:
            func: Function to execute
            operation_name: Operation name for logging
            max_retries: Maximum attempts
            initial_delay: Initial backoff delay in seconds
            
        Returns:
            API call result
        """
        return call_zep_read_with_retry(
            func,
            operation_name=operation_name,
            max_attempts=max_retries,
            initial_delay=initial_delay,
        )
    
    def get_all_nodes(self, graph_id: str) -> List[Dict[str, Any]]:
        """
        Retrieve all nodes for a graph (with automatic pagination)

        Args:
            graph_id: Knowledge graph ID

        Returns:
            List of node dictionaries
        """
        logger.info(f"Retrieving all nodes for graph {graph_id}...")

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

        logger.info(f"Retrieved {len(nodes_data)} nodes")
        return nodes_data

    def get_all_edges(self, graph_id: str) -> List[Dict[str, Any]]:
        """
        Retrieve all edges for a graph (with automatic pagination)

        Args:
            graph_id: Knowledge graph ID

        Returns:
            List of edge dictionaries
        """
        logger.info(f"Retrieving all edges for graph {graph_id}...")

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

        logger.info(f"Retrieved {len(edges_data)} edges")
        return edges_data
    
    def get_node_edges(
        self,
        node_uuid: str,
        *,
        graph_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Get related edges for a specified node.

        Args:
            node_uuid: Node UUID
            graph_id: Knowledge graph ID
            
        Returns:
            List of edge dictionaries
        """
        try:
            if graph_id:
                return [
                    edge
                    for edge in self.get_all_edges(graph_id)
                    if edge["source_node_uuid"] == node_uuid
                    or edge["target_node_uuid"] == node_uuid
                ]

            edges = self._call_with_retry(
                func=lambda: self.client.graph.node.get_edges(node_uuid=node_uuid),
                operation_name=f"get node edges (node={node_uuid[:8]}...)"
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
            logger.error(f"Failed to get edges for node {node_uuid}: {str(e)}")
            raise
    
    def filter_defined_entities(
        self, 
        graph_id: str,
        defined_entity_types: Optional[List[str]] = None,
        enrich_with_edges: bool = True
    ) -> FilteredEntities:
        """
        Filter and extract entities from the graph.
        
        Filtering logic:
        - Prioritize nodes with custom labels beyond generic Entity and Node.
        - If defined_entity_types is provided, match against those types.
        - If strict filtering yields 0 entities but nodes exist, fallback to all available nodes.
        
        Args:
            graph_id: Knowledge graph ID
            defined_entity_types: Optional list of predefined entity types to filter by
            enrich_with_edges: Whether to enrich each entity with edge and relationship data
            
        Returns:
            FilteredEntities collection
        """
        logger.info(f"Filtering entities for graph {graph_id}...")
        
        all_nodes = self.get_all_nodes(graph_id)
        total_count = len(all_nodes)
        
        all_edges = self.get_all_edges(graph_id) if enrich_with_edges else []
        node_map = {n["uuid"]: n for n in all_nodes}
        
        filtered_entities = []
        entity_types_found = set()
        
        for node in all_nodes:
            labels = node.get("labels", [])
            custom_labels = [l for l in labels if l not in ["Entity", "Node"]]
            
            if not custom_labels:
                continue
            
            if defined_entity_types:
                matching_labels = [l for l in custom_labels if l in defined_entity_types]
                if not matching_labels:
                    continue
                entity_type = matching_labels[0]
            else:
                entity_type = custom_labels[0]
            
            entity_types_found.add(entity_type)
            
            entity = EntityNode(
                uuid=node["uuid"],
                name=node["name"],
                labels=labels,
                summary=node["summary"],
                attributes=node["attributes"],
            )
            
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
        
        # Fallback: if strict filtering returned 0 entities but all_nodes has nodes,
        # use all available nodes so the simulation does not fail.
        if not filtered_entities and all_nodes:
            logger.warning(
                f"Strict label filtering matched 0 entities from {total_count} nodes. "
                "Applying fallback extraction using all graph nodes."
            )
            for node in all_nodes:
                labels = node.get("labels", [])
                custom_labels = [l for l in labels if l not in ["Entity", "Node"]]
                if custom_labels:
                    entity_type = custom_labels[0]
                elif node.get("attributes", {}).get("type"):
                    entity_type = str(node["attributes"]["type"])
                elif labels:
                    entity_type = labels[0]
                else:
                    entity_type = "Entity"
                
                entity_types_found.add(entity_type)
                
                entity = EntityNode(
                    uuid=node["uuid"],
                    name=node.get("name") or "Entity",
                    labels=labels if labels else [entity_type],
                    summary=node.get("summary", ""),
                    attributes=node.get("attributes", {}),
                )
                
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
                    
                    related_nodes = []
                    for related_uuid in related_node_uuids:
                        if related_uuid in node_map:
                            related_node = node_map[related_uuid]
                            related_nodes.append({
                                "uuid": related_node["uuid"],
                                "name": related_node["name"],
                                "labels": related_node.get("labels", []),
                                "summary": related_node.get("summary", ""),
                            })
                    entity.related_nodes = related_nodes
                
                filtered_entities.append(entity)

        logger.info(
            f"Filtering complete: total nodes {total_count}, matched entities {len(filtered_entities)}, "
            f"entity types: {entity_types_found}"
        )
        
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
        Get a single entity with its full graph context (edges and neighbor nodes)
        
        Args:
            graph_id: Knowledge graph ID
            entity_uuid: Entity UUID
            
        Returns:
            EntityNode or None
        """
        try:
            node = self._call_with_retry(
                func=lambda: self.client.graph.node.get(uuid_=entity_uuid),
                operation_name=f"get node details (uuid={entity_uuid[:8]}...)"
            )
            
            if not node:
                return None
            
            edges = self.get_node_edges(entity_uuid, graph_id=graph_id)
            all_nodes = self.get_all_nodes(graph_id)
            node_map = {n["uuid"]: n for n in all_nodes}
            
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
            logger.error(f"Failed to get entity {entity_uuid}: {str(e)}")
            raise
    
    def get_entities_by_type(
        self, 
        graph_id: str, 
        entity_type: str,
        enrich_with_edges: bool = True
    ) -> List[EntityNode]:
        """
        Get all entities of a specific type
        
        Args:
            graph_id: Knowledge graph ID
            entity_type: Entity type name
            enrich_with_edges: Whether to enrich with edge information
            
        Returns:
            List of EntityNode instances
        """
        result = self.filter_defined_entities(
            graph_id=graph_id,
            defined_entity_types=[entity_type],
            enrich_with_edges=enrich_with_edges
        )
        return result.entities
