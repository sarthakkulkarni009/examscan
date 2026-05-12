import io
import os
from django.conf import settings
from django.db import IntegrityError
from django.http import FileResponse, Http404
from django.utils import timezone
from rest_framework import status, generics
from rest_framework.parsers import MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.users.permissions import IsScanningStaff, IsTeacher, IsExamDept
from utils.audit_helper import log_action
from utils.barcode import detect_barcode
from utils.pdf_compiler import compile_images_to_pdf
from utils.token_crypto import generate_token
from .models import Bundle, AnswerSheet, AnswerSheetImage, Subject, StudentToken
from .serializers import (
    BundleSerializer, AnswerSheetSerializer, AnswerSheetImageSerializer, SubjectSerializer,
    StudentTokenBulkInputSerializer, StudentTokenWithRollSerializer,
)


# ─────────────────────────────────────────────────────────
# Subject Views
# ─────────────────────────────────────────────────────────

class SubjectListCreateView(generics.ListCreateAPIView):
    """GET / POST subjects. Exam dept can create; any authenticated can list."""
    queryset = Subject.objects.all()
    serializer_class = SubjectSerializer
    pagination_class = None

    def get_permissions(self):
        if self.request.method == 'POST':
            return [IsExamDept()]
        return [IsAuthenticated()]

    def perform_create(self, serializer):
        instance = serializer.save()
        log_action(self.request, 'SCAN', 'Subject', instance.pk, new_value=serializer.data)


# ─────────────────────────────────────────────────────────
# Bundle Views
# ─────────────────────────────────────────────────────────

class BundleCreateView(generics.CreateAPIView):
    """POST /api/bundles/ — Scanning staff creates a new bundle."""
    serializer_class = BundleSerializer
    permission_classes = [IsScanningStaff]

    def perform_create(self, serializer):
        instance = serializer.save(created_by=self.request.user)
        log_action(
            self.request, 'SCAN', 'Bundle', instance.pk,
            new_value=BundleSerializer(instance).data,
            notes=f'Bundle #{instance.bundle_number} created.'
        )


class BundleListView(generics.ListAPIView):
    """GET /api/bundles/ — Exam dept lists all bundles. Scanners list their own."""
    queryset = Bundle.objects.select_related('subject', 'created_by').all()
    serializer_class = BundleSerializer
    pagination_class = None
    filterset_fields = ['status', 'subject__department']

    def get_permissions(self):
        # Allow Exam Dept, Scanning Staff, and Teachers securely.
        if self.request.user and self.request.user.is_authenticated:
            if self.request.user.role in ['exam_dept', 'scanning_staff', 'teacher']:
                return [IsAuthenticated()]
        return [IsExamDept()]

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        if user and user.is_authenticated:
            if user.role == 'scanning_staff':
                qs = qs.filter(created_by=user)
            elif user.role == 'exam_dept':
                qs = qs.filter(status='submitted')
            elif user.role == 'teacher':
                from django.db.models import Q
                qs = qs.filter(
                    Q(answer_sheets__assigned_teacher=user) |
                    Q(moderation_assignment__moderator=user)
                ).distinct()
        return qs


class BundleDetailView(generics.RetrieveDestroyAPIView):
    """GET /api/bundles/{id}/ — Exam dept or scanning staff. DELETE allowed for open bundles."""
    queryset = Bundle.objects.select_related('subject', 'created_by').all()
    serializer_class = BundleSerializer

    def get_permissions(self):
        user = self.request.user
        if user and user.is_authenticated and user.role in ['exam_dept', 'scanning_staff']:
            return [IsAuthenticated()]
        return [IsExamDept()]

    def perform_destroy(self, instance):
        from rest_framework import serializers
        if instance.status == 'submitted':
            raise serializers.ValidationError({"error": "You cannot delete a bundle that has already been submitted."})
        
        # Only allow the creator to delete it, or the admin
        user = self.request.user
        if user.role == 'scanning_staff' and instance.created_by != user:
            raise serializers.ValidationError({"error": "You can only delete your own bundles."})
            
        import os
        from django.conf import settings
        import shutil

        bundle_dir = os.path.join(settings.MEDIA_ROOT, f'answer_sheets/bundle_{instance.pk}')
        if os.path.exists(bundle_dir):
            shutil.rmtree(bundle_dir)

        log_action(
            self.request, 'SCAN', 'Bundle', instance.pk,
            old_value=BundleSerializer(instance).data,
            notes='Bundle deleted by scanning staff.'
        )
        instance.delete()


