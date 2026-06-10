import subprocess
import platform
import time
import re
from datetime import datetime, timedelta
import threading
import os
import json
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter, landscape
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak, Image
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.enums import TA_CENTER, TA_LEFT
import sys
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from io import BytesIO
from collections import deque
import signal
import gc
import atexit
import traceback

# OpenAI integration
try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False
    print("[WARNING] OpenAI library not installed. Install with: pip install openai")

# =========================================================
# GLOBAL FLAG FOR CLEAN SHUTDOWN
# =========================================================
running = True

# =========================================================
# CONFIGURATION FILES
# =========================================================

NODES_FILE = "nodes_config.json"
EMAIL_CONFIG_FILE = "email_config.json"
SCHEDULE_CONFIG_FILE = "schedule_config.json"
MONITORING_CONFIG_FILE = "monitoring_config.json"
MONITORING_LOG_FILE = "monitoring_log.json"
STATS_FILE = "network_stats.json"
OPENAI_CONFIG_FILE = "openai_config.json"

# =========================================================
# SAFE JSON LOAD FUNCTION
# =========================================================

def safe_load_json(filepath, default_config):
    """Safely load JSON file with error handling and auto-recovery"""
    if not os.path.exists(filepath):
        with open(filepath, 'w') as f:
            json.dump(default_config, f, indent=4)
        print(f"[CONFIG] Created config file: {filepath}")
        return default_config
    
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
            # Try to fix common JSON errors
            content = re.sub(r',\s*}', '}', content)
            content = re.sub(r',\s*]', ']', content)
            return json.loads(content)
    except json.JSONDecodeError as e:
        print(f"[CONFIG ERROR] Failed to parse {filepath}: {e}")
        print(f"[CONFIG] Creating backup of corrupted file as {filepath}.bak")
        
        # Backup corrupted file
        if os.path.exists(filepath):
            import shutil
            shutil.copy(filepath, f"{filepath}.bak")
        
        # Create new default config
        with open(filepath, 'w') as f:
            json.dump(default_config, f, indent=4)
        print(f"[CONFIG] Recreated {filepath} with default values")
        return default_config
    except Exception as e:
        print(f"[CONFIG ERROR] Unexpected error loading {filepath}: {e}")
        return default_config

# =========================================================
# LOAD OPENAI CONFIGURATION
# =========================================================

def load_openai_config():
    """Load OpenAI configuration from JSON file"""
    default_config = {
        "enabled": False,
        "api_key": "",
        "model": "gpt-3.5-turbo",
        "max_tokens": 600,
        "temperature": 0.5,
        "include_recommendations": False,
        "description": "Set include_recommendations to False to remove recommendations from AI summary"
    }
    return safe_load_json(OPENAI_CONFIG_FILE, default_config)

# =========================================================
# LOAD MONITORING CONFIGURATION
# =========================================================

def load_monitoring_config():
    """Load monitoring configuration from JSON file"""
    default_config = {
        "ping_interval_seconds": 5,
        "packet_size_bytes": 32,
        "ping_timeout_seconds": 5,
        "failure_threshold": 3,
        "packet_loss_log_retention": 100,
        "packet_loss_window_seconds": 30,
        "monitoring_log_interval_seconds": 30,
        "packet_loss_calculation_only_online": True,
        "initial_status_check_seconds": 30,
        "description": "failure_threshold: Number of consecutive failures before marking as DOWN (default 3 = 15 seconds)"
    }
    return safe_load_json(MONITORING_CONFIG_FILE, default_config)

# =========================================================
# LOAD SCHEDULE CONFIGURATION
# =========================================================

def load_schedule_config():
    """Load report schedule configuration from JSON file"""
    default_config = {
        "daily_report": {
            "enabled": True,
            "hour": 23,
            "minute": 59,
            "description": "Daily report at 23:59"
        },
        "weekly_report": {
            "enabled": True,
            "day_of_week": 6,
            "hour": 23,
            "minute": 59,
            "description": "Weekly report on Sunday at 23:59 (0=Monday, 6=Sunday)"
        },
        "monthly_report": {
            "enabled": False,
            "day_of_month": 1,
            "hour": 0,
            "minute": 0,
            "description": "Monthly report on 1st day of month at 00:00"
        },
        "hourly_report": {
            "enabled": False,
            "minute": 0,
            "description": "Hourly report at the top of every hour"
        },
        "custom_interval": {
            "enabled": False,
            "interval_hours": 6,
            "description": "Custom 6-hour report"
        }
    }
    return safe_load_json(SCHEDULE_CONFIG_FILE, default_config)

# =========================================================
# LOAD NODES CONFIGURATION
# =========================================================

def load_nodes_config():
    """Load nodes configuration from JSON file"""
    default_config = {
        "nodes": [],
        "description": "Add your BTS nodes here. Example: {\"name\": \"BTS Name\", \"ip\": \"192.168.1.1\", \"is_major\": true}"
    }
    
    if not os.path.exists(NODES_FILE):
        with open(NODES_FILE, 'w') as f:
            json.dump(default_config, f, indent=4)
        print(f"[CONFIG] Created empty nodes config file: {NODES_FILE}")
        print("[CONFIG] ERROR: No nodes configured! Please add your BTS nodes to nodes_config.json")
        return []
    
    try:
        with open(NODES_FILE, 'r', encoding='utf-8') as f:
            config = json.load(f)
            
            if isinstance(config, list):
                nodes = config
            else:
                nodes = config.get("nodes", [])
            
            if not nodes:
                print("[CONFIG] WARNING: No nodes found in nodes_config.json")
            
            return nodes
    except Exception as e:
        print(f"[CONFIG ERROR] Failed to load nodes: {e}")
        return []

# =========================================================
# LOAD EMAIL CONFIGURATION
# =========================================================

def load_email_config():
    """Load email configuration from JSON file"""
    default_config = {
        "smtp_server": "smtp.gmail.com",
        "smtp_port": 587,
        "sender_email": "",
        "sender_password": "",
        "recipient_emails": [],
        "enabled": False,
        "email_subject_prefix": "[NOC] BTS Network Report"
    }
    return safe_load_json(EMAIL_CONFIG_FILE, default_config)

# =========================================================
# LOAD ALL CONFIGURATIONS
# =========================================================

monitoring_config = load_monitoring_config()
schedule_config = load_schedule_config()
nodes_config = load_nodes_config()
email_config = load_email_config()
openai_config = load_openai_config()

# =========================================================
# APPLY MONITORING CONFIGURATION
# =========================================================

PING_INTERVAL = monitoring_config.get("ping_interval_seconds", 5)
PACKET_SIZE = monitoring_config.get("packet_size_bytes", 32)
PING_TIMEOUT = monitoring_config.get("ping_timeout_seconds", 5)
FAILURE_THRESHOLD = monitoring_config.get("failure_threshold", 3)
PACKET_LOSS_LOG_RETENTION = monitoring_config.get("packet_loss_log_retention", 100)
PACKET_LOSS_WINDOW_SECONDS = monitoring_config.get("packet_loss_window_seconds", 30)
MONITORING_LOG_INTERVAL = monitoring_config.get("monitoring_log_interval_seconds", 30)
PACKET_LOSS_ONLY_ONLINE = monitoring_config.get("packet_loss_calculation_only_online", True)
INITIAL_STATUS_CHECK_SECONDS = monitoring_config.get("initial_status_check_seconds", 30)

