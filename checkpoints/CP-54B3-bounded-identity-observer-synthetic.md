# CP-54B3 — bounded active-session identity observer / synthetic checkpoint

Date: 2026-10-10. Owner: rassvetpublic-spec/Rassvet_AI_Fabric, branch AG_pather.
Source HEAD at start: ad722142b3c6e9e615314ac4237dfdc089765813.

## Status
SOURCE_READY / SYNTHETIC_11_OF_11_PASS / WINDOWS_HOST_NOT_RUN / LIVE_IDENTITY_NOT_TESTED.
This is not G2 account attribution or permission to switch accounts.

## Evidence and scope
- CP54B2 project MD/JSON handoff and Tower noncanon PR #29 were read. All cursors remain project-owned.
- BPR40 Router v18 / BPR40 4.0.3 exact hashes verified: Router e9d8cae1c371ba6cbac6904bda8d8070b86b7db76dab9d8486418ae639352cbd, BOOTSTRAP c1357cfba33b7f253f74f2e6b3bbb360465d427bc01f944c5410376df7865197, MANIFEST e5dad90670ab57206d944baafe51f66a06fa60deb439fbc648667fdb2229fcfc, CORE fbe51e299c4100bf2cf86d58d47849bdc794c8fd562185e2a82166cb21b4d10c.
- New src/raif_ag_supervisor/identity_observer.py provides a guarded local-only GetUserStatus read, fixed 256 KiB maximum, two-second timeout, explicit opt-in and fresh caller-supplied LS ownership check. No automatic process discovery, credential access or account switching.
- Returns only fixed verdict codes and userStatus/planInfo presence booleans, no raw payload, CSRF, email, access/refresh tokens or account handles. account_identity_verified=false, matched_account_id=null, eligible_for_pool=false on all paths.
- Eleven synthetic offline tests PASS against exact existing native_rpc.py blob 4fd8cf92eba6b9f69b36ce654050386130c860c4; cover oversized response, ambiguity, privacy, owner-mismatch, explicit opt-in and no inferred binding. Linux sandbox is not Windows host.
- No live RPC, provider, native credentials, CI or processes were called from local tests. No repeat of CP31, CP46, CP52D, CP54A5, CP54B1.

## Known unknowns
- Presence of userStatus/planInfo is not independent identity proof, and the RAiF Registry only holds opaque account IDs.
- Earlier GetUserStatus exceeded 16 KiB. A 256 KiB bound is synthetic-tested, not real provider evidence.
- Internal Connect RPC is not a documented stable public API.
- GitHub main and Tower authority unchanged; PR #29 is pointer-only and remains OPEN.
- Fabric 10.1B / WINDOWS_HOST_ACCEPTANCE remains HOST_NOT_RUN.
- Windows Desktop Commander service reported a monthly usage cap; no files written to actual D:\ЗАГРУЗКИ and no Windows host runtime claimed.

## Gates and next cursor
G2-B3-SYNTHETIC_OBSERVER=PASS_LOCAL_11_OF_11.
G2-B3-WINDOWS_HOST_SYNTHETIC=PENDING.
G2-B3-LIVE_IDENTITY_BINDING=UNKNOWN. If no independent approved local comparison exists, conclude IDENTITY_UNVERIFIED/UNSUPPORTED.
All future Windows runtime, script, ZIP and RESULT only D:\ЗАГРУЗКИ, existing C:\GIT\Rassvet_AI_Fabric clone read-only.
Current: AG_pather / CP-54B3 / BOUNDED_OBSERVER_SOURCE_SYNTHETIC_DONE.
Next: CP-54B3 / WINDOWS_OFFLINE_SYNTHETIC_RESULT_READBACK → EXPLICIT_G2_IDENTITY_READ_GATE.
Parallel: Fabric 10.1B / WINDOWS_HOST_ACCEPTANCE.
No live identity read, account switching, OAuth, rollback, merge, Tower/Router/BPR40/CKS authority changes or CI re-run without separate gate.
