"""
Moderation workflow service layer.

Encapsulates business logic for:
- Bundle assignment with random moderation sample generation
- Moderation comparison engine
- Evaluation revision snapshots
- Unlock logic
- Notification creation
"""
import random
from math import ceil

from django.db import transaction
from django.utils import timezone

from apps.audit.models import AuditLog
from utils.audit_helper import log_action


def create_bundle_assignment(request, bundle, assessor, moderator):
    """
    Create a BundleAssignment, generate moderation samples (20% of sheets),
    assign assessor to all sheets, and notify the moderator.

    Returns the created BundleAssignment.
    """
    from .models import BundleAssignment, ModerationSample, Notification

    with transaction.atomic():
        assignment = BundleAssignment.objects.create(
            bundle=bundle,
            assessor=assessor,
            moderator=moderator,
        )

        # Assign assessor to all sheets in the bundle
        sheets = list(bundle.answer_sheets.all())
        for sheet in sheets:
            sheet.assigned_teacher = assessor
            sheet.status = 'assigned'
        from apps.scanning.models import AnswerSheet
        AnswerSheet.objects.bulk_update(sheets, ['assigned_teacher', 'status'])

        # Select random moderation sample (20%, min 1)
        total_sheets = len(sheets)
        sample_size = max(1, ceil(total_sheets * 0.20))
        sampled_sheets = random.sample(sheets, min(sample_size, total_sheets))

        samples = []
        for sheet in sampled_sheets:
            samples.append(ModerationSample(
                bundle_assignment=assignment,
                answer_sheet=sheet,
            ))
        ModerationSample.objects.bulk_create(samples)

        # Create notification for moderator
        Notification.objects.create(
            recipient=moderator,
            event_type='MODERATOR_EVAL_PENDING',
            message=f'You have been assigned as moderator for Bundle #{bundle.bundle_number}. '
                    f'{len(sampled_sheets)} papers require your evaluation.',
            bundle=bundle,
        )

        # Audit logs
        log_action(
            request, 'BUNDLE_ASSIGNED', 'BundleAssignment', assignment.pk,
            new_value={
                'assessor': str(assessor.id),
                'moderator': str(moderator.id),
                'bundle': bundle.pk,
            },
            notes=f'Bundle #{bundle.bundle_number} assigned. '
                  f'Assessor: {assessor.full_name}, Moderator: {moderator.full_name}.',
        )
        log_action(
            request, 'MOD_SAMPLE_GEN', 'BundleAssignment', assignment.pk,
            new_value={
                'sample_size': len(sampled_sheets),
                'sheet_ids': [s.id for s in sampled_sheets],
            },
            notes=f'{len(sampled_sheets)} moderation samples generated for bundle #{bundle.bundle_number}.',
        )

    return assignment


def check_moderator_completion(bundle_assignment):
    """
    Check whether the moderator has evaluated ALL moderation sample papers.
    Returns (is_complete: bool, missing_count: int).
    """
    from .models import EvaluationResult

    sample_sheet_ids = list(
        bundle_assignment.samples.values_list('answer_sheet_id', flat=True)
    )

    moderator_evals = EvaluationResult.objects.filter(
        answer_sheet_id__in=sample_sheet_ids,
        role='moderator',
        teacher=bundle_assignment.moderator,
    ).values_list('answer_sheet_id', flat=True)

    evaluated_ids = set(moderator_evals)
    missing = [sid for sid in sample_sheet_ids if sid not in evaluated_ids]

    return len(missing) == 0, len(missing)


