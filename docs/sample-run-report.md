# Freight rate run `43eb4bfd-4a72-4ba6-bcc7-177c0bce75bf`

- **Status:** ✅ succeeded
- **Finished:** 2026-10-02 04:22 UTC
- **HTTP:** 9 requests, 2 retries, 39 KiB, status codes {200: 7, 503: 2}

## Pipeline

| Step | Count |
|---|---:|
| Extracted from `asl` | 101 |
| Extracted from `mcl` | 100 |
| Extracted from `ssc` | 101 |
| Valid rates | 290 |
| Rejected | 11 |
| Exact duplicates dropped | 1 |
| Loaded: new | 0 |
| Loaded: price changed | 66 |
| Loaded: unchanged | 224 |
| Published to logistics platform | 290 |
| Platform rejected | 0 |

## Data quality: rejected rows

| Source | Reason | Rows | Example |
|---|---|---:|---|
| `asl` | no price published | 6 | `asl/page-1.html#row-6`: no price published ('On request') |
| `asl` | unknown origin port | 1 | `asl/page-1.html#row-8`: unknown origin port 'Kuala Tanjung, Indonesia' |
| `mcl` | amount: Input should be greater than 0 | 1 | `mcl/rates.json#item-5`: amount: Input should be greater than 0 |
| `mcl` | unsupported container type | 1 | `mcl/rates.json#item-100`: unsupported container type '45'HC' |
| `ssc` | unknown destination port | 1 | `ssc/rates.csv#line-101`: unknown destination port 'XXXXX' |
| `ssc` | valid_to is before valid_from | 1 | `ssc/rates.csv#line-102`: valid_to is before valid_from |

## Biggest price moves

| Carrier | Lane | Container | Before | Now | Change |
|---|---|---|---:|---:|---:|
| SSC | THLCH → MMRGN | 20GP | 466.00 | 582.50 | +25.0% |
| MCL | SGSIN → MYPKG | 40HC | 523.60 | 654.50 | +25.0% |
| MCL | SGSIN → THLCH | 40GP | 564.80 | 694.70 | +23.0% |
| ASL | VNSGN → USLAX | 40GP | 1553.60 | 1895.39 | +22.0% |
| SSC | THLCH → JPTYO | 40HC | 991.10 | 1209.14 | +22.0% |
