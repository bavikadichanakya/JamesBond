"""Response Manager for NEXUS Intelligent Routing.

Consolidates multi-step and single-step execution results into clean, unified natural
language responses with explicit simulation badges and provenance tracking.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from nexus.routing.models import RoutingExecutionOutcome, RoutingPlan
from nexus.tools.result import StandardizedToolResult


class ResponseManager:
    """Consolidates tool execution results into understandable, unified responses.
    
    Guarantees:
    - Never conceals simulated vs real-world data status.
    - Explicitly surfaces permission denials or execution failures.
    - Unifies multi-integration results into a single cohesive narrative.
    """

    @staticmethod
    def format_single_result(tool_name: str, result: StandardizedToolResult) -> str:
        """Format a single tool execution result into user-facing natural language."""
        if not result.success:
            err = result.error.message if result.error else "Unknown execution error"
            return f"I encountered an issue executing this action: {err}"

        data = result.data or {}

        # 1. Muse Device Discovery
        if tool_name == "muse_discover_devices":
            devices = data.get("devices", [])
            if not devices:
                return "I scanned your local network, but no smart devices were found."
            lines = [f"I discovered {len(devices)} smart devices:"]
            for d in devices:
                lines.append(f"• **{d.get('name')}** ({d.get('category')}) — Status: {d.get('state')}")
            return "\n".join(lines)

        # 2. Muse Gadget Action
        elif tool_name == "muse_invoke_gadget_action":
            dev_id = data.get("device_id")
            action = data.get("action")
            updated = data.get("updated_state", {})
            return f"Successfully executed **{action}** on device `{dev_id}`. Updated state: {updated}."

        # 3. OpenClaw Gateway Status
        elif tool_name == "openclaw_gateway_status":
            status = data.get("gateway_status")
            channels = data.get("active_channels", 0)
            return f"OpenClaw Gateway status is **{status}** with {channels} configured channels."

        # 4. OpenClaw Send Message
        elif tool_name == "openclaw_send_channel_message":
            channel = data.get("channel_id")
            deliv = data.get("delivery_status")
            return f"Message to channel `{channel}` has been processed with status: **{deliv}**."

        # 5. OpenClaw Extensions
        elif tool_name == "openclaw_list_extensions":
            exts = data.get("extensions", [])
            count = data.get("count", len(exts))
            lines = [f"Discovered {count} OpenClaw extensions:"]
            for e in exts[:10]:
                lines.append(f"• **{e.get('name')}**: {e.get('description') or 'Extension plugin'}")
            return "\n".join(lines)

        # 6. Hermes Query Memory
        elif tool_name == "hermes_query_memory":
            mems = data.get("memories", [])
            if not mems:
                return "I queried the persistent memory store, but found no matching records."
            lines = ["Here is what I found in persistent memory:"]
            for m in mems:
                lines.append(f"• [{m.get('store', 'memory')}] {m.get('text')}")
            return "\n".join(lines)

        # 7. Hermes List Skills
        elif tool_name == "hermes_list_skills":
            skills = data.get("skills", [])
            lines = [f"Found {len(skills)} Hermes workflow skills:"]
            for s in skills[:10]:
                lines.append(f"• **{s.get('name')}** ({s.get('category')}): {s.get('description')}")
            return "\n".join(lines)

        # 8. Hermes Audit Code
        elif tool_name == "hermes_audit_skill_code":
            safe = data.get("safe", False)
            findings = data.get("findings", [])
            if safe:
                return "Security audit completed: No critical or high-risk patterns detected. Code appears safe."
            lines = [f"Security audit warning: Found {len(findings)} potential security findings:"]
            for f in findings:
                lines.append(f"• Line {f.get('line')}: [{f.get('severity')}] {f.get('description')}")
            return "\n".join(lines)

        # 9. Hermes Run Subagent
        elif tool_name == "hermes_run_subagent":
            role = data.get("subagent_role")
            summary = data.get("summary")
            return f"Subagent [{role}] has completed the delegated task:\n{summary}"

        # 10. Local System Open Website
        elif tool_name == "open_website":
            url = data.get("url")
            code = data.get("dispatch_code")
            note = data.get("note", "Windows accepted the launch request. Actual page rendering occurs in the default browser.")
            return (
                f"Dispatched browser launch request for **{url}** to Windows Shell (code {code}).\n"
                f"*{note}*"
            )

        # 11. Local System Launch Application
        elif tool_name == "launch_application":
            app = data.get("app_name")
            pid = data.get("pid")
            return f"Launched desktop application **{app}** (Process ID: {pid})."

        # 12. Local System Current Time
        elif tool_name == "get_current_time":
            t_str = data.get("time")
            d_str = data.get("date")
            tz = data.get("timezone", "Local")
            return f"The current local time is **{t_str}** on **{d_str}** ({tz})."

        # 13. Local System Info
        elif tool_name == "get_system_info":
            os_ver = data.get("os", "Windows")
            proc = data.get("processor", "Unknown")
            cores = data.get("cpu_cores", 0)
            mem = data.get("memory", {})
            cpu_p = data.get("cpu_utilization_percent", 0)

            lines = [f"**System Information:**", f"• **OS:** {os_ver}", f"• **CPU:** {proc} ({cores} cores, {cpu_p}% load)"]
            if mem:
                lines.append(f"• **Memory:** {mem.get('available_gb')} GB available of {mem.get('total_gb')} GB ({mem.get('percent_used')}% used)")
            disk = data.get("disk", {})
            if disk:
                lines.append(f"• **Disk:** {disk.get('free_gb')} GB free of {disk.get('total_gb')} GB")
            return "\n".join(lines)

        # 14. Local System Open Folder
        elif tool_name == "open_approved_folder":
            f_name = data.get("folder_name")
            f_path = data.get("path")
            return f"Opened the **{f_name}** folder in Windows Explorer: `{f_path}`."

        # Default fallback
        return f"Action completed successfully: {data}"

    @classmethod
    def consolidate(
        cls,
        plan: RoutingPlan,
        results: List[Dict[str, Any]],
        has_simulated: bool = False,
    ) -> str:
        """Consolidate multiple execution results into a unified natural language narrative."""
        if not results:
            return "No operations were executed for this request."

        # If any step failed
        failures = [r for r in results if not r.get("result", {}).success]
        if failures:
            fail_desc = []
            for f in failures:
                res: StandardizedToolResult = f["result"]
                err = res.error.message if res.error else "Execution error"
                fail_desc.append(f"• `{f['step'].tool_name}`: {err}")
            return "I was unable to complete the request because of the following issues:\n" + "\n".join(fail_desc)

        # Multi-integration consolidation
        if len(results) > 1:
            sections = []
            # Sort or correlate by integration
            for r in results:
                step = r["step"]
                res: StandardizedToolResult = r["result"]
                formatted = cls.format_single_result(step.tool_name, res)
                sections.append(f"### {step.description}\n{formatted}")

            final_text = "\n\n".join(sections)
        else:
            final_text = cls.format_single_result(results[0]["step"].tool_name, results[0]["result"])

        # Add simulation notice if applicable
        if has_simulated:
            final_text += "\n\n*(Note: Results contain simulated data as physical hardware or external gateways are currently offline.)*"

        return final_text