# Calculate window size in number of pings
PACKET_LOSS_WINDOW_SIZE = max(1, PACKET_LOSS_WINDOW_SECONDS // PING_INTERVAL)
INITIAL_CHECK_ATTEMPTS = max(3, INITIAL_STATUS_CHECK_SECONDS // PING_INTERVAL)

# =========================================================
# BUILD NODES AND MAJOR NODES FROM CONFIG
# =========================================================

nodes = []
major_node_names = set()
major_nodes_list = []
normal_nodes_list = []

for node_config in nodes_config:
    node = {
        "name": node_config["name"],
        "ip": node_config["ip"]
    }
    nodes.append(node)
    
    if node_config.get("is_major", False):
        major_node_names.add(node_config["name"])
        major_nodes_list.append(node)
    else:
        normal_nodes_list.append(node)

major_nodes = [{"name": name} for name in major_node_names]

if not nodes:
    print("\n[FATAL ERROR] No BTS nodes configured!")
    print("Please edit nodes_config.json and add your BTS nodes.")
    sys.exit(1)

# =========================================================
# Initialize OpenAI Client
# =========================================================

openai_client = None
if openai_config.get("enabled", False) and openai_config.get("api_key"):
    try:
        openai_client = OpenAI(api_key=openai_config["api_key"])
        print("[AI] OpenAI client initialized successfully")
    except Exception as e:
        print(f"[AI ERROR] Failed to initialize OpenAI client: {e}")
        openai_client = None

# =========================================================
# PDF Reports Directory
# =========================================================

PDF_DIR = "network_reports"
if not os.path.exists(PDF_DIR):
    os.makedirs(PDF_DIR)

# =========================================================
# PERSISTENT MONITORING LOG
# =========================================================

monitoring_sessions = []

def safe_write_json_file(filepath, data):
    """Safely write JSON file with retry and proper error handling"""
    try:
        temp_file = filepath + ".tmp"
        
        with open(temp_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
        
        if os.path.exists(filepath):
            try:
                os.remove(filepath)
            except Exception:
                pass
        
        os.rename(temp_file, filepath)
        return True
        
    except PermissionError:
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)
            return True
        except Exception:
            return False
    except Exception:
        return False

def load_monitoring_log():
    """Load monitoring sessions from persistent log file"""
    global monitoring_sessions
    
    if os.path.exists(MONITORING_LOG_FILE):
        try:
            with open(MONITORING_LOG_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                monitoring_sessions = []
                for session in data.get("sessions", []):
                    monitoring_sessions.append({
                        "start": datetime.fromisoformat(session["start"]),
                        "end": datetime.fromisoformat(session["end"]) if session["end"] else None
                    })
                print(f"[LOG] Loaded {len(monitoring_sessions)} monitoring sessions from log")
                
                if data.get("current_session_active", False):
                    incomplete_session = monitoring_sessions[-1] if monitoring_sessions else None
                    if incomplete_session and incomplete_session["end"] is None:
                        last_heartbeat = data.get("last_heartbeat")
                        if last_heartbeat:
                            incomplete_session["end"] = datetime.fromisoformat(last_heartbeat)
                            print(f"[LOG] Detected incomplete session - ended at {incomplete_session['end']}")
                        else:
                            incomplete_session["end"] = incomplete_session["start"] + timedelta(minutes=5)
                            print(f"[LOG] Detected incomplete session - estimated end at {incomplete_session['end']}")
        except Exception as e:
            print(f"[LOG ERROR] Failed to load monitoring log: {e}")
            monitoring_sessions = []
    else:
        monitoring_sessions = []
        print("[LOG] No existing monitoring log found - starting fresh")

def save_monitoring_log():
    """Save monitoring sessions to persistent log file"""
    try:
        data = {
            "sessions": [],
            "current_session_active": running,
            "last_heartbeat": datetime.now().isoformat() if running else None
        }
        
        for session in monitoring_sessions:
            data["sessions"].append({
                "start": session["start"].isoformat(),
                "end": session["end"].isoformat() if session["end"] else None
            })
        
        safe_write_json_file(MONITORING_LOG_FILE, data)
        
    except Exception:
        pass

def add_monitoring_session(start_time, end_time=None):
    """Add a monitoring session to the log"""
    global monitoring_sessions
    
    session = {
        "start": start_time,
        "end": end_time
    }
    monitoring_sessions.append(session)
    save_monitoring_log()

def close_current_session():
    """Close the current monitoring session"""
    global monitoring_sessions
    
    if monitoring_sessions and monitoring_sessions[-1]["end"] is None:
        monitoring_sessions[-1]["end"] = datetime.now()
        save_monitoring_log()

def heartbeat():
    """Periodic heartbeat"""
    global running
    while running:
        time.sleep(MONITORING_LOG_INTERVAL)
        if running:
            save_monitoring_log()

def get_monitoring_time_in_range(start_time, end_time):
    """Calculate monitored seconds within a range"""
    total_monitored_seconds = 0
    
    for session in monitoring_sessions:
        session_start = session["start"]
        session_end = session["end"] if session["end"] else datetime.now()
        
        if session_end >= start_time and session_start <= end_time:
            overlap_start = max(session_start, start_time)
            overlap_end = min(session_end, end_time)
            overlap_seconds = int((overlap_end - overlap_start).total_seconds())
            total_monitored_seconds += overlap_seconds
    
    return total_monitored_seconds

def get_monitoring_gaps_in_range(start_time, end_time):
    """Find gaps in monitoring within the time range"""
    gaps = []
    
    sorted_sessions = sorted(monitoring_sessions, key=lambda x: x["start"])
    
    relevant_sessions = []
    for session in sorted_sessions:
        session_end = session["end"] if session["end"] else datetime.now()
        if session_end >= start_time and session["start"] <= end_time:
            relevant_sessions.append({
                "start": max(session["start"], start_time),
                "end": min(session_end, end_time)
            })
    
    if not relevant_sessions:
        gaps.append({"start": start_time, "end": end_time})
        return gaps
    
    if relevant_sessions[0]["start"] > start_time:
        gaps.append({"start": start_time, "end": relevant_sessions[0]["start"]})
    
    for i in range(len(relevant_sessions) - 1):
        if relevant_sessions[i]["end"] < relevant_sessions[i + 1]["start"]:
            gaps.append({"start": relevant_sessions[i]["end"], "end": relevant_sessions[i + 1]["start"]})
    
    if relevant_sessions[-1]["end"] < end_time:
        gaps.append({"start": relevant_sessions[-1]["end"], "end": end_time})
    
    return gaps

# =========================================================
# PACKET LOSS LOGGING
# =========================================================

packet_loss_logs = {}

for node in nodes:
    packet_loss_logs[node["ip"]] = {
        "name": node["name"],
        "logs": [],
        "online_ping_history": deque(maxlen=PACKET_LOSS_WINDOW_SIZE)
    }

# =========================================================
# STORAGE
# =========================================================

all_time_stats = {}

def load_historical_stats():
    """Load historical statistics from file"""
    global all_time_stats
    
    if os.path.exists(STATS_FILE):
        try:
            with open(STATS_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                
                for ip, stats_data in data.items():
                    if ip in all_time_stats:
                        all_time_stats[ip]["successful_pings"] = stats_data.get("successful_pings", 0)
                        all_time_stats[ip]["failed_pings"] = stats_data.get("failed_pings", 0)
                        all_time_stats[ip]["latencies"] = stats_data.get("latencies", [])
                        all_time_stats[ip]["downtime_history"] = stats_data.get("downtime_history", [])
                        all_time_stats[ip]["downtime_count"] = stats_data.get("downtime_count", 0)
                        all_time_stats[ip]["total_downtime_seconds"] = stats_data.get("total_downtime_seconds", 0)
                
                print(f"[STATS] Loaded historical statistics from {STATS_FILE}")
        except Exception as e:
            print(f"[STATS ERROR] Failed to load stats: {e}")

def save_historical_stats():
    """Save historical statistics to file"""
    try:
        data = {}
        for ip, stats_data in all_time_stats.items():
            data[ip] = {
                "name": stats_data["name"],
                "successful_pings": stats_data["successful_pings"],
                "failed_pings": stats_data["failed_pings"],
                "latencies": stats_data["latencies"][-10000:],
                "downtime_history": stats_data["downtime_history"],
                "downtime_count": stats_data["downtime_count"],
                "total_downtime_seconds": stats_data["total_downtime_seconds"]
            }
        
        safe_write_json_file(STATS_FILE, data)
        
    except Exception:
        pass

for node in nodes:
    all_time_stats[node["ip"]] = {
        "name": node["name"],
        "ip": node["ip"],
        "successful_pings": 0,
        "failed_pings": 0,
        "latencies": [],
        "downtime_history": [],
        "downtime_count": 0,
        "total_downtime_seconds": 0,
        "first_seen": None,
        "last_seen": None,
        "initial_status": "UNKNOWN"
    }

load_historical_stats()

stats = {}

def reset_stats_for_period():
    """Reset stats for new reporting period"""
    global stats
    stats = {}
    
    for node in nodes:
        stats[node["ip"]] = {
            "name": node["name"],
            "successful_pings": 0,
            "failed_pings": 0,
            "latencies": [],
            "current_status": "UNKNOWN",
            "last_seen": "Never",
            "consecutive_failures": 0,
            "first_failure_time": None,
            "officially_down": False,
            "downtime_start": None,
            "downtime_history": [],
            "downtime_count": 0,
            "total_downtime_seconds": 0
        }

reset_stats_for_period()

# =========================================================
# INITIAL STATUS CHECK
# =========================================================

def perform_initial_status_check():
    """Check initial status of all nodes before starting monitoring"""
    print("\n[INITIAL STATUS CHECK] Checking all BTS nodes...")
    print("=" * 60)
    
    initially_down = []
    
    for node in nodes:
        name = node["name"]
        ip = node["ip"]
        
        # Perform multiple pings to determine initial status
        success_count = 0
        for attempt in range(INITIAL_CHECK_ATTEMPTS):
            latency = ping_host(ip)
            if latency is not None:
                success_count += 1
            time.sleep(PING_INTERVAL)
        
        # If less than 50% of attempts succeeded, mark as initially down
        if success_count < (INITIAL_CHECK_ATTEMPTS / 2):
            initially_down.append(name)
            all_time_stats[ip]["initial_status"] = "DOWN"
            stats[ip]["current_status"] = "OFFLINE"
            stats[ip]["officially_down"] = True
            stats[ip]["downtime_start"] = datetime.now()
            stats[ip]["first_failure_time"] = datetime.now()
            stats[ip]["consecutive_failures"] = FAILURE_THRESHOLD
            
            # Record downtime event starting from now
            downtime_event = {
                "start": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "end": None,
                "duration_seconds": 0,
                "ongoing": True
            }
            all_time_stats[ip]["downtime_history"].append(downtime_event)
            all_time_stats[ip]["downtime_count"] += 1
            
            print(f"  WARNING: {name} ({ip}) - INITIALLY OFFLINE (Detected at startup)")
        else:
            all_time_stats[ip]["initial_status"] = "ONLINE"
            stats[ip]["current_status"] = "ONLINE"
            stats[ip]["officially_down"] = False
            print(f"  OK: {name} ({ip}) - INITIALLY ONLINE")
    
    print("=" * 60)
    
    if initially_down:
        print(f"[INITIAL STATUS] {len(initially_down)} node(s) were offline at startup: {', '.join(initially_down)}")
    else:
        print("[INITIAL STATUS] All nodes were online at startup")
    
    return initially_down

# =========================================================
# PING FUNCTION
# =========================================================

def ping_host(ip):
    """Simple ping function that works reliably with small packet sizes"""
    system = platform.system().lower()
    
    try:
        if system == "windows":
            command = [
                "ping",
                "-n", "1",
                "-w", str(PING_TIMEOUT * 1000),
                ip
            ]
        else:
            command = [
                "ping",
                "-c", "1",
                "-W", str(PING_TIMEOUT),
                ip
            ]
        
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            timeout=PING_TIMEOUT + 1
        )
        
        output = result.stdout.lower()
        
        if system == "windows":
            if "reply from" in output:
                latency_match = re.search(r"time[=<]\s*(\d+)", output)
                if latency_match:
                    latency = float(latency_match.group(1))
                    return latency
                return 1.0
        else:
            if "1 received" in output or "time=" in output:
                latency_match = re.search(r"time=(\d+\.?\d*)", output)
                if latency_match:
                    latency = float(latency_match.group(1))
                    return latency
                return 1.0
                
    except subprocess.TimeoutExpired:
        pass
    except Exception:
        pass
    
    return None

# =========================================================
# PACKET LOSS CALCULATION
# =========================================================

def calculate_packet_loss_for_online_device(ip):
    """Calculate packet loss percentage ONLY when device is ONLINE"""
    history = packet_loss_logs[ip]["online_ping_history"]
    
    if len(history) == 0:
        return 0
    
    failures = sum(1 for success in history if not success)
    percentage = round((failures / len(history)) * 100, 2)
    
    if percentage >= 100:
        return 0
    
    return percentage

def update_online_ping_history(ip, success, is_online):
    """Update ping history for packet loss calculation"""
    if is_online:
        packet_loss_logs[ip]["online_ping_history"].append(success)
    else:
        packet_loss_logs[ip]["online_ping_history"].clear()

def log_packet_loss_event(ip, name, packet_loss_percentage, timestamp):
    """Log packet loss event"""
    if packet_loss_percentage <= 0 or packet_loss_percentage >= 100:
        return
    
    logs = packet_loss_logs[ip]["logs"]
    
    last_log = logs[-1] if logs else None
    if last_log is None or abs(last_log['packet_loss'] - packet_loss_percentage) >= 5:
        logs.append({
            "timestamp": timestamp,
            "packet_loss": packet_loss_percentage
        })
        
        if len(logs) > PACKET_LOSS_LOG_RETENTION:
            packet_loss_logs[ip]["logs"] = logs[-PACKET_LOSS_LOG_RETENTION:]
        
        if packet_loss_percentage >= 20:
            severity = "CRITICAL"
        elif packet_loss_percentage >= 10:
            severity = "WARNING"
        else:
            severity = "MINOR"
        
        print(f"\n[PACKET LOSS] {severity} - {name} ({ip}) - {packet_loss_percentage}% at {timestamp.strftime('%Y-%m-%d %H:%M:%S')}")

# =========================================================
# HELPER FUNCTIONS
# =========================================================

def format_seconds(seconds):
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    return f"{hours}h {minutes}m {secs}s"

def get_total_downtime_seconds(data):
    total = data["total_downtime_seconds"]
    if data.get("officially_down", False) and data.get("downtime_start"):
        ongoing = int((datetime.now() - data["downtime_start"]).total_seconds())
        total += ongoing
    return total

def calculate_uptime(total_downtime, monitored_seconds):
    if monitored_seconds <= 0:
        return 0
    uptime_seconds = monitored_seconds - total_downtime
    if uptime_seconds < 0:
        uptime_seconds = 0
    uptime = round((uptime_seconds / monitored_seconds) * 100, 2)
    return uptime

# =========================================================
# AI NOC SUMMARY GENERATION
# =========================================================

def generate_ai_noc_summary(summary_data, report_type, start_time, end_time, gaps, monitoring_coverage):
    """Generate an intelligent NOC-style summary using OpenAI"""
    
    if not openai_client or not openai_config.get("enabled", False):
        return None
    
    # Prepare the data for the AI
    major_summary = [bts for bts in summary_data if bts["name"] in major_node_names]
    normal_summary = [bts for bts in summary_data if bts["name"] not in major_node_names]
    
    # Identify critical issues
    critical_issues = []
    warning_issues = []
    
    for bts in summary_data:
        if bts['total_downtime_seconds'] > 300:
            critical_issues.append(f"{bts['name']}: {format_seconds(bts['total_downtime_seconds'])} downtime")
        elif bts['total_downtime_seconds'] > 60:
            warning_issues.append(f"{bts['name']}: {format_seconds(bts['total_downtime_seconds'])} downtime")
        
        if bts['packet_loss'] > 10:
            critical_issues.append(f"{bts['name']}: {bts['packet_loss']}% packet loss")
        elif bts['packet_loss'] > 5:
            warning_issues.append(f"{bts['name']}: {bts['packet_loss']}% packet loss")
        
        if bts['avg_latency'] > 200:
            critical_issues.append(f"{bts['name']}: {bts['avg_latency']}ms latency")
        elif bts['avg_latency'] > 100:
            warning_issues.append(f"{bts['name']}: {bts['avg_latency']}ms latency")
    
    # Calculate overall stats
    avg_uptime = round(sum(bts['uptime'] for bts in summary_data) / len(summary_data), 2)
    total_outages = sum(bts['downtime_count'] for bts in summary_data)
    
    include_recommendations = openai_config.get("include_recommendations", False)
    
    # Build prompt based on whether recommendations should be included
    if include_recommendations:
        prompt = f"""You are a Senior NOC Engineer. Write a network status report based on the data below.

REPORT DETAILS:
- Type: {report_type.upper()}
- Period: {start_time.strftime('%Y-%m-%d %H:%M:%S')} to {end_time.strftime('%Y-%m-%d %H:%M:%S')}
- Duration: {round((end_time - start_time).total_seconds() / 3600, 1)} hours
- Monitoring Coverage: {monitoring_coverage}%

NETWORK SUMMARY:
- Overall Average Uptime: {avg_uptime}%
- Total Outages: {total_outages}
- Devices with Issues: {len(critical_issues) + len(warning_issues)}

CRITICAL ISSUES:
{chr(10).join(f'• {issue}' for issue in critical_issues) if critical_issues else 'None'}

WARNING ISSUES:
{chr(10).join(f'• {issue}' for issue in warning_issues) if warning_issues else 'None'}

MAJOR BTS:
{chr(10).join(f'• {bts["name"]}: {bts["uptime"]}% uptime, {bts["packet_loss"]}% loss, {bts["avg_latency"]}ms' for bts in major_summary)}

OTHER BTS (Top 5):
{chr(10).join(f'• {bts["name"]}: {bts["uptime"]}% uptime, {bts["packet_loss"]}% loss, {bts["avg_latency"]}ms' for bts in normal_summary[:5])}

{'MONITORING GAPS:' + chr(10).join(f'• {gap["start"].strftime("%Y-%m-%d %H:%M:%S")} to {gap["end"].strftime("%Y-%m-%d %H:%M:%S")}' for gap in gaps) if gaps else ''}

Write a concise report with:
1. Executive Summary (2-3 sentences)
2. Key Observations
3. Recommendations (based on issues found)

Keep it professional and under 400 words. Do NOT include "Overall Health Status" or any health rating."""
    else:
        prompt = f"""You are a Senior NOC Engineer. Write a network status report based on the data below. DO NOT include recommendations or action items - just report the facts.

REPORT DETAILS:
- Type: {report_type.upper()}
- Period: {start_time.strftime('%Y-%m-%d %H:%M:%S')} to {end_time.strftime('%Y-%m-%d %H:%M:%S')}
- Duration: {round((end_time - start_time).total_seconds() / 3600, 1)} hours
- Monitoring Coverage: {monitoring_coverage}%

NETWORK SUMMARY:
- Overall Average Uptime: {avg_uptime}%
- Total Outages: {total_outages}
- Devices with Issues: {len(critical_issues) + len(warning_issues)}

CRITICAL ISSUES:
{chr(10).join(f'• {issue}' for issue in critical_issues) if critical_issues else 'None'}

WARNING ISSUES:
{chr(10).join(f'• {issue}' for issue in warning_issues) if warning_issues else 'None'}

MAJOR BTS:
{chr(10).join(f'• {bts["name"]}: {bts["uptime"]}% uptime, {bts["packet_loss"]}% loss, {bts["avg_latency"]}ms' for bts in major_summary)}

OTHER BTS (Top 5):
{chr(10).join(f'• {bts["name"]}: {bts["uptime"]}% uptime, {bts["packet_loss"]}% loss, {bts["avg_latency"]}ms' for bts in normal_summary[:5])}

{'MONITORING GAPS:' + chr(10).join(f'• {gap["start"].strftime("%Y-%m-%d %H:%M:%S")} to {gap["end"].strftime("%Y-%m-%d %H:%M:%S")}' for gap in gaps) if gaps else ''}

Write a concise report with:
1. Executive Summary (2-3 sentences)
2. Key Observations

Keep it professional and under 350 words. Do NOT include "Overall Health Status", health ratings, or recommendations."""

    try:
        response = openai_client.chat.completions.create(
            model=openai_config.get("model", "gpt-3.5-turbo"),
            messages=[
                {"role": "system", "content": "You are a Senior NOC Engineer writing factual network reports. Never include health status ratings like HEALTHY, DEGRADED, or CRITICAL."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=openai_config.get("max_tokens", 600),
            temperature=openai_config.get("temperature", 0.5)
        )
        
        ai_summary = response.choices[0].message.content
        print("[AI] NOC summary generated successfully")
        return ai_summary
        
    except Exception as e:
        print(f"[AI ERROR] Failed to generate NOC summary: {e}")
        return None

# =========================================================
# PIE CHART CREATION
# =========================================================

def create_pie_chart(uptime_percentage, downtime_percentage, bts_name, monitored_percentage=None):
    fig, ax = plt.subplots(figsize=(4, 4))
    
    labels = [f'Uptime ({uptime_percentage}%)', f'Downtime ({downtime_percentage}%)']
    sizes = [uptime_percentage, downtime_percentage]
    colors_pie = ['#4CAF50', '#F44336']
    explode = (0.05, 0.05)
    
    if uptime_percentage == 0 and downtime_percentage == 0:
        labels = ['No Data Available']
        sizes = [100]
        colors_pie = ['#CCCCCC']
        explode = (0,)
    
    wedges, texts, autotexts = ax.pie(
        sizes, 
        explode=explode, 
        labels=labels, 
        colors=colors_pie,
        autopct='%1.1f%%' if len(sizes) > 1 else None,
        startangle=90,
        textprops={'fontsize': 10}
    )
    
    if len(sizes) > 1:
        for text in texts:
            text.set_fontweight('bold')
        for autotext in autotexts:
            autotext.set_color('white')
            autotext.set_fontweight('bold')
            autotext.set_fontsize(10)
    
    title = f'{bts_name} - Uptime vs Downtime'
    if monitored_percentage is not None and monitored_percentage < 100:
        title += f'\n(Monitoring Coverage: {monitored_percentage}%)'
    
    ax.set_title(title, fontsize=12, fontweight='bold', pad=20)
    ax.axis('equal')
    
    img_data = BytesIO()
    plt.savefig(img_data, format='png', dpi=100, bbox_inches='tight')
    plt.close(fig)
    
    img_data.seek(0)
    return Image(img_data)

# =========================================================
# SEND EMAIL - WITHOUT COLORS
# =========================================================

def send_email_report(report_type, start_time, end_time, pdf_filename, text_summary, gaps, ai_summary=None):
    if not email_config.get("enabled", False):
        return False
    
    if not email_config.get("sender_email") or not email_config.get("sender_password"):
        return False
    
    if not email_config.get("recipient_emails"):
        return False
    
    try:
        msg = MIMEMultipart()
        msg['From'] = email_config['sender_email']
        msg['To'] = ', '.join(email_config['recipient_emails'])
        msg['Subject'] = f"{email_config.get('email_subject_prefix', '[NOC] BTS Network Report')} - {start_time.strftime('%Y-%m-%d')}"
        
        # Build clean plain text email body
        body = f"""
BTS NETWORK MONITORING REPORT
{'=' * 60}

Report Type: {report_type.upper()}
Report Period: {start_time.strftime('%Y-%m-%d %H:%M:%S')} - {end_time.strftime('%Y-%m-%d %H:%M:%S')}
Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

{'=' * 60}

"""
        
        # Add AI Summary if available
        if ai_summary:
            body += f"""
AI NOC ENGINEER ANALYSIS
{'=' * 40}

{ai_summary}

{'=' * 40}

"""
        
        # Add the detailed text summary
        body += f"""
DETAILED STATISTICS
{'=' * 40}

{text_summary}

{'=' * 40}

"""
        
        if gaps:
            body += """
MONITORING GAPS DETECTED
{'=' * 40}

The following periods were NOT monitored (script not running):

"""
            for gap in gaps:
                gap_duration = int((gap['end'] - gap['start']).total_seconds())
                body += f"  - {gap['start'].strftime('%Y-%m-%d %H:%M:%S')} to {gap['end'].strftime('%Y-%m-%d %H:%M:%S')} ({format_seconds(gap_duration)})\n"
            body += "\nThese periods were EXCLUDED from all calculations.\n"
            body += "=" * 40 + "\n"
        
        body += f"""
PDF ATTACHMENT
{'=' * 40}

The full detailed PDF report with charts is attached to this email.

This is an automated report from the BTS Network Monitoring System.
"""
        
        msg.attach(MIMEText(body, 'plain'))
        
        with open(pdf_filename, 'rb') as attachment:
            part = MIMEBase('application', 'octet-stream')
            part.set_payload(attachment.read())
            encoders.encode_base64(part)
            part.add_header('Content-Disposition', f'attachment; filename={os.path.basename(pdf_filename)}')
            msg.attach(part)
        
        server = smtplib.SMTP(email_config['smtp_server'], email_config['smtp_port'])
        server.starttls()
        server.login(email_config['sender_email'], email_config['sender_password'])
        server.send_message(msg)
        server.quit()
        
        print(f"[EMAIL] {report_type.upper()} report sent successfully")
        return True
        
    except Exception as e:
        print(f"[EMAIL ERROR] {e}")
        return False

# =========================================================
# PDF GENERATION WITH PACKET LOSS HISTORY
# =========================================================

def generate_pdf_report(summary_data, start_time, end_time, report_type="daily", gaps=None):
    filename = os.path.join(PDF_DIR, f"BTS_{report_type}_Report_{start_time.strftime('%Y%m%d_%H%M%S')}.pdf")
    
    doc = SimpleDocTemplate(filename, pagesize=landscape(letter), rightMargin=72, leftMargin=72, topMargin=72, bottomMargin=72)
    styles = getSampleStyleSheet()
    
    title_style = ParagraphStyle('CustomTitle', parent=styles['Heading1'], fontSize=24, textColor=colors.HexColor('#003366'), alignment=TA_CENTER, spaceAfter=10)
    subtitle_style = ParagraphStyle('Subtitle', parent=styles['Normal'], fontSize=14, textColor=colors.HexColor('#006699'), alignment=TA_CENTER, spaceAfter=20)
    warning_style = ParagraphStyle('Warning', parent=styles['Normal'], fontSize=10, textColor=colors.HexColor('#FF6600'), alignment=TA_CENTER, spaceAfter=10, backColor=colors.HexColor('#FFF3E0'))
    heading_style = ParagraphStyle('CustomHeading', parent=styles['Heading2'], fontSize=16, textColor=colors.HexColor('#004488'), spaceAfter=12, spaceBefore=20)
    subheading_style = ParagraphStyle('SubHeading', parent=styles['Heading3'], fontSize=12, textColor=colors.HexColor('#0066AA'), spaceAfter=8, spaceBefore=12)
    normal_style = ParagraphStyle('CustomNormal', parent=styles['Normal'], fontSize=10, spaceAfter=6)
    
    story = []
    
    story.append(Paragraph(f"BTS Uptime and Outage Report - {report_type.upper()}", title_style))
    story.append(Paragraph(f"{start_time.strftime('%Y-%m-%d %H:%M:%S')} - {end_time.strftime('%Y-%m-%d %H:%M:%S')}", subtitle_style))
    story.append(Paragraph(f"Report Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", normal_style))
    
    if gaps:
        gap_text = "WARNING: MONITORING GAPS DETECTED<br/>"
        for gap in gaps:
            gap_duration = int((gap['end'] - gap['start']).total_seconds())
            gap_text += f"• {gap['start'].strftime('%Y-%m-%d %H:%M:%S')} to {gap['end'].strftime('%Y-%m-%d %H:%M:%S')} ({format_seconds(gap_duration)})<br/>"
        story.append(Paragraph(gap_text, warning_style))
    
    story.append(Spacer(1, 0.3*inch))
    
    # Sort: Major BTS first
    major_summary = [bts for bts in summary_data if bts["name"] in major_node_names]
    normal_summary = [bts for bts in summary_data if bts["name"] not in major_node_names]
    sorted_summary_data = major_summary + normal_summary
    
    for bts_data in sorted_summary_data:
        story.append(Paragraph(f"BTS: {bts_data['name']}", heading_style))
        
        downtime_percentage = round(100 - bts_data['uptime'], 2)
        pie_chart = create_pie_chart(bts_data['uptime'], downtime_percentage, bts_data['name'], bts_data.get('monitoring_coverage', 100))
        story.append(pie_chart)
        story.append(Spacer(1, 0.2*inch))
        
        stats_data = [
            ["Metric", "Value"],
            ["Current Status", bts_data.get('current_status', 'ONLINE' if bts_data['uptime'] > 0 else 'OFFLINE')],
            ["Monitoring Coverage", f"{bts_data.get('monitoring_coverage', 100)}%"],
            ["Uptime (of monitored time)", f"{bts_data['uptime']}%"],
            ["Downtime (of monitored time)", f"{downtime_percentage}%"],
            ["Average Packet Loss", f"{bts_data['packet_loss']}%"],
            ["Average Latency", f"{bts_data['avg_latency']} ms"],
            ["Downtime Count", str(bts_data["downtime_count"])],
            ["Total Downtime", format_seconds(bts_data["total_downtime_seconds"])]
        ]
        
        stats_table = Table(stats_data, colWidths=[2.5*inch, 2.5*inch])
        stats_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (1, 0), colors.HexColor('#003366')),
            ('TEXTCOLOR', (0, 0), (1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 11),
            ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
            ('GRID', (0, 0), (-1, -1), 1, colors.grey),
        ]))
        story.append(stats_table)
        story.append(Spacer(1, 0.2*inch))
        
        # DOWNTIME HISTORY SECTION
        if bts_data.get("downtime_history"):
            story.append(Paragraph("Downtime History:", subheading_style))
            history_data = [["#", "Start Time", "End Time", "Duration"]]
            for idx, event in enumerate(bts_data["downtime_history"], 1):
                if event.get('end') and event['end'] != "ONGOING":
                    history_data.append([str(idx), event['start'], event['end'], format_seconds(event['duration_seconds'])])
                else:
                    history_data.append([str(idx), event['start'], "ONGOING", "In Progress"])
            
            history_table = Table(history_data, colWidths=[0.5*inch, 2.2*inch, 2.2*inch, 1.5*inch])
            history_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#0066AA')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('GRID', (0, 0), (-1, -1), 1, colors.grey),
            ]))
            story.append(history_table)
            story.append(Spacer(1, 0.1*inch))
        
        # PACKET LOSS HISTORY SECTION
        packet_loss_events = [log for log in packet_loss_logs[bts_data['ip']]['logs'] if 0 < log['packet_loss'] < 100]
        if packet_loss_events:
            story.append(Paragraph("Packet Loss History (when device was ONLINE):", subheading_style))
            
            pl_data = [["Timestamp", "Packet Loss %"]]
            
            for event in packet_loss_events[-20:]:
                pl_data.append([
                    event['timestamp'].strftime('%Y-%m-%d %H:%M:%S'),
                    f"{event['packet_loss']}%"
                ])
            
            pl_table = Table(pl_data, colWidths=[3*inch, 1.5*inch])
            
            style_commands = [
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#CC6600')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 10),
                ('GRID', (0, 0), (-1, -1), 1, colors.grey),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ]
            
            for i, event in enumerate(packet_loss_events[-20:], start=1):
                packet_loss = event['packet_loss']
                if packet_loss >= 20:
                    style_commands.append(('BACKGROUND', (1, i), (1, i), colors.HexColor('#FF0000')))
                    style_commands.append(('TEXTCOLOR', (1, i), (1, i), colors.whitesmoke))
                elif packet_loss >= 10:
                    style_commands.append(('BACKGROUND', (1, i), (1, i), colors.HexColor('#FFA500')))
                    style_commands.append(('TEXTCOLOR', (1, i), (1, i), colors.black))
            
            pl_table.setStyle(TableStyle(style_commands))
            story.append(pl_table)
        
        story.append(PageBreak())
    
    doc.build(story)
    print(f"[PDF GENERATED] {filename}")
    return filename

