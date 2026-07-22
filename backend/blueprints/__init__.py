from .accounts import bp as accounts_bp
from .auth_routes import bp as auth_bp
from .coverage import bp as coverage_bp
from .history_links import bp as history_links_bp
from .imports import bp as imports_bp
from .reconciliations import bp as reconciliations_bp
from .reports import bp as reports_bp
from .suggestions import bp as suggestions_bp
from .system import bp as system_bp
from .transactions import bp as transactions_bp

ALL_BLUEPRINTS = (
    auth_bp,
    imports_bp,
    transactions_bp,
    suggestions_bp,
    history_links_bp,
    reconciliations_bp,
    accounts_bp,
    coverage_bp,
    reports_bp,
    system_bp,
)
