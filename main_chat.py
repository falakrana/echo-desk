"""
AI Desktop Agent - Conversational Chat Mode

Alternative entry point that supports:
- Natural chat
- App launch requests
- App presence checks
- Explicit deep-search requests
- Explicit command execution via `cmd:` prefix with confirmation
"""

import sys
import logging
from pathlib import Path
from typing import Optional

from llm.chat_agent import ConversationalAgent
from system.executor import SafeExecutor
from system.app_finder import AppFinder
from memory.state import AgentMemory
from ui.cli import CLI


_handlers = [logging.StreamHandler()]
try:
    _handlers.insert(0, logging.FileHandler('agent_chat.log'))
except Exception:
    # Continue without file logging if log file is locked/unwritable.
    pass

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=_handlers
)
logger = logging.getLogger(__name__)


class ChatDesktopAgent:
    """Conversational desktop agent orchestrator."""

    def __init__(self, config_dir: Optional[Path] = None, dry_run: bool = False):
        if config_dir is None:
            config_dir = Path(__file__).parent / 'config'

        self.config_dir = Path(config_dir)
        self.registry_path = self.config_dir / 'app_registry.json'
        self.memory_path = self.config_dir / 'memory.json'
        self.dry_run = dry_run

        self.cli = CLI()
        self.executor = SafeExecutor(dry_run=dry_run)
        self.memory = AgentMemory(persist_path=self.memory_path)

        if not self.registry_path.exists():
            self.cli.show_error('Application registry not found!')
            self.cli.show_warning('Please run bootstrap scan first:')
            self.cli.show_info('  python -m tools.bootstrap_scan')
            sys.exit(1)

        self.agent = ConversationalAgent(
            registry_path=self.registry_path,
            llm_model='llama-3.1-8b-instant'
        )
        self.app_finder = AppFinder(registry_path=self.registry_path)

        logger.info('Chat Desktop Agent initialized')

    def _handle_special_command(self, user_input: str) -> bool:
        command = user_input.lower().strip()

        if command in ['help', '?']:
            self._show_chat_help()
            return True
        if command == 'list':
            self.cli.show_app_list(self.agent.available_apps)
            return True
        if command == 'stats':
            stats = self.memory.get_stats()
            self.cli.show_stats(stats)
            return True
        if command == 'clear':
            if self.cli.confirm('Clear chat history and memory?'):
                self.agent.reset_history()
                self.memory.clear()
                self.cli.show_success('Chat history and memory cleared')
            return True
        if command in ['exit', 'quit', 'q']:
            return True
        return False

    def _show_chat_help(self) -> None:
        help_text = """
CONVERSATIONAL CHAT MODE

You can:
- Chat naturally
- Ask to open apps
- Ask if an app is present/installed
- Ask for full deep search on device
- Use explicit command mode: cmd: <command>

Special commands:
  help      - Show this help message
  list      - List available registry applications
  stats     - Show memory stats
  clear     - Clear chat history and memory
  exit      - Exit the agent

Examples:
  "open chrome"
  "is vscode installed?"
  "search my whole pc for photoshop"
  "cmd: ipconfig"
        """
        print(self.cli._colorize(help_text, 'blue'))

    def _handle_explicit_command(self, user_input: str) -> bool:
        if not user_input.lower().startswith('cmd:'):
            return False

        command = user_input[4:].strip()
        if not command:
            self.cli.show_error('No command provided. Usage: cmd: <your command>')
            self.memory.record(user_input, 'execute_command', 1.0, None, False, 'Empty command')
            return True

        self.cli.show_warning('Explicit command mode requested.')
        self.cli.show_info(f'Command preview: {command}')
        if not self.cli.confirm('Execute this command?'):
            self.cli.show_info('Command cancelled.')
            self.memory.record(user_input, 'execute_command', 1.0, None, False, 'User cancelled command')
            return True

        result = self.executor.execute_command(command)
        if result.get('success'):
            self.cli.show_success(result.get('message', 'Command executed'))
        else:
            self.cli.show_error(result.get('message', 'Command failed'))

        stdout_text = (result.get('stdout') or '').strip()
        stderr_text = (result.get('stderr') or '').strip()
        if stdout_text:
            self.cli.show_info(f"stdout:\n{stdout_text[:500]}")
        if stderr_text:
            self.cli.show_warning(f"stderr:\n{stderr_text[:500]}")

        self.memory.record(
            user_input=user_input,
            goal='execute_command',
            confidence=1.0,
            app_name=None,
            success=result.get('success', False),
            message=result.get('message', 'Command executed')
        )
        return True

    def _handle_launch_action(self, user_input: str, action: dict) -> None:
        requested_app = (action.get('app_name') or '').strip()
        lookup = self.app_finder.find_in_registry(requested_app)
        resolved_name = lookup.get('match_name') or requested_app
        executable_path = lookup.get('path')

        if not executable_path:
            self.cli.show_info(f"'{requested_app}' not found in registry. Running deep search...")
            deep = self.app_finder.deep_search(requested_app)
            if deep.get('found'):
                match = deep['matches'][0]
                resolved_name = match['name']
                executable_path = match['path']
                self.cli.show_info(f"Using deep-search match: {resolved_name}")
            else:
                self.cli.show_error(f"Application '{requested_app}' not found.")
                self.memory.record(user_input, f'launch_{requested_app}', 1.0, requested_app, False, 'App not found')
                return

        exec_result = self.executor.execute(executable_path)
        if exec_result['success']:
            self.cli.show_success(f"Launched {resolved_name}")
        else:
            self.cli.show_error(f"Failed to launch {resolved_name}: {exec_result['message']}")

        self.memory.record(
            user_input=user_input,
            goal=f'launch_{resolved_name}',
            confidence=1.0,
            app_name=resolved_name,
            success=exec_result['success'],
            message=exec_result['message']
        )

    def _handle_check_presence_action(self, user_input: str, action: dict) -> None:
        found = action.get('status') == 'success'
        app_name = action.get('app_name')

        if found:
            self.cli.show_success(action.get('message', f"'{app_name}' is available."))
            if action.get('path'):
                self.cli.show_info(f"Path: {action['path']}")
        else:
            self.cli.show_warning(action.get('message', 'App not found in registry.'))

        self.memory.record(
            user_input=user_input,
            goal='check_app_presence',
            confidence=1.0,
            app_name=app_name,
            success=found,
            message=action.get('message', '')
        )

    def _handle_deep_search_action(self, user_input: str, action: dict) -> None:
        status = action.get('status')
        app_name = action.get('app_name')

        if status == 'success':
            matches = action.get('matches', [])
            self.cli.show_success(action.get('message', 'Deep search found matches.'))
            for match in matches[:5]:
                self.cli.show_info(f"- {match.get('name')}: {match.get('path')}")
            success = True
        else:
            self.cli.show_warning(action.get('message', 'No matches found.'))
            success = False

        self.memory.record(
            user_input=user_input,
            goal='deep_search_app',
            confidence=1.0,
            app_name=app_name,
            success=success,
            message=action.get('message', '')
        )

    def process_chat(self, user_input: str) -> None:
        logger.info(f'Processing chat: {user_input}')

        if self._handle_explicit_command(user_input):
            return

        result = self.agent.chat(user_input)
        response = result.get('response', '')
        action = result.get('action')
        error = result.get('error')

        if error:
            self.cli.show_error(f'Error: {error}')
            self.memory.record(user_input, 'error', 0.0, None, False, error)
            return

        if response:
            self.cli.show_chat_response(response)

        if action:
            action_type = action.get('action')
            if action_type == 'launch':
                self._handle_launch_action(user_input, action)
                return
            if action_type == 'check_presence':
                self._handle_check_presence_action(user_input, action)
                return
            if action_type == 'deep_search':
                self._handle_deep_search_action(user_input, action)
                return

        self.memory.record(
            user_input=user_input,
            goal='chat',
            confidence=1.0,
            app_name=None,
            success=True,
            message='Chat response'
        )

    def run(self) -> None:
        banner = """
AI DESKTOP AGENT - Conversational Chat Mode
Chat naturally, open apps, check app presence, and run explicit cmd: commands.
        """
        print(self.cli._colorize(banner, 'cyan'))

        if self.dry_run:
            self.cli.show_warning('Running in DRY RUN mode - no apps/commands will execute')

        self.cli.show_info(f"Loaded {len(self.agent.available_apps)} applications")
        self.cli.show_info("Type 'help' for commands or just start chatting")

        while True:
            try:
                user_input = self.cli.prompt_input()
                if not user_input:
                    continue
                if user_input.lower() in ['exit', 'quit', 'q']:
                    break
                if self._handle_special_command(user_input):
                    if user_input.lower() in ['exit', 'quit', 'q']:
                        break
                    continue

                self.process_chat(user_input)

            except KeyboardInterrupt:
                print('\n')
                break
            except Exception as e:
                logger.error(f'Unexpected error: {e}', exc_info=True)
                self.cli.show_error(f'An error occurred: {e}')

        self.cli.show_goodbye()

        stats = self.memory.get_stats()
        if stats['total_interactions'] > 0:
            self.cli.show_stats(stats)


def main():
    import argparse

    parser = argparse.ArgumentParser(description='AI Desktop Agent - Conversational Chat Mode')
    parser.add_argument('--dry-run', action='store_true', help='Simulate execution without launching apps')
    parser.add_argument('--config-dir', type=Path, help='Path to config directory')

    args = parser.parse_args()

    agent = ChatDesktopAgent(config_dir=args.config_dir, dry_run=args.dry_run)
    agent.run()


if __name__ == '__main__':
    main()
