# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026-2026. All rights reserved

import os
import unittest
from unittest import mock

from runtime_support import runtime_env_prepare


class TestRuntimeEnvPrepareGaussDB(unittest.TestCase):
    def setUp(self):
        self._original_env = os.environ.copy()

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._original_env)

    def test_apply_defaults_sets_5432_for_gaussdb(self):
        with mock.patch.dict(os.environ, {"DB_TYPE": "gaussdb"}, clear=True):
            runtime_env_prepare.apply_runtime_type_and_optional_defaults()
            self.assertEqual(os.environ["DB_PORT"], "5432")

    def test_collect_db_missing_accepts_gaussdb_with_required_fields(self):
        env = {
            "DB_TYPE": "gaussdb",
            "DB_HOST": "127.0.0.1",
            "DB_PORT": "5432",
            "DB_USER": "gauss_user",
            "DB_PASSWORD": "secret",
            "OPS_DB_NAME": "ops_db",
            "AGENT_DB_NAME": "agent_db",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            missing = []
            runtime_env_prepare._collect_db_missing(missing)
            self.assertEqual(missing, [])

    def test_collect_db_missing_rejects_invalid_db_type(self):
        with mock.patch.dict(os.environ, {"DB_TYPE": "postgres"}, clear=True):
            missing = []
            runtime_env_prepare._collect_db_missing(missing)

        self.assertEqual(len(missing), 1)
        self.assertIn("DB_TYPE 非法", missing[0])
        self.assertIn("gaussdb", missing[0])
        self.assertIn("opengauss", missing[0])
