import uuid

from django.db import models

from basics.models import BaseModel

# Create your models here.
AGENT_CHOICES = [
    ('support', 'Support Agent'),
    ('complaints', 'Complaints Agent'),
]


class Conversation(BaseModel):
    session_id=models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    user=models.ForeignKey('auth_app.User', on_delete=models.CASCADE, related_name='conversations')
    title=models.CharField(max_length=255)
    company=models.ForeignKey('company.Company', on_delete=models.CASCADE, related_name='conversations')
    summary=models.TextField(blank=True, default='')
    agent_type=models.CharField(max_length=20, choices=AGENT_CHOICES, default='support')
    auto_route=models.BooleanField(default=False, help_text="Re-pick the agent on every message (set for conversations started as Auto).")
    class Meta:
        ordering=['-id']


class Message(BaseModel):
    ROLE_CHOICES = [
        ('user', 'User'),
        ('assistant', 'Assistant'),
    ]
    conversation=models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name='messages')
    content=models.TextField(blank=True)
    role=models.CharField(max_length=20, choices=ROLE_CHOICES, default='user')
    file=models.FileField(upload_to='chat_uploads/', blank=True, null=True)
    document=models.ForeignKey('rag.Document', on_delete=models.SET_NULL, related_name='chat_messages', null=True, blank=True)
    session_id=models.UUIDField(null=True, blank=True)
    user=models.ForeignKey('auth_app.User', on_delete=models.CASCADE, related_name='messages', null=True, blank=True)
    company=models.ForeignKey('company.Company', on_delete=models.CASCADE, related_name='messages', null=True, blank=True)
    class Meta:
            ordering=['-id']

HTTP_METHOD_CHOICES = [
    ('GET', 'GET'),
    ('POST', 'POST'),
]


class Agent(BaseModel):
    company=models.ForeignKey('company.Company', on_delete=models.CASCADE, related_name='agents')
    agent_type=models.SlugField(max_length=50, unique=True, help_text="Used as the value stored on Conversation.agent_type.")
    label=models.CharField(max_length=100)
    description=models.CharField(max_length=255, blank=True)
    prompt=models.TextField(help_text="System prompt for this agent.")
    linked_agents=models.ManyToManyField(
        'self', symmetrical=False, related_name='parent_agents', blank=True,
        help_text="Agents this agent can delegate to, exposed to it as tools.",
    )
    workflow_json=models.JSONField(
        default=dict,
        blank=True,
        help_text='Canvas snapshot in React Flow shape: {"nodes": [...], "edges": [...]}.',
    )

    def __str__(self):
        return self.label

    def delegation_cycle(self, child_ids):
        """True if linking this agent to child_ids would make it reachable from itself."""
        child_ids = set(child_ids)
        if self.pk in child_ids:
            return True
        seen = set()
        frontier = child_ids
        while frontier:
            if self.pk in frontier:
                return True
            seen |= frontier
            frontier = set(
                Agent.linked_agents.through.objects.filter(from_agent_id__in=frontier)
                .values_list('to_agent_id', flat=True)
            ) - seen
        return False


ORDER_STATUS_CHOICES = [
    ('processing', 'Processing'),
    ('shipped', 'Shipped'),
    ('delivered', 'Delivered'),
    ('cancelled', 'Cancelled'),
]


class Order(BaseModel):
    company=models.ForeignKey('company.Company', on_delete=models.CASCADE, related_name='orders')
    order_number=models.CharField(max_length=50, unique=True)
    customer_name=models.CharField(max_length=255, blank=True)
    status=models.CharField(max_length=20, choices=ORDER_STATUS_CHOICES, default='processing')

    def __str__(self):
        return f"Order {self.order_number} ({self.status})"


class ToolDefinition(BaseModel):
    company=models.ForeignKey('company.Company', on_delete=models.CASCADE, related_name='tools')
    agents=models.ManyToManyField(Agent, related_name='tools', blank=True)
    name=models.SlugField(max_length=50, help_text="Tool name shown to the LLM, e.g. get_order_status.")
    description=models.TextField(help_text="Shown to the LLM so it knows when to call this tool.")
    args_schema=models.JSONField(
        default=list,
        blank=True,
        help_text='List of {"name": "...", "description": "...", "required": true}',
    )
    endpoint_url=models.URLField(help_text="Called with the LLM-supplied arguments when this tool is invoked.")
    http_method=models.CharField(max_length=10, choices=HTTP_METHOD_CHOICES, default='POST')
    workflow_json=models.JSONField(
        default=dict,
        blank=True,
        help_text='Canvas snapshot in React Flow shape: {"nodes": [...], "edges": [...]}.',
    )

    class Meta:
        unique_together = ('company', 'name')

    def __str__(self):
        return self.name
