#!/usr/bin/env python3
# NOTE (P4a): this logic now lives in src/fraud/ml.py (record-level scoring,
# two bug fixes, config-driven). This file is kept unchanged for reference.
"""
ML-Based Anomaly Detection Layer (Hybrid Approach)
Complements the deterministic rule-based scanner with statistical outlier detection.

Uses IsolationForest to find patterns that don't fit the rules but are still suspicious.
"""

import pandas as pd
import numpy as np
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler
import json
from pathlib import Path
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class MLAnomalyDetector:
    """
    Hybrid ML-based fraud detection to supplement rule-based approach.
    
    Philosophy:
    - Rules catch KNOWN fraud patterns (9999999999, WorkCode_000, etc.)
    - ML catches UNKNOWN statistical anomalies (unusual behavior patterns)
    """
    
    def __init__(self, contamination=0.05):
        """
        Args:
            contamination: Expected proportion of outliers (default 5%)
        """
        self.contamination = contamination
        self.scaler = StandardScaler()
        self.models = {
            'civil_registry': IsolationForest(contamination=contamination, random_state=42),
            'mgnrega': IsolationForest(contamination=contamination, random_state=42),
            'pmjay': IsolationForest(contamination=contamination, random_state=42)
        }
        self.anomaly_reports = []
    
    def detect_civil_registry_anomalies(self, df):
        """Detect anomalies in beneficiary data using statistical patterns"""
        logger.info("[ML] Analyzing Civil Registry for statistical anomalies...")
        
        # Feature engineering: Convert to numerical features
        features = df.copy()
        features['MobileNumber_numeric'] = pd.to_numeric(features['MobileNumber'], errors='coerce').fillna(0)
        features['JobCard_exists'] = features['JobCardID'].notna().astype(int)
        features['Gender_encoded'] = features['Gender'].map({'M': 0, 'F': 1, 'O': 2}).fillna(0)
        
        # Family size (how many people in same family)
        family_counts = features['FamilyID'].value_counts()
        features['FamilySize'] = features['FamilyID'].map(family_counts).fillna(1)
        
        # Select numerical columns for anomaly detection
        X = features[['Age', 'MobileNumber_numeric', 'JobCard_exists', 'Gender_encoded', 'FamilySize']].fillna(0)
        
        # Normalize and detect anomalies
        X_scaled = self.scaler.fit_transform(X)
        predictions = self.models['civil_registry'].fit_predict(X_scaled)
        
        # Extract anomalies (-1 means outlier)
        anomaly_mask = predictions == -1
        anomalies = df[anomaly_mask].copy()
        
        logger.info(f"[ML] Found {len(anomalies)} statistical anomalies in Civil Registry")
        return anomalies, self.models['civil_registry'].score_samples(X_scaled)
    
    def detect_mgnrega_anomalies(self, df):
        """Detect anomalies in MGNREGA transaction patterns"""
        logger.info("[ML] Analyzing MGNREGA for statistical anomalies...")
        
        # Feature engineering
        features = df.copy()
        features['DaysWorked'] = features['DaysWorked'].fillna(0)
        features['WageRate'] = features['WageRate'].fillna(0)
        features['TotalAmount'] = features['TotalAmount'].fillna(0)
        
        # Calculate derived features
        features['Amount_per_day'] = np.where(
            features['DaysWorked'] > 0,
            features['TotalAmount'] / features['DaysWorked'],
            0
        )
        
        # JobCard frequency (how often each card is used)
        card_counts = features['JobCardID'].value_counts()
        features['JobCard_frequency'] = features['JobCardID'].map(card_counts).fillna(0)
        
        X = features[['DaysWorked', 'WageRate', 'TotalAmount', 'Amount_per_day', 'JobCard_frequency']].fillna(0)
        
        X_scaled = self.scaler.fit_transform(X)
        predictions = self.models['mgnrega'].fit_predict(X_scaled)
        
        anomaly_mask = predictions == -1
        anomalies = df[anomaly_mask].copy()
        
        logger.info(f"[ML] Found {len(anomalies)} statistical anomalies in MGNREGA")
        return anomalies, self.models['mgnrega'].score_samples(X_scaled)
    
    def detect_pmjay_anomalies(self, df):
        """Detect anomalies in medical claim patterns"""
        logger.info("[ML] Analyzing PM-JAY for statistical anomalies...")
        
        features = df.copy()
        
        # Convert dates to numerical
        features['AdmissionDate'] = pd.to_datetime(features['AdmissionDate'], errors='coerce')
        features['DischargeDate'] = pd.to_datetime(features['DischargeDate'], errors='coerce')
        features['LengthOfStay'] = (features['DischargeDate'] - features['AdmissionDate']).dt.days.fillna(0)
        
        # Hospital frequency
        hospital_counts = features['HospitalID'].value_counts()
        features['Hospital_claim_frequency'] = features['HospitalID'].map(hospital_counts).fillna(0)
        
        # Procedure encoding (top 10 procedures, rest = 0)
        top_procedures = features['ProcedureName'].value_counts().head(10).index
        features['Procedure_encoded'] = features['ProcedureName'].apply(
            lambda x: list(top_procedures).index(x) if x in top_procedures else 0
        )
        
        X = features[[
            'ClaimAmount',
            'LengthOfStay',
            'Hospital_claim_frequency',
            'Procedure_encoded'
        ]].fillna(0)
        
        X_scaled = self.scaler.fit_transform(X)
        predictions = self.models['pmjay'].fit_predict(X_scaled)
        
        anomaly_mask = predictions == -1
        anomalies = df[anomaly_mask].copy()
        
        logger.info(f"[ML] Found {len(anomalies)} statistical anomalies in PM-JAY")
        return anomalies, self.models['pmjay'].score_samples(X_scaled)
    
    def run_all_detections(self):
        """Run ML anomaly detection across all domains"""
        print("\n" + "="*70)
        print("  ML ANOMALY DETECTION LAYER")
        print("  Isolation Forest | Statistical Outlier Detection")
        print("="*70 + "\n")
        
        results = {}
        
        # Domain 1: Civil Registry
        df_ben = pd.read_csv('data/beneficiaries.csv')
        civil_anomalies, civil_scores = self.detect_civil_registry_anomalies(df_ben)
        results['civil_registry'] = {
            'total_records': len(df_ben),
            'anomalies_detected': len(civil_anomalies),
            'anomaly_rate': f"{len(civil_anomalies) / len(df_ben) * 100:.2f}%"
        }
        
        # Domain 2: MGNREGA
        df_mgn = pd.read_csv('data/transactions_mgnrega.csv')
        mgnrega_anomalies, mgnrega_scores = self.detect_mgnrega_anomalies(df_mgn)
        results['mgnrega'] = {
            'total_records': len(df_mgn),
            'anomalies_detected': len(mgnrega_anomalies),
            'anomaly_rate': f"{len(mgnrega_anomalies) / len(df_mgn) * 100:.2f}%"
        }
        
        # Domain 3: PM-JAY
        df_pmjay = pd.read_csv('data/transactions_pmjay.csv')
        pmjay_anomalies, pmjay_scores = self.detect_pmjay_anomalies(df_pmjay)
        results['pmjay'] = {
            'total_records': len(df_pmjay),
            'anomalies_detected': len(pmjay_anomalies),
            'anomaly_rate': f"{len(pmjay_anomalies) / len(df_pmjay) * 100:.2f}%"
        }
        
        # Print summary
        print("\n[ML ANOMALY DETECTION SUMMARY]")
        print(f"  Civil Registry: {results['civil_registry']['anomalies_detected']:,} / {results['civil_registry']['total_records']:,} ({results['civil_registry']['anomaly_rate']})")
        print(f"  MGNREGA: {results['mgnrega']['anomalies_detected']:,} / {results['mgnrega']['total_records']:,} ({results['mgnrega']['anomaly_rate']})")
        print(f"  PM-JAY: {results['pmjay']['anomalies_detected']:,} / {results['pmjay']['total_records']:,} ({results['pmjay']['anomaly_rate']})")
        print(f"\n  Total ML-detected anomalies: {results['civil_registry']['anomalies_detected'] + results['mgnrega']['anomalies_detected'] + results['pmjay']['anomalies_detected']:,}")
        
        # Save ML report
        Path("output/reports").mkdir(parents=True, exist_ok=True)
        with open('output/reports/ml_anomaly_report.json', 'w') as f:
            json.dump(results, f, indent=2)
        
        print(f"\n[SUCCESS] ML report exported to: output/reports/ml_anomaly_report.json")
        print("="*70)
        
        return results


def main():
    """Run standalone ML anomaly detection"""
    detector = MLAnomalyDetector(contamination=0.05)  # Expect 5% anomalies
    results = detector.run_all_detections()
    
    print("\n💡 NOTE: ML anomalies are DIFFERENT from rule-based fraud flags:")
    print("   - Rules catch KNOWN patterns (dummy mobile, ghost projects)")
    print("   - ML catches UNKNOWN statistical outliers (unusual behavior)")
    print("   - Best approach: Investigate records flagged by BOTH systems first!")


if __name__ == "__main__":
    main()
