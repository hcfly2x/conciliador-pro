from flask import Blueprint, jsonify

bp = Blueprint("transactions", __name__)


def _application():
    from core import application

    return application


@bp.route("/api/v1/transactions/months")
def months():
    with _application().db_connect() as conn:
        rows = conn.execute(
            "SELECT DISTINCT competence_month FROM transactions ORDER BY competence_month DESC"
        ).fetchall()
    return jsonify([row[0] for row in rows])
