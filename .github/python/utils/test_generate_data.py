#!/usr/bin/env python3

import json
import os
import tempfile
import unittest
from unittest.mock import patch, MagicMock

# We'll import functions directly for unit tests
from generate_data import extract_test_fields


class TestGenerateDataValue(unittest.TestCase):

    def test_extract_test_fields_empty(self):
        """Test extract_test_fields with empty input"""
        fail, passing = extract_test_fields("")
        self.assertEqual(fail, "")
        self.assertEqual(passing, "")

    def test_extract_test_fields_fail_only(self):
        """Test extract_test_fields with only FAIL_TO_PASS"""
        test_input = "Some text\nFAIL_TO_PASS: TestClass1, TestClass2\nMore text"
        fail, passing = extract_test_fields(test_input)
        self.assertEqual(fail, "TestClass1, TestClass2")
        self.assertEqual(passing, "")

    def test_extract_test_fields_pass_only(self):
        """Test extract_test_fields with only PASS_TO_PASS"""
        test_input = "Some text\nPASS_TO_PASS: TestClass1, TestClass2\nMore text"
        fail, passing = extract_test_fields(test_input)
        self.assertEqual(fail, "")
        self.assertEqual(passing, "TestClass1, TestClass2")

    def test_extract_test_fields_both(self):
        """Test extract_test_fields with both FAIL_TO_PASS and PASS_TO_PASS"""
        test_input = """Commit message

        FAIL_TO_PASS: TestClass1, TestClass2
        PASS_TO_PASS: TestClass3, TestClass4
        """
        fail, passing = extract_test_fields(test_input)
        self.assertEqual(fail, "TestClass1, TestClass2")
        self.assertEqual(passing, "TestClass3, TestClass4")

    def test_extract_test_fields_with_commit_format(self):
        """Test extract_test_fields with realistic commit message format"""
        test_input = """Generate CRUD Developer controller #5

Generate CRUD Developer controller, service and repository. Developer controller should use "/api/developers" request mapping. Expose CRUD logic to the controller via service. Controller must expose Developer entity with DeveloperDto DTO object.

FAIL_TO_PASS: DeveloperControllerTests,DeveloperRepositoryTest,DeveloperServiceTest
"""
        fail, passing = extract_test_fields(test_input)
        self.assertEqual(fail, "DeveloperControllerTests,DeveloperRepositoryTest,DeveloperServiceTest")
        self.assertEqual(passing, "")

