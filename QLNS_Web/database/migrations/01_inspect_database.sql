/* QLNS Web - inspect the schema and relational constraints in SSMS */
USE [NHANSU_PY];
GO

-- 1. Tables and approximate row counts.
SELECT
    s.name AS SchemaName,
    t.name AS TableName,
    SUM(p.rows) AS ApproxRows
FROM sys.tables AS t
JOIN sys.schemas AS s ON s.schema_id = t.schema_id
LEFT JOIN sys.partitions AS p ON p.object_id = t.object_id AND p.index_id IN (0, 1)
GROUP BY s.name, t.name
ORDER BY s.name, t.name;
GO

-- 2. Declared foreign keys (parent -> referenced table).
SELECT
    fk.name AS ForeignKeyName,
    OBJECT_SCHEMA_NAME(fk.parent_object_id) AS ChildSchema,
    OBJECT_NAME(fk.parent_object_id) AS ChildTable,
    pc.name AS ChildColumn,
    OBJECT_SCHEMA_NAME(fk.referenced_object_id) AS ParentSchema,
    OBJECT_NAME(fk.referenced_object_id) AS ParentTable,
    rc.name AS ParentColumn,
    fk.is_disabled AS IsDisabled,
    fk.is_not_trusted AS IsNotTrusted
FROM sys.foreign_keys AS fk
JOIN sys.foreign_key_columns AS fkc ON fkc.constraint_object_id = fk.object_id
JOIN sys.columns AS pc ON pc.object_id = fkc.parent_object_id AND pc.column_id = fkc.parent_column_id
JOIN sys.columns AS rc ON rc.object_id = fkc.referenced_object_id AND rc.column_id = fkc.referenced_column_id
ORDER BY ChildTable, ForeignKeyName;
GO

-- 3. Check schema migration status.
IF OBJECT_ID(N'dbo.QlnsSchemaVersion', N'U') IS NOT NULL
    SELECT Version, IsComplete, StartedAt, CompletedAt
    FROM dbo.QlnsSchemaVersion
    ORDER BY StartedAt DESC;
ELSE
    PRINT N'QlnsSchemaVersion is not present. Run the project setup/migration command.';
GO

-- 4. Check the central employee key and the most important business tables.
SELECT
    OBJECT_ID(N'dbo.NhanVien', N'U') AS NhanVienTable,
    OBJECT_ID(N'dbo.TaiKhoan', N'U') AS TaiKhoanTable,
    OBJECT_ID(N'dbo.HopDong', N'U') AS HopDongTable,
    OBJECT_ID(N'dbo.ChamCong', N'U') AS ChamCongTable,
    OBJECT_ID(N'dbo.NghiPhep', N'U') AS NghiPhepTable,
    OBJECT_ID(N'dbo.Luong', N'U') AS LuongTable,
    OBJECT_ID(N'dbo.PhongBan', N'U') AS PhongBanTable,
    OBJECT_ID(N'dbo.ChucVu', N'U') AS ChucVuTable;
GO
