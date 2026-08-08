"""Skill activation tool — lets the LLM auto-activate skills by name.

When the model sees a skill directory in the system prompt (name +
description), it can invoke ``skill(name="python-expert")`` to load that
skill's full instructions into the conversation.  The tool returns the
skill content so the model can immediately follow it.

This mirrors cc-haha's ``SkillTool`` (src/tools/SkillTool/SkillTool.ts),
simplified to a single parameter and pure prompt injection (no fork
context, no argument substitution, no lifecycle hooks).
"""

from .base import Effect, Tool, ToolResult


class SkillTool(Tool):
    effects = frozenset({Effect.APP_STATE_WRITE})
    name = "skill"
    description = (
        "Activate a skill by name. The skill's full instructions will be "
        "loaded into the conversation for you to follow. Use this when "
        "the user's request matches a skill's domain (e.g. code review, "
        "Python development, React patterns)."
    )
    parameters = {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Name of the skill to activate (from the Skills list in the system prompt)",
            },
        },
        "required": ["name"],
    }

    # set by Agent.__init__ after construction
    _agent = None

    def execute(self, name: str) -> ToolResult:
        if self._agent is None:
            return ToolResult.error("skill tool not initialized", error_type="NotInitialized")

        from ..skills import find_skill_by_name, format_skill_invocation

        skill = find_skill_by_name(self._agent.skills, name)
        if skill is None:
            available = ", ".join(s.name for s in self._agent.skills) or "none"
            return ToolResult.error(
                f"Skill '{name}' not found. Available skills: {available}",
                error_type="SkillNotFound",
            )

        # Record activation so we know it's active this session
        self._agent.active_skills.add(skill.name)
        trace = getattr(self._agent, "trace", None)
        if trace is not None:
            trace.emit(
                "skill_activated",
                skill=skill.name,
                source=str(skill.source_path),
                activation="tool",
            )

        return ToolResult.success(format_skill_invocation(skill))
