"""SQLite Handler 单元测试"""

import os
import tempfile
import unittest

from openjiuwen_runtime.management.sdk.db.sqlite_handler import SQLiteHandler
from openjiuwen_runtime.management.sdk.models.table_def import (
    TableDefinition,
    ColumnDefinition,
    IndexDefinition,
)


class TestSQLiteHandler(unittest.IsolatedAsyncioTestCase):
    """SQLite Handler 测试类"""

    async def asyncSetUp(self):
        self.db_path = os.path.join(tempfile.gettempdir(), "test_sqlite.db")
        self.handler = SQLiteHandler(self.db_path)
        await self.handler.connect()

        self.test_table_def = TableDefinition(
            table_name="test_table",
            columns=[
                ColumnDefinition("id", "integer", primary_key=True, autoincrement=True),
                ColumnDefinition("name", "string", length=100, nullable=False),
                ColumnDefinition("value", "string", length=255, nullable=True),
            ],
            indexes=[
                IndexDefinition(["name"], unique=True),
            ],
        )

    async def asyncTearDown(self):
        await self.handler.disconnect()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    async def test_connect_disconnect(self):
        """测试连接和断开连接"""
        handler = SQLiteHandler(":memory:")
        await handler.connect()
        self.assertIsNotNone(handler.engine)
        self.assertIsNotNone(handler.session_factory)
        await handler.disconnect()

    async def test_init_table(self):
        """测试初始化表"""
        await self.handler.init_table(self.test_table_def)
        self.assertIn("test_table", self.handler._table_models)

    async def test_create(self):
        """测试创建记录"""
        await self.handler.init_table(self.test_table_def)

        record = await self.handler.create("test_table", {"name": "test_name", "value": "test_value"})

        self.assertIsNotNone(record)
        self.assertEqual(record.name, "test_name")
        self.assertEqual(record.value, "test_value")
        self.assertIsNotNone(record.id)

    async def test_get(self):
        """测试获取记录"""
        await self.handler.init_table(self.test_table_def)

        created = await self.handler.create("test_table", {"name": "get_test", "value": "get_value"})

        record = await self.handler.get("test_table", {"id": created.id})

        self.assertIsNotNone(record)
        self.assertEqual(record.name, "get_test")
        self.assertEqual(record.value, "get_value")

    async def test_update(self):
        """测试更新记录"""
        await self.handler.init_table(self.test_table_def)

        created = await self.handler.create("test_table", {"name": "update_test", "value": "old_value"})

        updated = await self.handler.update(
            "test_table",
            {"id": created.id},
            {"value": "new_value"}
        )

        self.assertIsNotNone(updated)
        self.assertEqual(updated.value, "new_value")

    async def test_delete(self):
        """测试删除记录"""
        await self.handler.init_table(self.test_table_def)

        created = await self.handler.create("test_table", {"name": "delete_test", "value": "delete_value"})

        deleted = await self.handler.delete("test_table", {"id": created.id})
        self.assertTrue(deleted)

        record = await self.handler.get("test_table", {"id": created.id})
        self.assertIsNone(record)

    async def test_list_records(self):
        """测试列表查询"""
        await self.handler.init_table(self.test_table_def)

        await self.handler.create("test_table", {"name": "list_test_1", "value": "value_1"})
        await self.handler.create("test_table", {"name": "list_test_2", "value": "value_2"})
        await self.handler.create("test_table", {"name": "list_test_3", "value": "value_3"})

        records = await self.handler.list_records("test_table", limit=10)

        self.assertEqual(len(records), 3)

        records_limited = await self.handler.list_records("test_table", limit=2)
        self.assertEqual(len(records_limited), 2)

        records_offset = await self.handler.list_records("test_table", limit=2, offset=1)
        self.assertEqual(len(records_offset), 2)
