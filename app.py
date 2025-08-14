# ABOUTME: Streamlit web UI for OpenSPP Deployment Manager
# ABOUTME: Main application entry point with dashboard and deployment management

import os
import sys
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from dotenv import load_dotenv
import yaml

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from src.models import AppConfig, DeploymentParams, DeploymentStatus
from src.deployment_manager import DeploymentManager
from src.utils import validate_email, validate_deployment_name, format_bytes
from src.performance_tracker import performance_tracker

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Page configuration
st.set_page_config(
    page_title="OpenSPP Deployment Manager",
    page_icon="🚀",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS
st.markdown("""
<style>
    .deployment-card {
        background-color: #f0f2f6;
        border-radius: 10px;
        padding: 20px;
        margin-bottom: 20px;
    }
    .status-running { color: #1f883d; }
    .status-stopped { color: #cf222e; }
    .status-creating { color: #fb8500; }
    .status-error { color: #da3633; }
    .metric-container {
        background-color: white;
        border-radius: 8px;
        padding: 15px;
        text-align: center;
    }
</style>
""", unsafe_allow_html=True)

# Load configuration
@st.cache_resource
def load_config():
    """Load application configuration"""
    config_path = Path("config.yaml")
    if config_path.exists():
        with open(config_path, 'r') as f:
            config_data = yaml.safe_load(f)
        return AppConfig.from_yaml(config_data)
    else:
        return AppConfig()

# Initialize deployment manager
@st.cache_resource
def get_deployment_manager():
    """Get deployment manager instance"""
    config = load_config()
    return DeploymentManager(config)

# Cache git branch lookups with 5 minute TTL
@st.cache_data(ttl=300)
def get_cached_dependency_branches(repo_name: str) -> List[str]:
    """Get available branches for a dependency with caching"""
    manager = get_deployment_manager()
    return manager.get_available_dependency_branches(repo_name)

# Define allowed invoke tasks
ALLOWED_INVOKE_TASKS = {
    # Lifecycle
    "start": {"params": [], "description": "Start services", "icon": "▶️"},
    "stop": {"params": [], "description": "Stop services", "icon": "⏹️"},
    "restart": {"params": ["quick"], "description": "Restart services", "icon": "🔄"},
    
    # Database
    "resetdb": {"params": [], "description": "Reset database", "icon": "🗄️"},
    "snapshot": {"params": [], "description": "Create DB snapshot", "icon": "📸"},
    "restore-snapshot": {"params": ["snapshot-name"], "description": "Restore snapshot", "icon": "⏮️"},
    
    # Development
    "logs": {"params": ["tail", "container"], "description": "View logs", "icon": "📋"},
    "install": {"params": ["modules"], "description": "Install modules", "icon": "📦"},
    "update": {"params": ["modules"], "description": "Update modules", "icon": "🔄"},
    "test": {"params": ["modules"], "description": "Run tests", "icon": "🧪"},
    
    # Git operations
    "git-aggregate": {"params": [], "description": "Update dependencies", "icon": "🔀"},
}

def format_status(status):
    """Format status with color"""
    status_colors = {
        DeploymentStatus.RUNNING: "🟢",
        DeploymentStatus.STOPPED: "🔴",
        DeploymentStatus.CREATING: "🟡",
        DeploymentStatus.UPDATING: "🟠",
        DeploymentStatus.ERROR: "❌"
    }
    # Convert string to enum if needed for backward compatibility
    if isinstance(status, str):
        try:
            status = DeploymentStatus(status)
        except ValueError:
            return f"⚪ {status.title()}"
    return f"{status_colors.get(status, '⚪')} {status.value.title()}"

def show_deployment_card(deployment, col_actions):
    """Display deployment card"""
    manager = get_deployment_manager()
    
    # Get real-time status
    with performance_tracker.track_operation(f"Get Status for {deployment.id}", show_progress=False):
        status_info = manager.get_deployment_status(deployment.id)
    
    # Main info columns
    col1, col2, col3 = st.columns([3, 2, 3])
    
    with col1:
        st.markdown(f"### {deployment.id}")
        st.text(f"Version: {deployment.openspp_version}")
        st.text(f"Environment: {deployment.environment}")
        st.text(f"Created: {deployment.created_at.strftime('%Y-%m-%d %H:%M')}")
    
    with col2:
        st.markdown("**Status**")
        st.markdown(format_status(deployment.status))
        
        if status_info.get("stats"):
            # Show resource usage
            for service, stats in status_info["stats"].items():
                if service == "odoo":
                    st.metric(
                        "CPU", 
                        f"{stats.get('cpu_percent', 0):.1f}%",
                        delta=None
                    )
                    st.metric(
                        "Memory",
                        f"{stats.get('memory_percent', 0):.1f}%",
                        delta=None
                    )
    
    with col3:
        st.markdown("**Access URLs**")
        # Check if nginx is enabled
        config = load_config()
        if config.nginx_enabled:
            odoo_url = f"http://{deployment.subdomain}"
        else:
            odoo_url = f"http://localhost:{deployment.port_base}"
        st.link_button(
            "🌐 Open Odoo",
            odoo_url,
            use_container_width=True
        )
        
        # Quick actions
        action_cols = st.columns(4)
        
        with action_cols[0]:
            if deployment.status == DeploymentStatus.STOPPED:
                if st.button("▶️", key=f"start_{deployment.id}", help="Start"):
                    success, msg = manager.start_deployment(deployment.id)
                    if success:
                        st.success(msg)
                        st.rerun()
                    else:
                        st.error(msg)
            elif deployment.status == DeploymentStatus.RUNNING:
                if st.button("⏹️", key=f"stop_{deployment.id}", help="Stop"):
                    success, msg = manager.stop_deployment(deployment.id)
                    if success:
                        st.success(msg)
                        st.rerun()
                    else:
                        st.error(msg)
        
        with action_cols[1]:
            if st.button("📋", key=f"logs_{deployment.id}", help="Logs"):
                st.session_state.manage_deployment = deployment.id
                st.session_state.show_logs_tab = True
        
        with action_cols[2]:
            if st.button("⚙️", key=f"manage_{deployment.id}", help="Manage"):
                st.session_state.manage_deployment = deployment.id
        
        with action_cols[3]:
            if st.button("🗑️", key=f"delete_{deployment.id}", help="Delete"):
                st.session_state.confirm_delete = deployment.id
    
    # Show tester notes if any
    if deployment.notes:
        with st.expander("📝 Notes"):
            st.text(deployment.notes)
    
    # Show auth credentials if available
    config = load_config()
    if config.nginx_enabled and deployment.auth_password:
        with st.expander("🔐 Credentials"):
            col1, col2 = st.columns(2)
            with col1:
                st.text("Username:")
                st.code(deployment.id)
            with col2:
                st.text("Password:")
                st.code(deployment.auth_password)
    
    st.divider()

def show_create_deployment_form():
    """Show deployment creation form"""
    manager = get_deployment_manager()
    config = load_config()
    
    with st.form("create_deployment", clear_on_submit=True):
        st.subheader("Create New Deployment")
        
        # Basic Information
        col1, col2 = st.columns(2)
        
        with col1:
            tester_email = st.text_input(
                "Tester Email *",
                placeholder="tester@example.com",
                help="Email address of the tester"
            )
            
            deployment_name = st.text_input(
                "Deployment Name *",
                placeholder="my-test",
                help="3-20 characters, alphanumeric and hyphens only"
            )
            
            environment = st.selectbox(
                "Environment",
                ["devel", "test", "prod"],
                help="Deployment environment type"
            )
        
        with col2:
            # Fetch available versions
            versions = manager.config.available_openspp_versions
            if not versions:
                st.error("Unable to fetch OpenSPP versions. Please check your internet connection.")
                if st.button("🔄 Retry Fetch", key="retry_versions"):
                    manager._refresh_available_versions()
                    st.rerun()
                st.stop()
            
            # Default to "17.0" branch if available, otherwise use first version
            default_index = 0
            if "17.0" in versions:
                default_index = versions.index("17.0")
            
            openspp_version = st.selectbox(
                "OpenSPP Version",
                versions,
                index=default_index,
                help="Select OpenSPP version to deploy (branch or tag)"
            )
            
            notes = st.text_area(
                "Notes",
                placeholder="Purpose of this deployment...",
                help="Optional notes about the deployment"
            )
        
        # Initialize dependencies variable
        dependencies = {}
        
        # Advanced Options
        with st.expander("🔧 Advanced Options (Optional)", expanded=True):
            st.markdown("**Override Dependency Versions**")
            st.info("Leave blank to use defaults from selected OpenSPP version. Refresh the page to reload dependencies.")
            st.markdown("🔀 **Organization Selection**: For OpenG2P modules, you can choose between:\n"
                       "- **OpenSPP/** versions - OpenSPP's fork with customizations\n"
                       "- **OpenG2P/** versions - Original OpenG2P repositories")
            
            # Get all available dependencies with caching
            if 'available_deps' not in st.session_state:
                with st.spinner("Loading available dependencies..."):
                    try:
                        with performance_tracker.track_operation("Load Available Dependencies", show_progress=True, expected_duration=15.0):
                            st.session_state.available_deps = manager.get_available_dependencies()
                    except Exception as e:
                        logger.error(f"Failed to load dependencies: {e}")
                        st.session_state.available_deps = {}
            
            available_deps = st.session_state.available_deps
            
            try:
                if available_deps:
                    # Group dependencies by type
                    openg2p_deps = [dep for dep in available_deps if dep.startswith('openg2p_')]
                    other_deps = [dep for dep in available_deps if not dep.startswith('openg2p_') and dep != 'openspp_modules']
                    
                    # Show OpenG2P dependencies first
                    if openg2p_deps:
                        st.markdown("**OpenG2P Dependencies**")
                        st.info("💡 Select versions from either OpenSPP fork or original OpenG2P repos")
                        for dep in sorted(openg2p_deps):
                            versions = available_deps[dep]
                            if versions:
                                # Separate versions by organization (already sorted by recency from backend)
                                openspp_versions = [v for v in versions if v.startswith("OpenSPP/")]
                                openg2p_versions = [v for v in versions if v.startswith("OpenG2P/")]
                                other_versions = [v for v in versions if not v.startswith(("OpenSPP/", "OpenG2P/"))]
                                
                                # Show all versions, grouped by organization
                                organized_versions = openspp_versions + openg2p_versions + other_versions
                                display_help = f"OpenSPP/* = Fork ({len(openspp_versions)} versions), OpenG2P/* = Original ({len(openg2p_versions)} versions)"
                                
                                selected = st.selectbox(
                                    f"{dep}",
                                    ["(default)"] + organized_versions,
                                    key=f"dep_{dep}",
                                    help=display_help
                                )
                                if selected != "(default)":
                                    dependencies[dep] = selected
                    
                    # Show other dependencies
                    if other_deps:
                        st.markdown("**Other Dependencies**")
                        for dep in sorted(other_deps):
                            versions = available_deps[dep]
                            if versions:
                                # Show all versions for consistency
                                help_text = f"{len(versions)} versions available"
                                
                                selected = st.selectbox(
                                    f"{dep}",
                                    ["(default)"] + versions,
                                    key=f"dep_{dep}",
                                    help=help_text
                                )
                                if selected != "(default)":
                                    dependencies[dep] = selected
            except Exception as e:
                # Fallback to basic dependencies
                st.warning("Could not load all dependencies, showing basic options")
                dep_repos = ["openg2p_registry", "openg2p_program"]
                
                for dep in dep_repos:
                    branches = get_cached_dependency_branches(dep)
                    if branches:
                        selected = st.selectbox(
                            f"{dep} branch",
                            ["(default)"] + branches,
                            key=f"dep_{dep}"
                        )
                        if selected != "(default)":
                            dependencies[dep] = selected
        
        # Add spacing and make submit button more prominent
        st.markdown("---")
        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            submitted = st.form_submit_button("🚀 Create Deployment", type="primary", use_container_width=True)
        
        if submitted:
            # Validate inputs
            errors = []
            
            if not tester_email:
                errors.append("Tester email is required")
            elif not validate_email(tester_email):
                errors.append("Invalid email format")
            
            if not deployment_name:
                errors.append("Deployment name is required")
            elif not validate_deployment_name(deployment_name):
                errors.append("Invalid deployment name format")
            
            if errors:
                for error in errors:
                    st.error(error)
            else:
                # Create deployment parameters
                params = DeploymentParams(
                    tester_email=tester_email,
                    name=deployment_name,
                    environment=environment,
                    openspp_version=openspp_version,
                    dependency_versions=dependencies,
                    notes=notes
                )
                
                # Show progress with detailed status
                progress_container = st.container()
                with progress_container:
                    with st.status("Creating deployment...", expanded=True) as status:
                        # Create callback for progress updates
                        def update_progress(step: str, detail: str = ""):
                            status.update(label=step, state="running")
                            if detail:
                                st.write(f"✓ {detail}")
                        
                        success, message, deployment = manager.create_deployment(params, progress_callback=update_progress)
                        
                        if success:
                            status.update(label="Deployment created successfully!", state="complete")
                        else:
                            status.update(label="Deployment failed", state="error")
                
                if success:
                    st.success(message)
                    st.balloons()
                    time.sleep(2)
                    st.session_state.show_create = False
                    st.rerun()
                else:
                    st.error(f"Failed to create deployment: {message}")

def show_deployment_management(deployment_id):
    """Show deployment management panel"""
    manager = get_deployment_manager()
    deployment = manager.db.get_deployment(deployment_id)
    
    if not deployment:
        st.error("Deployment not found")
        return
    
    st.subheader(f"Manage: {deployment.id}")
    
    # Get status info
    status_info = manager.get_deployment_status(deployment_id)
    
    # Status overview
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric("Status", deployment.status.value.title())
    
    if status_info.get("stats"):
        stats = status_info["stats"].get("odoo", {})
        with col2:
            st.metric("CPU Usage", f"{stats.get('cpu_percent', 0):.1f}%")
        with col3:
            memory_usage = stats.get('memory_usage', 0)
            memory_limit = stats.get('memory_limit', 1)
            memory_percent = stats.get('memory_percent', 0)
            st.metric("Memory", f"{memory_percent:.1f}%")
        with col4:
            st.metric("Port", deployment.port_base)
    
    # Access URLs
    st.markdown("### 🌐 Access URLs")
    config = load_config()
    if config.nginx_enabled:
        odoo_url = f"http://{deployment.subdomain}"
        mailhog_url = f"http://mailhog-{deployment.subdomain}"
        pgweb_url = f"http://pgweb-{deployment.subdomain}"
    else:
        odoo_url = f"http://localhost:{deployment.port_base}"
        mailhog_url = f"http://localhost:{deployment.port_mappings.get('smtp', deployment.port_base + 25)}"
        pgweb_url = f"http://localhost:{deployment.port_mappings.get('pgweb', deployment.port_base + 81)}"
    
    urls = {
        "Odoo": odoo_url,
        "Mailhog": mailhog_url,
        "PGWeb": pgweb_url
    }
    
    for service, url in urls.items():
        col1, col2 = st.columns([1, 4])
        with col1:
            st.text(service)
        with col2:
            st.code(url)
    
    # Display authentication credentials for external access
    if config.nginx_enabled and deployment.auth_password:
        st.markdown("### 🔐 Authentication Credentials")
        st.info(f"External domains (*.test.openspp.org) require authentication")
        col1, col2 = st.columns(2)
        with col1:
            st.text("Username:")
            st.code(deployment.id)
        with col2:
            st.text("Password:")
            st.code(deployment.auth_password)
        st.caption("💡 Internal domains (*.openspp-test.internal) do not require authentication")
    
    st.divider()
    
    # Create tabs for different management sections
    # Check if we should highlight logs
    show_logs_hint = st.session_state.get("show_logs_tab", False)
    
    # Create tabs
    tab1, tab2, tab3 = st.tabs(["🛠️ Execute Tasks", "📋 Logs", "🔧 Debug Logs"])
    
    # Show hint if logs button was clicked
    if show_logs_hint:
        st.success("💡 Click on the **📋 Logs** tab above to view deployment logs")
        # Clear the flag after showing the message
        if "show_logs_tab" in st.session_state:
            del st.session_state.show_logs_tab
    
    with tab1:
        # Task execution
        st.markdown("### Execute Tasks")
        
        task_name = st.selectbox(
            "Select Task",
            list(ALLOWED_INVOKE_TASKS.keys()),
            format_func=lambda x: f"{ALLOWED_INVOKE_TASKS[x]['icon']} {x} - {ALLOWED_INVOKE_TASKS[x]['description']}"
        )
    
        task_info = ALLOWED_INVOKE_TASKS[task_name]
        
        # Dynamic parameter inputs
        params = {}
        if task_info["params"]:
            st.markdown("**Parameters:**")
            for param in task_info["params"]:
                if param == "modules":
                    value = st.text_input(
                        "Modules (comma-separated)",
                        placeholder="e.g., spp_programs,spp_registry_group",
                        key=f"param_{param}"
                    )
                    if value:
                        params[param] = value
                elif param == "tail":
                    value = st.number_input(
                        "Number of lines",
                        min_value=10,
                        max_value=1000,
                        value=100,
                        key=f"param_{param}"
                    )
                    params[param] = str(value)
                elif param == "container":
                    containers = ["odoo", "db", "smtp", "pgweb"]
                    value = st.selectbox("Container", containers, key=f"param_{param}")
                    params[param] = value
                elif param == "snapshot-name":
                    value = st.text_input("Snapshot name", key=f"param_{param}")
                    if value:
                        params[param] = value
                elif param == "quick":
                    value = st.checkbox("Quick restart", key=f"param_{param}")
                    if value:
                        params[param] = "true"
        
        col1, col2 = st.columns([1, 4])
        with col1:
            if st.button(f"Execute {task_name}", type="primary"):
                with st.spinner(f"Executing {task_name}..."):
                    result = manager.execute_task(deployment_id, task_name, params)
                
                if result.success:
                    st.success(f"Task completed in {result.execution_time:.1f}s")
                    if result.output:
                        st.code(result.output, language="log")
                else:
                    st.error("Task failed")
                    if result.error:
                        st.code(result.error, language="log")
    
    with tab2:
        # Recent logs
        st.markdown("### 📋 Recent Logs")
        
        col1, col2, col3 = st.columns([2, 2, 1])
        with col1:
            log_service = st.selectbox(
                "Service",
                ["all", "odoo", "db", "smtp"],
                key="log_service"
            )
        with col2:
            log_lines = st.slider(
                "Number of lines",
                min_value=50,
                max_value=500,
                value=100,
                step=50,
                key="log_lines"
            )
        with col3:
            if st.button("🔄 Refresh Logs"):
                service = None if log_service == "all" else log_service
                logs = manager.get_deployment_logs(deployment_id, service=service, tail=log_lines)
                st.code(logs, language="log")
        
        # Auto-load logs
        service = None if log_service == "all" else log_service
        logs = manager.get_deployment_logs(deployment_id, service=service, tail=log_lines)
        st.code(logs, language="log")
    
    with tab3:
        # Command logs for debugging
        st.markdown("### 🔧 Command Logs (Debugging)")
        st.info("View detailed command execution logs for troubleshooting deployment issues")
        
        col1, col2 = st.columns([3, 1])
        with col1:
            debug_log_date = st.text_input(
                "Log Date (YYYYMMDD)", 
                placeholder=f"e.g., {time.strftime('%Y%m%d')}",
                help="Leave empty for today's logs",
                key="debug_log_date"
            )
        with col2:
            debug_type = st.radio(
                "Log Type",
                ["Detailed", "Debug & Timing"],
                key="debug_type"
            )
            
            if st.button("📥 View Logs"):
                if debug_type == "Detailed":
                    cmd_logs = manager.get_deployment_command_logs(deployment_id, date=debug_log_date if debug_log_date else None)
                    st.code(cmd_logs, language="log")
                else:
                    debug_logs = manager.get_deployment_debug_logs(deployment_id, date=debug_log_date if debug_log_date else None)
                    st.code(debug_logs, language="log")
        
        st.info("💡 Debug logs show command execution times and quick summaries - great for performance analysis!")

def show_system_overview():
    """Show system overview in sidebar"""
    manager = get_deployment_manager()
    
    st.sidebar.markdown("## 📊 System Overview")
    
    # Get system info
    with performance_tracker.track_operation("Get Docker System Info", show_progress=False):
        system_info = manager.resource_monitor.get_system_info()
    
    if system_info:
        st.sidebar.metric("Running Containers", system_info.get("containers_running", 0))
        st.sidebar.metric("Total Containers", system_info.get("containers", 0))
        st.sidebar.metric("Docker Version", system_info.get("docker_version", "Unknown"))
    
    # Dev mode indicator
    if manager.config.dev_mode:
        st.sidebar.warning("🚧 **DEV MODE**: Failed deployments preserved for debugging")
    
    # Quick stats
    with performance_tracker.track_operation("Load Deployments for Sidebar Stats", show_progress=False):
        all_deployments = manager.db.get_all_deployments()
    
    stats = {
        "Total": len(all_deployments),
        "Running": len([d for d in all_deployments if d.status == DeploymentStatus.RUNNING]),
        "Stopped": len([d for d in all_deployments if d.status == DeploymentStatus.STOPPED]),
        "Error": len([d for d in all_deployments if d.status == DeploymentStatus.ERROR])
    }
    
    st.sidebar.markdown("### Deployment Stats")
    for label, count in stats.items():
        st.sidebar.text(f"{label}: {count}")
    
    # Sync states button
    if st.sidebar.button("🔄 Sync States"):
        with st.spinner("Syncing deployment states..."):
            manager.sync_deployment_states()
        st.success("States synced")
        st.rerun()
    
    # Cleanup button
    if st.sidebar.button("🧹 Cleanup Resources"):
        cleaned = manager.resource_monitor.cleanup_dangling_resources()
        st.sidebar.success(f"Cleaned: {cleaned.get('images', 0)} images, "
                          f"{cleaned.get('volumes', 0)} volumes")

def main():
    """Main application"""
    st.title("🚀 OpenSPP Deployment Manager")
    
    # Initialize session state
    if "show_create" not in st.session_state:
        st.session_state.show_create = False
    if "manage_deployment" not in st.session_state:
        st.session_state.manage_deployment = None
    if "confirm_delete" not in st.session_state:
        st.session_state.confirm_delete = None
    
    # Get deployment manager
    manager = get_deployment_manager()
    
    # Show system overview in sidebar
    show_system_overview()
    
    # Handle delete confirmation
    if st.session_state.confirm_delete:
        deployment_id = st.session_state.confirm_delete
        st.warning(f"⚠️ Are you sure you want to delete deployment {deployment_id}?")
        col1, col2, col3 = st.columns([1, 1, 3])
        with col1:
            if st.button("Yes, Delete", type="primary"):
                with st.spinner("Deleting deployment..."):
                    with performance_tracker.track_operation(f"Delete deployment {deployment_id}", show_progress=True):
                        success, message = manager.delete_deployment(deployment_id)
                if success:
                    st.success(message)
                    st.session_state.confirm_delete = None
                    time.sleep(1)
                    st.rerun()
                else:
                    st.error(message)
        with col2:
            if st.button("Cancel"):
                st.session_state.confirm_delete = None
                st.rerun()
        return
    
    # Show create form if requested
    if st.session_state.show_create:
        show_create_deployment_form()
        if st.button("← Back to Dashboard"):
            st.session_state.show_create = False
            st.rerun()
        return
    
    # Show management panel if requested
    if st.session_state.manage_deployment:
        show_deployment_management(st.session_state.manage_deployment)
        if st.button("← Back to Dashboard"):
            st.session_state.manage_deployment = None
            st.rerun()
        return
    
    # Main tabs
    tab1, tab2 = st.tabs(["🚀 Deployments", "📊 Performance"])
    
    with tab1:
        # Main dashboard
        col1, col2 = st.columns([3, 1])
        with col1:
            st.markdown("Manage OpenSPP test deployments with ease")
        with col2:
            if st.button("➕ New Deployment", type="primary", use_container_width=True):
                st.session_state.show_create = True
                st.rerun()
        
        # Filters
        st.markdown("### 🔍 Filters")
        col1, col2, col3, col4 = st.columns(4)
    
        with col1:
            filter_tester = st.text_input("Tester Email", placeholder="Filter by tester...")
        with col2:
            filter_status = st.selectbox("Status", ["All"] + [status.value for status in DeploymentStatus])
        with col3:
            filter_version = st.text_input("Version", placeholder="Filter by version...")
        with col4:
            search_query = st.text_input("Search", placeholder="Search deployments...")
    
        # Get and filter deployments
        with performance_tracker.track_operation("Load All Deployments", show_progress=False):
            deployments = manager.db.get_all_deployments()
    
        # Apply filters
        if filter_tester:
            deployments = [d for d in deployments if filter_tester.lower() in d.tester_email.lower()]
    
        if filter_status != "All":
            # Convert string to enum for comparison
            try:
                status_enum = DeploymentStatus(filter_status)
                deployments = [d for d in deployments if d.status == status_enum]
            except ValueError:
                # Handle invalid status gracefully
                pass
    
        if filter_version:
            deployments = [d for d in deployments if filter_version.lower() in d.openspp_version.lower()]
    
        if search_query:
            query = search_query.lower()
            deployments = [d for d in deployments 
                          if query in d.id.lower() or 
                             query in d.notes.lower() or
                             query in d.tester_email.lower()]
    
        # Display deployments
        st.markdown(f"### 📦 Deployments ({len(deployments)})")
    
        if not deployments:
            st.info("No deployments found. Create your first deployment to get started!")
        else:
            # Create columns for action buttons
            action_cols = st.columns(len(deployments))
        
        # Display each deployment
        with performance_tracker.track_operation(f"Render {len(deployments)} Deployment Cards", show_progress=True, expected_duration=len(deployments) * 1.5):
            for i, deployment in enumerate(deployments):
                with st.container():
                    show_deployment_card(deployment, action_cols[i] if i < len(action_cols) else None)
    
    with tab2:
        # Performance Dashboard
        performance_tracker.display_performance_dashboard()

if __name__ == "__main__":
    main()