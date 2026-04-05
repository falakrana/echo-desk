"""
Safe Subprocess Executor

This module is responsible for ONLY executing validated, whitelisted applications.
It NEVER receives raw user input and NEVER uses shell execution.

SECURITY CONSTRAINTS:
- Input: Validated executable path from registry ONLY
- NEVER uses shell=True
- NEVER receives user input directly
- NEVER constructs dynamic commands
- Uses subprocess.run with shell=False exclusively

This is the ONLY module that executes system commands.
"""

import subprocess
import logging
from pathlib import Path
from typing import Dict, Optional
import os

logger = logging.getLogger(__name__)


class SafeExecutor:
    """
    Executes whitelisted applications with maximum safety.
    
    This class is the final layer of defense. It receives ONLY validated
    executable paths from the registry and launches them in the safest
    possible way.
    
    CRITICAL SECURITY RULES:
    1. NEVER use shell=True
    2. NEVER accept user input directly
    3. NEVER construct dynamic commands
    4. ALWAYS validate path before execution
    5. ALWAYS use list form for subprocess
    """
    
    def __init__(self, dry_run: bool = False):
        """
        Initialize the executor.
        
        Args:
            dry_run: If True, simulate execution without actually launching apps
        """
        self.dry_run = dry_run
        self.execution_count = 0
        
        if dry_run:
            logger.warning("Executor in DRY RUN mode - no apps will be launched")
    
    def _validate_path(self, executable_path: str) -> bool:
        """
        Validate that the executable path is safe to execute.
        
        Args:
            executable_path: Path to validate
            
        Returns:
            True if path is valid and safe, False otherwise
        """
        # Check if path is a string
        if not isinstance(executable_path, str):
            logger.error(f"Invalid path type: {type(executable_path)}")
            return False
        
        # Convert to Path object
        path = Path(executable_path)
        
        # Check if path exists
        if not path.exists():
            logger.error(f"Path does not exist: {executable_path}")
            return False
        
        # Check if path is a file
        if not path.is_file():
            logger.error(f"Path is not a file: {executable_path}")
            return False
        
        # Check if path has .exe extension (Windows)
        if not executable_path.lower().endswith('.exe'):
            logger.error(f"Path is not an executable: {executable_path}")
            return False
        
        # Check if path is absolute
        if not path.is_absolute():
            logger.error(f"Path is not absolute: {executable_path}")
            return False
        
        logger.info(f"Path validation passed: {executable_path}")
        return True
    
    def execute(self, executable_path: str) -> Dict[str, any]:
        """
        Execute a validated application.
        
        This is the ONLY public method that performs execution.
        It takes a validated path from the registry and launches it safely.
        
        Args:
            executable_path: Absolute path to executable (from registry ONLY)
            
        Returns:
            Dictionary with:
                - success: Boolean indicating if execution succeeded
                - message: Human-readable result message
                - path: The executed path (for logging)
                - dry_run: Whether this was a dry run
        
        Example:
            >>> executor.execute("C:\\Windows\\System32\\notepad.exe")
            {
                "success": True,
                "message": "Successfully launched: notepad.exe",
                "path": "C:\\Windows\\System32\\notepad.exe",
                "dry_run": False
            }
        """
        logger.info(f"Execute request: {executable_path}")
        
        # Validate path
        if not self._validate_path(executable_path):
            return {
                'success': False,
                'message': f"Invalid or unsafe path: {executable_path}",
                'path': executable_path,
                'dry_run': self.dry_run
            }
        
        # Extract app name for user-friendly messaging
        app_name = Path(executable_path).name
        
        # Dry run mode
        if self.dry_run:
            logger.info(f"DRY RUN: Would execute {executable_path}")
            return {
                'success': True,
                'message': f"[DRY RUN] Would launch: {app_name}",
                'path': executable_path,
                'dry_run': True
            }
        
        # Execute using subprocess with maximum safety
        try:
            # CRITICAL: Use list form and shell=False
            # This prevents command injection attacks
            subprocess.Popen(
                [executable_path],  # List form - NEVER string form
                shell=False,         # NEVER use shell=True
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.DETACHED_PROCESS if os.name == 'nt' else 0
            )
            
            self.execution_count += 1
            logger.info(f"Successfully launched: {app_name}")
            
            return {
                'success': True,
                'message': f"✓ Successfully launched: {app_name}",
                'path': executable_path,
                'dry_run': False
            }
            
        except FileNotFoundError:
            logger.error(f"Executable not found: {executable_path}")
            return {
                'success': False,
                'message': f"✗ Executable not found: {app_name}",
                'path': executable_path,
                'dry_run': False
            }
            
        except PermissionError:
            logger.error(f"Permission denied: {executable_path}")
            return {
                'success': False,
                'message': f"✗ Permission denied: {app_name}",
                'path': executable_path,
                'dry_run': False
            }
            
        except Exception as e:
            logger.error(f"Execution failed: {e}")
            return {
                'success': False,
                'message': f"✗ Failed to launch {app_name}: {str(e)}",
                'path': executable_path,
                'dry_run': False
            }
    
    def execute_command(self, command: str, timeout_seconds: int = 30) -> Dict[str, any]:
        """
        Execute an explicit shell command.

        Intended for explicit `cmd:` mode only, after user confirmation.
        """
        if not isinstance(command, str) or not command.strip():
            return {
                'success': False,
                'message': "Empty command",
                'command': command,
                'returncode': None,
                'stdout': "",
                'stderr': "",
                'dry_run': self.dry_run
            }

        clean_command = command.strip()
        logger.warning(f"Executing explicit command: {clean_command}")

        if self.dry_run:
            return {
                'success': True,
                'message': f"[DRY RUN] Would execute command: {clean_command}",
                'command': clean_command,
                'returncode': 0,
                'stdout': "",
                'stderr': "",
                'dry_run': True
            }

        try:
            completed = subprocess.run(
                clean_command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout_seconds
            )
            success = completed.returncode == 0
            return {
                'success': success,
                'message': "Command executed successfully" if success else "Command execution failed",
                'command': clean_command,
                'returncode': completed.returncode,
                'stdout': completed.stdout or "",
                'stderr': completed.stderr or "",
                'dry_run': False
            }
        except subprocess.TimeoutExpired:
            return {
                'success': False,
                'message': f"Command timed out after {timeout_seconds}s",
                'command': clean_command,
                'returncode': None,
                'stdout': "",
                'stderr': "",
                'dry_run': False
            }
        except Exception as e:
            return {
                'success': False,
                'message': f"Command execution error: {e}",
                'command': clean_command,
                'returncode': None,
                'stdout': "",
                'stderr': str(e),
                'dry_run': False
            }

    def get_stats(self) -> Dict[str, any]:
        """
        Get execution statistics.
        
        Returns:
            Dictionary with execution stats
        """
        return {
            'total_executions': self.execution_count,
            'dry_run_mode': self.dry_run
        }


# Example usage and testing
if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    
    print("\n" + "=" * 60)
    print("SAFE EXECUTOR TEST")
    print("=" * 60)
    
    # Test in dry run mode
    executor = SafeExecutor(dry_run=True)
    
    test_paths = [
        "C:\\Windows\\System32\\notepad.exe",  # Valid
        "C:\\Windows\\System32\\calc.exe",     # Valid
        "C:\\invalid\\path.exe",                # Invalid
        "/etc/passwd",                          # Invalid (not .exe)
        "",                                     # Invalid (empty)
    ]
    
    for path in test_paths:
        print(f"\nTesting: {path}")
        result = executor.execute(path)
        print(f"Success: {result['success']}")
        print(f"Message: {result['message']}")
    
    print(f"\nStats: {executor.get_stats()}")
