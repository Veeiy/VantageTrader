Head failover line (P012). Every head instruction in this folder starts with this sentence, and the stored prompt of each task repeats it.

```text
FAILOVER (P012, docs/earnings/FAILOVER.md): before anything else run `git pull --rebase origin ccr-ada2dc9a-o9lbyl` and `PYTHONPATH=src python -m vantage_trader.earnings lease take --role head --session session_018FLvMEhsok7fEKo5QjYahD`; commit and push state/earnings/trader_lease.json if it changed. Exit code 5 means the standby holds today's lease: place no orders today, tell Brad, read what the standby did, and stop.
```
