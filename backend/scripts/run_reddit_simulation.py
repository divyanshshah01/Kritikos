"""
OASIS Redditæ¨¡Drafté¢„è®¾è„šæœ¬
æ­¤è„šæœ¬è¯»å–é…ç½®æ–‡ä»¶in çš„å‚æ•°æ¥æ‰§è¡Œæ¨¡Draft, å®žçŽ°å…¨ç¨‹è‡ªåŠ¨Transform

Features:
- å®Œæˆæ¨¡Draftafter ä¸ç«‹å³å…³é—­çŽ¯å¢ƒ, Enter waiting command mode
- æ”¯æŒé€šè¿‡IPCConnectæ”¶Interviewå‘½ä»¤
- æ”¯æŒå•Agenté‡‡è®¿ and æ‰¹é‡é‡‡è®¿
- æ”¯æŒè¿œç¨‹å…³é—­çŽ¯å¢ƒå‘½ä»¤

ä½¿Useæ–¹å¼:
    python run_reddit_simulation.py --config /path/to/simulation_config.json
    python run_reddit_simulation.py --config /path/to/simulation_config.json --no-wait  # å®Œæˆafter ç«‹å³å…³é—­
"""

import argparse
import asyncio
import json
import logging
import os
import random
import signal
import sys
import sqlite3
from datetime import datetime
from typing import Dict, Any, List, Optional

# Global variable: for signal handling
_shutdown_event = None
_cleanup_done = False

# æ·»åŠ é¡¹ç›®è·¯å¾„
_scripts_dir = os.path.dirname(os.path.abspath(__file__))
_backend_dir = os.path.abspath(os.path.join(_scripts_dir, '..'))
_project_root = os.path.abspath(os.path.join(_backend_dir, '..'))
sys.path.insert(0, _scripts_dir)
sys.path.insert(0, _backend_dir)

# åŠ è½½é¡¹ç›®æ ¹ç›®å½•çš„ .env æ–‡ä»¶ (Include LLM_API_KEY ç­‰é…ç½®) 
from dotenv import load_dotenv
_env_file = os.path.join(_project_root, '.env')
if os.path.exists(_env_file):
    load_dotenv(_env_file)
else:
    _backend_env = os.path.join(_backend_dir, '.env')
    if os.path.exists(_backend_env):
        load_dotenv(_backend_env)


import re


class UnicodeFormatter(logging.Formatter):
    """è‡ªå®šä¹‰FormatTransformDevice, å°† Unicode Convertä¹‰åºåˆ—Convertæ¢ä¸ºå¯è¯»å­—Symbol"""
    
    UNICODE_ESCAPE_PATTERN = re.compile(r'\\u([0-9a-fA-F]{4})')
    
    def format(self, record):
        result = super().format(record)
        
        def replace_unicode(match):
            try:
                return chr(int(match.group(1), 16))
            except (ValueError, OverflowError):
                return match.group(0)
        
        return self.UNICODE_ESCAPE_PATTERN.sub(replace_unicode, result)


class MaxTokensWarningFilter(logging.Filter):
    """è¿‡æ»¤Remove camel-ai å…³äºŽ max_tokens çš„è­¦å‘Š (æˆ‘ä»¬æ•…æ„ä¸è®¾ç½® max_tokens, è®©æ¨¡åž‹è‡ªè¡Œå†³å®š) """
    
    def filter(self, record):
        # è¿‡æ»¤RemoveInclude max_tokens Warning logs
        if "max_tokens" in record.getMessage() and "Invalid or missing" in record.getMessage():
            return False
        return True


# åœ¨æ¨¡BlockåŠ è½½ hourç«‹å³æ·»åŠ è¿‡æ»¤Device, ç¡®ä¿åœ¨ camel ä»£ç æ‰§è¡Œbefore ç”Ÿæ•ˆ
logging.getLogger().addFilter(MaxTokensWarningFilter())