def run_moderation_comparison(request, bundle_assignment):
    """
    Compare assessor vs moderator totals for each moderation sample paper.

    Returns a dict with:
    - bundle_status: 'PASSED' or 'FAILED'
    - papers: list of per-paper comparison results
    """
    from .models import (
        EvaluationResult, ModerationPaperStatus, Notification,
    )

    now = timezone.now()
    bundle_assignment.moderation_requested_at = now
    bundle_assignment.save(update_fields=['moderation_requested_at'])

    samples = bundle_assignment.samples.select_related('answer_sheet').all()
    results = []
    all_passed = True

    with transaction.atomic():
        for sample in samples:
            sheet = sample.answer_sheet

            # Get assessor and moderator evaluations
            try:
                assessor_eval = EvaluationResult.objects.get(
                    answer_sheet=sheet,
                    role='assessor',
                )
            except EvaluationResult.DoesNotExist:
                assessor_eval = None

            try:
                moderator_eval = EvaluationResult.objects.get(
                    answer_sheet=sheet,
                    role='moderator',
                )
            except EvaluationResult.DoesNotExist:
                moderator_eval = None

            if not assessor_eval or not moderator_eval:
                # Should not happen if pre-checks passed, but handle gracefully
                continue

            # Lock moderator evaluation after comparison
            if not moderator_eval.comparison_locked:
                moderator_eval.comparison_locked = True
                moderator_eval.save(update_fields=['comparison_locked'])

            # Compute tolerance
            moderator_total = moderator_eval.total_marks
            assessor_total = assessor_eval.total_marks
            allowed_difference = max(round(moderator_total * 0.10), 1)

            passed = abs(assessor_total - moderator_total) <= allowed_difference
            status = 'PASSED' if passed else 'FAILED'

            if not passed:
                all_passed = False

            # Build question-wise comparison
            question_comparison = _build_question_comparison(
                assessor_eval.section_results,
                moderator_eval.section_results,
            )

            # Create or update paper status
            paper_status, _ = ModerationPaperStatus.objects.update_or_create(
                sample=sample,
                defaults={
                    'status': status,
                    'assessor_total': assessor_total,
                    'moderator_total': moderator_total,
                    'allowed_difference': allowed_difference,
                    'question_comparison': question_comparison,
                    'compared_at': now,
                },
            )

            # Audit log per paper
            action_type = 'MOD_COMP_PASSED' if passed else 'MOD_COMP_FAILED'
            log_action(
                request, action_type, 'ModerationPaperStatus', paper_status.pk,
                new_value={
                    'sheet_id': sheet.id,
                    'assessor_total': assessor_total,
                    'moderator_total': moderator_total,
                    'allowed_difference': allowed_difference,
                    'status': status,
                },
                notes=f'Paper #{sheet.id}: assessor={assessor_total}, '
                      f'moderator={moderator_total}, tolerance=±{allowed_difference}. '
                      f'Result: {status}.',
            )

            results.append({
                'paper_id': sheet.id,
                'token': sheet.token,
                'status': status,
                'assessor_total': assessor_total,
                'moderator_total': moderator_total,
                'allowed_difference': allowed_difference,
                'question_comparison': question_comparison,
            })

        # Update bundle assignment status
        bundle_status = 'PASSED' if all_passed else 'FAILED'
        bundle_assignment.moderation_completed = True
        bundle_assignment.moderation_passed = all_passed
        bundle_assignment.moderation_completed_at = now if all_passed else None
        bundle_assignment.save(update_fields=[
            'moderation_completed', 'moderation_passed', 'moderation_completed_at',
        ])

        # If all passed, unlock remaining papers
        if all_passed:
            unlock_remaining_papers(request, bundle_assignment)

        # Notifications
        if not all_passed:
            failed_count = sum(1 for r in results if r['status'] == 'FAILED')
            Notification.objects.create(
                recipient=bundle_assignment.assessor,
                event_type='MODERATION_FAILED',
                message=f'{failed_count} moderation paper(s) in Bundle '
                        f'#{bundle_assignment.bundle.bundle_number} require correction.',
                bundle=bundle_assignment.bundle,
            )
        else:
            Notification.objects.create(
                recipient=bundle_assignment.assessor,
                event_type='MODERATION_PASSED',
                message=f'All moderation papers in Bundle '
                        f'#{bundle_assignment.bundle.bundle_number} passed! '
                        f'Remaining papers are now unlocked.',
                bundle=bundle_assignment.bundle,
            )

    return {
        'bundle_status': bundle_status,
        'papers': results,
    }


def unlock_remaining_papers(request, bundle_assignment):
    """
    When all moderation papers pass, unlock remaining papers.
    Moderation papers are already accessible; this unlocks the rest.
    """
    from .models import Notification

    bundle = bundle_assignment.bundle
    sample_sheet_ids = set(
        bundle_assignment.samples.values_list('answer_sheet_id', flat=True)
    )

    # All sheets already have assigned_teacher = assessor from assignment
    # They are already 'assigned' status. No additional unlock needed
    # because the frontend uses moderation status to determine accessibility.

    log_action(
        request, 'MOD_UNLOCKED', 'BundleAssignment', bundle_assignment.pk,
        new_value={'bundle_id': bundle.pk},
        notes=f'Remaining papers unlocked for bundle #{bundle.bundle_number}.',
    )

    Notification.objects.create(
        recipient=bundle_assignment.assessor,
        event_type='PAPERS_UNLOCKED',
        message=f'All papers in Bundle #{bundle.bundle_number} are now available for evaluation.',
        bundle=bundle,
    )


def create_evaluation_revision(evaluation, changed_by, reason='Moderation correction'):
    """
    Snapshot the current evaluation state before an edit.
    """
    from .models import EvaluationRevision

    return EvaluationRevision.objects.create(
        evaluation=evaluation,
        previous_section_results=evaluation.section_results,
        previous_total=evaluation.total_marks,
        changed_by=changed_by,
        reason=reason,
    )


def _build_question_comparison(assessor_sections, moderator_sections):
    """
    Build a question-wise comparison table from section_results.
    Returns list of {question, assessor, moderator} dicts.
    """
    comparison = []

    assessor_map = _flatten_section_marks(assessor_sections)
    moderator_map = _flatten_section_marks(moderator_sections)

    all_questions = set(assessor_map.keys()) | set(moderator_map.keys())
    for q in sorted(all_questions):
        comparison.append({
            'question': q,
            'assessor': assessor_map.get(q, 0),
            'moderator': moderator_map.get(q, 0),
        })

    return comparison


def _flatten_section_marks(section_results):
    """
    Flatten section_results to {question_label: marks_obtained} dict.
    """
    marks = {}
    if not section_results:
        return marks

    for q in section_results:
        q_name = q.get('name', '?')
        for sq in q.get('sub_questions', []):
            sq_name = sq.get('name', '?')
            for p in sq.get('parts', []):
                p_name = p.get('name', '?')
                label = f"{q_name}.{sq_name}.{p_name}"
                obtained = p.get('marks_obtained')
                marks[label] = obtained if obtained is not None else 0

    return marks
