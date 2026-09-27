"""Errors that mean something about the request, mapped to HTTP statuses in one place (main.py).

Services raise these; routers don't translate them. Anything else escaping a
generation route is the model's side failing (502, see rhizomes.router).
"""


class QivisError(Exception):
    status_code = 500


class NotFoundError(QivisError):
    status_code = 404


class InvalidRequestError(QivisError):
    status_code = 400


class NotConfiguredError(QivisError):
    status_code = 503
