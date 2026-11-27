# Personal data breach response plan

For the shop running Smart Inventory. Kenya Data Protection Act, 2019 (sections 43 and 44)
and the Data Protection (General) Regulations, 2021. Keep a printed copy near the server.

A **breach** is any loss, theft, leak, unauthorised access to or change of personal data:
for example a stolen laptop or backup disk, a staff password used by someone else, records
exported without permission, a ransomware attack, or a server reachable from the internet
without protection.

## Who does what

| Role | Person (fill in) | Phone |
|---|---|---|
| Breach lead (decides, informs the Commissioner) | Owner / Store Manager | |
| Technical lead (contains, investigates) | Super Administrator / IT support | |
| Data protection contact (from the privacy notice) | `PRIVACY_CONTACT` | |

## Steps and time limits

1. **Report at once (hour 0).** Anyone who suspects a breach tells the breach lead
   immediately. Do not delete anything; note the time and what was seen.
2. **Contain (first hours).** Technical lead, as needed:
   - deactivate the affected accounts, or sign them out everywhere (Administration → Users →
     *Sign out everywhere*), and issue new passwords;
   - if a server secret may be known, change `JWT_SECRET` (signs everyone out), the database
     passwords, `ANTHROPIC_API_KEY`, the M-Pesa keys and `PAPERLESS_TOKEN` in `.env`, then
     `docker compose up -d`;
   - disconnect the server from the internet if it is under attack;
   - if a backup disk or laptop is lost, list what it contained.
3. **Assess (within 24 hours).** Use the audit log (Administration → Audit log; filter by user,
   action and date) and `docker compose logs` to find out: what data, whose (staff,
   customers, suppliers), how many people, since when, and whether it is still happening.
   Decide whether there is a **real risk of harm** to the people affected (fraud, identity
   theft, loss of money, embarrassment).
4. **Notify the Data Protection Commissioner within 72 hours** of becoming aware, if there is
   a real risk of harm (odpc.go.ke). Give: what happened, the categories and approximate number
   of people and records, likely consequences, measures taken, and the contact person. If
   something is not yet known, report what is known and add the rest later.
5. **Tell the people affected without delay**, in plain language, if there is a real risk of
   harm: what happened, what data, what the shop has done, and what they should do (for
   example watch for fake M-Pesa messages, change a password). Do not do this if it would
   hinder a police investigation and the police ask you to wait.
6. **Recover.** Restore from the last good backup if data was changed or deleted
   (`make restore NAME=<backup>`, see the installation guide, section 4). Check that the
   restored data is correct before reopening.
7. **Record and learn (within 2 weeks).** Write down every breach, even small ones not
   reported: date, facts, effects, decisions and fixes. Keep these records. Fix the cause
   (training, stronger passwords, two-step sign-in for managers, server updates).

## Prevention already built in

- Passwords hashed with Argon2; optional two-step sign-in; account lockout after failed
  attempts; role-based access; audit log of every important action.
- Secrets only in the server's `.env` (never in the browser or in Git).
- Nightly verified backups; a restore procedure tested in the installation guide.
- Personal data erasure for former staff (Administration → Users → *Erase personal data*).
