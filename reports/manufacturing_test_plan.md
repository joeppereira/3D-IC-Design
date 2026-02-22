# 🧪 Manufacturing Test Plan: Search King 1TB CXL Switch

## 1. DFT Strategy
*   **Scan Chains**: 12,000 internal chains per die to ensure >99.2% stuck-at coverage.
*   **At-Speed Test**: Targeted transition-fault testing at 2GHz operation.

## 2. Integrated BIST
*   **Memory BIST (MBIST)**: Dual-pattern algorithms for the 1GB stacked SRAM and 1TB LPDDR5X pool.
*   **Logic BIST (LBIST)**: Self-test logic for the CXL PBR manager.

## 3. SI Margin Test
*   **On-die Eye Monitor**: SerDes macros include dedicated eye-sampling circuits to monitor SNR in the field.
*   **Loopback**: Full PRBS-31 support for PCIe 7.0 and RDMA validation at board level.

## 4. Security Verification
*   **SPDM Identity**: Factory-burned Unique Device Secret (UDS) used for DICE attestation during boot.
