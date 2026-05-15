import hashlib
import os

from django.conf import settings
from django.http import FileResponse
from django.utils import timezone
from rest_framework import status, generics
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.users.permissions import IsTeacher, IsExamDept
from apps.scanning.models import MarkingScheme, AnswerSheet, Subject, Bundle
from apps.scanning.serializers import MarkingSchemeSerializer
from apps.audit.models import AuditLog
from utils.audit_helper import log_action
from .models import (
    EvaluationResult, BundleAssignment, ModerationSample,
    ModerationPaperStatus, Notification,
)
from .serializers import (
    EvaluationResultSerializer, BundleAssignmentSerializer,
    ModerationPaperStatusSerializer, NotificationSerializer,
    BundleAssignmentSummarySerializer,
)
from . import services


class IsTeacherOrExamDept(IsAuthenticated):
    def has_permission(self, request, view):
        if not super().has_permission(request, view):
            return False
        return request.user.role in ('teacher', 'exam_dept')


# ─────────────────────────────────────────────────────────
# Marking Scheme Views (unchanged)
# ─────────────────────────────────────────────────────────

class MarkingSchemeListCreateView(generics.ListCreateAPIView):
    queryset = MarkingScheme.objects.select_related('subject').all()
    serializer_class = MarkingSchemeSerializer

    def get_permissions(self):
        if self.request.method == 'POST':
            return [IsExamDept()]
        return [IsAuthenticated()]

    def get_queryset(self):
        qs = super().get_queryset()
        subject_code = self.request.query_params.get('subject_code')
        if subject_code:
            qs = qs.filter(subject__subject_code=subject_code)
        return qs

    def create(self, request, *args, **kwargs):
        subject_code = request.data.get('subject_code')
        subject_name = request.data.get('subject_name')
        department = request.data.get('department', '')
        semester = request.data.get('semester')
        sections = request.data.get('sections')

        if not subject_code or not subject_name or not sections:
            return Response(
                {'error': 'subject_code, subject_name and sections are required.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        subject, created = Subject.objects.get_or_create(
            subject_code=subject_code,
            defaults={
                'subject_name': subject_name,
                'department': department,
                'semester': int(semester) if semester else 1
            }
        )

        if not created and MarkingScheme.objects.filter(subject=subject).exists():
           return Response(
               {'error': f'A marking scheme already exists for subject {subject_code}.'},
               status=status.HTTP_400_BAD_REQUEST
           )

        scheme_data = {
            'subject': subject.id,
            'sections': sections
        }

        serializer = self.get_serializer(data=scheme_data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        headers = self.get_success_headers(serializer.data)
        return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)

    def perform_create(self, serializer):
        instance = serializer.save()
        log_action(
            self.request, 'SCAN', 'MarkingScheme', instance.pk,
            new_value=MarkingSchemeSerializer(instance).data,
            notes=f'Marking scheme created for {instance.subject.subject_code}.'
        )


class MarkingSchemeDetailView(generics.RetrieveUpdateAPIView):
    queryset = MarkingScheme.objects.select_related('subject').all()
    serializer_class = MarkingSchemeSerializer

    def get_permissions(self):
        if self.request.method in ('PUT', 'PATCH'):
            return [IsExamDept()]
        return [IsAuthenticated()]

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop('partial', False)
        instance = self.get_object()

        subject_name = request.data.get('subject_name')
        subject_code = request.data.get('subject_code')
        department = request.data.get('department')
        semester = request.data.get('semester')
        sections = request.data.get('sections')

        subject = instance.subject
        subject_updated = False
        if subject_name and subject.subject_name != subject_name:
            subject.subject_name = subject_name
            subject_updated = True
        if subject_code and subject.subject_code != subject_code:
            if Subject.objects.exclude(id=subject.id).filter(subject_code=subject_code).exists():
                 return Response({'error': 'subject_code already in use.'}, status=400)
            subject.subject_code = subject_code
            subject_updated = True
        if department is not None and subject.department != department:
            subject.department = department
            subject_updated = True
        if semester is not None:
            try:
                sem = int(semester)
                if subject.semester != sem:
                    subject.semester = sem
                    subject_updated = True
            except ValueError:
                pass

        if subject_updated:
            subject.save()

        scheme_data = {'subject': subject.id}
        if sections is not None:
             scheme_data['sections'] = sections

        serializer = self.get_serializer(instance, data=scheme_data, partial=partial)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)

        if getattr(instance, '_prefetched_objects_cache', None):
            instance._prefetched_objects_cache = {}

        return Response(serializer.data)

    def perform_update(self, serializer):
        old_data = MarkingSchemeSerializer(self.get_object()).data
        instance = serializer.save()
        log_action(
            self.request, 'EDIT_MARKS', 'MarkingScheme', instance.pk,
            old_value=old_data,
            new_value=MarkingSchemeSerializer(instance).data,
            notes=f'Marking scheme updated for {instance.subject.subject_code}.'
        )


