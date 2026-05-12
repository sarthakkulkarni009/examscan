from django.conf import settings
from django.db import models


from django.core.serializers.json import DjangoJSONEncoder

class AuditLog(models.Model):
    """
    Immutable audit trail for all significant actions in the system.
    """
    ACTION_CHOICES = [
        ('LOGIN', 'Login'),
        ('SCAN', 'Scan'),
        ('SUBMIT_SESSION', 'Submit Session'),
        ('ASSIGN', 'Assign'),
        ('GRADE', 'Grade'),
        ('EDIT_MARKS', 'Edit Marks'),
        ('FLAG', 'Flag'),
        ('AMENDMENT_REQUEST', 'Amendment Request'),
        ('AMENDMENT_COMPLETE', 'Amendment Complete'),
        ('AMEND_MARKS', 'Amend Marks'),
        ('RESULT_GENERATED', 'Result Generated'),
        # Moderation workflow events
        ('BUNDLE_ASSIGNED', 'Bundle Assigned'),
        ('MOD_SAMPLE_GEN', 'Moderation Sample Generated'),
        ('MOD_REQUESTED', 'Moderation Requested'),
        ('MOD_COMP_PASSED', 'Moderation Comparison Passed'),
        ('MOD_COMP_FAILED', 'Moderation Comparison Failed'),
        ('MOD_CORRECTION', 'Moderation Correction'),
        ('MOD_UNLOCKED', 'Moderation Unlocked'),
    ]

    action_type = models.CharField(max_length=30, choices=ACTION_CHOICES)
    performed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='audit_logs'
    )
    performed_at = models.DateTimeField(auto_now_add=True)
    target_model = models.CharField(max_length=100)
    target_id = models.CharField(max_length=100)
    old_value = models.JSONField(null=True, blank=True, encoder=DjangoJSONEncoder)
    new_value = models.JSONField(null=True, blank=True, encoder=DjangoJSONEncoder)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        db_table = 'audit_logs'
        ordering = ['-performed_at']

    def __str__(self):
        return f"[{self.action_type}] by {self.performed_by} at {self.performed_at}"
