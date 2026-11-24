"""Shared HTTP and unexpected-error responses."""

from flask import jsonify, render_template, request
from werkzeug.exceptions import HTTPException


def register_error_handlers(app):
    @app.errorhandler(HTTPException)
    def handle_http_error(error):
        status = error.code or 500
        message = error.description or "Y\u00eau c\u1ea7u kh\u00f4ng th\u1ec3 x\u1eed l\u00fd."
        if request.path.startswith("/api/"):
            return jsonify(ok=False, error=message), status
        return render_template("error.html", status=status, message=message), status

    @app.errorhandler(Exception)
    def handle_unexpected_error(error):
        app.logger.exception("Unhandled request error")
        status = 500
        message = "\u0110\u00e3 x\u1ea3y ra l\u1ed7i h\u1ec7 th\u1ed1ng. Vui l\u00f2ng th\u1eed l\u1ea1i sau."
        if request.path.startswith("/api/"):
            return jsonify(ok=False, error=message), status
        return render_template("error.html", status=status, message=message), status
