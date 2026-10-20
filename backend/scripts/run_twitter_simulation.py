"""
OASIS Twitter模Draft预设脚本
此脚本读取配置文件in 的参数来执行模Draft, 实现全程自动Transform

Features:
- 完成模Draftafter 不立即关闭环境, Enter waiting command mode
- 支持通过IPCConnect收Interview命令
- 支持单Agent采访 and 批量采访
- 支持远程关闭环境命令

使Use方式:
    python run_twitter_simulation.py --config /path/to/simulation_config.json
    python run_twitter_simulation.py --config /path/to/simulation_config.json --no-wait  # 完成after 立即关闭
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

# 添加项目路径
_scripts_dir = os.path.dirname(os.path.abspath(__file__))
_backend_dir = os.path.abspath(os.path.join(_scripts_dir, '..'))
_project_root = os.path.abspath(os.path.join(_backend_dir, '..'))
sys.path.insert(0, _scripts_dir)
sys.path.insert(0, _backend_dir)

# 加载项目根目录的 .env 文件 (Include LLM_API_KEY 等配置) 
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
    """自定义FormatTransformDevice, 将 Unicode Convert义序列Convert换为可读字Symbol"""
    
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
    """过滤Remove camel-ai 关于 max_tokens 的警告 (我们故意不设置 max_tokens, 让模型自行决定) """
    
    def filter(self, record):
        # 过滤RemoveInclude max_tokens Warning logs
        if "max_tokens" in record.getMessage() and "Invalid or missing" in record.getMessage():
            return False
        return True


# 在模Block加载 hour立即添加过滤Device, 确保在 camel 代码执行before 生效
logging.getLogger().addFilter(MaxTokensWarningFilter())


def setup_oasis_logging(log_dir: str):
    """配置 OASIS 的 day志, 使Use固定名称的 day志文件"""
    os.makedirs(log_dir, exist_ok=True)
    
    # 清理旧的 day志文件
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
        generate_twitter_agent_graph
    )
except ImportError as e:
    print(f"错误: 缺少依赖 {e}")
    print("请First安装: pip install oasis-ai camel-ai")
    sys.exit(1)


# IPC相关常量
IPC_COMMANDS_DIR = "ipc_commands"
IPC_RESPONSES_DIR = "ipc_responses"
ENV_STATUS_FILE = "env_status.json"

class CommandType:
    """命令Class型常量"""
    INTERVIEW = "interview"
    BATCH_INTERVIEW = "batch_interview"
    CLOSE_ENV = "close_env"


class IPCHandler:
    """IPC命令Location理Device"""
    
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
        """更新环境状态"""
        with open(self.status_file, 'w', encoding='utf-8') as f:
            json.dump({
                "status": status,
                "timestamp": datetime.now().isoformat()
            }, f, ensure_ascii=False, indent=2)
    
    def poll_command(self) -> Optional[Dict[str, Any]]:
        """ rounds询获取PendingLocation理命令"""
        if not os.path.exists(self.commands_dir):
            return None
        
        # 获取命令文件 (按 hour间排序) 
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
        
        # Delete命令文件
        command_file = os.path.join(self.commands_dir, f"{command_id}.json")
        try:
            os.remove(command_file)
        except OSError:
            pass
    
    async def handle_interview(self, command_id: str, agent_id: int, prompt: str) -> bool:
        """
        Location理单Agent采访命令
        
        Returns:
            True 表Example成功, False 表Example失败
        """
        try:
            # 获取Agent
            agent = self.agent_graph.get_agent(agent_id)
            
            # Create Interview action
            interview_action = ManualAction(
                action_type=ActionType.INTERVIEW,
                action_args={"prompt": prompt}
            )
            
            # 执行Interview
            actions = {agent: interview_action}
            await self.env.step(actions)
            
            # 从数据库获取结果
            result = self._get_interview_result(agent_id)
            
            self.send_response(command_id, "completed", result=result)
            print(f"  Interview完成: agent_id={agent_id}")
            return True
            
        except Exception as e:
            error_msg = str(e)
            print(f"  Interview失败: agent_id={agent_id}, error={error_msg}")
            self.send_response(command_id, "failed", error=error_msg)
            return False
    
    async def handle_batch_interview(self, command_id: str, interviews: List[Dict]) -> bool:
        """
        Location理批量采访命令
        
        Args:
            interviews: [{"agent_id": int, "prompt": str}, ...]
        """
        try:
            # 构建动作字典
            actions = {}
            agent_prompts = {}  # 记录每agent的prompt
            
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
                    print(f"  警告: noneMethod获取Agent {agent_id}: {e}")
            
            if not actions:
                self.send_response(command_id, "failed", error="没hashas效的Agent")
                return False
            
            # 执行批量Interview
            await self.env.step(actions)
            
            # 获取所has结果
            results = {}
            for agent_id in agent_prompts.keys():
                result = self._get_interview_result(agent_id)
                results[agent_id] = result
            
            self.send_response(command_id, "completed", result={
                "interviews_count": len(results),
                "results": results
            })
            print(f"  批量Interview完成: {len(results)} Agent")
            return True
            
        except Exception as e:
            error_msg = str(e)
            print(f"  批量Interview失败: {error_msg}")
            self.send_response(command_id, "failed", error=error_msg)
            return False
    
    def _get_interview_result(self, agent_id: int) -> Dict[str, Any]:
        """从数据库获取最新的Interview结果"""
        db_path = os.path.join(self.simulation_dir, "twitter_simulation.db")
        
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
            
            # 查询最新的Interview记录
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
            print(f"  读取Interview结果失败: {e}")
        
        return result
    
    async def process_commands(self) -> bool:
        """
        Location理所hasPendingLocation理命令
        
        Returns:
            True 表Example继续运行, False 表Example应该退Output
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
            print("收到关闭环境命令")
            self.send_response(command_id, "completed", result={"message": "环境即将关闭"})
            return False
        
        else:
            self.send_response(command_id, "failed", error=f"not Knowledge命令Class型: {command_type}")
            return True


