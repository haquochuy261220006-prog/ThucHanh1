"""Database package.

Keep package initialization empty so commands such as ``database.migrate_db``
can select their database credentials before importing the connection module.
``from database import db`` still loads the ``database.db`` submodule lazily.
"""
