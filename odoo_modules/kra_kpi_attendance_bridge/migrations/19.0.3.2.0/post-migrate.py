from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    """Upgrading from a bridge that never linked employees: connect the KRA
    users who already exist, the same as a fresh install does."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    env['res.users']._kra_link_all_employees()
