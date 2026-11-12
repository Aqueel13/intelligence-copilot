---
id: AP-105
title: Duplicate Invoice Prevention
doc_type: sop
version: "1.1"
effective_date: 2025-01-01
status: current
owner: AP Manager
---

# Duplicate Invoice Prevention

Varaha Auto Components Pvt. Ltd. (fictional)

## 1. Purpose

Prevents the same invoice from being paid twice, whatever channel it arrives through.

## 2. Checks at capture

2.1 The ERP blocks an invoice whose **supplier GSTIN, invoice number and invoice date** match an invoice already captured.

2.2 A soft warning is raised when the supplier, amount and date match but the invoice number differs by one or two characters. The capturer must check the original before continuing.

## 3. Checks before payment

3.1 The payment proposal is screened for the same supplier and amount within 30 days. Hits are held for review by AP Matching.

3.2 Duplicates found are cancelled and the supplier is informed. Fewer than 0.2% of invoices are held as possible duplicates; most are resubmissions of a paper invoice that was also e-mailed.

## 4. Responsibilities

AP Matching reviews holds within 1 working day. The AP Manager reports duplicate payments recovered every quarter.