# =========================================================
# GENERATE REPORT
# =========================================================

def generate_summary_report(start_time, end_time, report_type="daily"):
    """Generate summary data considering only ACTUAL monitoring time"""
    summary_data = []
    
    gaps = get_monitoring_gaps_in_range(start_time, end_time)
    total_monitored_seconds = get_monitoring_time_in_range(start_time, end_time)
    
    total_period_seconds = int((end_time - start_time).total_seconds())
    monitoring_coverage = round((total_monitored_seconds / total_period_seconds) * 100, 2) if total_period_seconds > 0 else 0
    
    for ip, data in all_time_stats.items():
        period_downtimes = []
        period_downtime_total = 0
        period_downtime_count = 0
        
        # Process downtime history
        for downtime in data.get("downtime_history", []):
            # Handle ongoing downtimes
            if downtime.get('ongoing') and downtime.get('end') is None:
                downtime_start = datetime.strptime(downtime['start'], "%Y-%m-%d %H:%M:%S")
                if downtime_start < end_time:
                    overlap_end = min(end_time, datetime.now())
                    if overlap_end > downtime_start:
                        overlap_seconds = int((overlap_end - downtime_start).total_seconds())
                        period_downtime_total += overlap_seconds
                        period_downtime_count += 1
                        period_downtimes.append({
                            'start': downtime_start.strftime("%Y-%m-%d %H:%M:%S"),
                            'end': "ONGOING",
                            'duration_seconds': overlap_seconds
                        })
                continue
            
            # Handle closed downtimes
            if downtime.get('end') and downtime['end'] != "ONGOING":
                try:
                    downtime_start = datetime.strptime(downtime['start'], "%Y-%m-%d %H:%M:%S")
                    downtime_end = datetime.strptime(downtime['end'], "%Y-%m-%d %H:%M:%S")
                    
                    if downtime_end >= start_time and downtime_start <= end_time:
                        period_overlap_start = max(downtime_start, start_time)
                        period_overlap_end = min(downtime_end, end_time)
                        overlap_seconds = int((period_overlap_end - period_overlap_start).total_seconds())
                        
                        if overlap_seconds > 0:
                            period_downtime_total += overlap_seconds
                            period_downtime_count += 1
                            period_downtimes.append({
                                'start': period_overlap_start.strftime("%Y-%m-%d %H:%M:%S"),
                                'end': period_overlap_end.strftime("%Y-%m-%d %H:%M:%S"),
                                'duration_seconds': overlap_seconds
                            })
                except Exception as e:
                    print(f"[WARNING] Error parsing downtime: {e}")
        
        # Calculate AVERAGE packet loss - ONLY from events when device was ONLINE
        packet_loss_events = packet_loss_logs[ip]['logs']
        total_weighted_loss = 0
        total_duration = 0
        previous_timestamp = None
        previous_loss = None
        
        for event in packet_loss_events:
            event_time = event['timestamp']
            if start_time <= event_time <= end_time:
                if previous_timestamp is not None and previous_loss is not None:
                    duration = int((event_time - previous_timestamp).total_seconds())
                    total_weighted_loss += previous_loss * duration
                    total_duration += duration
                previous_timestamp = event_time
                previous_loss = event['packet_loss']
        
        if previous_timestamp is not None and previous_loss is not None:
            end_point = min(end_time, datetime.now())
            if previous_timestamp < end_point:
                duration = int((end_point - previous_timestamp).total_seconds())
                total_weighted_loss += previous_loss * duration
                total_duration += duration
        
        average_packet_loss = round(total_weighted_loss / total_duration, 2) if total_duration > 0 else 0
        
        # Calculate average latency
        if data.get("latencies"):
            period_latencies = data["latencies"]
            avg_latency = round(sum(period_latencies) / len(period_latencies), 2) if period_latencies else 0
        else:
            avg_latency = 0
        
        # Calculate uptime
        uptime = calculate_uptime(period_downtime_total, total_monitored_seconds)
        
        # Determine current status based on uptime/downtime
        if uptime > 0:
            current_status = "ONLINE"
        elif period_downtime_total > 0 and uptime == 0:
            current_status = "OFFLINE"
        else:
            current_status = "UNKNOWN"
        
        summary_data.append({
            "name": data["name"],
            "ip": ip,
            "uptime": uptime,
            "packet_loss": average_packet_loss,
            "avg_latency": avg_latency,
            "downtime_count": period_downtime_count,
            "total_downtime_seconds": period_downtime_total,
            "downtime_history": period_downtimes,
            "current_status": current_status,
            "monitoring_coverage": monitoring_coverage
        })
    
    return summary_data, gaps, monitoring_coverage

