"""
pdf_worker.py
-------------
Lightweight background PDF annotation worker using ThreadPoolExecutor.

Architecture:
  - Django views call submit_pdf_task(evaluation_id) to queue work.
  - A singleton ThreadPoolExecutor (max 2 workers) processes tasks.
  - Each worker: loads the EvaluationResult, runs annotate_pdf(), updates status.
  - Row-level DB locks (select_for_update) prevent duplicate processing.
  - On Django startup, recover_pending_tasks() requeues interrupted work.

Celery migration path:
  - process_pdf_task() is a plain function taking a single int ID.
  - To migrate: decorate with @shared_task, replace submit_pdf_task() call.
"""

import hashlib
import logging
import os
import threading
from concurrent.futures import ThreadPoolExecutor

from django.conf import settings

logger = logging.getLogger('examflow.pdf_worker')

# ── Singleton executor ──────────────────────────────────────────────────────

_executor = None
_lock = threading.Lock()


def get_executor():
    """Lazy-initialise a singleton ThreadPoolExecutor."""
    global _executor
    if _executor is None:
        with _lock:
            if _executor is None:
                _executor = ThreadPoolExecutor(
                    max_workers=2,
                    thread_name_prefix='pdf-worker',
                )
                logger.info('PDF worker pool started (max_workers=2).')
    return _executor


def submit_pdf_task(evaluation_id: int):
    """
    Submit a PDF generation task to the background pool.
    Safe to call multiple times for the same ID — the worker will skip
    if the evaluation is already processing or completed.
    """
    get_executor().submit(_safe_process, evaluation_id)
    logger.info(f'PDF task submitted for evaluation {evaluation_id}.')


# ── Worker implementation ───────────────────────────────────────────────────

def _safe_process(evaluation_id: int):
    """Wrapper that catches all exceptions so the thread pool stays healthy."""
    try:
        process_pdf_task(evaluation_id)
    except Exception:
        logger.exception(f'PDF task crashed for evaluation {evaluation_id}.')
        # Try to mark as failed even if process_pdf_task didn't
        try:
            from .models import EvaluationResult
            EvaluationResult.objects.filter(pk=evaluation_id).update(
                pdf_status='failed',
                pdf_error='Unexpected worker crash. Check server logs.',
            )
        except Exception:
            pass
    finally:
        # Close the DB connection used by this thread so it doesn't leak.
        from django.db import connection
        connection.close()


