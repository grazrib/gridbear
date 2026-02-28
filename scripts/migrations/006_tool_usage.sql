-- UP: Composite index for tool usage queries (ORM handles table + single indexes)
CREATE INDEX IF NOT EXISTS idx_tool_usage_agent_tool
    ON public.tool_usage (agent_name, tool_name);

-- DOWN
-- DROP INDEX IF EXISTS public.idx_tool_usage_agent_tool;
