# ABOUTME: Performance tracking and debugging utilities for Streamlit app
# ABOUTME: Provides timing, progress indicators, and bottleneck identification tools

import time
import logging
import streamlit as st
from contextlib import contextmanager
from typing import Optional, Dict, Any, List
from datetime import datetime
import json
from pathlib import Path

logger = logging.getLogger(__name__)

class PerformanceTracker:
    """Comprehensive performance tracking for deployment operations"""
    
    def __init__(self):
        # Initialize session state for performance data
        if 'perf_logs' not in st.session_state:
            st.session_state.perf_logs = []
        if 'perf_stats' not in st.session_state:
            st.session_state.perf_stats = {}
    
    @contextmanager
    def track_operation(self, description: str, show_progress: bool = True, 
                       expected_duration: Optional[float] = None):
        """
        Context manager to track performance and provide user feedback
        
        Args:
            description: Description of the operation
            show_progress: Whether to show st.status progress indicator
            expected_duration: Expected duration in seconds (for better UX)
        """
        # Ensure session state is initialized
        if 'perf_logs' not in st.session_state:
            st.session_state.perf_logs = []
        if 'perf_stats' not in st.session_state:
            st.session_state.perf_stats = {}
            
        start_time = time.perf_counter()
        operation_id = f"{description}_{int(start_time)}"
        
        # Determine if this operation typically takes long
        baseline = self._get_baseline_duration(description)
        is_potentially_slow = baseline is None or baseline > 2.0
        
        status_container = None
        if show_progress and is_potentially_slow:
            status_container = st.status(f"🔄 {description}...", expanded=True)
            if expected_duration:
                status_container.write(f"⏱️ Expected duration: ~{expected_duration:.1f}s")
        
        try:
            yield operation_id
            
            # Operation completed successfully
            end_time = time.perf_counter()
            duration = end_time - start_time
            
            # Log performance data
            self._log_operation(description, duration, "Success", operation_id)
            
            # Update UI
            if status_container:
                if duration > 10:
                    status_container.update(
                        label=f"✅ {description} (Completed in {duration:.1f}s)", 
                        state="complete", 
                        expanded=False
                    )
                else:
                    status_container.update(
                        label=f"✅ {description} (Fast: {duration:.2f}s)", 
                        state="complete", 
                        expanded=False
                    )
            
        except Exception as e:
            # Operation failed
            end_time = time.perf_counter()
            duration = end_time - start_time
            
            # Log failure
            self._log_operation(description, duration, f"Failed: {str(e)}", operation_id)
            
            # Update UI
            if status_container:
                status_container.update(
                    label=f"❌ {description} failed!", 
                    state="error", 
                    expanded=True
                )
                status_container.error(f"Error: {str(e)}")
            
            # Re-raise the exception
            raise
    
    def _log_operation(self, description: str, duration: float, status: str, operation_id: str):
        """Log operation performance data"""
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "operation": description,
            "duration": round(duration, 3),
            "status": status,
            "operation_id": operation_id
        }
        
        # Add to session state
        st.session_state.perf_logs.append(log_entry)
        
        # Update statistics
        if description not in st.session_state.perf_stats:
            st.session_state.perf_stats[description] = {
                "count": 0,
                "total_duration": 0,
                "avg_duration": 0,
                "min_duration": float('inf'),
                "max_duration": 0,
                "success_count": 0
            }
        
        stats = st.session_state.perf_stats[description]
        stats["count"] += 1
        stats["total_duration"] += duration
        stats["avg_duration"] = stats["total_duration"] / stats["count"]
        stats["min_duration"] = min(stats["min_duration"], duration)
        stats["max_duration"] = max(stats["max_duration"], duration)
        
        if "Success" in status:
            stats["success_count"] += 1
        
        # Console logging for debugging
        logger.info(f"PERF: {description} - {duration:.3f}s - {status}")
    
    def _get_baseline_duration(self, description: str) -> Optional[float]:
        """Get baseline duration for an operation type"""
        if description in st.session_state.perf_stats:
            return st.session_state.perf_stats[description]["avg_duration"]
        return None
    
    def get_slow_operations(self, threshold: float = 5.0) -> List[Dict]:
        """Get operations that are slower than threshold"""
        slow_ops = []
        for op, stats in st.session_state.perf_stats.items():
            if stats["avg_duration"] > threshold:
                slow_ops.append({
                    "operation": op,
                    "avg_duration": stats["avg_duration"],
                    "count": stats["count"],
                    "success_rate": stats["success_count"] / stats["count"] * 100
                })
        return sorted(slow_ops, key=lambda x: x["avg_duration"], reverse=True)
    
    def display_performance_dashboard(self):
        """Display comprehensive performance dashboard"""
        # Ensure session state is initialized
        if 'perf_logs' not in st.session_state:
            st.session_state.perf_logs = []
        if 'perf_stats' not in st.session_state:
            st.session_state.perf_stats = {}
            
        st.markdown("## 📊 Performance Dashboard")
        
        if not st.session_state.perf_logs:
            st.info("No performance data yet. Operations will be tracked automatically.")
            return
        
        # Summary metrics
        col1, col2, col3, col4 = st.columns(4)
        
        total_ops = len(st.session_state.perf_logs)
        successful_ops = len([log for log in st.session_state.perf_logs if "Success" in log["status"]])
        avg_duration = sum([log["duration"] for log in st.session_state.perf_logs]) / total_ops
        
        with col1:
            st.metric("Total Operations", total_ops)
        with col2:
            st.metric("Success Rate", f"{successful_ops/total_ops*100:.1f}%")
        with col3:
            st.metric("Avg Duration", f"{avg_duration:.2f}s")
        with col4:
            recent_ops = st.session_state.perf_logs[-10:]
            recent_avg = sum([log["duration"] for log in recent_ops]) / len(recent_ops)
            st.metric("Recent Avg", f"{recent_avg:.2f}s")
        
        # Slow operations alert
        slow_ops = self.get_slow_operations(threshold=3.0)
        if slow_ops:
            st.warning("🐌 **Slow Operations Detected**")
            for op in slow_ops[:3]:  # Show top 3 slowest
                st.write(f"• **{op['operation']}**: {op['avg_duration']:.1f}s avg ({op['count']} runs)")
        
        # Detailed logs
        with st.expander("📋 Detailed Performance Logs", expanded=False):
            if st.button("Clear Performance Logs"):
                st.session_state.perf_logs = []
                st.session_state.perf_stats = {}
                st.rerun()
            
            # Recent operations (last 20)
            recent_logs = st.session_state.perf_logs[-20:]
            st.dataframe(recent_logs, use_container_width=True)
        
        # Performance statistics
        with st.expander("📈 Operation Statistics", expanded=False):
            if st.session_state.perf_stats:
                stats_data = []
                for op, stats in st.session_state.perf_stats.items():
                    stats_data.append({
                        "Operation": op,
                        "Count": stats["count"],
                        "Avg Duration (s)": f"{stats['avg_duration']:.2f}",
                        "Min (s)": f"{stats['min_duration']:.2f}",
                        "Max (s)": f"{stats['max_duration']:.2f}",
                        "Success Rate": f"{stats['success_count']/stats['count']*100:.1f}%"
                    })
                st.dataframe(stats_data, use_container_width=True)
    
    def export_performance_data(self, filepath: Optional[str] = None) -> str:
        """Export performance data to JSON file"""
        if not filepath:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filepath = f"performance_data_{timestamp}.json"
        
        data = {
            "export_timestamp": datetime.now().isoformat(),
            "logs": st.session_state.perf_logs,
            "statistics": st.session_state.perf_stats
        }
        
        Path(filepath).write_text(json.dumps(data, indent=2))
        return filepath

# Global instance
performance_tracker = PerformanceTracker()

# Convenience decorator for functions
def track_performance(description: str, show_progress: bool = True):
    """Decorator to track function performance"""
    def decorator(func):
        def wrapper(*args, **kwargs):
            with performance_tracker.track_operation(description, show_progress):
                return func(*args, **kwargs)
        return wrapper
    return decorator

# Performance baselines for common operations (adjust based on your environment)
OPERATION_BASELINES = {
    "Git Clone": 15.0,
    "Git Fetch": 3.0,
    "Docker Build": 60.0,
    "Docker Start": 10.0,
    "Database Query": 0.5,
    "File System Operation": 1.0,
}

def get_expected_duration(operation: str) -> Optional[float]:
    """Get expected duration for an operation"""
    for baseline_op, duration in OPERATION_BASELINES.items():
        if baseline_op.lower() in operation.lower():
            return duration
    return None