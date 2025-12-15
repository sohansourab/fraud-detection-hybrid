clean md:
# 🔍 Fraud Detection non Agent - Project Summary

## 📋 Overview

Built a **deterministic fraud detection system** for Indian Government welfare schemes that scans beneficiary and transaction data to identify suspicious patterns and automatically generates legal notices.

---

## 🏗️ Architecture

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────────┐     ┌─────────────────┐
│   CSV Datasets  │ --> │ audit_scanner.py │ --> │ fraud_report.json   │ --> │ PDF Notices     │
│   (3 domains)   │     │ (12 rules)       │     │ (flagged records)   │     │ (per domain)    │
└─────────────────┘     └──────────────────┘     └─────────────────────┘     └─────────────────┘
```

---

## 📊 Domains & Rules Implemented

### Domain 1: Civil Registry (Identity Fraud)
**Dataset:** `data/beneficiaries.csv`

| Rule | Pattern Name | Logic | Risk Score |
|------|--------------|-------|------------|
| RULE_001 | Mob of 999 | `MobileNumber == "9999999999"` | 25 |
| RULE_002 | Child Labor | `Age < 18 AND JobCardID exists` | 25 |
| RULE_003 | Centenarian Ghost | `Age > 100` | 25 |
| RULE_004 | Mega Family | `FamilyID member count > 15` | 25 |

---

### Domain 2: MGNREGA Labor Fraud
**Dataset:** `data/transactions_mgnrega.csv`

| Rule | Pattern Name | Logic | Risk Score |
|------|--------------|-------|------------|
| RULE_005 | Impossible Human | `DaysWorked > 15` | 25 |
| RULE_006 | Ghost Project | `WorkCode ends with _000` | 25 |
| RULE_007 | Wage Theft | `TotalAmount != Days * WageRate` | 25 |
| RULE_008 | Free Money | `Days == 0 AND Amount > 0` | 25 |

---

### Domain 3: PM-JAY Medical Fraud
**Dataset:** `data/transactions_pmjay.csv`

| Rule | Pattern Name | Logic | Risk Score |
|------|--------------|-------|------------|
| RULE_009 | Time Travel | `DischargeDate < AdmissionDate` | 25 |
| RULE_010 | Biological Mismatch | `Gender == 'M' AND Procedure == 'Hysterectomy'` | 25 |
| RULE_011 | Massive Upcoding | `Procedure == 'General Ward' AND Amount > 50000` | 25 |
| RULE_012 | Blacklisted Hospital | `HospitalID == 'HOSP_999'` | 25 |

---

## 📁 Project Structure

```
promptpirates/
├── data/
│   ├── beneficiaries.csv          # Civil Registry data (2000 records)
│   ├── transactions_mgnrega.csv   # MGNREGA transactions (5000 records)
│   └── transactions_pmjay.csv     # PM-JAY claims (3000 records)
├── output/
│   ├── reports/
│   │   └── fraud_report.json      # Scan results
│   └── notices/
│       ├── civil_registry/        # Civil Registry PDFs
│       ├── mgnrega_labor/         # MGNREGA PDFs
│       └── pm-jay_medical/        # PM-JAY PDFs
├── docs/
│   └── PROJECT_SUMMARY.md         # This file
├── audit_scanner.py               # Main fraud scanner (12 rules)
└── show_cause_notice.py           # PDF notice generator
```

---

## 📈 Scan Results

| Metric | Value |
|--------|-------|
| **Total Records Scanned** | 10,000 |
| **Total Flagged** | 981 |
| **Flag Rate** | 9.81% |

### By Domain

| Domain | Records | Flagged | Rate |
|--------|---------|---------|------|
| Civil Registry | 2,000 | 386 | 19.30% |
| MGNREGA Labor | 5,000 | 243 | 4.86% |
| PM-JAY Medical | 3,000 | 352 | 11.73% |

### Risk Distribution

| Risk Level | Score Range | Count |
|------------|-------------|-------|
| LOW | 0-25 | 900+ |
| MEDIUM | 26-50 | 50+ |
| HIGH | 51-75 | 20+ |
| CRITICAL | 76+ | 10+ |

---

## 🛠️ Key Features

### audit_scanner.py
- ✅ O(N) linear scan optimization
- ✅ Pre-computed lookups (family sizes, beneficiary data)
- ✅ Multi-domain support with separate scanner classes
- ✅ Structured JSON output with metadata

### show_cause_notice.py
- ✅ Domain-specific PDF templates
- ✅ Unicode sanitization for PDF compatibility
- ✅ Risk-based color coding
- ✅ Organized output folders by domain
- ✅ Domain-specific document requirements

---

## 🚀 How to Run

```bash
cd /home/sohansourab/Documents/promptpirates

# Step 1: Generate fraud report
python audit_scanner.py

# Step 2: Generate PDF notices
python show_cause_notice.py
```

---

## 🔜 Next Steps (Future Enhancements)

| Phase | Description | Status |
|-------|-------------|--------|
| **Agentic AI** | LLM-based fraud explanation | Pending |
| **ML Models** | Anomaly detection, clustering | Pending |
| **API Integration** | Aadhaar verification, SMS alerts | Pending |
| **Dashboard** | Real-time monitoring UI | Pending |

---

## 📌 Tech Stack

- **Language:** Python 3.13
- **Libraries:** pandas, fpdf, pathlib, dataclasses
- **Output:** JSON reports, PDF notices
- **Approach:** Deterministic rule-based (no ML yet)

---

**Status: ✅ Phase 1 Complete (Deterministic Rules)**
