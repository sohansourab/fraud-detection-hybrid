# 🔍 Multi-Domain Fraud Detection System with Hybrid AI

## 📋 Overview

A comprehensive **hybrid fraud detection system** combining **deterministic rule-based scanning** (16 rules) and **ML-based anomaly detection** for Indian Government welfare schemes. The system scans beneficiary and transaction data across 3 domains to identify fraud patterns and automatically generates legal notices.

**Approach:** Option C - Hybrid (Deterministic Rules + Machine Learning)

---

## 🏗️ System Architecture

```
┌─────────────────────┐
│  Data Generation    │
│ data_simulator.py   │ ──> Synthetic data with fraud contamination
└─────────────────────┘
           │
           ↓
┌─────────────────────────────────────────────────────────────┐
│              HYBRID DETECTION LAYER                         │
├─────────────────────────────────────────────────────────────┤
│  ┌──────────────────────┐    ┌──────────────────────────┐  │
│  │  Rule-Based Scanner  │    │   ML Anomaly Detector    │  │
│  │  audit_scanner.py    │    │ ml_anomaly_detector.py   │  │
│  │  (16 Rules)          │    │  (IsolationForest)       │  │
│  └──────────────────────┘    └──────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
           │                              │
           ↓                              ↓
┌─────────────────────┐      ┌─────────────────────┐
│ fraud_report.json   │      │ ml_anomaly_report   │
│ (1,776 flagged)     │      │ (502 anomalies)     │
└─────────────────────┘      └─────────────────────┘
           │
           ↓
┌─────────────────────┐
│ show_cause_notice   │
│ (PDF Generator)     │ ──> 1,776 Legal Notices
└─────────────────────┘
```

---

## 🎯 Detection Rules (16 Total)

### Domain 1: Civil Registry (Identity Fraud) - 5 Rules

| Rule | Pattern | Logic | Risk Score |
|------|---------|-------|------------|
| **RULE_001** | Invalid Mobile | Mobile = 9999999999 | 25 |
| **RULE_002** | Underage Job Card | Age < 18 AND has JobCard | 25 |
| **RULE_003** | Suspicious Age | Age > 100 years | 25 |
| **RULE_004** | Mega Family | Family size > 15 members | 25 |
| **RULE_013** | Clone Detection | Mobile shared by >3 people | 30 |

---

### Domain 2: MGNREGA Labor Fraud - 5 Rules

| Rule | Pattern | Logic | Risk Score |
|------|---------|-------|------------|
| **RULE_005** | Impossible Human | DaysWorked > 15 per cycle | 25 |
| **RULE_006** | Ghost Project | WorkCode ends with _000 | 25 |
| **RULE_007** | Wage Theft | Amount ≠ Days × WageRate | 25 |
| **RULE_008** | Free Money | Days = 0 AND Amount > 0 | 25 |
| **RULE_017** | Muster Roll Cartel | Same workers in >80% of rolls | 35 |

---

### Domain 3: PM-JAY Medical Fraud - 4 Rules

| Rule | Pattern | Logic | Risk Score |
|------|---------|-------|------------|
| **RULE_009** | Time Travel | DischargeDate < AdmissionDate | 25 |
| **RULE_010** | Biological Mismatch | Male + Hysterectomy | 25 |
| **RULE_011** | Massive Upcoding | General Ward > Rs.50,000 | 25 |
| **RULE_012** | Blacklisted Hospital | HospitalID = HOSP_999 | 25 |
| **RULE_021** | Procedure Mill | Same procedure >50 times/month | 35 |

---

### Cross-Domain Analysis - 1 Rule

| Rule | Pattern | Logic | Risk Score |
|------|---------|-------|------------|
| **RULE_025** | Multi-Scheme Velocity | Flagged in 2+ domains | 40 |

---

## 🤖 ML Anomaly Detection Layer

**Algorithm:** IsolationForest (Unsupervised Learning)

**Purpose:** Detect statistical outliers that don't match known fraud patterns

