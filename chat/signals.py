from django.db.models.signals import m2m_changed, post_delete, post_save
from django.dispatch import receiver

from chat.models import Agent, ToolDefinition


@receiver([post_save, post_delete], sender=Agent)
@receiver([post_save, post_delete], sender=ToolDefinition)
@receiver(m2m_changed, sender=Agent.linked_agents.through)
@receiver(m2m_changed, sender=ToolDefinition.agents.through)
def clear_agent_graph_cache(sender, **kwargs):
    # Compiled graphs bake in their prompt, tools and linked sub-agents.
    from chat.service.langgraph_agents import clear_agent_graph_cache as clear
    clear()
