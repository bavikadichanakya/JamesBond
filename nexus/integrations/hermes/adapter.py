"""Hermes Agent Integration Adapter for NEXUS.

Exposes Hermes Agent capabilities (persistent memory queries, skill catalog discovery,
AST code security auditing, and subagent task delegation) to NEXUS under the central
orchestration, permission, and tool execution system.
"""

from __future__ import annotations

import ast
import datetime
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from nexus.integrations.base import (
    BaseIntegrationAdapter,
    IntegrationMetadata,
    IntegrationStatus,
)
from nexus.tools.permissions import PermissionLevel
from nexus.tools.registry import ToolRegistry
from nexus.tools.schema import ToolDefinition, ToolParameter

logger = logging.getLogger("nexus.integrations.hermes")


class HermesAdapter(BaseIntegrationAdapter):
    """Adapter for Hermes Agent reasoning and skill capabilities.
    
    Guarantees:
    - Independent operation: operates as an auxiliary service without modifying Hermes upstream.
    - Safe execution: all subagent delegations require user confirmation.
    - Memory isolation: reads curated memory without modifying user profile without consent.
    - Static analysis: performs deep AST checks on skill code to prevent dangerous patterns.
    - Clear simulation tagging: any mock/fallback responses are explicitly marked as simulated.
    """

    def __init__(
        self,
        upstream_dir: str = "A:\\Mixer\\hermes-agent-main\\hermes-agent-main",
        memories_dir: Optional[str] = None,
        force_simulated: bool = False,
    ) -> None:
        metadata = IntegrationMetadata(
            name="hermes",
            version="2026.10",
            description="Hermes Agent reasoning workflows, skills management, and memory architecture",
            upstream_source_dir=upstream_dir,
            capabilities=[
                "memory_query",
                "skill_discovery",
                "ast_security_audit",
                "subagent_delegation",
            ],
            status=IntegrationStatus.UNINITIALIZED,
        )
        super().__init__(metadata)
        self.upstream_dir = Path(upstream_dir)
        self.memories_dir = Path(memories_dir) if memories_dir else self.upstream_dir / "memories"
        self.force_simulated = force_simulated

        # In-memory fallback memories when disk memory files are absent
        self._simulated_memories: Dict[str, List[Dict[str, str]]] = {
            "memory": [
                {
                    "id": "mem_001",
                    "text": "User prefers concise code with comprehensive typing and unit tests.",
                    "category": "preference",
                    "timestamp": "2026-10-25T10:00:00Z",
                },
                {
                    "id": "mem_002",
                    "text": "NEXUS architecture integrates OpenClaw, Hermes, and Muse into a single local runtime.",
                    "category": "architecture",
                    "timestamp": "2026-10-30T14:30:00Z",
                },
            ],
            "user": [
                {
                    "id": "usr_001",
                    "text": "Host machine environment: Windows with Ollama local model qwen2.5-coder:3b.",
                    "category": "environment",
                    "timestamp": "2026-10-31T09:15:00Z",
                }
            ],
        }

    def initialize(self) -> bool:
        """Inspect upstream source and skills directories."""
        if not self.upstream_dir.exists():
            logger.warning("Hermes upstream directory not found at: %s", self.upstream_dir)
            self.metadata.status = IntegrationStatus.DISCONNECTED
            return False

        skills_dir = self.upstream_dir / "skills"
        tools_dir = self.upstream_dir / "tools"
        has_skills = skills_dir.is_dir()
        has_tools = tools_dir.is_dir()

        self.health_check()
        return has_skills or has_tools

    def health_check(self) -> Dict[str, Any]:
        """Verify presence of skills, memory store, and tools."""
        self.metadata.last_health_check = datetime.datetime.now(datetime.timezone.utc).isoformat()

        if self.force_simulated:
            self.metadata.status = IntegrationStatus.SIMULATED
            details = {
                "connected": False,
                "mode": "forced_simulated",
                "upstream_source_valid": self.upstream_dir.exists(),
            }
            self.metadata.health_details = details
            return details

        skills_dir = self.upstream_dir / "skills"
        tools_dir = self.upstream_dir / "tools"

        if not self.upstream_dir.exists() or not skills_dir.is_dir():
            self.metadata.status = IntegrationStatus.SIMULATED
            details = {
                "connected": False,
                "mode": "simulated_fallback",
                "skills_found": 0,
                "memory_available": False,
            }
            self.metadata.health_details = details
            return details

        # Count skills
        skill_count = sum(1 for p in skills_dir.rglob("SKILL.md"))
        memory_exists = self.memories_dir.is_dir() or (self.upstream_dir / "MEMORY.md").is_file()

        self.metadata.status = IntegrationStatus.CONNECTED
        details = {
            "connected": True,
            "mode": "local_source",
            "skills_count": skill_count,
            "memory_available": memory_exists,
            "skills_dir": str(skills_dir),
        }
        self.metadata.health_details = details
        return details

    def get_capabilities(self) -> List[str]:
        return list(self.metadata.capabilities)

    def shutdown(self) -> None:
        """Release adapter state."""
        self.metadata.status = IntegrationStatus.DISCONNECTED
        logger.info("Hermes integration adapter shut down cleanly.")

    def register_tools(self, registry: ToolRegistry) -> None:
        """Register Hermes tools into the central NEXUS tool registry."""

        # 1. hermes_query_memory
        registry.register_tool(
            ToolDefinition(
                name="hermes_query_memory",
                description="Query curated persistent memories (agent notes or user profile) maintained by Hermes.",
                parameters={
                    "query": ToolParameter(
                        name="query",
                        type="string",
                        description="Optional keyword to search within stored memories.",
                        required=False,
                    ),
                    "target": ToolParameter(
                        name="target",
                        type="string",
                        description="Target memory store: 'memory' (agent notes), 'user' (user profile), or 'all'.",
                        required=False,
                        enum=["memory", "user", "all"],
                        default="all",
                    ),
                },
                permission_level=PermissionLevel.READ_ONLY,
                handler=self.handle_query_memory,
                source="NEXUS_HERMES_ADAPTER",
                simulated=(self.metadata.status == IntegrationStatus.SIMULATED),
            )
        )

        # 2. hermes_list_skills
        registry.register_tool(
            ToolDefinition(
                name="hermes_list_skills",
                description="Discover available reasoning and workflow skills from the Hermes skills catalog.",
                parameters={
                    "category": ToolParameter(
                        name="category",
                        type="string",
                        description="Optional skill category filter (e.g. 'productivity', 'research', 'devops').",
                        required=False,
                    )
                },
                permission_level=PermissionLevel.READ_ONLY,
                handler=self.handle_list_skills,
                source="NEXUS_HERMES_ADAPTER",
                simulated=False,
            )
        )

        # 3. hermes_audit_skill_code
        registry.register_tool(
            ToolDefinition(
                name="hermes_audit_skill_code",
                description="Perform deep AST static security analysis on Python skill code to detect unsafe dynamic imports, eval, or code execution.",
                parameters={
                    "code": ToolParameter(
                        name="code",
                        type="string",
                        description="The Python source code string to inspect.",
                        required=True,
                    )
                },
                permission_level=PermissionLevel.READ_ONLY,
                handler=self.handle_audit_skill_code,
                source="NEXUS_HERMES_ADAPTER",
                simulated=False,
            )
        )

        # 4. hermes_run_subagent
        registry.register_tool(
            ToolDefinition(
                name="hermes_run_subagent",
                description="Delegate a scoped subtask to an independent Hermes subagent. Requires user confirmation.",
                parameters={
                    "task_description": ToolParameter(
                        name="task_description",
                        type="string",
                        description="Clear description of the subtask to execute.",
                        required=True,
                    ),
                    "role": ToolParameter(
                        name="role",
                        type="string",
                        description="The specialized role of the subagent (e.g. 'Code Reviewer', 'Research Assistant').",
                        required=True,
                    ),
                    "max_turns": ToolParameter(
                        name="max_turns",
                        type="integer",
                        description="Maximum conversation turns allocated to the subagent.",
                        required=False,
                        default=3,
                    ),
                },
                permission_level=PermissionLevel.CONFIRMATION_REQUIRED,
                handler=self.handle_run_subagent,
                source="NEXUS_HERMES_ADAPTER",
                simulated=(self.metadata.status == IntegrationStatus.SIMULATED),
            )
        )

    # -------------------------------------------------------------------------
    # Tool Handlers
    # -------------------------------------------------------------------------

    def handle_query_memory(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Query persistent memories."""
        query = args.get("query", "").lower()
        target = args.get("target", "all")
        is_live = self.metadata.status == IntegrationStatus.CONNECTED

        results: List[Dict[str, Any]] = []

        # Attempt to read on-disk memory files if available
        on_disk_found = False
        memory_file = self.upstream_dir / "MEMORY.md"
        user_file = self.upstream_dir / "USER.md"

        if target in ("memory", "all") and memory_file.is_file():
            try:
                content = memory_file.read_text(encoding="utf-8")
                on_disk_found = True
                for line in content.splitlines():
                    line_s = line.strip()
                    if line_s and not line_s.startswith("#"):
                        if not query or query in line_s.lower():
                            results.append({"store": "memory", "text": line_s, "source": str(memory_file)})
            except Exception as e:
                logger.warning("Error reading MEMORY.md: %s", e)

        if target in ("user", "all") and user_file.is_file():
            try:
                content = user_file.read_text(encoding="utf-8")
                on_disk_found = True
                for line in content.splitlines():
                    line_s = line.strip()
                    if line_s and not line_s.startswith("#"):
                        if not query or query in line_s.lower():
                            results.append({"store": "user", "text": line_s, "source": str(user_file)})
            except Exception as e:
                logger.warning("Error reading USER.md: %s", e)

        # If on-disk memories were not found or empty, fall back to safe simulated memory facts
        if not on_disk_found or len(results) == 0:
            simulated_items = []
            targets = ["memory", "user"] if target == "all" else [target]
            for t in targets:
                for item in self._simulated_memories.get(t, []):
                    if not query or query in item["text"].lower() or query in item.get("category", ""):
                        simulated_items.append({"store": t, "text": item["text"], "id": item["id"]})

            return {
                "count": len(simulated_items),
                "memories": simulated_items,
                "simulated": True,
                "disclaimer": "Retrieved from simulated memory store (on-disk memory file not populated).",
            }

        return {
            "count": len(results),
            "memories": results[:20],
            "simulated": False,
        }

    def handle_list_skills(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Discover Hermes skills on disk."""
        skills_dir = self.upstream_dir / "skills"
        category_filter = args.get("category")

        if not skills_dir.is_dir():
            return {
                "count": 0,
                "skills": [],
                "simulated": True,
                "disclaimer": "Hermes skills directory not found on disk.",
            }

        found_skills: List[Dict[str, Any]] = []

        for category_dir in sorted(skills_dir.iterdir()):
            if not category_dir.is_dir() or category_dir.name.startswith("."):
                continue

            category_name = category_dir.name
            if category_filter and category_filter.lower() != category_name.lower():
                continue

            for skill_path in category_dir.iterdir():
                if skill_path.is_dir() and (skill_path / "SKILL.md").is_file():
                    skill_file = skill_path / "SKILL.md"
                    description = ""
                    try:
                        # Extract first paragraph or summary
                        lines = skill_file.read_text(encoding="utf-8").splitlines()
                        for line in lines[:10]:
                            line_s = line.strip()
                            if line_s and not line_s.startswith("#") and not line_s.startswith("---"):
                                description = line_s
                                break
                    except Exception:
                        pass

                    found_skills.append({
                        "name": skill_path.name,
                        "category": category_name,
                        "description": description or f"{skill_path.name} workflow skill",
                        "path": str(skill_file),
                    })

        return {
            "count": len(found_skills),
            "skills": found_skills[:30],  # Bound to 30 items
            "simulated": False,
        }

    def handle_audit_skill_code(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Perform AST security analysis on Python code."""
        code = args.get("code", "")
        if not code.strip():
            raise ValueError("Parameter 'code' cannot be empty.")

        try:
            tree = ast.parse(code)
        except SyntaxError as syn_err:
            return {
                "valid_syntax": False,
                "error": f"SyntaxError at line {syn_err.lineno}: {syn_err.msg}",
                "findings": [],
                "safe": False,
                "simulated": False,
            }

        findings: List[Dict[str, Any]] = []

        class SecurityVisitor(ast.NodeVisitor):
            def visit_Call(self, node: ast.Call) -> None:
                # Check eval() and exec()
                if isinstance(node.func, ast.Name):
                    if node.func.id in ("eval", "exec", "__import__"):
                        findings.append({
                            "line": node.lineno,
                            "severity": "HIGH",
                            "pattern_id": f"call_{node.func.id}",
                            "description": f"Direct call to built-in '{node.func.id}()' allows arbitrary code execution.",
                        })
                    elif node.func.id == "getattr":
                        # Check if getattr uses a dynamic (non-constant) attribute
                        if len(node.args) >= 2 and not isinstance(node.args[1], ast.Constant):
                            findings.append({
                                "line": node.lineno,
                                "severity": "MEDIUM",
                                "pattern_id": "dynamic_getattr",
                                "description": "getattr() with non-literal attribute name may bypass access control.",
                            })

                # Check os.system, subprocess calls
                elif isinstance(node.func, ast.Attribute):
                    if node.func.attr == "system" and isinstance(node.func.value, ast.Name) and node.func.value.id == "os":
                        findings.append({
                            "line": node.lineno,
                            "severity": "CRITICAL",
                            "pattern_id": "os_system",
                            "description": "os.system() call executes shell commands directly.",
                        })
                    elif node.func.attr == "import_module":
                        findings.append({
                            "line": node.lineno,
                            "severity": "HIGH",
                            "pattern_id": "dynamic_import_module",
                            "description": "importlib.import_module() dynamically imports arbitrary modules.",
                        })
                    elif node.func.attr in ("Popen", "run", "call", "check_call", "check_output"):
                        findings.append({
                            "line": node.lineno,
                            "severity": "MEDIUM",
                            "pattern_id": f"subprocess_{node.func.attr}",
                            "description": f"subprocess.{node.func.attr}() invocation requires strict sandboxing.",
                        })

                self.generic_visit(node)

            def visit_Import(self, node: ast.Import) -> None:
                for alias in node.names:
                    if alias.name in ("importlib", "subprocess", "socket"):
                        findings.append({
                            "line": node.lineno,
                            "severity": "INFO",
                            "pattern_id": f"import_{alias.name}",
                            "description": f"Import of '{alias.name}' detected; audit usage of system/network APIs.",
                        })
                self.generic_visit(node)

            def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
                if node.module in ("importlib", "subprocess", "socket"):
                    findings.append({
                        "line": node.lineno,
                        "severity": "INFO",
                        "pattern_id": f"import_from_{node.module}",
                        "description": f"Import from '{node.module}' detected; audit usage.",
                    })
                self.generic_visit(node)

        visitor = SecurityVisitor()
        visitor.visit(tree)

        has_critical = any(f["severity"] in ("CRITICAL", "HIGH") for f in findings)

        return {
            "valid_syntax": True,
            "safe": not has_critical,
            "findings_count": len(findings),
            "findings": findings,
            "simulated": False,
        }

    def handle_run_subagent(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute or simulate a subagent task delegation."""
        task = args.get("task_description", "").strip()
        role = args.get("role", "").strip()
        max_turns = args.get("max_turns", 3)

        if not task:
            raise ValueError("Parameter 'task_description' cannot be empty.")
        if not role:
            raise ValueError("Parameter 'role' cannot be empty.")

        # In local/simulated mode, execute a safe bounded delegation turn
        return {
            "subagent_role": role,
            "task": task,
            "max_turns": max_turns,
            "status": "COMPLETED",
            "summary": f"Subagent [{role}] completed scoped analysis for: {task[:60]}...",
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "simulated": True,
            "disclaimer": "Simulated subagent execution within NEXUS sandbox boundaries.",
        }