**Features Used:**
- **Civil Registry:** Age, Mobile patterns, Family size, JobCard presence
- **MGNREGA:** DaysWorked, WageRate, Amount/day ratio, JobCard frequency
- **PM-JAY:** Claim amount, Length of stay, Hospital frequency, Procedure type

**Results:**
- Civil Registry: 100 anomalies (5.00%)
- MGNREGA: 252 anomalies (5.01%)
- PM-JAY: 150 anomalies (5.00%)
- **Total: 502 statistical anomalies**

---

## 📁 Project Structure

```
promptpirates/
├── data/
│   ├── beneficiaries.csv              # 2,000 beneficiaries
│   ├── transactions_mgnrega.csv       # 5,027 labor transactions
│   └── transactions_pmjay.csv         # 3,000 medical claims
│
├── output/
│   ├── reports/
│   │   ├── fraud_report.json          # Rule-based scan results
│   │   ├── ml_anomaly_report.json     # ML anomaly results
│   │   └── fraud_ground_truth.json    # Expected fraud counts
│   └── notices/
│       ├── civil_registry/            # 296 PDF notices
│       ├── mgnrega_labor/             # 1,118 PDF notices
│       └── pm-jay_medical/            # 362 PDF notices
│
├── audit_scanner.py                   # Rule-based fraud scanner (16 rules)
├── ml_anomaly_detector.py             # ML anomaly detector
├── data_simulator.py                  # Synthetic data generator
├── show_cause_notice.py               # PDF legal notice generator
├── requirements.txt                   # Python dependencies
├── FRAUD_DETECTION_VALIDATION.md      # Accuracy analysis
└── README.md                          # This file
```

---

## 📊 Detection Results

### Rule-Based Detection

| Metric | Value |
|--------|-------|
| **Total Records Scanned** | 10,000 |
| **Total Flagged** | 1,776 |
| **Total Flags** | 2,244 |
| **Detection Rate** | 17.76% |

#### By Domain

| Domain | Records | Flagged | Rate |
|--------|---------|---------|------|
| Civil Registry | 2,000 | 296 | 14.80% |
| MGNREGA Labor | 5,027 | 1,118 | 22.24% |
| PM-JAY Medical | 3,000 | 362 | 12.07% |

#### By Rule

| Rule | Flags | Rule | Flags |
|------|-------|------|-------|
| RULE_001 | 94 | RULE_009 | 89 |
| RULE_002 | 65 | RULE_010 | 31 |
| RULE_003 | 34 | RULE_011 | 139 |
| RULE_004 | 84 | RULE_012 | 114 |
| RULE_005 | 302 | RULE_013 | 107 |
| RULE_006 | 267 | RULE_017 | Network* |
| RULE_007 | 409 | RULE_021 | Network* |
| RULE_008 | 210 | RULE_025 | 99 |

*Network-based rules embedded in transaction flags

#### Risk Distribution

| Risk Level | Score Range | Count | Priority |
|------------|-------------|-------|----------|
| **CRITICAL** | 76-100 | 18 | Immediate action |
| **HIGH** | 51-75 | 137 | Urgent investigation |
| **MEDIUM** | 26-50 | 127 | Review required |
| **LOW** | 1-25 | 1,494 | Routine follow-up |

---

## 🚀 Quick Start

### Prerequisites

```bash
Python 3.13+
pip install pandas fpdf2 Faker scikit-learn numpy
```

### Installation

```bash
git clone https://github.com/yourusername/promptpirates.git
cd promptpirates
pip install -r requirements.txt
```

### Usage

**Step 1: Generate Synthetic Data**
```bash
python data_simulator.py
```
Output: `data/beneficiaries.csv`, `transactions_mgnrega.csv`, `transactions_pmjay.csv`

**Step 2: Run Rule-Based Fraud Scanner**
```bash
python audit_scanner.py
```
Output: `output/reports/fraud_report.json`

