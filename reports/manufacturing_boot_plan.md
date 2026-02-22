# 🧪 Manufacturing Test & Boot-up Plan (with Test Vectors)

This document provides the low-level sequence for initial silicon bring-up and high-volume manufacturing (HVM).

## 1. Power-On-Reset (PoR) Sequence
1.  **VDD_CORE (0.8V)**: Ramp to 90% in < 5ms.
2.  **VDDQ (0.3V)**: Initialize LPDDR5X interface.
3.  **Ref_Clk**: Verify 156.25 MHz differential stability.
4.  **RST_N**: Assert high to trigger Caliptra Boot.

## 2. Boot-up Security Handshake (DICE/SPDM)
| Step | Vector ID | Operation | Target |
| :--- | :--- | :--- | :--- |
| 1 | VEC_BOOT_01 | `0x384_SHA_START` | Caliptra Internal |
| 2 | VEC_DICE_02 | `GET_UDS_SECRET` | OTP Fuses |
| 3 | VEC_SPDM_03 | `AUTH_CERT_EXCHANGE` | Host <-> Switch |

## 3. Manufacturing Test Vectors (Scan/BIST)
*   **Vector Set A (Scan)**: `1.2M` patterns for stuck-at coverage.
*   **Vector Set B (Memory)**: `MARCH-C` algorithms for 1GB SRAM and 1TB DRAM pool.
*   **Vector Set C (IO)**: `PRBS-31` burst for 224G SerDes bit-error rate check.

## 4. Sample Test Vector Data (Mock)
```text
// Vector: VEC_RDMA_LOOPBACK_01
// Description: Verify packet framing through RDMA engine
INPUT:  [CLK=1, RST=1, DATA=512'hABCD_1234_..., VALID=1]
EXPECT: [FRAME_OUT=1024'h0000_..._ABCD_1234_..., VALID=1]
```
