# Complete v4 candidate workflow example

Run:

```powershell
.\env\Scripts\python.exe examples\run_v4_demo.py --output-dir demo-output
```

The command generates a matching dataset manifest, 45-metric G1–G6 measurement
package, judged Session, report config, JSON/HTML/PDF acceptance report, waiver,
and summary.  The synthetic G1 S1 result deliberately triggers section 13.2 rule
5, so the example also proves that an active waiver preserves the rejected
formal result.

All names and signoffs are marked `DEMO ONLY`.  This demonstrates the data
contracts and workflow; it is not production evidence and does not satisfy the
three-party release-review gate.
