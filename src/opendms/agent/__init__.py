"""Agent layer: planner, working memory, tool broker, guardrail interceptor.

The four components that distinguish an agent from an executor. Imported
lazily by the router so that a misconfigured LLM cannot prevent the rest of
OpenDMS from starting.
"""

from opendms.agent import guardrails, memory, planner, tools

__all__ = ["guardrails", "memory", "planner", "tools"]
