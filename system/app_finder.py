"""
Application Finder

Provides fast app lookup via registry and optional deep disk search for .exe files.
"""

import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class AppFinder:
    """Find applications by name from registry and filesystem."""

    def __init__(self, registry_path: Path):
        self.registry_path = Path(registry_path)
        self.available_apps: Dict[str, str] = {}
        self._load_registry()

    def _load_registry(self) -> None:
        """Load app registry from disk."""
        if not self.registry_path.exists():
            logger.warning(f"Registry path does not exist: {self.registry_path}")
            return

        try:
            with open(self.registry_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.available_apps = data.get("applications", {})
            logger.info(f"AppFinder loaded {len(self.available_apps)} registry apps")
        except Exception as e:
            logger.error(f"Failed to load app registry: {e}")

    @staticmethod
    def _normalize(text: str) -> str:
        return "".join(ch for ch in text.lower().strip() if ch.isalnum())

    def find_in_registry(self, app_name: str) -> Dict[str, Any]:
        """
        Find app in cached registry.

        Returns:
            {
              "found": bool,
              "requested": str,
              "match_name": Optional[str],
              "path": Optional[str],
              "source": "registry"
            }
        """
        requested = (app_name or "").strip()
        requested_key = requested.lower()
        requested_norm = self._normalize(requested)

        if not requested:
            return {
                "found": False,
                "requested": requested,
                "match_name": None,
                "path": None,
                "source": "registry",
            }

        if requested_key in self.available_apps:
            return {
                "found": True,
                "requested": requested,
                "match_name": requested_key,
                "path": self.available_apps[requested_key],
                "source": "registry",
            }

        # Fuzzy contains match on app keys
        for key, path in self.available_apps.items():
            key_norm = self._normalize(key)
            if requested_norm and (requested_norm in key_norm or key_norm in requested_norm):
                return {
                    "found": True,
                    "requested": requested,
                    "match_name": key,
                    "path": path,
                    "source": "registry",
                }

        return {
            "found": False,
            "requested": requested,
            "match_name": None,
            "path": None,
            "source": "registry",
        }

    def deep_search(
        self,
        app_name: str,
        search_roots: Optional[List[Path]] = None,
        timeout_seconds: int = 30,
        max_results: int = 5,
    ) -> Dict[str, Any]:
        """
        Deep-search filesystem for matching executable names.
        """
        requested = (app_name or "").strip()
        requested_norm = self._normalize(requested)
        if not requested_norm:
            return {
                "found": False,
                "requested": requested,
                "matches": [],
                "timed_out": False,
                "searched_roots": [],
                "source": "deep_search",
            }

        if search_roots is None:
            search_roots = [Path("C:\\")]

        matches: List[Dict[str, str]] = []
        started = time.time()
        timed_out = False
        scanned_roots: List[str] = []

        for root in search_roots:
            root = Path(root)
            scanned_roots.append(str(root))
            if not root.exists():
                continue

            for dirpath, _, filenames in os.walk(root, topdown=True):
                if time.time() - started > timeout_seconds:
                    timed_out = True
                    break

                for filename in filenames:
                    if not filename.lower().endswith(".exe"):
                        continue

                    stem_norm = self._normalize(Path(filename).stem)
                    if requested_norm in stem_norm or stem_norm in requested_norm:
                        full_path = str(Path(dirpath) / filename)
                        matches.append(
                            {
                                "name": Path(filename).stem.lower(),
                                "path": full_path,
                            }
                        )
                        if len(matches) >= max_results:
                            break

                if len(matches) >= max_results:
                    break

            if timed_out or len(matches) >= max_results:
                break

        return {
            "found": len(matches) > 0,
            "requested": requested,
            "matches": matches,
            "timed_out": timed_out,
            "searched_roots": scanned_roots,
            "source": "deep_search",
        }
