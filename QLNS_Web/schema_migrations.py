"""Helpers for explicit, out-of-band SQL Server schema upgrades."""

CURRENT_SCHEMA_VERSION = "2026.11.16.2"


def begin_migration(db, version=CURRENT_SCHEMA_VERSION):
    db.execute(
        "IF OBJECT_ID(N'dbo.QlnsSchemaVersion',N'U') IS NULL "
        "CREATE TABLE dbo.QlnsSchemaVersion(Version NVARCHAR(30) NOT NULL PRIMARY KEY, "
        "IsComplete BIT NOT NULL, StartedAt DATETIME2 NOT NULL, CompletedAt DATETIME2 NULL)"
    )
    db.execute(
        "IF EXISTS(SELECT 1 FROM dbo.QlnsSchemaVersion WHERE Version=?) "
        "UPDATE dbo.QlnsSchemaVersion SET IsComplete=0,StartedAt=SYSUTCDATETIME(),CompletedAt=NULL WHERE Version=? "
        "ELSE INSERT INTO dbo.QlnsSchemaVersion(Version,IsComplete,StartedAt) VALUES(?,0,SYSUTCDATETIME())",
        (version, version, version),
    )


def finish_migration(db, version=CURRENT_SCHEMA_VERSION):
    db.execute(
        "UPDATE dbo.QlnsSchemaVersion SET IsComplete=1,CompletedAt=SYSUTCDATETIME() WHERE Version=?",
        (version,),
    )


def grant_web_read(db, principal):
    if not principal:
        return
    quoted_principal = "[" + principal.replace("]", "]]" ) + "]"
    db.execute(
        "DECLARE @principal SYSNAME; SET @principal=?; "
        "IF DATABASE_PRINCIPAL_ID(@principal) IS NULL BEGIN "
        ";THROW 51000, 'DB_WEB_USER is not a database principal in the target database.', 1; END; "
        "GRANT SELECT ON dbo.QlnsSchemaVersion TO " + quoted_principal,
        (principal,),
    )