def process_pdf_task(evaluation_id: int):
    """
    The actual PDF processing function.

    This signature is Celery-compatible: takes a single int ID,
    does all DB lookups internally, has no request context dependency.
    """
    from django.db import transaction
    from .models import EvaluationResult
    from .pdf_annotator import annotate_pdf

    # ── 1. Claim the task atomically ────────────────────────────────────────
    with transaction.atomic():
        try:
            result = (
                EvaluationResult.objects
                .select_for_update(skip_locked=True)
                .get(pk=evaluation_id)
            )
        except EvaluationResult.DoesNotExist:
            logger.warning(f'Evaluation {evaluation_id} not found. Skipping.')
            return

        # Only process if status is 'pending'
        if result.pdf_status not in ('pending',):
            logger.info(
                f'Evaluation {evaluation_id} status is "{result.pdf_status}". '
                f'Skipping (already claimed or completed).'
            )
            return

        # Mark as processing
        result.pdf_status = 'processing'
        result.pdf_error = ''
        result.save(update_fields=['pdf_status', 'pdf_error'])

    # ── 2. Load related data (outside the lock) ────────────────────────────
    # Re-fetch without lock to get full data
    result = (
        EvaluationResult.objects
        .select_related('answer_sheet', 'answer_sheet__bundle')
        .get(pk=evaluation_id)
    )

    sheet = result.answer_sheet
    mark_positions = result.mark_positions or []

    if not mark_positions:
        # Nothing to annotate
        result.pdf_status = 'skipped'
        result.save(update_fields=['pdf_status'])
        logger.info(f'Evaluation {evaluation_id}: no mark positions, skipped.')
        return

    # ── 3. Run annotate_pdf ─────────────────────────────────────────────────
    try:
        original_pdf_path = sheet.pdf_file.path
        output_pdf_path = os.path.join(
            settings.MEDIA_ROOT, 'answer_sheets',
            str(sheet.bundle_id), f'{sheet.token}_v2_marked.pdf',
        )

        logger.info(
            f'Evaluation {evaluation_id}: generating marked PDF '
            f'({len(mark_positions)} badges)...'
        )

        pdf_hash = annotate_pdf(
            original_pdf_path=original_pdf_path,
            mark_positions=mark_positions,
            output_pdf_path=output_pdf_path,
        )

        marked_pdf_rel = os.path.relpath(output_pdf_path, settings.MEDIA_ROOT)

        # ── 4. Update result ────────────────────────────────────────────────
        result.marked_pdf_path = marked_pdf_rel
        result.pdf_status = 'completed'
        result.pdf_error = ''
        result.save(update_fields=['marked_pdf_path', 'pdf_status', 'pdf_error'])

        logger.info(
            f'Evaluation {evaluation_id}: marked PDF complete. '
            f'Hash: {pdf_hash[:16]}...'
        )

        # ── 5. Record hash in audit log ─────────────────────────────────────
        try:
            from apps.audit.models import AuditLog
            AuditLog.objects.filter(
                action_type='GRADE',
                target_model='EvaluationResult',
                target_id=str(evaluation_id),
            ).order_by('-performed_at').update(
                # Append hash to existing new_value JSON if possible
            )
            # Simpler: just log a new entry
            AuditLog.objects.create(
                performed_by=result.teacher,
                action_type='PDF_GENERATED',
                target_model='EvaluationResult',
                target_id=str(evaluation_id),
                new_value={
                    'pdf_sha256': pdf_hash,
                    'marked_pdf_path': marked_pdf_rel,
                    'badge_count': len(mark_positions),
                },
                notes=f'Background PDF generated for evaluation {evaluation_id}.',
            )
        except Exception as exc:
            # Audit log failure should never block the main task
            logger.warning(f'Audit log write failed for eval {evaluation_id}: {exc}')

    except FileNotFoundError as exc:
        result.pdf_status = 'failed'
        result.pdf_error = f'Original PDF not found: {exc}'
        result.save(update_fields=['pdf_status', 'pdf_error'])
        logger.error(f'Evaluation {evaluation_id}: {result.pdf_error}')

    except Exception as exc:
        result.pdf_status = 'failed'
        result.pdf_error = str(exc)[:500]
        result.save(update_fields=['pdf_status', 'pdf_error'])
        logger.exception(f'Evaluation {evaluation_id}: PDF generation failed.')


# ── Crash recovery ──────────────────────────────────────────────────────────

def recover_pending_tasks():
    """
    Called on Django startup.
    Resets any 'processing' records (server crashed mid-generation) to 'pending',
    then requeues all 'pending' tasks.
    """
    import time
    # Small delay to let Django fully initialise
    time.sleep(2)

    try:
        from .models import EvaluationResult

        # Reset stuck 'processing' records
        stuck_count = EvaluationResult.objects.filter(
            pdf_status='processing',
        ).update(pdf_status='pending', pdf_error='')

        if stuck_count:
            logger.warning(
                f'Recovery: reset {stuck_count} stuck "processing" tasks to "pending".'
            )

        # Requeue all pending
        pending_ids = list(
            EvaluationResult.objects.filter(
                pdf_status='pending',
            ).values_list('pk', flat=True)
        )

        if pending_ids:
            logger.info(f'Recovery: requeuing {len(pending_ids)} pending PDF tasks.')
            for eval_id in pending_ids:
                submit_pdf_task(eval_id)
        else:
            logger.info('Recovery: no pending PDF tasks found.')

    except Exception:
        logger.exception('PDF worker recovery failed.')
