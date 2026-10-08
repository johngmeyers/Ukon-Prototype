# Cedar Law (synthetic) — MFA claimed on remote access, VPN has none

An 18-person law firm. The firm administrator filled out the application, reusing an answer from last year's renewal: "MFA is required for email and VPN."

- **Remote access:** the SonicWall SSL-VPN authenticates against local firewall accounts with no MFA, and partners connect from home through it. The MSP notes say a Duo quote is pending. The M365 report shows only that MFA is enforced in Entra ID, which says nothing about the VPN. That is why this evidence comes from the MSP notes.
- Email MFA is enforced for all 18 users and both admin accounts.
- Defender for Endpoint is active on all 22 devices.
- Acronis backs up to immutable cloud storage, and a restore test passed on 2026-03-04.
- Critical patches take at most 12 days; the application claims 14.
- Proofpoint Essentials filters email.

## Expected statuses

| Control | Claim | Evidence | Expected |
|---|---|---|---|
| mfa_email | yes | 18/18 users enforced | supported |
| mfa_remote_access | yes | notes: VPN uses local accounts, no MFA | contradicted |
| mfa_privileged | yes | 2/2 admins enforced | supported |
| edr_all_endpoints | yes | 22/22 active | supported |
| backups_offline_immutable | yes | Acronis immutable storage | supported |
| backup_restore_tested | yes | restore test 2026-03-04 | supported |
| critical_patch_days | 14 | max 12 days | supported |
| email_filtering | yes | notes: Proofpoint Essentials | supported |
| security_awareness_training | yes | none | unverifiable |
| incident_response_plan | yes | none | unverifiable |