def generate_text_summary(summary_data, report_type, start_time, end_time, gaps, monitoring_coverage):
    summary_lines = []
    summary_lines.append(f"{report_type.upper()} NETWORK SUMMARY")
    summary_lines.append("=" * 50)
    
    if monitoring_coverage < 100:
        summary_lines.append(f"\nMONITORING COVERAGE: {monitoring_coverage}%")
        summary_lines.append(f"(Only {monitoring_coverage}% of the report period was monitored)\n")
    
    major_summary = [bts for bts in summary_data if bts["name"] in major_node_names]
    normal_summary = [bts for bts in summary_data if bts["name"] not in major_node_names]
    
    if major_summary:
        summary_lines.append("\n" + "=" * 60)
        summary_lines.append("MAJOR BTS SUMMARY (PRIORITY)")
        summary_lines.append("=" * 60)
        
        for idx, bts in enumerate(sorted(major_summary, key=lambda x: x['uptime'], reverse=True), 1):
            downtime_percentage = round(100 - bts['uptime'], 2)
            summary_lines.append(f"\n{idx}. {bts['name']}")
            summary_lines.append(f"   Status: {bts['current_status']}")
            summary_lines.append(f"   Uptime: {bts['uptime']}%")
            summary_lines.append(f"   Downtime: {downtime_percentage}%")
            summary_lines.append(f"   Packet Loss: {bts['packet_loss']}%")
            summary_lines.append(f"   Avg Latency: {bts['avg_latency']} ms")
            summary_lines.append(f"   Downtime Count: {bts['downtime_count']}")
            summary_lines.append(f"   Total Downtime: {format_seconds(bts['total_downtime_seconds'])}")
        
        avg_uptime_major = round(sum(bts['uptime'] for bts in major_summary) / len(major_summary), 2)
        summary_lines.append(f"\n{'-' * 60}")
        summary_lines.append(f"MAJOR BTS AVG UPTIME: {avg_uptime_major}%")
    
    if normal_summary:
        summary_lines.append("\n" + "=" * 60)
        summary_lines.append("OTHER BTS SUMMARY")
        summary_lines.append("=" * 60)
        
        for idx, bts in enumerate(sorted(normal_summary, key=lambda x: x['uptime'], reverse=True), 1):
            downtime_percentage = round(100 - bts['uptime'], 2)
            summary_lines.append(f"\n{idx}. {bts['name']}")
            summary_lines.append(f"   Status: {bts['current_status']}")
            summary_lines.append(f"   Uptime: {bts['uptime']}%")
            summary_lines.append(f"   Downtime: {downtime_percentage}%")
            summary_lines.append(f"   Packet Loss: {bts['packet_loss']}%")
            summary_lines.append(f"   Avg Latency: {bts['avg_latency']} ms")
            summary_lines.append(f"   Downtime Count: {bts['downtime_count']}")
            summary_lines.append(f"   Total Downtime: {format_seconds(bts['total_downtime_seconds'])}")
        
        avg_uptime_normal = round(sum(bts['uptime'] for bts in normal_summary) / len(normal_summary), 2)
        summary_lines.append(f"\n{'-' * 60}")
        summary_lines.append(f"OTHER BTS AVG UPTIME: {avg_uptime_normal}%")
    
    return "\n".join(summary_lines)