class TestIntegration(unittest.TestCase):

    @patch('subprocess.run')
    def test_script_with_mocked_commits(self, mock_run):
        """Test the script's handling of commits with FAIL_TO_PASS"""

        # Mock subprocess calls to simulate GitHub API responses
        def mock_subprocess(cmd, **kwargs):
            result = MagicMock()
            result.stdout = ""
            result.returncode = 0

            # Make a string representation of the command for easier checking
            cmd_str = ' '.join(cmd) if isinstance(cmd, list) else str(cmd)

            # When fetching commits for an issue
            if 'timeline' in cmd_str and 'commit_id' in cmd_str:
                result.stdout = "commit1\ncommit2\n"

            # When fetching commit messages
            elif '/commits/' in cmd_str:
                if 'commit1' in cmd_str:
                    result.stdout = """Generate CRUD Developer controller #5

Generate CRUD Developer controller, service and repository.

FAIL_TO_PASS: DeveloperControllerTests,DeveloperRepositoryTest,DeveloperServiceTest
"""
                elif 'commit2' in cmd_str:
                    result.stdout = "Another commit message\n"

            # For other API calls, return empty
            return result

        mock_run.side_effect = mock_subprocess

        # Create a temporary environment for testing
        with tempfile.TemporaryDirectory() as tmpdir:
            script_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'generate_data_value.py')

            # Set up environment variables
            test_env = os.environ.copy()
            test_env.update({
                'ISSUE_NUMBER': '5',
                'REPOSITORY': 'test-repo',
                'ORGANIZATION': 'test-org',
                'LATEST_COMMIT': 'commit1',
                'BASE_COMMIT': 'base-commit',
                'GH_TOKEN': 'fake-token',
                'TEST_COMMIT_MESSAGE': """Generate CRUD Developer controller #5

Generate CRUD Developer controller, service and repository.

FAIL_TO_PASS: DeveloperControllerTests,DeveloperRepositoryTest,DeveloperServiceTest
""",
                'TEST_FAIL_TO_PASS': "DeveloperControllerTests,DeveloperRepositoryTest,DeveloperServiceTest"
            })

            # Create a temporary file to capture the output
            output_file = os.path.join(tmpdir, "output.json")
            
            # Create a command that sets the environment variables and runs the script
            env_vars = " ".join([f"{k}='{v}'" for k, v in test_env.items()])
            cmd = f"{env_vars} python {script_path} > {output_file}"
            
            # Run the script and redirect output to the temporary file
            os.system(cmd)
            
            # Read the output from the temporary file
            with open(output_file, 'r') as f:
                output = f.read()
            
            # Debug: Print the output
            print(f"OUTPUT (test_script_with_mocked_commits): '{output}'")
            
            # Parse the JSON output
            output_json = json.loads(output)

            # Check that FAIL_TO_PASS was correctly extracted and formatted
            expected_fail_to_pass = json.dumps(["DeveloperControllerTests", "DeveloperRepositoryTest", "DeveloperServiceTest"])
            self.assertEqual(output_json["FAIL_TO_PASS"], expected_fail_to_pass)
            self.assertEqual(output_json["PASS_TO_PASS"], "[]")

    @patch('subprocess.run')
    def test_script_with_issue_comments(self, mock_run):
        """Test the script's handling of issue comments with test fields"""

        # Mock subprocess calls to simulate GitHub API responses
        def mock_subprocess(cmd, **kwargs):
            result = MagicMock()
            result.stdout = ""
            result.returncode = 0

            # Make a string representation of the command for easier checking
            cmd_str = ' '.join(cmd) if isinstance(cmd, list) else str(cmd)

            # When fetching issue comments
            if '/comments' in cmd_str:
                result.stdout = """Comment 1 without fields
---
Comment with fields

FAIL_TO_PASS: CommentTest1, CommentTest2
PASS_TO_PASS: PassingTest1, PassingTest2
"""

            # For other API calls, return empty
            return result

        mock_run.side_effect = mock_subprocess

        # Create a temporary environment for testing
        with tempfile.TemporaryDirectory() as tmpdir:
            script_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'generate_data_value.py')

            # Set up environment variables
            test_env = os.environ.copy()
            test_env.update({
                'ISSUE_NUMBER': '5',
                'REPOSITORY': 'test-repo',
                'ORGANIZATION': 'test-org',
                'LATEST_COMMIT': 'commit1',
                'BASE_COMMIT': 'base-commit',
                'GH_TOKEN': 'fake-token',
                'TEST_ISSUE_COMMENTS': """Comment 1 without fields
---
Comment with fields

FAIL_TO_PASS: CommentTest1, CommentTest2
PASS_TO_PASS: PassingTest1, PassingTest2
""",
                'TEST_FAIL_TO_PASS': "CommentTest1, CommentTest2",
                'TEST_PASS_TO_PASS': "PassingTest1, PassingTest2"
            })

            # Create a temporary file to capture the output
            output_file = os.path.join(tmpdir, "output.json")
            
            # Create a command that sets the environment variables and runs the script
            env_vars = " ".join([f"{k}='{v}'" for k, v in test_env.items()])
            cmd = f"{env_vars} python {script_path} > {output_file}"
            
            # Run the script and redirect output to the temporary file
            os.system(cmd)
            
            # Read the output from the temporary file
            with open(output_file, 'r') as f:
                output = f.read()
            
            # Debug: Print the output
            print(f"OUTPUT (test_script_with_issue_comments): '{output}'")
            
            # Parse the JSON output
            output_json = json.loads(output)

            # Check that values from comments were correctly extracted and formatted
            expected_fail_to_pass = json.dumps(["CommentTest1", "CommentTest2"])
            expected_pass_to_pass = json.dumps(["PassingTest1", "PassingTest2"])
            self.assertEqual(output_json["FAIL_TO_PASS"], expected_fail_to_pass)
            self.assertEqual(output_json["PASS_TO_PASS"], expected_pass_to_pass)

    def test_manual_extract(self):
        """Manual test to ensure the regex is working properly"""
        test_input = """Generate CRUD Developer controller #5

Generate CRUD Developer controller, service and repository. Developer controller should use "/api/developers" request mapping. Expose CRUD logic to the controller via service. Controller must expose Developer entity with DeveloperDto DTO object.

FAIL_TO_PASS: DeveloperControllerTests,DeveloperRepositoryTest,DeveloperServiceTest
"""
        import re

        # Test the regex directly
        pattern = r'FAIL_TO_PASS:\s*(.*?)(\n\s*\n|$)'
        match = re.search(pattern, test_input, re.DOTALL)
        if match:
            print(f"Direct regex match found: '{match.group(1).strip()}'")
            self.assertIn("DeveloperControllerTests", match.group(1))
        else:
            self.fail("Regex failed to match FAIL_TO_PASS")

if __name__ == "__main__":
    unittest.main()
