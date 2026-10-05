import logging

from odoo import api, models, fields

_logger = logging.getLogger(__name__)

# The groups that make somebody "the HR person" in the attendance app: they
# approve leave and WFH, manage compensatory offs and see the admin Config
# tab. hr.group_hr_manager is deliberately NOT here -- that is full backend
# HR administration, a decision for the Odoo admin, not for a role dropdown.
HR_ROLE_GROUP_XMLIDS = (
    'hr.group_hr_user',
    'hr_attendance_369.group_leave_manager',
    'hr_attendance_369.group_wfh_manager',
)

# KRA's own role groups, the ones its dropdown moves people between.
KRA_ROLE_GROUP_XMLIDS = (
    'kra_kpi_module.group_kra_owner',
    'kra_kpi_module.group_kra_admin',
    'kra_kpi_module.group_kra_developer',
    'kra_kpi_module.group_kra_client',
)


class ResUsersHrRole(models.Model):
    """A fourth KRA/KPI role: HR.

    KRA's Login Management knows Admin, User and Client. With the attendance
    suite in the same database somebody has to be the HR person, and this
    bridge is the one module that knows about both sides -- so it is where the
    role belongs. `selection_add` slots HR into the SAME dropdown, in the
    backend Users form and list, and the controller override in
    controllers/kra_role_bridge.py serves it to the KRA app's screen.

    Picking HR moves the user out of every KRA role group (they become an
    ordinary app user there) and into the attendance HR groups; picking any
    KRA role strips the HR groups again. One dropdown, exclusive roles, the
    same contract the original three have.
    """

    _inherit = 'res.users'

    kpi_role = fields.Selection(selection_add=[('hr', 'HR')])

    def _hr_role_groups(self):
        groups = self.env['res.groups']
        for xmlid in HR_ROLE_GROUP_XMLIDS:
            grp = self.env.ref(xmlid, raise_if_not_found=False)
            if grp:
                groups |= grp
        return groups

    def _kra_role_groups(self):
        groups = self.env['res.groups']
        for xmlid in KRA_ROLE_GROUP_XMLIDS:
            grp = self.env.ref(xmlid, raise_if_not_found=False)
            if grp:
                groups |= grp
        return groups

    def _is_hr_role(self):
        self.ensure_one()
        return (self.has_group('hr.group_hr_user')
                or self.has_group('hr.group_hr_manager'))

    @api.depends('group_ids', 'all_group_ids')
    def _compute_kpi_role(self):
        super()._compute_kpi_role()
        for u in self:
            # Admin outranks HR: a system or KRA owner account stays Admin
            # even when it also carries HR groups. HR outranks the
            # developer/client fallbacks, which is what makes the role
            # visible at all.
            if u.kpi_role != 'admin' and u._is_hr_role():
                u.kpi_role = 'hr'

    def _inverse_kpi_role(self):
        hr_users = self.filtered(lambda u: u.kpi_role == 'hr')
        others = self - hr_users

        for u in hr_users:
            if u.has_group('base.group_system'):
                continue  # same guard as KRA: never re-role the super-admin
            cmds = [(3, g.id) for g in u._kra_role_groups()]
            cmds += [(4, g.id) for g in u._hr_role_groups()]
            u.sudo().write({'group_ids': cmds})

        if others:
            # Moving to a KRA role means leaving HR: strip the HR groups
            # first, then let KRA's own inverse move them between its groups.
            for u in others:
                if u.has_group('base.group_system'):
                    continue
                hr_groups = u._hr_role_groups()
                if any(u.has_group(x) for x in HR_ROLE_GROUP_XMLIDS):
                    u.sudo().write({'group_ids': [(3, g.id) for g in hr_groups]})
            super(ResUsersHrRole, others)._inverse_kpi_role()

    # ------------------------------------------------------------------ #
    # Employee link                                                      #
    # ------------------------------------------------------------------ #
    # KRA models people as res.users; attendance needs an hr.employee. A KRA
    # user with no employee starts a workday and nothing reaches attendance.
    # These two methods close that gap from the bridge, so neither parent
    # module has to change.

    def _kra_ensure_employee(self):
        """The hr.employee behind this user, linked or created if missing.

        Order: an employee already pointing at the user; else an unlinked
        employee in the user's company whose work email is the user's email
        or login (HR set them up by hand but never linked them); else a new
        employee, built the way Odoo's own "Create Employee" button does it.
        Empty for portal or archived users, and when the company switch
        "KRA Users Get an Employee Automatically" is off.
        """
        self.ensure_one()
        Employee = self.env['hr.employee'].sudo()
        user = self.sudo()
        found = Employee.search([('user_id', '=', user.id)], limit=1)
        if found or not user.active or user.share:
            return found
        company = user.company_id
        if not company.kra_auto_create_employee:
            return Employee.browse()

        emails = {e.strip().lower() for e in (user.email, user.login) if e and '@' in e}
        if emails:
            for emp in Employee.search([('user_id', '=', False),
                                        ('company_id', '=', company.id),
                                        ('work_email', '!=', False)]):
                if emp.work_email.strip().lower() in emails:
                    emp.write({'user_id': user.id})
                    _logger.info("[kra-attendance] linked user %s to employee %s by email",
                                 user.login, emp.id)
                    return emp

        emp = Employee.with_company(company).create(dict(
            name=user.name or user.login,
            company_id=company.id,
            **Employee._sync_user(user),
        ))
        _logger.info("[kra-attendance] created employee %s for KRA user %s",
                     emp.id, user.login)
        return emp

    @api.model
    def _kra_link_all_employees(self):
        """Give every current KRA user an employee. Runs on install and upgrade.

        The roster is everyone in the KRA developer group, directly or through
        admin/owner (which imply it), minus KRA clients: they log in to read
        reports, never to start a workday. One bad record is logged and
        skipped so the rest still get linked.
        """
        grp = self.env.ref('kra_kpi_module.group_kra_developer', raise_if_not_found=False)
        if not grp:
            return 0
        Kpi = self.env['kra.kpi'].sudo()
        done = 0
        for user in grp.sudo().all_user_ids:
            if not user.active or user.share:
                continue
            if (user.has_group('kra_kpi_module.group_kra_client')
                    and not Kpi._user_is_kpi_admin(user)):
                continue
            try:
                with self.env.cr.savepoint():
                    if user._kra_ensure_employee():
                        done += 1
            except Exception:
                _logger.exception("[kra-attendance] could not link user %s to an employee",
                                  user.login)
        _logger.info("[kra-attendance] %s KRA users have an employee", done)
        return done