def generate_and_send_report(report_type, start_time, end_time):
    print(f"\n[REPORT] Generating {report_type.upper()} report...")
    
    gaps = get_monitoring_gaps_in_range(start_time, end_time)
    total_monitored = get_monitoring_time_in_range(start_time, end_time)
    total_period = int((end_time - start_time).total_seconds())
    coverage = round((total_monitored / total_period) * 100, 2) if total_period > 0 else 0
    
    print(f"  Total period: {format_seconds(total_period)}")
    print(f"  Monitored time: {format_seconds(total_monitored)}")
    print(f"  Coverage: {coverage}%")
    
    summary_data, gaps, monitoring_coverage = generate_summary_report(start_time, end_time, report_type)
    text_summary = generate_text_summary(summary_data, report_type, start_time, end_time, gaps, monitoring_coverage)
    ai_summary = generate_ai_noc_summary(summary_data, report_type, start_time, end_time, gaps, monitoring_coverage)
    
    print("\n" + "=" * 90)
    print(f"{report_type.upper()} REPORT SUMMARY")
    print(f"Period: {start_time.strftime('%Y-%m-%d %H:%M:%S')} - {end_time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Monitoring Coverage: {monitoring_coverage}%")
    print("=" * 90)
    print(text_summary)
    print("=" * 90)
    
    if ai_summary:
        print("\n" + "=" * 90)
        print("AI NOC ENGINEER SUMMARY")
        print("=" * 90)
        print(ai_summary)
        print("=" * 90)
    
    pdf_file = generate_pdf_report(summary_data, start_time, end_time, report_type, gaps)
    
    if email_config.get("enabled", False):
        send_email_report(report_type, start_time, end_time, pdf_file, text_summary, gaps, ai_summary)
    
    return pdf_file

