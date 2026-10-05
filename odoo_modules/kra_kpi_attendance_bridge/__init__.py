from . import models
from . import controllers


def post_init_hook(env):
    """On install, give every current KRA user an HR employee so their very
    first Start Workday already reaches attendance."""
    env['res.users']._kra_link_all_employees()