class TwitterSimulationRunner:
    """Twitter模Draft运行Device"""
    
    # Twitter可Use动作 (不IncludeINTERVIEW, INTERVIEW只能通过ManualAction手动Trigger发) 
    AVAILABLE_ACTIONS = [
        ActionType.CREATE_POST,
        ActionType.LIKE_POST,
        ActionType.REPOST,
        ActionType.FOLLOW,
        ActionType.DO_NOTHING,
        ActionType.QUOTE_POST,
    ]
    
    def __init__(self, config_path: str, wait_for_commands: bool = True):
        """
        初StartTransform模Draft运行Device
        
        Args:
            config_path: 配置文件路径 (simulation_config.json)
            wait_for_commands: 模Draft完成after is no等Pending命令 (Default认True) 
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
        """Get Profile file path (OASIS Twitter uses CSV format) """
        return os.path.join(self.simulation_dir, "twitter_profiles.csv")
    
    def _get_db_path(self) -> str:
        """Get database path"""
        return os.path.join(self.simulation_dir, "twitter_simulation.db")
    
    def _create_model(self):
        """
        Create LLM model
        
        Consistently use project root directory .env Configuration in file (highest priority) : 
        - LLM_API_KEY: APISecret key
        - LLM_BASE_URL: API基BaseURL
        - LLM_MODEL_NAME: 模型名称
        """
        # 优First从 .env 读取配置
        llm_api_key = os.environ.get("LLM_API_KEY", "")
        llm_base_url = os.environ.get("LLM_BASE_URL", "")
        llm_model = os.environ.get("LLM_MODEL_NAME", "")
        
        # 如果 .env If not present, use config as fallback
        if not llm_model:
            llm_model = self.config.get("llm_model", "gpt-4o-mini")
        
        # 设置 camel-ai 所需的环境Change量
        if llm_api_key:
            os.environ["OPENAI_API_KEY"] = llm_api_key
        
        if not os.environ.get("OPENAI_API_KEY"):
            raise ValueError("缺少 API Key 配置, 请在项目根目录 .env 文件in 设置 LLM_API_KEY")
        
        if llm_base_url:
            os.environ["OPENAI_API_BASE_URL"] = llm_base_url
        
        print(f"LLM配置: model={llm_model}, base_url={llm_base_url[:40] if llm_base_url else 'Default认'}...")
        
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
        根据 hour间 and 配置决定本 rounds激活哪些Agent
        
        Args:
            env: OASIS环境
            current_hour: Current simulation hour (0-23) 
            round_num: 当before  rounds数
            
        Returns:
            激活的Agent列表
        """
        time_config = self.config.get("time_config", {})
        agent_configs = self.config.get("agent_configs", [])
        
        # 基Base激活数量
        base_min = time_config.get("agents_per_hour_min", 5)
        base_max = time_config.get("agents_per_hour_max", 20)
        
        # 根据 hourSegmentInvoke整
        peak_hours = time_config.get("peak_hours", [9, 10, 11, 14, 15, 20, 21, 22])
        off_peak_hours = time_config.get("off_peak_hours", [0, 1, 2, 3, 4, 5])
        
        if current_hour in peak_hours:
            multiplier = time_config.get("peak_activity_multiplier", 1.5)
        elif current_hour in off_peak_hours:
            multiplier = time_config.get("off_peak_activity_multiplier", 0.3)
        else:
            multiplier = 1.0
        
        target_count = int(random.uniform(base_min, base_max) * multiplier)
        
        # 根据每Agent的配置计算激活概率
        candidates = []
        for cfg in agent_configs:
            agent_id = cfg.get("agent_id", 0)
            active_hours = cfg.get("active_hours", list(range(8, 23)))
            activity_level = cfg.get("activity_level", 0.5)
            
            # 检查is no在活跃 hour间
            if current_hour not in active_hours:
                continue
            
            # Calculate probability based on activity level
            if random.random() < activity_level:
                candidates.append(agent_id)
        
        # 随机选择
        selected_ids = random.sample(
            candidates, 
            min(target_count, len(candidates))
        ) if candidates else []
        
        # Convert换为Agent对象
        active_agents = []
        for agent_id in selected_ids:
            try:
                agent = env.agent_graph.get_agent(agent_id)
                active_agents.append((agent_id, agent))
            except Exception:
                pass
        
        return active_agents
    
    async def run(self, max_rounds: int = None):
        """运行Twitter模Draft
        
        Args:
            max_rounds: 最Large模Draft rounds数 (可选, Use于截断过长的模Draft) 
        """
        print("=" * 60)
        print("OASIS Twitter模Draft")
        print(f"配置文件: {self.config_path}")
        print(f"模DraftID: {self.config.get('simulation_id', 'unknown')}")
        print(f"等Pending命令模式: {'启Use' if self.wait_for_commands else 'Disable'}")
        print("=" * 60)
        
        # Load time configuration
        time_config = self.config.get("time_config", {})
        total_hours = time_config.get("total_simulation_hours", 72)
        minutes_per_round = time_config.get("minutes_per_round", 30)
        
        # 计算总 rounds数
        total_rounds = (total_hours * 60) // minutes_per_round
        
        # 如果Indicates定了最Large rounds数, 则截断
        if max_rounds is not None and max_rounds > 0:
            original_rounds = total_rounds
            total_rounds = min(total_rounds, max_rounds)
            if total_rounds < original_rounds:
                print(f"\n rounds数already 截断: {original_rounds} -> {total_rounds} (max_rounds={max_rounds})")
        
        print(f"\nSimulation Parameters:")
        print(f"  - Total simulation duration: {total_hours}Hour")
        print(f"  - 每 rounds hour间: {minutes_per_round}minutes")
        print(f"  - 总 rounds数: {total_rounds}")
        if max_rounds:
            print(f"  - 最Large rounds数限制: {max_rounds}")
        print(f"  - Agent数量: {len(self.config.get('agent_configs', []))}")
        
        # Create模型
        print("\n初StartTransformLLM模型...")
        model = self._create_model()
        
        # 加载Agent图
        print("加载Agent Profile...")
        profile_path = self._get_profile_path()
        if not os.path.exists(profile_path):
            print(f"错误: Profile文件不存在: {profile_path}")
            return
        
        self.agent_graph = await generate_twitter_agent_graph(
            profile_path=profile_path,
            model=model,
            available_actions=self.AVAILABLE_ACTIONS,
        )
        
        # 数据库路径
        db_path = self._get_db_path()
        if os.path.exists(db_path):
            os.remove(db_path)
            print(f"already Delete旧数据库: {db_path}")
        
        # Create环境
        print("CreateOASIS环境...")
        self.env = oasis.make(
            agent_graph=self.agent_graph,
            platform=oasis.DefaultPlatformType.TWITTER,
            database_path=db_path,
            semaphore=30,  # 限制最Large并发 LLM 请Request数, 防止 API 过载
        )
        
        await self.env.reset()
        print("环境初StartTransform完成\n")
        
        # 初StartTransformIPCLocation理Device
        self.ipc_handler = IPCHandler(self.simulation_dir, self.env, self.agent_graph)
        self.ipc_handler.update_status("running")
        
        # Execute initial events
        event_config = self.config.get("event_config", {})
        initial_posts = event_config.get("initial_posts", [])
        
        if initial_posts:
            print(f"Execute initial events ({len(initial_posts)} items初Start帖Child)...")
            initial_actions = {}
            for post in initial_posts:
                agent_id = post.get("poster_agent_id", 0)
                content = post.get("content", "")
                try:
                    agent = self.env.agent_graph.get_agent(agent_id)
                    initial_actions[agent] = ManualAction(
                        action_type=ActionType.CREATE_POST,
                        action_args={"content": content}
                    )
                except Exception as e:
                    print(f"  警告: noneMethod为Agent {agent_id}Create初Start帖Child: {e}")
            
            if initial_actions:
                await self.env.step(initial_actions)
                print(f"  already 发布 {len(initial_actions)}  items初Start帖Child")
        
        # 主模Draft循环
        print("\n开Start模Draft循环...")
        start_time = datetime.now()
        
        for round_num in range(total_rounds):
            # 计算当before 模Draft hour间
            simulated_minutes = round_num * minutes_per_round
            simulated_hour = (simulated_minutes // 60) % 24
            simulated_day = simulated_minutes // (60 * 24) + 1
            
            # 获取本 rounds激活的Agent
            active_agents = self._get_active_agents_for_round(
                self.env, simulated_hour, round_num
            )
            
            if not active_agents:
                continue
            
            # 构建动作
            actions = {
                agent: LLMAction()
                for _, agent in active_agents
            }
            
            # Execute action
            await self.env.step(actions)
            
            # 打印进度
            if (round_num + 1) % 10 == 0 or round_num == 0:
                elapsed = (datetime.now() - start_time).total_seconds()
                progress = (round_num + 1) / total_rounds * 100
                print(f"  [Day {simulated_day}, {simulated_hour:02d}:00] "
                      f"Round {round_num + 1}/{total_rounds} ({progress:.1f}%) "
                      f"- {len(active_agents)} agents active "
                      f"- elapsed: {elapsed:.1f}s")
        
        total_elapsed = (datetime.now() - start_time).total_seconds()
        print(f"\nSimulation loop completed!")
        print(f"  - 总耗 hour: {total_elapsed:.1f}s")
        print(f"  - 数据库: {db_path}")
        
        # is noEnter waiting command mode
        if self.wait_for_commands:
            print("\n" + "=" * 60)
            print("Enter waiting command mode - 环境保持运行")
            print("支持的命令: interview, batch_interview, close_env")
            print("=" * 60)
            
            self.ipc_handler.update_status("alive")
            
            # 等Pending命令循环 (使Use全局 _shutdown_event) 
            try:
                while not _shutdown_event.is_set():
                    should_continue = await self.ipc_handler.process_commands()
                    if not should_continue:
                        break
                    try:
                        await asyncio.wait_for(_shutdown_event.wait(), timeout=0.5)
                        break  # 收到退Output信号
                    except asyncio.TimeoutError:
                        pass
            except KeyboardInterrupt:
                print("\n收到in 断信号")
            except asyncio.CancelledError:
                print("\n任务被取Delete")
            except Exception as e:
                print(f"\n命令Location理Output错: {e}")
            
            print("\n关闭环境...")
        
        # 关闭环境
        self.ipc_handler.update_status("stopped")
        await self.env.close()
        
        print("Environment is closed")
        print("=" * 60)


async def main():
    parser = argparse.ArgumentParser(description='OASIS Twitter模Draft')
    parser.add_argument(
        '--config', 
        type=str, 
        required=True,
        help='配置文件路径 (simulation_config.json)'
    )
    parser.add_argument(
        '--max-rounds',
        type=int,
        default=None,
        help='最Large模Draft rounds数 (可选, Use于截断过长的模Draft) '
    )
    parser.add_argument(
        '--no-wait',
        action='store_true',
        default=False,
        help='模Draft完成after 立即关闭环境, 不Enter waiting command mode'
    )
    
    args = parser.parse_args()
    
    # 在 main 函数开Start hourCreate shutdown Event
    global _shutdown_event
    _shutdown_event = asyncio.Event()
    
    if not os.path.exists(args.config):
        print(f"错误: 配置文件不存在: {args.config}")
        sys.exit(1)
    
    # 初StartTransform day志配置 (使Use固定文件名, 清理旧 day志) 
    simulation_dir = os.path.dirname(args.config) or "."
    setup_oasis_logging(os.path.join(simulation_dir, "log"))
    
    runner = TwitterSimulationRunner(
        config_path=args.config,
        wait_for_commands=not args.no_wait
    )
    await runner.run(max_rounds=args.max_rounds)


def setup_signal_handlers():
    """
    设置信号Location理Device, 确保收到 SIGTERM/SIGINT  hour能够正确退Output
    让程序has机会正常清理资Source (关闭数据库, 环境等) 
    """
    def signal_handler(signum, frame):
        global _cleanup_done
        sig_name = "SIGTERM" if signum == signal.SIGTERM else "SIGINT"
        print(f"\n收到 {sig_name} 信号, 正在退Output...")
        if not _cleanup_done:
            _cleanup_done = True
            if _shutdown_event:
                _shutdown_event.set()
        else:
            # 重复收到信号才Strong制退Output
            print("Strong制退Output...")
            sys.exit(1)
    
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)


if __name__ == "__main__":
    setup_signal_handlers()
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n程序被in 断")
    except SystemExit:
        pass
    finally:
        print("Simulation process has exited")
