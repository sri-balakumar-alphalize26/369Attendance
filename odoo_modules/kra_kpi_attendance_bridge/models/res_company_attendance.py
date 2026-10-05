from odoo import models, fields


class ResCompanyKraAttendance(models.Model):
    """The one switch behind the app's attendance bubble.

    Company-wide, off by default. It lives on res.company beside the other KRA
    app settings (res_company_kpi.py in kra_kpi_module) so the app's
    Configuration screen reads and writes it through the same /kpi_config
    routes as everything else on that screen -- see
    controllers/kra_attendance_api.py.

    Deliberately NOT on hr.attendance.late.config: that record is per company
    or per department and governs how days are graded. Whether the app shows
    the result is a different question, and one answer for the whole company
    is what an admin expects from a single toggle.
    """

    _inherit = 'res.company'

    kra_attendance_in_app = fields.Boolean(
        string='Show Attendance in the KRA App',
        default=False,
        help='When on, developers and admins get a floating Attendance button '
             'on the app\'s Home screen: each person sees their own HR '
             'attendance, admins also see the team for a day. Clients never '
             'see it. Off by default.',
    )

    kra_auto_create_employee = fields.Boolean(
        string='KRA Users Get an Employee Automatically',
        default=True,
        help='Attendance is kept per employee, KRA per user. When on, a KRA '
             'user without an employee is linked to one on install and on '
             'their first Start Workday: an unlinked employee with the same '
             'work email, or a new one. Turn off to link people by hand.',
    )
