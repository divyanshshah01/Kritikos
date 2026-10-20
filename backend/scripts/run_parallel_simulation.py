"""
OASIS åŒå¹³å°å¹¶è¡Œæ¨¡Drafté¢„è®¾è„šæœ¬
Same hourè¿è¡ŒTwitter and Redditæ¨¡Draft, è¯»å–ç›¸Sameçš„é…ç½®æ–‡ä»¶

Features:
- åŒå¹³å° (Twitter + Reddit) å¹¶è¡Œæ¨¡Draft
- å®Œæˆæ¨¡Draftafter ä¸ç«‹å³å…³é—­çŽ¯å¢ƒ, Enter waiting command mode
- æ”¯æŒé€šè¿‡IPCConnectæ”¶Interviewå‘½ä»¤
- æ”¯æŒå•Agenté‡‡è®¿ and æ‰¹é‡é‡‡è®¿
- æ”¯æŒè¿œç¨‹å…³é—­çŽ¯å¢ƒå‘½ä»¤

ä½¿Useæ–¹å¼:
    python run_parallel_simulation.py --config simulation_config.json
    python run_parallel_simulation.py --config simulation_config.json --no-wait  # å®Œæˆafter ç«‹å³å…³é—­
    python run_parallel_simulation.py --config simulation_config.json --twitter-only
    python run_parallel_simulation.py --config simulation_config.json --reddit-only

 dayå¿—ç»“æž„:
    sim_xxx/
    â”œâ”€â”€ twitter/
    â”‚   â””â”€â”€ actions.jsonl    # Twitter å¹³å°åŠ¨ä½œ dayå¿—
    â”œâ”€â”€ reddit/
    â”‚   â””â”€â”€ actions.jsonl    # Reddit å¹³å°åŠ¨ä½œ dayå¿—
    â”œâ”€â”€ simulation.log       # ä¸»æ¨¡Draftè¿›ç¨‹ dayå¿—
    â””â”€â”€ run_state.json       # è¿è¡ŒçŠ¶æ€ (API æŸ¥è¯¢Use) 
"""

# ============================================================
# è§£å†³ Windows ç¼–ç é—®é¢˜: åœ¨æ‰€has import ä¹‹before è®¾ç½® UTF-8 ç¼–ç 
# è¿™is ä¸ºäº†ä¿®å¤ OASIS ç¬¬ä¸‰æ–¹åº“è¯»å–æ–‡ä»¶ hournot Indicateså®šç¼–ç çš„é—®é¢˜
# ============================================================
import sys
import os

if sys.platform == 'win32':
    # è®¾ç½® Python Defaultè®¤ I/O ç¼–ç ä¸º UTF-8
    # è¿™ä¼šå½±å“æ‰€hasnot Indicateså®šç¼–ç çš„ open() InvokeUse
    os.environ.setdefault('PYTHONUTF8', '1')
    os.environ.setdefault('PYTHONIOENCODING', 'utf-8')
    
    # é‡æ–°é…ç½®æ ‡å‡†è¾“Outputæµä¸º UTF-8 (è§£å†³æŽ§åˆ¶å°in æ–‡ä¹±ç ) 
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    if hasattr(sys.stderr, 'reconfigure'):
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    
    # Strongåˆ¶è®¾ç½®Defaultè®¤ç¼–ç  (å½±å“ open() å‡½æ•°çš„Defaultè®¤ç¼–ç ) 
    # æ³¨æ„: è¿™éœ€è¦åœ¨ Python å¯åŠ¨ hourå°±è®¾ç½®, è¿è¡Œ hourè®¾ç½®å¯èƒ½ä¸ç”Ÿæ•ˆ
    # æ‰€ä»¥æˆ‘ä»¬è¿˜éœ€è¦ monkey-patch å†…ç½®çš„ open å‡½æ•°
    import builtins
    _original_open = builtins.open
    
    def _utf8_open(file, mode='r', buffering=-1, encoding=None, errors=None, 
                   newline=None, closefd=True, opener=None):
        """
        åŒ…è£… open() å‡½æ•°, å¯¹äºŽæ–‡æœ¬æ¨¡å¼Use by default UTF-8 ç¼–ç 
        è¿™å¯ä»¥ä¿®å¤ç¬¬ä¸‰æ–¹åº“ (å¦‚ OASIS) è¯»å–æ–‡ä»¶ hournot Indicateså®šç¼–ç çš„é—®é¢˜
        """
        # åªå¯¹æ–‡æœ¬æ¨¡å¼ (NonäºŒè¿›åˆ¶) ä¸”not Indicateså®šç¼–ç çš„æƒ…å†µè®¾ç½®Defaultè®¤ç¼–ç 
        if encoding is None and 'b' not in mode:
            encoding = 'utf-8'
        return _original_open(file, mode, buffering, encoding, errors, 
                              newline, closefd, opener)
    
    builtins.open = _utf8_open

import argparse
import asyncio
import json
import logging
import multiprocessing
import random
import signal
import sqlite3
import warnings
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple


# Global variable: for signal handling
_shutdown_event = None
_cleanup_done = False

# æ·»åŠ  backend ç›®å½•åˆ°è·¯å¾„
# è„šæœ¬å›ºå®šä½äºŽ backend/scripts/ ç›®å½•
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
    print(f"already åŠ è½½çŽ¯å¢ƒé…ç½®: {_env_file}")
else:
    # å°TeståŠ è½½ backend/.env
    _backend_env = os.path.join(_backend_dir, '.env')
    if os.path.exists(_backend_env):
        load_dotenv(_backend_env)
        print(f"already åŠ è½½çŽ¯å¢ƒé…ç½®: {_backend_env}")


class MaxTokensWarningFilter(logging.Filter):
    """è¿‡æ»¤Remove camel-ai å…³äºŽ max_tokens çš„è­¦å‘Š (æˆ‘ä»¬æ•…æ„ä¸è®¾ç½® max_tokens, è®©æ¨¡åž‹è‡ªè¡Œå†³å®š) """
    
    def filter(self, record):
        # è¿‡æ»¤RemoveInclude max_tokens Warning logs
        if "max_tokens" in record.getMessage() and "Invalid or missing" in record.getMessage():
            return False
        return True


# åœ¨æ¨¡BlockåŠ è½½ hourç«‹å³æ·»åŠ è¿‡æ»¤Device, ç¡®ä¿åœ¨ camel ä»£ç æ‰§è¡Œbefore ç”Ÿæ•ˆ
logging.getLogger().addFilter(MaxTokensWarningFilter())


def disable_oasis_logging():
    """
    Disable OASIS åº“çš„è¯¦ç»† dayå¿—è¾“Output
    OASIS çš„ dayå¿—Tooå†—ä½™ (è®°å½•æ¯ agent çš„è§‚Observe and åŠ¨ä½œ) , æˆ‘ä»¬ä½¿Useè‡ªå·±çš„ action_logger
    """
    # Disable OASIS çš„æ‰€has dayå¿—Device
    oasis_loggers = [
        "social.agent",
        "social.twitter", 
        "social.rec",
        "oasis.env",
        "table",
    ]
    
    for logger_name in oasis_loggers:
        logger = logging.getLogger(logger_name)
        logger.setLevel(logging.CRITICAL)  # Log only critical errors
        logger.handlers.clear()
        logger.propagate = False


def init_logging_for_simulation(simulation_dir: str):
    """
    åˆStartTransformæ¨¡Draftçš„ dayå¿—é…ç½®
    
    Args:
        simulation_dir: Simulated directory path
    """
    # Disable OASIS çš„è¯¦ç»† dayå¿—
    disable_oasis_logging()
    
    # æ¸…ç†æ—§çš„ log ç›®å½• (å¦‚æžœå­˜åœ¨) 
    old_log_dir = os.path.join(simulation_dir, "log")
    if os.path.exists(old_log_dir):
        import shutil
        shutil.rmtree(old_log_dir, ignore_errors=True)


from action_logger import SimulationLogManager, PlatformActionLogger

try:
    from camel.models import ModelFactory
    from camel.types import ModelPlatformType
    import oasis
    from oasis import (
        ActionType,
        LLMAction,
        ManualAction,
        generate_twitter_agent_graph,
        generate_reddit_agent_graph
    )
