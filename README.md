# BTS Network Monitor & AI NOC System

[![Python](https://img.shields.io/badge/Python-3.12+-blue.svg)](https://python.org)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![OpenAI](https://img.shields.io/badge/OpenAI-API-412991.svg)](https://openai.com)
[![ReportLab](https://img.shields.io/badge/ReportLab-PDF-red.svg)](https://www.reportlab.com)

## 📡 Overview

**BTS Network Monitor** is a real-time network monitoring system designed for Base Transceiver Station (BTS) infrastructure. It tracks uptime, downtime, packet loss, and latency across multiple network nodes, generates professional PDF reports, and uses OpenAI to produce intelligent NOC-style summaries.

### Key Features

- ✅ **Real-time Monitoring** - Pings nodes every 5 seconds with configurable thresholds
- 📊 **Packet Loss Analysis** - Sliding window calculation (configurable 30-60 seconds)
- 🔔 **Downtime Detection** - Automatic outage detection and recovery tracking
- 📄 **PDF Reports** - Professional reports with pie charts, downtime history, and packet loss logs
- 🤖 **AI NOC Summaries** - OpenAI-powered network analysis with severity classification
- 📧 **Email Alerts** - Automatic email distribution with PDF attachments
- 🔄 **Crash Recovery** - Persistent logging and state reconciliation
- ⏰ **Scheduled Reports** - Daily, weekly, monthly, hourly, or custom intervals

## 🏗️ Architecture
