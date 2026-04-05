"""
Conversational AI Agent with Application Launch Capabilities

This module creates a full conversational AI assistant that can:
1. Chat naturally about anything
2. Launch applications when requested
3. Use LLM (Groq) to decide when to chat vs. when to take action

The LLM has access to a "launch_application" tool that it can call
when the user wants to open an application.
"""

import os
import json
import logging
import re
from typing import Dict, List, Optional, Any
from pathlib import Path
from dotenv import load_dotenv
from system.app_finder import AppFinder

# LangChain imports
try:
    from langchain_groq import ChatGroq
    from langchain_core.tools import tool
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
    LANGCHAIN_AVAILABLE = True
except ImportError:
    LANGCHAIN_AVAILABLE = False
    logging.warning("LangChain not available. Install with: pip install -r requirements.txt")

# Load environment variables
load_dotenv()

logger = logging.getLogger(__name__)


class ConversationalAgent:
    """
    A conversational AI agent that can chat and launch applications.
    
    This agent uses a Groq-hosted LLM with function calling to:
    - Have natural conversations
    - Detect when user wants to launch an app
    - Call the appropriate tool to launch apps
    """
    
    def __init__(self, registry_path: Optional[Path] = None, llm_model: str = "llama-3.1-8b-instant"):
        """
        Initialize the conversational agent.
        
        Args:
            registry_path: Path to app_registry.json
            llm_model: LLM model to use
        """
        self.llm_model = llm_model
        self.llm = None
        self.chat_history: List[Any] = []
        self.available_apps: Dict[str, str] = {}
        self.launch_tool = None
        self.check_tool = None
        self.deep_search_tool = None
        self.app_finder: Optional[AppFinder] = None
        
        # Load registry
        if registry_path and registry_path.exists():
            self._load_registry(registry_path)
            self.app_finder = AppFinder(registry_path=registry_path)
        
        # Initialize LLM and agent
        if LANGCHAIN_AVAILABLE:
            self._initialize_agent()
        else:
            logger.error("LangChain not available. Cannot create conversational agent.")
    
    def _load_registry(self, registry_path: Path) -> None:
        """Load application registry."""
        try:
            with open(registry_path, 'r', encoding='utf-8') as f:
                registry_data = json.load(f)
            self.available_apps = registry_data.get('applications', {})
            logger.info(f"Loaded {len(self.available_apps)} applications")
        except Exception as e:
            logger.error(f"Failed to load registry: {e}")
    
    def _create_launch_tool(self):
        """
        Create a tool for launching applications.
        
        This tool will be available to the LLM to call when needed.
        """
        available_apps = self.available_apps
        
        @tool
        def launch_application(app_name: str) -> str:
            """Launch an application by name. Use this when the user wants to open, launch, start, or use an application.
            
            Args:
                app_name: Name of the application to launch (e.g., 'chrome', 'notepad', 'brave')
            
            Returns:
                JSON string with launch status
            
            Examples:
                - User: "open chrome" -> call launch_application("chrome")
                - User: "I want to use brave" -> call launch_application("brave")
                - User: "launch notepad" -> call launch_application("notepad")
            """
            app_name_lower = app_name.lower().strip()
            
            # Try exact match first
            if app_name_lower in available_apps:
                return json.dumps({
                    "action": "launch",
                    "app_name": app_name_lower,
                    "status": "success",
                    "message": f"Launching {app_name_lower}"
                })
            
            # Try fuzzy match (contains)
            for app in available_apps.keys():
                if app_name_lower in app or app in app_name_lower:
                    return json.dumps({
                        "action": "launch",
                        "app_name": app,
                        "status": "success",
                        "message": f"Launching {app}"
                    })
            
            # App not found
            available_list = ", ".join(list(available_apps.keys())[:10])
            return json.dumps({
                "action": "launch",
                "app_name": app_name_lower,
                "status": "error",
                "message": f"Application '{app_name}' not found. Try: {available_list}..."
            })
        
        return launch_application

    def _create_check_tool(self):
        """Create a tool for checking app presence in registry."""
        app_finder = self.app_finder

        @tool
        def check_application_presence(app_name: str) -> str:
            """Check if an application is available in the registry.

            Use this when user asks if an app exists/is installed/available.
            """
            if not app_finder:
                return json.dumps({
                    "action": "check_presence",
                    "status": "error",
                    "message": "App finder not initialized."
                })

            result = app_finder.find_in_registry(app_name)
            if result["found"]:
                return json.dumps({
                    "action": "check_presence",
                    "status": "success",
                    "app_name": result["match_name"],
                    "path": result["path"],
                    "message": f"'{result['match_name']}' is available."
                })

            return json.dumps({
                "action": "check_presence",
                "status": "not_found",
                "app_name": app_name,
                "message": f"'{app_name}' was not found in the current registry."
            })

        return check_application_presence

    def _create_deep_search_tool(self):
        """Create a tool for deep-searching app executables across disk."""
        app_finder = self.app_finder

        @tool
        def deep_search_application(app_name: str) -> str:
            """Deep-search the device for matching .exe files.

            Use this only when user explicitly asks to search the whole PC/device.
            """
            if not app_finder:
                return json.dumps({
                    "action": "deep_search",
                    "status": "error",
                    "message": "App finder not initialized."
                })

            result = app_finder.deep_search(app_name)
            if result["found"]:
                first = result["matches"][0]
                return json.dumps({
                    "action": "deep_search",
                    "status": "success",
                    "app_name": first["name"],
                    "path": first["path"],
                    "matches": result["matches"],
                    "timed_out": result["timed_out"],
                    "message": f"Found {len(result['matches'])} match(es) for '{app_name}'."
                })

            timeout_note = " (search timed out)" if result["timed_out"] else ""
            return json.dumps({
                "action": "deep_search",
                "status": "not_found",
                "app_name": app_name,
                "matches": [],
                "timed_out": result["timed_out"],
                "message": f"No executable match found for '{app_name}'{timeout_note}."
            })

        return deep_search_application
    
    def _initialize_agent(self) -> None:
        """Initialize the LLM and bind tools."""
        try:
            api_key = os.getenv("GROQ_API_KEY")
            if not api_key or api_key == "your_api_key_here":
                logger.error("GROQ_API_KEY not set. Please create a .env file with your API key.")
                return
            
            self.launch_tool = self._create_launch_tool()
            self.check_tool = self._create_check_tool()
            self.deep_search_tool = self._create_deep_search_tool()
            self.llm = ChatGroq(
                model=self.llm_model,
                api_key=api_key,
                temperature=0.7,
            ).bind_tools([self.launch_tool, self.check_tool, self.deep_search_tool])
            
            logger.info(f"Conversational agent initialized with {self.llm_model}")
            
        except Exception as e:
            logger.error(f"Failed to initialize agent: {e}")
            logger.exception(e)

    def _extract_app_name_from_text(self, user_input: str) -> Optional[str]:
        """Extract probable app name from user text."""
        text = (user_input or "").strip().lower()
        if not text:
            return None

        patterns = [
            r"(?:open|launch|start|run|use)\s+(.+)$",
            r"(?:is|do i have|check if)\s+(.+?)\s+(?:installed|present|available)\??$",
            r"(?:search|find)\s+(.+?)\s+(?:on|in)\s+(?:my\s+)?(?:pc|device|computer|system)\??$",
        ]
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                candidate = match.group(1).strip(" .!?")
                # Trim common leading qualifiers.
                candidate = re.sub(r"^(the|an|a)\s+", "", candidate).strip()
                return candidate or None
        return None

    def _fallback_action_from_text(self, user_input: str, error_text: str) -> Dict[str, Any]:
        """
        Fallback path when LLM tool calling fails.
        Uses deterministic parsing + AppFinder to avoid hard failure.
        """
        text = (user_input or "").lower().strip()
        app_name = self._extract_app_name_from_text(user_input) or ""

        is_deep_search = any(k in text for k in ["whole pc", "whole device", "entire device", "search my pc", "search my device"])
        is_presence_check = any(k in text for k in ["installed", "present", "available", "do i have", "is there"])
        is_launch = any(k in text for k in ["open", "launch", "start", "run", "use"])

        if not self.app_finder:
            return {
                "response": "I hit a tool-call issue and fallback is unavailable right now.",
                "action": None,
                "error": f"LLM tool-call failure: {error_text}",
            }

        if is_deep_search and app_name:
            deep = self.app_finder.deep_search(app_name)
            if deep.get("found"):
                first = deep["matches"][0]
                return {
                    "response": f"I hit a tool-call issue, so I used fallback search and found {first['name']}.",
                    "action": {
                        "action": "deep_search",
                        "status": "success",
                        "app_name": first["name"],
                        "path": first["path"],
                        "matches": deep["matches"],
                        "timed_out": deep["timed_out"],
                        "message": f"Found {len(deep['matches'])} match(es) for '{app_name}'.",
                    },
                    "error": None,
                }
            return {
                "response": f"I hit a tool-call issue, and fallback search did not find '{app_name}'.",
                "action": {
                    "action": "deep_search",
                    "status": "not_found",
                    "app_name": app_name,
                    "matches": [],
                    "timed_out": deep["timed_out"],
                    "message": f"No executable match found for '{app_name}'.",
                },
                "error": None,
            }

        if is_presence_check and app_name:
            present = self.app_finder.find_in_registry(app_name)
            if present.get("found"):
                return {
                    "response": f"I hit a tool-call issue, but fallback check says '{present['match_name']}' is available.",
                    "action": {
                        "action": "check_presence",
                        "status": "success",
                        "app_name": present["match_name"],
                        "path": present["path"],
                        "message": f"'{present['match_name']}' is available.",
                    },
                    "error": None,
                }
            return {
                "response": f"I hit a tool-call issue, and '{app_name}' is not in the current registry.",
                "action": {
                    "action": "check_presence",
                    "status": "not_found",
                    "app_name": app_name,
                    "message": f"'{app_name}' was not found in the current registry.",
                },
                "error": None,
            }

        if is_launch and app_name:
            present = self.app_finder.find_in_registry(app_name)
            launch_name = present["match_name"] if present.get("found") else app_name
            return {
                "response": f"I hit a tool-call issue, so I switched to fallback launch flow for '{launch_name}'.",
                "action": {
                    "action": "launch",
                    "status": "success",
                    "app_name": launch_name,
                    "message": f"Launching {launch_name}",
                },
                "error": None,
            }

        return {
            "response": "I hit a tool-call issue. Please try rephrasing, for example: 'open vscode'.",
            "action": None,
            "error": None,
        }
    
    def chat(self, user_input: str) -> Dict[str, Any]:
        """
        Process user input and generate a response.
        
        The LLM will decide whether to:
        1. Just chat (return a conversational response)
        2. Launch an app (call the launch_application tool)
        
        Args:
            user_input: User's message
            
        Returns:
            Dictionary with response and any actions taken
        """
        if not self.llm or not self.launch_tool:
            return {
                "response": "Sorry, I'm not properly initialized. Please check your GROQ_API_KEY.",
                "action": None,
                "error": "Agent not initialized"
            }
        
        try:
            app_list = ", ".join(list(self.available_apps.keys())[:20])
            if len(self.available_apps) > 20:
                app_list += f"... and {len(self.available_apps) - 20} more"
            
            system_prompt = """You are a helpful AI assistant that can chat naturally AND launch applications on the user's computer.

Your capabilities:
1. Have natural conversations about anything (weather, jokes, questions, advice, etc.)
2. Launch applications when the user requests it
3. Check whether an app is available
4. Deep-search the device when user explicitly asks to search the whole device/PC

When to use tools:
- launch_application:
- User explicitly asks to open/launch/start/use an application
- Examples: "open chrome", "I want to use brave", "launch notepad"

- check_application_presence:
- User asks if an app is installed/present/available
- Examples: "is photoshop installed?", "do I have vscode?"

- deep_search_application:
- User explicitly asks for full-device search
- Examples: "search my whole PC for photoshop", "find X on my device"

When to just chat:
- Greetings: "hello", "hi", "how are you"
- Questions: "what's the weather?", "tell me a joke"
- General conversation: "what can you do?", "help me with..."

Be friendly, helpful, and conversational. If you're not sure which app the user wants, ask for clarification.

Available applications: {app_list}
""".format(app_list=app_list)

            messages: List[Any] = [SystemMessage(content=system_prompt)]
            messages.extend(self.chat_history)
            messages.append(HumanMessage(content=user_input))

            try:
                first_response = self.llm.invoke(messages)
            except Exception as e:
                logger.error(f"LLM tool-call invoke failed, using fallback: {e}")
                logger.exception(e)
                return self._fallback_action_from_text(user_input, str(e))

            action_taken = None
            final_text = first_response.content if hasattr(first_response, "content") else ""

            tool_calls = getattr(first_response, "tool_calls", None) or []
            if tool_calls:
                tool_messages: List[ToolMessage] = []

                for tool_call in tool_calls:
                    tool_name = tool_call.get("name")
                    tool_call_id = tool_call.get("id")
                    tool_args = tool_call.get("args")

                    if tool_args is None:
                        function = tool_call.get("function") or {}
                        arguments = function.get("arguments")
                        if isinstance(arguments, str):
                            try:
                                tool_args = json.loads(arguments)
                            except Exception:
                                tool_args = {}

                    known_tools = {
                        self.launch_tool.name if self.launch_tool else "",
                        self.check_tool.name if self.check_tool else "",
                        self.deep_search_tool.name if self.deep_search_tool else "",
                    }
                    if tool_name not in known_tools:
                        continue

                    target_tool = None
                    if self.launch_tool and tool_name == self.launch_tool.name:
                        target_tool = self.launch_tool
                    elif self.check_tool and tool_name == self.check_tool.name:
                        target_tool = self.check_tool
                    elif self.deep_search_tool and tool_name == self.deep_search_tool.name:
                        target_tool = self.deep_search_tool

                    if not target_tool:
                        continue

                    tool_output = target_tool.invoke(tool_args or {})
                    tool_messages.append(ToolMessage(content=tool_output, tool_call_id=tool_call_id))

                    try:
                        action_data = json.loads(tool_output)
                        if action_data.get("action") in {"launch", "check_presence", "deep_search"}:
                            action_taken = action_data
                    except Exception:
                        pass

                followup_messages: List[Any] = messages + [first_response] + tool_messages
                final_response = self.llm.invoke(followup_messages)
                final_text = final_response.content if hasattr(final_response, "content") else final_text
            else:
                # If no tool call is returned for an obvious action request, use deterministic fallback.
                lowered = user_input.lower()
                if any(k in lowered for k in ["open ", "launch ", "start ", "run ", "use ", "installed", "present", "whole pc", "whole device"]):
                    fallback = self._fallback_action_from_text(user_input, "no_tool_call")
                    if fallback.get("action"):
                        return fallback

            self.chat_history.append(HumanMessage(content=user_input))
            self.chat_history.append(AIMessage(content=final_text))

            if len(self.chat_history) > 10:
                self.chat_history = self.chat_history[-10:]
            
            return {
                "response": final_text,
                "action": action_taken,
                "error": None
            }
            
        except Exception as e:
            logger.error(f"Error in chat: {e}")
            logger.exception(e)
            return {
                "response": f"Sorry, I encountered an error: {str(e)}",
                "action": None,
                "error": str(e)
            }
    
    def reset_history(self) -> None:
        """Clear chat history."""
        self.chat_history = []
        logger.info("Chat history cleared")


# Example usage
if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    
    # Create agent
    registry_path = Path(__file__).parent.parent / 'config' / 'app_registry.json'
    agent = ConversationalAgent(registry_path=registry_path)
    
    # Test conversations
    test_inputs = [
        "Hello! How are you?",
        "What can you do?",
        "Tell me a joke",
        "I want to open chrome",
        "Thanks!",
    ]
    
    print("\n" + "=" * 70)
    print("CONVERSATIONAL AGENT TEST")
    print("=" * 70)
    
    for user_input in test_inputs:
        print(f"\n> {user_input}")
        result = agent.chat(user_input)
        print(f"🤖 {result['response']}")
        if result['action']:
            print(f"⚡ Action: {result['action']}")