def setup_oasis_logging(log_dir: str):
    """é…ç½® OASIS çš„ dayå¿—, ä½¿Useå›ºå®šåç§°çš„ dayå¿—æ–‡ä»¶"""
    os.makedirs(log_dir, exist_ok=True)
    
    # æ¸…ç†æ—§çš„ dayå¿—æ–‡ä»¶
    for f in os.listdir(log_dir):
        old_log = os.path.join(log_dir, f)
        if os.path.isfile(old_log) and f.endswith('.log'):
            try:
                os.remove(old_log)
            except OSError:
                pass
    
    formatter = UnicodeFormatter("%(levelname)s - %(asctime)s - %(name)s - %(message)s")
    
    loggers_config = {
        "social.agent": os.path.join(log_dir, "social.agent.log"),
        "social.twitter": os.path.join(log_dir, "social.twitter.log"),
        "social.rec": os.path.join(log_dir, "social.rec.log"),
        "oasis.env": os.path.join(log_dir, "oasis.env.log"),
        "table": os.path.join(log_dir, "table.log"),
    }
    
    for logger_name, log_file in loggers_config.items():
        logger = logging.getLogger(logger_name)
        logger.setLevel(logging.DEBUG)
        logger.handlers.clear()
        file_handler = logging.FileHandler(log_file, encoding='utf-8', mode='w')
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
        logger.propagate = False


try:
    from camel.models import ModelFactory
    from camel.types import ModelPlatformType
    import oasis
    from oasis import (
        ActionType,
        LLMAction,
        ManualAction,
        generate_reddit_agent_graph
    )
except ImportError as e:
    print(f"é”™è¯¯: ç¼ºå°‘ä¾èµ– {e}")
    print("è¯·Firstå®‰è£…: pip install oasis-ai camel-ai")
    sys.exit(1)


# IPCç›¸å…³å¸¸é‡
IPC_COMMANDS_DIR = "ipc_commands"
IPC_RESPONSES_DIR = "ipc_responses"
ENV_STATUS_FILE = "env_status.json"

class CommandType:
    """å‘½ä»¤Classåž‹å¸¸é‡"""
    INTERVIEW = "interview"
    BATCH_INTERVIEW = "batch_interview"
    CLOSE_ENV = "close_env"