except ImportError as e:
    print(f"é”™è¯¯: ç¼ºå°‘ä¾èµ– {e}")
    print("è¯·Firstå®‰è£…: pip install oasis-ai camel-ai")
    sys.exit(1)


# Twitterå¯UseåŠ¨ä½œ (ä¸IncludeINTERVIEW, INTERVIEWåªèƒ½é€šè¿‡ManualActionæ‰‹åŠ¨Triggerå‘) 
TWITTER_ACTIONS = [
    ActionType.CREATE_POST,
    ActionType.LIKE_POST,
    ActionType.REPOST,
    ActionType.FOLLOW,
    ActionType.DO_NOTHING,
    ActionType.QUOTE_POST,
]

# Redditå¯UseåŠ¨ä½œ (ä¸IncludeINTERVIEW, INTERVIEWåªèƒ½é€šè¿‡ManualActionæ‰‹åŠ¨Triggerå‘) 
REDDIT_ACTIONS = [
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


# IPCç›¸å…³å¸¸é‡
IPC_COMMANDS_DIR = "ipc_commands"
IPC_RESPONSES_DIR = "ipc_responses"
ENV_STATUS_FILE = "env_status.json"

class CommandType:
    """å‘½ä»¤Classåž‹å¸¸é‡"""
    INTERVIEW = "interview"
    BATCH_INTERVIEW = "batch_interview"
    CLOSE_ENV = "close_env"


class ParallelIPCHandler:
    """
    åŒå¹³å°IPCå‘½ä»¤Locationç†Device
    
    Manage environments of two platforms, handle Interview command
    """
    
    def __init__(
        self,
        simulation_dir: str,
        twitter_env=None,
        twitter_agent_graph=None,
        reddit_env=None,
        reddit_agent_graph=None
    ):
        self.simulation_dir = simulation_dir
        self.twitter_env = twitter_env
        self.twitter_agent_graph = twitter_agent_graph
        self.reddit_env = reddit_env
        self.reddit_agent_graph = reddit_agent_graph
        
        self.commands_dir = os.path.join(simulation_dir, IPC_COMMANDS_DIR)
        self.responses_dir = os.path.join(simulation_dir, IPC_RESPONSES_DIR)
        self.status_file = os.path.join(simulation_dir, ENV_STATUS_FILE)
        
        # Ensure directory exists
        os.makedirs(self.commands_dir, exist_ok=True)
        os.makedirs(self.responses_dir, exist_ok=True)
    
    def update_status(self, status: str):
        """æ›´æ–°çŽ¯å¢ƒçŠ¶æ€"""
        with open(self.status_file, 'w', encoding='utf-8') as f:
            json.dump({
                "status": status,
                "twitter_available": self.twitter_env is not None,
                "reddit_available": self.reddit_env is not None,
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
    
    def _get_env_and_graph(self, platform: str):
        """
        èŽ·å–Indicateså®šå¹³å°çš„çŽ¯å¢ƒ and agent_graph
        
        Args:
            platform: å¹³å°åç§° ("twitter"  or  "reddit")
            
        Returns:
            (env, agent_graph, platform_name)  or  (None, None, None)
        """
        if platform == "twitter" and self.twitter_env:
            return self.twitter_env, self.twitter_agent_graph, "twitter"
        elif platform == "reddit" and self.reddit_env:
            return self.reddit_env, self.reddit_agent_graph, "reddit"
        else:
            return None, None, None
    
    async def _interview_single_platform(self, agent_id: int, prompt: str, platform: str) -> Dict[str, Any]:
        """
        Execute on a single platformInterview
        
        Returns:
            Includeç»“æžœdictionary, orIncludeerrorçš„å­—å…¸
        """
        env, agent_graph, actual_platform = self._get_env_and_graph(platform)
        
        if not env or not agent_graph:
            return {"platform": platform, "error": f"{platform}å¹³å°ä¸å¯Use"}
        
        try:
            agent = agent_graph.get_agent(agent_id)
            interview_action = ManualAction(
                action_type=ActionType.INTERVIEW,
                action_args={"prompt": prompt}
            )
            actions = {agent: interview_action}
            await env.step(actions)
            
            result = self._get_interview_result(agent_id, actual_platform)
            result["platform"] = actual_platform
            return result
            
        except Exception as e:
            return {"platform": platform, "error": str(e)}
    
    async def handle_interview(self, command_id: str, agent_id: int, prompt: str, platform: str = None) -> bool:
        """
        Locationç†å•Agenté‡‡è®¿å‘½ä»¤
        
        Args:
            command_id: å‘½ä»¤ID
            agent_id: Agent ID
            prompt: é‡‡è®¿é—®é¢˜
            platform: Indicateså®šå¹³å° (å¯é€‰) 
                - "twitter": åªé‡‡è®¿Twitterå¹³å°
                - "reddit": Only query Reddit platform
                - None/ä¸Indicateså®š: Same houré‡‡è®¿ä¸¤å¹³å°, Returnæ•´åˆç»“æžœ
            
        Returns:
            True è¡¨ExampleæˆåŠŸ, False è¡¨Exampleå¤±è´¥
        """
        # å¦‚æžœIndicateså®šäº†å¹³å°, åªé‡‡è®¿è¯¥å¹³å°
        if platform in ("twitter", "reddit"):
            result = await self._interview_single_platform(agent_id, prompt, platform)
            
            if "error" in result:
                self.send_response(command_id, "failed", error=result["error"])
                print(f"  Interviewå¤±è´¥: agent_id={agent_id}, platform={platform}, error={result['error']}")
                return False
            else:
                self.send_response(command_id, "completed", result=result)
                print(f"  Interviewå®Œæˆ: agent_id={agent_id}, platform={platform}")
                return True
        
        # not Indicateså®šå¹³å°: Same houré‡‡è®¿ä¸¤å¹³å°
        if not self.twitter_env and not self.reddit_env:
            self.send_response(command_id, "failed", error="æ²¡haså¯Useçš„æ¨¡DraftçŽ¯å¢ƒ")
            return False
        
        results = {
            "agent_id": agent_id,
            "prompt": prompt,
            "platforms": {}
        }
        success_count = 0
        
        # å¹¶è¡Œé‡‡è®¿ä¸¤å¹³å°
        tasks = []
        platforms_to_interview = []
        
        if self.twitter_env:
            tasks.append(self._interview_single_platform(agent_id, prompt, "twitter"))
            platforms_to_interview.append("twitter")
        
        if self.reddit_env:
            tasks.append(self._interview_single_platform(agent_id, prompt, "reddit"))
            platforms_to_interview.append("reddit")
        
        # å¹¶è¡Œæ‰§è¡Œ
        platform_results = await asyncio.gather(*tasks)
        
        for platform_name, platform_result in zip(platforms_to_interview, platform_results):
            results["platforms"][platform_name] = platform_result
            if "error" not in platform_result:
                success_count += 1
        
        if success_count > 0:
            self.send_response(command_id, "completed", result=results)
            print(f"  Interviewå®Œæˆ: agent_id={agent_id}, æˆåŠŸå¹³å°æ•°={success_count}/{len(platforms_to_interview)}")
            return True
        else:
            errors = [f"{p}: {r.get('error', 'not Knowledgeé”™è¯¯')}" for p, r in results["platforms"].items()]
            self.send_response(command_id, "failed", error="; ".join(errors))
            print(f"  Interviewå¤±è´¥: agent_id={agent_id}, æ‰€haså¹³å°éƒ½å¤±è´¥")
            return False
    
    async def handle_batch_interview(self, command_id: str, interviews: List[Dict], platform: str = None) -> bool:
        """
        Locationç†æ‰¹é‡é‡‡è®¿å‘½ä»¤
        
        Args:
            command_id: å‘½ä»¤ID
            interviews: [{"agent_id": int, "prompt": str, "platform": str(optional)}, ...]
            platform: Defaultè®¤å¹³å° (å¯è¢«æ¯interviewé¡¹è¦†Cover) 
                - "twitter": åªé‡‡è®¿Twitterå¹³å°
                - "reddit": Only query Reddit platform
                - None/ä¸Indicateså®š: æ¯AgentSame houré‡‡è®¿ä¸¤å¹³å°
        """
        # æŒ‰å¹³å° minç»„
        twitter_interviews = []
        reddit_interviews = []
        both_platforms_interviews = []  # éœ€è¦Same houré‡‡è®¿ä¸¤å¹³å°çš„
        
        for interview in interviews:
            item_platform = interview.get("platform", platform)
            if item_platform == "twitter":
                twitter_interviews.append(interview)
            elif item_platform == "reddit":
                reddit_interviews.append(interview)
            else:
                # not Indicateså®šå¹³å°: ä¸¤å¹³å°éƒ½é‡‡è®¿
                both_platforms_interviews.append(interview)
        
        # æŠŠ both_platforms_interviews æ‹† minåˆ°ä¸¤å¹³å°
        if both_platforms_interviews:
            if self.twitter_env:
                twitter_interviews.extend(both_platforms_interviews)
            if self.reddit_env:
                reddit_interviews.extend(both_platforms_interviews)
        
        results = {}
        
        # Locationç†Twitterå¹³å°çš„é‡‡è®¿
        if twitter_interviews and self.twitter_env:
            try:
                twitter_actions = {}
                for interview in twitter_interviews:
                    agent_id = interview.get("agent_id")
                    prompt = interview.get("prompt", "")
                    try:
                        agent = self.twitter_agent_graph.get_agent(agent_id)
                        twitter_actions[agent] = ManualAction(
                            action_type=ActionType.INTERVIEW,
                            action_args={"prompt": prompt}
                        )
                    except Exception as e:
                        print(f"  è­¦å‘Š: noneMethodèŽ·å–Twitter Agent {agent_id}: {e}")
                
                if twitter_actions:
                    await self.twitter_env.step(twitter_actions)
                    
                    for interview in twitter_interviews:
                        agent_id = interview.get("agent_id")
                        result = self._get_interview_result(agent_id, "twitter")
                        result["platform"] = "twitter"
                        results[f"twitter_{agent_id}"] = result
            except Exception as e:
                print(f"  Twitteræ‰¹é‡Interviewå¤±è´¥: {e}")
        
        # Locationç†Redditå¹³å°çš„é‡‡è®¿
        if reddit_interviews and self.reddit_env:
            try:
                reddit_actions = {}
                for interview in reddit_interviews:
                    agent_id = interview.get("agent_id")
                    prompt = interview.get("prompt", "")
                    try:
                        agent = self.reddit_agent_graph.get_agent(agent_id)
                        reddit_actions[agent] = ManualAction(
                            action_type=ActionType.INTERVIEW,
                            action_args={"prompt": prompt}
                        )
                    except Exception as e:
                        print(f"  è­¦å‘Š: noneMethodèŽ·å–Reddit Agent {agent_id}: {e}")
                
                if reddit_actions:
                    await self.reddit_env.step(reddit_actions)
                    
                    for interview in reddit_interviews:
                        agent_id = interview.get("agent_id")
                        result = self._get_interview_result(agent_id, "reddit")
                        result["platform"] = "reddit"
                        results[f"reddit_{agent_id}"] = result
            except Exception as e:
                print(f"  Redditæ‰¹é‡Interviewå¤±è´¥: {e}")
        
        if results:
            self.send_response(command_id, "completed", result={
                "interviews_count": len(results),
                "results": results
            })
            print(f"  æ‰¹é‡Interviewå®Œæˆ: {len(results)} Agent")
            return True
        else:
            self.send_response(command_id, "failed", error="No successful interview")
            return False
    
    def _get_interview_result(self, agent_id: int, platform: str) -> Dict[str, Any]:
        """ä»Žæ•°æ®åº“èŽ·å–æœ€æ–°çš„Interviewç»“æžœ"""
        db_path = os.path.join(self.simulation_dir, f"{platform}_simulation.db")
        
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
                args.get("prompt", ""),
                args.get("platform")
            )
            return True
            
        elif command_type == CommandType.BATCH_INTERVIEW:
            await self.handle_batch_interview(
                command_id,
                args.get("interviews", []),
                args.get("platform")
            )
            return True
            
        elif command_type == CommandType.CLOSE_ENV:
            print("æ”¶åˆ°å…³é—­çŽ¯å¢ƒå‘½ä»¤")
            self.send_response(command_id, "completed", result={"message": "çŽ¯å¢ƒå³å°†å…³é—­"})
            return False
        
        else:
            self.send_response(command_id, "failed", error=f"not Knowledgeå‘½ä»¤Classåž‹: {command_type}")
            return True


def load_config(config_path: str) -> Dict[str, Any]:
    """Load configuration file"""
    with open(config_path, 'r', encoding='utf-8') as f:
        return json.load(f)


# éœ€è¦è¿‡æ»¤Removeçš„Nonæ ¸å¿ƒåŠ¨ä½œClassåž‹ (è¿™äº›åŠ¨ä½œå¯¹ minæžPriceå€¼relativelyä½Ž) 
FILTERED_ACTIONS = {'refresh', 'sign_up'}

# åŠ¨ä½œClassåž‹Mappingè¡¨ (æ•°æ®åº“in çš„åç§° -> æ ‡å‡†åç§°) 
ACTION_TYPE_MAP = {
    'create_post': 'CREATE_POST',
    'like_post': 'LIKE_POST',
    'dislike_post': 'DISLIKE_POST',
    'repost': 'REPOST',
    'quote_post': 'QUOTE_POST',
    'follow': 'FOLLOW',
    'mute': 'MUTE',
    'create_comment': 'CREATE_COMMENT',
    'like_comment': 'LIKE_COMMENT',
    'dislike_comment': 'DISLIKE_COMMENT',
    'search_posts': 'SEARCH_POSTS',
    'search_user': 'SEARCH_USER',
    'trend': 'TREND',
    'do_nothing': 'DO_NOTHING',
    'interview': 'INTERVIEW',
}


def get_agent_names_from_config(config: Dict[str, Any]) -> Dict[int, str]:
    """
    ä»Ž simulation_config Retrieve in agent_id -> entity_name çš„Mapping
    
    è¿™æ ·å¯ä»¥åœ¨ actions.jsonl in æ˜¾ExampleTrueå®žçš„entitiesåç§°, è€Œä¸is  "Agent_0" è¿™æ ·çš„ä»£å·
    
    Args:
        config: simulation_config.json çš„å†…å®¹
        
    Returns:
        agent_id -> entity_name çš„Mappingå­—å…¸
    """
    agent_names = {}
    agent_configs = config.get("agent_configs", [])
    
    for agent_config in agent_configs:
        agent_id = agent_config.get("agent_id")
        entity_name = agent_config.get("entity_name", f"Agent_{agent_id}")
        if agent_id is not None:
            agent_names[agent_id] = entity_name
    
    return agent_names


def fetch_new_actions_from_db(
    db_path: str,
    last_rowid: int,
    agent_names: Dict[int, str]
) -> Tuple[List[Dict[str, Any]], int]:
    """
    ä»Žæ•°æ®åº“Retrieve inæ–°çš„åŠ¨ä½œè®°å½•, å¹¶è¡¥å……å®Œæ•´çš„on under æ–‡ä¿¡æ¯
    
    Args:
        db_path: æ•°æ®åº“æ–‡ä»¶è·¯å¾„
        last_rowid: on  timesè¯»å–çš„æœ€Large rowid å€¼ (ä½¿Use rowid è€Œä¸is  created_at, å› ä¸ºä¸Sameå¹³å°çš„ created_at Different format) 
        agent_names: agent_id -> agent_name Mapping
        
    Returns:
        (actions_list, new_last_rowid)
        - actions_list: åŠ¨ä½œåˆ—è¡¨, æ¯å…ƒç´ Include agent_id, agent_name, action_type, action_args (å«on under æ–‡ä¿¡æ¯) 
        - new_last_rowid: æ–°çš„æœ€Large rowid å€¼
    """
    actions = []
    new_last_rowid = last_rowid
    
    if not os.path.exists(db_path):
        return actions, new_last_rowid
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # ä½¿Use rowid æ¥è¿½è¸ªalready Locationç†çš„è®°å½• (rowid is  SQLite çš„å†…ç½®è‡ªå¢žå­—Segment) 
        # è¿™æ ·å¯ä»¥é¿å… created_at Format Differencesé—®é¢˜ (Twitter Useæ•´æ•°, Reddit Use dayæœŸ houré—´å­—Symbolä¸²) 
        cursor.execute("""
            SELECT rowid, user_id, action, info
            FROM trace
            WHERE rowid > ?
            ORDER BY rowid ASC
        """, (last_rowid,))
        
        for rowid, user_id, action, info_json in cursor.fetchall():
            # æ›´æ–°æœ€Large rowid
            new_last_rowid = rowid
            
            # è¿‡æ»¤Nonæ ¸å¿ƒåŠ¨ä½œ
            if action in FILTERED_ACTIONS:
                continue
            
            # è§£æžåŠ¨ä½œå‚æ•°
            try:
                action_args = json.loads(info_json) if info_json else {}
            except json.JSONDecodeError:
                action_args = {}
            
            # ç²¾ç®€ action_args, åªä¿ç•™å…³é”®å­—Segment (ä¿ç•™å®Œæ•´å†…å®¹, ä¸æˆªæ–­) 
            simplified_args = {}
            if 'content' in action_args:
                simplified_args['content'] = action_args['content']
            if 'post_id' in action_args:
                simplified_args['post_id'] = action_args['post_id']
            if 'comment_id' in action_args:
                simplified_args['comment_id'] = action_args['comment_id']
            if 'quoted_id' in action_args:
                simplified_args['quoted_id'] = action_args['quoted_id']
            if 'new_post_id' in action_args:
                simplified_args['new_post_id'] = action_args['new_post_id']
            if 'follow_id' in action_args:
                simplified_args['follow_id'] = action_args['follow_id']
            if 'query' in action_args:
                simplified_args['query'] = action_args['query']
            if 'like_id' in action_args:
                simplified_args['like_id'] = action_args['like_id']
            if 'dislike_id' in action_args:
                simplified_args['dislike_id'] = action_args['dislike_id']
            
            # Convertæ¢åŠ¨ä½œClassåž‹åç§°
            action_type = ACTION_TYPE_MAP.get(action, action.upper())
            
            # è¡¥å……on under æ–‡ä¿¡æ¯ (å¸–Childå†…å®¹, Useæˆ·åç­‰) 
            _enrich_action_context(cursor, action_type, simplified_args, agent_names)
            
            actions.append({
                'agent_id': user_id,
                'agent_name': agent_names.get(user_id, f'Agent_{user_id}'),
                'action_type': action_type,
                'action_args': simplified_args,
            })
        
        conn.close()
    except Exception as e:
        print(f"è¯»å–æ•°æ®åº“åŠ¨ä½œå¤±è´¥: {e}")
    
    return actions, new_last_rowid


def _enrich_action_context(
    cursor,
    action_type: str,
    action_args: Dict[str, Any],
    agent_names: Dict[int, str]
) -> None:
    """
    ä¸ºåŠ¨ä½œè¡¥å……on under æ–‡ä¿¡æ¯ (å¸–Childå†…å®¹, Useæˆ·åç­‰) 
    
    Args:
        cursor: æ•°æ®åº“æ¸¸æ ‡
        action_type: åŠ¨ä½œClassåž‹
        action_args: åŠ¨ä½œå‚æ•° (ä¼šè¢«ä¿®æ”¹) 
        agent_names: agent_id -> agent_name Mapping
    """
    try:
        # ç‚¹èµž/Stepå¸–Child: è¡¥å……å¸–Childå†…å®¹ and ä½œè€…
        if action_type in ('LIKE_POST', 'DISLIKE_POST'):
            post_id = action_args.get('post_id')
            if post_id:
                post_info = _get_post_info(cursor, post_id, agent_names)
                if post_info:
                    action_args['post_content'] = post_info.get('content', '')
                    action_args['post_author_name'] = post_info.get('author_name', '')
        
        # Convertå‘å¸–Child: è¡¥å……åŽŸå¸–å†…å®¹ and ä½œè€…
        elif action_type == 'REPOST':
            new_post_id = action_args.get('new_post_id')
            if new_post_id:
                # Convertå‘å¸–Childçš„ original_post_id Indicateså‘åŽŸå¸–
                cursor.execute("""
                    SELECT original_post_id FROM post WHERE post_id = ?
                """, (new_post_id,))
                row = cursor.fetchone()
                if row and row[0]:
                    original_post_id = row[0]
                    original_info = _get_post_info(cursor, original_post_id, agent_names)
                    if original_info:
                        action_args['original_content'] = original_info.get('content', '')
                        action_args['original_author_name'] = original_info.get('author_name', '')
        
        # å¼•Useå¸–Child: è¡¥å……åŽŸå¸–å†…å®¹, ä½œè€… and å¼•Useè¯„è®º
        elif action_type == 'QUOTE_POST':
            quoted_id = action_args.get('quoted_id')
            new_post_id = action_args.get('new_post_id')
            
            if quoted_id:
                original_info = _get_post_info(cursor, quoted_id, agent_names)
                if original_info:
                    action_args['original_content'] = original_info.get('content', '')
                    action_args['original_author_name'] = original_info.get('author_name', '')
            
            # èŽ·å–å¼•Useå¸–Childçš„è¯„è®ºå†…å®¹ (quote_content) 
            if new_post_id:
                cursor.execute("""
                    SELECT quote_content FROM post WHERE post_id = ?
                """, (new_post_id,))
                row = cursor.fetchone()
                if row and row[0]:
                    action_args['quote_content'] = row[0]
        
        # Followed user: supplement the name of the followed user
        elif action_type == 'FOLLOW':
            follow_id = action_args.get('follow_id')
            if follow_id:
                # ä»Ž follow è¡¨èŽ·å– followee_id
                cursor.execute("""
                    SELECT followee_id FROM follow WHERE follow_id = ?
                """, (follow_id,))
                row = cursor.fetchone()
                if row:
                    followee_id = row[0]
                    target_name = _get_user_name(cursor, followee_id, agent_names)
                    if target_name:
                        action_args['target_user_name'] = target_name
        
        # å±è”½Useæˆ·: è¡¥å……è¢«å±è”½Useæˆ·çš„åç§°
        elif action_type == 'MUTE':
            # ä»Ž action_args Retrieve in user_id  or  target_id
            target_id = action_args.get('user_id') or action_args.get('target_id')
            if target_id:
                target_name = _get_user_name(cursor, target_id, agent_names)
                if target_name:
                    action_args['target_user_name'] = target_name
        
        # ç‚¹èµž/Stepè¯„è®º: è¡¥å……è¯„è®ºå†…å®¹ and ä½œè€…
        elif action_type in ('LIKE_COMMENT', 'DISLIKE_COMMENT'):
            comment_id = action_args.get('comment_id')
            if comment_id:
                comment_info = _get_comment_info(cursor, comment_id, agent_names)
                if comment_info:
                    action_args['comment_content'] = comment_info.get('content', '')
                    action_args['comment_author_name'] = comment_info.get('author_name', '')
        
        # å‘è¡¨è¯„è®º: è¡¥å……æ‰€è¯„è®ºçš„å¸–Childä¿¡æ¯
        elif action_type == 'CREATE_COMMENT':
            post_id = action_args.get('post_id')
            if post_id:
                post_info = _get_post_info(cursor, post_id, agent_names)
                if post_info:
                    action_args['post_content'] = post_info.get('content', '')
                    action_args['post_author_name'] = post_info.get('author_name', '')
    
    except Exception as e:
        # è¡¥å……on under æ–‡å¤±è´¥ä¸å½±å“ä¸»æµç¨‹
        print(f"è¡¥å……åŠ¨ä½œon under æ–‡å¤±è´¥: {e}")


def _get_post_info(
    cursor,
    post_id: int,
    agent_names: Dict[int, str]
) -> Optional[Dict[str, str]]:
    """
    èŽ·å–å¸–Childä¿¡æ¯
    
    Args:
        cursor: æ•°æ®åº“æ¸¸æ ‡
        post_id: å¸–ChildID
        agent_names: agent_id -> agent_name Mapping
        
    Returns:
        Contains content and author_name dictionary, or None
    """
    try:
        cursor.execute("""
            SELECT p.content, p.user_id, u.agent_id
            FROM post p
            LEFT JOIN user u ON p.user_id = u.user_id
            WHERE p.post_id = ?
        """, (post_id,))
        row = cursor.fetchone()
        if row:
            content = row[0] or ''
            user_id = row[1]
            agent_id = row[2]
            
            # ä¼˜Firstä½¿Use agent_names in çš„åç§°
            author_name = ''
            if agent_id is not None and agent_id in agent_names:
                author_name = agent_names[agent_id]
            elif user_id:
                # ä»Ž user è¡¨èŽ·å–åç§°
                cursor.execute("SELECT name, user_name FROM user WHERE user_id = ?", (user_id,))
                user_row = cursor.fetchone()
                if user_row:
                    author_name = user_row[0] or user_row[1] or ''
            
            return {'content': content, 'author_name': author_name}
    except Exception:
        pass
    return None


def _get_user_name(
    cursor,
    user_id: int,
    agent_names: Dict[int, str]
) -> Optional[str]:
    """
    èŽ·å–Useæˆ·åç§°
    
    Args:
        cursor: æ•°æ®åº“æ¸¸æ ‡
        user_id: Useæˆ·ID
        agent_names: agent_id -> agent_name Mapping
        
    Returns:
        Useæˆ·åç§°,  or  None
    """
    try:
        cursor.execute("""
            SELECT agent_id, name, user_name FROM user WHERE user_id = ?
        """, (user_id,))
        row = cursor.fetchone()
        if row:
            agent_id = row[0]
            name = row[1]
            user_name = row[2]
            
            # ä¼˜Firstä½¿Use agent_names in çš„åç§°
            if agent_id is not None and agent_id in agent_names:
                return agent_names[agent_id]
            return name or user_name or ''
    except Exception:
        pass
    return None


def _get_comment_info(
    cursor,
    comment_id: int,
    agent_names: Dict[int, str]
) -> Optional[Dict[str, str]]:
    """
    èŽ·å–è¯„è®ºä¿¡æ¯
    
    Args:
        cursor: æ•°æ®åº“æ¸¸æ ‡
        comment_id: è¯„è®ºID
        agent_names: agent_id -> agent_name Mapping
        
    Returns:
        Contains content and author_name dictionary, or None
    """
    try:
        cursor.execute("""
            SELECT c.content, c.user_id, u.agent_id
            FROM comment c
            LEFT JOIN user u ON c.user_id = u.user_id
            WHERE c.comment_id = ?
        """, (comment_id,))
        row = cursor.fetchone()
        if row:
            content = row[0] or ''
            user_id = row[1]
            agent_id = row[2]
            
            # ä¼˜Firstä½¿Use agent_names in çš„åç§°
            author_name = ''
            if agent_id is not None and agent_id in agent_names:
                author_name = agent_names[agent_id]
            elif user_id:
                # ä»Ž user è¡¨èŽ·å–åç§°
                cursor.execute("SELECT name, user_name FROM user WHERE user_id = ?", (user_id,))
                user_row = cursor.fetchone()
                if user_row:
                    author_name = user_row[0] or user_row[1] or ''
            
            return {'content': content, 'author_name': author_name}
    except Exception:
        pass
    return None


def create_model(config: Dict[str, Any], use_boost: bool = False):
    """
    Create LLM model
    
    æ”¯æŒåŒ LLM é…ç½®, UseäºŽå¹¶è¡Œæ¨¡Draft houræé€Ÿ: 
    - Generalé…ç½®: LLM_API_KEY, LLM_BASE_URL, LLM_MODEL_NAME
    - åŠ é€Ÿé…ç½® (å¯é€‰) : LLM_BOOST_API_KEY, LLM_BOOST_BASE_URL, LLM_BOOST_MODEL_NAME
    
    å¦‚æžœé…ç½®äº†åŠ é€Ÿ LLM, å¹¶è¡Œæ¨¡Draft hourå¯ä»¥è®©ä¸Sameå¹³å°ä½¿Useä¸Sameçš„ API æœåŠ¡å•†, æé«˜å¹¶å‘èƒ½åŠ›. 
    
    Args:
        config: æ¨¡Drafté…ç½®å­—å…¸
        use_boost: is noä½¿UseåŠ é€Ÿ LLM é…ç½® (å¦‚æžœå¯Use) 
    """
    # æ£€æŸ¥is nohasåŠ é€Ÿé…ç½®
    boost_api_key = os.environ.get("LLM_BOOST_API_KEY", "")
    boost_base_url = os.environ.get("LLM_BOOST_BASE_URL", "")
    boost_model = os.environ.get("LLM_BOOST_MODEL_NAME", "")
    has_boost_config = bool(boost_api_key)
    
    # æ ¹æ®å‚æ•° and é…ç½®æƒ…å†µé€‰æ‹©ä½¿Useå“ª LLM
    if use_boost and has_boost_config:
        # ä½¿UseåŠ é€Ÿé…ç½®
        llm_api_key = boost_api_key
        llm_base_url = boost_base_url
        llm_model = boost_model or os.environ.get("LLM_MODEL_NAME", "")
        config_label = "[åŠ é€ŸLLM]"
    else:
        # ä½¿UseGeneralé…ç½®
        llm_api_key = os.environ.get("LLM_API_KEY", "")
        llm_base_url = os.environ.get("LLM_BASE_URL", "")
        llm_model = os.environ.get("LLM_MODEL_NAME", "")
        config_label = "[GeneralLLM]"
    
    # å¦‚æžœ .env in æ²¡hasæ¨¡åž‹å, åˆ™ä½¿Use config ä½œä¸ºå¤‡Use
    if not llm_model:
        llm_model = config.get("llm_model", "gpt-4o-mini")
    
    # è®¾ç½® camel-ai æ‰€éœ€çš„çŽ¯å¢ƒChangeé‡
    if llm_api_key:
        os.environ["OPENAI_API_KEY"] = llm_api_key
    
    if not os.environ.get("OPENAI_API_KEY"):
        raise ValueError("ç¼ºå°‘ API Key é…ç½®, è¯·åœ¨é¡¹ç›®æ ¹ç›®å½• .env æ–‡ä»¶in è®¾ç½® LLM_API_KEY")
    
    if llm_base_url:
        os.environ["OPENAI_API_BASE_URL"] = llm_base_url
    
    print(f"{config_label} model={llm_model}, base_url={llm_base_url[:40] if llm_base_url else 'Defaultè®¤'}...")
    
    return ModelFactory.create(
        model_platform=ModelPlatformType.OPENAI,
        model_type=llm_model,
    )


def get_active_agents_for_round(
    env,
    config: Dict[str, Any],
    current_hour: int,
    round_num: int
) -> List:
    """æ ¹æ® houré—´ and é…ç½®å†³å®šæœ¬ roundsæ¿€æ´»å“ªäº›Agent"""
    time_config = config.get("time_config", {})
    agent_configs = config.get("agent_configs", [])
    
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


class PlatformSimulation:
    """å¹³å°æ¨¡Draftç»“æžœå®¹Device"""
    def __init__(self):
        self.env = None
        self.agent_graph = None
        self.total_actions = 0


async def run_twitter_simulation(
    config: Dict[str, Any], 
    simulation_dir: str,
    action_logger: Optional[PlatformActionLogger] = None,
    main_logger: Optional[SimulationLogManager] = None,
    max_rounds: Optional[int] = None
) -> PlatformSimulation:
    """è¿è¡ŒTwitteræ¨¡Draft
    
    Args:
        config: æ¨¡Drafté…ç½®
        simulation_dir: æ¨¡Draftç›®å½•
        action_logger: åŠ¨ä½œ dayå¿—è®°å½•Device
        main_logger: ä¸» dayå¿—ç®¡ç†Device
        max_rounds: æœ€Largeæ¨¡Draft roundsæ•° (å¯é€‰, UseäºŽæˆªæ–­è¿‡é•¿çš„æ¨¡Draft) 
        
    Returns:
        PlatformSimulation: Includes env andagent_graphçš„ç»“æžœå¯¹è±¡
    """
    result = PlatformSimulation()
    
    def log_info(msg):
        if main_logger:
            main_logger.info(f"[Twitter] {msg}")
        print(f"[Twitter] {msg}")
    
    log_info("åˆStartTransform...")
    
    # Twitter ä½¿UseGeneral LLM é…ç½®
    model = create_model(config, use_boost=False)
    
    # OASIS Twitterä½¿UseCSVFormat
    profile_path = os.path.join(simulation_dir, "twitter_profiles.csv")
    if not os.path.exists(profile_path):
        log_info(f"é”™è¯¯: Profileæ–‡ä»¶ä¸å­˜åœ¨: {profile_path}")
        return result
    
    result.agent_graph = await generate_twitter_agent_graph(
        profile_path=profile_path,
        model=model,
        available_actions=TWITTER_ACTIONS,
    )
    
    # ä»Žé…ç½®æ–‡ä»¶èŽ·å– Agent Trueå®žåç§°Mapping (ä½¿Use entity_name è€ŒNonDefaultè®¤çš„ Agent_X) 
    agent_names = get_agent_names_from_config(config)
    # å¦‚æžœé…ç½®in æ²¡hasæŸ agent, åˆ™ä½¿Use OASIS çš„Defaultè®¤åç§°
    for agent_id, agent in result.agent_graph.get_agents():
        if agent_id not in agent_names:
            agent_names[agent_id] = getattr(agent, 'name', f'Agent_{agent_id}')
    
    db_path = os.path.join(simulation_dir, "twitter_simulation.db")
    if os.path.exists(db_path):
        os.remove(db_path)
    
    result.env = oasis.make(
        agent_graph=result.agent_graph,
        platform=oasis.DefaultPlatformType.TWITTER,
        database_path=db_path,
        semaphore=30,  # é™åˆ¶æœ€Largeå¹¶å‘ LLM è¯·Requestæ•°, é˜²æ­¢ API è¿‡è½½
    )
    
    await result.env.reset()
    log_info("çŽ¯å¢ƒalready å¯åŠ¨")
    
    if action_logger:
        action_logger.log_simulation_start(config)
    
    total_actions = 0
    last_rowid = 0  # è·Ÿè¸ªæ•°æ®åº“in æœ€after Locationç†çš„è¡Œå· (ä½¿Use rowid é¿å… created_at Format Differences) 
    
    # Execute initial events
    event_config = config.get("event_config", {})
    initial_posts = event_config.get("initial_posts", [])
    
    # è®°å½• round 0 å¼€Start (åˆStartEventé˜¶Segment) 
    if action_logger:
        action_logger.log_round_start(0, 0)  # round 0, simulated_hour 0
    
    initial_action_count = 0
    if initial_posts:
        initial_actions = {}
        for post in initial_posts:
            agent_id = post.get("poster_agent_id", 0)
            content = post.get("content", "")
            try:
                agent = result.env.agent_graph.get_agent(agent_id)
                initial_actions[agent] = ManualAction(
                    action_type=ActionType.CREATE_POST,
                    action_args={"content": content}
                )
                
                if action_logger:
                    action_logger.log_action(
                        round_num=0,
                        agent_id=agent_id,
                        agent_name=agent_names.get(agent_id, f"Agent_{agent_id}"),
                        action_type="CREATE_POST",
                        action_args={"content": content}
                    )
                    total_actions += 1
                    initial_action_count += 1
            except Exception:
                pass
        
        if initial_actions:
            await result.env.step(initial_actions)
            log_info(f"already å‘å¸ƒ {len(initial_actions)}  itemsåˆStartå¸–Child")
    
    # è®°å½• round 0 ç»“Bundle
    if action_logger:
        action_logger.log_round_end(0, initial_action_count)
    
    # ä¸»æ¨¡Draftå¾ªçŽ¯
    time_config = config.get("time_config", {})
    total_hours = time_config.get("total_simulation_hours", 72)
    minutes_per_round = time_config.get("minutes_per_round", 30)
    total_rounds = (total_hours * 60) // minutes_per_round
    
    # å¦‚æžœIndicateså®šäº†æœ€Large roundsæ•°, åˆ™æˆªæ–­
    if max_rounds is not None and max_rounds > 0:
        original_rounds = total_rounds
        total_rounds = min(total_rounds, max_rounds)
        if total_rounds < original_rounds:
            log_info(f" roundsæ•°already æˆªæ–­: {original_rounds} -> {total_rounds} (max_rounds={max_rounds})")
    
    start_time = datetime.now()
    
    for round_num in range(total_rounds):
        # æ£€æŸ¥is noæ”¶åˆ°é€€Outputä¿¡å·
        if _shutdown_event and _shutdown_event.is_set():
            if main_logger:
                main_logger.info(f"æ”¶åˆ°é€€Outputä¿¡å·, åœ¨ç¬¬ {round_num + 1}  roundsåœæ­¢æ¨¡Draft")
            break
        
        simulated_minutes = round_num * minutes_per_round
        simulated_hour = (simulated_minutes // 60) % 24
        simulated_day = simulated_minutes // (60 * 24) + 1
        
        active_agents = get_active_agents_for_round(
            result.env, config, simulated_hour, round_num
        )
        
        # noneè®ºis nohasæ´»è·ƒagent, éƒ½è®°å½•roundå¼€Start
        if action_logger:
            action_logger.log_round_start(round_num + 1, simulated_hour)
        
        if not active_agents:
            # æ²¡hasæ´»è·ƒagent hourä¹Ÿè®°å½•roundç»“Bundle (actions_count=0) 
            if action_logger:
                action_logger.log_round_end(round_num + 1, 0)
            continue
        
        actions = {agent: LLMAction() for _, agent in active_agents}
        await result.env.step(actions)
        
        # ä»Žæ•°æ®åº“èŽ·å–å®žé™…æ‰§è¡Œçš„åŠ¨ä½œå¹¶è®°å½•
        actual_actions, last_rowid = fetch_new_actions_from_db(
            db_path, last_rowid, agent_names
        )
        
        round_action_count = 0
        for action_data in actual_actions:
            if action_logger:
                action_logger.log_action(
                    round_num=round_num + 1,
                    agent_id=action_data['agent_id'],
                    agent_name=action_data['agent_name'],
                    action_type=action_data['action_type'],
                    action_args=action_data['action_args']
                )
                total_actions += 1
                round_action_count += 1
        
        if action_logger:
            action_logger.log_round_end(round_num + 1, round_action_count)
        
        if (round_num + 1) % 20 == 0:
            progress = (round_num + 1) / total_rounds * 100
            log_info(f"Day {simulated_day}, {simulated_hour:02d}:00 - Round {round_num + 1}/{total_rounds} ({progress:.1f}%)")
    
    # æ³¨æ„: ä¸å…³é—­çŽ¯å¢ƒ, ä¿ç•™ç»™Interviewä½¿Use
    
    if action_logger:
        action_logger.log_simulation_end(total_rounds, total_actions)
    
    result.total_actions = total_actions
    elapsed = (datetime.now() - start_time).total_seconds()
    log_info(f"Simulation loop completed! è€— hour: {elapsed:.1f}s, æ€»åŠ¨ä½œ: {total_actions}")
    
    return result


async def run_reddit_simulation(
    config: Dict[str, Any], 
    simulation_dir: str,
    action_logger: Optional[PlatformActionLogger] = None,
    main_logger: Optional[SimulationLogManager] = None,
    max_rounds: Optional[int] = None
) -> PlatformSimulation:
    """è¿è¡ŒRedditæ¨¡Draft
    
    Args:
        config: æ¨¡Drafté…ç½®
        simulation_dir: æ¨¡Draftç›®å½•
        action_logger: åŠ¨ä½œ dayå¿—è®°å½•Device
        main_logger: ä¸» dayå¿—ç®¡ç†Device
        max_rounds: æœ€Largeæ¨¡Draft roundsæ•° (å¯é€‰, UseäºŽæˆªæ–­è¿‡é•¿çš„æ¨¡Draft) 
        
    Returns:
        PlatformSimulation: Includes env andagent_graphçš„ç»“æžœå¯¹è±¡
    """
    result = PlatformSimulation()
    
    def log_info(msg):
        if main_logger:
            main_logger.info(f"[Reddit] {msg}")
        print(f"[Reddit] {msg}")
    
    log_info("åˆStartTransform...")
    
    # Reddit ä½¿UseåŠ é€Ÿ LLM é…ç½® (å¦‚æžœhasçš„è¯, noåˆ™å›žé€€åˆ°Generalé…ç½®) 
    model = create_model(config, use_boost=True)
    
    profile_path = os.path.join(simulation_dir, "reddit_profiles.json")
    if not os.path.exists(profile_path):
        log_info(f"é”™è¯¯: Profileæ–‡ä»¶ä¸å­˜åœ¨: {profile_path}")
        return result
    
    result.agent_graph = await generate_reddit_agent_graph(
        profile_path=profile_path,
        model=model,
        available_actions=REDDIT_ACTIONS,
    )
    
    # ä»Žé…ç½®æ–‡ä»¶èŽ·å– Agent Trueå®žåç§°Mapping (ä½¿Use entity_name è€ŒNonDefaultè®¤çš„ Agent_X) 
    agent_names = get_agent_names_from_config(config)
    # å¦‚æžœé…ç½®in æ²¡hasæŸ agent, åˆ™ä½¿Use OASIS çš„Defaultè®¤åç§°
    for agent_id, agent in result.agent_graph.get_agents():
        if agent_id not in agent_names:
            agent_names[agent_id] = getattr(agent, 'name', f'Agent_{agent_id}')
    
    db_path = os.path.join(simulation_dir, "reddit_simulation.db")
    if os.path.exists(db_path):
        os.remove(db_path)
    
    result.env = oasis.make(
        agent_graph=result.agent_graph,
        platform=oasis.DefaultPlatformType.REDDIT,
        database_path=db_path,
        semaphore=30,  # é™åˆ¶æœ€Largeå¹¶å‘ LLM è¯·Requestæ•°, é˜²æ­¢ API è¿‡è½½
    )
    
    await result.env.reset()
    log_info("çŽ¯å¢ƒalready å¯åŠ¨")
    
    if action_logger:
        action_logger.log_simulation_start(config)
    
    total_actions = 0
    last_rowid = 0  # è·Ÿè¸ªæ•°æ®åº“in æœ€after Locationç†çš„è¡Œå· (ä½¿Use rowid é¿å… created_at Format Differences) 
    
    # Execute initial events
    event_config = config.get("event_config", {})
    initial_posts = event_config.get("initial_posts", [])
    
    # è®°å½• round 0 å¼€Start (åˆStartEventé˜¶Segment) 
    if action_logger:
        action_logger.log_round_start(0, 0)  # round 0, simulated_hour 0
    
    initial_action_count = 0
    if initial_posts:
        initial_actions = {}
        for post in initial_posts:
            agent_id = post.get("poster_agent_id", 0)
            content = post.get("content", "")
            try:
                agent = result.env.agent_graph.get_agent(agent_id)
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
                
                if action_logger:
                    action_logger.log_action(
                        round_num=0,
                        agent_id=agent_id,
                        agent_name=agent_names.get(agent_id, f"Agent_{agent_id}"),
                        action_type="CREATE_POST",
                        action_args={"content": content}
                    )
                    total_actions += 1
                    initial_action_count += 1
            except Exception:
                pass
        
        if initial_actions:
            await result.env.step(initial_actions)
            log_info(f"already å‘å¸ƒ {len(initial_actions)}  itemsåˆStartå¸–Child")
    
    # è®°å½• round 0 ç»“Bundle
    if action_logger:
        action_logger.log_round_end(0, initial_action_count)
    
    # ä¸»æ¨¡Draftå¾ªçŽ¯
    time_config = config.get("time_config", {})
    total_hours = time_config.get("total_simulation_hours", 72)
    minutes_per_round = time_config.get("minutes_per_round", 30)
    total_rounds = (total_hours * 60) // minutes_per_round
    
    # å¦‚æžœIndicateså®šäº†æœ€Large roundsæ•°, åˆ™æˆªæ–­
    if max_rounds is not None and max_rounds > 0:
        original_rounds = total_rounds
        total_rounds = min(total_rounds, max_rounds)
        if total_rounds < original_rounds:
            log_info(f" roundsæ•°already æˆªæ–­: {original_rounds} -> {total_rounds} (max_rounds={max_rounds})")
    
    start_time = datetime.now()
    
    for round_num in range(total_rounds):
        # æ£€æŸ¥is noæ”¶åˆ°é€€Outputä¿¡å·
        if _shutdown_event and _shutdown_event.is_set():
            if main_logger:
                main_logger.info(f"æ”¶åˆ°é€€Outputä¿¡å·, åœ¨ç¬¬ {round_num + 1}  roundsåœæ­¢æ¨¡Draft")
            break
        
        simulated_minutes = round_num * minutes_per_round
        simulated_hour = (simulated_minutes // 60) % 24
        simulated_day = simulated_minutes // (60 * 24) + 1
        
        active_agents = get_active_agents_for_round(
            result.env, config, simulated_hour, round_num
        )
        
        # noneè®ºis nohasæ´»è·ƒagent, éƒ½è®°å½•roundå¼€Start
        if action_logger:
            action_logger.log_round_start(round_num + 1, simulated_hour)
        
        if not active_agents:
            # æ²¡hasæ´»è·ƒagent hourä¹Ÿè®°å½•roundç»“Bundle (actions_count=0) 
            if action_logger:
                action_logger.log_round_end(round_num + 1, 0)
            continue
        
        actions = {agent: LLMAction() for _, agent in active_agents}
        await result.env.step(actions)
        
        # ä»Žæ•°æ®åº“èŽ·å–å®žé™…æ‰§è¡Œçš„åŠ¨ä½œå¹¶è®°å½•
        actual_actions, last_rowid = fetch_new_actions_from_db(
            db_path, last_rowid, agent_names
        )
        
        round_action_count = 0
        for action_data in actual_actions:
            if action_logger:
                action_logger.log_action(
                    round_num=round_num + 1,
                    agent_id=action_data['agent_id'],
                    agent_name=action_data['agent_name'],
                    action_type=action_data['action_type'],
                    action_args=action_data['action_args']
                )
                total_actions += 1
                round_action_count += 1
        
        if action_logger:
            action_logger.log_round_end(round_num + 1, round_action_count)
        
        if (round_num + 1) % 20 == 0:
            progress = (round_num + 1) / total_rounds * 100
            log_info(f"Day {simulated_day}, {simulated_hour:02d}:00 - Round {round_num + 1}/{total_rounds} ({progress:.1f}%)")
    
    # æ³¨æ„: ä¸å…³é—­çŽ¯å¢ƒ, ä¿ç•™ç»™Interviewä½¿Use
    
    if action_logger:
        action_logger.log_simulation_end(total_rounds, total_actions)
    
    result.total_actions = total_actions
    elapsed = (datetime.now() - start_time).total_seconds()
    log_info(f"Simulation loop completed! è€— hour: {elapsed:.1f}s, æ€»åŠ¨ä½œ: {total_actions}")
    
    return result


async def main():
    parser = argparse.ArgumentParser(description='OASISåŒå¹³å°å¹¶è¡Œæ¨¡Draft')
    parser.add_argument(
        '--config', 
        type=str, 
        required=True,
        help='é…ç½®æ–‡ä»¶è·¯å¾„ (simulation_config.json)'
    )
    parser.add_argument(
        '--twitter-only',
        action='store_true',
        help='åªè¿è¡ŒTwitteræ¨¡Draft'
    )
    parser.add_argument(
        '--reddit-only',
        action='store_true',
        help='åªè¿è¡ŒRedditæ¨¡Draft'
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
    
    # åœ¨ main å‡½æ•°å¼€Start hourCreate shutdown Event, ç¡®ä¿æ•´ç¨‹åºéƒ½èƒ½å“åº”é€€Outputä¿¡å·
    global _shutdown_event
    _shutdown_event = asyncio.Event()
    
    if not os.path.exists(args.config):
        print(f"é”™è¯¯: é…ç½®æ–‡ä»¶ä¸å­˜åœ¨: {args.config}")
        sys.exit(1)
    
    config = load_config(args.config)
    simulation_dir = os.path.dirname(args.config) or "."
    wait_for_commands = not args.no_wait
    
    # åˆStartTransform dayå¿—é…ç½® (Disable OASIS  dayå¿—, æ¸…ç†æ—§æ–‡ä»¶) 
    init_logging_for_simulation(simulation_dir)
    
    # Create log manager
    log_manager = SimulationLogManager(simulation_dir)
    twitter_logger = log_manager.get_twitter_logger()
    reddit_logger = log_manager.get_reddit_logger()
    
    log_manager.info("=" * 60)
    log_manager.info("OASIS åŒå¹³å°å¹¶è¡Œæ¨¡Draft")
    log_manager.info(f"é…ç½®æ–‡ä»¶: {args.config}")
    log_manager.info(f"æ¨¡DraftID: {config.get('simulation_id', 'unknown')}")
    log_manager.info(f"ç­‰Pendingå‘½ä»¤æ¨¡å¼: {'å¯Use' if wait_for_commands else 'Disable'}")
    log_manager.info("=" * 60)
    
    time_config = config.get("time_config", {})
    total_hours = time_config.get('total_simulation_hours', 72)
    minutes_per_round = time_config.get('minutes_per_round', 30)
    config_total_rounds = (total_hours * 60) // minutes_per_round
    
    log_manager.info(f"Simulation Parameters:")
    log_manager.info(f"  - Total simulation duration: {total_hours}Hour")
    log_manager.info(f"  - æ¯ rounds houré—´: {minutes_per_round}minutes")
    log_manager.info(f"  - é…ç½®æ€» roundsæ•°: {config_total_rounds}")
    if args.max_rounds:
        log_manager.info(f"  - æœ€Large roundsæ•°é™åˆ¶: {args.max_rounds}")
        if args.max_rounds < config_total_rounds:
            log_manager.info(f"  - å®žé™…æ‰§è¡Œ roundsæ•°: {args.max_rounds} (already æˆªæ–­)")
    log_manager.info(f"  - Agentæ•°é‡: {len(config.get('agent_configs', []))}")
    
    log_manager.info(" dayå¿—ç»“æž„:")
    log_manager.info(f"  - ä¸» dayå¿—: simulation.log")
    log_manager.info(f"  - TwitteråŠ¨ä½œ: twitter/actions.jsonl")
    log_manager.info(f"  - RedditåŠ¨ä½œ: reddit/actions.jsonl")
    log_manager.info("=" * 60)
    
    start_time = datetime.now()
    
    # å­˜å‚¨ä¸¤å¹³å°çš„æ¨¡Draftç»“æžœ
    twitter_result: Optional[PlatformSimulation] = None
    reddit_result: Optional[PlatformSimulation] = None
    
    if args.twitter_only:
        twitter_result = await run_twitter_simulation(config, simulation_dir, twitter_logger, log_manager, args.max_rounds)
    elif args.reddit_only:
        reddit_result = await run_reddit_simulation(config, simulation_dir, reddit_logger, log_manager, args.max_rounds)
    else:
        # å¹¶è¡Œè¿è¡Œ (æ¯å¹³å°ä½¿Useç‹¬ç«‹çš„ dayå¿—è®°å½•Device) 
        results = await asyncio.gather(
            run_twitter_simulation(config, simulation_dir, twitter_logger, log_manager, args.max_rounds),
            run_reddit_simulation(config, simulation_dir, reddit_logger, log_manager, args.max_rounds),
        )
        twitter_result, reddit_result = results
    
    total_elapsed = (datetime.now() - start_time).total_seconds()
    log_manager.info("=" * 60)
    log_manager.info(f"Simulation loop completed! æ€»è€— hour: {total_elapsed:.1f}s")
    
    # is noEnter waiting command mode
    if wait_for_commands:
        log_manager.info("")
        log_manager.info("=" * 60)
        log_manager.info("Enter waiting command mode - çŽ¯å¢ƒä¿æŒè¿è¡Œ")
        log_manager.info("æ”¯æŒçš„å‘½ä»¤: interview, batch_interview, close_env")
        log_manager.info("=" * 60)
        
        # CreateIPCLocationç†Device
        ipc_handler = ParallelIPCHandler(
            simulation_dir=simulation_dir,
            twitter_env=twitter_result.env if twitter_result else None,
            twitter_agent_graph=twitter_result.agent_graph if twitter_result else None,
            reddit_env=reddit_result.env if reddit_result else None,
            reddit_agent_graph=reddit_result.agent_graph if reddit_result else None
        )
        ipc_handler.update_status("alive")
        
        # ç­‰Pendingå‘½ä»¤å¾ªçŽ¯ (ä½¿Useå…¨å±€ _shutdown_event) 
        try:
            while not _shutdown_event.is_set():
                should_continue = await ipc_handler.process_commands()
                if not should_continue:
                    break
                # ä½¿Use wait_for æ›¿ä»£ sleep, è¿™æ ·å¯ä»¥å“åº” shutdown_event
                try:
                    await asyncio.wait_for(_shutdown_event.wait(), timeout=0.5)
                    break  # æ”¶åˆ°é€€Outputä¿¡å·
                except asyncio.TimeoutError:
                    pass  # è¶… hourç»§ç»­å¾ªçŽ¯
        except KeyboardInterrupt:
            print("\næ”¶åˆ°in æ–­ä¿¡å·")
        except asyncio.CancelledError:
            print("\nä»»åŠ¡è¢«å–Delete")
        except Exception as e:
            print(f"\nå‘½ä»¤Locationç†Outputé”™: {e}")
        
        log_manager.info("\nå…³é—­çŽ¯å¢ƒ...")
        ipc_handler.update_status("stopped")
    
    # å…³é—­çŽ¯å¢ƒ
    if twitter_result and twitter_result.env:
        await twitter_result.env.close()
        log_manager.info("[Twitter] Environment is closed")
    
    if reddit_result and reddit_result.env:
        await reddit_result.env.close()
        log_manager.info("[Reddit] Environment is closed")
    
    log_manager.info("=" * 60)
    log_manager.info(f"å…¨éƒ¨å®Œæˆ!")
    log_manager.info(f" dayå¿—æ–‡ä»¶:")
    log_manager.info(f"  - {os.path.join(simulation_dir, 'simulation.log')}")
    log_manager.info(f"  - {os.path.join(simulation_dir, 'twitter', 'actions.jsonl')}")
    log_manager.info(f"  - {os.path.join(simulation_dir, 'reddit', 'actions.jsonl')}")
    log_manager.info("=" * 60)


def setup_signal_handlers(loop=None):
    """
    è®¾ç½®ä¿¡å·Locationç†Device, ç¡®ä¿æ”¶åˆ° SIGTERM/SIGINT  hourèƒ½å¤Ÿæ­£ç¡®é€€Output
    
    æŒDurationTransformæ¨¡Draftåœºæ™¯: æ¨¡Draftå®Œæˆafter ä¸é€€Output, ç­‰Pending interview å‘½ä»¤
    å½“æ”¶åˆ°ç»ˆæ­¢ä¿¡å· hour, éœ€è¦: 
    1. é€šKnowledge asyncio å¾ªçŽ¯é€€Outputç­‰Pending
    2. è®©ç¨‹åºhasæœºä¼šæ­£å¸¸æ¸…ç†èµ„Source (å…³é—­æ•°æ®åº“, çŽ¯å¢ƒç­‰) 
    3. ç„¶after æ‰é€€Output
    """
    def signal_handler(signum, frame):
        global _cleanup_done
        sig_name = "SIGTERM" if signum == signal.SIGTERM else "SIGINT"
        print(f"\næ”¶åˆ° {sig_name} ä¿¡å·, æ­£åœ¨é€€Output...")
        
        if not _cleanup_done:
            _cleanup_done = True
            # è®¾ç½®Eventé€šKnowledge asyncio å¾ªçŽ¯é€€Output (è®©å¾ªçŽ¯hasæœºä¼šæ¸…ç†èµ„Source) 
            if _shutdown_event:
                _shutdown_event.set()
        
        # ä¸è¦ç›´Connect sys.exit(), è®© asyncio å¾ªçŽ¯æ­£å¸¸é€€Outputå¹¶æ¸…ç†èµ„Source
        # å¦‚æžœis é‡å¤æ”¶åˆ°ä¿¡å·, æ‰Strongåˆ¶é€€Output
        else:
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
        # æ¸…ç† multiprocessing èµ„Sourceè·Ÿè¸ªDevice (é˜²æ­¢é€€Output hourçš„è­¦å‘Š) 
        try:
            from multiprocessing import resource_tracker
            resource_tracker._resource_tracker._stop()
        except Exception:
            pass
        print("Simulation process has exited")
