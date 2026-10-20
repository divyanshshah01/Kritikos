"""
本体生成服务
Connect口1:  min析文本内容, 生成适合社会模Draft的entities and relationsClass型定义
"""

import json
import logging
import re
from typing import Dict, Any, List, Optional
from ..utils.llm_client import LLMClient
from ..utils.locale import get_language_instruction
from ..utils.file_parser import split_text_into_chunks
from ..utils.ontology import (
    MAX_ONTOLOGY_TYPES,
    normalize_ontology_attributes,
    normalize_ontology_source_targets,
)

logger = logging.getLogger(__name__)


def _to_pascal_case(name: str) -> str:
    """Convert names of any format to PascalCase (e.g. 'works_for' -> 'WorksFor', 'person' -> 'Person') """
    # 按Non字母数字字Symbol minCut
    parts = re.split(r'[^a-zA-Z0-9]+', name)
    # 再按 camelCase edges界 minCut (如 'camelCase' -> ['camel', 'Case']) 
    words = []
    for part in parts:
        words.extend(re.sub(r'([a-z])([A-Z])', r'\1_\2', part).split('_'))
    # 每词首字母Large写, 过滤空串
    result = ''.join(word.capitalize() for word in words if word)
    return result if result else 'Unknown'


def _to_upper_snake_case(name: str) -> str:
    """Convert free-form or camelCase names to SCREAMING_SNAKE_CASE."""

    separated = re.sub(r'([a-z0-9])([A-Z])', r'\1_\2', name.strip())
    normalized = re.sub(r'[^a-zA-Z0-9]+', '_', separated).strip('_').upper()
    if not normalized:
        return "UNKNOWN"
    if normalized[0].isdigit():
        normalized = f"REL_{normalized}"
    return normalized


# Ontology generation system prompt
ONTOLOGY_SYSTEM_PROMPT = """You are an expert knowledge graph ontology designer for **Kritikos — Autonomous Startup & Idea Validation Platform**.
Your task is to analyze the provided idea/product pitch and simulation requirements, and design entity types and relationship types suitable for **simulating real-world market adoption, technical scrutiny, and investor validation**.

**CRITICAL: You must output valid JSON format data only. Do not output any markdown text or explanations outside the JSON.**

## Core Task Context

We are building a **market & stakeholder simulation system** to stress-test startup ideas:
- Each entity is an "account" or "agent" capable of voicing opinions, reviewing products, debating feasibility, and interacting on social/professional platforms.
- Entities evaluate the startup idea, discuss pain points, compare competitors, challenge unit economics, and test technical claims.
- We simulate the reactions of all ecosystem stakeholders: customers, engineers, competitors, investors, and regulators.

Therefore, **entities must be real-world agents that can speak, evaluate, and interact**:

**Valid Stakeholder Entities (Choose relevant types based on the idea)**:
- Target Customers & Early Adopters (e.g., EnterpriseBuyer, SMBOwner, Freelancer, EverydayConsumer, PowerUser)
- Technical Experts & Architects (e.g., SeniorArchitect, SecurityEngineer, TechLead, OpenSourceDeveloper)
- Competitors & Incumbents (e.g., IncumbentExecutive, DirectCompetitor, AlternativePlatform)
- Investors & Financial Analysts (e.g., AngelInvestor, SeedVC, GrowthFundPartner, MarketAnalyst)
- Regulatory & Compliance Watchdogs (e.g., ComplianceOfficer, RegulatoryAuditor, LegalCounsel)
- Media & Industry Influencers (e.g., TechJournalist, IndustryInfluencer, Podcaster)

**Invalid Entities (DO NOT USE)**:
- Abstract concepts (such as "Feasibility", "Emotion", "Market Trend", "Valuation")
- Topics / Issues (such as "Scalability Problem", "AI Ethics")
- Stances / Attitudes (such as "Supporters", "Critics")

## Output Format

Output valid JSON matching this schema:

```json
{
    "entity_types": [
        {
            "name": "EntityType (English, PascalCase)",
            "description": "Short description (English, max 100 characters)",
            "attributes": [
                {
                    "name": "attribute_name (English, snake_case)",
                    "type": "text",
                    "description": "Attribute description"
                }
            ],
            "examples": ["Example 1", "Example 2"]
        }
    ],
    "edge_types": [
        {
            "name": "RELATIONSHIP_TYPE (English, UPPER_SNAKE_CASE)",
            "description": "Short description (English, max 100 characters)",
            "source_targets": [
                {"source": "SourceEntityType", "target": "TargetEntityType"}
            ],
            "attributes": []
        }
    ],
    "analysis_summary": "Brief analysis and summary of the text content in English"
}
```

## Design Guidelines (Strictly Follow!)

### 1. Entity Type Design
- **Count: Must be exactly 10 entity types.**
- **Hierarchy Requirements (Must include both specific types and fallback types)**:
  - **Fallback Types (Mandatory, placed as the last 2 items in the list)**:
    - `Person`: Fallback type for any individual human who does not fit a more specific person type.
    - `Organization`: Fallback type for any organization or group that does not fit a more specific organization type.
  - **Specific Types (8 types, tailored to the source document)**:
    - Identify primary roles from the document (e.g., if academic: `Student`, `Professor`, `University`; if business: `Company`, `CEO`, `Employee`).
    - Each specific type must have clear boundaries.

### 2. Relationship Type Design
- **Count: 6 to 10 relationship types.**
- Relationships should reflect real interactions on social media and organizations.
- Ensure `source_targets` map to your defined entity types.

### 3. Attribute Design
- 1 to 3 key attributes per entity type.
- **Forbidden attribute names**: `name`, `uuid`, `group_id`, `graph_id`, `created_at`, `summary` (reserved system keywords).
- Recommended attributes: `full_name`, `title`, `role`, `position`, `location`, `description`, etc.

## Entity Type Reference
- Individual: Student, Professor, Journalist, Celebrity, Executive, Official, Lawyer, Doctor
- Fallback Person: Person
- Organization: University, Company, GovernmentAgency, MediaOutlet, Hospital, School, NGO
- Fallback Organization: Organization

## Relationship Type Reference
- WORKS_FOR, STUDIES_AT, AFFILIATED_WITH, REPRESENTS, REGULATES, REPORTS_ON, COMMENTS_ON, RESPONDS_TO, SUPPORTS, OPPOSES, COLLABORATES_WITH, COMPETES_WITH
"""


