from math import ceil
from rest_framework import serializers
from .models import (
    EvaluationResult, BundleAssignment, ModerationSample,
    ModerationPaperStatus, EvaluationRevision, Notification,
)


class EvaluationResultSerializer(serializers.ModelSerializer):
    """
    Serializer for EvaluationResult.
    Validates marks_obtained: 0 ≤ value ≤ max_marks for every question part.
    """
    teacher_name = serializers.CharField(source='teacher.full_name', read_only=True)
    answer_sheet_id = serializers.IntegerField(source='answer_sheet.id', read_only=True)
    answer_sheet_status = serializers.CharField(source='answer_sheet.status', read_only=True)

    class Meta:
        model = EvaluationResult
        fields = [
            'id', 'answer_sheet', 'answer_sheet_id', 'answer_sheet_status',
            'teacher', 'teacher_name',
            'role', 'is_final', 'comparison_locked',
            'section_results', 'total_marks', 'submitted_at', 'graded_at',
            'last_edited_at', 'pdf_version_at_grading',
            'was_amended', 'amended_at',
            # Badge fields
            'mark_positions', 'marked_pdf_path',
        ]
        read_only_fields = [
            'id', 'submitted_at', 'graded_at', 'last_edited_at',
            'teacher', 'total_marks', 'was_amended', 'amended_at',
            'marked_pdf_path', 'answer_sheet_status',
            'is_final', 'comparison_locked',
        ]

    def validate_section_results(self, value):
        """Validate marks_obtained for every part using the Q -> SQ -> Part schema."""
        if not isinstance(value, list) or len(value) == 0:
            raise serializers.ValidationError('section_results must be a non-empty list.')

        errors = {}
        computed_total = 0

        for q in value:
            q_name = q.get('name', 'Unknown')
            if 'sub_questions' not in q or not isinstance(q['sub_questions'], list):
                raise serializers.ValidationError(f'Question "{q_name}" must have a "sub_questions" list.')

            sq_totals = []
            for sq in q['sub_questions']:
                sq_name = sq.get('name', 'Unknown')
                if 'parts' not in sq or not isinstance(sq['parts'], list):
                    raise serializers.ValidationError(f'Sub-question "{q_name}{sq_name}" must have a "parts" list.')

                part_totals = []
                for p in sq['parts']:
                    p_name = p.get('name', '?')
                    max_marks = p.get('max_marks', 0)
                    marks_obtained = p.get('marks_obtained')

                    if marks_obtained is None:
                        # null = unattempted — valid, counts as 0 in total
                        part_totals.append(0)
                        continue

                    if not isinstance(marks_obtained, (int, float)):
                        errors[f'{q_name}{sq_name}.{p_name}'] = ['marks_obtained must be a number.']
                        continue

                    if marks_obtained < 0 or marks_obtained > max_marks:
                        errors[f'{q_name}{sq_name}.{p_name}'] = [f'must be between 0 and {max_marks}.']
                        continue

                    part_totals.append(marks_obtained)

                # Apply sub-question attempt rule
                sq_rule = sq.get('rule', 'all')
                sq_rule_count = sq.get('rule_count')
                if sq_rule == 'any' and isinstance(sq_rule_count, int) and sq_rule_count > 0:
                    part_totals.sort(reverse=True)
                    sq_total = sum(part_totals[:sq_rule_count])
                else:
                    sq_total = sum(part_totals)

                sq['obtained_total'] = sq_total
                sq_totals.append(sq_total)

            # Apply question attempt rule
            q_rule = q.get('rule', 'all')
            q_rule_count = q.get('rule_count')
            if q_rule == 'any' and isinstance(q_rule_count, int) and q_rule_count > 0:
                sq_totals.sort(reverse=True)
                q_total = sum(sq_totals[:q_rule_count])
            else:
                q_total = sum(sq_totals)

            q['obtained_total'] = q_total
            computed_total += q_total

        if errors:
            raise serializers.ValidationError(errors)

        self._computed_total = ceil(computed_total)
        return value

    def create(self, validated_data):
        validated_data['total_marks'] = getattr(self, '_computed_total', 0)
        return super().create(validated_data)

    def update(self, instance, validated_data):
        if hasattr(self, '_computed_total'):
            validated_data['total_marks'] = self._computed_total
        return super().update(instance, validated_data)


class ModerationSampleSerializer(serializers.ModelSerializer):
    token = serializers.CharField(source='answer_sheet.token', read_only=True)
    sheet_id = serializers.IntegerField(source='answer_sheet.id', read_only=True)

    class Meta:
        model = ModerationSample
        fields = ['id', 'sheet_id', 'token', 'selected_at']


class ModerationPaperStatusSerializer(serializers.ModelSerializer):
    paper_id = serializers.IntegerField(source='sample.answer_sheet_id', read_only=True)
    token = serializers.CharField(source='sample.answer_sheet.token', read_only=True)

    class Meta:
        model = ModerationPaperStatus
        fields = [
            'id', 'paper_id', 'token', 'status',
            'assessor_total', 'moderator_total', 'allowed_difference',
            'question_comparison', 'compared_at',
        ]


class BundleAssignmentSerializer(serializers.ModelSerializer):
    assessor_name = serializers.CharField(source='assessor.full_name', read_only=True)
    moderator_name = serializers.CharField(source='moderator.full_name', read_only=True)
    samples = ModerationSampleSerializer(many=True, read_only=True)
    sample_count = serializers.SerializerMethodField()

    class Meta:
        model = BundleAssignment
        fields = [
            'id', 'bundle', 'assessor', 'assessor_name',
            'moderator', 'moderator_name',
            'moderation_completed', 'moderation_passed',
            'moderation_requested_at', 'moderation_completed_at',
            'created_at', 'samples', 'sample_count',
        ]
        read_only_fields = [
            'id', 'created_at', 'moderation_completed', 'moderation_passed',
            'moderation_requested_at', 'moderation_completed_at',
        ]

    def get_sample_count(self, obj):
        return obj.samples.count()


class BundleAssignmentSummarySerializer(serializers.ModelSerializer):
    """Lightweight serializer for embedding in bundle lists — no nested samples."""
    assessor_name = serializers.CharField(source='assessor.full_name', read_only=True)
    moderator_name = serializers.CharField(source='moderator.full_name', read_only=True)

    class Meta:
        model = BundleAssignment
        fields = [
            'id', 'assessor', 'assessor_name',
            'moderator', 'moderator_name',
            'moderation_completed', 'moderation_passed',
            'moderation_requested_at', 'moderation_completed_at',
            'created_at',
        ]


class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notification
        fields = [
            'id', 'event_type', 'message', 'bundle',
            'is_read', 'created_at',
        ]
        read_only_fields = ['id', 'event_type', 'message', 'bundle', 'created_at']


class EvaluationRevisionSerializer(serializers.ModelSerializer):
    changed_by_name = serializers.CharField(source='changed_by.full_name', read_only=True)

    class Meta:
        model = EvaluationRevision
        fields = [
            'id', 'evaluation', 'previous_section_results', 'previous_total',
            'changed_by', 'changed_by_name', 'changed_at', 'reason',
        ]
