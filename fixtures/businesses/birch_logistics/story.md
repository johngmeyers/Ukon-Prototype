# Birch Logistics (synthetic) — EDR gap and untested backups

A 30-person freight broker. The owner filled out the application from memory. Two answers are wrong in ordinary ways:

- **EDR:** they claim CrowdStrike is on all endpoints, but the console shows it active on 47 of 50 devices. Two new laptops (BIRCH-WS17, BIRCH-WS33) never got the agent, and BIRCH-WS41's sensor has been offline for 41 days.
- **Restore test:** they claim restores are tested, but the backup log shows only backup jobs. The MSP notes say no test restore has been done since moving to Datto in 2024.

Everything else checks out. Backups include a weekly offline USB rotation, Duo protects the VPN, and Mimecast filters email. Critical patches take at most 21 days; the application claims 30. The owner says no to an IR plan, which is an honest answer but still unverifiable.

## Expected statuses

| Control | Claim | Evidence | Expected |
|---|---|---|---|
| mfa_email | yes | 30/30 users enforced | supported |
| mfa_remote_access | yes | notes: Duo on SonicWall VPN | supported |
| mfa_privileged | yes | 2/2 admins enforced | supported |
| edr_all_endpoints | yes | 47/50 active (94%) | contradicted |
| backups_offline_immutable | yes | weekly offline USB rotation | supported |
| backup_restore_tested | yes | no restore test in log; notes confirm none since 2024 | contradicted |
| critical_patch_days | 30 | max 21 days | supported |
| email_filtering | yes | notes: Mimecast | supported |
| security_awareness_training | yes | none | unverifiable |
| incident_response_plan | no | none | unverifiable |
