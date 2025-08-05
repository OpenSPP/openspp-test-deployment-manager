#!/usr/bin/env python3
# ABOUTME: Comprehensive integration test for deployment preparation
# ABOUTME: Tests full deployment setup without running Docker commands

import sys
import os
import shutil
import tempfile
import time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.models import AppConfig, DeploymentParams, Deployment, DeploymentStatus
from src.deployment_manager import DeploymentManager
from src.database import DeploymentDatabase
from src.utils import (
    sanitize_deployment_id, get_port_mappings, generate_env_content,
    read_yaml_file, write_yaml_file
)
import git
import yaml

class DeploymentPreparationTest:
    """Test full deployment preparation process"""
    
    def __init__(self):
        self.temp_dir = None
        self.config = None
        self.manager = None
        self.deployment = None
        
    def setup(self):
        """Set up test environment"""
        print("🔧 Setting up test environment...")
        
        # Create temporary directory
        self.temp_dir = tempfile.mkdtemp(prefix="openspp_test_")
        print(f"   ✅ Created temp directory: {self.temp_dir}")
        
        # Create configuration
        self.config = AppConfig()
        self.config.base_deployment_path = self.temp_dir
        self.config.nginx_enabled = False
        self.config.openspp_docker_repo = "https://github.com/OpenSPP/openspp-docker.git"
        self.config.default_branch = "17.0"
        
        # Create deployment manager (with temporary database)
        db_path = os.path.join(self.temp_dir, "test_deployments.db")
        self.manager = DeploymentManager(self.config)
        self.manager.db = DeploymentDatabase(db_path)
        
        print("   ✅ Configuration created")
        print(f"   ✅ Database initialized at {db_path}")
        
    def cleanup(self):
        """Clean up test environment"""
        print("\n🧹 Cleaning up...")
        if self.temp_dir and os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)
            print("   ✅ Removed temporary directory")
    
    def test_deployment_preparation(self):
        """Test the full deployment preparation process"""
        print("\n" + "=" * 70)
        print("COMPREHENSIVE DEPLOYMENT PREPARATION TEST")
        print("=" * 70)
        
        # 1. Create deployment parameters
        print("\n1️⃣ Creating deployment parameters...")
        params = DeploymentParams(
            tester_email="test@example.com",
            name="test-app",
            environment="devel",
            openspp_version="openspp-17.0.1.2.1",
            dependency_versions={
                "openg2p_registry": "17.0-develop-openspp",
                "openg2p_program": "17.0-develop"
            },
            notes="Integration test deployment"
        )
        
        errors = params.validate()
        if errors:
            print(f"   ❌ Validation failed: {errors}")
            return False
        
        print("   ✅ Parameters validated")
        print(f"      - Tester: {params.tester_email}")
        print(f"      - Name: {params.name}")
        print(f"      - OpenSPP Version: {params.openspp_version}")
        print(f"      - Dependencies: {list(params.dependency_versions.keys())}")
        
        # 2. Allocate resources
        print("\n2️⃣ Allocating resources...")
        deployment_id = sanitize_deployment_id(params.tester_email, params.name)
        print(f"   ✅ Deployment ID: {deployment_id}")
        
        port_base = self.manager.db.allocate_port_range(deployment_id)
        if not port_base:
            print("   ❌ Failed to allocate port")
            return False
        
        print(f"   ✅ Allocated port base: {port_base}")
        port_mappings = get_port_mappings(port_base)
        print("   ✅ Port mappings:")
        for service, port in port_mappings.items():
            print(f"      - {service}: {port}")
        
        # 3. Create deployment object
        print("\n3️⃣ Creating deployment object...")
        self.deployment = Deployment(
            id=deployment_id,
            name=params.name,
            tester_email=params.tester_email,
            openspp_version=params.openspp_version,
            dependency_versions=params.dependency_versions,
            environment=params.environment,
            status=DeploymentStatus.CREATING,
            port_base=port_base,
            port_mappings=port_mappings,
            subdomain=f"localhost:{port_base}",
            notes=params.notes
        )
        
        # Save to database
        self.manager.db.save_deployment(self.deployment)
        print("   ✅ Deployment saved to database")
        
        # 4. Create deployment directory
        print("\n4️⃣ Creating deployment directory structure...")
        deployment_path = os.path.join(self.config.base_deployment_path, deployment_id)
        os.makedirs(deployment_path, exist_ok=True)
        print(f"   ✅ Created: {deployment_path}")
        
        # 5. Clone openspp-docker repository
        print("\n5️⃣ Cloning openspp-docker repository...")
        print(f"   📦 Repository: {self.config.openspp_docker_repo}")
        print(f"   🌿 Branch: {self.config.default_branch}")
        print("   ⏳ This may take a moment...")
        
        start_time = time.time()
        try:
            repo_path = os.path.join(deployment_path, "openspp-docker")
            repo = git.Repo.clone_from(
                self.config.openspp_docker_repo,
                repo_path,
                branch=self.config.default_branch,
                progress=lambda op_code, cur_count, max_count, message: 
                    print(f"      {message.strip()}", end='\r') if message else None
            )
            elapsed = time.time() - start_time
            print(f"\n   ✅ Cloned successfully in {elapsed:.1f}s")
            print(f"   ✅ Repository at: {repo_path}")
        except Exception as e:
            print(f"   ❌ Clone failed: {e}")
            return False
        
        # 6. Verify repository structure
        print("\n6️⃣ Verifying repository structure...")
        expected_files = {
            "docker-compose.yaml": "Docker Compose configuration",
            "docker-compose.override.yaml": "Override configuration",
            "odoo/custom/src/repos.yaml": "Repository dependencies",
            "tasks.py": "Invoke tasks",
            ".env.example": "Environment template"
        }
        
        for file_path, description in expected_files.items():
            full_path = os.path.join(repo_path, file_path)
            exists = os.path.exists(full_path)
            status = "✅" if exists else "⚠️"
            print(f"   {status} {file_path}: {description}")
            if exists and file_path.endswith('.yaml'):
                size = os.path.getsize(full_path)
                print(f"      Size: {size} bytes")
        
        # 7. Update repos.yaml with versions
        print("\n7️⃣ Updating repos.yaml with deployment versions...")
        repos_yaml_path = os.path.join(repo_path, "odoo/custom/src/repos.yaml")
        
        if os.path.exists(repos_yaml_path):
            # Read current repos.yaml
            repos = read_yaml_file(repos_yaml_path)
            print("   ✅ Loaded repos.yaml")
            
            # Update openspp_modules version
            if 'openspp_modules' in repos:
                old_version = repos['openspp_modules'].get('merges', ['unknown'])[0]
                repos['openspp_modules']['target'] = f"openspp {self.deployment.openspp_version}"
                repos['openspp_modules']['merges'] = [f"openspp {self.deployment.openspp_version}"]
                print(f"   ✅ Updated openspp_modules:")
                print(f"      - From: {old_version}")
                print(f"      - To: openspp {self.deployment.openspp_version}")
            
            # Update dependency versions
            for dep, version in self.deployment.dependency_versions.items():
                if dep in repos:
                    old_version = repos[dep].get('merges', ['unknown'])[0]
                    repos[dep]['merges'] = [f"openg2p {version}"]
                    print(f"   ✅ Updated {dep}:")
                    print(f"      - From: {old_version}")
                    print(f"      - To: openg2p {version}")
            
            # Write updated repos.yaml
            write_yaml_file(repos_yaml_path, repos)
            print("   ✅ Saved updated repos.yaml")
            
            # Verify changes
            print("\n   🔍 Verifying changes...")
            updated_repos = read_yaml_file(repos_yaml_path)
            if 'openspp_modules' in updated_repos:
                actual_version = updated_repos['openspp_modules']['merges'][0]
                expected_version = f"openspp {self.deployment.openspp_version}"
                if actual_version == expected_version:
                    print(f"      ✅ openspp_modules correctly set to: {actual_version}")
                else:
                    print(f"      ❌ Version mismatch: expected {expected_version}, got {actual_version}")
        else:
            print("   ❌ repos.yaml not found!")
            return False
        
        # 8. Generate .env file
        print("\n8️⃣ Generating .env configuration file...")
        env_path = os.path.join(deployment_path, ".env")
        
        config_dict = {
            'docker_cpu_limit': self.config.docker_cpu_limit,
            'docker_memory_limit': self.config.docker_memory_limit
        }
        
        env_content = generate_env_content(
            deployment_id,
            self.deployment.port_base,
            config_dict
        )
        
        with open(env_path, 'w') as f:
            f.write(env_content)
        
        print("   ✅ Generated .env file")
        print("   📋 Environment variables:")
        for line in env_content.split('\n'):
            if '=' in line and not line.startswith('#'):
                key = line.split('=')[0].strip()
                if key in ['ODOO_PORT', 'SMTP_PORT', 'PGWEB_PORT', 'COMPOSE_PROJECT_NAME']:
                    print(f"      - {line.strip()}")
        
        # 9. Save deployment metadata
        print("\n9️⃣ Saving deployment metadata...")
        metadata_path = os.path.join(deployment_path, "deployment.json")
        import json
        with open(metadata_path, 'w') as f:
            json.dump(self.deployment.to_dict(), f, indent=2, default=str)
        print(f"   ✅ Saved deployment metadata to deployment.json")
        
        # 10. Show what commands would be run
        print("\n🔟 Commands that would be executed (in order):")
        commands = [
            ("develop", "Set up development environment"),
            ("img-pull", "Pull Docker images"),
            ("img-build", "Build custom images"),
            ("git-aggregate", "Aggregate git dependencies"),
            ("resetdb", "Initialize database"),
            ("start --detach", "Start all services in background")
        ]
        
        print("   📝 Working directory: openspp-docker/")
        for cmd, description in commands:
            print(f"   $ invoke {cmd}")
            print(f"     → {description}")
        
        # 11. Verify everything is ready
        print("\n✅ DEPLOYMENT PREPARATION COMPLETE!")
        print("\n📊 Summary:")
        print(f"   - Deployment ID: {deployment_id}")
        print(f"   - Location: {deployment_path}")
        print(f"   - OpenSPP Version: {self.deployment.openspp_version}")
        print(f"   - Port Range: {port_base}-{port_base + 99}")
        print(f"   - Status: Ready for Docker operations")
        
        print("\n📁 Created structure:")
        print(f"   {deployment_path}/")
        print(f"   ├── .env                    # Environment configuration")
        print(f"   ├── deployment.json         # Deployment metadata")
        print(f"   └── openspp-docker/         # Cloned repository")
        print(f"       ├── docker-compose.yaml")
        print(f"       ├── tasks.py")
        print(f"       └── odoo/custom/src/repos.yaml  # Updated with versions")
        
        return True

def main():
    """Run the comprehensive integration test"""
    print("\n🧪 OpenSPP Deployment Manager - Full Preparation Test\n")
    print("This test will:")
    print("  ✓ Clone the actual openspp-docker repository")
    print("  ✓ Configure repos.yaml with specific versions")
    print("  ✓ Generate .env file with port mappings")
    print("  ✓ Create all necessary files for deployment")
    print("  ✗ NOT run Docker commands\n")
    
    test = DeploymentPreparationTest()
    
    try:
        test.setup()
        success = test.test_deployment_preparation()
        
        if success:
            print("\n" + "=" * 70)
            print("✅ ALL TESTS PASSED!")
            print("=" * 70)
            print("\nThe deployment preparation process works correctly:")
            print("- Git cloning ✓")
            print("- Version configuration ✓")
            print("- Environment setup ✓")
            print("- File generation ✓")
            print("\n🚀 Ready to run Docker commands!")
            return 0
        else:
            print("\n❌ Test failed!")
            return 1
            
    except Exception as e:
        print(f"\n❌ Error during test: {e}")
        import traceback
        traceback.print_exc()
        return 1
    finally:
        test.cleanup()

if __name__ == "__main__":
    sys.exit(main())