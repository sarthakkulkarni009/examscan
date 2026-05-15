from django.conf import settings
from django.db import models


class EvaluationResult(models.Model):
    """
    Stores the grading result for a single answer sheet.
    Supports multiple evaluations per sheet (assessor + moderator).

    section_results JSON schema:
    [
        {
            "name": "Q1",
            "sub_questions": [
                {"name": "1a", "parts": [{"name": "i", "max_marks": 5, "marks_obtained": 4}]}
            ]
        }
    ]
    """
    ROLE_CHOICES = [
        ('assessor', 'Assessor'),
        ('moderator', 'Moderator'),
    ]

    answer_sheet = models.ForeignKey(
        'scanning.AnswerSheet', on_delete=models.CASCADE, related_name='evaluations'
    )
    teacher = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='evaluations'
    )
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='assessor')
    is_final = models.BooleanField(default=False)
    comparison_locked = models.BooleanField(default=False)

    section_results = models.JSONField()
    total_marks = models.PositiveIntegerField()
    submitted_at = models.DateTimeField(auto_now_add=True)
    graded_at = models.DateTimeField(auto_now_add=True)
    last_edited_at = models.DateTimeField(auto_now=True)
    pdf_version_at_grading = models.PositiveIntegerField()
    was_amended = models.BooleanField(default=False)
    amended_at = models.DateTimeField(null=True, blank=True)

    # ── Mark badge positions ─────────────────────────────────────────────────
    mark_positions = models.JSONField(default=list)
    # List of badge dicts, e.g.:
    # [{"question_id": "Q1_1a_i", "value": 7, "page": 2,
    #   "x_percent": 42.5, "y_percent": 31.2}]
    # Positions stored as % of page dimensions → resolution-independent.

    marked_pdf_path = models.CharField(max_length=500, blank=True, null=True)
    # Path to annotated PDF relative to MEDIA_ROOT.
    # e.g. "answer_sheets/{bundle_id}/{token}_v2_marked.pdf"
    # The original AnswerSheet.pdf_file is NEVER modified.

    PDF_STATUS_CHOICES = [
        ('pending', 'Pending'),        # Marks saved, PDF generation not yet started
        ('processing', 'Processing'),  # Background worker is generating PDF
        ('completed', 'Completed'),    # Marked PDF ready on disk
        ('failed', 'Failed'),          # PDF generation failed
        ('skipped', 'Skipped'),        # No mark_positions → no PDF needed
    ]
    pdf_status = models.CharField(
        max_length=20, choices=PDF_STATUS_CHOICES, default='skipped',
        help_text='Background PDF generation status',
    )
    pdf_error = models.TextField(blank=True, default='',
        help_text='Error message if PDF generation failed',
    )
    # ── End mark badge fields ────────────────────────────────────────────────

    class Meta:
        db_table = 'evaluation_results'
        unique_together = ('answer_sheet', 'role')

    def __str__(self):
        return f"Evaluation ({self.role}) for Sheet #{self.answer_sheet_id} — {self.total_marks} marks"


class BundleAssignment(models.Model):
    """
    Assigns an assessor and moderator to a bundle for moderation workflow.
    One active assignment per bundle.
    """
    bundle = models.OneToOneField(
        'scanning.Bundle', on_delete=models.CASCADE, related_name='moderation_assignment'
    )
    assessor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='assessor_assignments'
    )
    moderator = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='moderator_assignments'
    )
    moderation_completed = models.BooleanField(default=False)
    moderation_passed = models.BooleanField(default=False)
    moderation_requested_at = models.DateTimeField(null=True, blank=True)
    moderation_completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'bundle_assignments'

    def clean(self):
        from django.core.exceptions import ValidationError
        if self.assessor_id == self.moderator_id:
            raise ValidationError('Assessor and moderator must be different teachers.')

    def __str__(self):
        return f"Assignment for Bundle #{self.bundle_id}"


class ModerationSample(models.Model):
    """
    A paper randomly selected for moderation.
    Generated during bundle assignment. Fixed forever — never regenerated.
    """
    bundle_assignment = models.ForeignKey(
        BundleAssignment, on_delete=models.CASCADE, related_name='samples'
    )
    answer_sheet = models.ForeignKey(
        'scanning.AnswerSheet', on_delete=models.CASCADE, related_name='moderation_samples'
    )
    selected_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'moderation_samples'
        unique_together = ('bundle_assignment', 'answer_sheet')

    def __str__(self):
        return f"Mod sample: Sheet #{self.answer_sheet_id} in Assignment #{self.bundle_assignment_id}"


class ModerationPaperStatus(models.Model):
    """
    Per-paper moderation comparison result.
    """
    PAPER_STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('PASSED', 'Passed'),
        ('FAILED', 'Failed'),
    ]

    sample = models.OneToOneField(
        ModerationSample, on_delete=models.CASCADE, related_name='comparison_status'
    )
    status = models.CharField(max_length=20, choices=PAPER_STATUS_CHOICES, default='PENDING')
    assessor_total = models.IntegerField(null=True, blank=True)
    moderator_total = models.IntegerField(null=True, blank=True)
    allowed_difference = models.IntegerField(null=True, blank=True)
    question_comparison = models.JSONField(default=list)
    compared_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'moderation_paper_statuses'

    def __str__(self):
        return f"Status {self.status} for sample #{self.sample_id}"


class EvaluationRevision(models.Model):
    """
    Stores a snapshot of evaluation data before a correction is made.
    Automatically created before assessor edits failed moderation papers.
    """
    evaluation = models.ForeignKey(
        EvaluationResult, on_delete=models.CASCADE, related_name='revisions'
    )
    previous_section_results = models.JSONField()
    previous_total = models.IntegerField()
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True
    )
    changed_at = models.DateTimeField(auto_now_add=True)
    reason = models.CharField(max_length=200, blank=True, default='')

    class Meta:
        db_table = 'evaluation_revisions'
        ordering = ['-changed_at']

    def __str__(self):
        return f"Revision for Eval #{self.evaluation_id} at {self.changed_at}"


class Notification(models.Model):
    """
    Lightweight notification model for moderation workflow events.
    """
    EVENT_TYPES = [
        ('MODERATOR_EVAL_PENDING', 'Moderator Evaluation Pending'),
        ('COMPARISON_REQUESTED', 'Comparison Requested'),
        ('MODERATION_INCOMPLETE', 'Moderation Incomplete'),
        ('MODERATION_PASSED', 'Moderation Passed'),
        ('MODERATION_FAILED', 'Moderation Failed'),
        ('PAPERS_UNLOCKED', 'Papers Unlocked'),
    ]

    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='notifications'
    )
    event_type = models.CharField(max_length=50, choices=EVENT_TYPES)
    message = models.TextField()
    bundle = models.ForeignKey(
        'scanning.Bundle', on_delete=models.CASCADE, null=True, blank=True
    )
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'notifications'
        ordering = ['-created_at']

    def __str__(self):
        return f"[{self.event_type}] → {self.recipient_id}"