class OntologyGenerator:
    """
    Ontology Generator
     min析文本内容, 生成entities and relationsClass型定义
    """
    
    def __init__(self, llm_client: Optional[LLMClient] = None):
        self.llm_client = llm_client or LLMClient()
    
    def generate(
        self,
        document_texts: List[str],
        simulation_requirement: str,
        additional_context: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        生成本体定义
        
        Args:
            document_texts: 文档文本列表
            simulation_requirement: 模Draft需Request描Description
            additional_context: 额外on under 文
            
        Returns:
            本体定义 (entity_types, edge_types等) 
        """
        # Construct user message
        user_message = self._build_user_message(
            document_texts, 
            simulation_requirement,
            additional_context
        )
        
        lang_instruction = get_language_instruction()
        system_prompt = f"{ONTOLOGY_SYSTEM_PROMPT}\n\n{lang_instruction}\nIMPORTANT: Entity type names MUST be in English PascalCase (e.g., 'PersonEntity', 'MediaOrganization'). Relationship type names MUST be in English UPPER_SNAKE_CASE (e.g., 'WORKS_FOR'). Attribute names MUST be in English snake_case. Only description fields and analysis_summary should use the specified language above."
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message}
        ]
        
        # InvokeUseLLM
        result = self.llm_client.chat_json(
            messages=messages,
            temperature=0.3,
            # Structured ontology responses can exceed 4096 completion tokens,
            # especially when a compatible provider counts hidden reasoning in
            # the same budget. Let the provider use its model-specific limit.
            max_tokens=None,
            max_attempts=2,
        )
        
        # 验证 and after Location理
        result = self._validate_and_process(result)
        
        return result
    
    # Maximum text length passed to LLM (prevents HTTP 413 token limit errors with Groq/OpenAI)
    MAX_TEXT_LENGTH_FOR_LLM = 16000
    LONG_TEXT_CHUNK_SIZE = 4000
    LONG_TEXT_CHUNK_OVERLAP = 200
    MAX_LONG_TEXT_CHUNKS = 20
    MIN_LONG_TEXT_EXCERPT = 400
    
    def _build_user_message(
        self,
        document_texts: List[str],
        simulation_requirement: str,
        additional_context: Optional[str]
    ) -> str:
        """Construct user message"""
        
        combined_text = self._build_document_context(document_texts)
        
        message = f"""## Simulation Requirements

{simulation_requirement}

## Document Content

{combined_text}
"""
        
        if additional_context:
            message += f"""
## Additional Context

{additional_context}
"""
        
        message += """
Based on the above content, design entity types and relationship types suitable for market and stakeholder simulation.

**Required Rules**:
1. Output exactly 10 entity types.
2. The last 2 MUST be fallback types: Person (individual fallback) and Organization (organization fallback).
3. The first 8 must be specific entity types designed based on the document content and market ecosystem.
4. All entity types must be real-world agents that can speak, evaluate, and interact (not abstract concepts).
5. Attribute names must NOT use reserved keywords such as name, uuid, group_id, graph_id (use full_name, org_name, etc. instead).
"""
        
        return message

    def _build_document_context(self, document_texts: List[str]) -> str:
        """构建Use于本体 min析的文档on under 文, 长文本按全局Chunking抽样而不is 只截取开头. """

        combined_text = "\n\n---\n\n".join(document_texts)
        original_length = len(combined_text)

        if original_length <= self.MAX_TEXT_LENGTH_FOR_LLM:
            return combined_text

        chunks = self._collect_document_chunks(document_texts)
        if not chunks:
            return ""

        selected_chunks = self._select_representative_chunks(chunks)
        excerpt_budget = self._calculate_excerpt_budget(len(selected_chunks))
        context = self._render_chunked_context(
            selected_chunks=selected_chunks,
            original_length=original_length,
            total_chunks=len(chunks),
            excerpt_limit=excerpt_budget,
        )

        while len(context) > self.MAX_TEXT_LENGTH_FOR_LLM and excerpt_budget > self.MIN_LONG_TEXT_EXCERPT:
            excerpt_budget = max(self.MIN_LONG_TEXT_EXCERPT, int(excerpt_budget * 0.85))
            context = self._render_chunked_context(
                selected_chunks=selected_chunks,
                original_length=original_length,
                total_chunks=len(chunks),
                excerpt_limit=excerpt_budget,
            )

        if len(context) > self.MAX_TEXT_LENGTH_FOR_LLM:
            marker = "\n\n...(Chunked context compressed to ontology analysis limit)..."
            context = context[:self.MAX_TEXT_LENGTH_FOR_LLM - len(marker)] + marker

        return context

    def _collect_document_chunks(self, document_texts: List[str]) -> List[Dict[str, Any]]:
        """Collect chunks by document, preserving document and chunk indexing."""

        all_chunks: List[Dict[str, Any]] = []
        for doc_index, text in enumerate(document_texts, 1):
            doc_chunks = split_text_into_chunks(
                text,
                chunk_size=self.LONG_TEXT_CHUNK_SIZE,
                overlap=self.LONG_TEXT_CHUNK_OVERLAP,
            )
            total_doc_chunks = len(doc_chunks)
            for chunk_index, chunk in enumerate(doc_chunks, 1):
                all_chunks.append({
                    "document_index": doc_index,
                    "chunk_index": chunk_index,
                    "total_document_chunks": total_doc_chunks,
                    "text": chunk,
                })

        return all_chunks

    def _select_representative_chunks(self, chunks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """从全部Chunkingin 等距抽样, 覆Cover长文开头, in Segment and 结尾. """

        if len(chunks) <= self.MAX_LONG_TEXT_CHUNKS:
            return chunks

        if self.MAX_LONG_TEXT_CHUNKS <= 1:
            return [chunks[0]]

        last_index = len(chunks) - 1
        selected_indexes = {
            round(i * last_index / (self.MAX_LONG_TEXT_CHUNKS - 1))
            for i in range(self.MAX_LONG_TEXT_CHUNKS)
        }
        return [chunks[i] for i in sorted(selected_indexes)]

    def _calculate_excerpt_budget(self, selected_count: int) -> int:
        """根据选in 的Chunking数量为每Block min配字Symbol预算. """

        header_budget = 600
        chunk_header_budget = 120 * selected_count
        available = max(
            self.MIN_LONG_TEXT_EXCERPT * selected_count,
            self.MAX_TEXT_LENGTH_FOR_LLM - header_budget - chunk_header_budget,
        )
        return max(self.MIN_LONG_TEXT_EXCERPT, available // max(selected_count, 1))

    def _render_chunked_context(
        self,
        selected_chunks: List[Dict[str, Any]],
        original_length: int,
        total_chunks: int,
        excerpt_limit: int,
    ) -> str:
        """渲Color长文本Chunkingon under 文. """

        lines = [
            (
                f"[Automatic chunked summarization of long text] Original text has {original_length} characters, "
                f"split into {total_chunks} text blocks for global coverage analysis."
            ),
            (
                f"Below shows excerpts from {len(selected_chunks)} representative text blocks, "
                "covering beginning, middle, and end. Design the ontology based on these cross-document clues."
            ),
        ]

        for chunk in selected_chunks:
            excerpt = self._excerpt_text(chunk["text"], excerpt_limit)
            lines.append(
                "\n".join([
                    (
                        f"--- Document {chunk['document_index']} / "
                        f"Chunk {chunk['chunk_index']}/{chunk['total_document_chunks']} ---"
                    ),
                    excerpt,
                ])
            )

        return "\n\n".join(lines)

    @staticmethod
    def _excerpt_text(text: str, char_limit: int) -> str:
        """Preserve start and end of chunk to maintain context representation."""

        text = text.strip()
        if len(text) <= char_limit:
            return text

        marker = "\n...(Intermediate content omitted)...\n"
        if char_limit <= len(marker) + 20:
            return text[:char_limit]

        remaining = char_limit - len(marker)
        head_len = remaining // 2
        tail_len = remaining - head_len
        return f"{text[:head_len].rstrip()}{marker}{text[-tail_len:].lstrip()}"
    
    def _validate_and_process(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """Validate and post-process ontology generation results."""
        if not isinstance(result, dict):
            raise ValueError("Ontology result must be an object")

        raw_entities = result.get("entity_types")
        raw_edges = result.get("edge_types")
        if not isinstance(raw_entities, list):
            raw_entities = []
        if not isinstance(raw_edges, list):
            raw_edges = []
        if not isinstance(result.get("analysis_summary"), str):
            result["analysis_summary"] = ""

        # Normalize entity entries before touching their fields. LLMs
        # occasionally emit a bare string, null, or another scalar.
        entity_name_map: Dict[str, str] = {}
        processed_entities: List[Dict[str, Any]] = []
        seen_entity_names = set()
        for raw_entity in raw_entities:
            if isinstance(raw_entity, str):
                entity = {"name": raw_entity}
            elif isinstance(raw_entity, dict):
                entity = dict(raw_entity)
            else:
                logger.warning("Ignoring non-object ontology entity entry")
                continue

            original_name = entity.get("name")
            if not isinstance(original_name, str) or not original_name.strip():
                logger.warning("Ignoring ontology entity without a usable name")
                continue
            original_name = original_name.strip()
            normalized_name = _to_pascal_case(original_name)
            if normalized_name == "Unknown":
                continue
            if normalized_name in seen_entity_names:
                logger.warning(f"Duplicate entity type '{normalized_name}' removed during validation")
                entity_name_map[original_name] = normalized_name
                entity_name_map[original_name.lower()] = normalized_name
                continue

            if normalized_name != original_name:
                logger.warning(
                    f"Entity type name '{original_name}' auto-converted to '{normalized_name}'"
                )
            entity["name"] = normalized_name
            entity["attributes"] = normalize_ontology_attributes(
                entity.get("attributes", [])
            )
            if not isinstance(entity.get("examples"), list):
                entity["examples"] = []
            description = entity.get("description")
            if not isinstance(description, str) or not description:
                description = f"A {normalized_name} entity."
            entity["description"] = (
                description[:97] + "..." if len(description) > 100 else description
            )

            seen_entity_names.add(normalized_name)
            processed_entities.append(entity)
            entity_name_map[original_name] = normalized_name
            entity_name_map[original_name.lower()] = normalized_name
            entity_name_map[normalized_name] = normalized_name
            entity_name_map[normalized_name.lower()] = normalized_name

        result["entity_types"] = processed_entities

        # 兜底Class型定义
        person_fallback = {
            "name": "Person",
            "description": "Any individual person not fitting other specific person types.",
            "attributes": [
                {"name": "full_name", "type": "text", "description": "Full name of the person"},
                {"name": "role", "type": "text", "description": "Role or occupation"}
            ],
            "examples": ["ordinary citizen", "anonymous netizen"]
        }
        
        organization_fallback = {
            "name": "Organization",
            "description": "Any organization not fitting other specific organization types.",
            "attributes": [
                {"name": "org_name", "type": "text", "description": "Name of the organization"},
                {"name": "org_type", "type": "text", "description": "Type of organization"}
            ],
            "examples": ["small business", "community group"]
        }
        
        # 检查is noalready has兜底Class型
        entity_names = {e["name"] for e in result["entity_types"]}
        has_person = "Person" in entity_names
        has_organization = "Organization" in entity_names
        
        # 需要添加的兜底Class型
        fallbacks_to_add = []
        if not has_person:
            fallbacks_to_add.append(person_fallback)
        if not has_organization:
            fallbacks_to_add.append(organization_fallback)
        
        if fallbacks_to_add:
            current_count = len(result["entity_types"])
            needed_slots = len(fallbacks_to_add)
            
            # 如果添加after 会超过 10 , 需要Transfer除一些现hasClass型
            if current_count + needed_slots > MAX_ONTOLOGY_TYPES:
                # 计算需要Transfer除多少
                to_remove = current_count + needed_slots - MAX_ONTOLOGY_TYPES
                # 从末尾Transfer除 (保留before 面更重要的具体Class型) 
                result["entity_types"] = result["entity_types"][:-to_remove]
            
            # 添加兜底Class型
            result["entity_types"].extend(fallbacks_to_add)
        
        # 最终确保不超过限制 (防御性编程) 
        result["entity_types"] = result["entity_types"][:MAX_ONTOLOGY_TYPES]

        # Resolve edge endpoints only after entity fallback/capping, so an edge
        # cannot refer to a type that was removed to satisfy Zep's limits.
        valid_entity_names = {entity["name"] for entity in result["entity_types"]}
        for name in valid_entity_names:
            entity_name_map[name] = name
            entity_name_map[name.lower()] = name

        def resolve_entity_name(value: str) -> Optional[str]:
            stripped = value.strip()
            if stripped == "Entity":
                return stripped
            mapped = entity_name_map.get(stripped) or entity_name_map.get(stripped.lower())
            if mapped in valid_entity_names:
                return mapped
            pascal_name = _to_pascal_case(stripped)
            return pascal_name if pascal_name in valid_entity_names else None

        processed_edges: List[Dict[str, Any]] = []
        seen_edge_names = set()
        for raw_edge in raw_edges:
            if isinstance(raw_edge, str):
                # A bare edge name has no endpoints and cannot be installed in
                # Zep safely. Ignore it instead of inventing a relationship.
                logger.warning(f"Ignoring ontology edge without source_targets: {raw_edge}")
                continue
            elif isinstance(raw_edge, dict):
                edge = dict(raw_edge)
            else:
                logger.warning("Ignoring non-object ontology edge entry")
                continue

            original_name = edge.get("name")
            if not isinstance(original_name, str) or not original_name.strip():
                logger.warning("Ignoring ontology edge without a usable name")
                continue
            normalized_name = _to_upper_snake_case(original_name)
            if normalized_name == "UNKNOWN" or normalized_name in seen_edge_names:
                if normalized_name in seen_edge_names:
                    logger.warning(f"Duplicate edge type '{normalized_name}' removed during validation")
                continue
            if normalized_name != original_name:
                logger.warning(
                    f"Edge type name '{original_name}' auto-converted to '{normalized_name}'"
                )
            edge["name"] = normalized_name

            normalized_targets = []
            for source_target in normalize_ontology_source_targets(
                edge.get("source_targets", []),
                limit=None,
            ):
                source = resolve_entity_name(source_target["source"])
                target = resolve_entity_name(source_target["target"])
                if source and target:
                    normalized_targets.append({"source": source, "target": target})
            edge["source_targets"] = normalize_ontology_source_targets(
                normalized_targets
            )
            edge["attributes"] = normalize_ontology_attributes(
                edge.get("attributes", [])
            )
            description = edge.get("description")
            if not isinstance(description, str) or not description:
                description = f"A {normalized_name} relationship."
            edge["description"] = (
                description[:97] + "..." if len(description) > 100 else description
            )

            seen_edge_names.add(normalized_name)
            processed_edges.append(edge)
            if len(processed_edges) == MAX_ONTOLOGY_TYPES:
                break

        result["edge_types"] = processed_edges
        
        return result
    
    def generate_python_code(self, ontology: Dict[str, Any]) -> str:
        """
        Convert Ontology Definition to Python Code (Similarontology.py) 
        
        Args:
            ontology: 本体定义
            
        Returns:
            Python代码字Symbol串
        """
        code_lines = [
            '"""',
            'Custom entity types definition',
            'Automatically generated by Kritikos for startup and idea validation',
            '"""',
            '',
            'from pydantic import Field',
            'from zep_cloud.external_clients.ontology import EntityModel, EntityText, EdgeModel',
            '',
            '',
            '# ============== entitiesClass型定义 ==============',
            '',
        ]
        
        # 生成entitiesClass型
        for entity in ontology.get("entity_types", []):
            name = entity["name"]
            desc = entity.get("description", f"A {name} entity.")
            
            code_lines.append(f'class {name}(EntityModel):')
            code_lines.append(f'    """{desc}"""')
            
            attrs = entity.get("attributes", [])
            if attrs:
                for attr in attrs:
                    attr_name = attr["name"]
                    attr_desc = attr.get("description", attr_name)
                    code_lines.append(f'    {attr_name}: EntityText = Field(')
                    code_lines.append(f'        description="{attr_desc}",')
                    code_lines.append(f'        default=None')
                    code_lines.append(f'    )')
            else:
                code_lines.append('    pass')
            
            code_lines.append('')
            code_lines.append('')
        
        code_lines.append('# ============== relationsClass型定义 ==============')
        code_lines.append('')
        
        # 生成relationsClass型
        for edge in ontology.get("edge_types", []):
            name = edge["name"]
            # Convert to PascalCase class name
            class_name = ''.join(word.capitalize() for word in name.split('_'))
            desc = edge.get("description", f"A {name} relationship.")
            
            code_lines.append(f'class {class_name}(EdgeModel):')
            code_lines.append(f'    """{desc}"""')
            
            attrs = edge.get("attributes", [])
            if attrs:
                for attr in attrs:
                    attr_name = attr["name"]
                    attr_desc = attr.get("description", attr_name)
                    code_lines.append(f'    {attr_name}: EntityText = Field(')
                    code_lines.append(f'        description="{attr_desc}",')
                    code_lines.append(f'        default=None')
                    code_lines.append(f'    )')
            else:
                code_lines.append('    pass')
            
            code_lines.append('')
            code_lines.append('')
        
        # 生成Class型字典
        code_lines.append('# ============== Class型配置 ==============')
        code_lines.append('')
        code_lines.append('ENTITY_TYPES = {')
        for entity in ontology.get("entity_types", []):
            name = entity["name"]
            code_lines.append(f'    "{name}": {name},')
        code_lines.append('}')
        code_lines.append('')
        code_lines.append('EDGE_TYPES = {')
        for edge in ontology.get("edge_types", []):
            name = edge["name"]
            class_name = ''.join(word.capitalize() for word in name.split('_'))
            code_lines.append(f'    "{name}": {class_name},')
        code_lines.append('}')
        code_lines.append('')
        
        # 生成edges的source_targetsMapping
        code_lines.append('EDGE_SOURCE_TARGETS = {')
        for edge in ontology.get("edge_types", []):
            name = edge["name"]
            source_targets = edge.get("source_targets", [])
            if source_targets:
                st_list = ', '.join([
                    f'{{"source": "{st.get("source", "Entity")}", "target": "{st.get("target", "Entity")}"}}'
                    for st in source_targets
                ])
                code_lines.append(f'    "{name}": [{st_list}],')
        code_lines.append('}')
        
        return '\n'.join(code_lines)