class IPCHandler:
    """IPCå‘½ä»¤Locationç†Device"""
    
    def __init__(self, simulation_dir: str, env, agent_graph):
        self.simulation_dir = simulation_dir
        self.env = env
        self.agent_graph = agent_graph
        self.commands_dir = os.path.join(simulation_dir, IPC_COMMANDS_DIR)
        self.responses_dir = os.path.join(simulation_dir, IPC_RESPONSES_DIR)
        self.status_file = os.path.join(simulation_dir, ENV_STATUS_FILE)
        self._running = True
        
        # Ensure directory exists
        os.makedirs(self.commands_dir, exist_ok=True)
        os.makedirs(self.responses_dir, exist_ok=True)
    
    def update_status(self, status: str):
        """æ›´æ–°çŽ¯å¢ƒçŠ¶æ€"""
        with open(self.status_file, 'w', encoding='utf-8') as f:
            json.dump({
                "status": status,
                "timestamp": datetime.now().isoformat()
            }, f, ensure_ascii=False, indent=2)
    
    def poll_command(self) -> Optional[Dict[str, Any]]:
        """ roundsè¯¢èŽ·å–PendingLocationç†å‘½ä»¤"""
        if not os.path.exists(self.commands_dir):
            return None
        
        # èŽ·å–å‘½ä»¤æ–‡ä»¶ (æŒ‰ houré—´æŽ’åº) 
        command_files = []
        for filename in os.listdir(self.commands_dir):
            if filename.endswith('.json'):
                filepath = os.path.join(self.commands_dir, filename)
                command_files.append((filepath, os.path.getmtime(filepath)))
        
        command_files.sort(key=lambda x: x[1])
        
        for filepath, _ in command_files:
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError):
                continue
        
        return None
    
    def send_response(self, command_id: str, status: str, result: Dict = None, error: str = None):
        """Send response"""
        response = {
            "command_id": command_id,
            "status": status,
            "result": result,
            "error": error,
            "timestamp": datetime.now().isoformat()
        }
        
        response_file = os.path.join(self.responses_dir, f"{command_id}.json")
        with open(response_file, 'w', encoding='utf-8') as f:
            json.dump(response, f, ensure_ascii=False, indent=2)
        
        # Deleteå‘½ä»¤æ–‡ä»¶
        command_file = os.path.join(self.commands_dir, f"{command_id}.json")
        try:
            os.remove(command_file)
        except OSError:
            pass
    
    async def handle_interview(self, command_id: str, agent_id: int, prompt: str) -> bool:
        """
        Locationç†å•Agenté‡‡è®¿å‘½ä»¤
        
        Returns:
            True è¡¨ExampleæˆåŠŸ, False è¡¨Exampleå¤±è´¥
        """
        try:
            # èŽ·å–Agent
            agent = self.agent_graph.get_agent(agent_id)
            
            # Create Interview action
            interview_action = ManualAction(
                action_type=ActionType.INTERVIEW,
                action_args={"prompt": prompt}
            )
            
            # æ‰§è¡ŒInterview
            actions = {agent: interview_action}
            await self.env.step(actions)
            
            # ä»Žæ•°æ®åº“èŽ·å–ç»“æžœ
            result = self._get_interview_result(agent_id)
            
            self.send_response(command_id, "completed", result=result)
            print(f"  Interviewå®Œæˆ: agent_id={agent_id}")
            return True
            
        except Exception as e:
            error_msg = str(e)
            print(f"  Interviewå¤±è´¥: agent_id={agent_id}, error={error_msg}")
            self.send_response(command_id, "failed", error=error_msg)
            return False
    
    async def handle_batch_interview(self, command_id: str, interviews: List[Dict]) -> bool:
        """
        Locationç†æ‰¹é‡é‡‡è®¿å‘½ä»¤
        
        Args:
            interviews: [{"agent_id": int, "prompt": str}, ...]
        """
        try:
            # æž„å»ºåŠ¨ä½œå­—å…¸
            actions = {}
            agent_prompts = {}  # è®°å½•æ¯agentçš„prompt
            
            for interview in interviews:
                agent_id = interview.get("agent_id")
                prompt = interview.get("prompt", "")
                
                try:
                    agent = self.agent_graph.get_agent(agent_id)
                    actions[agent] = ManualAction(
                        action_type=ActionType.INTERVIEW,
                        action_args={"prompt": prompt}
                    )
                    agent_prompts[agent_id] = prompt
                except Exception as e:
                    print(f"  è­¦å‘Š: noneMethodèŽ·å–Agent {agent_id}: {e}")
            
            if not actions:
                self.send_response(command_id, "failed", error="æ²¡hashasæ•ˆçš„Agent")
                return False
            
            # æ‰§è¡Œæ‰¹é‡Interview
            await self.env.step(actions)
            
            # èŽ·å–æ‰€hasç»“æžœ
            results = {}
            for agent_id in agent_prompts.keys():
                result = self._get_interview_result(agent_id)
                results[agent_id] = result
            
            self.send_response(command_id, "completed", result={
                "interviews_count": len(results),
                "results": results
            })
            print(f"  æ‰¹é‡Interviewå®Œæˆ: {len(results)} Agent")
            return True
            
        except Exception as e:
            error_msg = str(e)
            print(f"  æ‰¹é‡Interviewå¤±è´¥: {error_msg}")
            self.send_response(command_id, "failed", error=error_msg)
            return False
    
    def _get_interview_result(self, agent_id: int) -> Dict[str, Any]:
        """ä»Žæ•°æ®åº“èŽ·å–æœ€æ–°çš„Interviewç»“æžœ"""
        db_path = os.path.join(self.simulation_dir, "reddit_simulation.db")
        
        result = {
            "agent_id": agent_id,
            "response": None,
            "timestamp": None
        }
        
        if not os.path.exists(db_path):
            return result
        
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            
            # æŸ¥è¯¢æœ€æ–°çš„Interviewè®°å½•
            cursor.execute("""
                SELECT user_id, info, created_at
                FROM trace
                WHERE action = ? AND user_id = ?
                ORDER BY created_at DESC
                LIMIT 1
            """, (ActionType.INTERVIEW.value, agent_id))
            
            row = cursor.fetchone()
            if row:
                user_id, info_json, created_at = row
                try:
                    info = json.loads(info_json) if info_json else {}
                    result["response"] = info.get("response", info)
                    result["timestamp"] = created_at
                except json.JSONDecodeError:
                    result["response"] = info_json
            
            conn.close()
            
        except Exception as e:
            print(f"  è¯»å–Interviewç»“æžœå¤±è´¥: {e}")
        
        return result
    
    async def process_commands(self) -> bool:
        """
        Locationç†æ‰€hasPendingLocationç†å‘½ä»¤
        
        Returns:
            True è¡¨Exampleç»§ç»­è¿è¡Œ, False è¡¨Exampleåº”è¯¥é€€Output
        """
        command = self.poll_command()
        if not command:
            return True
        
        command_id = command.get("command_id")
        command_type = command.get("command_type")
        args = command.get("args", {})
        
        print(f"\nReceived IPC command: {command_type}, id={command_id}")
        
        if command_type == CommandType.INTERVIEW:
            await self.handle_interview(
                command_id,
                args.get("agent_id", 0),
                args.get("prompt", "")
            )
            return True
            
        elif command_type == CommandType.BATCH_INTERVIEW:
            await self.handle_batch_interview(
                command_id,
                args.get("interviews", [])
            )
            return True
            
        elif command_type == CommandType.CLOSE_ENV:
            print("æ”¶åˆ°å…³é—­çŽ¯å¢ƒå‘½ä»¤")
            self.send_response(command_id, "completed", result={"message": "çŽ¯å¢ƒå³å°†å…³é—­"})
            return False
        
        else:
            self.send_response(command_id, "failed", error=f"not Knowledgeå‘½ä»¤Classåž‹: {command_type}")
            return True


