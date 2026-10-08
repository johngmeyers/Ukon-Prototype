# Acme Dental (synthetic) — the clean case

A 12-person dental practice. The office manager filled out the application with the MSP on the phone, and every answer matches the environment.

- MFA enforced for all 12 staff and both admin accounts in M365.
- VPN (FortiClient) signs in through Entra ID, and Conditional Access requires MFA. RDP is not exposed.
- SentinelOne is active on all 14 devices.
- Veeam backs up to a local NAS plus an immutable Wasabi copy (30-day object lock). A restore test passed on 2026-06-12.
- Critical patches are deployed in 9 days at most; the application claims 14.
- Defender for Office 365 filters email.
- Training and IR plan are claimed but no evidence source exists.

## Expected statuses

| Control | Claim | Evidence | Expected |
|---|---|---|---|
| mfa_email | yes | 12/12 users enforced | supported |
| mfa_remote_access | yes | notes: VPN via Entra + CA MFA | supported |
| mfa_privileged | yes | 2/2 admins enforced | supported |
| edr_all_endpoints | yes | 14/14 active | supported |
| backups_offline_immutable | yes | immutable Wasabi copy | supported |
| backup_restore_tested | yes | restore test 2026-06-12 | supported |
| critical_patch_days | 14 | max 9 days | supported |
| email_filtering | yes | notes: Defender for O365 | supported |
| security_awareness_training | yes | none | unverifiable |
| incident_response_plan | yes | none | unverifiable |
