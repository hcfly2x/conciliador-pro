from flask import Blueprint, jsonify

bp = Blueprint("imports", __name__)


@bp.route("/api/v1/import/scan-folder", methods=["POST"])
def import_scan_folder():
    return jsonify(
        {
            "detail": "Importacao automatica por pasta foi descontinuada.",
            "code": "FOLDER_IMPORT_DISABLED",
        }
    ), 410
