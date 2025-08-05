# ABOUTME: Tests for utility functions
# ABOUTME: Validates validation, Git operations, and helpers

import pytest
import tempfile
import os
import time
from unittest.mock import patch, MagicMock
from src.utils import (
    validate_deployment_name, validate_email, sanitize_deployment_id,
    get_port_mappings, retry_on_failure, run_command_with_retry,
    format_docker_project_name, parse_git_tags, parse_git_branches
)


class TestValidation:
    """Test validation functions"""
    
    def test_validate_deployment_name(self):
        """Test deployment name validation"""
        # Valid names
        assert validate_deployment_name("valid-name") == True
        assert validate_deployment_name("test123") == True
        assert validate_deployment_name("a-b") == True  # Minimum 3 chars
        
        # Invalid names
        assert validate_deployment_name("") == False
        assert validate_deployment_name("a") == False  # Too short
        assert validate_deployment_name("ab") == False  # Too short
        assert validate_deployment_name("invalid name") == False  # Spaces
        assert validate_deployment_name("invalid_name") == False  # Underscore
        assert validate_deployment_name("UPPERCASE") == True  # Converted to lowercase internally
        assert validate_deployment_name("-start-dash") == False
        assert validate_deployment_name("end-dash-") == False
        assert validate_deployment_name("a" * 21) == False  # Too long
    
    def test_validate_email(self):
        """Test email validation"""
        # Valid emails
        assert validate_email("test@example.com") == True
        assert validate_email("user.name@company.co.uk") == True
        assert validate_email("test+tag@example.com") == True
        
        # Invalid emails
        assert validate_email("") == False
        assert validate_email("not-an-email") == False
        assert validate_email("@example.com") == False
        assert validate_email("test@") == False
        assert validate_email("test@.com") == False
    
    def test_sanitize_deployment_id(self):
        """Test deployment ID sanitization"""
        assert sanitize_deployment_id("test@example.com", "my-app") == "test-my-app"
        assert sanitize_deployment_id("john.doe@company.com", "test") == "john-doe-test"
        assert sanitize_deployment_id("user+tag@example.com", "app") == "usertag-app"
        assert sanitize_deployment_id("TEST@EXAMPLE.COM", "APP") == "test-app"


class TestPortMappings:
    """Test port mapping functions"""
    
    def test_get_port_mappings(self):
        """Test port mapping generation"""
        mappings = get_port_mappings(18000)
        
        assert mappings["odoo"] == 18000
        assert mappings["smtp"] == 18025
        assert mappings["mailhog"] == 18025  # Same as smtp
        assert mappings["pgweb"] == 18081
        assert mappings["debugger"] == 18084
    
    def test_format_docker_project_name(self):
        """Test Docker project name formatting"""
        assert format_docker_project_name("test-deployment") == "openspp_test_deployment"
        assert format_docker_project_name("my-app-123") == "openspp_my_app_123"


class TestRetryLogic:
    """Test retry decorator and functions"""
    
    def test_retry_on_failure_success(self):
        """Test retry decorator with successful function"""
        call_count = 0
        
        @retry_on_failure(max_attempts=3, delay=0.1, backoff=2.0)
        def successful_function():
            nonlocal call_count
            call_count += 1
            return "success"
        
        result = successful_function()
        assert result == "success"
        assert call_count == 1  # Should succeed on first try
    
    def test_retry_on_failure_eventual_success(self):
        """Test retry decorator with function that fails then succeeds"""
        call_count = 0
        
        @retry_on_failure(max_attempts=3, delay=0.1, backoff=2.0)
        def eventually_successful():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise Exception("Temporary failure")
            return "success"
        
        result = eventually_successful()
        assert result == "success"
        assert call_count == 3
    
    def test_retry_on_failure_all_attempts_fail(self):
        """Test retry decorator when all attempts fail"""
        call_count = 0
        
        @retry_on_failure(max_attempts=3, delay=0.1, backoff=2.0)
        def always_fails():
            nonlocal call_count
            call_count += 1
            raise Exception("Permanent failure")
        
        with pytest.raises(Exception) as exc_info:
            always_fails()
        
        assert "Permanent failure" in str(exc_info.value)
        assert call_count == 3
    
    @patch('src.utils.run_command')
    def test_run_command_with_retry_git(self, mock_run_command):
        """Test run_command_with_retry for git commands"""
        # Mock a transient network error that succeeds on retry
        mock_result_fail = MagicMock()
        mock_result_fail.returncode = 1
        mock_result_fail.stderr = "network timeout error"
        
        mock_result_success = MagicMock()
        mock_result_success.returncode = 0
        mock_result_success.stdout = "success"
        
        mock_run_command.side_effect = [mock_result_fail, mock_result_success]
        
        result = run_command_with_retry(["git", "pull"], max_attempts=3)
        
        assert result.returncode == 0
        assert mock_run_command.call_count == 2
    
    @patch('src.utils.run_command')
    def test_run_command_with_retry_non_retriable(self, mock_run_command):
        """Test run_command_with_retry for non-retriable commands"""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_run_command.return_value = mock_result
        
        # Non-retriable command should only be called once
        result = run_command_with_retry(["ls", "-la"], max_attempts=3)
        
        assert result.returncode == 0
        assert mock_run_command.call_count == 1


class TestGitParsing:
    """Test Git output parsing functions"""
    
    def test_parse_git_tags(self):
        """Test parsing git tag output"""
        output = """
        a1b2c3d4 refs/tags/openspp-17.0.1.2.0
        e5f6g7h8 refs/tags/openspp-17.0.1.2.1
        i9j0k1l2 refs/tags/v1.0.0
        m3n4o5p6 refs/tags/openspp-17.0.1.1.0
        """
        
        tags = parse_git_tags(output)
        
        assert len(tags) == 4
        assert "openspp-17.0.1.2.1" in tags
        assert "openspp-17.0.1.2.0" in tags
        assert "v1.0.0" in tags
        # Should be sorted in reverse order
        assert tags[0] == "v1.0.0"  # Alphabetically last
    
    def test_parse_git_branches(self):
        """Test parsing git branch output"""
        output = """
        a1b2c3d4 refs/heads/main
        e5f6g7h8 refs/heads/17.0-develop-openspp
        i9j0k1l2 refs/heads/feature/new-feature
        m3n4o5p6 refs/heads/17.0
        """
        
        branches = parse_git_branches(output)
        
        assert len(branches) == 4
        assert "main" in branches
        assert "17.0-develop-openspp" in branches
        assert "feature/new-feature" in branches
        assert branches[0] == "17.0"  # Should be sorted
    
    def test_parse_git_branches_simple_format(self):
        """Test parsing simple git branch output"""
        output = """
        * main
          develop
          feature/test
        """
        
        branches = parse_git_branches(output)
        
        assert len(branches) == 3
        assert "main" in branches
        assert "develop" in branches
        assert "feature/test" in branches