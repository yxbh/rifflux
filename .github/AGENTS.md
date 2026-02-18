# AGENTS for Rifflux

This repository uses custom agent assets from `.github/`.

## Workspace instructions
- Global behavior: `.github/copilot-instructions.md`
- Additional scoped instructions: `.github/instructions/*.instructions.md`

## Custom agents
- `.github/agents/python-mcp-expert.agent.md`
- `.github/agents/repo-architect.agent.md`
- `.github/agents/specification.agent.md`
- `.github/agents/implementation-plan.agent.md`
- `.github/agents/task-planner.agent.md`
- `.github/agents/task-researcher.agent.md`

## Skills
- `.github/skills/rifflux-design/SKILL.md`

## Usage guidance
- Use `task-researcher` for technology and tradeoff exploration.
- Use `repo-architect` to refine boundaries between indexing core and MCP adapter.
- Use `python-mcp-expert` for MCP tool contracts and transport implementation.
- Use the Rifflux skill for repeatable design/planning workflows.
