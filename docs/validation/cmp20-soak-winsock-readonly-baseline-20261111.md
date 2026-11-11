# CMP-20: owner 15:45 JST signed soak checkpoint and WinSock diagnostic baseline (2026-11-11)

## Scope and authority
This is an actual **read-only** owner YWSHTMR observation during the existing 24-hour public canary. No additional Task, execution grant, source release, OS reboot, logoff, Tailscale Serve change, process stop, database change, or private key export occurred. Keep September Phase1–8 historical product acceptance separate from CMP-20 operations/campaign closure.

## Actual independent owner readbacks

Owner date/time: **2026-11-11 15:45 JST**. LastBootUpTime **2026-11-10 14:24:48.500 JST** (**2026-11-10 05:24:48.500Z**); no new Windows boot in this checkpoint.

| Evidence | Observed |
|---|---|
| Owner Task | `RinkaLegalKBPublicGuardedOnceV2`, **Ready**, exact `C:\Python314\python.exe -B ...\cmp20_public_guarded_owner_v2.py --once` |
| Native Task run | **15:45:01 JST**, `LastTaskResult=0`, `NumberOfMissedRuns=0`, next **15:50 JST** |
| Latest guardian receipt | checked **15:45:05.789 JST**; SHA256 **`f76b3018c95de645211be23280904703d0de2a44a3b0595d12a64f4cfb6c1d12`** |
| Receipt content | `status=PASS`, `source_signed=true`, `task_source_grant=V2_ED25519_TWO_ROLES`, `candidate_recovered=false`, `public_fallback_used=false`, `public_route=http://127.0.0.1:8879`, `no_old_pid_kill=true`, `no_os_reboot=true` |
| Actual listeners | private **8877 PID5740** / original public **8878 PID15900** / candidate public **8879 PID8976**, all `pythonw.exe` |
| Local GET | each of **8877 / 8878 / 8879** `/api/v1/health` returned **HTTP200** |
| Serve/Funnel | `ywshtmr.tail8fd68c.ts.net:8443` root → `http://127.0.0.1:8879`; Funnel enabled |
| Public GET | HTTPS8443 root and `/api/v1/health` **200**; `/api/v1/favorites` **404**; CSP present, `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff` |
| Independent V2 verification | Protected `cmp20_public_guarded_task_verify_v2.py --verify`: **PASS, exit 0**. Ed25519 V2 and prior V1 evidence match. Old public stop, existing Task change, OS reboot grants remain **false** |

The local owner FQDN test is **not** proof of an independent third-party external network. The latest receipt is overwritten by subsequent periodic runs and does **not** archive or prove every intervening 5-minute tick.

## WinError 10055: bounded actual diagnostic

The **historical failure** remains the 2026-11-01 07:13:20 JST exception in original public `select.select` / `socketserver.serve_forever`, recorded in [2026-11-10 recovery evidence](cmp20-public-demo-operational-recovery-20261110.md). The new signed V2 public overlay and guardian protect availability without assigning an unproven OS-wide cause.

This checkpoint's **current resource snapshot** (not a recreation of the November 1 fault):

- TCP connections **167 total**: Listen **63**, Established **42**, Bound **41**, TimeWait **18**, CloseWait **3**.
- Current process handles **124** (private 8877), **124** (old public 8878), **128** (candidate 8879); one thread each; no observed current listener absence.
- Physical memory **4,990 MiB free** of **15,959 MiB visible** at sampling.
- Read-only Windows System/Application event query for **2026-11-01 06:55–07:40 JST** yielded **1 System event, 7 Application events** in the bounded sample and **no Error/Critical matches**. Event retention, coverage and unrelated processes are not independently established, so absence of a match **does not** exclude historic resource pressure.

**Verdict: `WIN10055_OS_RESOURCE_ROOT_CAUSE_NOT_PROVEN`.** Do not claim the current counts explain historical resource pressure. No OS policy/registry changes, unreviewed packages, broad process termination or unsanctioned restarts.

## Next evidence and non-mutation boundary

1. Retain existing **one-time 2026-11-12 10:30 JST** 24-hour durability check. It must independently reread exact signed Task/receipt/boot/Funnel/HTTPS/private/listener/PID gates. Distinguish elapsed 24-hour endpoint from proof of **every** intermediate 5-minute tick.
2. Preserve the pre-joint-reboot exact baseline boot `2026-11-10T05:24:48.5000000Z` and the original/private/candidate services. User coordination and a separate physical-reboot authority are required; this V2 packet explicitly **does not** authorize Windows reboot.
3. At authorized shared CMP08/CMP24 reboot and owner relogin: prove an **actually later OS boot**, postboot natural V2 Task trigger and fresh PASS receipt timestamp, process creation after new boot, Funnel8443 still → 8879, secure root/health200, public favorites404, and original/private continuity. Run the separate [CMP08 cross-CMP postrelogin reader](https://github.com/watarionn/rinka-local-operator/blob/main/docs/campaigns/CMP08_JOINT_RESTART_CROSSCMP_READONLY_20261110.md) without treating its Task witnesses as full CMP24 acceptance.
4. iPhone/PWA owner confirmation, independent external-network accessibility and formal CMP20 campaign registration/closeout are separate future decisions. Planning registry `creation_authorized=false` / noncanonical remains unchanged.

Live owner evidence was also posted and independently read back at [LegalKB Issue #54 owner checkpoint](https://github.com/watarionn/legal-knowledge-base/issues/54#issuecomment-6789102728).