**Step 3: Run ML Anomaly Detector**
```bash
python ml_anomaly_detector.py
```
Output: `output/reports/ml_anomaly_report.json`

**Step 4: Generate Legal Notices**
```bash
python show_cause_notice.py
```
Output: `output/notices/{domain}/*.pdf`

---

## 🔬 Validation & Accuracy

**Detection Accuracy:** 99.1% (validated against ground truth)

| Rule | Expected | Detected | Accuracy |
|------|----------|----------|----------|
| RULE_001-012 | 1,850 | 1,833 | 99.1% |
| RULE_013 | ~100 | 107 | ✅ |
| RULE_017 | ~200 | Cartel-based | ✅ |
| RULE_021 | ~150 | 183 | ✅ |
| RULE_025 | Dynamic | 99 | ✅ |

See [FRAUD_DETECTION_VALIDATION.md](FRAUD_DETECTION_VALIDATION.md) for detailed analysis.

---

## 💡 Key Features

### 1. Hybrid Detection
- ✅ **Deterministic Rules:** Catch KNOWN fraud patterns
- ✅ **ML Anomalies:** Detect UNKNOWN statistical outliers
- ✅ **Best Practice:** Investigate records flagged by BOTH systems

### 2. Multi-Domain Support
- ✅ Identity fraud (Civil Registry)
- ✅ Labor fraud (MGNREGA)
- ✅ Medical fraud (PM-JAY)
- ✅ Cross-domain correlation

### 3. Network Analysis
- ✅ Mobile sharing rings (Clone Detection)
- ✅ Worker cartels (Muster Roll Cartel)
- ✅ Hospital mills (Procedure Mill)
- ✅ Multi-scheme fraudsters (Velocity)

### 4. Automated Notice Generation
- ✅ Domain-specific templates
- ✅ Risk-based prioritization
- ✅ Legal framework compliance
- ✅ Evidence documentation

---

## 🎯 Use Cases

1. **Government Auditors:** Automated fraud detection across welfare schemes
2. **Policy Makers:** Identify systemic fraud patterns for policy reform
3. **Law Enforcement:** Evidence-based prosecution with documented violations
4. **Researchers:** Study fraud patterns in public welfare systems
5. **ML Training:** Labeled dataset for supervised learning models

---

## 📈 Future Enhancements

### Phase 2: Multi-Agent Architecture (Planned)
- ✅ BaseAgent with LLM reasoning
- ✅ Domain-specific agents (CivilRegistryAgent, MGNREGAAgent, PMJAYAgent)
- ✅ SupervisorAgent for orchestration
- ✅ Cross-domain correlation engine
- ✅ Active learning from auditor feedback

### Additional Rules (Tier 2 & 3)
- Rule 14: Duplicate Aadhaar patterns
- Rule 15: Geographic impossibility
- Rule 16: Rapid family expansion
- Rule 18: Payment velocity anomaly
- Rule 19: Wage rate arbitrage
- Rule 20: Dormant reactivation
- Rule 22: Readmission churning
- Rule 23: Geographic distance anomaly
- Rule 24: Claim timing patterns
- Rule 26: Family network fraud
- Rule 27: Address clustering
- Rule 28: Sudden death paradox

---

## 🤝 Contributing

Contributions welcome! Areas of interest:
- Additional fraud rules
- New ML algorithms (Autoencoders, Graph Neural Networks)
- Real-world dataset integration
- Performance optimization
- Multi-agent system implementation

---

## 📄 License

MIT License - See LICENSE file for details

---

## 👥 Authors

Built for the Digital India Initiative - Fraud Detection Unit

**Project Type:** Deterministic + ML Hybrid Fraud Detection System

**Tech Stack:** Python, Pandas, scikit-learn, FPDF2, Faker

---

## 📞 Contact

For questions or collaboration: [Your Contact Info]

---

**⚠️ Disclaimer:** This is a demonstration system using synthetic data. For production use, integrate with actual government databases and legal frameworks.
