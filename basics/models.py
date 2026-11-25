from django.conf import settings
from django.db import models

class BaseModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name='%(class)s_created',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name='%(class)s_updated',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        abstract = True