class BundleSubmitView(APIView):
    """PATCH /api/bundles/{id}/submit/ — Scanning staff marks bundle as submitted."""
    permission_classes = [IsScanningStaff]

    def patch(self, request, pk):
        try:
            bundle = Bundle.objects.get(pk=pk)
        except Bundle.DoesNotExist:
            return Response({'error': 'Bundle not found.'}, status=status.HTTP_404_NOT_FOUND)

        if bundle.status == 'submitted':
            return Response({'error': 'Bundle already submitted.'}, status=status.HTTP_400_BAD_REQUEST)

        # Validate: actual sheet count must match declared total
        actual_count = bundle.answer_sheets.count()
        if actual_count != bundle.total_sheets:
            return Response(
                {
                    'error': f'Sheet count mismatch. Expected {bundle.total_sheets} answer sheets but found {actual_count}. '
                             f'Please finalize all sheets before submitting.'
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        old_status = bundle.status
        bundle.status = 'submitted'
        bundle.save()

        log_action(
            request, 'SUBMIT_SESSION', 'Bundle', bundle.pk,
            old_value={'status': old_status},
            new_value={'status': 'submitted'},
            notes=f'Bundle #{bundle.bundle_number} submitted.'
        )

        return Response(BundleSerializer(bundle).data, status=status.HTTP_200_OK)


class BundleAssignView(APIView):
    """PATCH /api/bundles/{id}/assign/ — Exam dept assigns a teacher to all sheets in a bundle."""
    permission_classes = [IsExamDept]

    def patch(self, request, pk):
        try:
            bundle = Bundle.objects.get(pk=pk, status='submitted')
        except Bundle.DoesNotExist:
            return Response({'error': 'Submitted bundle not found.'}, status=status.HTTP_404_NOT_FOUND)

        teacher_id = request.data.get('teacher_id')
        if not teacher_id:
            return Response({'error': 'teacher_id is required.'}, status=status.HTTP_400_BAD_REQUEST)

        from apps.users.models import User
        try:
            teacher = User.objects.get(pk=teacher_id, role='teacher')
        except User.DoesNotExist:
            return Response({'error': 'Teacher not found.'}, status=status.HTTP_404_NOT_FOUND)

        # Update all sheets inside the bundle
        sheets = bundle.answer_sheets.all()
        updated = sheets.update(assigned_teacher=teacher, status='assigned')

        # Log it
        log_action(
            request, 'ASSIGN', 'Bundle', bundle.pk,
            new_value={'assigned_teacher': str(teacher.id)},
            notes=f'Bundle #{bundle.bundle_number} assigned to {teacher.full_name}.'
        )

        return Response({'message': f'Assigned {updated} sheets in bundle to teacher.'}, status=status.HTTP_200_OK)


# ─────────────────────────────────────────────────────────
# Answer Sheet Image Views
# ─────────────────────────────────────────────────────────

class AnswerSheetImageUploadView(APIView):
    """POST /api/answer-sheets/upload-image/ — Upload a scanned page image."""
    permission_classes = [IsScanningStaff]
    parser_classes = [MultiPartParser]

    def post(self, request):
        bundle_id = request.data.get('bundle_id')
        image_file = request.FILES.get('image')
        page_number = request.data.get('page_number', 1)
        is_first_page = request.data.get('is_first_page', 'false').lower() == 'true'
        token = request.data.get('token', '')

        if not bundle_id or not image_file:
            return Response(
                {'error': 'bundle_id and image are required.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            bundle = Bundle.objects.get(pk=bundle_id)
        except Bundle.DoesNotExist:
            return Response({'error': 'Bundle not found.'}, status=status.HTTP_404_NOT_FOUND)

        if bundle.status == 'submitted':
            return Response({'error': 'Cannot upload to a submitted bundle.'}, status=status.HTTP_400_BAD_REQUEST)

        # Detect barcode on first page — barcode contains the encrypted token
        detected_token = None
        if is_first_page:
            detected_token = detect_barcode(image_file)
            image_file.seek(0)  # reset pointer after read
            if not detected_token:
                return Response(
                    {'error': 'Could not detect barcode on the first page.'},
                    status=status.HTTP_422_UNPROCESSABLE_ENTITY
                )
            # Look up the StudentToken to validate it
            try:
                student_token = StudentToken.objects.get(
                    token=detected_token,
                    subject=bundle.subject
                )
            except StudentToken.DoesNotExist:
                return Response(
                    {'error': f'Token "{detected_token}" is not registered for subject {bundle.subject.subject_code}. Contact Exam Dept.'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            # Mark token as used
            student_token.is_used = True
            student_token.save(update_fields=['is_used'])
            token = detected_token

        sheet_image = AnswerSheetImage.objects.create(
            bundle=bundle,
            token=token,
            roll_number='',  # roll_number never stored in temp images
            image=image_file,
            page_number=int(page_number),
            is_first_page=is_first_page,
        )

        log_action(
            request, 'SCAN', 'AnswerSheetImage', sheet_image.pk,
            new_value={'token': token, 'page_number': int(page_number)},
            notes=f'Image uploaded for bundle #{bundle.bundle_number}.'
        )

        # Immediate quality check for the frontend
        from utils.blur_detector import check_image_quality
        quality = check_image_quality(sheet_image.image.path)

        data = AnswerSheetImageSerializer(sheet_image).data
        data['is_blurry'] = quality.get('is_blurry', False)
        data['is_low_quality'] = quality.get('is_low_quality', False)
        data['quality_score'] = quality['score']

        if detected_token:
            data['detected_token'] = detected_token
            
        return Response(data, status=status.HTTP_201_CREATED)


class AnswerSheetImageDeleteView(APIView):
    """DELETE /api/answer-sheets/upload-image/{id}/ — Delete a scanned image."""
    permission_classes = [IsScanningStaff]

    def delete(self, request, pk):
        try:
            img = AnswerSheetImage.objects.get(pk=pk)
        except AnswerSheetImage.DoesNotExist:
            return Response({'error': 'Image not found.'}, status=status.HTTP_404_NOT_FOUND)

        if img.bundle.status == 'submitted':
            return Response(
                {'error': 'Cannot delete images from a submitted bundle.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        log_action(
            request, 'SCAN', 'AnswerSheetImage', img.pk,
            old_value={'roll_number': img.roll_number, 'page_number': img.page_number},
            notes='Scanned image deleted.'
        )

        # Delete physical file
        if img.image and os.path.isfile(img.image.path):
            os.remove(img.image.path)
        img.delete()

        return Response({'message': 'Image deleted.'}, status=status.HTTP_200_OK)


class AnswerSheetFinalizeView(APIView):
    """
    POST /api/answer-sheets/finalize/
    Compiles all images for a token within a bundle into a single PDF.
    """
    permission_classes = [IsScanningStaff]

    def post(self, request):
        bundle_id = request.data.get('bundle_id')
        token = request.data.get('token')

        if not bundle_id or not token:
            return Response(
                {'error': 'bundle_id and token are required.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            bundle = Bundle.objects.get(pk=bundle_id)
        except Bundle.DoesNotExist:
            return Response({'error': 'Bundle not found.'}, status=status.HTTP_404_NOT_FOUND)

        images = AnswerSheetImage.objects.filter(
            bundle=bundle, token=token
        ).order_by('page_number')

        if not images.exists():
            return Response(
                {'error': 'No images found for this token in the bundle.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Look up the real roll number from StudentToken
        roll_number = token  # fallback for legacy tokens
        try:
            student_token = StudentToken.objects.get(token=token, subject=bundle.subject)
            roll_number = student_token.roll_number
        except StudentToken.DoesNotExist:
            pass  # Legacy token — use token as roll_number directly

        # Compile PDF — filename uses token, not roll number
        image_paths = [img.image.path for img in images]
        pdf_rel_path = f'answer_sheets/bundle_{bundle_id}/{token}.pdf'
        pdf_abs_path = os.path.join(settings.MEDIA_ROOT, pdf_rel_path)

        try:
            compile_images_to_pdf(image_paths, pdf_abs_path)
        except RuntimeError as e:
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        # Calculate sharpness of the compiled PDF
        from utils.blur_detector import check_pdf_quality
        quality_info = check_pdf_quality(pdf_abs_path)

        # Create or update AnswerSheet record
        answer_sheet, created = AnswerSheet.objects.update_or_create(
            bundle=bundle,
            token=token,
            defaults={
                'roll_number': roll_number,
                'pdf_file': pdf_rel_path,
                'scanned_by': request.user,
                'status': 'pending',
                'quality_score': quality_info.get('score'),
            }
        )
        if not created:
            answer_sheet.pdf_version += 1
            answer_sheet.save()

        # ── Cleanup: delete raw scanned images now that PDF is compiled ──
        deleted_count = 0
        for img in images:
            try:
                if img.image and os.path.isfile(img.image.path):
                    os.remove(img.image.path)
            except Exception:
                pass  # Don't fail the whole request over a stale file
            img.delete()
            deleted_count += 1

        log_action(
            request, 'SCAN', 'AnswerSheet', answer_sheet.pk,
            new_value={'token': token, 'pdf_version': answer_sheet.pdf_version},
            notes=f'Answer sheet finalized for token {token}. {deleted_count} raw images cleaned up.'
        )

        return Response(
            AnswerSheetSerializer(answer_sheet, context={'request': request}).data,
            status=status.HTTP_201_CREATED
        )


# ─────────────────────────────────────────────────────────
# Answer Sheet Management Views
# ─────────────────────────────────────────────────────────

class AnswerSheetListView(generics.ListAPIView):
    """
    GET /api/answer-sheets/
    Exam dept sees all; teachers see only their assigned sheets.
    """
    serializer_class = AnswerSheetSerializer
    pagination_class = None

    def get_permissions(self):
        # Allow any of these roles
        user = self.request.user
        if user and user.is_authenticated and user.role in ['exam_dept', 'teacher', 'scanning_staff']:
            return [IsAuthenticated()]
        return [IsExamDept()]

    def get_queryset(self):
        qs = AnswerSheet.objects.select_related(
            'bundle', 'bundle__subject', 'assigned_teacher'
        )
        user = self.request.user
        if user.role == 'teacher':
            from django.db.models import Q
            qs = qs.filter(
                Q(assigned_teacher=self.request.user) |
                Q(moderation_samples__bundle_assignment__moderator=self.request.user)
            ).distinct()
        elif user.role == 'scanning_staff':
            qs = qs.filter(bundle__created_by=user)
        elif user.role == 'exam_dept':
            qs = qs.filter(bundle__status='submitted')

        # Filtering
        bundle_id = self.request.query_params.get('bundle')
        status_filter = self.request.query_params.get('status')
        if bundle_id:
            qs = qs.filter(bundle_id=bundle_id)
        if status_filter:
            qs = qs.filter(status=status_filter)
        return qs


class AnswerSheetAssignView(APIView):
    """PATCH /api/answer-sheets/{id}/assign/ — Exam dept assigns a teacher."""
    permission_classes = [IsExamDept]

    def patch(self, request, pk):
        try:
            sheet = AnswerSheet.objects.get(pk=pk)
        except AnswerSheet.DoesNotExist:
            return Response({'error': 'Answer sheet not found.'}, status=status.HTTP_404_NOT_FOUND)

        teacher_id = request.data.get('teacher_id')
        if not teacher_id:
            return Response({'error': 'teacher_id is required.'}, status=status.HTTP_400_BAD_REQUEST)

        from apps.users.models import User
        try:
            teacher = User.objects.get(pk=teacher_id, role='teacher')
        except User.DoesNotExist:
            return Response({'error': 'Teacher not found.'}, status=status.HTTP_404_NOT_FOUND)

        old_teacher = str(sheet.assigned_teacher_id) if sheet.assigned_teacher_id else None
        sheet.assigned_teacher = teacher
        sheet.status = 'assigned'
        sheet.save()

        log_action(
            request, 'ASSIGN', 'AnswerSheet', sheet.pk,
            old_value={'assigned_teacher': old_teacher},
            new_value={'assigned_teacher': str(teacher.id)},
            notes=f'Sheet assigned to {teacher.full_name}.'
        )

        return Response(
            AnswerSheetSerializer(sheet, context={'request': request}).data,
            status=status.HTTP_200_OK
        )


class AnswerSheetBulkAssignView(APIView):
    """PATCH /api/answer-sheets/bulk-assign/ — Exam dept assigns multiple sheets."""
    permission_classes = [IsExamDept]

    def patch(self, request):
        teacher_id = request.data.get('teacher_id')
        sheet_ids = request.data.get('sheet_ids', [])

        if not teacher_id or not sheet_ids:
            return Response(
                {'error': 'teacher_id and sheet_ids are required.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        from apps.users.models import User
        try:
            teacher = User.objects.get(pk=teacher_id, role='teacher')
        except User.DoesNotExist:
            return Response({'error': 'Teacher not found.'}, status=status.HTTP_404_NOT_FOUND)

        sheets = AnswerSheet.objects.filter(pk__in=sheet_ids)
        updated = sheets.update(assigned_teacher=teacher, status='assigned')

        for sheet in sheets:
            log_action(
                request, 'ASSIGN', 'AnswerSheet', sheet.pk,
                new_value={'assigned_teacher': str(teacher.id)},
                notes=f'Bulk assign to {teacher.full_name}.'
            )

        return Response({'message': f'{updated} sheets assigned.'}, status=status.HTTP_200_OK)


class AnswerSheetFlagView(APIView):
    """PATCH /api/answer-sheets/{id}/flag/ — Teacher flags an answer sheet."""
    permission_classes = [IsTeacher]

    def patch(self, request, pk):
        try:
            sheet = AnswerSheet.objects.get(pk=pk, assigned_teacher=request.user)
        except AnswerSheet.DoesNotExist:
            return Response({'error': 'Answer sheet not found.'}, status=status.HTTP_404_NOT_FOUND)

        reason = request.data.get('flag_reason')
        if not reason:
            return Response({'error': 'flag_reason is required.'}, status=status.HTTP_400_BAD_REQUEST)

        old_status = sheet.status
        sheet.status = 'flagged'
        sheet.flag_reason = reason
        sheet.last_flagged_at = timezone.now()
        sheet.save()

        log_action(
            request, 'FLAG', 'AnswerSheet', sheet.pk,
            old_value={'status': old_status},
            new_value={'status': 'flagged', 'flag_reason': reason},
            notes=f'Sheet flagged: {reason}.'
        )

        return Response(
            AnswerSheetSerializer(sheet, context={'request': request}).data,
            status=status.HTTP_200_OK
        )


class AnswerSheetPDFView(APIView):
    """GET /api/answer-sheets/{id}/pdf/ — Stream the PDF file."""

    def get_permissions(self):
        user = self.request.user
        if user and user.is_authenticated and user.role in ['exam_dept', 'teacher']:
            return [IsAuthenticated()]
        return [IsExamDept()]

    def get(self, request, pk):
        try:
            sheet = AnswerSheet.objects.get(pk=pk)
        except AnswerSheet.DoesNotExist:
            raise Http404

        # Teachers can only view their own assigned sheets or moderation samples
        if request.user.role == 'teacher':
            is_assigned = (sheet.assigned_teacher == request.user)
            is_moderator = sheet.moderation_samples.filter(
                bundle_assignment__moderator=request.user
            ).exists()
            if not is_assigned and not is_moderator:
                return Response({'error': 'Not authorized.'}, status=status.HTTP_403_FORBIDDEN)

        file_path = sheet.pdf_file.path
        if not os.path.isfile(file_path):
            raise Http404

        response = FileResponse(open(file_path, 'rb'), content_type='application/pdf')
        response['Content-Disposition'] = f'inline; filename="sheet_{pk}.pdf"'
        return response


# ─────────────────────────────────────────────────────────
# Token Management Views (Exam Dept Only)
# ─────────────────────────────────────────────────────────

class GenerateStudentTokensView(APIView):
    """
    POST /api/tokens/generate/
    Exam Dept only.
    Accepts: { subject_id: int, roll_numbers: ["2023CS001", "2023CS002", ...] }
    Returns: [ { token: "XK729FAB", roll_number: "2023CS001" }, ... ]
    Skips duplicates silently (returns existing token for that student+subject).
    """
    permission_classes = [IsExamDept]

    def post(self, request):
        serializer = StudentTokenBulkInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        subject_id = serializer.validated_data['subject_id']
        roll_numbers = serializer.validated_data['roll_numbers']

        try:
            subject = Subject.objects.get(id=subject_id)
        except Subject.DoesNotExist:
            return Response({'error': 'Subject not found.'}, status=status.HTTP_404_NOT_FOUND)

        result = []
        for roll in roll_numbers:
            roll = roll.strip()
            if not roll:
                continue
            # Retry loop guards against the rare race where two concurrent
            # requests try to insert the same (roll_number, subject) pair,
            # or the even rarer case of a random token collision.
            for attempt in range(5):
                try:
                    obj, created = StudentToken.objects.get_or_create(
                        roll_number=roll,
                        subject=subject,
                        defaults={
                            'token': generate_token(roll),
                            'created_by': request.user,
                        }
                    )
                    break
                except IntegrityError:
                    # Token collision or concurrent insert — fetch the winner
                    try:
                        obj = StudentToken.objects.get(roll_number=roll, subject=subject)
                        break
                    except StudentToken.DoesNotExist:
                        continue  # genuine token collision; retry with new nonce
            else:
                return Response(
                    {'error': f'Could not generate a unique token for roll {roll}. Please retry.'},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )
            result.append({'token': obj.token, 'roll_number': roll})

        log_action(request, 'SCAN', 'StudentToken', subject_id,
                   notes=f"Generated {len(result)} tokens for subject {subject.subject_code}")

        return Response(result, status=status.HTTP_201_CREATED)


class ListStudentTokensView(APIView):
    """
    GET /api/tokens/?subject_id=&is_used=
    Exam Dept only.
    Returns token list WITH roll_numbers (for printing barcodes and report mapping).
    """
    permission_classes = [IsExamDept]

    def get(self, request):
        qs = StudentToken.objects.select_related('subject')
        subject_id = request.query_params.get('subject_id')
        is_used = request.query_params.get('is_used')
        if subject_id:
            qs = qs.filter(subject_id=subject_id)
        if is_used is not None:
            qs = qs.filter(is_used=is_used.lower() == 'true')
        serializer = StudentTokenWithRollSerializer(qs, many=True)
        return Response(serializer.data)


class TokenFileUploadView(APIView):
    """
    POST /api/tokens/upload/
    Exam Dept only.
    Accepts: multipart file (CSV or .xlsx) + subject_id
    Parses file, auto-detects roll number column, generates tokens.
    Returns: [ { token: "...", roll_number: "..." }, ... ]
    """
    permission_classes = [IsExamDept]
    parser_classes = [MultiPartParser]

    ROLL_COLUMN_HINTS = [
        'roll_number', 'roll_no', 'rollnumber', 'rollno',
        'roll', 'enrollment', 'enroll_no', 'reg_no',
        'registration_number', 'student_id', 'usn', 'prn',
    ]

    def _detect_column(self, headers):
        """Auto-detect the roll number column from headers."""
        for hint in self.ROLL_COLUMN_HINTS:
            for idx, header in enumerate(headers):
                if header.strip().lower().replace(' ', '_') == hint:
                    return idx
        return 0  # fallback to first column

    def post(self, request):
        file = request.FILES.get('file')
        subject_id = request.data.get('subject_id')

        if not file or not subject_id:
            return Response(
                {'error': 'file and subject_id are required.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            subject = Subject.objects.get(id=int(subject_id))
        except (Subject.DoesNotExist, ValueError):
            return Response({'error': 'Subject not found.'}, status=status.HTTP_404_NOT_FOUND)

        # Parse file
        filename = file.name.lower()
        roll_numbers = []

        try:
            if filename.endswith('.csv'):
                import csv
                content = file.read().decode('utf-8-sig')
                reader = csv.reader(io.StringIO(content))
                rows = list(reader)
                if not rows:
                    return Response({'error': 'File is empty.'}, status=status.HTTP_400_BAD_REQUEST)

                col_idx = self._detect_column(rows[0])
                for row in rows[1:]:  # skip header
                    if col_idx < len(row):
                        val = row[col_idx].strip()
                        if val:
                            roll_numbers.append(val)

            elif filename.endswith('.xlsx') or filename.endswith('.xls'):
                import openpyxl
                wb = openpyxl.load_workbook(file, read_only=True, data_only=True)
                ws = wb.active
                rows = list(ws.iter_rows(values_only=True))
                if not rows:
                    return Response({'error': 'File is empty.'}, status=status.HTTP_400_BAD_REQUEST)

                headers = [str(h or '').strip() for h in rows[0]]
                col_idx = self._detect_column(headers)
                for row in rows[1:]:
                    if col_idx < len(row) and row[col_idx] is not None:
                        val = str(row[col_idx]).strip()
                        if val:
                            roll_numbers.append(val)

            else:
                return Response(
                    {'error': 'Unsupported file format. Use .csv or .xlsx.'},
                    status=status.HTTP_400_BAD_REQUEST
                )
        except Exception as e:
            return Response(
                {'error': f'Failed to parse file: {str(e)}'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Deduplicate
        roll_numbers = list(dict.fromkeys(roll_numbers))

        if not roll_numbers:
            return Response(
                {'error': 'No valid roll numbers found in the file.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Generate tokens
        result = []
        for roll in roll_numbers:
            for attempt in range(5):
                try:
                    obj, created = StudentToken.objects.get_or_create(
                        roll_number=roll,
                        subject=subject,
                        defaults={
                            'token': generate_token(roll),
                            'created_by': request.user,
                        }
                    )
                    break
                except IntegrityError:
                    try:
                        obj = StudentToken.objects.get(roll_number=roll, subject=subject)
                        break
                    except StudentToken.DoesNotExist:
                        continue
            else:
                return Response(
                    {'error': f'Could not generate a unique token for roll {roll}. Please retry.'},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )
            result.append({'token': obj.token, 'roll_number': roll})

        log_action(request, 'SCAN', 'StudentToken', subject.id,
                   notes=f"File upload: generated {len(result)} tokens for {subject.subject_code} from {file.name}")

        return Response({
            'tokens': result,
            'count': len(result),
            'source_file': file.name,
        }, status=status.HTTP_201_CREATED)


# ─────────────────────────────────────────────────────────
# Quality Check Views (Scanning Staff)
# ─────────────────────────────────────────────────────────

class BundleQualityCheckView(APIView):
    """
    GET /api/bundles/{bundle_id}/quality-check/

    Scanning staff only. Runs Laplacian blur detection on all finalized
    AnswerSheet PDFs in the bundle. Returns per-sheet quality results
    so the frontend can highlight bad pages before final submission.

    Response:
    {
        "bundle_id": 23,
        "total_sheets": 5,
        "flagged_count": 1,
        "results": [
            {
                "sheet_id": 101,
                "token": "XK729FAB",
                "is_blurry": false,
                "score": 142.5,
                "thumbnail_url": "/api/answer-sheets/101/thumbnail/"
            }, ...
        ]
    }
    """
    permission_classes = [IsScanningStaff]

    def get(self, request, bundle_id):
        try:
            bundle = Bundle.objects.get(id=bundle_id)
        except Bundle.DoesNotExist:
            return Response({'error': 'Bundle not found.'}, status=status.HTTP_404_NOT_FOUND)

        sheets = AnswerSheet.objects.filter(bundle=bundle).order_by('token')
        if not sheets.exists():
            return Response({'error': 'No answer sheets found for this bundle.'}, status=status.HTTP_400_BAD_REQUEST)

        from utils.blur_detector import check_answer_sheet_quality

        results = []
        for sheet in sheets:
            quality = check_answer_sheet_quality(sheet)
            results.append({
                'sheet_id': sheet.id,
                'token': sheet.token,
                'is_blurry': quality['is_blurry'],
                'score': quality['score'],
                'thumbnail_url': f'/api/answer-sheets/{sheet.id}/thumbnail/',
            })

        flagged_count = sum(1 for r in results if r['is_blurry'])

        log_action(
            request, 'SCAN', 'Bundle', bundle_id,
            notes=f"Quality check run: {flagged_count} blurry sheets out of {len(results)}"
        )

        return Response({
            'bundle_id': bundle_id,
            'total_sheets': len(results),
            'flagged_count': flagged_count,
            'results': results,
        })


class AnswerSheetThumbnailView(APIView):
    """
    GET /api/answer-sheets/{pk}/thumbnail/

    Returns a JPEG thumbnail (max 400px wide) of the first page of the
    answer sheet PDF. Used by the review screen thumbnail strip.
    Scanning staff and teachers can view.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        try:
            sheet = AnswerSheet.objects.get(pk=pk)
        except AnswerSheet.DoesNotExist:
            from django.http import Http404
            raise Http404

        # Role check: scanning staff see all; teachers see only assigned
        if request.user.role == 'teacher' and sheet.assigned_teacher != request.user:
            return Response({'error': 'Not authorized.'}, status=status.HTTP_403_FORBIDDEN)

        try:
            from PIL import Image as PILImage
            import fitz  # PyMuPDF — fast PDF renderer

            doc = fitz.open(sheet.pdf_file.path)
            page = doc[0]
            # Render at 1.5x for decent quality thumbnail
            mat = fitz.Matrix(1.5, 1.5)
            pix = page.get_pixmap(matrix=mat)
            img_data = pix.tobytes("jpeg")
            doc.close()
            from django.http import HttpResponse
            return HttpResponse(img_data, content_type='image/jpeg')

        except ImportError:
            # PyMuPDF not available — fall back to Pillow JPEG extraction
            pass
        except Exception:
            pass

        # Pillow fallback — works for image-only PDFs
        try:
            from PIL import Image as PILImage
            with PILImage.open(sheet.pdf_file.path) as img:
                img.thumbnail((400, 600))
                buf = io.BytesIO()
                img.save(buf, format='JPEG', quality=80)
                buf.seek(0)
                from django.http import HttpResponse
                return HttpResponse(buf.read(), content_type='image/jpeg')
        except Exception:
            pass

        # Last resort: return a 1x1 placeholder so the UI doesn't break
        from django.http import HttpResponse
        import base64
        # 1x1 grey JPEG
        placeholder = base64.b64decode(
            '/9j/4AAQSkZJRgABAQEASABIAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8U'
            'HRofHh0aHBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/2wBDAQkJCQwLDBgN'
            'DRgyIRwhMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIy'
            'MjL/wAARCAABAAEDASIAAhEBAxEB/8QAFgABAQEAAAAAAAAAAAAAAAAABgUE/8QAIRAAAg'
            'IBBQEAAAAAAAAAAAAAAQIDBAUREiExUf/EABQBAQAAAAAAAAAAAAAAAAAAAAD/xAAUEQEA'
            'AAAAAAAAAAAAAAAAAAAA/9oADAMBAAIRAxEAPwCwABr3QAAAAASUVORK5CYII='
        )
        return HttpResponse(placeholder, content_type='image/jpeg')


class AnswerSheetReplaceImageView(APIView):
    """
    POST /api/answer-sheets/{pk}/replace-image/

    Scanning staff only. Accepts a new set of page images for a given answer
    sheet, recompiles the PDF, and runs a fresh quality check.

    Body: multipart — { images: File[] }   (one or more pages in order)
    OR:   multipart — { image: File }       (single replacement page 1)

    Response: { sheet_id, token, quality: { is_blurry, score } }
    """
    permission_classes = [IsScanningStaff]
    parser_classes = [MultiPartParser]

    def post(self, request, pk):
        try:
            sheet = AnswerSheet.objects.get(pk=pk)
        except AnswerSheet.DoesNotExist:
            return Response({'error': 'Answer sheet not found.'}, status=status.HTTP_404_NOT_FOUND)

        if sheet.bundle.status == 'submitted':
            return Response({'error': 'Cannot replace images in a submitted bundle.'}, status=status.HTTP_400_BAD_REQUEST)

        # Accept one or more images
        image_files = request.FILES.getlist('images') or (
            [request.FILES['image']] if 'image' in request.FILES else []
        )
        if not image_files:
            return Response({'error': 'No images provided.'}, status=status.HTTP_400_BAD_REQUEST)

        # Save temp files and recompile PDF
        import tempfile, shutil
        temp_dir = tempfile.mkdtemp()
        try:
            temp_paths = []
            for i, f in enumerate(image_files):
                ext = os.path.splitext(f.name)[1] or '.jpg'
                tmp_path = os.path.join(temp_dir, f'page_{i+1:03d}{ext}')
                with open(tmp_path, 'wb') as out:
                    for chunk in f.chunks():
                        out.write(chunk)
                temp_paths.append(tmp_path)

            # Recompile PDF
            pdf_rel_path = sheet.pdf_file.name
            pdf_abs_path = sheet.pdf_file.path
            os.makedirs(os.path.dirname(pdf_abs_path), exist_ok=True)

            compile_images_to_pdf(temp_paths, pdf_abs_path)
            sheet.pdf_version += 1
            sheet.save(update_fields=['pdf_version'])
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

        # Quality check on new PDF
        from utils.blur_detector import check_answer_sheet_quality
        quality = check_answer_sheet_quality(sheet)

        log_action(
            request, 'SCAN', 'AnswerSheet', pk,
            notes=f"Images re-uploaded for token {sheet.token}. New quality score: {quality['score']}"
        )

        return Response({
            'sheet_id': sheet.id,
            'token': sheet.token,
            'thumbnail_url': f'/api/answer-sheets/{sheet.id}/thumbnail/',
            'quality': quality,
        })


class IPWebcamProxyView(APIView):
    """
    GET /api/answer-sheets/ip-webcam-proxy/?url=...
    Proxies requests to local IP webcams to bypass browser CORS and mixed-content issues.
    """
    permission_classes = [] # Allow unauthenticated local proxying to avoid token issues in img src

    def get(self, request):
        url = request.query_params.get('url')
        if not url:
            from rest_framework.response import Response
            from rest_framework import status
            return Response({'error': 'URL is required'}, status=status.HTTP_400_BAD_REQUEST)
            
        try:
            import urllib.request
            req = urllib.request.Request(url)
            response = urllib.request.urlopen(req, timeout=5)
            
            def stream_generator():
                while True:
                    chunk = response.read(8192)
                    if not chunk:
                        break
                    yield chunk
            
            from django.http import StreamingHttpResponse
            return StreamingHttpResponse(
                stream_generator(),
                content_type=response.headers.get('Content-Type', 'image/jpeg')
            )
        except Exception as e:
            from rest_framework.response import Response
            from rest_framework import status
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
