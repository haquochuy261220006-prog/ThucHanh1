/*
  QLNS Web - SQL Server database bootstrap
  Run in SSMS while connected to the intended SQL Server instance.
  This script only creates the database when it does not exist.
  It does NOT drop, recreate, or clear an existing database.
*/
USE [master];
GO
IF DB_ID(N'NHANSU_PY') IS NULL
BEGIN
    CREATE DATABASE [NHANSU_PY];
    PRINT N'Database NHANSU_PY created.';
END
ELSE
BEGIN
    PRINT N'Database NHANSU_PY already exists; it was left unchanged.';
END;
GO