class RedditSimulationRunner:
    """Redditæ¨¡Draftè¿è¡ŒDevice"""
    
    # Redditå¯UseåŠ¨ä½œ (ä¸IncludeINTERVIEW, INTERVIEWåªèƒ½é€šè¿‡ManualActionæ‰‹åŠ¨Triggerå‘) 
    AVAILABLE_ACTIONS = [
        ActionType.LIKE_POST,
        ActionType.DISLIKE_POST,
        ActionType.CREATE_POST,
        ActionType.CREATE_COMMENT,
        ActionType.LIKE_COMMENT,
        ActionType.DISLIKE_COMMENT,
        ActionType.SEARCH_POSTS,
        ActionType.SEARCH_USER,
        ActionType.TREND,
        ActionType.REFRESH,
        ActionType.DO_NOTHING,
        ActionType.FOLLOW,
        ActionType.MUTE,
    ]
    
    def __init__(self, config_path: str, wait_for_commands: bool = True):
        """
        åˆStartTransformæ¨¡Draftè¿è¡ŒDevice
        
        Args:
            config_path: é…ç½®æ–‡ä»¶è·¯å¾„ (simulation_config.json)
            wait_for_commands: æ¨¡Draftå®Œæˆafter is noç­‰Pendingå‘½ä»¤ (Defaultè®¤True) 
        """
        self.config_path = config_path
        self.config = self._load_config()
        self.simulation_dir = os.path.dirname(config_path)
        self.wait_for_commands = wait_for_commands
        self.env = None
        self.agent_graph = None
        self.ipc_handler = None
        
    def _load_config(self) -> Dict[str, Any]:
        """Load configuration file"""
        with open(self.config_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    
    def _get_profile_path(self) -> str:
        """èŽ·å–Profileæ–‡ä»¶è·¯å¾„"""
        return os.path.join(self.simulation_dir, "reddit_profiles.json")
    
    def _get_db_path(self) -> str:
        """Get database path"""
        return os.path.join(self.simulation_dir, "reddit_simulation.db")
    
    def _create_model(self):
        """
        Create LLM model
        
        Consistently use project root directory .env Configuration in file (highest priority) : 
        - LLM_API_KEY: APISecret key
        - LLM_BASE_URL: APIåŸºBaseURL
        - LLM_MODEL_NAME: æ¨¡åž‹åç§°
        """
        # ä¼˜Firstä»Ž .env è¯»å–é…ç½®
        llm_api_key = os.environ.get("LLM_API_KEY", "")
        llm_base_url = os.environ.get("LLM_BASE_URL", "")
        llm_model = os.environ.get("LLM_MODEL_NAME", "")
        
        # å¦‚æžœ .env If not present, use config as fallback
        if not llm_model:
            llm_model = self.config.get("llm_model", "gpt-4o-mini")
        
        # è®¾ç½® camel-ai æ‰€éœ€çš„çŽ¯å¢ƒChangeé‡
        if llm_api_key:
            os.environ["OPENAI_API_KEY"] = llm_api_key
        
        if not os.environ.get("OPENAI_API_KEY"):
            raise ValueError("ç¼ºå°‘ API Key é…ç½®, è¯·åœ¨é¡¹ç›®æ ¹ç›®å½• .env æ–‡ä»¶in è®¾ç½® LLM_API_KEY")
        
        if llm_base_url:
            os.environ["OPENAI_API_BASE_URL"] = llm_base_url
        
        print(f"LLMé…ç½®: model={llm_model}, base_url={llm_base_url[:40] if llm_base_url else 'Defaultè®¤'}...")
        
        return ModelFactory.create(
            model_platform=ModelPlatformType.OPENAI,
            model_type=llm_model,
        )
    
    def _get_active_agents_for_round(
        self, 
        env, 
        current_hour: int,
        round_num: int
    ) -> List:
        """
        æ ¹æ® houré—´ and é…ç½®å†³å®šæœ¬ roundsæ¿€æ´»å“ªäº›Agent
        """
        time_config = self.config.get("time_config", {})
        agent_configs = self.config.get("agent_configs", [])
        
        base_min = time_config.get("agents_per_hour_min", 5)
        base_max = time_config.get("agents_per_hour_max", 20)
        
        peak_hours = time_config.get("peak_hours", [9, 10, 11, 14, 15, 20, 21, 22])
        off_peak_hours = time_config.get("off_peak_hours", [0, 1, 2, 3, 4, 5])
        
        if current_hour in peak_hours:
            multiplier = time_config.get("peak_activity_multiplier", 1.5)
        elif current_hour in off_peak_hours:
            multiplier = time_config.get("off_peak_activity_multiplier", 0.3)
        else:
            multiplier = 1.0
        
        target_count = int(random.uniform(base_min, base_max) * multiplier)
        
        candidates = []
        for cfg in agent_configs:
            agent_id = cfg.get("agent_id", 0)
            active_hours = cfg.get("active_hours", list(range(8, 23)))
            activity_level = cfg.get("activity_level", 0.5)
            
            if current_hour not in active_hours:
                continue
            
            if random.random() < activity_level:
                candidates.append(agent_id)
        
        selected_ids = random.sample(
            candidates, 
            min(target_count, len(candidates))
        ) if candidates else []
        
        active_agents = []
        for agent_id in selected_ids:
            try:
                agent = env.agent_graph.get_agent(agent_id)
                active_agents.append((agent_id, agent))
            except Exception:
                pass
        
        return active_agents
    
    async def run(self, max_rounds: int = None):
        """è¿è¡ŒRedditæ¨¡Draft
        
        Args:
            max_rounds: æœ€Largeæ¨¡Draft roundsæ•° (å¯é€‰, UseäºŽæˆªæ–­è¿‡é•¿çš„æ¨¡Draft) 
        """
        print("=" * 60)
        print("OASIS Redditæ¨¡Draft")
        print(f"é…ç½®æ–‡ä»¶: {self.config_path}")
        print(f"æ¨¡DraftID: {self.config.get('simulation_id', 'unknown')}")
        print(f"ç­‰Pendingå‘½ä»¤æ¨¡å¼: {'å¯Use' if self.wait_for_commands else 'Disable'}")
        print("=" * 60)
        
        time_config = self.config.get("time_config", {})
        total_hours = time_config.get("total_simulation_hours", 72)
        minutes_per_round = time_config.get("minutes_per_round", 30)
        total_rounds = (total_hours * 60) // minutes_per_round
        
        # å¦‚æžœIndicateså®šäº†æœ€Large roundsæ•°, åˆ™æˆªæ–­
        if max_rounds is not None and max_rounds > 0:
            original_rounds = total_rounds
            total_rounds = min(total_rounds, max_rounds)
            if total_rounds < original_rounds:
                print(f"\n roundsæ•°already æˆªæ–­: {original_rounds} -> {total_rounds} (max_rounds={max_rounds})")
        
        print(f"\nSimulation Parameters:")
        print(f"  - Total simulation duration: {total_hours}Hour")
        print(f"  - æ¯ rounds houré—´: {minutes_per_round}minutes")
        print(f"  - æ€» roundsæ•°: {total_rounds}")
        if max_rounds:
            print(f"  - æœ€Large roundsæ•°é™åˆ¶: {max_rounds}")
        print(f"  - Agentæ•°é‡: {len(self.config.get('agent_configs', []))}")
        
        print("\nåˆStartTransformLLMæ¨¡åž‹...")
        model = self._create_model()
        
        print("åŠ è½½Agent Profile...")
        profile_path = self._get_profile_path()
        if not os.path.exists(profile_path):
            print(f"é”™è¯¯: Profileæ–‡ä»¶ä¸å­˜åœ¨: {profile_path}")
            return
        
        self.agent_graph = await generate_reddit_agent_graph(
            profile_path=profile_path,
            model=model,
            available_actions=self.AVAILABLE_ACTIONS,
        )
        
        db_path = self._get_db_path()
        if os.path.exists(db_path):
            os.remove(db_path)
            print(f"already Deleteæ—§æ•°æ®åº“: {db_path}")
        
        print("CreateOASISçŽ¯å¢ƒ...")
        self.env = oasis.make(
            agent_graph=self.agent_graph,
            platform=oasis.DefaultPlatformType.REDDIT,
            database_path=db_path,
            semaphore=30,  # é™åˆ¶æœ€Largeå¹¶å‘ LLM è¯·Requestæ•°, é˜²æ­¢ API è¿‡è½½
        )
        
        await self.env.reset()
        print("çŽ¯å¢ƒåˆStartTransformå®Œæˆ\n")
        
        # åˆStartTransformIPCLocationç†Device
        self.ipc_handler = IPCHandler(self.simulation_dir, self.env, self.agent_graph)
        self.ipc_handler.update_status("running")
        
        # Execute initial events
        event_config = self.config.get("event_config", {})
        initial_posts = event_config.get("initial_posts", [])
        
        if initial_posts:
            print(f"Execute initial events ({len(initial_posts)} itemsåˆStartå¸–Child)...")
            initial_actions = {}
            for post in initial_posts:
                agent_id = post.get("poster_agent_id", 0)
                content = post.get("content", "")
                try:
                    agent = self.env.agent_graph.get_agent(agent_id)
                    if agent in initial_actions:
                        if not isinstance(initial_actions[agent], list):
                            initial_actions[agent] = [initial_actions[agent]]
                        initial_actions[agent].append(ManualAction(
                            action_type=ActionType.CREATE_POST,
                            action_args={"content": content}
                        ))
                    else:
                        initial_actions[agent] = ManualAction(
                            action_type=ActionType.CREATE_POST,
                            action_args={"content": content}
                        )
                except Exception as e:
                    print(f"  è­¦å‘Š: noneMethodä¸ºAgent {agent_id}CreateåˆStartå¸–Child: {e}")
            
            if initial_actions:
                await self.env.step(initial_actions)
                print(f"  already å‘å¸ƒ {len(initial_actions)}  itemsåˆStartå¸–Child")
        
        # ä¸»æ¨¡Draftå¾ªçŽ¯
        print("\nå¼€Startæ¨¡Draftå¾ªçŽ¯...")
        start_time = datetime.now()
        
        for round_num in range(total_rounds):
            simulated_minutes = round_num * minutes_per_round
            simulated_hour = (simulated_minutes // 60) % 24
            simulated_day = simulated_minutes // (60 * 24) + 1
            
            active_agents = self._get_active_agents_for_round(
                self.env, simulated_hour, round_num
            )
            
            if not active_agents:
                continue
            
            actions = {
                agent: LLMAction()
                for _, agent in active_agents
            }
            
            await self.env.step(actions)
            
            if (round_num + 1) % 10 == 0 or round_num == 0:
                elapsed = (datetime.now() - start_time).total_seconds()
                progress = (round_num + 1) / total_rounds * 100
                print(f"  [Day {simulated_day}, {simulated_hour:02d}:00] "
                      f"Round {round_num + 1}/{total_rounds} ({progress:.1f}%) "
                      f"- {len(active_agents)} agents active "
                      f"- elapsed: {elapsed:.1f}s")
        
        total_elapsed = (datetime.now() - start_time).total_seconds()
        print(f"\nSimulation loop completed!")
        print(f"  - æ€»è€— hour: {total_elapsed:.1f}s")
        print(f"  - æ•°æ®åº“: {db_path}")
        
        # is noEnter waiting command mode
        if self.wait_for_commands:
            print("\n" + "=" * 60)
            print("Enter waiting command mode - çŽ¯å¢ƒä¿æŒè¿è¡Œ")
            print("æ”¯æŒçš„å‘½ä»¤: interview, batch_interview, close_env")
            print("=" * 60)
            
            self.ipc_handler.update_status("alive")
            
            # ç­‰Pendingå‘½ä»¤å¾ªçŽ¯ (ä½¿Useå…¨å±€ _shutdown_event) 
            try:
                while not _shutdown_event.is_set():
                    should_continue = await self.ipc_handler.process_commands()
                    if not should_continue:
                        break
                    try:
                        await asyncio.wait_for(_shutdown_event.wait(), timeout=0.5)
                        break  # æ”¶åˆ°é€€Outputä¿¡å·
                    except asyncio.TimeoutError:
                        pass
            except KeyboardInterrupt:
                print("\næ”¶åˆ°in æ–­ä¿¡å·")
            except asyncio.CancelledError:
                print("\nä»»åŠ¡è¢«å–Delete")
            except Exception as e:
                print(f"\nå‘½ä»¤Locationç†Outputé”™: {e}")
            
            print("\nå…³é—­çŽ¯å¢ƒ...")
        
        # å…³é—­çŽ¯å¢ƒ
        self.ipc_handler.update_status("stopped")
        await self.env.close()
        
        print("Environment is closed")
        print("=" * 60)


async def main():
    parser = argparse.ArgumentParser(description='OASIS Redditæ¨¡Draft')
    parser.add_argument(
        '--config', 
        type=str, 
        required=True,
        help='é…ç½®æ–‡ä»¶è·¯å¾„ (simulation_config.json)'
    )
    parser.add_argument(
        '--max-rounds',
        type=int,
        default=None,
        help='æœ€Largeæ¨¡Draft roundsæ•° (å¯é€‰, UseäºŽæˆªæ–­è¿‡é•¿çš„æ¨¡Draft) '
    )
    parser.add_argument(
        '--no-wait',
        action='store_true',
        default=False,
        help='æ¨¡Draftå®Œæˆafter ç«‹å³å…³é—­çŽ¯å¢ƒ, ä¸Enter waiting command mode'
    )
    
    args = parser.parse_args()
    
    # åœ¨ main å‡½æ•°å¼€Start hourCreate shutdown Event
    global _shutdown_event
    _shutdown_event = asyncio.Event()
    
    if not os.path.exists(args.config):
        print(f"é”™è¯¯: é…ç½®æ–‡ä»¶ä¸å­˜åœ¨: {args.config}")
        sys.exit(1)
    
    # åˆStartTransform dayå¿—é…ç½® (ä½¿Useå›ºå®šæ–‡ä»¶å, æ¸…ç†æ—§ dayå¿—) 
    simulation_dir = os.path.dirname(args.config) or "."
    setup_oasis_logging(os.path.join(simulation_dir, "log"))
    
    runner = RedditSimulationRunner(
        config_path=args.config,
        wait_for_commands=not args.no_wait
    )
    await runner.run(max_rounds=args.max_rounds)


def setup_signal_handlers():
    """
    è®¾ç½®ä¿¡å·Locationç†Device, ç¡®ä¿æ”¶åˆ° SIGTERM/SIGINT  hourèƒ½å¤Ÿæ­£ç¡®é€€Output
    è®©ç¨‹åºhasæœºä¼šæ­£å¸¸æ¸…ç†èµ„Source (å…³é—­æ•°æ®åº“, çŽ¯å¢ƒç­‰) 
    """
    def signal_handler(signum, frame):
        global _cleanup_done
        sig_name = "SIGTERM" if signum == signal.SIGTERM else "SIGINT"
        print(f"\næ”¶åˆ° {sig_name} ä¿¡å·, æ­£åœ¨é€€Output...")
        if not _cleanup_done:
            _cleanup_done = True
            if _shutdown_event:
                _shutdown_event.set()
        else:
            # é‡å¤æ”¶åˆ°ä¿¡å·æ‰Strongåˆ¶é€€Output
            print("Strongåˆ¶é€€Output...")
            sys.exit(1)
    
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)


if __name__ == "__main__":
    setup_signal_handlers()
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nç¨‹åºè¢«in æ–­")
    except SystemExit:
        pass
    finally:
        print("Simulation process has exited")

