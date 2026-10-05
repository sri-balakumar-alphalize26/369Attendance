from odoo import models, fields, api, _
from datetime import datetime, timedelta
import logging
import pytz

_logger = logging.getLogger(__name__)


class HrAttendanceKraLink(models.Model):
    """The attendance side of the KRA link.

    Kept in this file rather than hr_attendance.py so that every reference to
    `kpi.work.session` lives in one place -- if the bridge is ever lifted out
    into its own addon, this file is the whole of it.
    """

    _inherit = 'hr.attendance'

    kra_session_ids = fields.One2many(
        'kpi.work.session', 'hr_attendance_id',
        string='KRA Workday Sessions', readonly=True,
        help='The KRA/KPI workday sessions that produced this attendance. '
             'Inverse of a Many2one, so it costs no column.',
    )


class KpiWorkSessionAttendanceBridge(models.Model):
    """Start Workday in the KRA board creates the check-in here; End Workday
    writes the check-out.

    `kra_kpi_module` is deliberately NOT modified -- it knows nothing about HR
    and has no `hr.employee` link of its own. This class reaches into its
    `kpi.work.session` model by classic `_inherit` and hooks the two ORM writes
    that matter:

      * create()                 -> Start Workday  -> check in
      * write(state='closed')    -> End Workday    -> check out

    Hooking `write` on the state transition rather than patching
    `action_end_day` means every close path is covered by one piece of code:
    the manual End Workday button, the midnight `_close_overdue` sweep, and the
    idle close, without the bridge having to know any of them exist.

    Every hook is wrapped so a failure here can never roll back the workday
    itself. Somebody must always be able to start their day, whatever HR
    configuration happens to be broken -- the same contract KRA already applies
    to its own WhatsApp and notification side effects.
    """

    _inherit = 'kpi.work.session'

    hr_attendance_id = fields.Many2one(
        'hr.attendance', string='HR Attendance',
        ondelete='set null', readonly=True, copy=False,
        help='The attendance record this workday session checked in to.',
    )

    # ------------------------------------------------------------------ #
    # ORM hooks                                                          #
    # ------------------------------------------------------------------ #
    @api.model_create_multi
    def create(self, vals_list):
        sessions = super().create(vals_list)
        for sess in sessions:
            try:
                # Savepoint, not a bare try/except: if the attendance side fails
                # at the DATABASE level (a constraint, a deadlock) the Postgres
                # transaction is left aborted and every later statement in it
                # fails too -- including KRA's own. Catching the exception would
                # not save the workday; rolling back to here does.
                with self.env.cr.savepoint():
                    sess._kra_sync_checkin()
                    if sess.state == 'closed':
                        # KRA's retro-create cron builds sessions that are
                        # ALREADY closed, for developers who logged time but
                        # never opened the board. write() never sees a
                        # transition for those, so the check-out has to happen
                        # here or the attendance dangles open forever.
                        sess._kra_sync_checkout()
            except Exception as err:
                _logger.exception(
                    "[kra-attendance] check-in sync failed for session %s", sess.id)
                sess._kra_alert_sync_failed(_("Start Workday"), err)
        return sessions

    def write(self, vals):
        # Work out which sessions are closing on THIS write before calling
        # super() -- afterwards every record already reads state == 'closed'
        # and an idempotent re-save would look like a fresh close.
        closing = self.browse()
        if vals.get('state') == 'closed':
            closing = self.filtered(lambda s: s.state != 'closed')

        res = super().write(vals)

        for sess in closing:
            try:
                with self.env.cr.savepoint():
                    sess._kra_sync_checkout()
            except Exception as err:
                _logger.exception(
                    "[kra-attendance] check-out sync failed for session %s", sess.id)
                sess._kra_alert_sync_failed(_("End Workday"), err)
        return res

    # ------------------------------------------------------------------ #
    # Check in                                                           #
    # ------------------------------------------------------------------ #
    def _kra_sync_checkin(self):
        """Adopt or create today's attendance for this session.

        Adopting rather than always creating is what keeps this safe. Two real
        cases would otherwise raise on the developer's screen:

          * an approved WFH check-in already made an OPEN record today -- a
            second open check-in trips the core Odoo overlap constraint;
          * the day was auto-closed or reverted by an admin and the developer
            is starting again -- a second check-in trips
            `_check_no_reentry_same_session` ("you have already checked out of
            Session 1 today") and the Start Workday button breaks.

        Both are handled by reusing the day's existing record: reopened if it
        had already been closed.
        """
        self.ensure_one()
        if self.hr_attendance_id:
            return self.hr_attendance_id

        employee = self._kra_employee()
        if not employee and self.user_id:
            # First workday of someone KRA knows but HR does not: link or
            # create their employee now instead of dropping the day.
            employee = self.user_id._kra_ensure_employee()
        if not employee:
            _logger.warning(
                "[kra-attendance] no hr.employee linked to user %s (%s) -- "
                "workday session %s will not appear in attendance",
                self.user_id.id, self.user_id.login or '', self.id)
            self._kra_alert_no_employee()
            return self.env['hr.attendance'].browse()

        cfg = self.env['hr.attendance.late.config'].get_config_for_employee(employee.id)
        if not cfg.get('kra_workday_creates_attendance', True):
            return self.env['hr.attendance'].browse()

        at = self.login_at or fields.Datetime.now()
        start, end = self._kra_day_window(employee, cfg, at)
        Attendance = self.env['hr.attendance'].sudo()

        existing = Attendance.search([
            ('employee_id', '=', employee.id),
            ('check_in', '>=', start),
            ('check_in', '<', end),
        ], order='check_in desc', limit=1)

        if existing:
            if existing.check_out:
                # Reopen: the developer is back on the clock for a day that had
                # already been closed out (auto-close or admin revert). The
                # original check_in is kept -- it is when they actually arrived,
                # and it is what grades the day.
                existing.with_context(skip_late_reason_required=True).write(
                    {'check_out': False})
            self.sudo().write({'hr_attendance_id': existing.id})
            return existing

        # skip_late_reason_required: an automated check-in must always succeed,
        # whatever the time. Without it a late start raises "Please enter the
        # Late Reason before saving" from _check_late_reason_required -- with no
        # field anywhere to type one into, because this came from a button in a
        # different application. Lateness is still fully recorded; only the
        # blocking validation is skipped. Same trick wfh_request.action_checkin
        # uses, for the same reason.
        attendance = Attendance.with_context(skip_late_reason_required=True).create({
            'employee_id': employee.id,
            'check_in': at,
        })
        self.sudo().write({'hr_attendance_id': attendance.id})
        return attendance

    # ------------------------------------------------------------------ #
    # Check out                                                          #
    # ------------------------------------------------------------------ #
    def _kra_sync_checkout(self):
        """Close the linked attendance at this session's logout time."""
        self.ensure_one()
        attendance = self.hr_attendance_id

        if not attendance:
            # Sessions opened before this module was installed have no link.
            # Fall back to today's still-open record so their first close still
            # lands somewhere sensible.
            attendance = self._kra_find_open_attendance()
            if not attendance:
                return self.env['hr.attendance'].browse()
            self.sudo().write({'hr_attendance_id': attendance.id})

        out = self.logout_at or fields.Datetime.now()

        # Core Odoo requires check_out > check_in. A zero-length workday (start
        # and end in the same second) would otherwise be rejected and left
        # dangling open forever, which is worse than a one-second day.
        if attendance.check_in and out <= attendance.check_in:
            out = attendance.check_in + timedelta(seconds=1)

        # Never shrink an existing check-out: a second session later the same
        # day extends the record, it does not truncate what came before.
        if attendance.check_out and attendance.check_out >= out:
            return attendance

        attendance.sudo().with_context(skip_late_reason_required=True).write(
            {'check_out': out})
        return attendance

    def _kra_find_open_attendance(self):
        """Today's open attendance for this session's employee, if any."""
        self.ensure_one()
        employee = self._kra_employee()
        if not employee:
            return self.env['hr.attendance'].browse()
        cfg = self.env['hr.attendance.late.config'].get_config_for_employee(employee.id)
        at = self.logout_at or self.login_at or fields.Datetime.now()
        start, end = self._kra_day_window(employee, cfg, at)
        return self.env['hr.attendance'].sudo().search([
            ('employee_id', '=', employee.id),
            ('check_in', '>=', start),
            ('check_in', '<', end),
            ('check_out', '=', False),
        ], order='check_in desc', limit=1)

    # ------------------------------------------------------------------ #
    # Helpers                                                            #
    # ------------------------------------------------------------------ #
    def _kra_employee(self):
        """The hr.employee behind this session's res.users.

        KRA models developers as `res.users` and has no HR link of its own, so
        the join happens here. Same lookup wfh_request._compute_hr_employee_id
        already uses.
        """
        self.ensure_one()
        if not self.user_id:
            return self.env['hr.employee'].browse()
        return self.env['hr.employee'].sudo().search(
            [('user_id', '=', self.user_id.id)], limit=1)

    # --- Alerts (hr_attendance_369's notification centre) ----------------
    def _kra_alert_sync_failed(self, action, err):
        """The workday opened (or closed) in KRA but attendance did not follow,
        so the day will grade Absent unless somebody fixes it. Both the
        developer and the admins need to know today, not at payroll."""
        self.ensure_one()
        N = self.env['hr.attendance.notification']
        employee = self._kra_employee()
        company = employee.company_id if employee else self.env.company
        N._notify('emp_kra_sync_failed', self.user_id, _("Workday not recorded"),
                  _("%(action)s did not record your attendance. Check in from the "
                    "attendance app, or ask HR to fix it.", action=action),
                  employee or None, 'Home', include_actor=True)
        N._notify('adm_kra_sync_failed', N._hr_users('admin', company),
                  _("KRA attendance sync failed"),
                  _("%(action)s for %(user)s: %(err)s",
                    action=action, user=self.user_id.name, err=str(err)[:120]))

    def _kra_alert_no_employee(self):
        """Once a day per user: a KRA account with no employee record never
        reaches attendance at all."""
        self.ensure_one()
        N = self.env['hr.attendance.notification']
        if N._once_per_day('kra_no_employee_%s' % self.user_id.id,
                           fields.Date.context_today(self)):
            N._notify('adm_kra_no_employee', N._hr_users('admin', self.user_id.company_id),
                      _("KRA user without employee"),
                      _("%s started a workday but has no employee record, so no "
                        "attendance is recorded. Link the user to an employee.",
                        self.user_id.name))

    def _kra_day_window(self, employee, cfg, moment):
        """UTC bounds of the OFFICE-local day containing `moment`.

        Deliberately not KRA's own `session_date`: that is computed in the
        user's timezone while attendance grades everything in the office
        timezone, and near midnight the two disagree about which day it is.
        `moment` is a naive UTC datetime, the Odoo convention.
        """
        tz_name = cfg.get('timezone') or employee.tz or 'UTC'
        try:
            tz = pytz.timezone(tz_name)
        except Exception:
            tz = pytz.utc
        local_day = pytz.utc.localize(moment).astimezone(tz).date()
        start_local = tz.localize(datetime.combine(local_day, datetime.min.time()))
        start = start_local.astimezone(pytz.utc).replace(tzinfo=None)
        end = (start_local + timedelta(days=1)).astimezone(pytz.utc).replace(tzinfo=None)
        return start, end
