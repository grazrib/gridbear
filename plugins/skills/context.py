"""Context provider for Skills plugin."""


async def get_context(user_id: int, platform: str, plugin_manager) -> str:
    """Provide skills context to GridBear."""
    skills_service = plugin_manager.get_service("skills")
    if not skills_service:
        return ""

    skills = await skills_service.list_skills(user_id=user_id, include_shared=True)
    if not skills:
        return ""

    # Group by category
    by_category = {}
    for skill in skills:
        cat = skill.get("category", "other")
        if cat not in by_category:
            by_category[cat] = []
        by_category[cat].append(skill)

    lines = ["[Available Skills]"]
    for category, cat_skills in sorted(by_category.items()):
        lines.append(f"\n{category.title()}:")
        for skill in cat_skills:
            desc = f" - {skill['description']}" if skill.get("description") else ""
            lines.append(f"  - {skill['name']}: {skill['title']}{desc}")

    lines.append("\nUser can say 'use skill <name>' to execute a skill.")
    lines.append("Skills can also be used with memos for scheduled execution.")

    return "\n".join(lines)
