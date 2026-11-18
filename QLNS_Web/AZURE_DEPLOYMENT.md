# Deploy QLNS Web to Azure

This project can run as a Linux Flask app in Azure App Service and use Azure SQL Database. Keep the web app and database in the same Azure region. This guide prepares deployment; it does not create Azure resources or migrate production data.

## 1. Prepare a database copy

Create a separate staging database first and migrate a backup/copy of `NHANSU_PY` into it. Do not point staging at the live local database. Check SQL Server to Azure SQL compatibility and run the application's first-request schema setup against the staging copy before moving real users. Do not run `setup_db.py` against an existing production database: it creates a database and sample admin account.

Keep Azure SQL inaccessible from the public internet where possible. Prefer a private endpoint and App Service VNet integration. If using a public endpoint temporarily, allow only the web app's outbound IPs and a known administrator IP; do not enable the broad “Allow Azure services” rule. Azure SQL denies connections by default and supports private network access: <https://learn.microsoft.com/en-us/azure/azure-sql/database/network-access-controls-overview?view=azuresql>.

## 2. Create the web app

Create an **Azure App Service for Linux using a custom container**. The container installs Python 3.12, Tesseract with Vietnamese/English OCR data, and Microsoft ODBC Driver 18; the standard code-based App Service runtime does not install this project's Tesseract system binary. Select the smallest paid App Service plan that supports the availability and networking features you need; check current Azure pricing before creating it. Use a region close to the database and employees.

Build and push the image to Azure Container Registry (or another private container registry):

```text
docker build -t <registry>.azurecr.io/qlns-web:<tag> .
docker push <registry>.azurecr.io/qlns-web:<tag>
```

Configure the App Service container to use that image, set `WEBSITES_PORT` to `8000`, and enable managed identity/registry access to the private image. The image starts Gunicorn using the `CMD` in `Dockerfile`. `requirements-azure.txt` adds Gunicorn without breaking local Windows installs. The image installs ODBC Driver 18 using Microsoft's official Debian instructions:

- ODBC Driver 18 Linux installation: <https://learn.microsoft.com/en-us/sql/connect/odbc/linux/installing-the-microsoft-odbc-driver-for-sql-server-on-linux>

## 3. Set App Service application settings

Add these in **App Service → Settings → Environment variables**. Values shown in angle brackets are placeholders; enter real values in Azure's settings UI or Key Vault, never in source code.

| Setting | Value |
| --- | --- |
| `APP_ENV` | `production` |
| `FLASK_SECRET_KEY` | Long random secret, at least 32 random bytes |
| `DB_SERVER` | `<server>.database.windows.net,1433` |
| `DB_NAME` | The migrated database name |
| `DB_DRIVER` | `ODBC Driver 18 for SQL Server` |
| `DB_WINDOWS_AUTH` | `false` |
| `DB_USER` | Dedicated least-privilege SQL login |
| `DB_PASSWORD` | Secret for that SQL login |
| `DB_WEB_USER` | Database principal mapped to the web login; grant it only the application permissions plus SELECT on `dbo.QlnsSchemaVersion` |
| `DB_ENCRYPT` | `yes` |
| `DB_TRUST_SERVER_CERTIFICATE` | `no` |
| `FACE_ENCRYPTION_KEY` | Fernet key; back it up securely and keep it unchanged |
| `WEBSITES_PORT` | `8000` |

Set only the integrations you use, such as `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`, `AI_PROVIDER`, and the corresponding AI key. Use Key Vault references for production secrets if available. Azure SQL App Service Linux commonly includes ODBC Driver 17 and 18; this project now reads the driver and connection options from environment settings.

Do not add migration credentials to App Service. Stop the web app, then from a protected one-off runner connect to the staging database using `DB_MIGRATION_USER`/`DB_MIGRATION_PASSWORD`, and set `DB_WEB_USER` to the existing database principal for the app. Run `python migrate_db.py`, then restart the web app. The migration identity needs the DDL/data-update permissions used by the upgrade; the web identity must not have schema-alteration permissions. The app returns HTTP 503 until the required schema version is marked complete. Follow [INTEGRATION_TEST_PLAN.md](INTEGRATION_TEST_PLAN.md) against staging before production.

Provision distinct database principals before migration. Give the web principal only the data roles required by the app and the schema-marker read grant; remove DDL/admin memberships if present. For a database principal that has already been created, the SQL Server/Azure SQL operator can apply this in the target database after replacing the placeholder:

```sql
IF IS_ROLEMEMBER(N'db_owner', N'qlns_web_user') = 1
    ALTER ROLE db_owner DROP MEMBER [qlns_web_user];
IF IS_ROLEMEMBER(N'db_ddladmin', N'qlns_web_user') = 1
    ALTER ROLE db_ddladmin DROP MEMBER [qlns_web_user];
IF IS_ROLEMEMBER(N'db_datareader', N'qlns_web_user') = 0
    ALTER ROLE db_datareader ADD MEMBER [qlns_web_user];
IF IS_ROLEMEMBER(N'db_datawriter', N'qlns_web_user') = 0
    ALTER ROLE db_datawriter ADD MEMBER [qlns_web_user];
GRANT SELECT ON dbo.QlnsSchemaVersion TO [qlns_web_user];
```

Review existing explicit grants and database/server roles too; this snippet only removes two common role memberships. The migration identity remains separate and is never configured in App Service.

See Microsoft's [GRANT object permissions](https://learn.microsoft.com/en-us/sql/t-sql/statements/grant-object-permissions-transact-sql?view=sql-server-ver16) documentation for principal/object permission syntax.

Create a Fernet key with `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`. Treat it as backup-critical: losing/changing it makes encrypted face templates unreadable. Existing plaintext face templates must be handled with the migration plan in `README.md`; do not expect old templates to work after enabling encryption.

## 4. HTTPS, domain, and verification

Turn on **HTTPS Only** in App Service. The project sets secure session cookies when `APP_ENV=production`; browser face-camera access also needs HTTPS. Add a custom domain only after DNS is ready, then configure its managed TLS certificate.

Before inviting users, verify a staging copy end-to-end: sign in and roles, SQL writes, employee document upload/download, OTP email, payroll, report exports, face consent/enrollment, and camera attendance from a phone. Confirm database backups and restore procedure. Keep the local copy untouched until the online database has been validated and backed up.

For the operational backup policy, Azure SQL point-in-time restore/long-term retention setup, and a quarterly restore drill, follow [BACKUP_RESTORE.md](BACKUP_RESTORE.md). Azure SQL manages database backups; do not run the SQL Server `.bak` script against Azure SQL Database.

## 5. Cutover and rollback

Schedule a short maintenance window. Take a final SQL Server backup, migrate the final changes, set the App Service database settings to the production database, and run smoke checks before sharing the URL. Keep the previous server/database read-only for rollback until the new deployment is stable. Do not allow local and online apps to write to separate copies after cutover; they will diverge.
