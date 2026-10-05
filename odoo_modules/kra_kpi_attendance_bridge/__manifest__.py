{
    'name': 'KRA/KPI Workday -> Attendance Bridge',
    'version': '19.0.3.2.0',
    'category': 'Human Resources/Attendance',
    'summary': 'Starting a KRA/KPI workday records an HR attendance check-in, '
               'and ending it writes the check-out',
    'description': """
        KRA/KPI Workday to Attendance Bridge
        ====================================

        Links two applications that otherwise know nothing about each other:

        - **kra_kpi_module** tracks a developer's workday in `kpi.work.session`,
          keyed on `res.users`. It has no HR dependency and no `hr.employee`
          link of its own.
        - **hr_attendance_369** owns real HR attendance on `hr.attendance`,
          keyed on `hr.employee`, with late tracking, the day-status ladder and
          deductions.

        This module is the join. Pressing **Start Workday** in the KRA board
        creates the attendance check-in; **End Workday** writes the check-out.
        Everything that grades the day afterwards (late window, half day,
        absent stamp, deductions) lives in hr_attendance_369 and is not
        duplicated here.

        Deliberately a separate addon so that neither parent has to depend on
        the other: hr_attendance_369 installs standalone for an HR-only
        database, and kra_kpi_module is never modified at all. `auto_install`
        means Odoo adds this bridge by itself once both parents are present, so
        there is nothing to remember at install time.

        **Employees for KRA users.** Attendance is kept per hr.employee, KRA
        per res.users. On install, upgrade and every Start Workday the bridge
        links each KRA user to an employee: an unlinked one with the same work
        email, or a new one. Turn it off with the company field "KRA Users Get
        an Employee Automatically" to link people by hand.

        Nothing else needs configuring, but the bridge can be switched off per
        company or department with "KRA Workday Creates Attendance" on the
        Office Hours configuration in hr_attendance_369.

        With both parents present the bridge also adds a fourth KRA/KPI role,
        **HR**, beside Admin / User / Client -- in the backend Users form and
        in the KRA app's Login Management. Picking it makes the person the
        attendance HR: they approve leave and WFH and manage compensatory
        offs, and hold no KRA role group.

        **Attendance in the app.** The KRA app's Configuration screen gains an
        "Attendance" card with one switch, "Show attendance in the app"
        (company-wide, off by default). When on, developers and admins get a
        floating Attendance button on Home that opens their own HR attendance
        -- today, this week, the month's counts and a day-by-day history --
        and admins/HR also see the whole team for any day. Read-only: the
        check-in and check-out still come from Start/End Workday. Clients
        never see it. Routes: /kpi_attendance/status, /mine, /team.
    """,
    'author': 'Alphalize Technologies',
    'depends': ['hr_attendance_369', 'kra_kpi_module'],
    'external_dependencies': {
        'python': ['pytz'],
    },
    'data': [
        'views/hr_attendance_bridge_views.xml',
    ],
    'installable': True,
    'application': False,
    # Installs itself as soon as BOTH parents are installed, and stays out of
    # the way on databases that only have one of them.
    'auto_install': True,
    'post_init_hook': 'post_init_hook',
    'license': 'LGPL-3',
}
