import sys
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock, mock_open

sys.path.insert(0, str(Path(__file__).parent.parent))

import preflight


class TestCheckVenv(unittest.TestCase):

    def test_missing_venv_exits_with_code_1(self):
        with patch.object(preflight, "VENV_DIR", Path("/fake/.venv")):
            with patch.object(Path, "exists", return_value=False):
                with self.assertRaises(SystemExit) as cm:
                    preflight.check_venv()
                self.assertEqual(cm.exception.code, 1)

    def test_missing_venv_error_message(self):
        with patch.object(preflight, "VENV_DIR", Path("/fake/.venv")):
            with patch.object(Path, "exists", return_value=False):
                with patch("sys.stdout") as mock_stdout:
                    try:
                        preflight.check_venv()
                    except SystemExit:
                        pass
                output = mock_stdout.write.call_args_list[0][0][0]
                self.assertIn("PREFLIGHT_VENV_MISSING", output)

    def test_venv_exists_passes(self):
        with patch.object(preflight, "VENV_DIR", Path("/fake/.venv")):
            with patch.object(Path, "exists", return_value=True):
                result = preflight.check_venv()
                self.assertTrue(result)


class TestCheckWb(unittest.TestCase):

    def test_wb_not_found_exits_with_code_1(self):
        with patch.object(preflight, "WB_PATH", Path("/fake/.venv/bin/wb")):
            with patch.object(preflight, "VENV_DIR", Path("/fake/.venv")):
                with patch.object(Path, "exists", return_value=False):
                    with patch("shutil.which", return_value=None):
                        with self.assertRaises(SystemExit) as cm:
                            preflight.check_wb()
                        self.assertEqual(cm.exception.code, 1)

    def test_wb_not_found_error_message(self):
        with patch.object(preflight, "WB_PATH", Path("/fake/.venv/bin/wb")):
            with patch.object(preflight, "VENV_DIR", Path("/fake/.venv")):
                with patch.object(Path, "exists", return_value=False):
                    with patch("shutil.which", return_value=None):
                        with patch("sys.stdout") as mock_stdout:
                            try:
                                preflight.check_wb()
                            except SystemExit:
                                pass
                        output = mock_stdout.write.call_args_list[0][0][0]
                        self.assertIn("PREFLIGHT_WB_NOT_FOUND", output)

    def test_wb_on_path_passes(self):
        with patch("shutil.which", return_value="/usr/bin/wb"):
            result = preflight.check_wb()
            self.assertTrue(result)


class TestCheckDomainContext(unittest.TestCase):

    def test_config_missing_exits_with_code_1(self):
        with patch.object(preflight, "DOMAIN_CONTEXT_PATH", Path("/fake/config.yaml")):
            with patch.object(Path, "exists", return_value=False):
                with patch("sys.stdout") as mock_stdout:
                    with self.assertRaises(SystemExit) as cm:
                        preflight.check_domain_context()
                    self.assertEqual(cm.exception.code, 1)
                output = mock_stdout.write.call_args_list[0][0][0]
                self.assertIn("PREFLIGHT_CONFIG_MISSING", output)

    def test_config_empty_exits_with_code_1(self):
        with patch.object(preflight, "DOMAIN_CONTEXT_PATH", Path("/fake/config.yaml")):
            with patch.object(Path, "exists", return_value=True):
                with patch("builtins.open", mock_open(read_data="")):
                    with patch("sys.stdout") as mock_stdout:
                        with self.assertRaises(SystemExit) as cm:
                            preflight.check_domain_context()
                        self.assertEqual(cm.exception.code, 1)
                    output = mock_stdout.write.call_args_list[0][0][0]
                    self.assertIn("PREFLIGHT_CONFIG_EMPTY", output)

    def test_domain_empty_exits_with_code_1(self):
        with patch.object(preflight, "DOMAIN_CONTEXT_PATH", Path("/fake/config.yaml")):
            with patch.object(Path, "exists", return_value=True):
                with patch("builtins.open", mock_open(read_data="domain: ''")):
                    with patch("sys.stdout") as mock_stdout:
                        with self.assertRaises(SystemExit) as cm:
                            preflight.check_domain_context()
                        self.assertEqual(cm.exception.code, 1)
                    output = mock_stdout.write.call_args_list[0][0][0]
                    self.assertIn("PREFLIGHT_DOMAIN_EMPTY", output)

    def test_year_scope_empty_exits_with_code_1(self):
        with patch.object(preflight, "DOMAIN_CONTEXT_PATH", Path("/fake/config.yaml")):
            with patch.object(Path, "exists", return_value=True):
                with patch("builtins.open", mock_open(read_data="domain: myapp\nyear_scope:\n  active: []")):
                    with self.assertRaises(SystemExit) as cm:
                        preflight.check_domain_context()
                    self.assertEqual(cm.exception.code, 1)

    def test_vocabulary_empty_exits_with_code_1(self):
        with patch.object(preflight, "DOMAIN_CONTEXT_PATH", Path("/fake/config.yaml")):
            with patch.object(Path, "exists", return_value=True):
                with patch("builtins.open", mock_open(read_data="domain: myapp\nyear_scope:\n  active: [2024]\nvocabulary:\n  operational: []\n  reference: []")):
                    with self.assertRaises(SystemExit) as cm:
                        preflight.check_domain_context()
                    self.assertEqual(cm.exception.code, 1)

    def test_all_valid_passes(self):
        with patch.object(preflight, "DOMAIN_CONTEXT_PATH", Path("/fake/config.yaml")):
            with patch.object(Path, "exists", return_value=True):
                with patch("builtins.open", mock_open(read_data="domain: myapp\nyear_scope:\n  active: [2024]\nvocabulary:\n  operational:\n    - order\n    - invoice")):
                    result = preflight.check_domain_context()
                    self.assertTrue(result)


class TestMainIntegration(unittest.TestCase):

    def test_missing_venv_exits_with_code_1(self):
        with patch.object(preflight, "VENV_DIR", Path("/fake/.venv")):
            with patch.object(Path, "exists", return_value=False):
                with self.assertRaises(SystemExit) as cm:
                    preflight.main()
                self.assertEqual(cm.exception.code, 1)

    def test_wb_not_found_exits_with_code_1(self):
        with patch.object(preflight, "WB_PATH", Path("/fake/.venv/bin/wb")):
            with patch.object(preflight, "VENV_DIR", Path("/fake/.venv")):
                with patch.object(preflight, "DOMAIN_CONTEXT_PATH", Path("/fake/config.yaml")):
                    with patch.object(Path, "exists", return_value=False):
                        with patch("shutil.which", return_value=None):
                            with self.assertRaises(SystemExit) as cm:
                                preflight.main()
                            self.assertEqual(cm.exception.code, 1)

    def test_all_checks_pass_exits_with_code_0(self):
        with patch.object(preflight, "WB_PATH", Path("/fake/.venv/bin/wb")):
            with patch.object(preflight, "VENV_DIR", Path("/fake/.venv")):
                with patch.object(preflight, "DOMAIN_CONTEXT_PATH", Path("/fake/config.yaml")):
                    with patch.object(Path, "exists", return_value=True):
                        with patch("shutil.which", return_value="/usr/bin/wb"):
                            with patch("builtins.open", mock_open(read_data="domain: myapp\nyear_scope:\n  active: [2024]\nvocabulary:\n  operational:\n    - order")):
                                try:
                                    preflight.main()
                                    self.fail("Expected SystemExit with code 0")
                                except SystemExit as e:
                                    self.assertEqual(e.code, 0)


if __name__ == "__main__":
    unittest.main()