# =========================================================
# SCHEDULER - FIXED
# =========================================================

def schedule_reports():
    global running
    
    # Track last report times to prevent duplicates
    last_reports = {
        "daily": None,
        "weekly": None,
        "monthly": None,
        "hourly": None,
        "custom": None
    }
    
    # Track last dates to prevent multiple reports on same day
    last_report_dates = {
        "daily": None,
        "weekly": None,
        "monthly": None
    }
    
    # Track last custom interval time
    last_custom_time = None
    
    print("[SCHEDULER] Report scheduler started")
    print("[SCHEDULER] Configuration loaded:")
    
    daily_config = schedule_config.get("daily_report", {})
    if daily_config.get("enabled", False):
        print(f"  - Daily reports: ENABLED at {daily_config.get('hour', 0):02d}:{daily_config.get('minute', 0):02d}")
    else:
        print("  - Daily reports: DISABLED")
    
    weekly_config = schedule_config.get("weekly_report", {})
    if weekly_config.get("enabled", False):
        days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        day_name = days[weekly_config.get('day_of_week', 0)]
        print(f"  - Weekly reports: ENABLED on {day_name} at {weekly_config.get('hour', 0):02d}:{weekly_config.get('minute', 1):02d}")
    else:
        print("  - Weekly reports: DISABLED")
    
    monthly_config = schedule_config.get("monthly_report", {})
    if monthly_config.get("enabled", False):
        print(f"  - Monthly reports: ENABLED on day {monthly_config.get('day_of_month', 1)} at {monthly_config.get('hour', 0):02d}:{monthly_config.get('minute', 0):02d}")
    else:
        print("  - Monthly reports: DISABLED")
    
    hourly_config = schedule_config.get("hourly_report", {})
    if hourly_config.get("enabled", False):
        print(f"  - Hourly reports: ENABLED at minute {hourly_config.get('minute', 0):02d} of every hour")
    else:
        print("  - Hourly reports: DISABLED")
    
    custom_config = schedule_config.get("custom_interval", {})
    if custom_config.get("enabled", False):
        print(f"  - Custom interval: ENABLED every {custom_config.get('interval_hours', 6)} hours")
    else:
        print("  - Custom interval: DISABLED")
    
    print("[SCHEDULER] Waiting for report triggers...\n")
    
    while running:
        now = datetime.now()
        
        # =========================================================
        # HOURLY REPORT
        # =========================================================
        hourly_config = schedule_config.get("hourly_report", {})
        if hourly_config.get("enabled", False):
            report_minute = hourly_config.get("minute", 0)
            current_hour_key = now.replace(minute=0, second=0, microsecond=0)
            
            if (now.minute == report_minute and 
                (last_reports["hourly"] != current_hour_key)):
                
                report_end = now.replace(minute=report_minute, second=0, microsecond=0)
                report_start = report_end - timedelta(hours=1)
                
                print(f"\n[SCHEDULER] Triggering HOURLY report at {now.strftime('%Y-%m-%d %H:%M:%S')}")
                print(f"  Period: {report_start.strftime('%Y-%m-%d %H:%M:%S')} - {report_end.strftime('%Y-%m-%d %H:%M:%S')}")
                
                try:
                    generate_and_send_report("hourly", report_start, report_end)
                    last_reports["hourly"] = current_hour_key
                    print(f"[SCHEDULER] Hourly report completed successfully")
                except Exception as e:
                    print(f"[SCHEDULER ERROR] Hourly report failed: {e}")
                    traceback.print_exc()
        
        # =========================================================
        # DAILY REPORT
        # =========================================================
        daily_config = schedule_config.get("daily_report", {})
        if daily_config.get("enabled", False):
            report_hour = daily_config.get("hour", 0)
            report_minute = daily_config.get("minute", 0)
            
            if (now.hour == report_hour and 
                now.minute == report_minute and 
                (last_report_dates["daily"] != now.date())):
                
                report_end = now.replace(hour=report_hour, minute=report_minute, second=0, microsecond=0)
                report_start = report_end - timedelta(days=1)
                
                print(f"\n[SCHEDULER] Triggering DAILY report at {now.strftime('%Y-%m-%d %H:%M:%S')}")
                print(f"  Period: {report_start.strftime('%Y-%m-%d %H:%M:%S')} - {report_end.strftime('%Y-%m-%d %H:%M:%S')}")
                
                try:
                    generate_and_send_report("daily", report_start, report_end)
                    last_reports["daily"] = now
                    last_report_dates["daily"] = now.date()
                    print(f"[SCHEDULER] Daily report completed successfully")
                except Exception as e:
                    print(f"[SCHEDULER ERROR] Daily report failed: {e}")
                    traceback.print_exc()
        
        # =========================================================
        # WEEKLY REPORT
        # =========================================================
        weekly_config = schedule_config.get("weekly_report", {})
        if weekly_config.get("enabled", False):
            report_day = weekly_config.get("day_of_week", 0)
            report_hour = weekly_config.get("hour", 0)
            report_minute = weekly_config.get("minute", 1)
            
            if (now.weekday() == report_day and 
                now.hour == report_hour and 
                now.minute == report_minute and
                (last_report_dates["weekly"] != now.date())):
                
                report_end = now.replace(hour=report_hour, minute=report_minute, second=0, microsecond=0)
                report_start = report_end - timedelta(days=7)
                
                print(f"\n[SCHEDULER] Triggering WEEKLY report at {now.strftime('%Y-%m-%d %H:%M:%S')}")
                print(f"  Period: {report_start.strftime('%Y-%m-%d %H:%M:%S')} - {report_end.strftime('%Y-%m-%d %H:%M:%S')}")
                
                try:
                    generate_and_send_report("weekly", report_start, report_end)
                    last_reports["weekly"] = now
                    last_report_dates["weekly"] = now.date()
                    print(f"[SCHEDULER] Weekly report completed successfully")
                except Exception as e:
                    print(f"[SCHEDULER ERROR] Weekly report failed: {e}")
                    traceback.print_exc()
        
        # =========================================================
        # MONTHLY REPORT
        # =========================================================
        monthly_config = schedule_config.get("monthly_report", {})
        if monthly_config.get("enabled", False):
            report_day = monthly_config.get("day_of_month", 1)
            report_hour = monthly_config.get("hour", 0)
            report_minute = monthly_config.get("minute", 0)
            
            if (now.day == report_day and 
                now.hour == report_hour and 
                now.minute == report_minute and
                (last_report_dates["monthly"] != now.date())):
                
                report_end = now.replace(hour=report_hour, minute=report_minute, second=0, microsecond=0)
                first_day_this_month = now.replace(day=1)
                last_day_prev_month = first_day_this_month - timedelta(days=1)
                first_day_prev_month = last_day_prev_month.replace(day=1)
                report_start = first_day_prev_month
                
                print(f"\n[SCHEDULER] Triggering MONTHLY report at {now.strftime('%Y-%m-%d %H:%M:%S')}")
                print(f"  Period: {report_start.strftime('%Y-%m-%d %H:%M:%S')} - {report_end.strftime('%Y-%m-%d %H:%M:%S')}")
                
                try:
                    generate_and_send_report("monthly", report_start, report_end)
                    last_reports["monthly"] = now
                    last_report_dates["monthly"] = now.date()
                    print(f"[SCHEDULER] Monthly report completed successfully")
                except Exception as e:
                    print(f"[SCHEDULER ERROR] Monthly report failed: {e}")
                    traceback.print_exc()
        
        # =========================================================
        # CUSTOM INTERVAL REPORT
        # =========================================================
        custom_config = schedule_config.get("custom_interval", {})
        if custom_config.get("enabled", False):
            interval_hours = custom_config.get("interval_hours", 6)
            
            if last_custom_time is None:
                last_custom_time = now
            else:
                hours_diff = (now - last_custom_time).total_seconds() / 3600
                if hours_diff >= interval_hours:
                    report_start = last_custom_time
                    report_end = now
                    
                    print(f"\n[SCHEDULER] Triggering CUSTOM INTERVAL report at {now.strftime('%Y-%m-%d %H:%M:%S')}")
                    print(f"  Interval: {interval_hours} hours")
                    print(f"  Period: {report_start.strftime('%Y-%m-%d %H:%M:%S')} - {report_end.strftime('%Y-%m-%d %H:%M:%S')}")
                    
                    try:
                        generate_and_send_report(f"{interval_hours}h", report_start, report_end)
                        last_custom_time = now
                        print(f"[SCHEDULER] Custom interval report completed successfully")
                    except Exception as e:
                        print(f"[SCHEDULER ERROR] Custom interval report failed: {e}")
                        traceback.print_exc()
        
        time.sleep(10)  # Check every 10 seconds