# ─────────────────────────────────────────────────────────
# Evaluation Views (updated for roles)
# ─────────────────────────────────────────────────────────

class EvaluationCreateView(APIView):
    """
    POST /api/evaluations/
    Teacher submits grading. Accepts role param for moderation workflow.
    """
    permission_classes = [IsTeacher]

    def post(self, request):
        answer_sheet_id = request.data.get('answer_sheet')
        mark_positions = request.data.get('mark_positions', [])
        role = request.data.get('role', 'assessor')

        try:
            sheet = AnswerSheet.objects.get(pk=answer_sheet_id)
        except AnswerSheet.DoesNotExist:
            return Response({'error': 'Answer sheet not found.'}, status=status.HTTP_404_NOT_FOUND)

        # Permission: teacher must be assigned (assessor) or moderator
        assignment = getattr(sheet.bundle, 'moderation_assignment', None)
        if assignment:
            if role == 'moderator':
                if request.user != assignment.moderator:
                    return Response({'error': 'Not authorized as moderator.'}, status=403)
                # Moderator can only evaluate moderation samples
                if not sheet.moderation_samples.filter(bundle_assignment=assignment).exists():
                    return Response({'error': 'This paper is not a moderation sample.'}, status=400)
            else:
                if request.user != assignment.assessor:
                    return Response({'error': 'Not authorized as assessor.'}, status=403)
        else:
            # Legacy flow: teacher must be assigned
            if sheet.assigned_teacher != request.user:
                return Response({'error': 'Not assigned to you.'}, status=404)

        # Check if moderator eval is locked
        existing = EvaluationResult.objects.filter(
            answer_sheet=sheet, role=role
        ).first()

        if existing and existing.comparison_locked:
            return Response(
                {'error': 'This evaluation is locked after comparison.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # If assessor is correcting a failed moderation paper, create revision
        if existing and role == 'assessor' and assignment:
            sample = sheet.moderation_samples.filter(bundle_assignment=assignment).first()
            if sample:
                try:
                    paper_status = sample.comparison_status
                    if paper_status.status == 'FAILED':
                        services.create_evaluation_revision(
                            existing, request.user, reason='Moderation correction'
                        )
                        log_action(
                            request, 'MOD_CORRECTION', 'EvaluationResult', existing.pk,
                            old_value={'total_marks': existing.total_marks},
                            notes=f'Assessor correcting marks after failed moderation.',
                        )
                except ModerationPaperStatus.DoesNotExist:
                    pass

        serializer = EvaluationResultSerializer(
            instance=existing,
            data=request.data,
            partial=(existing is not None),
        )
        serializer.is_valid(raise_exception=True)

        if existing:
            old_data = EvaluationResultSerializer(existing).data
            for field, value in serializer.validated_data.items():
                setattr(existing, field, value)
            existing.mark_positions = mark_positions
            existing.total_marks = getattr(serializer, '_computed_total', existing.total_marks)
            existing.is_final = True
            existing.save()
            existing.refresh_from_db()
            instance = existing
            is_new = False
        else:
            instance = serializer.save(
                teacher=request.user,
                role=role,
                pdf_version_at_grading=sheet.pdf_version,
                mark_positions=mark_positions,
                is_final=True,
            )
            is_new = True

        # ── Queue PDF generation in background — do NOT block the response ──
        if mark_positions and role == 'assessor':
            instance.pdf_status = 'pending'
            instance.save(update_fields=['pdf_status'])
            from .pdf_worker import submit_pdf_task
            submit_pdf_task(instance.pk)
        else:
            instance.pdf_status = 'skipped'
            instance.save(update_fields=['pdf_status'])

        # Update sheet status — only assessor submissions mark the sheet
        if role == 'assessor':
            sheet.status = 'completed'
            sheet.save(update_fields=['status'])

        action_type = 'GRADE' if is_new else 'EDIT_MARKS'
        log_action(
            request, action_type, 'EvaluationResult', instance.pk,
            old_value=None if is_new else EvaluationResultSerializer(instance).data,
            new_value={
                'total_marks': instance.total_marks,
                'role': instance.role,
                'pdf_status': instance.pdf_status,
                'badge_count': len(mark_positions),
            },
            notes=f'Evaluated ({role}) by {request.user.full_name}. Total: {instance.total_marks}.',
        )

        return Response(
            EvaluationResultSerializer(instance).data,
            status=status.HTTP_201_CREATED if is_new else status.HTTP_200_OK,
        )


class EvaluationDetailView(APIView):
    """GET /api/evaluations/{answer_sheet_id}/?role=assessor"""

    def get_permissions(self):
        return [IsTeacherOrExamDept()]

    def get(self, request, answer_sheet_id):
        role = request.query_params.get('role', 'assessor')
        try:
            result = EvaluationResult.objects.select_related(
                'teacher', 'answer_sheet'
            ).get(answer_sheet_id=answer_sheet_id, role=role)
        except EvaluationResult.DoesNotExist:
            return Response({'error': 'Evaluation result not found.'}, status=404)

        if request.user.role == 'teacher' and result.teacher != request.user:
            return Response({'error': 'Not authorized.'}, status=403)

        return Response(EvaluationResultSerializer(result).data)


class EvaluationAmendView(APIView):
    """PATCH /api/evaluations/{pk}/amend-marks/ — Exam Dept corrects marks."""
    permission_classes = [IsExamDept]

    def patch(self, request, pk):
        try:
            result = EvaluationResult.objects.select_related(
                'teacher', 'answer_sheet'
            ).get(pk=pk)
        except EvaluationResult.DoesNotExist:
            return Response({'error': 'Evaluation result not found.'}, status=404)

        new_section_results = request.data.get('section_results')
        if not new_section_results:
            return Response({'error': 'section_results is required.'}, status=400)

        serializer = EvaluationResultSerializer(
            result, data={'section_results': new_section_results,
                          'answer_sheet': result.answer_sheet_id,
                          'pdf_version_at_grading': result.pdf_version_at_grading},
            partial=True
        )
        serializer.is_valid(raise_exception=True)

        old_data = {
            'section_results': result.section_results,
            'total_marks': result.total_marks,
        }

        result.section_results = serializer.validated_data['section_results']
        result.total_marks = getattr(serializer, '_computed_total', result.total_marks)
        result.was_amended = True
        result.amended_at = timezone.now()
        result.save()

        log_action(
            request, 'AMEND_MARKS', 'EvaluationResult', result.pk,
            old_value=old_data,
            new_value={'section_results': result.section_results, 'total_marks': result.total_marks},
            notes=f'Marks amended by Exam Dept. New total: {result.total_marks}.'
        )

        return Response(EvaluationResultSerializer(result).data)


class SaveEvaluationDraftView(APIView):
    """PATCH /api/evaluations/draft/ — Auto-save draft with role support."""
    permission_classes = [IsTeacher]

    def patch(self, request):
        answer_sheet_id = request.data.get('answer_sheet')
        section_results = request.data.get('section_results', [])
        mark_positions = request.data.get('mark_positions', [])
        role = request.data.get('role', 'assessor')

        try:
            sheet = AnswerSheet.objects.get(pk=answer_sheet_id)
        except AnswerSheet.DoesNotExist:
            return Response({'error': 'Answer sheet not found.'}, status=404)

        # Verify authorization
        assignment = getattr(sheet.bundle, 'moderation_assignment', None)
        if assignment:
            if role == 'moderator' and request.user != assignment.moderator:
                return Response({'error': 'Not authorized.'}, status=403)
            elif role == 'assessor' and request.user != assignment.assessor:
                return Response({'error': 'Not authorized.'}, status=403)
        elif sheet.assigned_teacher != request.user:
            return Response({'error': 'Not authorized.'}, status=403)

        # Check if locked
        existing = EvaluationResult.objects.filter(
            answer_sheet=sheet, role=role
        ).first()
        if existing and existing.comparison_locked:
            return Response({'error': 'Evaluation locked.'}, status=400)

        # Compute total
        from math import ceil as _ceil
        total = 0
        for q in (section_results or []):
            for sq in q.get('sub_questions', []):
                for p in sq.get('parts', []):
                    v = p.get('marks_obtained')
                    if isinstance(v, (int, float)) and v >= 0:
                        total += v
        total = _ceil(total)

        result, created = EvaluationResult.objects.update_or_create(
            answer_sheet=sheet,
            role=role,
            defaults={
                'teacher': request.user,
                'section_results': section_results,
                'mark_positions': mark_positions,
                'total_marks': total,
                'pdf_version_at_grading': sheet.pdf_version,
            }
        )

        if sheet.status == 'assigned':
            sheet.status = 'under_evaluation'
            sheet.save(update_fields=['status'])

        return Response({'status': 'draft_saved', 'total_marks': total})


class MarkedPDFView(APIView):
    """GET /api/evaluations/{pk}/marked-pdf/"""
    def get_permissions(self):
        return [IsTeacherOrExamDept()]

    def get(self, request, pk):
        try:
            result = EvaluationResult.objects.select_related('answer_sheet').get(pk=pk)
        except EvaluationResult.DoesNotExist:
            return Response({'error': 'Not found.'}, status=404)

        if request.user.role == 'teacher' and result.teacher != request.user:
            return Response({'error': 'Forbidden.'}, status=403)

        if not result.marked_pdf_path:
            return Response({'error': 'Marked PDF not yet generated.'}, status=404)

        full_path = os.path.join(settings.MEDIA_ROOT, result.marked_pdf_path)
        if not os.path.exists(full_path):
            return Response({'error': 'Marked PDF file not found on disk.'}, status=404)

        response = FileResponse(open(full_path, 'rb'), content_type='application/pdf')
        response['Content-Disposition'] = f'inline; filename="marked_{pk}.pdf"'
        return response


class VerifyMarkedPDFView(APIView):
    """GET /api/evaluations/{pk}/verify-pdf/"""
    permission_classes = [IsExamDept]

    def get(self, request, pk):
        try:
            result = EvaluationResult.objects.get(pk=pk)
        except EvaluationResult.DoesNotExist:
            return Response({'error': 'Not found.'}, status=404)

        if not result.marked_pdf_path:
            return Response({'error': 'No marked PDF for this evaluation.'}, status=404)

        full_path = os.path.join(settings.MEDIA_ROOT, result.marked_pdf_path)
        if not os.path.exists(full_path):
            return Response({'error': 'Marked PDF missing from disk.'}, status=404)

        with open(full_path, 'rb') as f:
            computed_hash = hashlib.sha256(f.read()).hexdigest()

        log_entry = AuditLog.objects.filter(
            action_type='GRADE', target_model='EvaluationResult', target_id=str(pk),
        ).order_by('-performed_at').first()

        stored_hash = None
        if log_entry and log_entry.new_value:
            stored_hash = log_entry.new_value.get('pdf_sha256')

        return Response({
            'verified': stored_hash is not None,
            'stored_hash': stored_hash,
            'computed_hash': computed_hash,
            'match': stored_hash == computed_hash,
        })


class PDFStatusView(APIView):
    """GET /api/evaluations/{pk}/pdf-status/"""
    permission_classes = [IsTeacherOrExamDept]

    def get(self, request, pk):
        try:
            result = EvaluationResult.objects.only(
                'pdf_status', 'marked_pdf_path', 'pdf_error'
            ).get(pk=pk)
        except EvaluationResult.DoesNotExist:
            return Response({'error': 'Not found.'}, status=404)
        return Response({
            'pdf_status': result.pdf_status,
            'marked_pdf_path': result.marked_pdf_path or None,
            'has_error': bool(result.pdf_error),
            'pdf_error': result.pdf_error,
        })


# ─────────────────────────────────────────────────────────
# Bundle Assignment (Moderation)
# ─────────────────────────────────────────────────────────

class BundleAssignmentCreateView(APIView):
    """POST /api/bundles/{pk}/assign-moderation/ — Exam dept assigns assessor + moderator."""
    permission_classes = [IsExamDept]

    def post(self, request, pk):
        try:
            bundle = Bundle.objects.get(pk=pk, status='submitted')
        except Bundle.DoesNotExist:
            return Response({'error': 'Submitted bundle not found.'}, status=404)

        if hasattr(bundle, 'moderation_assignment'):
            return Response({'error': 'Bundle already has an assignment.'}, status=400)

        assessor_id = request.data.get('assessor_id')
        moderator_id = request.data.get('moderator_id')

        if not assessor_id or not moderator_id:
            return Response({'error': 'assessor_id and moderator_id required.'}, status=400)

        if str(assessor_id) == str(moderator_id):
            return Response({'error': 'Assessor and moderator must be different.'}, status=400)

        from apps.users.models import User
        try:
            assessor = User.objects.get(pk=assessor_id, role='teacher')
            moderator = User.objects.get(pk=moderator_id, role='teacher')
        except User.DoesNotExist:
            return Response({'error': 'Teacher not found.'}, status=404)

        assignment = services.create_bundle_assignment(request, bundle, assessor, moderator)

        return Response(
            BundleAssignmentSerializer(assignment).data,
            status=status.HTTP_201_CREATED,
        )


class RequestComparisonView(APIView):
    """POST /api/moderation/{bundle_id}/request-comparison/"""
    permission_classes = [IsTeacher]

    def post(self, request, bundle_id):
        try:
            assignment = BundleAssignment.objects.select_related(
                'bundle', 'assessor', 'moderator'
            ).get(bundle_id=bundle_id)
        except BundleAssignment.DoesNotExist:
            return Response({'error': 'No moderation assignment found.'}, status=404)

        if request.user != assignment.assessor:
            return Response({'error': 'Only the assessor can request comparison.'}, status=403)

        from django.db.models import Q
        # Check assessor has evaluated all moderation papers
        sample_ids = list(assignment.samples.values_list('answer_sheet_id', flat=True))
        assessor_eval_count = EvaluationResult.objects.filter(
            Q(is_final=True) | Q(answer_sheet__status='completed'),
            answer_sheet_id__in=sample_ids, role='assessor', teacher=assignment.assessor
        ).count()
        if assessor_eval_count < len(sample_ids):
            return Response({
                'error': 'You must evaluate all moderation papers first.',
                'evaluated': assessor_eval_count,
                'total': len(sample_ids),
            }, status=400)

        # Check moderator completion
        is_complete, missing = services.check_moderator_completion(assignment)
        if not is_complete:
            # Send reminder notification
            Notification.objects.create(
                recipient=assignment.moderator,
                event_type='MODERATION_INCOMPLETE',
                message=f'Assessor has requested comparison for Bundle '
                        f'#{assignment.bundle.bundle_number}. '
                        f'{missing} paper(s) still need your evaluation.',
                bundle=assignment.bundle,
            )
            log_action(
                request, 'MOD_REQUESTED', 'BundleAssignment', assignment.pk,
                notes=f'Comparison blocked: moderator has {missing} papers remaining.',
            )
            return Response({
                'status': 'BLOCKED',
                'message': f'Moderator has not completed evaluation. {missing} paper(s) remaining. A reminder has been sent.',
                'missing_count': missing,
            })

        # Run comparison
        log_action(
            request, 'MOD_REQUESTED', 'BundleAssignment', assignment.pk,
            notes='Comparison requested and executed.',
        )
        result = services.run_moderation_comparison(request, assignment)
        return Response(result)


class ModerationStatusView(APIView):
    """GET /api/moderation/{bundle_id}/status/"""
    permission_classes = [IsTeacherOrExamDept]

    def get(self, request, bundle_id):
        try:
            assignment = BundleAssignment.objects.select_related(
                'bundle', 'assessor', 'moderator'
            ).get(bundle_id=bundle_id)
        except BundleAssignment.DoesNotExist:
            return Response({'error': 'No moderation assignment.'}, status=404)

        # Build per-paper status
        samples = assignment.samples.select_related('answer_sheet').all()
        paper_statuses = []
        for sample in samples:
            try:
                ps = sample.comparison_status
                paper_statuses.append(ModerationPaperStatusSerializer(ps).data)
            except ModerationPaperStatus.DoesNotExist:
                paper_statuses.append({
                    'paper_id': sample.answer_sheet_id,
                    'token': sample.answer_sheet.token,
                    'status': 'PENDING',
                    'assessor_total': None, 'moderator_total': None,
                    'allowed_difference': None,
                    'question_comparison': [], 'compared_at': None,
                })

        from django.db.models import Q
        # Check eval completion
        sample_ids = [s.answer_sheet_id for s in samples]
        assessor_evals = EvaluationResult.objects.filter(
            Q(is_final=True) | Q(answer_sheet__status='completed'),
            answer_sheet_id__in=sample_ids, role='assessor'
        )
        moderator_evals = EvaluationResult.objects.filter(
            answer_sheet_id__in=sample_ids, role='moderator', is_final=True
        )
        assessor_done = assessor_evals.count()
        moderator_done = moderator_evals.count()
        assessor_eval_ids = set(assessor_evals.values_list('answer_sheet_id', flat=True))
        moderator_eval_ids = set(moderator_evals.values_list('answer_sheet_id', flat=True))

        # Determine bundle moderation state
        if assignment.moderation_passed:
            bundle_mod_status = 'UNLOCKED'
        elif assignment.moderation_completed and not assignment.moderation_passed:
            bundle_mod_status = 'FAILED'
        elif assignment.moderation_requested_at:
            bundle_mod_status = 'COMPARISON_REQUESTED'
        else:
            bundle_mod_status = 'PENDING'

        return Response({
            'assignment': BundleAssignmentSummarySerializer(assignment).data,
            'bundle_status': bundle_mod_status,
            'sample_count': len(sample_ids),
            'sample_sheet_ids': sample_ids,
            'assessor_evaluated': assessor_done,
            'moderator_evaluated': moderator_done,
            'assessor_evaluated_sheet_ids': list(assessor_eval_ids),
            'moderator_evaluated_sheet_ids': list(moderator_eval_ids),
            'papers': paper_statuses,
        })


# ─────────────────────────────────────────────────────────
# Teacher Bundle Views (Assessment / Moderation split)
# ─────────────────────────────────────────────────────────

class TeacherAssessmentBundlesView(APIView):
    """GET /api/teacher/bundles/assessment/"""
    permission_classes = [IsTeacher]

    def get(self, request):
        from apps.scanning.serializers import BundleSerializer
        # Bundles where user is assessor (via BundleAssignment) OR legacy assigned
        mod_bundle_ids = BundleAssignment.objects.filter(
            assessor=request.user
        ).values_list('bundle_id', flat=True)

        legacy_bundle_ids = AnswerSheet.objects.filter(
            assigned_teacher=request.user
        ).values_list('bundle_id', flat=True).distinct()

        all_ids = set(mod_bundle_ids) | set(legacy_bundle_ids)

        bundles = Bundle.objects.filter(id__in=all_ids).select_related('subject', 'created_by')
        return Response(BundleSerializer(bundles, many=True).data)


class TeacherModerationBundlesView(APIView):
    """GET /api/teacher/bundles/moderation/"""
    permission_classes = [IsTeacher]

    def get(self, request):
        from apps.scanning.serializers import BundleSerializer
        bundle_ids = BundleAssignment.objects.filter(
            moderator=request.user
        ).values_list('bundle_id', flat=True)

        bundles = Bundle.objects.filter(id__in=bundle_ids).select_related('subject', 'created_by')
        return Response(BundleSerializer(bundles, many=True).data)


# ─────────────────────────────────────────────────────────
# Notification Views
# ─────────────────────────────────────────────────────────

class NotificationListView(APIView):
    """GET /api/notifications/"""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        notifs = Notification.objects.filter(recipient=request.user)[:50]
        return Response(NotificationSerializer(notifs, many=True).data)


class NotificationMarkReadView(APIView):
    """PATCH /api/notifications/{pk}/read/"""
    permission_classes = [IsAuthenticated]

    def patch(self, request, pk):
        try:
            n = Notification.objects.get(pk=pk, recipient=request.user)
        except Notification.DoesNotExist:
            return Response({'error': 'Not found.'}, status=404)
        n.is_read = True
        n.save(update_fields=['is_read'])
        return Response({'status': 'ok'})


class NotificationMarkAllReadView(APIView):
    """PATCH /api/notifications/read-all/"""
    permission_classes = [IsAuthenticated]

    def patch(self, request):
        Notification.objects.filter(
            recipient=request.user, is_read=False
        ).update(is_read=True)
        return Response({'status': 'ok'})