# =========================================================
# SIGNAL HANDLER
# =========================================================

def signal_handler(sig, frame):
    global running
    print("\n\n[SHUTDOWN] Stopping BTS Network Monitor...")
    running = False
    
    close_current_session()
    save_historical_stats()
    
    plt.close('all')
    gc.collect()
    
    print("[SHUTDOWN] Cleanup complete. Goodbye!")
    sys.exit(0)

# =========================================================
# MAIN MONITORING LOOP - FIXED
# =========================================================

def main():
    global running
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    atexit.register(close_current_session)
    atexit.register(save_historical_stats)
    
    load_monitoring_log()
    
    session_start = datetime.now()
    add_monitoring_session(session_start)
    
    # Perform initial status check
    initially_down = perform_initial_status_check()
    
    heartbeat_thread = threading.Thread(target=heartbeat, daemon=True)
    heartbeat_thread.start()
    
    print("\n" + "=" * 90)
    print("BTS NETWORK MONITORING SYSTEM WITH AI NOC")
    print("=" * 90)
    print(f"Monitoring {len(nodes)} BTS nodes")
    print(f"  - Major BTS: {len(major_nodes_list)} nodes")
    print(f"  - Other BTS: {len(normal_nodes_list)} nodes")
    print(f"Ping Interval: {PING_INTERVAL} seconds")
    print(f"Failure Threshold: {FAILURE_THRESHOLD} consecutive failures")
    
    if initially_down:
        print(f"\nNodes offline at startup: {', '.join(initially_down)}")
    
    if openai_client and openai_config.get("enabled", False):
        print(f"\nAI NOC Summary: ENABLED")
    else:
        print(f"\nAI NOC Summary: DISABLED")
    
    print("\nPress ENTER for immediate 24-hour report")
    print("=" * 90 + "\n")
    
    # Start scheduler thread
    scheduler_thread = threading.Thread(target=schedule_reports, daemon=True)
    scheduler_thread.start()
    
    # Keyboard listener for immediate reports
    def keyboard_listener():
        while running:
            input()
            if running:
                print("\n[MANUAL TRIGGER] Generating immediate 24-hour report...")
                now = datetime.now()
                last_24h = now - timedelta(hours=24)
                generate_and_send_report("24h", last_24h, now)
    
    listener_thread = threading.Thread(target=keyboard_listener, daemon=True)
    listener_thread.start()
    
    # Periodic stats save thread
    def periodic_stats_save():
        while running:
            time.sleep(300)
            if running:
                save_historical_stats()
    
    stats_save_thread = threading.Thread(target=periodic_stats_save, daemon=True)
    stats_save_thread.start()
    
    # Main monitoring loop
    while running:
        for node in nodes:
            if not running:
                break
                
            name = node["name"]
            ip = node["ip"]
            data = stats[ip]
            all_data = all_time_stats[ip]
            
            if all_data["first_seen"] is None:
                all_data["first_seen"] = datetime.now()
            all_data["last_seen"] = datetime.now()
            
            latency = ping_host(ip)
            current_time = datetime.now()
            current_time_str = current_time.strftime("%Y-%m-%d %H:%M:%S")
            
            if latency is not None:
                # SUCCESS - Node is online
                data["successful_pings"] += 1
                all_data["successful_pings"] += 1
                data["latencies"].append(latency)
                all_data["latencies"].append(latency)
                data["last_seen"] = current_time_str
                
                update_online_ping_history(ip, True, True)
                
                # CHECK FOR RECOVERY - Was it down before?
                if data.get("officially_down", False):
                    # RECOVERY DETECTED! Node came back online
                    downtime_end = current_time
                    downtime_start = data["downtime_start"]
                    
                    if downtime_start:
                        downtime_seconds = int((downtime_end - downtime_start).total_seconds())
                        
                        # Update current period stats
                        data["total_downtime_seconds"] += downtime_seconds
                        all_data["total_downtime_seconds"] += downtime_seconds
                        
                        # Create a CLOSED downtime event for current period stats
                        closed_event = {
                            "start": downtime_start.strftime("%Y-%m-%d %H:%M:%S"),
                            "end": downtime_end.strftime("%Y-%m-%d %H:%M:%S"),
                            "duration_seconds": downtime_seconds
                        }
                        data["downtime_history"].append(closed_event)
                        
                        # CRITICAL: Find and CLOSE the ongoing event in all_time_stats
                        found_and_closed = False
                        for i, event in enumerate(all_data["downtime_history"]):
                            if event.get("ongoing") and event.get("end") is None:
                                # Close this event
                                all_data["downtime_history"][i]["end"] = downtime_end.strftime("%Y-%m-%d %H:%M:%S")
                                all_data["downtime_history"][i]["duration_seconds"] = downtime_seconds
                                all_data["downtime_history"][i]["ongoing"] = False
                                found_and_closed = True
                                break
                        
                        # If no ongoing event was found, add the closed event
                        if not found_and_closed:
                            all_data["downtime_history"].append({
                                "start": downtime_start.strftime("%Y-%m-%d %H:%M:%S"),
                                "end": downtime_end.strftime("%Y-%m-%d %H:%M:%S"),
                                "duration_seconds": downtime_seconds,
                                "ongoing": False
                            })
                        
                        data["downtime_count"] += 1
                        all_data["downtime_count"] += 1
                        
                        # Reset packet loss history on recovery
                        packet_loss_logs[ip]["online_ping_history"].clear()
                        packet_loss_logs[ip]["logs"] = []
                        
                        print(f"\n[RECOVERED] {name} is BACK ONLINE! (Was down for: {format_seconds(downtime_seconds)})")
                
                # Reset failure counters
                data["consecutive_failures"] = 0
                data["first_failure_time"] = None
                data["officially_down"] = False
                data["downtime_start"] = None
                data["current_status"] = "ONLINE"
                
                if latency < 1000:
                    print(f"[{current_time_str}] {name} ONLINE {latency} ms")
                else:
                    print(f"[{current_time_str}] {name} ONLINE")
                
                # Calculate packet loss (only if device is online and not down)
                if not data.get("officially_down", False):
                    packet_loss = calculate_packet_loss_for_online_device(ip)
                    if 0 < packet_loss < 100:
                        log_packet_loss_event(ip, name, packet_loss, current_time)
            
            else:
                # FAILURE - Node is offline
                data["failed_pings"] += 1
                all_data["failed_pings"] += 1
                data["consecutive_failures"] += 1
                
                is_currently_online = not data.get("officially_down", False)
                update_online_ping_history(ip, False, is_currently_online)
                
                if data.get("first_failure_time") is None:
                    data["first_failure_time"] = current_time
                
                print(f"[{current_time_str}] {name} FAILED ({data['consecutive_failures']}/{FAILURE_THRESHOLD})")
                
                # Only calculate packet loss if still considered online
                if is_currently_online:
                    packet_loss = calculate_packet_loss_for_online_device(ip)
                    if 0 < packet_loss < 100:
                        log_packet_loss_event(ip, name, packet_loss, current_time)
                
                # Check if we should mark as officially DOWN
                if data["consecutive_failures"] >= FAILURE_THRESHOLD and not data.get("officially_down", False):
                    data["officially_down"] = True
                    data["downtime_start"] = data["first_failure_time"]
                    data["current_status"] = "OFFLINE"
                    
                    # Clear packet loss history when device goes down
                    packet_loss_logs[ip]["online_ping_history"].clear()
                    
                    # Add an ongoing downtime event to all_time_stats (only ONE)
                    # Check if there's already an ongoing event to prevent duplicates
                    has_ongoing = False
                    for event in all_data["downtime_history"]:
                        if event.get("ongoing") and event.get("end") is None:
                            has_ongoing = True
                            break
                    
                    if not has_ongoing:
                        downtime_event = {
                            "start": data["downtime_start"].strftime("%Y-%m-%d %H:%M:%S"),
                            "end": None,
                            "duration_seconds": 0,
                            "ongoing": True
                        }
                        all_data["downtime_history"].append(downtime_event)
                        all_data["downtime_count"] += 1
                    
                    print(f"\n[ALERT] {name} is now OFFLINE! (Started at: {data['downtime_start'].strftime('%Y-%m-%d %H:%M:%S')})")
        
        time.sleep(PING_INTERVAL)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n[SHUTDOWN] BTS Network monitor stopped by user")
        sys.exit(0)